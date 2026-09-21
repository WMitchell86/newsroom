"""Story inbox store (M4A skeleton) — what a collection run produces.

The inbox is what a human reads; it is deliberately dumb in M4A:

* **one row per collected item**, no story clustering, no angles, no research and
  no drafting (that is M4B/M4C);
* an inbox item is a **candidate, never evidence**: nothing here claims a fact is
  true, and nothing here is publication-ready material. The factual contracts stay
  where they are;
* identity is deterministic — `item_id` derives from `(source_id, source_item_id,
  url)`, so re-collecting the same item is a no-op rather than a duplicate;
* statuses are only `NEW` / `SEEN` / `IGNORED`. M4C adds story identity; it must
  not overload these;
* one atomic writer, deterministic bytes, newest first.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from editor_assistant.workflow import live_store

ROOT = Path(__file__).resolve().parents[3]

ITEM_STATUSES = ("NEW", "SEEN", "IGNORED")

#: A closed schema: unknown keys are refused, so a typo cannot be stored silently.
#:
#: `source_id`/`source_kind` = **how it was discovered**; `publisher_domain` /
#: `publisher_kind` / `factual_authority` = **who published it**. The latter are
#: computed from the real publisher, never inherited from the discovery source.
FIELDS = (
    "item_id",
    "source_id",
    "source_item_id",
    "title",
    "url",
    "published_at",
    #: Real event dates, supplied only by a collector that knows them (M4B.1 F2).
    #: Empty for every collector wired today; never populated from `published_at`.
    "event_at",
    "event_end_at",
    "discovered_at",
    "summary",
    "source_kind",
    "priority",
    "publisher_domain",
    "publisher_kind",
    "factual_authority",
    "status",
)


class InboxError(ValueError):
    """A row that must not be stored."""


def inbox_path(path=None):
    """Runtime store; overridable for tests (never read/write outside it)."""
    if path is not None:
        return Path(path)
    override = os.environ.get("NEWSROOM_INBOX_PATH")
    if override:
        return Path(override)
    return ROOT / "var" / "newsroom" / "inbox.jsonl"


def item_id_for(source_id, source_item_id, url):
    """Deterministic identity: the same item collected twice is the same row."""
    seed = f"{source_id}\x1f{source_item_id or ''}\x1f{url or ''}"
    return "i" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:15]


def _http_url(url):
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def validate_item(item):
    """Return a normalized copy or raise `InboxError` (never a partial store)."""
    if not isinstance(item, dict):
        raise InboxError("an inbox item must be an object")
    unknown = sorted(set(item) - set(FIELDS))
    if unknown:
        raise InboxError(f"unknown inbox fields {unknown} (allowed: {list(FIELDS)})")
    source_id = str(item.get("source_id", "")).strip()
    if not source_id:
        raise InboxError("source_id is required")
    title = str(item.get("title", "")).strip()
    if not title:
        raise InboxError(f"{source_id}: title is required")
    url = _http_url(item.get("url"))
    if not url:
        raise InboxError(f"{source_id}: url must be http(s), got {item.get('url')!r}")
    status = str(item.get("status") or "NEW")
    if status not in ITEM_STATUSES:
        raise InboxError(f"{source_id}: status must be one of {ITEM_STATUSES}")
    source_item_id = str(item.get("source_item_id") or url)
    authority = item.get("factual_authority", False)
    if not isinstance(authority, bool):
        raise InboxError(f"{source_id}: factual_authority must be true or false")
    return {
        "item_id": str(item.get("item_id") or item_id_for(source_id, source_item_id, url)),
        "source_id": source_id,
        "source_item_id": source_item_id,
        "title": title,
        "url": url,
        "published_at": str(item.get("published_at") or ""),
        "event_at": str(item.get("event_at") or ""),
        "event_end_at": str(item.get("event_end_at") or ""),
        "discovered_at": str(item.get("discovered_at") or ""),
        "summary": str(item.get("summary") or "")[:2000],
        "source_kind": str(item.get("source_kind") or ""),
        "priority": str(item.get("priority") or "normal"),
        "publisher_domain": str(item.get("publisher_domain") or ""),
        "publisher_kind": str(item.get("publisher_kind") or ""),
        "factual_authority": authority,
        "status": status,
    }


def _sort_key(item):
    return (item.get("discovered_at") or "", item["item_id"])


def read_items(path=None):
    """All items, newest first. A missing file is an empty inbox (not an error)."""
    store = inbox_path(path)
    if not store.exists():
        return []
    items = []
    for line_no, line in enumerate(store.open(encoding="utf-8"), start=1):
        if not line.strip():
            continue
        try:
            items.append(validate_item(json.loads(line)))
        except (ValueError, InboxError) as exc:
            raise InboxError(f"inbox row {line_no} is unreadable ({store}): {exc}") from exc
    return sorted(items, key=_sort_key, reverse=True)


def save_items(items, path=None):
    """Validate everything, serialize fully, then write atomically."""
    normalized = [validate_item(item) for item in items]
    lines = [
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in sorted(normalized, key=_sort_key, reverse=True)
    ]
    payload = "\n".join(lines) + ("\n" if lines else "")
    live_store.atomic_write(inbox_path(path), payload)
    return normalized


def add_items(items, path=None):
    """Add candidate items. An already-known `item_id` is a duplicate, not an error."""
    existing = {item["item_id"]: item for item in read_items(path)}
    added, duplicates = [], []
    for raw in items:
        item = validate_item(raw)
        if item["item_id"] in existing:
            duplicates.append(item["item_id"])
            continue
        existing[item["item_id"]] = item
        added.append(item)
    save_items(list(existing.values()), path)
    return {"new": len(added), "duplicate": len(duplicates), "items": added}


def set_status(item_id, status, *, path=None):
    """Move one item between NEW / SEEN / IGNORED (the editor's only inbox action)."""
    if status not in ITEM_STATUSES:
        raise InboxError(f"status must be one of {ITEM_STATUSES}, got {status!r}")
    items = read_items(path)
    for item in items:
        if item["item_id"] == item_id:
            item["status"] = status
            save_items(items, path)
            return item
    raise InboxError(f"unknown item_id: {item_id}")


def count_buckets(items):
    """Status counts for a list of items (shared by lifetime and daily counts)."""
    by_status = {status: 0 for status in ITEM_STATUSES}
    for item in items:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return by_status


def counts(path=None):
    """Lifetime totals. The UI must not label these "Днес" (M4B.1 F3)."""
    items = read_items(path)
    by_source = {}
    for item in items:
        by_source[item["source_id"]] = by_source.get(item["source_id"], 0) + 1
    return {
        "total": len(items),
        "by_status": count_buckets(items),
        "by_source": dict(sorted(by_source.items())),
    }


def today_counts(path=None, *, now=None):
    """Real counts for the current Europe/Sofia calendar day.

    "Today" is a newsroom-arrival day, so it is computed from `discovered_at` on
    the local `Europe/Sofia` date — not from the file's lifetime totals and not
    from `published_at` (an item published yesterday but collected today arrived
    today). `source_health` owns the timezone helper so cadence and "today" never
    disagree.
    """
    from editor_assistant.workflow import source_health

    today = source_health.sofia_date(now)
    items = read_items(path)
    arrived = [i for i in items if source_health.sofia_date_of(i.get("discovered_at")) == today]
    return {
        "date": today.isoformat(),
        "total": len(arrived),
        "by_status": count_buckets(arrived),
    }


def unreviewed_count(path=None):
    """Unfinished work: every NEW row, however old it is.

    Deliberately lifetime, not daily — the editor must not lose an item that
    arrived yesterday and was never looked at.
    """
    return sum(1 for item in read_items(path) if item["status"] == "NEW")
