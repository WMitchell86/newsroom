"""V1.2-G4.2 §2/§3C — the Story's OWN publication is valid Draft material.

**The problem this fixes.** The owner pressed `Чернова` on a Story with a real
publication and got `NO_DRAFT_MATERIAL`. The Story was not empty: its canonical
Publication had a URL. What was missing was a durable *evidence basis*, because
older research runs opened the page, read claims out of it, and then discarded
them when the corroboration gate declined to promote them.

Concluding "there is nothing to write from" there was simply the wrong question.
The publication exists and can be read.

**What this is.** A bounded, safe read of the Story's representative Publication
that produces *source material for a work-in-progress Draft*. It is explicitly
**not** a fact promotion:

* nothing is written to `story_research_store`, so `basis["facts"]` stays empty
  and no gap is cleared;
* every extracted sentence keeps the page URL and a `claim:N` locator;
* the Draft that results is attributed and carries the single-source warning.

**Why it belongs here and not in Research.** Research answers *"is this
corroborated?"* and is allowed to say no. This answers *"is there readable
prose?"*, which is a different question, and it must not inherit Research's
quality bar — otherwise a Story can never be drafted without a research pass,
which is the loop the owner is trying to leave.

**Bounded on purpose.** One page per Story, the same fetch guards as research,
the same claim-quality filters (navigation chrome, boilerplate, tag clouds), and
a small cap. This is not a crawler and it never triggers a search.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from editor_assistant.sources import html_desc, web_fetch
from editor_assistant.workflow import blocked_domains, claim_quality
from editor_assistant.workflow import search as search_mod

#: Every network call in this module is bounded. A Draft command runs inside a
#: worker the editor is waiting on, so a slow provider must degrade to "no
#: material" rather than hang the button.
NETWORK_TIMEOUT = 12

#: The identifying words of a title, for matching a discovery record to it.
_TITLE_NOISE = re.compile(r"[^\w]+", re.UNICODE)

#: How many sentences one publication may contribute. Small on purpose: this is
#: a first draft's grounding, not a corpus.
MAX_CLAIMS = 6

#: Sentences shorter than this are navigation fragments, not propositions.
MIN_CLAIM_CHARS = 60

#: Never a local source: a Google News redirect is a wrapper, not a publisher.
_NON_PUBLISHER_HOSTS = frozenset(
    {
        "news.google.com",
        "google.com",
        "facebook.com",
        "fb.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "tiktok.com",
        "youtube.com",
        "youtu.be",
        "linkedin.com",
        "t.me",
        "telegram.me",
        "reddit.com",
    }
)

#: Hosts that are never the Story's own publication, whatever the URL says.
_SELF_HOSTS = ("chernomorie-bg.com",)


def is_readable_publication(url: str) -> bool:
    """Whether this URL is worth one bounded read.

    The same publisher test research uses, so a snippet or a social wrapper can
    never become Draft material — and this site's own domain, whose republication
    is the very thing a Draft must never be built from.
    """
    text = str(url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return False
    host = (urlsplit(text).hostname or "").lower()
    if not host:
        return False
    # Suffix, not equality: a social or aggregator wrapper is just as much a
    # wrapper at `www.facebook.com` as at `facebook.com`, and an exact match
    # let the `www.` form straight through as if it were a publisher.
    if any(host == bad or host.endswith("." + bad) for bad in _NON_PUBLISHER_HOSTS):
        return False
    if any(host == own or host.endswith("." + own) for own in _SELF_HOSTS):
        return False
    # The editor's own blocked-domain policy applies here exactly as it does to
    # Research. Enforcing it only downstream let a blocked publisher be READ and
    # then refused by the safety guard, which surfaced as `SAFETY_BLOCKED` — a
    # safety verdict about a URL we should never have fetched in the first place.
    return not blocked_domains.is_blocked(text)


def _title_key(text: str) -> frozenset[str]:
    """The identifying words of a title, for matching a discovery record to it."""
    return frozenset(
        word
        for word in _TITLE_NOISE.split(str(text or "").casefold())
        if len(word) > 3
    )


def _title_matches(left: str, right: str) -> bool:
    """True when two titles share their distinctive words.

    Deliberately not an exact match: the same article is collected under several
    slightly different headlines, which is exactly the duplication the owner sees
    on the desk. What must hold is that they are the SAME article, so the
    distinctive words have to agree almost completely.
    """
    a, b = _title_key(left), _title_key(right)
    if not a or not b:
        return False
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    return len(smaller & larger) / len(smaller) >= 0.8


def resolve_publication_urls(title: str, *, runs_dir=None, limit: int = 200) -> list[str]:
    """Find where a Story's article actually lives, from the newsroom's own record.

    **Why this exists.** Every publication these Stories were collected from is a
    `news.google.com` redirect: a JS page that cannot be read and does not carry
    the destination URL. Refusing on that basis would leave a Story that plainly
    has a real article unable to produce a Draft — the exact failure reported.

    Collection already resolved the real publisher URL when it ran and wrote it
    into the search audit. This reads **that record**: no new search, no provider
    spend, and no second opinion about what the article is. No match returns
    `""` and the caller refuses honestly.
    """
    wanted = _title_key(title)
    if not wanted:
        return []
    directory = Path(runs_dir or search_mod.search_runs_dir())
    if not directory.exists():
        return []
    found: list[str] = []
    seen: set[str] = set()
    scanned = 0
    for path in sorted(directory.glob("*.jsonl")):
        if scanned >= limit:
            break
        scanned += 1
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for candidate in bundle.get("candidates") or []:
            url = str(candidate.get("url") or "")
            if not is_readable_publication(url) or url in seen:
                continue
            if _title_matches(candidate.get("title", ""), title):
                seen.add(url)
                found.append(url)
    return found


def resolve_publication_url(title: str, *, runs_dir=None, limit: int = 200) -> str:
    """The first publisher URL the newsroom's own record holds for this title."""
    found = resolve_publication_urls(title, runs_dir=runs_dir, limit=limit)
    return found[0] if found else ""


