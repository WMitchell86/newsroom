"""Canonical editor Article records and Article-keyed working content.

This store sits beside the mature Idea/Evidence/Case/Draft workflow. It never
reads, mutates, or substitutes an immutable generated Draft. Article state is
intentionally not persisted here; it is derived by ``editor_projections``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import live_store, story_store

ROOT = Path(__file__).resolve().parents[3]
ARTICLE_FIELDS = {
    "article_id",
    "story_id",
    "working_title",
    "editorial_focus",
    "focus_confirmed_at",
    "created_at",
    "updated_at",
    "content_version",
    "content_path",
    "internal_refs",
    "ready_version",
    "ready_validation_digest",
    "ready_at",
    "finalized_at",
}
INTERNAL_REF_FIELDS = {"idea_id", "evidence_id", "case_id", "draft_id"}
CONTENT_FIELDS = {"article_id", "title", "body", "content_version", "updated_at"}
ARTICLE_ID_RE = re.compile(r"art_[a-z0-9]+(?:_[0-9]+)?\Z")
_MUTATION_LOCK = threading.RLock()


class ArticleStoreError(ValueError):
    """An Article record or content document that must not be stored."""


class ArticleVersionConflict(ArticleStoreError):
    """A content write based on an obsolete Article version."""


@dataclass(frozen=True)
class ReadinessValidation:
    """Server-produced validation identity captured for one content version."""

    content_version: int
    digest: str
    blocking: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _required_text(value, field: str) -> str:
    if not isinstance(value, str):
        raise ArticleStoreError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ArticleStoreError(f"{field} is required")
    return text


def _text(value, field: str) -> str:
    if not isinstance(value, str):
        raise ArticleStoreError(f"{field} must be a string")
    return value.strip()


def _timestamp(value, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArticleStoreError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ArticleStoreError(f"{field} must include a timezone")
    return text


def _version(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArticleStoreError(f"{field} must be a non-negative integer")
    return value


def _article_id(value, field: str = "article_id") -> str:
    if not isinstance(value, str) or not ARTICLE_ID_RE.fullmatch(value):
        raise ArticleStoreError(f"{field} must match {ARTICLE_ID_RE.pattern}")
    return value


def _content_relative_path(article_id: str, content_version: int) -> str:
    return f"editor_articles/{article_id}/v{content_version:08d}.json"


def editorial_workflow_dir() -> Path:
    return Path(
        os.environ.get("WB_EDITORIAL_WORKFLOW_DIR") or (ROOT / "var" / "editorial_workflow")
    )


def editor_articles_path(*, root=None) -> Path:
    return Path(root or editorial_workflow_dir()) / "editor_articles.jsonl"


def article_content_path(article_id: str, content_version: int, *, root=None) -> Path:
    safe_id = _article_id(article_id)
    version = _version(content_version, "content_version")
    return (
        Path(root or editorial_workflow_dir())
        / "editor_articles"
        / safe_id
        / f"v{version:08d}.json"
    )


def validate_editor_article(raw) -> dict:
    if not isinstance(raw, dict):
        raise ArticleStoreError("an editor Article must be an object")
    unknown = sorted(set(raw) - ARTICLE_FIELDS)
    if unknown:
        raise ArticleStoreError(
            f"unknown Article fields {unknown} (allowed: {sorted(ARTICLE_FIELDS)})"
        )
    missing = sorted(ARTICLE_FIELDS - set(raw))
    if missing:
        raise ArticleStoreError(f"Article missing fields: {missing}")
    article_id = _article_id(raw["article_id"])
    expected_path = _content_relative_path(
        article_id, _version(raw["content_version"], "content_version")
    )
    if raw["content_path"] != expected_path:
        raise ArticleStoreError(f"content_path must be {expected_path!r}")
    content_version = _version(raw["content_version"], "content_version")
    ready_version = (
        None if raw["ready_version"] is None else _version(raw["ready_version"], "ready_version")
    )
    ready_at = _timestamp(raw["ready_at"], "ready_at", nullable=True)
    ready_digest = (
        None
        if raw["ready_validation_digest"] is None
        else _required_text(raw["ready_validation_digest"], "ready_validation_digest")
    )
    checkpoint = (ready_version, ready_at, ready_digest)
    if any(value is not None for value in checkpoint) and not all(
        value is not None for value in checkpoint
    ):
        raise ArticleStoreError("readiness checkpoint fields must be all set or all null")
    if ready_version is not None and ready_version != content_version:
        raise ArticleStoreError("ready_version must equal the current content_version")
    finalized_at = _timestamp(raw["finalized_at"], "finalized_at", nullable=True)
    focus_confirmed_at = _timestamp(raw["focus_confirmed_at"], "focus_confirmed_at", nullable=True)
    if finalized_at is not None and ready_version is None:
        raise ArticleStoreError("a finalized Article requires a valid readiness checkpoint")
    if finalized_at is not None and not (raw["editorial_focus"] and focus_confirmed_at):
        raise ArticleStoreError("a finalized Article requires confirmed editorial focus")
    return {
        "article_id": article_id,
        "story_id": _required_text(raw["story_id"], "story_id"),
        "working_title": _text(raw["working_title"], "working_title"),
        "editorial_focus": _text(raw["editorial_focus"], "editorial_focus"),
        "focus_confirmed_at": focus_confirmed_at,
        "created_at": _timestamp(raw["created_at"], "created_at"),
        "updated_at": _timestamp(raw["updated_at"], "updated_at"),
        "content_version": content_version,
        "content_path": expected_path,
        "internal_refs": _validate_internal_refs(raw["internal_refs"]),
        "ready_version": ready_version,
        "ready_validation_digest": ready_digest,
        "ready_at": ready_at,
        "finalized_at": finalized_at,
    }


def validate_article_content(raw) -> dict:
    if not isinstance(raw, dict):
        raise ArticleStoreError("Article content must be an object")
    unknown = sorted(set(raw) - CONTENT_FIELDS)
    if unknown:
        raise ArticleStoreError(f"unknown content fields {unknown}")
    missing = sorted(CONTENT_FIELDS - set(raw))
    if missing:
        raise ArticleStoreError(f"content missing fields: {missing}")
    return {
        "article_id": _article_id(raw["article_id"], "content.article_id"),
        "title": _text(raw["title"], "title"),
        "body": raw["body"] if isinstance(raw["body"], str) else _text(raw["body"], "body"),
        "content_version": _version(raw["content_version"], "content.content_version"),
        "updated_at": _timestamp(raw["updated_at"], "content.updated_at"),
    }


def _validate_internal_refs(raw) -> dict[str, str | None]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ArticleStoreError("internal_refs must be an object")
    unknown = sorted(set(raw) - INTERNAL_REF_FIELDS)
    if unknown:
        raise ArticleStoreError(f"unknown internal_refs fields {unknown}")
    return {
        field: (
            None if raw.get(field) is None else _required_text(raw[field], f"internal_refs.{field}")
        )
        for field in sorted(INTERNAL_REF_FIELDS)
    }


def _serialize_articles(rows) -> str:
    normalized = [validate_editor_article(row) for row in rows]
    ids = [row["article_id"] for row in normalized]
    if len(ids) != len(set(ids)):
        raise ArticleStoreError("duplicate article_id in store")
    lines = [
        json.dumps(row, ensure_ascii=False, sort_keys=True)
        for row in sorted(normalized, key=lambda row: row["article_id"])
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def read_editor_articles(*, root=None) -> list[dict]:
    path = editor_articles_path(root=root)
    if not path.exists():
        return []
    rows = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    rows.append(validate_editor_article(json.loads(line)))
                except (ValueError, TypeError) as exc:
                    raise ArticleStoreError(
                        f"Article store line {line_no} is invalid: {exc}"
                    ) from exc
    except OSError as exc:
        raise ArticleStoreError(f"Article store is unreadable ({path}): {exc}") from exc
    ids = [row["article_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ArticleStoreError("duplicate article_id in store")
    return sorted(rows, key=lambda row: row["article_id"])


def save_editor_articles(rows, *, root=None) -> list[dict]:
    """Validate/serialize before the existing atomic file replacement."""
    previous = {row["article_id"]: row for row in read_editor_articles(root=root)}
    normalized = [validate_editor_article(row) for row in rows]
    for row in normalized:
        old = previous.get(row["article_id"])
        if old is not None and old["story_id"] != row["story_id"]:
            raise ArticleStoreError("story_id is immutable")
        if old is not None and old["finalized_at"] and row != old:
            raise ArticleStoreError("finalized Article record is immutable")
    incoming_ids = {row["article_id"] for row in normalized}
    removed = sorted(set(previous) - incoming_ids)
    if removed:
        raise ArticleStoreError(f"cannot remove Article records: {removed}")
    payload = _serialize_articles(normalized)
    live_store.atomic_write(editor_articles_path(root=root), payload)
    return sorted(normalized, key=lambda row: row["article_id"])


def get_editor_article(article_id: str, *, root=None) -> dict:
    wanted = _required_text(article_id, "article_id")
    row = next(
        (item for item in read_editor_articles(root=root) if item["article_id"] == wanted),
        None,
    )
    if row is None:
        raise ArticleStoreError(f"unknown article_id: {wanted}")
    return row


def _article_id_for(story_id: str, created_at: str, existing_ids) -> str:
    base = hashlib.sha256(f"editor-article\0{story_id}\0{created_at}".encode()).hexdigest()[:15]
    candidate = f"art_{base}"
    suffix = 1
    while candidate in existing_ids:
        candidate = f"art_{base}_{suffix}"
        suffix += 1
    return candidate


def _write_content(content, *, root=None) -> dict:
    normalized = validate_article_content(content)
    path = article_content_path(normalized["article_id"], normalized["content_version"], root=root)
    if path.exists():
        try:
            existing = validate_article_content(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise ArticleStoreError(
                f"Article content version is unreadable ({path}): {exc}"
            ) from exc
        if existing != normalized:
            raise ArticleStoreError("an Article content version is immutable")
        return existing
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    live_store.atomic_write(path, payload)
    return normalized


def get_article_content(article_id: str, *, root=None) -> dict:
    record = get_editor_article(article_id, root=root)
    path = article_content_path(record["article_id"], record["content_version"], root=root)
    if not path.exists():
        raise ArticleStoreError(f"Article content is missing ({path})")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArticleStoreError(f"Article content is unreadable ({path}): {exc}") from exc
    content = validate_article_content(raw)
    if content["article_id"] != record["article_id"]:
        raise ArticleStoreError("content article_id does not match its Article record")
    if content["content_version"] != record["content_version"]:
        raise ArticleStoreError("content version does not match its Article record")
    if content["title"] != record["working_title"]:
        raise ArticleStoreError("content title does not match its Article record")
    return content


def focus_is_confirmed(article: dict) -> bool:
    return bool(article.get("editorial_focus") and article.get("focus_confirmed_at"))


def create_editor_article(
    *,
    story_id: str,
    stories_path,
    working_title: str = "",
    editorial_focus: str = "",
    internal_refs=None,
    now=None,
    root=None,
) -> dict:
    """Create explicit canonical Story lineage plus empty Article content."""
    story = _required_text(story_id, "story_id")
    created = _timestamp(now or _now(), "created_at")
    with _MUTATION_LOCK:
        canonical = story_store.story_by_id(story_store.read_store(stories_path), story)
        if canonical is None:
            raise ArticleStoreError(f"unknown canonical story_id: {story}")
        rows = read_editor_articles(root=root)
        title = _text(working_title, "working_title")
        focus = _text(editorial_focus, "editorial_focus")
        article_id = _article_id_for(story, created, {r["article_id"] for r in rows})
        record = validate_editor_article(
            {
                "article_id": article_id,
                "story_id": story,
                "working_title": title,
                "editorial_focus": focus,
                "focus_confirmed_at": None,
                "created_at": created,
                "updated_at": created,
                "content_version": 0,
                "content_path": _content_relative_path(article_id, 0),
                "internal_refs": internal_refs or {},
                "ready_version": None,
                "ready_validation_digest": None,
                "ready_at": None,
                "finalized_at": None,
            }
        )
        _write_content(
            {
                "article_id": article_id,
                "title": title,
                "body": "",
                "content_version": 0,
                "updated_at": created,
            },
            root=root,
        )
        try:
            save_editor_articles([*rows, record], root=root)
        except Exception:
            article_content_path(article_id, 0, root=root).unlink(missing_ok=True)
            raise
        return get_editor_article(article_id, root=root)


def _replace_article(updated, *, root=None) -> dict:
    rows = read_editor_articles(root=root)
    replaced = False
    output = []
    for row in rows:
        if row["article_id"] == updated["article_id"]:
            output.append(updated)
            replaced = True
        else:
            output.append(row)
    if not replaced:
        raise ArticleStoreError(f"unknown article_id: {updated['article_id']}")
    return next(
        row
        for row in save_editor_articles(output, root=root)
        if row["article_id"] == updated["article_id"]
    )


def update_editor_focus(
    article_id: str,
    editorial_focus: str,
    *,
    now=None,
    root=None,
) -> dict:
    """Editor edit/acceptance atomically replaces focus and confirmation time."""
    focus = _text(editorial_focus, "editorial_focus")
    if not focus:
        raise ArticleStoreError("editorial_focus is required")
    with _MUTATION_LOCK:
        record = deepcopy(get_editor_article(article_id, root=root))
        if record["finalized_at"]:
            raise ArticleStoreError("finalized Article focus is immutable")
        confirmed_at = _timestamp(now or _now(), "focus_confirmed_at")
        record["editorial_focus"] = focus
        record["focus_confirmed_at"] = confirmed_at
        record["updated_at"] = confirmed_at
        record["ready_version"] = None
        record["ready_validation_digest"] = None
        record["ready_at"] = None
        return _replace_article(record, root=root)


def save_article_content(
    article_id: str,
    expected_version: int,
    title: str,
    body: str,
    *,
    now=None,
    root=None,
) -> dict:
    """Expected-version Article save; any real edit invalidates readiness."""
    expected = _version(expected_version, "expected_version")
    new_title = _text(title, "title")
    if not isinstance(body, str):
        raise ArticleStoreError("body must be a string")
    new_body = body
    stamp = _timestamp(now or _now(), "content.updated_at")
    with _MUTATION_LOCK:
        record = deepcopy(get_editor_article(article_id, root=root))
        if expected != record["content_version"]:
            raise ArticleVersionConflict(
                f"expected content_version {expected}, current is {record['content_version']}"
            )
        if record["finalized_at"]:
            raise ArticleStoreError("finalized Article content is immutable")
        current = get_article_content(article_id, root=root)
        changed = current["title"] != new_title or current["body"] != new_body
        if not changed:
            return current
        next_version = expected + 1
        content_path = _content_relative_path(article_id, next_version)
        content = _write_content(
            {
                "article_id": article_id,
                "title": new_title,
                "body": new_body,
                "content_version": next_version,
                "updated_at": stamp,
            },
            root=root,
        )
        record["working_title"] = new_title
        record["content_version"] = content["content_version"]
        record["content_path"] = content_path
        record["updated_at"] = stamp
        record["ready_version"] = None
        record["ready_validation_digest"] = None
        record["ready_at"] = None
        # The immutable candidate document is written first. The Article record
        # remains the atomic current-version pointer; a failed pointer update
        # leaves the previous version readable and only an orphan candidate.
        _replace_article(record, root=root)
        return content


def mark_article_ready(
    article_id: str,
    *,
    expected_version: int,
    validation,
    now=None,
    root=None,
) -> dict:
    """Bind readiness to a validation result produced for this exact version."""
    from editor_assistant.workflow import editor_projections

    if not isinstance(validation, ReadinessValidation):
        raise ArticleStoreError("validation must be a ReadinessValidation result")
    expected = _version(expected_version, "expected_version")
    validation_version = _version(validation.content_version, "validation.content_version")
    if validation_version != expected:
        raise ArticleVersionConflict("validation is based on a stale content version")
    if not isinstance(validation.blocking, bool):
        raise ArticleStoreError("validation.blocking must be true or false")
    if validation.blocking:
        raise ArticleStoreError("blocking validation issues prevent readiness")
    digest = _required_text(validation.digest, "validation.digest")
    with _MUTATION_LOCK:
        record = deepcopy(get_editor_article(article_id, root=root))
        content = get_article_content(article_id, root=root)
        if record["content_version"] != expected:
            raise ArticleVersionConflict("readiness checkpoint is based on a stale version")
        if not editor_projections.can_mark_article_ready(record, content):
            raise ArticleStoreError("confirmed focus and non-empty content are required")
        record["ready_version"] = expected
        record["ready_validation_digest"] = digest
        ready_at = _timestamp(now or _now(), "ready_at")
        record["ready_at"] = ready_at
        record["updated_at"] = ready_at
        return _replace_article(record, root=root)
