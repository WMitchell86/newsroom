"""Search reliability foundation (M2S Track S): a real SearchProvider contract.

The audit found the largest architectural gap: the product had a research data
model (SourceBundle) but no stable search execution layer - discovery lived in
ad-hoc harness behavior (Bing consent pages, BTA 429s, silent fallbacks).
This module gives discovery a stable, inspectable, stdlib-only contract:

* explicit failure taxonomy - infrastructure failure is never evidence that
  information does not exist, and never silently changes the editor request;
* result snippets are DISCOVERY_ONLY - they name candidate sources, they can
  never back a promoted fact (the SourceBundle provenance rule stays);
* capability-based provider stack (M2S-R2, reordered M2S-R4): NEWS ->
  Google News RSS / TinyFish / Serper / DDGS / Brave; WEB -> TinyFish /
  Serper / DDGS / Brave; BACKGROUND -> Wikipedia / TinyFish / Serper / DDGS.
  Every adapter speaks the same SearchProvider contract and the same failure
  taxonomy. Consumer Bing/Google HTML scraping remains NOT a production path;
* TinyFish Search/Fetch adapters (M2S-R3) - Search ADOPTED into the default
  PROVIDER_ORDER (M2S-R4, on measured benchmark data: 20/20 SEARCH_OK,
  7/7 known-answer, avg ~0.3s); Fetch stays AVAILABLE but NOT a default
  fetch fallback (narrow failure-category trigger only). Missing key
  degrades the chain explicitly (tinyfish:no-key), pin still supported via
  SEARCH_PROVIDER=tinyfish;
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
    # M2S-R3: registered and benchmarkable, but deliberately NOT inserted into
    # PROVIDER_ORDER below until the live benchmark justifies a routing change
    # (harness A8: do not change routing before benchmarking).
    "tinyfish": [CAP_WEB, CAP_NEWS],
}

# Config-driven preference order per capability (Round-2 decision). An explicit
# SEARCH_PROVIDER env pins a single provider instead of the full chain.
#
# M2S-R4 (routing decision on measured benchmark data): TinyFish is ADOPTED
# as the first general WEB provider and joins NEWS/BACKGROUND behind the
# keyless specialists (RSS for NEWS, Wikipedia for BACKGROUND). Evidence:
# var/search_benchmark/tinyfish_eval.json - 20/20 SEARCH_OK, 7/7 known-answer,
# avg ~0.3s vs the incumbent chain's 18/20 with same-day DDGS degradation.
# Serper/Brave stay key-gated members of the chain (they run only with keys).
# TinyFish FETCH is deliberately NOT promoted to a default fetch fallback
# (benchmark: no added value on the two live fallback cases); the adapter
# remains available via fetch_with_fallback's narrow failure-category trigger.
PROVIDER_ORDER = {
    CAP_NEWS: ["google_news_rss", "tinyfish", "serper", "ddgs", "brave"],
    CAP_WEB: ["tinyfish", "serper", "ddgs", "brave"],
    CAP_BACKGROUND: ["wikipedia", "tinyfish", "serper", "ddgs"],
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
    if forced and forced not in order:
        # A pinned provider missing from this capability's order is either a
        # typo or a capability mismatch: an explicit unavailability, never a
        # silent full-chain fallback. The tinyfish branch below stays as a
        # safety net for capability-specific builds (news -> news index).
        pinned = tinyfish_search_provider(capability, environment) if forced == "tinyfish" else None
        if pinned is not None:
            return [pinned], []
        return [], [f"{forced}:unavailable"]
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
        elif name == "tinyfish":
            # M2S-R4: default-routed. A missing key degrades the chain
            # explicitly (tinyfish:no-key), never fabricating a result.
            provider = tinyfish_search_provider(capability, environment)
            if provider is None:
                unavailable.append("tinyfish:no-key")
            else:
                chain.append(provider)
    return chain, unavailable


# ---------- TinyFish adapters (M2S-R3 Part A) ----------

# Direct REST integration (no broker, no Monid in the runtime path): the
# SearchProvider contract is satisfied by a stdlib urllib call to the two
# public TinyFish endpoints. Docs: https://docs.tinyfish.ai
TINYFISH_SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
TINYFISH_FETCH_ENDPOINT = "https://api.fetch.tinyfish.ai"
TINYFISH_API_KEY_ENV = "TINYFISH_API_KEY"

# Provider metadata (harness A1) - recorded for audits, never treated as an
# immutable product assumption. Search 30 req/min; Fetch 150 URLs/min.
TINYFISH_LIMITS = {
    "search_requests_per_minute": 30,
    "fetch_urls_per_minute": 150,
    "fetch_urls_per_request": 10,
}

# Harness A7: the source-level taxonomy the rest of the product understands.
SOURCE_ACCESS_BLOCKED = "SOURCE_ACCESS_BLOCKED"
SOURCE_FETCH_FAILED = "SOURCE_FETCH_FAILED"
SOURCE_PARSE_FAILED = "SOURCE_PARSE_FAILED"

# web_fetch category -> source taxonomy. Blocked targets are access problems;
# transport/HTTP/timeout are fetch problems; unusable/empty extraction is a
# parse problem. Infrastructure failure is NEVER NO_RESULTS.
_SOURCE_CATEGORY_MAP = {
    web_fetch.FETCH_BLOCKED_TARGET: SOURCE_ACCESS_BLOCKED,
    web_fetch.FETCH_HTTP_ERROR: SOURCE_FETCH_FAILED,
    web_fetch.FETCH_UNREACHABLE: SOURCE_FETCH_FAILED,
    web_fetch.FETCH_TIMEOUT: SOURCE_FETCH_FAILED,
    web_fetch.FETCH_UNSUPPORTED_CONTENT: SOURCE_PARSE_FAILED,
    web_fetch.FETCH_PARSE_FAILED: SOURCE_PARSE_FAILED,
    web_fetch.FETCH_TOO_LARGE: SOURCE_PARSE_FAILED,
}


def source_failure_category(category):
    """Map an internal fetch failure into the harness source taxonomy."""
    return _SOURCE_CATEGORY_MAP.get(category, SOURCE_FETCH_FAILED)


# Freshness -> recency_minutes (TinyFish takes minutes, not freshness codes).
_FRESHNESS_MINUTES = {"pd": 1440, "pw": 10080, "pm": 43200, "py": 525600}


class TinyFishSearchProvider(SearchProvider):
    """TinyFish Search adapter (stdlib urllib, official REST API).

    Free at $0 wallet balance, no card required; `X-API-Key` auth. Key-gated
    like the other keyed adapters: a missing key is an explicit
    SEARCH_CAPABILITY_UNAVAILABLE at chain-build time, never a fabricated
    result. Snippets stay DISCOVERY_ONLY (the caller sets `snippet_authority`;
    nothing here can promote a snippet to evidence).

    The API exposes no result-count parameter (only `page` 0..10), so `count`
    is applied to the normalized response and `count_param_ignored` is recorded
    instead of pretending the provider honoured it.
    """

    name = "tinyfish"

    def __init__(self, api_key, *, timeout=20, domain_type="web"):
        if not api_key or not api_key.strip():
            raise SearchError("TinyFishSearchProvider requires an API key")
        if domain_type not in ("web", "news", "research_paper"):
            raise SearchError(f"unsupported domain_type: {domain_type!r}")
        self._api_key = api_key.strip()
        self._timeout = timeout
        self.domain_type = domain_type

    def search(
        self,
        query,
        *,
        count=10,
        country="bg",
        search_language="bg",
        freshness=None,
        purpose=None,
        after_date=None,
        before_date=None,
        include_domains=None,
        exclude_domains=None,
        page=0,
    ):
        record = self._empty(query, count)
        record["count_param_ignored"] = True  # provider exposes no count param
        guard_public_query(query)
        params = {
            "query": query,
            "location": (country or "bg").upper(),
            "language": search_language or "bg",
            "domain_type": self.domain_type,
            "page": str(int(page)),
        }
        if purpose:
            params["purpose"] = guard_public_query(purpose)
        if freshness and _FRESHNESS_MINUTES.get(freshness):
            params["recency_minutes"] = str(_FRESHNESS_MINUTES[freshness])
        if after_date:
            params["after_date"] = after_date
        if before_date:
            params["before_date"] = before_date
        for key, value in (
            ("include_domains", include_domains),
            ("exclude_domains", exclude_domains),
        ):
            if value:
                params[key] = value if isinstance(value, str) else ",".join(value)
        url = TINYFISH_SEARCH_ENDPOINT + "?" + urllib.parse.urlencode(params)
        record["endpoint"] = TINYFISH_SEARCH_ENDPOINT
        record["requested_location"] = params["location"]
        record["requested_language"] = params["language"]
        record["requested_domain_type"] = self.domain_type
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "X-API-Key": self._api_key,
                "Accept": "application/json",
                "User-Agent": web_fetch.USER_AGENT,
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
                record["error_code"] = _tinyfish_error_code(exc)
                if exc.code == 429 and attempt < MAX_PROVIDER_ATTEMPTS:
                    time.sleep(min(float(retry_after or 0), 5.0) or 1.0)
                    continue
                # 429/402/403/outage is a capability problem - never NO_RESULTS.
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
        for item in (payload.get("results") or [])[:count]:
            result_url = item.get("url", "")
            results.append(
                {
                    "rank": int(item.get("position") or len(results) + 1),
                    "title": item.get("title", ""),
                    "url": result_url,
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("date", "") or "",
                    "source_name": item.get("site_name")
                    or urllib.parse.urlparse(result_url).hostname
                    or "",
                    "publisher": item.get("publisher", "") or "",
                }
            )
        record["results"] = results
        record["total_results"] = payload.get("total_results")
        record["page"] = payload.get("page", page)
        record["status"] = SEARCH_OK if results else NO_RESULTS
        return record


def _tinyfish_error_code(exc):
    """Provider error code from an HTTPError body, when present."""
    try:
        payload = json.loads(exc.read(200_000).decode("utf-8", "replace"))
    except (AttributeError, ValueError, OSError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    return error.get("code") if isinstance(error, dict) else None


def tinyfish_search_provider(capability=CAP_WEB, env=None):
    """TinyFish search adapter from the environment; None is an explicit state.

    domain_type follows the requested capability (news -> news index), so the
    benchmark can compare the same query class against the incumbent chain.
    """
    import os

    environment = env if env is not None else os.environ
    key = (environment.get(TINYFISH_API_KEY_ENV) or "").strip()
    if not key:
        return None
    domain_type = "news" if capability == CAP_NEWS else "web"
    return TinyFishSearchProvider(key, domain_type=domain_type)


# ---------- privacy guard (harness A6) ----------

# Anything that looks like raw caption/transcript material must never leave the
# machine for a third party. TinyFish may receive a public search query and a
# public URL - never draft text, editor notes, or transcript bodies.
_TRANSCRIPT_MARKER = re.compile(
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b|\b\d+\s*(?:seconds?|минути|секунди)\b"
    r"|\[музика\]|субтитри|auto[- ]?caption|транскрипт",
    re.IGNORECASE,
)
PUBLIC_TEXT_LIMIT = 400  # a public query/purpose is a phrase, not a document


class PrivacyGuardError(SearchError):
    pass


def guard_public_query(text, *, limit=PUBLIC_TEXT_LIMIT):
    """Reject outbound text that is not a public search phrase (harness A6).

    Guards against pasting transcript bodies / draft prose / editor notes into
    a third-party query or purpose field. Deterministic and cheap: length plus
    caption-artifact markers (cue clocks, caption vocabulary).
    """
    value = str(text or "")
    if not value.strip():
        raise PrivacyGuardError("empty public text")
    if len(value) > limit:
        raise PrivacyGuardError(
            f"outbound text exceeds the public-phrase limit ({len(value)} > {limit} chars)"
        )
    if _TRANSCRIPT_MARKER.search(value):
        raise PrivacyGuardError("outbound text looks like transcript/caption material")
    return value


def guard_public_url(url):
    """Public http(s) URL only; private/loopback targets are never forwarded.

    Reuses the local SSRF guard so a third-party fetcher can never be pointed
    at internal infrastructure.
    """
    web_fetch.guard_target(url)
    return url


# ---------- TinyFish Fetch (harness A5) ----------

# Fallback triggers: only pages the local opener could not deliver. A blocked
# *target* is a security decision, never a reason to forward the URL.
FALLBACK_TRIGGER_CATEGORIES = (
    web_fetch.FETCH_HTTP_ERROR,
    web_fetch.FETCH_UNSUPPORTED_CONTENT,
    web_fetch.FETCH_PARSE_FAILED,
    web_fetch.FETCH_TIMEOUT,
    web_fetch.FETCH_UNREACHABLE,
)
NEVER_FORWARD_CATEGORIES = (web_fetch.FETCH_BLOCKED_TARGET,)
MIN_USABLE_TEXT = 200  # below this a local extraction counts as parse-empty


class TinyFishFetchProvider:
    """TinyFish Fetch adapter returning the local opened-source contract.

    `fetch(url)` produces the same plain record shape as
    `web_fetch.fetch_page`, so it is a drop-in fallback opener; failures raise
    `web_fetch.WebFetchError` with an existing category (or FETCH_PARSE_FAILED
    for an unusable extraction), so the product's failure taxonomy is unchanged.
    Free at $0 balance; 150 URLs/minute; up to 10 URLs per request.
    """

    name = "tinyfish_fetch"

    def __init__(self, api_key, *, timeout=30, format="markdown"):
        if not api_key or not api_key.strip():
            raise SearchError("TinyFishFetchProvider requires an API key")
        self._api_key = api_key.strip()
        self._timeout = timeout
        self.format = format

    def fetch(self, url, *, purpose=None, ttl=0, per_url_timeout_ms=None):
        results, errors = _tinyfish_fetch_request(
            self, [url], purpose=purpose, ttl=ttl, per_url_timeout_ms=per_url_timeout_ms
        )
        if results:
            return results[0]
        first = errors[0] if errors else {}
        detail = first.get("error") or "no result returned"
        raise web_fetch.WebFetchError(
            _tinyfish_fetch_category(first), f"tinyfish fetch failed for {url}: {detail}"
        )

    def fetch_many(self, urls, *, purpose=None, ttl=0):
        """Batch fetch (max 10 URLs); per-URL failures do not fail the batch."""
        if not urls:
            raise SearchError("fetch_many requires at least one URL")
        if len(urls) > TINYFISH_LIMITS["fetch_urls_per_request"]:
            raise SearchError(
                f"tinyfish fetch accepts at most {TINYFISH_LIMITS['fetch_urls_per_request']} URLs"
            )
        return _tinyfish_fetch_request(self, list(urls), purpose=purpose, ttl=ttl)


def _tinyfish_fetch_request(provider, urls, *, purpose=None, ttl=0, per_url_timeout_ms=None):
    """POST /fetch for 1..10 public URLs; returns (results, errors)."""
    for url in urls:
        guard_public_url(url)
    body = {"urls": list(urls), "format": provider.format, "ttl": int(ttl)}
    if purpose:
        # Only a short public statement ever leaves the machine (A6).
        body["purpose"] = guard_public_query(purpose)
    if per_url_timeout_ms:
        body["per_url_timeout_ms"] = int(per_url_timeout_ms)
    request = urllib.request.Request(
        TINYFISH_FETCH_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "X-API-Key": provider._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": web_fetch.USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=provider._timeout) as resp:
            payload = json.loads(resp.read(4_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise web_fetch.WebFetchError(
            web_fetch.FETCH_HTTP_ERROR,
            f"tinyfish fetch HTTP {exc.code}",
            status=exc.code,
            retry_after=(exc.headers or {}).get("Retry-After"),
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise web_fetch.WebFetchError(
            web_fetch.FETCH_UNREACHABLE, f"tinyfish fetch {type(exc).__name__}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise web_fetch.WebFetchError(
            web_fetch.FETCH_PARSE_FAILED, "tinyfish fetch returned invalid JSON"
        ) from exc
    results = []
    for item in payload.get("results") or []:
        text = item.get("text") or ""
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        if item.get("status") == "failed" or not text.strip():
            continue
        results.append(
            {
                "url": item.get("url", ""),
                "final_url": item.get("final_url", "") or item.get("url", ""),
                "status": 200,
                "content_type": "text/markdown" if provider.format == "markdown" else "text/html",
                "bytes": len(text.encode("utf-8")),
                "text": text,
                "title": item.get("title") or "",
                "language": item.get("language") or "",
                "published_at": item.get("published_date") or "",
                "extractor": provider.name,
            }
        )
    return results, list(payload.get("errors") or [])


def _tinyfish_fetch_category(error_entry):
    """Map a per-URL TinyFish error into an existing WebFetchError category."""
    text = str((error_entry or {}).get("error", "")).lower()
    if any(word in text for word in ("block", "forbidden", "403", "captcha", "denied")):
        return web_fetch.FETCH_HTTP_ERROR
    if "timeout" in text:
        return web_fetch.FETCH_TIMEOUT
    if any(word in text for word in ("empty", "parse", "extract", "content type", "unsupported")):
        return web_fetch.FETCH_PARSE_FAILED
    return web_fetch.FETCH_UNREACHABLE


def tinyfish_fetch_provider(env=None):
    """Build the TinyFish fetcher when configured; None is an explicit state."""
    import os

    environment = env if env is not None else os.environ
    key = (environment.get(TINYFISH_API_KEY_ENV) or "").strip()
    return TinyFishFetchProvider(key) if key else None


def fetch_with_fallback(
    url,
    *,
    local_opener=None,
    fallback=None,
    env=None,
    purpose=None,
    min_usable_text=MIN_USABLE_TEXT,
):
    """Open one public source: local fetcher first, TinyFish only as a fallback.

    Returns {source, opened, fallback_attempted, local_failure, failure_category}.
    Routing stays explicit and narrow (harness A5): the fallback runs only for
    failed/parse-empty local reads, never by default, and never for a blocked
    *target* (private/loopback stays blocked everywhere - it is a security
    decision, not a page-quality problem).
    """
    opener = local_opener or web_fetch.fetch_page
    record = {
        "url": url,
        "source": "local",
        "opened": None,
        "fallback_attempted": False,
        "local_failure": None,
        "failure_category": None,
    }
    try:
        page = opener(url)
        text = page.get("text") or ""
        if len(text.strip()) >= min_usable_text:
            record["opened"] = page
            return record
        record["local_failure"] = {
            "status": web_fetch.FETCH_PARSE_FAILED,
            "detail": f"local extraction near-empty ({len(text.strip())} chars)",
        }
    except web_fetch.WebFetchError as exc:
        record["local_failure"] = {
            "status": exc.category,
            "detail": exc.detail,
            "http_status": exc.status,
        }
        if exc.category in NEVER_FORWARD_CATEGORIES:
            record["failure_category"] = SOURCE_ACCESS_BLOCKED
            record["reason"] = "blocked target is never forwarded to a third party"
            return record

    local_status = record["local_failure"]["status"]
    record["failure_category"] = source_failure_category(local_status)
    if local_status not in FALLBACK_TRIGGER_CATEGORIES:
        return record
    provider = fallback if fallback is not None else tinyfish_fetch_provider(env)
    if provider is None:
        record["reason"] = f"no fallback fetcher configured ({TINYFISH_API_KEY_ENV} missing)"
        return record
    record["fallback_attempted"] = True
    try:
        page = provider.fetch(url, purpose=purpose)
    except web_fetch.WebFetchError as exc:
        record["fallback_failure"] = {"status": exc.category, "detail": exc.detail}
        record["failure_category"] = source_failure_category(exc.category)
        return record
    record["source"] = provider.name
    record["opened"] = page
    record["failure_category"] = None
    return record


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
