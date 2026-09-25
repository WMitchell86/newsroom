"""Narrow Story editor metadata: follow bookmark and observed-review cursor.

The canonical ``NEW / SEEN / IGNORED`` Story lifecycle and discovery members
remain in ``story_store``. This module never persists attention and never treats
follow as a Story status.
"""

from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import editor_projections, inbox_store, live_store, story_store

ROOT = Path(__file__).resolve().parents[3]
VERSION = 1
METADATA_FIELDS = {
    "story_id",
    "followed",
    "last_reviewed_at",
    "reviewed_development_ids",
}
STORE_FIELDS = {"version", "stories"}
DEVELOPMENT_ID_RE = re.compile(r"dev_[0-9a-f]{15}\Z")
_MUTATION_LOCK = threading.RLock()


class StoryEditorMetadataError(ValueError):
    """Story editor metadata that must not be stored or trusted."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def story_editor_metadata_path(*, root=None) -> Path:
    if root is not None:
        return Path(root) / "story_editor_metadata.json"
    override = os.environ.get("NEWSROOM_STORY_EDITOR_METADATA_PATH")
    if override:
        return Path(override)
    root_path = Path(
        os.environ.get("WB_NEWSROOM_DIR")
        or os.environ.get("NEWSROOM_DIR")
        or (ROOT / "var" / "newsroom")
    )
    return root_path / "story_editor_metadata.json"


def _timestamp(value, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise StoryEditorMetadataError(f"{field} must be a non-empty timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StoryEditorMetadataError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise StoryEditorMetadataError(f"{field} must include a timezone")
    return text


def _development_ids(raw) -> list[str]:
    if not isinstance(raw, list):
        raise StoryEditorMetadataError("reviewed_development_ids must be a list")
    ids = []
    for value in raw:
        if not isinstance(value, str) or not DEVELOPMENT_ID_RE.fullmatch(value):
            raise StoryEditorMetadataError(
                f"reviewed development id must match {DEVELOPMENT_ID_RE.pattern}"
            )
        ids.append(value)
    if len(ids) != len(set(ids)):
        raise StoryEditorMetadataError("reviewed_development_ids cannot contain duplicates")
    return sorted(ids)


def validate_story_editor_metadata(raw) -> dict:
    if not isinstance(raw, dict):
        raise StoryEditorMetadataError("Story editor metadata must be an object")
    unknown = sorted(set(raw) - METADATA_FIELDS)
    if unknown:
        raise StoryEditorMetadataError(
            f"unknown metadata fields {unknown} (allowed: {sorted(METADATA_FIELDS)})"
        )
    missing = sorted(METADATA_FIELDS - set(raw))
    if missing:
        raise StoryEditorMetadataError(f"metadata missing fields: {missing}")
    if not isinstance(raw["story_id"], str):
        raise StoryEditorMetadataError("story_id must be a string")
    story_id = raw["story_id"].strip()
    if not story_id:
        raise StoryEditorMetadataError("story_id is required")
    if not isinstance(raw["followed"], bool):
        raise StoryEditorMetadataError("followed must be true or false")
    return {
        "story_id": story_id,
        "followed": raw["followed"],
        "last_reviewed_at": _timestamp(raw["last_reviewed_at"], "last_reviewed_at", nullable=True),
        "reviewed_development_ids": _development_ids(raw["reviewed_development_ids"]),
    }


def validate_story_editor_store(raw) -> dict:
    if not isinstance(raw, dict):
        raise StoryEditorMetadataError("Story editor metadata store must be an object")
    unknown = sorted(set(raw) - STORE_FIELDS)
    if unknown:
        raise StoryEditorMetadataError(f"unknown store fields {unknown}")
    if raw.get("version") != VERSION:
        raise StoryEditorMetadataError(f"store version must be {VERSION}")
    if not isinstance(raw.get("stories"), list):
        raise StoryEditorMetadataError("store stories must be a list")
    rows = [validate_story_editor_metadata(row) for row in raw["stories"]]
    ids = [row["story_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise StoryEditorMetadataError("duplicate story_id in metadata store")
    return {
        "version": VERSION,
        "stories": sorted(rows, key=lambda row: row["story_id"]),
    }


def read_story_editor_metadata_store(*, root=None) -> dict:
    path = story_editor_metadata_path(root=root)
    if not path.exists():
        return {"version": VERSION, "stories": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoryEditorMetadataError(
            f"Story editor metadata store is unreadable ({path}): {exc}"
        ) from exc
    return validate_story_editor_store(raw)


def write_story_editor_metadata(raw, *, root=None) -> dict:
    normalized = validate_story_editor_store(raw)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    live_store.atomic_write(story_editor_metadata_path(root=root), payload)
    return normalized


def _empty(story_id: str) -> dict:
    return {
        "story_id": story_id,
        "followed": False,
        "last_reviewed_at": None,
        "reviewed_development_ids": [],
    }


def get_story_editor_metadata(story_id: str, *, root=None) -> dict:
    if not isinstance(story_id, str):
        raise StoryEditorMetadataError("story_id must be a string")
    wanted = story_id.strip()
    if not wanted:
        raise StoryEditorMetadataError("story_id is required")
    store = read_story_editor_metadata_store(root=root)
    return next(
        (deepcopy(row) for row in store["stories"] if row["story_id"] == wanted),
        _empty(wanted),
    )


def _save_row(row, *, root=None) -> dict:
    store = read_story_editor_metadata_store(root=root)
    rows = [item for item in store["stories"] if item["story_id"] != row["story_id"]]
    rows.append(row)
    return write_story_editor_metadata({"version": VERSION, "stories": rows}, root=root)


def set_story_followed(story_id: str, followed: bool, *, stories_path, root=None) -> dict:
    if not isinstance(followed, bool):
        raise StoryEditorMetadataError("followed must be true or false")
    with _MUTATION_LOCK:
        canonical = story_store.story_by_id(story_store.read_store(stories_path), story_id)
        if canonical is None:
            raise StoryEditorMetadataError(f"unknown canonical story_id: {story_id}")
        row = get_story_editor_metadata(story_id, root=root)
        row["followed"] = followed
        _save_row(row, root=root)
        return row


def _development_id(story_id: str, item_id: str) -> str:
    return editor_projections.development_id_for(story_id, item_id)


def _restore_file(path: Path, before: bytes | None) -> None:
    if before is None:
        path.unlink(missing_ok=True)
    else:
        live_store.atomic_write(path, before.decode("utf-8"))


def _available_development_ids(story: dict) -> set[str]:
    if not isinstance(story, dict):
        raise StoryEditorMetadataError("canonical Story is required")
    story_id = str(story.get("story_id") or "").strip()
    if not story_id:
        raise StoryEditorMetadataError("canonical Story requires story_id")
    return {
        _development_id(story_id, member["item_id"])
        for member in story.get("members") or []
        if member.get("relation") == "NEW_DEVELOPMENT"
    }


def review_story_developments(
    story_id: str,
    observed_development_ids,
    *,
    stories_path,
    inbox_path,
    now=None,
    root=None,
) -> dict:
    """Acknowledge only submitted IDs and restore the canonical Story as SEEN."""
    if not isinstance(story_id, str):
        raise StoryEditorMetadataError("story_id must be a string")
    story_id = story_id.strip()
    if isinstance(observed_development_ids, (str, bytes)):
        raise StoryEditorMetadataError("observed_development_ids must be a list")
    observed = _development_ids(list(observed_development_ids))
    stories_file = Path(stories_path)
    inbox_file = Path(inbox_path)
    with _MUTATION_LOCK:
        store = story_store.read_store(stories_file)
        story = story_store.story_by_id(store, story_id)
        if story is None:
            raise StoryEditorMetadataError(f"unknown story_id: {story_id}")
        unknown = sorted(set(observed) - _available_development_ids(story))
        if unknown:
            raise StoryEditorMetadataError(f"unknown development ids: {unknown}")
        items = inbox_store.read_items(inbox_file)
        before_story = stories_file.read_bytes() if stories_file.exists() else None
        before_inbox = inbox_file.read_bytes() if inbox_file.exists() else None
        row = get_story_editor_metadata(story_id, root=root)
        row["reviewed_development_ids"] = sorted(
            set(row["reviewed_development_ids"]) | set(observed)
        )
        row["last_reviewed_at"] = _timestamp(now or _now(), "last_reviewed_at")
        story_store.set_story_status(store, story_id, "SEEN")
        desired = story_store.desired_item_statuses(story)
        for item in items:
            target = desired.get(item["item_id"])
            if target:
                item["status"] = target
        try:
            if items:
                inbox_store.save_items(items, inbox_file)
            story_store.write_store(store, stories_file)
            _save_row(row, root=root)
        except Exception:
            _restore_file(stories_file, before_story)
            _restore_file(inbox_file, before_inbox)
            raise
        return row