def _relevance(url: str, title: str) -> float:
    """How strongly a candidate URL names the Story, for a stable ordering.

    Provider result order is not stable between calls, so relying on it made the
    resolution flaky: the same Story could resolve to a good publisher page once
    and to an unrelated one the next time. Ranking by the Story's own words in
    the URL makes the choice deterministic and puts the right publisher first.
    """
    wanted = _title_key(title)
    if not wanted:
        return 0.0
    slug = _TITLE_NOISE.sub(" ", (urlsplit(url).path + " " + url).casefold())
    have = frozenset(word for word in slug.split() if len(word) > 3)
    if not have:
        return 0.0
    return len(wanted & have) / len(wanted)


def _keyless_lookup(title: str, *, limit: int = 8) -> list[str]:
    """One bounded, keyless lookup of the Story's OWN article.

    V1.2-G4.2 §3C. This is deliberately NOT research: it is one DDGS query for
    the Story's own headline, used only to find the publisher page the inbox
    already told us about. Two deliberate constraints:

    * **DDGS only.** The provider chain also contains Serper, and spending paid
      search credits to produce a first Draft is exactly what the owner ruled
      out. DDGS is keyless, so this costs nothing and cannot exhaust a budget.
    * **Publisher pages only.** Social wrappers, aggregators and this site's own
      domain are dropped, so the Draft is still never built from a snippet or
      from a republication of ourselves.
    """
    try:
        results = search_mod.DDGSProvider().search(title).get("results") or []
    except (OSError, ValueError, KeyError, TypeError, search_mod.SearchError):
        return []
    found: list[str] = []
    for row in results[:limit]:
        url = str(row.get("url") or "")
        if is_readable_publication(url) and url not in found:
            found.append(url)
    return found


#: Resolved candidates per title, for the life of this process.
#:
#: The Draft path resolves the Story's publication TWICE — once to decide whether
#: a refusal is final, once to actually read the page — and the keyless provider
#: rate-limits a second immediate call. The second lookup could therefore come
#: back empty for a Story that had just resolved perfectly, which showed up as
#: an inexplicable `NO_DRAFT_MATERIAL`. One resolution, remembered.
_RESOLVED: dict[str, list[str]] = {}


