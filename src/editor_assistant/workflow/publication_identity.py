"""M4C: publication identity — *which exact published article is this?*

Deliberately narrow: `InboxItem -> publication_key`. No story semantics live here.

Three identities stay separate in M4C (see `m4/HARNESS_PROMPT_M4B1_M4C_STORY_IDENTITY.md`):

```text
DISCOVERY    source_id / source_kind      how did the system find this item?
PUBLICATION  publication_key + domain     which exact published article is this?
STORY        story_id                     which real-world event does it belong to?
```

The inbox keeps one row per *discovery* (`item_id = hash(source_id, source_item_id,
url)`), so the same article found through three monitoring queries is three inbox
rows. Publication identity collapses exactly those duplicates without touching the
raw rows:

```text
3 inbox item_ids  ->  1 publication_key  ->  1 story membership
```

Nothing here is evidence, and nothing here is a fact: a `publication_key` only says
"the same URL, at the same publisher".

Contract
--------
* a usable URL is required — no exact identity is invented from a title;
* the key is independent of `source_id` (the discovery monitor never decides it);
* the publisher domain is part of the input, so the same opaque Google News token
  surfaced under different publishers can never collapse by accident;
* conservative: tracking noise is removed, meaningful query parameters are kept.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Query parameters that never identify an article (analytics/campaign noise).
#: `utm_*` is a family; the rest are named explicitly.
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = frozenset({"fbclid", "gclid"})


def _is_tracking(name):
    lowered = name.lower()
    return lowered.startswith(TRACKING_PREFIXES) or lowered in TRACKING_PARAMS


def _host_kind(host):
    """`google` for the opaque Google News redirect host, else `publisher`."""
    if host == "news.google.com" or host.endswith(".news.google.com"):
        return "google"
    return "publisher"


def normalize_publication_url(url):
    """Normalized identity URL, or `""` when the input is not usable.

    Ordinary publisher URLs: lower-case host, fragment removed, default port
    removed, tracking parameters removed, remaining query parameters kept (sorted,
    so parameter order cannot create a second identity), one trailing empty slash
    removed. Paths are never rewritten — `/a/1` and `/a/1/` are the same article,
    `/a/1` and `/a/2` never are.

    Google News opaque URLs: the stable article path/token is kept and all query
    noise is dropped (the redirect target cannot be resolved offline). The
    publisher domain enters the identity separately in `publication_key_for`.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    if _host_kind(host) == "google":
        path = (parts.path or "").rstrip("/")
        if not path:
            return ""
        return urlunsplit(("https", host, path, "", ""))

    try:
        port = parts.port
    except ValueError:
        # Malformed/out-of-range port (":abc"): keep the identity on the bare
        # host — deterministic and crash-free; junk never enters the key
        # (M4F P3: this runs on every collected item).
        port = None
    netloc = host
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    query = urlencode(
        sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
        )
    )
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def publication_key_for(url, publisher_domain=""):
    """Exact publication identity for a URL + its publisher, or `None`.

    `None` means "no usable URL" — the caller must NOT invent an exact duplicate
    from a title; story candidate matching handles that conservatively instead.
    """
    normalized = normalize_publication_url(url)
    if not normalized:
        return None
    domain = str(publisher_domain or "").strip().lower()
    seed = f"{normalized}\x1f{domain}"
    return "p" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:15]


def publication_key(item):
    """Exact publication identity of one inbox item (`None` when unusable).

    Reads only the publication fields: `url` (the published article) and
    `publisher_domain` (who published it). `source_id` is deliberately not read.
    """
    if not isinstance(item, dict):
        return None
    return publication_key_for(item.get("url"), item.get("publisher_domain") or "")


def publication_view(item):
    """Display/debug shape: the key plus the normalized URL it was built from."""
    normalized = normalize_publication_url((item or {}).get("url"))
    return {
        "publication_key": publication_key(item),
        "normalized_url": normalized,
        "publisher_domain": str((item or {}).get("publisher_domain") or ""),
    }
