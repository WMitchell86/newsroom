"""Pure editor-facing projections and derived Today eligibility.

No state is written here. Internal Idea/Evidence/Prepared/Case/model fields
never cross this boundary.
"""

from __future__ import annotations

import hashlib

ACTIVE_ARTICLE_STATES = ("preparation", "draft", "ready")


def readiness_is_current(
    article: dict,
    content: dict,
    current_validation_digest: str | None,
) -> bool:
    """True only for the exact content version and current warning identity."""
    return bool(
        content.get("body", "").strip()
        and article.get("ready_version") == content.get("content_version")
        and article.get("ready_version") == article.get("content_version")
        and article.get("ready_at")
        and article.get("ready_validation_digest")
        and focus_is_confirmed(article)
        and current_validation_digest
        and article.get("ready_validation_digest") == current_validation_digest
    )


def derive_article_state(
    article: dict,
    content: dict,
    current_validation_digest: str | None,
) -> str | None:
    """Derive one of three active states; finalized Articles return ``None``."""
    if article.get("finalized_at"):
        return None
    if not str(content.get("body") or "").strip() and not article.get("draft_established_version"):
        return "preparation"
    if readiness_is_current(article, content, current_validation_digest):
        return "ready"
    return "draft"


def focus_is_confirmed(article: dict) -> bool:
    return bool(article.get("editorial_focus") and article.get("focus_confirmed_at"))


def project_editor_article(
    article: dict,
    content: dict,
    current_validation_digest: str | None,
    story_reference: dict | None = None,
) -> dict:
    """Return the narrow Article editor projection without internal artifacts."""
    state = derive_article_state(article, content, current_validation_digest)
    ready = readiness_is_current(article, content, current_validation_digest)
    return {
        "id": article["article_id"],
        "story": story_reference or {"id": article["story_id"]},
        "title": article["working_title"],
        "focus": {
            "text": article["editorial_focus"],
            "confirmed_at": article["focus_confirmed_at"],
        },
        "state": state,
        "is_finalized": bool(article.get("finalized_at")),
        "content": {
            "title": content["title"],
            "body": content["body"],
            "version": content["content_version"],
        },
        "readiness": {
            "is_current": ready,
            "ready_version": article.get("ready_version"),
            "ready_at": article.get("ready_at"),
        },
        "timestamps": {
            "created_at": article["created_at"],
            "updated_at": article["updated_at"],
            "finalized_at": article.get("finalized_at"),
        },
    }


def publication_id_for(publication_key: str, fallback: str) -> str:
    return "pub_" + hashlib.sha256((publication_key or fallback).encode()).hexdigest()[:15]


def development_id_for(story_id: str, item_id: str) -> str:
    seed = f"{story_id}\0{item_id}".encode()
    return "dev_" + hashlib.sha256(seed).hexdigest()[:15]


def meaningful_developments(story: dict, items_by_id: dict) -> list[dict]:
    """Return editor-facing New Developments, newest first."""
    rows = []
    for member in story.get("members") or []:
        if member.get("relation") != "NEW_DEVELOPMENT":
            continue
        item = items_by_id.get(member.get("item_id")) or {}
        rows.append(
            {
                "id": development_id_for(story["story_id"], member["item_id"]),
                "publication_id": publication_id_for(
                    member.get("publication_key") or "", member["item_id"]
                ),
                "title": item.get("title") or "",
                "summary": item.get("summary") or "",
                "changed_at": item.get("discovered_at") or member.get("added_at") or "",
            }
        )
    return sorted(rows, key=lambda row: (row["changed_at"], row["id"]), reverse=True)


_meaningful_developments = meaningful_developments


def unreviewed_development_ids(story: dict, metadata: dict) -> list[str]:
    reviewed = set(metadata.get("reviewed_development_ids") or [])
    return [row["id"] for row in _meaningful_developments(story, {}) if row["id"] not in reviewed]


def _development_ids(story: dict) -> list[str]:
    return [
        member["item_id"]
        for member in story.get("members") or []
        if member.get("relation") == "NEW_DEVELOPMENT"
    ]


def _metadata_for_story(story: dict, metadata: dict) -> dict:
    if metadata.get("story_id") != story.get("story_id"):
        raise ValueError("Story metadata does not match canonical Story")
    return metadata


def followed_story_has_development(story: dict, metadata: dict) -> bool:
    metadata = _metadata_for_story(story, metadata)
    if not metadata.get("followed") or story.get("status") == "IGNORED":
        return False
    reviewed = set(metadata.get("reviewed_development_ids") or [])
    story_id = story.get("story_id")
    return any(
        development_id_for(story_id, item_id) not in reviewed for item_id in _development_ids(story)
    )


def derive_story_attention(story: dict, metadata: dict) -> str | None:
    """Derive Story attention without persisting an attention row or flag."""
    if story.get("status") == "IGNORED":
        return None
    metadata = _metadata_for_story(story, metadata)
    if story.get("status") == "NEW":
        return "NEW_STORY"
    if followed_story_has_development(story, metadata):
        return "FOLLOWED_DEVELOPMENT"
    return None


def article_today_eligible(
    article: dict,
    content: dict,
    current_validation_digest: str | None,
    *,
    concrete_next_action: str | None,
) -> bool:
    state = derive_article_state(article, content, current_validation_digest)
    return state in ACTIVE_ARTICLE_STATES and bool(concrete_next_action)


def project_story_editor(
    story: dict,
    metadata: dict,
    items_by_id: dict,
    article_records,
) -> dict:
    """Small Story foundation for later API work; no raw backend artifacts."""
    metadata = _metadata_for_story(story, metadata)
    developments = meaningful_developments(story, items_by_id)
    reviewed = set(metadata.get("reviewed_development_ids") or [])
    unreviewed = [row for row in developments if row["id"] not in reviewed]
    related = [
        {"id": row["article_id"], "title": row["working_title"], "updated_at": row["updated_at"]}
        for row in article_records
        if row.get("story_id") == story.get("story_id")
    ]
    return {
        "id": story["story_id"],
        "followed": bool(metadata.get("followed")),
        "reviewed": story.get("status") == "SEEN",
        "ignored": story.get("status") == "IGNORED",
        "last_reviewed_at": metadata.get("last_reviewed_at"),
        "unreviewed_development_ids": [row["id"] for row in unreviewed],
        "unreviewed_development_count": len(unreviewed),
        "latest_development": unreviewed[0] if unreviewed else None,
        "related_articles": related,
    }


def can_mark_article_ready(article: dict, content: dict) -> bool:
    """Focus is a draft/readiness prerequisite; proposed-only text is not."""
    return bool(
        focus_is_confirmed(article)
        and str(content.get("body") or "").strip()
        and not article.get("finalized_at")
    )


def validate_finalization_preconditions(
    article: dict,
    content: dict,
    current_validation_digest: str | None,
) -> None:
    """Pure guard primitive for the later finalization command."""
    if article.get("finalized_at"):
        raise ValueError("Article is already finalized")
    if not can_mark_article_ready(article, content):
        raise ValueError("confirmed focus and non-empty content are required")
    if not readiness_is_current(article, content, current_validation_digest):
        raise ValueError("current readiness checkpoint is required")