def _news_lookup(title: str, *, limit: int = 8) -> list[str]:
    """The publishers currently carrying this article, via the keyless news feed.

    V1.2-G4.2 §3C. This is the *collector* provider the newsroom already uses for
    every regional Story, so it is the one lookup guaranteed to be both keyless
    and un-throttled. Its links are `news.google.com` redirects, which carry no
    article path — but each item names the PUBLISHER, and that is exactly what is
    needed: it tells us this story is on `faragency.bg` or `bnrnews.bg`, so the
    publisher is known even when the article URL is not.

    The returned entries are publisher roots, not articles, so a caller that
    cannot open them must simply move on — which is what the reader loop does.
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    query = urllib.parse.quote(str(title or ""))
    url = (
        "https://news.google.com/rss/search?q=" + query + "&hl=bg&gl=BG&ceid=BG:bg"
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "chernomorie-editor/1.0"})
        feed = urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT).read()
        root = ET.fromstring(feed)
    except (OSError, ValueError, ET.ParseError):
        return []
    roots: list[str] = []
    for item in root.findall("./channel/item")[: limit * 3]:
        source = item.find("source")
        domain = str((source.get("url") if source is not None else "") or "")
        if not domain.lower().startswith(("http://", "https://")):
            continue
        if not is_readable_publication(domain):
            continue
        if domain not in roots:
            roots.append(domain)
        if len(roots) >= limit:
            break
    return roots


def publication_urls(title: str, *, runs_dir=None, refresh: bool = False) -> list[str]:
    """Every URL the Story's article might be readable at, best first.

    The newsroom's own discovery record comes first because it is free and
    already knows the answer; the bounded keyless lookup is the fallback for a
    Story collected before that record existed, or whose recorded publisher
    blocks our request. A publisher returning 403 must never be what decides
    that a Story has no readable material.
    """
    key = str(title or "").strip().casefold()
    if key and key in _RESOLVED and not refresh:
        return list(_RESOLVED[key])
    found = resolve_publication_urls(title, runs_dir=runs_dir)
    for url in _keyless_lookup(title):
        if url not in found:
            found.append(url)
    for root in _news_lookup(title):
        if root not in found:
            found.append(root)
    # Most story-like first, so the read is deterministic and does not depend on
    # whichever order the provider happened to return.
    ordered = sorted(found, key=lambda url: -_relevance(url, title))
    if key:
        _RESOLVED[key] = list(ordered)
    return list(ordered)


#: How much of the Story's distinctive wording the page must also contain.
#:
#: This is a CORRECTNESS gate, not a quality one. A resolver can legitimately
#: return a page that is on the right publisher but about a different event — a
#: tourism-ministry meeting standing in for a prize ceremony, say. A Draft built
#: from that reports a story the newsroom never ran, which is far worse than no
#: Draft at all, so a page that is not about this Story is rejected outright.
MIN_TOPIC_OVERLAP = 0.34


def page_is_about(text: str, topic: str) -> bool:
    """Whether a page is actually about the Story whose publication we wanted."""
    wanted = _title_key(topic)
    if not wanted:
        return True  # nothing to check against; the URL itself is the evidence
    have = _title_key(text[:6000])
    if not have:
        return False
    return len(wanted & have) / len(wanted) >= MIN_TOPIC_OVERLAP


def read_publication(url: str, *, topic: str = "", opener=None) -> dict | None:
    """Open one publication and return its usable prose, or `None`.

    `None` means the page could not be read, held nothing propositional, or was
    not about this Story. That is the only outcome that may lead to
    `NO_DRAFT_MATERIAL` (§5) once this is wired in — never "research promoted
    nothing".
    """
    if not is_readable_publication(url):
        return None
    try:
        page = opener(url) if opener else web_fetch.fetch_page(url)
    except (web_fetch.WebFetchError, OSError, ValueError):
        # A page we cannot open is exactly the §5 case, and a fetch failure is
        # never a reason to raise through the Draft command.
        return None
    text = str((page or {}).get("text") or "")
    if not text.strip():
        return None
    if not page_is_about(text, topic):
        return None
    blocks = html_desc.normalize_blocks(text)
    if not blocks and text.strip():
        blocks = ({"kind": html_desc.PROSE, "text": text},)
    sentences = claim_quality.SENTENCE_SPLIT.split(text)
    claims = claim_quality.select_candidate_claims(
        sentences,
        # A single open question keeps the extractor focused on the story rather
        # than on a checklist; it shapes which sentences score, not what is true.
        ["Какво се случи в тази новина?"],
        limit=MAX_CLAIMS,
        topic=topic,
        blocks=blocks,
    )
    kept = [
        str(row.get("text") or "").strip()
        for row in claims
        if len(str(row.get("text") or "").strip()) >= MIN_CLAIM_CHARS
    ][:MAX_CLAIMS]
    if not kept:
        return None
    return {
        "url": str((page or {}).get("final_url") or url),
        "domain": (urlsplit(str((page or {}).get("final_url") or url)).hostname or "").lower(),
        "claims": [
            {"text": text, "locator": f"claim:{index}"} for index, text in enumerate(kept)
        ],
    }
