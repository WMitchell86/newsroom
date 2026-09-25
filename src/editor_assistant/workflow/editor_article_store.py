"""Canonical editor Article records and Article-keyed working content.

This store sits beside the mature Idea/Evidence/Case/Draft workflow. It never
reads, mutates, or substitutes an immutable generated Draft. Article state is
intentionally not persisted here; it is derived by ``editor_projections``.

C5 adds the finalized snapshot: the one immutable canonical document written by
`Финализирай`. It lives beside the Article's versioned content documents
(`editor_articles/{article_id}/`) and is keyed by the same `article_id`, so the
Archive never becomes a second, unrelated identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
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
    # Durable Draft identity and audit currency. These are not workflow states:
    # they preserve the fact that a real Draft existed and which generated
    # content version the immutable generation audit assessed.
    "draft_established_version",
    "generated_content_version",
}
INTERNAL_REF_FIELDS = {"idea_id", "evidence_id", "case_id", "draft_id"}
CONTENT_FIELDS = {"article_id", "title", "body", "content_version", "updated_at"}
#: The immutable finalized Article. It is the Archive's canonical content, so
#: every field here is a frozen editorial fact: the final text, the exact
#: content version, the readiness digest that authorized finalization, the
#: Story lineage and the evidence/source traceability an audit needs.
FINALIZED_FIELDS = {
    "article_id",
    "story_id",
    "title",
    "body",
    "editorial_focus",
    "focus_confirmed_at",
    "content_version",
    "ready_version",
    "ready_validation_digest",
    "ready_at",
    "finalized_at",
    "evidence",
}
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


@contextmanager
def _cross_process_article_lock(*, root=None):
    import fcntl

    path = Path(root or editorial_workflow_dir()) / "editor_articles.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
    missing = sorted(
        (ARTICLE_FIELDS - {"draft_established_version", "generated_content_version"}) - set(raw)
    )
    if missing:
        raise ArticleStoreError(f"Article missing fields: {missing}")
    article_id = _article_id(raw["article_id"])
    expected_path = _content_relative_path(
        article_id, _version(raw["content_version"], "content_version")
    )
    if raw["content_path"] != expected_path:
        raise ArticleStoreError(f"content_path must be {expected_path!r}")
    content_version = _version(raw["content_version"], "content_version")
    internal_refs = _validate_internal_refs(raw["internal_refs"])
    # C3 adds durable Draft/audit markers. Existing C1/C2 records predate those
    # fields, so normalize them on read instead of invalidating real stores.
    raw_draft_version = raw.get("draft_established_version")
    raw_generated_version = raw.get("generated_content_version")
    if raw_draft_version is None and any(internal_refs.values()):
        # Legacy lineage proves that a Draft existed, but not which version its
        # generation audit assessed. Never resurrect stale warnings by guessing.
        raw_draft_version = content_version
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
    draft_established_version = (
        None
        if raw_draft_version is None
        else _version(raw_draft_version, "draft_established_version")
    )
    generated_content_version = (
        None
        if raw_generated_version is None
        else _version(raw_generated_version, "generated_content_version")
    )
    if draft_established_version is not None and draft_established_version > content_version:
        raise ArticleStoreError("draft_established_version cannot exceed content_version")
    if generated_content_version is not None and generated_content_version > content_version:
        raise ArticleStoreError("generated_content_version cannot exceed content_version")
    if generated_content_version is not None and draft_established_version is None:
        raise ArticleStoreError("generated_content_version requires a durable Draft")
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
        "internal_refs": internal_refs,
        "ready_version": ready_version,
        "ready_validation_digest": ready_digest,
        "ready_at": ready_at,
        "finalized_at": finalized_at,
        "draft_established_version": draft_established_version,
        "generated_content_version": generated_content_version,
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


def _article_id_for(
    story_id: str, created_at: str, existing_ids, *, idempotency_key: str = ""
) -> str:
    # A retried command with the same key deterministically addresses the same
    # canonical Article. A later intentional command uses a fresh key (or no
    # key) and therefore remains a distinct Article.
    seed = (
        f"editor-article-start\0{story_id}\0{idempotency_key}"
        if idempotency_key
        else f"editor-article\0{story_id}\0{created_at}"
    )
    base = hashlib.sha256(seed.encode()).hexdigest()[:15]
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
    idempotency_key: str = "",
) -> dict:
    """Create explicit canonical Story lineage plus empty Article content."""
    story = _required_text(story_id, "story_id")
    request_key = _text(idempotency_key, "idempotency_key")
    created = _timestamp(now or _now(), "created_at")
    with _MUTATION_LOCK, _cross_process_article_lock(root=root):
        canonical = story_store.story_by_id(story_store.read_store(stories_path), story)
        if canonical is None:
            raise ArticleStoreError(f"unknown canonical story_id: {story}")
        rows = read_editor_articles(root=root)
        title = _text(working_title, "working_title")
        focus = _text(editorial_focus, "editorial_focus")
        if request_key:
            existing = next(
                (
                    row
                    for row in rows
                    if row["article_id"]
                    == _article_id_for(story, created, set(), idempotency_key=request_key)
                ),
                None,
            )
            if existing is not None:
                if existing["story_id"] != story:
                    raise ArticleStoreError("idempotency key belongs to another Story")
                get_article_content(existing["article_id"], root=root)
                return existing
        article_id = _article_id_for(
            story,
            created,
            {r["article_id"] for r in rows},
            idempotency_key=request_key,
        )
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
                "draft_established_version": None,
                "generated_content_version": None,
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


def update_article_title(
    article_id: str, expected_version: int, title: str, *, now=None, root=None
) -> dict:
    """Update only the working title while preserving the current Article body."""
    with _MUTATION_LOCK:
        record = get_editor_article(article_id, root=root)
        content = get_article_content(article_id, root=root)
        if record["finalized_at"]:
            raise ArticleStoreError("finalized Article title is immutable")
        return {
            "content": save_article_content(
                article_id,
                expected_version,
                title,
                content["body"],
                now=now,
                root=root,
            ),
            "article": get_editor_article(article_id, root=root),
        }


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
    with _MUTATION_LOCK, _cross_process_article_lock(root=root):
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
    with _MUTATION_LOCK, _cross_process_article_lock(root=root):
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
        if new_body.strip() and record["draft_established_version"] is None:
            record["draft_established_version"] = next_version
        # The immutable candidate document is written first. The Article record
        # remains the atomic current-version pointer; a failed pointer update
        # leaves the previous version readable and only an orphan candidate.
        _replace_article(record, root=root)
        return content


def publish_generated_draft(
    article_id: str,
    expected_version: int,
    *,
    title: str,
    body: str,
    internal_refs=None,
    now=None,
    root=None,
) -> dict:
    """Publish one server-generated Draft as the Article's working content.

    Same expected-version contract as `save_article_content`, plus the internal
    refs of the generation that produced the text. The immutable content
    document is written first and the Article record - the atomic current-version
    pointer that also carries the internal refs - last, so an interrupted
    publication leaves the previous version readable and only an orphan
    candidate. A real content change always invalidates readiness, exactly like
    an editor edit.
    """
    expected = _version(expected_version, "expected_version")
    new_title = _text(title, "title")
    if not isinstance(body, str) or not body.strip():
        raise ArticleStoreError("a generated Draft must carry real text")
    refs = _validate_internal_refs(internal_refs or {})
    stamp = _timestamp(now or _now(), "content.updated_at")
    with _MUTATION_LOCK, _cross_process_article_lock(root=root):
        record = deepcopy(get_editor_article(article_id, root=root))
        if expected != record["content_version"]:
            raise ArticleVersionConflict(
                f"expected content_version {expected}, current is {record['content_version']}"
            )
        if record["finalized_at"]:
            raise ArticleStoreError("finalized Article content is immutable")
        next_version = expected + 1
        content = _write_content(
            {
                "article_id": article_id,
                "title": new_title,
                "body": body,
                "content_version": next_version,
                "updated_at": stamp,
            },
            root=root,
        )
        record["working_title"] = new_title
        record["content_version"] = content["content_version"]
        record["content_path"] = _content_relative_path(article_id, next_version)
        record["updated_at"] = stamp
        record["internal_refs"] = refs
        record["ready_version"] = None
        record["ready_validation_digest"] = None
        record["ready_at"] = None
        record["draft_established_version"] = next_version
        record["generated_content_version"] = next_version
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
    with _MUTATION_LOCK, _cross_process_article_lock(root=root):
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


# ------------------------------------------------------ C5 «Финализирай» storage


def finalized_article_path(article_id: str, *, root=None) -> Path:
    """The one immutable finalized document, keyed by the canonical article_id."""
    safe_id = _article_id(article_id)
    return Path(root or editorial_workflow_dir()) / "editor_articles" / safe_id / "finalized.json"


def _validate_evidence(raw) -> dict:
    """Frozen evidence/source traceability: enough for an audit, never raw audits.

    Only what the editor was shown at finalization time is kept: the canonical
    facts with their source identity and locator, plus the open questions and
    the moment the basis was assessed. No internal Case, Draft or model row.
    """
    if raw is None:
        return {"facts": [], "missing": {"items": [], "assessedAt": None}}
    if not isinstance(raw, dict):
        raise ArticleStoreError("finalized evidence must be an object")
    unknown = sorted(set(raw) - {"facts", "missing"})
    if unknown:
        raise ArticleStoreError(f"unknown finalized evidence fields {unknown}")
    facts = raw.get("facts") or []
    if not isinstance(facts, list):
        raise ArticleStoreError("finalized evidence facts must be a list")
    missing = raw.get("missing") or {}
    if not isinstance(missing, dict):
        raise ArticleStoreError("finalized evidence missing must be an object")
    return {
        "facts": [dict(row) for row in facts if isinstance(row, dict)],
        "missing": {
            "items": [dict(row) for row in (missing.get("items") or []) if isinstance(row, dict)],
            "assessedAt": missing.get("assessedAt") or None,
        },
    }


def validate_finalized_article(raw) -> dict:
    if not isinstance(raw, dict):
        raise ArticleStoreError("a finalized Article must be an object")
    unknown = sorted(set(raw) - FINALIZED_FIELDS)
    if unknown:
        raise ArticleStoreError(
            f"unknown finalized Article fields {unknown} (allowed: {sorted(FINALIZED_FIELDS)})"
        )
    missing = sorted(FINALIZED_FIELDS - set(raw))
    if missing:
        raise ArticleStoreError(f"finalized Article missing fields: {missing}")
    content_version = _version(raw["content_version"], "finalized.content_version")
    ready_version = _version(raw["ready_version"], "finalized.ready_version")
    if ready_version != content_version:
        raise ArticleStoreError("a finalized Article freezes one exact ready content version")
    body = raw["body"]
    if not isinstance(body, str) or not body.strip():
        raise ArticleStoreError("a finalized Article must carry real text")
    return {
        "article_id": _article_id(raw["article_id"]),
        "story_id": _required_text(raw["story_id"], "finalized.story_id"),
        "title": _required_text(raw["title"], "finalized.title"),
        "body": body,
        "editorial_focus": _text(raw["editorial_focus"], "finalized.editorial_focus"),
        "focus_confirmed_at": _timestamp(
            raw["focus_confirmed_at"], "finalized.focus_confirmed_at", nullable=True
        ),
        "content_version": content_version,
        "ready_version": ready_version,
        "ready_validation_digest": _required_text(
            raw["ready_validation_digest"], "finalized.ready_validation_digest"
        ),
        "ready_at": _timestamp(raw["ready_at"], "finalized.ready_at"),
        "finalized_at": _timestamp(raw["finalized_at"], "finalized.finalized_at"),
        "evidence": _validate_evidence(raw["evidence"]),
    }


def reopen_article(article_id: str, *, now=None, root=None) -> dict:
    """`Готова → Чернова`: drop the readiness checkpoint, keep everything else.

    The Article id, Story lineage, title, body, focus, generated Draft markers
    and internal refs are all preserved, and no content version is created:
    reopening is a decision, not an edit. The editor must run the review cycle
    again and press `Отбележи като готова` once more - an unchanged body never
    becomes `Готова` by itself.
    """
    with _MUTATION_LOCK, _cross_process_article_lock(root=root):
        record = deepcopy(get_editor_article(article_id, root=root))
        if record["finalized_at"]:
            raise ArticleStoreError("a finalized Article cannot be reopened")
        content = get_article_content(article_id, root=root)
        if record["ready_version"] is None:
            raise ArticleStoreError("only a ready Article can be reopened")
        if not str(content.get("body") or "").strip():
            raise ArticleStoreError("a ready Article must carry real text")
        record["ready_version"] = None
        record["ready_validation_digest"] = None
        record["ready_at"] = None
        record["updated_at"] = _timestamp(now or _now(), "updated_at")
        return _replace_article(record, root=root)


def finalize_article(
    article_id: str,
    *,
    expected_version: int,
    validation,
    evidence=None,
    now=None,
    root=None,
) -> dict:
    """Freeze one exact validated Article as the canonical finalized snapshot.

    The caller revalidates first and passes the result; this store only binds
    the freeze to that exact version and digest. A finalized Article can never
    be rewritten: a repeated call with the same version and digest returns the
    snapshot that already exists, and anything else is refused.
    """
    expected = _version(expected_version, "expected_version")
    if not isinstance(validation, ReadinessValidation):
        raise ArticleStoreError("validation must be a ReadinessValidation result")
    validation_version = _version(validation.content_version, "validation.content_version")
    if validation_version != expected:
        raise ArticleVersionConflict("validation is based on a stale content version")
    if validation.blocking:
        raise ArticleStoreError("blocking validation issues prevent finalization")
    digest = _required_text(validation.digest, "validation.digest")
    with _MUTATION_LOCK, _cross_process_article_lock(root=root):
        record = deepcopy(get_editor_article(article_id, root=root))
        existing = read_finalized_article(article_id, root=root)
        if existing is not None:
            # A repeated attempt returns the same canonical finalized Article
            # instead of creating a second Archive entry.
            if (
                existing["content_version"] == expected
                and existing["ready_validation_digest"] == digest
            ):
                return existing
            raise ArticleStoreError("a finalized Article is immutable")
        if record["finalized_at"]:
            raise ArticleStoreError("a finalized Article is immutable")
        content = get_article_content(article_id, root=root)
        if record["content_version"] != expected:
            raise ArticleVersionConflict("finalization is based on a stale content version")
        if record["ready_version"] != expected or record["ready_validation_digest"] != digest:
            raise ArticleStoreError("a current readiness checkpoint is required")
        if (
            not str(content.get("title") or "").strip()
            or not str(content.get("body") or "").strip()
        ):
            raise ArticleStoreError("a finalized Article requires a title and text")
        if not (record["editorial_focus"] and record["focus_confirmed_at"]):
            raise ArticleStoreError("a finalized Article requires confirmed editorial focus")
        stamp = _timestamp(now or _now(), "finalized_at")
        snapshot = validate_finalized_article(
            {
                "article_id": article_id,
                "story_id": record["story_id"],
                "title": content["title"],
                "body": content["body"],
                "editorial_focus": record["editorial_focus"],
                "focus_confirmed_at": record["focus_confirmed_at"],
                "content_version": expected,
                "ready_version": record["ready_version"],
                "ready_validation_digest": record["ready_validation_digest"],
                "ready_at": record["ready_at"],
                "finalized_at": stamp,
                "evidence": evidence,
            }
        )
        # The immutable snapshot becomes durable first; the Article record - the
        # atomic pointer the Archive and Today read - is written last, so an
        # interrupted run leaves an orphan snapshot, never a half-finalized
        # Article. A retry with the same version and digest reuses the snapshot.
        path = finalized_article_path(article_id, root=root)
        payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
        live_store.atomic_write(path, payload)
        record["finalized_at"] = stamp
        record["updated_at"] = stamp
        _replace_article(record, root=root)
        return snapshot


def read_finalized_article(article_id: str, *, root=None) -> dict | None:
    """The finalized snapshot, or `None` when the Article was never finalized."""
    path = finalized_article_path(article_id, root=root)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArticleStoreError(f"finalized Article is unreadable ({path}): {exc}") from exc
    snapshot = validate_finalized_article(raw)
    if snapshot["article_id"] != article_id:
        raise ArticleStoreError("finalized article_id does not match its path")
    return snapshot
