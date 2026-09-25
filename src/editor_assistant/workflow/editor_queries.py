"""Read-only Phase A composition for canonical editor projections.

This module joins existing validated stores in memory. It exposes no HTTP route,
persists no attention rows, and keeps internal Idea/Evidence/Case/Draft fields out
of returned dictionaries.
"""

from __future__ import annotations

from editor_assistant.workflow import (
    editor_article_store,
    editor_projections,
    inbox_store,
    story_editor_metadata,
    story_store,
)


class EditorQueryError(ValueError):
    """Editor records cannot be composed into a valid projection."""


def _metadata_by_story(rows) -> dict[str, dict]:
    return {row["story_id"]: row for row in rows}


def _story_ids(stories) -> set[str]:
    return {story["story_id"] for story in stories}


def read_editor_article_projection(
    article_id: str,
    *,
    current_validation_digest: str | None,
    stories_path,
    article_root=None,
) -> dict:
    """Read one Article with its canonical Story reference and current content."""
    stories = story_store.read_store(stories_path)["stories"]
    article = editor_article_store.get_editor_article(article_id, root=article_root)
    if article["story_id"] not in _story_ids(stories):
        raise EditorQueryError(f"Article references an unknown Story: {article['story_id']}")
    content = editor_article_store.get_article_content(article_id, root=article_root)
    return editor_projections.project_editor_article(article, content, current_validation_digest)


def read_story_editor_projection(
    story_id: str,
    *,
    stories_path,
    inbox_path,
    metadata_root=None,
    article_root=None,
) -> dict:
    """Read the narrow Story editor context from existing canonical stores."""
    store = story_store.read_store(stories_path)
    story = story_store.story_by_id(store, story_id)
    if story is None:
        raise EditorQueryError(f"unknown story_id: {story_id}")
    items = inbox_store.read_items(inbox_path)
    metadata = story_editor_metadata.get_story_editor_metadata(story_id, root=metadata_root)
    articles = editor_article_store.read_editor_articles(root=article_root)
    return editor_projections.project_story_editor(
        story,
        metadata,
        {item["item_id"]: item for item in items},
        articles,
    )


def project_today(
    *,
    stories,
    metadata,
    items_by_id,
    article_records,
    article_contents,
    validation_digests=None,
    article_next_actions=None,
) -> dict:
    """Pure Today composition; callers provide current validation/action context."""
    digests = dict(validation_digests or {})
    next_actions = dict(article_next_actions or {})
    canonical_ids = _story_ids(stories)
    story_entries = []
    for story in stories:
        story_id = story["story_id"]
        try:
            story_metadata = metadata[story_id]
        except KeyError as exc:
            raise EditorQueryError(f"missing Story editor metadata: {story_id}") from exc
        projected = editor_projections.project_story_editor(
            story, story_metadata, items_by_id, article_records
        )
        attention = editor_projections.derive_story_attention(story, story_metadata)
        if attention:
            story_entries.append({"attention": attention, "story": projected})

    article_entries = []
    for article in article_records:
        article_id = article["article_id"]
        if article["story_id"] not in canonical_ids:
            raise EditorQueryError(
                f"Article {article_id} references an unknown Story: {article['story_id']}"
            )
        try:
            content = article_contents[article_id]
        except KeyError as exc:
            raise EditorQueryError(f"missing Article content: {article_id}") from exc
        next_action = next_actions.get(article_id)
        if editor_projections.article_today_eligible(
            article,
            content,
            digests.get(article_id),
            concrete_next_action=next_action,
        ):
            projected = editor_projections.project_editor_article(
                article, content, digests.get(article_id)
            )
            article_entries.append({"next_action": next_action, "article": projected})

    story_entries.sort(
        key=lambda row: (
            ((row["story"].get("latest_development") or {}).get("changed_at") or ""),
            row["story"]["id"],
        ),
        reverse=True,
    )
    article_entries.sort(
        key=lambda row: (row["article"]["timestamps"]["updated_at"], row["article"]["id"]),
        reverse=True,
    )
    return {"stories": story_entries, "articles": article_entries}


def read_today(
    *,
    stories_path,
    inbox_path,
    metadata_root=None,
    article_root=None,
    validation_digests=None,
    article_next_actions=None,
) -> dict:
    """Read and derive Today without writing an attention row or queue."""
    store = story_store.read_store(stories_path)
    stories = store["stories"]
    items = inbox_store.read_items(inbox_path)
    metadata = story_editor_metadata.read_story_editor_metadata_store(root=metadata_root)["stories"]
    articles = editor_article_store.read_editor_articles(root=article_root)
    canonical_ids = _story_ids(stories)
    for article in articles:
        if article["story_id"] not in canonical_ids:
            raise EditorQueryError(
                f"Article {article['article_id']} references an unknown Story: {article['story_id']}"
            )
    contents = {
        row["article_id"]: editor_article_store.get_article_content(
            row["article_id"], root=article_root
        )
        for row in articles
    }
    unknown_metadata = sorted(set(_metadata_by_story(metadata)) - canonical_ids)
    if unknown_metadata:
        raise EditorQueryError(f"metadata references unknown Stories: {unknown_metadata}")
    return project_today(
        stories=stories,
        metadata=_metadata_by_story(metadata),
        items_by_id={row["item_id"]: row for row in items},
        article_records=articles,
        article_contents=contents,
        validation_digests=validation_digests,
        article_next_actions=article_next_actions,
    )
