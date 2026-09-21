"""M4C: the story store — real-world events, built from preserved source items.

The inbox stays the **raw collected-source-item store**. This module never
rewrites it, never deletes a row and never changes an `item_id`: a story holds
*references* to existing item IDs, so every collected row stays auditable.

```text
SOURCE ITEMS (inbox.jsonl, untouched)
    -> PUBLICATION IDENTITY (publication_key)
    -> STORY MEMBERSHIP (this module)
    -> STORY VIEW (Workbench «Истории»)
```

Store shape (`var/newsroom/stories.json`, env `NEWSROOM_STORIES_PATH`):

```json
{
  "version": 1,
  "stories": [
    {
      "story_id": "s...",
      "status": "NEW",
      "needs_review": false,
      "created_at": "...", "first_seen_at": "...", "first_public_at": "...",
      "last_seen_at": "...", "latest_material_change_at": "...",
      "representative_item_id": "i...",
      "members": [
        {"item_id": "i...", "publication_key": "p...", "relation": "ORIGIN",
         "relation_source": "first_item", "added_at": "..."}
      ]
    }
  ],
  "overrides": [
    {"action": "SPLIT", "at": "...", "item_id": "i...", "from_story": "s...",
     "to_story": "s...", "note": ""}
  ]
}
```

Rules
-----
* **atomic writes** through the shared `live_store.atomic_write`;
* **strict validation** — a closed schema for stories, members and overrides; a
  malformed or unreadable store raises `StoryStoreError` (it must never look
  empty, or the next automatic update would silently rebuild over the editor);
* **editor decisions win** — `SPLIT` / `MERGE` are recorded as explicit overrides
  and `is_editor_locked()` reports the item IDs an automatic pass must not move;
* **statuses are only `NEW` / `SEEN` / `IGNORED`**, with the M4C lifecycle rules
  (`SAME_STORY` keeps `SEEN`, `NEW_DEVELOPMENT` reopens it, `IGNORED` stays).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import live_store

ROOT = Path(__file__).resolve().parents[3]

VERSION = 1

STORY_STATUSES = ("NEW", "SEEN", "IGNORED")

#: Membership relations. `NEW_STORY` is deliberately absent: creating a separate
#: story is the *action* taken when nothing matches, never a relation.
RELATIONS = ("ORIGIN", "SAME_STORY", "NEW_DEVELOPMENT", "RELATED_BACKGROUND")

#: Relations that carry a materially new development (reopen a SEEN story).
DEVELOPMENT_RELATIONS = ("NEW_DEVELOPMENT",)

#: Relations that never reopen a story.
BACKGROUND_RELATIONS = ("RELATED_BACKGROUND",)

STORY_FIELDS = (
    "story_id",
    "status",
    "needs_review",
    "created_at",
    "first_seen_at",
    "first_public_at",
    "last_seen_at",
    "latest_material_change_at",
    "representative_item_id",
    "members",
)

MEMBER_FIELDS = (
    "item_id",
    "publication_key",
    "relation",
    "relation_source",
    "added_at",
)

OVERRIDE_FIELDS = ("action", "at", "item_id", "from_story", "to_story", "note")

OVERRIDE_ACTIONS = ("SPLIT", "MERGE")

#: Relation sources (audit only; never authority).
SOURCE_EXACT_PUBLICATION = "exact_publication"
SOURCE_DETERMINISTIC_TITLE = "deterministic_title"
SOURCE_SEMANTIC = "semantic"
SOURCE_FIRST_ITEM = "first_item"
SOURCE_EDITOR = "editor"


class StoryStoreError(ValueError):
    """A story record or store that must not be written."""


def stories_path(path=None):
    """Runtime store; overridable for tests (never read/write outside it)."""
    if path is not None:
        return Path(path)
    override = os.environ.get("NEWSROOM_STORIES_PATH")
    if override:
        return Path(override)
    root = Path(os.environ.get("NEWSROOM_DIR") or (ROOT / "var" / "newsroom"))
    return root / "stories.json"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(value=None):
    return str(value) if value else _now()


# ---------------------------------------------------------------- ids


def story_id_for(first_identity):
    """Stable story id from immutable origin identity.

    `first_publication_key` when there is one, else the first `item_id`. Never
    from generated headline text, so a story keeps its id across updates.
    """
    seed = str(first_identity or "").strip()
    if not seed:
        raise StoryStoreError("a story needs an origin identity (publication_key or item_id)")
    return "s" + hashlib.sha256(f"story:{seed}".encode()).hexdigest()[:15]


# ---------------------------------------------------------------- validation


def validate_member(member):
    if not isinstance(member, dict):
        raise StoryStoreError("a story member must be an object")
    unknown = sorted(set(member) - set(MEMBER_FIELDS))
    if unknown:
        raise StoryStoreError(f"unknown member fields {unknown} (allowed: {list(MEMBER_FIELDS)})")
    item_id = str(member.get("item_id") or "").strip()
    if not item_id:
        raise StoryStoreError("a story member requires item_id")
    relation = str(member.get("relation") or "")
    if relation not in RELATIONS:
        raise StoryStoreError(f"relation must be one of {RELATIONS}, got {relation!r}")
    return {
        "item_id": item_id,
        "publication_key": str(member.get("publication_key") or ""),
        "relation": relation,
        "relation_source": str(member.get("relation_source") or ""),
        "added_at": str(member.get("added_at") or _now()),
    }


def validate_story(story):
    if not isinstance(story, dict):
        raise StoryStoreError("a story must be an object")
    unknown = sorted(set(story) - set(STORY_FIELDS))
    if unknown:
        raise StoryStoreError(f"unknown story fields {unknown} (allowed: {list(STORY_FIELDS)})")
    story_id = str(story.get("story_id") or "").strip()
    if not story_id:
        raise StoryStoreError("story_id is required")
    status = str(story.get("status") or "NEW")
    if status not in STORY_STATUSES:
        raise StoryStoreError(f"status must be one of {STORY_STATUSES}, got {status!r}")
    needs_review = story.get("needs_review", False)
    if not isinstance(needs_review, bool):
        raise StoryStoreError("needs_review must be true or false")
    members = [validate_member(m) for m in (story.get("members") or [])]
    if not members:
        raise StoryStoreError(f"{story_id}: a story must have at least one member")
    if not any(m["relation"] == "ORIGIN" for m in members):
        raise StoryStoreError(f"{story_id}: a story must keep exactly one ORIGIN member")
    seen = set()
    for member in members:
        if member["item_id"] in seen:
            raise StoryStoreError(f"{story_id}: item {member['item_id']} appears twice")
        seen.add(member["item_id"])
    representative = str(story.get("representative_item_id") or "")
    if representative and representative not in seen:
        raise StoryStoreError(f"{story_id}: representative_item_id is not a member")
    return {
        "story_id": story_id,
        "status": status,
        "needs_review": needs_review,
        "created_at": str(story.get("created_at") or _now()),
        "first_seen_at": str(story.get("first_seen_at") or ""),
        "first_public_at": str(story.get("first_public_at") or ""),
        "last_seen_at": str(story.get("last_seen_at") or ""),
        "latest_material_change_at": str(story.get("latest_material_change_at") or ""),
        "representative_item_id": representative or members[0]["item_id"],
        "members": members,
    }


def validate_override(row):
    if not isinstance(row, dict):
        raise StoryStoreError("an override must be an object")
    unknown = sorted(set(row) - set(OVERRIDE_FIELDS))
    if unknown:
        raise StoryStoreError(
            f"unknown override fields {unknown} (allowed: {list(OVERRIDE_FIELDS)})"
        )
    action = str(row.get("action") or "")
    if action not in OVERRIDE_ACTIONS:
        raise StoryStoreError(f"override action must be one of {OVERRIDE_ACTIONS}, got {action!r}")
    return {
        "action": action,
        "at": str(row.get("at") or _now()),
        "item_id": str(row.get("item_id") or ""),
        "from_story": str(row.get("from_story") or ""),
        "to_story": str(row.get("to_story") or ""),
        "note": str(row.get("note") or ""),
    }


def validate_store(store):
    if not isinstance(store, dict):
        raise StoryStoreError("the story store must be an object")
    unknown = sorted(set(store) - {"version", "stories", "overrides"})
    if unknown:
        raise StoryStoreError(f"unknown store fields {unknown}")
    stories = [validate_story(s) for s in (store.get("stories") or [])]
    overrides = [validate_override(o) for o in (store.get("overrides") or [])]
    ids = [s["story_id"] for s in stories]
    if len(ids) != len(set(ids)):
        raise StoryStoreError("duplicate story_id in the store")
    held = {}
    for story in stories:
        for member in story["members"]:
            other = held.get(member["item_id"])
            if other and other != story["story_id"]:
                raise StoryStoreError(
                    f"item {member['item_id']} belongs to two stories ({other}, {story['story_id']})"
                )
            held[member["item_id"]] = story["story_id"]
    return {"version": VERSION, "stories": stories, "overrides": overrides}


EMPTY_STORE = {"version": VERSION, "stories": [], "overrides": []}


def read_store(path=None):
    """Read + validate. A missing file is an empty store; anything else raises."""
    store = stories_path(path)
    if not store.exists():
        return {"version": VERSION, "stories": [], "overrides": []}
    try:
        raw = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoryStoreError(f"story store is unreadable ({store}): {exc}") from exc
    return validate_store(raw)


def write_store(store, path=None):
    """Validate everything, serialize fully, then write atomically."""
    normalized = validate_store(store)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    live_store.atomic_write(stories_path(path), payload)
    return normalized


def read_stories(path=None):
    return read_store(path)["stories"]


def read_overrides(path=None):
    return read_store(path)["overrides"]


def save_stories(stories, *, overrides=None, path=None):
    return write_store(
        {"version": VERSION, "stories": list(stories), "overrides": list(overrides or [])}, path
    )


# ---------------------------------------------------------------- lookups


def story_by_id(store, story_id):
    for story in store["stories"]:
        if story["story_id"] == story_id:
            return story
    return None


def story_id_for_item(store, item_id):
    for story in store["stories"]:
        if any(m["item_id"] == item_id for m in story["members"]):
            return story["story_id"]
    return None


def story_id_for_publication(store, publication_key):
    """Exact-publication lookup: the Stage-A fast path (no model call)."""
    if not publication_key:
        return None
    for story in store["stories"]:
        if any(m["publication_key"] == publication_key for m in story["members"]):
            return story["story_id"]
    return None


def assigned_item_ids(store):
    return {m["item_id"] for story in store["stories"] for m in story["members"]}


def is_editor_locked(store, item_id):
    """True when an editor SPLIT/MERGE decision covers this item.

    An automatic pass must never silently undo an editor correction; such items
    are reported for review instead of being moved again.
    """
    for row in store["overrides"]:
        if row["action"] == "SPLIT" and row["item_id"] == item_id:
            return True
        if row["action"] == "MERGE" and item_id in (row["item_id"],):
            return True
    return False


# ---------------------------------------------------------------- lifecycle


def member_times(members, items_by_id):
    """`(first_seen, first_public, last_seen)` from real timestamps only."""
    discovered = [
        str(items_by_id[m["item_id"]].get("discovered_at") or "")
        for m in members
        if m["item_id"] in items_by_id
    ]
    discovered = [d for d in discovered if d]
    published = [
        str(items_by_id[m["item_id"]].get("published_at") or "")
        for m in members
        if m["item_id"] in items_by_id
    ]
    published = [p for p in published if p]
    return (
        min(discovered) if discovered else "",
        min(published) if published else "",
        max(discovered) if discovered else "",
    )


def refresh_times(story, items_by_id, *, now=None):
    """Recompute the derived timestamps. No date is ever fabricated."""
    first_seen, first_public, last_seen = member_times(story["members"], items_by_id)
    changes = [story["created_at"]]
    for member in story["members"]:
        if member["relation"] in DEVELOPMENT_RELATIONS:
            item = items_by_id.get(member["item_id"])
            moment = str(item.get("discovered_at") or "") if item else member.get("added_at") or ""
            if moment:
                changes.append(moment)
    story["first_seen_at"] = first_seen
    story["first_public_at"] = first_public
    story["last_seen_at"] = last_seen
    story["latest_material_change_at"] = max(changes) if changes else ""
    return story


def status_after_relation(status, relation):
    """M4C §12 lifecycle: what a new member does to the story's status.

    * `NEW_DEVELOPMENT` added to a `SEEN` story reopens it to `NEW` (the editor
      must see the development);
    * `SAME_STORY` / `RELATED_BACKGROUND` never reopen;
    * an `IGNORED` story stays ignored — the editor's ignore is intentional.
    """
    if status == "IGNORED":
        return "IGNORED"
    if relation in DEVELOPMENT_RELATIONS:
        return "NEW"
    return status


def add_member(story, item, *, relation, relation_source, publication_key="", now=None):
    """Append one member and apply the lifecycle rule. Mutates and returns `story`."""
    member = validate_member(
        {
            "item_id": item["item_id"],
            "publication_key": publication_key,
            "relation": relation,
            "relation_source": relation_source,
            "added_at": _stamp(now),
        }
    )
    story["members"] = list(story["members"]) + [member]
    story["status"] = status_after_relation(story["status"], relation)
    if relation in DEVELOPMENT_RELATIONS:
        story["representative_item_id"] = member["item_id"]
    return story


def new_story(item, *, publication_key="", relation_source=SOURCE_FIRST_ITEM, now=None):
    """A fresh story whose ORIGIN is this item (stable id from its identity)."""
    origin = publication_key or item["item_id"]
    stamp = _stamp(now)
    return validate_story(
        {
            "story_id": story_id_for(origin),
            "status": "NEW",
            "needs_review": False,
            "created_at": stamp,
            "first_seen_at": item.get("discovered_at") or "",
            "first_public_at": item.get("published_at") or "",
            "last_seen_at": item.get("discovered_at") or "",
            "latest_material_change_at": stamp,
            "representative_item_id": item["item_id"],
            "members": [
                {
                    "item_id": item["item_id"],
                    "publication_key": publication_key,
                    "relation": "ORIGIN",
                    "relation_source": relation_source,
                    "added_at": stamp,
                }
            ],
        }
    )


# ---------------------------------------------------------------- editor actions


def split_member(story, item_id, *, items_by_id, now=None, note="", reserved_ids=None):
    """Editor correction: take one member out of a story into its own story.

    Returns `(story_or_None, new_story)`. The removed member becomes the origin of
    a fresh story (`relation=ORIGIN`, `relation_source=editor`), and the split is
    recorded as an override so a later automatic pass cannot re-merge it. An
    emptied source story is dropped; otherwise its representative is recomputed.

    `reserved_ids` are story ids already in use: splitting a *duplicate* member out
    of a story must not mint the id its origin already holds, so the fallback
    identity is the item's own `item_id`.
    """
    member = next((m for m in story["members"] if m["item_id"] == item_id), None)
    if member is None:
        raise StoryStoreError(f"{story['story_id']}: item {item_id} is not a member")
    if member["relation"] == "ORIGIN" and len(story["members"]) == 1:
        raise StoryStoreError("a story with a single ORIGIN member cannot be split")
    remaining = [m for m in story["members"] if m["item_id"] != item_id]
    item = items_by_id.get(item_id) or {"item_id": item_id}
    key = member["publication_key"]
    if reserved_ids and key and story_id_for(key) in set(reserved_ids):
        key = ""
    fresh = new_story(
        item,
        publication_key=key,
        relation_source=SOURCE_EDITOR,
        now=now,
    )
    fresh["first_seen_at"] = str(item.get("discovered_at") or "")
    fresh["first_public_at"] = str(item.get("published_at") or "")
    fresh["last_seen_at"] = str(item.get("discovered_at") or "")
    if not remaining:
        return None, fresh
    origin = next((m for m in remaining if m["relation"] == "ORIGIN"), remaining[0])
    if not any(m["relation"] == "ORIGIN" for m in remaining):
        origin = {**origin, "relation": "ORIGIN", "relation_source": SOURCE_EDITOR}
        remaining = [origin if m["item_id"] == origin["item_id"] else m for m in remaining]
    story["members"] = remaining
    if story["representative_item_id"] == item_id:
        story["representative_item_id"] = origin["item_id"]
    return refresh_times(story, items_by_id, now=now), fresh


def merge_stories(store, target_id, source_id, *, items_by_id, now=None, note=""):
    """Editor correction: move every member of `source_id` into `target_id`.

    Returns the merged target story. The source story is dropped and the merge is
    recorded as an override; members keep their relation (an `ORIGIN` from the
    source becomes `RELATED_BACKGROUND` so the target keeps exactly one origin).
    """
    if target_id == source_id:
        raise StoryStoreError("cannot merge a story with itself")
    target = story_by_id(store, target_id)
    source = story_by_id(store, source_id)
    if target is None or source is None:
        raise StoryStoreError("merge target/source story not found")
    known = {m["item_id"] for m in target["members"]}
    for member in source["members"]:
        if member["item_id"] in known:
            continue
        moved = dict(member)
        if moved["relation"] == "ORIGIN":
            moved["relation"] = "RELATED_BACKGROUND"
            moved["relation_source"] = SOURCE_EDITOR
        target["members"].append(validate_member(moved))
        target["status"] = status_after_relation(target["status"], moved["relation"])
    if source["representative_item_id"] and not any(
        m["item_id"] == target["representative_item_id"] for m in target["members"]
    ):
        target["representative_item_id"] = source["representative_item_id"]
    refresh_times(target, items_by_id, now=now)
    store["stories"] = [s for s in store["stories"] if s["story_id"] != source_id]
    store["overrides"] = list(store.get("overrides") or []) + [
        validate_override(
            {
                "action": "MERGE",
                "at": _stamp(now),
                "item_id": source["representative_item_id"],
                "from_story": source_id,
                "to_story": target_id,
                "note": note,
            }
        )
    ]
    return target


def record_split_override(store, *, item_id, from_story, to_story, now=None, note=""):
    store["overrides"] = list(store.get("overrides") or []) + [
        validate_override(
            {
                "action": "SPLIT",
                "at": _stamp(now),
                "item_id": item_id,
                "from_story": from_story,
                "to_story": to_story,
                "note": note,
            }
        )
    ]
    return store


def set_story_status(store, story_id, status):
    if status not in STORY_STATUSES:
        raise StoryStoreError(f"status must be one of {STORY_STATUSES}, got {status!r}")
    story = story_by_id(store, story_id)
    if story is None:
        raise StoryStoreError(f"unknown story_id: {story_id}")
    story["status"] = status
    return story


def desired_item_statuses(story):
    """How a story-level status propagates to its members' inbox rows.

    A story `SEEN`/`IGNORED` is an editor statement about the whole story, so the
    raw view must not keep showing misleading `NEW` rows for it. Reopening a story
    to `NEW` (a new development) deliberately does **not** touch the items: the
    development's own item is new already, and older items stay as the editor left
    them.
    """
    if story["status"] == "SEEN":
        return {m["item_id"]: "SEEN" for m in story["members"]}
    if story["status"] == "IGNORED":
        return {m["item_id"]: "IGNORED" for m in story["members"]}
    return {}


def metrics(story, items_by_id):
    """`discovery_count` / `publication_count` / `publisher_count` (M4C §2.4).

    Five discovery rows that are two unique publications from two publishers must
    never read as "5 sources". A member without a usable publication key counts as
    its own publication (we cannot honestly collapse it).
    """
    keys = []
    publishers = set()
    for member in story["members"]:
        item = items_by_id.get(member["item_id"]) or {}
        key = member["publication_key"] or f"item:{member['item_id']}"
        keys.append(key)
        domain = str(item.get("publisher_domain") or "")
        if domain:
            publishers.add(domain)
    return {
        "discovery_count": len(story["members"]),
        "publication_count": len(set(keys)),
        "publisher_count": len(publishers),
    }
