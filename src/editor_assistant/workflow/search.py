"""Search reliability foundation (M2S Track S): a real SearchProvider contract.

The audit found the largest architectural gap: the product had a research data
model (SourceBundle) but no stable search execution layer - discovery lived in
ad-hoc harness behavior (Bing consent pages, BTA 429s, silent fallbacks).
This module gives discovery a stable, inspectable, stdlib-only contract:

* explicit failure taxonomy - infrastructure failure is never evidence that
  information does not exist, and never silently changes the editor request;
* result snippets are DISCOVERY_ONLY - they name candidate sources, they can
  never back a promoted fact (the SourceBundle provenance rule stays);
* capability-based provider stack (M2S-R2): NEWS -> Google News RSS / DDGS /
  Serper / Brave; WEB -> Serper / DDGS / Brave; BACKGROUND -> Wikipedia API.
  Every adapter speaks the same SearchProvider contract and the same failure
  taxonomy. Consumer Bing/Google HTML scraping remains NOT a production path;
* no secrets in any log or record - keys are read from the environment and
  never persisted.

Design boundary: this module performs discovery and page opening. It does not
touch SourceBundle semantics (research.py keeps that contract) and does not
touch editorial judgments.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.sources import web_fetch

SEARCH_OK = "SEARCH_OK"
SEARCH_CAPABILITY_UNAVAILABLE = "SEARCH_CAPABILITY_UNAVAILABLE"
SEARCH_PROVIDER_ERROR = "SEARCH_PROVIDER_ERROR"
RATE_LIMITED = "RATE_LIMITED"
NO_RESULTS = "NO_RESULTS"
QUERY_EXHAUSTED = "QUERY_EXHAUSTED"

SEARCH_STATUSES = (
    SEARCH_OK,
    SEARCH_CAPABILITY_UNAVAILABLE,
    SEARCH_PROVIDER_ERROR,
    RATE_LIMITED,
    NO_RESULTS,
    QUERY_EXHAUSTED,
)

# Semantic-request constraint preservation (audit A7 / harness A7): a failed
# provider or source must never silently change the class of the editor task.
CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"
SEARCH_COMPLETE = "SEARCH_COMPLETE"

MAX_PROVIDER_ATTEMPTS = 2  # harness A5: bounded, never a scheduler
SEARCH_RUNS_DIR = Path(__file__).resolve().parents[3] / "var" / "editorial_workflow" / "search_runs"


class SearchError(ValueError):
    pass


# ---------- semantic editor-request constraints (harness A7) ----------


def make_constraints(*, description, required_domains=(), freshness=None, location=None):
    """Record what the editor actually asked for, before any searching.

    A fallback candidate may be used only when it still satisfies every
    recorded constraint; otherwise the operation must report SEARCH_INCOMPLETE.
    """
    return {
        "description": description,
        "required_domains": [d.lower() for d in required_domains],
        "freshness": freshness or "",
        "location": location or "",
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def constraints_satisfied(constraints, candidate_url):
    """True when a fallback candidate still matches the original request."""
    domains = (constraints or {}).get("required_domains") or []
    if not domains:
        return True
    host = (urllib.parse.urlparse(candidate_url or "").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def evaluate_operation(constraints, candidates):
    """SEARCH_COMPLETE only if >=1 candidate satisfies the constraints.

    Never silently substitutes a different semantic class (audit A7: the BTA
    429 -> municipality-calendar switch changed the experiment).
    """
    satisfied = [c for c in candidates if constraints_satisfied(constraints, c.get("url", ""))]
    if satisfied:
        return {"status": SEARCH_COMPLETE, "satisfied_candidates": satisfied}
    return {
        "status": SEARCH_INCOMPLETE,
        "satisfied_candidates": [],
        "reason": (
            "ниеден кандидат не удовлетворява записаните ограничения на редакторското "
            f"задание ({(constraints or {}).get('description', '')}); инфраструктурен "
            "провал не се превръща в редакторско 'няма материал'"
        ),
    }


# ---------- query planning (harness A8) ----------

_AGENDA_CUE = re.compile(
    r"програма|час[а-я]*|начало|вход|цени|участниц[а-я]*|формат|адрес|седмиц[а-я]*",
    re.IGNORECASE,
)


def plan_queries(*, topic, missing_dimensions=(), research_questions=(), location="Бургас"):
    """1-3 targeted queries per round from the missing semantics (gap-driven).

    Regression guidance only - no entity is ever encoded here (harness A8).
    """
    base = " ".join(str(topic).split())
    queries = []
    if base:
        queries.append(f"{base} {location}".strip())
    if any(_AGENDA_CUE.search(str(d)) for d in missing_dimensions) or any(
        _AGENDA_CUE.search(str(q)) for q in research_questions
    ):
        queries.append(f"{base} програма вход")
    if missing_dimensions:
        extra = " ".join(str(d).replace("_", " ") for d in missing_dimensions[:2])
        queries.append(f"{base} {extra}".strip())
    # dedupe, keep order, cap at 3
    seen, out = set(), []
    for q in queries:
        q = " ".join(q.split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:3]


# ---------- provider contract ----------


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SearchProvider:
    """One inspectable method: search(query) -> normalized outcome record.

    Implementations must never fabricate results and never log credentials.
    """

    name = "abstract"

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        raise NotImplementedError

    def _empty(self, query, count):
        """Normalized outcome skeleton shared by every provider adapter."""
        return {
            "provider": self.name,
            "query": query,
            "requested_count": count,
            "started_at": _utcnow(),
            "status": SEARCH_PROVIDER_ERROR,
            "attempt": 0,
            "http_status": None,
            "retry_after": None,
            "elapsed_ms": None,
            "results": [],
        }


class BraveSearchProvider(SearchProvider):
    """Brave Search API adapter (stdlib urllib, no new dependency)."""

    name = "brave"
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key, *, timeout=15):
        if not api_key or not api_key.strip():
            raise SearchError("BraveSearchProvider requires an API key")
        self._api_key = api_key.strip()
        self._timeout = timeout

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        record = self._empty(query, count)
        params = {
            "q": query,
            "count": str(min(int(count), 20)),
            "country": country,
            "search_lang": search_language,
            "safesearch": "off",
        }
        if freshness:
            params["freshness"] = freshness  # pd / pw / pm / py
        url = self.ENDPOINT + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": self._api_key,
            },
        )
        started = time.monotonic()
        for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
            record["attempt"] = attempt
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                    status = resp.status
                    payload = json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
                break
            except urllib.error.HTTPError as exc:
                retry_after = (exc.headers or {}).get("Retry-After")
                record["http_status"] = exc.code
                record["retry_after"] = retry_after
                if exc.code == 429 and attempt < MAX_PROVIDER_ATTEMPTS:
                    time.sleep(min(float(retry_after or 0), 5.0) or 1.0)
                    continue
                record["status"] = RATE_LIMITED if exc.code == 429 else SEARCH_PROVIDER_ERROR
                record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                return record
            except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
                record["status"] = SEARCH_PROVIDER_ERROR
                record["error"] = f"{type(exc).__name__}"
                record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                return record
        else:
            record["status"] = SEARCH_PROVIDER_ERROR
            return record

        record["http_status"] = status
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        results = []
        for item in (payload.get("web") or {}).get("results", [])[:count]:
            results.append(
                {
                    "rank": len(results) + 1,
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                    "published_at": (item.get("age") or item.get("page_age") or ""),
                    "source_name": (item.get("meta_url") or {}).get("hostname", ""),
                }
            )
        record["results"] = results
        record["status"] = SEARCH_OK if results else NO_RESULTS
        return record


# ---------- search operation: plan -> provider -> open candidates ----------


def run_search_operation(
    *,
    topic,
    constraints,
    missing_dimensions=(),
    research_questions=(),
    provider=None,
    page_opener=None,
    max_open=3,
    audit_path=None,
    env=None,
    capability="WEB",
):
    """One targeted research round: plan -> search -> open satisfying pages.

    Provider snippets are discovery-only; every selected URL is opened with the
    generic fetcher, and only opened pages can later become evidence through
    the existing SourceBundle contract. The whole operation is auditable.
    """
    if provider is not None:
        chain = [provider]
        unavailable = []
    else:
        chain, unavailable = provider_chain(capability=capability, env=env)
    operation = {
        "topic": topic,
        "constraints": constraints,
        "started_at": _utcnow(),
        "capability": capability,
        "provider_chain": [p.name for p in chain],
        "providers_unavailable": unavailable,
        "provider_status": SEARCH_OK if chain else SEARCH_CAPABILITY_UNAVAILABLE,
        "queries": [],
        "candidates": [],
        "status": SEARCH_INCOMPLETE,
    }
    if not chain:
        operation["failure"] = SEARCH_CAPABILITY_UNAVAILABLE
        operation["reason"] = "няма наличен доставчик за търсенето (SEARCH_PROVIDER/capability)"
        _audit(audit_path, operation)
        return operation

    queries = plan_queries(
        topic=topic,
        missing_dimensions=missing_dimensions,
        research_questions=research_questions,
        location=constraints.get("location") or "Бургас",
    )
    if not queries:
        queries = [topic]
    aggregated = []
    chain_fallbacks = []
    for query in queries:
        outcome = None
        for candidate_provider in chain:
            try:
                attempt = candidate_provider.search(query)
            except SearchError:  # provider unusable at call time (e.g. package missing)
                chain_fallbacks.append(f"{candidate_provider.name}:{SEARCH_CAPABILITY_UNAVAILABLE}")
                continue
            operation["queries"].append({k: v for k, v in attempt.items()})
            if attempt["status"] == SEARCH_OK and attempt["results"]:
                outcome = attempt
                break
            # RATE_LIMITED / PROVIDER_ERROR / NO_RESULTS: try the next provider in
            # the chain; each attempt stays inside its own bounded retry policy.
            chain_fallbacks.append(f"{candidate_provider.name}:{attempt['status']}")
        if outcome is not None:
            aggregated.extend(outcome["results"])
    if chain_fallbacks:
        operation["chain_fallbacks"] = chain_fallbacks
    if not aggregated:
        any_no_results = any(q["status"] == NO_RESULTS for q in operation["queries"])
        operation["failure"] = NO_RESULTS if any_no_results else QUERY_EXHAUSTED
        operation["reason"] = (
            "provider-ът не върна резултати (NO_RESULTS)"
            if any_no_results
            else "заявките не дадоха използваеми резултати (QUERY_EXHAUSTED)"
        )
        _audit(audit_path, operation)
        return operation

    seen_urls = set()
    for result in aggregated:
        url = result.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if not constraints_satisfied(constraints, url):
            continue
        if len(operation["candidates"]) >= max_open:
            break
        candidate = {
            "title": result.get("title", ""),
            "url": url,
            "snippet": result.get("snippet", ""),
            "snippet_authority": "DISCOVERY_ONLY",
            "opened": None,
        }
        try:
            page = (page_opener or web_fetch.fetch_page)(url)
            candidate["opened"] = {
                "status": web_fetch.FETCH_OK,
                "final_url": page["final_url"],
                "content_type": page["content_type"],
                "bytes": page["bytes"],
            }
        except web_fetch.WebFetchError as exc:
            candidate["opened"] = {
                "status": exc.category,
                "detail": exc.detail,
                "http_status": exc.status,
                "retry_after": exc.retry_after,
            }
        operation["candidates"].append(candidate)
    verdict = evaluate_operation(constraints, operation["candidates"])
    operation["status"] = verdict["status"]
    if verdict["status"] == SEARCH_INCOMPLETE:
        operation["reason"] = verdict.get("reason")
    _audit(audit_path, operation)
    return operation


def _audit(path, operation):
    """Append-only search audit; never stores credentials (harness A10)."""
    target = Path(path) if path else SEARCH_RUNS_DIR / f"run-{_utcnow().replace(':', '')}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(operation, ensure_ascii=False, sort_keys=True) + "\n")
    return target


# ---------- capability-based provider stack (M2S-R2) ----------

CAP_NEWS = "NEWS"  # fresh coverage / related reporting
CAP_WEB = "WEB"  # general web search
CAP_BACKGROUND = "BACKGROUND"  # encyclopedic context only, never current-event evidence
CAP_KNOWN_OFFICIAL = "KNOWN_OFFICIAL"  # direct fetch of a known institution source

PROVIDER_CAPABILITIES = {
    "google_news_rss": [CAP_NEWS],
    "serper": [CAP_WEB, CAP_NEWS],
    "ddgs": [CAP_WEB, CAP_NEWS],
    "brave": [CAP_WEB, CAP_NEWS],
    "wikipedia": [CAP_BACKGROUND],
    "direct_fetch": [CAP_KNOWN_OFFICIAL],
}

# Config-driven preference order per capability (Round-2 decision). An explicit
# SEARCH_PROVIDER env pins a single provider instead of the full chain.
PROVIDER_ORDER = {
    CAP_NEWS: ["google_news_rss", "serper", "ddgs", "brave"],
    CAP_WEB: ["serper", "ddgs", "brave"],
    CAP_BACKGROUND: ["wikipedia", "serper", "ddgs"],
    CAP_KNOWN_OFFICIAL: ["direct_fetch", "serper", "ddgs"],
}

_FRESHNESS_RSS = {"pd": "1d", "pw": "7d", "pm": "1m", "py": "1y"}


def _load_ddgs():
    """Import the approved optional dependency; None when unavailable."""
    try:
        from ddgs import DDGS
    except ImportError:
        return None
    return DDGS


class GoogleNewsRSSProvider(SearchProvider):
    """news.google.com RSS - best-effort, keyless news discovery.

    Results arrive through Google News redirect URLs and stay DISCOVERY_ONLY
    (audit A9): the publisher page must be opened before anything can become
    evidence. A zero-result feed means "this provider returned no candidates",
    never "the news does not exist".
    """

    name = "google_news_rss"
    TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=bg&gl=BG&ceid=BG:bg"

    def __init__(self, *, timeout=15):
        self._timeout = timeout

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        record = self._empty(query, count)
        effective = query
        if freshness:
            effective = f"{query} when:{_FRESHNESS_RSS.get(freshness, '')}".strip()
        feed_url = self.TEMPLATE.format(query=urllib.parse.quote_plus(effective))
        record["feed_url"] = feed_url
        started = time.monotonic()
        request = urllib.request.Request(
            feed_url,
            headers={
                "User-Agent": web_fetch.USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                status = resp.status
                body = resp.read(1_000_000)
        except urllib.error.HTTPError as exc:
            record["http_status"] = exc.code
            record["status"] = RATE_LIMITED if exc.code == 429 else SEARCH_PROVIDER_ERROR
            record["retry_after"] = (exc.headers or {}).get("Retry-After")
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            record["status"] = SEARCH_PROVIDER_ERROR
            record["error"] = type(exc).__name__
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record
        record["http_status"] = status
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            record["status"] = SEARCH_PROVIDER_ERROR
            record["error"] = "rss parse failed"
            return record
        results = []
        for item in root.findall("./channel/item")[:count]:

            def _text(tag, _item=item):
                node = _item.find(tag)
                return (node.text or "").strip() if node is not None else ""

            results.append(
                {
                    "rank": len(results) + 1,
                    "title": _text("title"),
                    "url": _text("link"),
                    "snippet": _text("description"),
                    "published_at": _text("pubDate"),
                    "source_name": _text("source"),
                }
            )
        record["results"] = results
        record["status"] = SEARCH_OK if results else NO_RESULTS
        return record


class DDGSProvider(SearchProvider):
    """DDGS adapter over the approved optional `ddgs` package (multi-backend).

    Zero-signup fallback; unofficial surfaces, so it never serves as the only
    dependency - it sits last in the WEB/NEWS chains by design.
    """

    name = "ddgs"

    def __init__(self, ddgs_factory=None, *, timeout=20):
        client_cls = (ddgs_factory or _load_ddgs)()
        if client_cls is None:
            raise SearchError("ddgs package is not installed (approved optional dependency)")
        self._client = client_cls(timeout=timeout)

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        record = self._empty(query, count)
        started = time.monotonic()
        try:
            raw = self._client.text(
                query,
                region="bg-bg",
                max_results=min(int(count), 20),
            )
        except Exception as exc:  # noqa: BLE001 - ddgs raises varied per-backend errors
            record["status"] = SEARCH_PROVIDER_ERROR
            record["error"] = type(exc).__name__
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        results = []
        for item in list(raw or [])[:count]:
            url = item.get("href", "")
            results.append(
                {
                    "rank": len(results) + 1,
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("body", ""),
                    "published_at": item.get("date", "") or "",
                    "source_name": urllib.parse.urlparse(url).hostname or "",
                }
            )
        record["results"] = results
        record["status"] = SEARCH_OK if results else NO_RESULTS
        return record


class WikipediaBackgroundProvider(SearchProvider):
    """Official MediaWiki search API - BACKGROUND capability only.

    Good for stable context (institution, person, place); never for
    current-event evidence.
    """

    name = "wikipedia"
    TEMPLATE = "https://bg.wikipedia.org/w/api.php"

    def __init__(self, *, timeout=15):
        self._timeout = timeout

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        record = self._empty(query, count)
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(min(int(count), 20)),
            "format": "json",
            "origin": "*",
        }
        url = self.TEMPLATE + "?" + urllib.parse.urlencode(params)
        started = time.monotonic()
        request = urllib.request.Request(
            url, headers={"User-Agent": web_fetch.USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                status = resp.status
                payload = json.loads(resp.read(1_000_000).decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            record["http_status"] = exc.code
            record["status"] = RATE_LIMITED if exc.code == 429 else SEARCH_PROVIDER_ERROR
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            record["status"] = SEARCH_PROVIDER_ERROR
            record["error"] = type(exc).__name__
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record
        record["http_status"] = status
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        results = []
        for item in (payload.get("query") or {}).get("search", [])[:count]:
            title = item.get("title", "")
            results.append(
                {
                    "rank": len(results) + 1,
                    "title": title,
                    "url": "https://bg.wikipedia.org/wiki/"
                    + urllib.parse.quote(title.replace(" ", "_")),
                    "snippet": re.sub(r"<[^>]+>", "", item.get("snippet", "")),
                    "published_at": item.get("timestamp", "") or "",
                    "source_name": "bg.wikipedia.org",
                }
            )
        record["results"] = results
        record["status"] = SEARCH_OK if results else NO_RESULTS
        return record


class SerperProvider(SearchProvider):
    """Serper.dev adapter - Google SERP over an official API; key-gated.

    Free tier (2,500 queries, no card) covers the benchmark; top-up pricing
    afterwards. Activated only when SERPER_API_KEY is present in the env.
    """

    name = "serper"
    ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, api_key, *, timeout=15):
        if not api_key or not api_key.strip():
            raise SearchError("SerperProvider requires an API key")
        self._api_key = api_key.strip()
        self._timeout = timeout

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        record = self._empty(query, count)
        body = json.dumps(
            {"q": query, "num": min(int(count), 20), "gl": country, "hl": search_language}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.ENDPOINT,
            data=body,
            method="POST",
            headers={
                "X-API-KEY": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        started = time.monotonic()
        for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
            record["attempt"] = attempt
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                    status = resp.status
                    payload = json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
                break
            except urllib.error.HTTPError as exc:
                retry_after = (exc.headers or {}).get("Retry-After")
                record["http_status"] = exc.code
                record["retry_after"] = retry_after
                if exc.code == 429 and attempt < MAX_PROVIDER_ATTEMPTS:
                    time.sleep(min(float(retry_after or 0), 5.0) or 1.0)
                    continue
                record["status"] = RATE_LIMITED if exc.code == 429 else SEARCH_PROVIDER_ERROR
                record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                return record
            except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
                record["status"] = SEARCH_PROVIDER_ERROR
                record["error"] = type(exc).__name__
                record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                return record
        else:
            record["status"] = SEARCH_PROVIDER_ERROR
            return record
        record["http_status"] = status
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        results = []
        for item in (payload.get("organic") or [])[:count]:
            url = item.get("link", "")
            results.append(
                {
                    "rank": len(results) + 1,
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("date", "") or "",
                    "source_name": urllib.parse.urlparse(url).hostname or "",
                }
            )
        record["results"] = results
        record["status"] = SEARCH_OK if results else NO_RESULTS
        return record


def provider_chain(capability=CAP_WEB, env=None):
    """Ordered available providers for a capability; unavailable ones named.

    Returns (chain, unavailable_notes). Missing config is an explicit outcome,
    never a fabricated result (harness A2/A3).
    """
    import os

    environment = env if env is not None else os.environ
    order = PROVIDER_ORDER.get(capability)
    if order is None:
        raise SearchError(f"unknown capability: {capability!r}")
    forced = (environment.get("SEARCH_PROVIDER") or "").strip().lower()
    chain, unavailable = [], []
    for name in order:
        if forced and forced != name:
            continue  # explicit SEARCH_PROVIDER pins a single provider
        if name == "brave":
            key = environment.get("BRAVE_SEARCH_API_KEY") or ""
            if key.strip():
                chain.append(BraveSearchProvider(key))
            else:
                unavailable.append("brave:no-key")
        elif name == "serper":
            key = environment.get("SERPER_API_KEY") or ""
            if key.strip():
                chain.append(SerperProvider(key))
            else:
                unavailable.append("serper:no-key")
        elif name == "ddgs":
            if _load_ddgs() is None:
                unavailable.append("ddgs:package-missing")
            else:
                try:
                    chain.append(DDGSProvider())
                except SearchError:
                    unavailable.append("ddgs:init-failed")
        elif name == "google_news_rss":
            chain.append(GoogleNewsRSSProvider())
        elif name == "wikipedia":
            chain.append(WikipediaBackgroundProvider())
    return chain, unavailable


# ---------- legacy single-provider resolution (M2S Track S; kept for compat) ----------


def resolve_provider(env=None):
    """Pick the configured single provider; missing config is an explicit outcome.

    Returns (provider_or_None, status). Never raises for missing config and
    never fabricates results in its absence.
    """
    import os

    environment = env if env is not None else os.environ
    name = (environment.get("SEARCH_PROVIDER") or "").strip().lower()
    if name in ("", "brave"):
        key = environment.get("BRAVE_SEARCH_API_KEY") or ""
        if not key.strip():
            return None, SEARCH_CAPABILITY_UNAVAILABLE
        return BraveSearchProvider(key), SEARCH_OK
    if name == "serper":
        key = environment.get("SERPER_API_KEY") or ""
        if not key.strip():
            return None, SEARCH_CAPABILITY_UNAVAILABLE
        return SerperProvider(key), SEARCH_OK
    if name == "ddgs":
        try:
            return DDGSProvider(), SEARCH_OK
        except SearchError:
            return None, SEARCH_CAPABILITY_UNAVAILABLE
    if name == "google_news_rss":
        return GoogleNewsRSSProvider(), SEARCH_OK
    if name == "wikipedia":
        return WikipediaBackgroundProvider(), SEARCH_OK
    raise SearchError(f"unknown SEARCH_PROVIDER: {name!r}")
