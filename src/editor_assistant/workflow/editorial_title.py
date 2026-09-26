"""The one editorial headline cleaner (V1.2-G2.1 §A).

**What this is.** A publisher or source name is *metadata*, not part of the
editorial headline. Feeds and aggregators routinely decorate a real headline
with their own brand:

```text
Община Несебър започва ремонта на пристанището - БНР
```

That raw string is source material and stays exactly as collected: the inbox
item title and the Publication title are never rewritten (§A2). What the editor
reads — the Story display title, the Today row, the research query, a new
Article's working title — is an *editorial* title, and this module produces it
from the raw one.

**Why it is not a `rsplit(" - ", 1)`.** A legitimate Bulgarian headline can end
in a hyphenated clause, and a real newsroom title such as
`Бургас - Поморие: затварят пътя` must survive untouched. So a trailing segment
is decoration only when it can be *demonstrated* to be publisher decoration
from structured identity data — the item's real `publisher_domain`, its
registrable label, and the registry rows for that publisher (§A3).

**Discovery is not the publisher.** The identity set is built from the item's
own publisher, never from the feed that happened to carry it. That is the same
invariant the rest of the pipeline already enforces (M4B.1), and the real
corpus depends on it: items discovered through an official-labelled feed are
routinely republished media.

**One rule, one place.** The Story projection, the Today row, Article creation
and the research query all call this module (§A4). No caller re-implements it,
and React never sees the raw decorated string: the projection is the boundary.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

#: A trailing `" - X"` decoration, where X carries no further hyphen. The
#: non-greedy head backtracks so the LAST separator is the one considered, and
#: the tail's hyphen ban keeps a title like `... Бургас-Созопол` intact.
_PUBLISHER_SUFFIX = re.compile(r"^(?P<head>.+?)\s+-\s+(?P<tail>[^-]{1,60})$")

#: A real headline never becomes this short once its decoration is removed.
_MIN_HEAD_CHARS = 12

#: Bounded: real feeds stack at most a brand plus a site section.
_MAX_STRIPPED_SEGMENTS = 2

#: Generic section nouns a publisher appends to its own brand
#: (`БНР Новини`, `bTV Новините`). Recognised only as the SECOND token of a
#: two-token tail whose FIRST token is already proven publisher identity, so it
#: can never strip a clause such as `Поморие: затварят пътя`.
_SECTION_WORDS = frozenset(
    {
        "новини",
        "новината",
        "новините",
        "бюлетин",
        "бюлетина",
        "bulletin",
        "news",
    }
)

_PUNCTUATION = re.compile(r"[«»„“”\"'()\[\].,:;!?…·]")


def _normalize(value: str | None) -> str:
    """Case- and punctuation-insensitive comparison form for one name."""
    text = _PUNCTUATION.sub(" ", str(value or "").casefold())
    return re.sub(r"\s+", " ", text).strip()


def _host(value: str | None) -> str:
    """The host of a URL or a bare host, without a leading ``www.``."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "//" in raw:
        raw = urlsplit(raw).hostname or ""
    else:
        raw = raw.split("/", 1)[0]
    host = raw.casefold().strip().strip(".")
    return host.removeprefix("www.")


def _label(host: str) -> str:
    """The registrable label of a host: `burgasmedia.com` -> `burgasmedia`."""
    return host.split(".")[0] if host else ""


def publisher_identity(
    *,
    publisher_domain: str | None = None,
    url: str | None = None,
    registry_rows: object = (),
) -> set[str]:
    """Every name this publisher may legitimately decorate a headline with.

    ``publisher_domain`` is the *real* publisher of the item. When it is absent
    the item's own ``url`` host is used, which is correct only for a direct feed
    — an aggregator redirect is not a publisher and its host is never added
    here by this module; callers pass the real publisher domain.

    Every registry row that claims the host contributes its name, not just the
    first one: the real registry legitimately has several rows per publisher
    domain (a municipality and its cultural programme both live on
    `burgas.bg`), and picking one of them would make the decision depend on
    registry order.
    """
    identity: set[str] = set()
    host = _host(publisher_domain) or _host(url)
    if not host:
        return identity

    candidates = {host, _label(host)}
    for row in registry_rows or ():
        if not isinstance(row, dict):
            continue
        row_host = _host(row.get("domain")) or _host(row.get("url"))
        if not row_host:
            continue
        # The row claims this publisher when its own domain or feed host is the
        # publisher host, or a parent of it (`www.burgas.bg` vs `burgas.bg`).
        if row_host == host or host.endswith("." + row_host) or row_host.endswith("." + host):
            for value in (row.get("name"), row.get("domain"), row.get("url")):
                normalized = _normalize(value)
                if len(normalized) >= 3:
                    identity.add(normalized)
            label = _label(row_host)
            if label:
                identity.add(_normalize(label))
    for candidate in candidates:
        if candidate:
            identity.add(_normalize(candidate))
    return {value for value in identity if len(value) >= 3}


