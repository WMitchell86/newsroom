"""M1.3 version fingerprint — deterministic, stdlib only, no I/O.

Content hashed: title, published_at (UTC-canonicalized), body_text,
body_links (appearance order preserved), author.
Excluded: source_id, source_url, item_url, fetched_at (identity/transport).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timezone

from editor_assistant.models import SourceItem


class StateError(ValueError):
    """Raised for invalid state input (e.g. naive datetimes)."""


def canonical_published_at(item: SourceItem) -> str | None:
    """Fingerprint-only canonicalization: aware instant -> UTC ISO-8601.

    None stays explicit None. Naive datetimes are a defect -> StateError,
    never silently assumed UTC/local (same rule as RSS pubDate parsing).
    """
    if item.published_at is None:
        return None
    if item.published_at.tzinfo is None:
        raise StateError("published_at must be timezone-aware or None for fingerprinting")
    return item.published_at.astimezone(timezone.utc).isoformat()


def canonical_payload(item: SourceItem) -> dict[str, object]:
    """Explicit canonical structure with stable field order (insertion-ordered)."""
    return {
        "title": item.title,
        "published_at": canonical_published_at(item),
        "body_text": item.body_text,
        "body_links": list(item.body_links),
        "author": item.author,
    }


def fingerprint_item(item: SourceItem) -> str:
    """SHA-256 over deterministic JSON (sorted keys, compact, UTF-8)."""
    raw = json.dumps(
        canonical_payload(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