def _is_publisher_decoration(tail: str, identity: set[str]) -> bool:
    """Whether one trailing segment is demonstrably publisher decoration."""
    normalized = _normalize(tail)
    if not normalized or ":" in tail or "/" in tail:
        return False
    tokens = normalized.split()
    if len(tokens) > 2:
        # A clause, not a brand. `Поморие: затварят пътя` and
        # `00 18881 / 25.09.2026 г.` both land here and stay untouched.
        return False
    if normalized in identity:
        return True
    if any((normalized in value or value in normalized) for value in identity if len(value) >= 4):
        return True
    if len(tokens) == 2 and tokens[1] in _SECTION_WORDS:
        # `БНР Новини`: the brand is proven identity, the second token is a
        # generic section noun rather than editorial text.
        brand = tokens[0]
        return any((brand in value or value in brand) for value in identity if len(value) >= 3)
    return False


def editorial_story_title(raw_title: str | None, *, identity: object = ()) -> str:
    """The editorial title of a Story, derived from the raw collected headline.

    The raw title is never modified in place and no caller ever stores the
    result: this is a projection-level title, and the source material keeps the
    exact string the feed delivered.
    """
    current = str(raw_title or "").strip()
    if not current:
        return ""
    known = {str(value).strip().casefold() for value in identity or () if str(value).strip()}
    known = {_normalize(value) for value in known} - {""}
    for _ in range(_MAX_STRIPPED_SEGMENTS):
        match = _PUBLISHER_SUFFIX.match(current)
        if not match:
            break
        head = match.group("head").strip()
        tail = match.group("tail").strip()
        if len(head) < _MIN_HEAD_CHARS:
            break
        if not _is_publisher_decoration(tail, known):
            break
        current = head
    return current


# --------------------------------------------------------------------------
# the one resolver every projection uses
# --------------------------------------------------------------------------

#: Registry rows, cached per file revision. A Today projection cleans a title
#: for every row it returns, so re-reading the registry per row would make the
#: cost of one screen proportional to its row count. The registry is an
#: operator file that changes rarely, and its mtime is the invalidation signal.
_REGISTRY_CACHE: dict[str, tuple] = {}


def load_registry_rows(path) -> tuple:
    """Registry rows for title cleaning, cached per (path, mtime).

    A missing or unreadable registry yields an empty identity set rather than an
    error: titles are then shown exactly as collected, which is honest, and the
    registry itself stays an operator problem.
    """
    from editor_assistant.workflow import sources_registry

    try:
        stamp = path.stat().st_mtime_ns
    except (OSError, ValueError):
        return ()
    key = str(path)
    cached = _REGISTRY_CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        rows = tuple(sources_registry.read_registry(path).values())
    except sources_registry.RegistryError:
        rows = ()
    _REGISTRY_CACHE[key] = (stamp, rows)
    return rows


def clear_registry_cache() -> None:
    """Drop the cached registry revision (tests and long-lived operators)."""
    _REGISTRY_CACHE.clear()


def editorial_title_for_item(item: dict, *, registry_rows: object = ()) -> str:
    """One publication's editorial title, from its raw collected headline.

    The single entry point every Story title funnels through (§A4): the Story
    projection, the Today row, both Article-creation paths and the research
    query. The item's raw title is never modified and never stored cleaned.
    """
    raw = str((item or {}).get("title") or "")
    if not raw:
        return ""
    identity = publisher_identity(
        # The real publisher, never the feed that carried the item: an item
        # discovered through an official-labelled feed is regularly republished
        # media, and its decoration follows the publisher (M4B.1).
        publisher_domain=(item or {}).get("publisher_domain"),
        url=(item or {}).get("url")
        if not str((item or {}).get("publisher_domain") or "").strip()
        else "",
        registry_rows=registry_rows,
    )
    return editorial_story_title(raw, identity=identity)
