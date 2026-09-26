"""Read-only Phase A composition for canonical editor projections.

This module joins existing validated stores in memory. It exposes no HTTP route,
persists no attention rows, and keeps internal Idea/Evidence/Case/Draft fields out
of returned dictionaries.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from editor_assistant.workflow import (
    editor_article_store,
    editor_projections,
    editorial_title,
    inbox_store,
    source_health,
    story_editor_metadata,
    story_store,
)

#: Calendar days of recency Today keeps, counted backwards from the current
#: `Europe/Sofia` date. `1` means "today plus the previous calendar day".
#:
#: A calendar horizon, not a rolling 24-hour window, because editorial work is
#: calendar-based: the morning editor still sees yesterday evening, and a
#: backlog that is several days old leaves the first screen on its own instead
#: of requiring anybody to mark it reviewed.
TODAY_HORIZON_PREVIOUS_DAYS = 1

#: Hard bound on Story attention rows. Today is an attention surface, not the
#: Story database: an editor should be able to scan the first screen without
#: receiving 251 decisions at once. The complete collection stays reachable
#: under «Истории», and the remainder is reported as a count, never silently
#: dropped.
TODAY_STORY_CAP = 30


class EditorQueryError(ValueError):
    """Editor records cannot be composed into a valid projection."""


def today_horizon_start(now=None) -> date:
    """The oldest `Europe/Sofia` calendar date Today still considers current."""
    return source_health.sofia_date(now) - timedelta(days=TODAY_HORIZON_PREVIOUS_DAYS)


def story_is_within_horizon(story: dict, *, horizon_start: date) -> bool:
    """Whether a Story's canonical change timestamp is inside the horizon.

    Both sides are real `Europe/Sofia` calendar dates, so a naive date is never
    compared and the server's own timezone is never inferred. A Story whose
    timestamp cannot be read is *not* current: nothing proves it arrived.
    """
    moment = source_health.parse_timestamp(editor_projections.story_chronology_at(story))
    if moment is None:
        return False
    return source_health.sofia_date(moment) >= horizon_start


def story_editorial_title(story: dict, items_by_id: dict, registry_rows=()) -> str:
    """The Story's editorial title, through the one canonical rule.

    V1.2-G2.1 §A4/§A5. `editor_queries` and `editor_application` both need the
    Story headline, and both must produce the same string: a Today row and the
    Story it opens may never disagree about what the story is called. The
    cleaning rule itself lives in `editorial_title`; this is only the lookup of
    which publication supplies the title.
    """
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    developments = editor_projections.meaningful_developments(story, items_by_id)
    item = (
        representative if representative.get("title") else (developments[0] if developments else {})
    )
    return editorial_title.editorial_title_for_item(item, registry_rows=registry_rows)


def _metadata_by_story(rows) -> dict[str, dict]:
    return {row["story_id"]: row for row in rows}


def _story_ids(stories) -> set[str]:
    return {story["story_id"] for story in stories}


def read_editor_article_projection(
    article_id: str,
    *,
    current_validation_digest: str | None,
    stories_path,
    inbox_path=None,
    article_root=None,
) -> dict:
    """Read one Article with its canonical Story reference and current content."""
    stories = story_store.read_store(stories_path)["stories"]
    stories_by_id = {story["story_id"]: story for story in stories}
    article = editor_article_store.get_editor_article(article_id, root=article_root)
    if article["story_id"] not in stories_by_id:
        raise EditorQueryError(f"Article references an unknown Story: {article['story_id']}")
    content = editor_article_store.get_article_content(article_id, root=article_root)
    story = stories_by_id[article["story_id"]]
    title = ""
    if inbox_path is not None:
        items_by_id = {row["item_id"]: row for row in inbox_store.read_items(inbox_path)}
        title = story_editorial_title(story, items_by_id, registry_rows=_registry_rows(inbox_path))
    story_reference = {"id": story["story_id"]}
    if title:
        story_reference["title"] = title
    return editor_projections.project_editor_article(
        article, content, current_validation_digest, story_reference
    )


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


def _chronological(rows, *, newest, tie_breaker) -> list[dict]:
    """Newest first on a timestamp key, with an ascending-id tie-break.

    Two stable passes. The id pass establishes a deterministic base order, and
    the timestamp pass then only reorders whole groups of rows, so rows sharing
    a timestamp keep ascending id order. The result is a total, reproducible
    order that is never a reverse sort on a hash-derived id — which is exactly
    what made the previous ordering look random.
    """
    ordered = sorted(rows, key=tie_breaker)
    ordered.sort(key=newest, reverse=True)
    return ordered


def _registry_rows(inbox_path) -> tuple:
    """Registry rows for title cleaning, from the newsroom that owns the inbox."""
    if inbox_path is None:
        return ()
    return editorial_title.load_registry_rows(Path(inbox_path).parent / "sources.json")


def _story_attention_row(
    story: dict, metadata: dict, items_by_id: dict, attention: str, registry_rows=()
) -> dict:
    """One Story attention row: the canonical fields Today needs, precomputed.

    Everything here is an in-memory join over the single snapshot the caller
    already read. The row carries its own title, summary and canonical change
    timestamp so the API layer never re-reads a store to decorate one row.

    `publisherCount` is the number of **independent publishers** the Story has,
    taken from the existing `story_store.metrics` computation (M4C §2.4). It is
    surfaced rather than recomputed, because five discovery rows from one
    publisher must never read as "5 sources" and the frontend has no business
    re-deriving that. It is corroboration context, not evidence authority: a
    Story can have five publishers and still have no opened, promotable page.
    """
    projected = editor_projections.project_story_editor(story, metadata, items_by_id, ())
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    developments = editor_projections.meaningful_developments(story, items_by_id)
    latest = developments[0] if developments else {}
    return {
        "id": story["story_id"],
        "attention": attention,
        "title": story_editorial_title(story, items_by_id, registry_rows=registry_rows),
        "summary": str(representative.get("summary") or latest.get("summary") or ""),
        "latestChangeAt": editor_projections.story_chronology_at(story),
        "unreviewedDevelopmentCount": projected["unreviewed_development_count"],
        "publisherCount": story_store.metrics(story, items_by_id)["publisher_count"],
    }


def project_today(
    *,
    stories,
    metadata,
    items_by_id,
    article_records,
    article_contents,
    validation_digests=None,
    article_next_actions=None,
    now=None,
    story_cap=TODAY_STORY_CAP,
    registry_rows=(),
) -> dict:
    """Pure Today composition; callers provide current validation/action context.

    **Ordering.** Story attention is ordered by the canonical change timestamp
    the editor already sees as `latestChangeAt`, newest first. The previous key
    was `latest_development.changed_at`, which is empty for every Story in the
    real corpus (no member is classified `NEW_DEVELOPMENT`), so the sort
    degenerated into a reverse sort on the hash-derived Story id.

    **Horizon.** Ordinary `NEW_STORY` attention must be current: today or the
    previous calendar day in `Europe/Sofia`. A Story survives the horizon only
    for an explicit current reason — an unreviewed meaningful development —
    never merely because its status is still `NEW`, so an untouched backlog
    retires itself instead of living forever.

    **Cap.** After the horizon, at most `story_cap` Story rows are emitted, and
    the qualifying total is always reported, so a bounded first screen never
    hides the fact that more work exists.
    """
    digests = dict(validation_digests or {})
    next_actions = dict(article_next_actions or {})
    canonical_ids = _story_ids(stories)
    horizon_start = today_horizon_start(now)

    candidates = []
    for story in stories:
        story_id = story["story_id"]
        story_metadata = metadata.get(
            story_id, story_editor_metadata.default_story_editor_metadata(story_id)
        )
        attention = editor_projections.derive_story_attention(story, story_metadata)
        if not attention:
            continue
        current = story_is_within_horizon(story, horizon_start=horizon_start)
        if not current and not editor_projections.has_unreviewed_development(story, story_metadata):
            continue
        candidates.append(
            _story_attention_row(
                story, story_metadata, items_by_id, attention, registry_rows=registry_rows
            )
        )

    candidates = _chronological(
        candidates,
        newest=lambda row: row["latestChangeAt"],
        tie_breaker=lambda row: row["id"],
    )
    total = len(candidates)
    shown = candidates[: max(int(story_cap), 0)]

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

    # Article work is bounded on its own terms and never competes with Story
    # attention for the Story cap, so a full Story list cannot displace an
    # in-progress Article.
    article_entries = _chronological(
        article_entries,
        newest=lambda row: row["article"]["timestamps"]["updated_at"],
        tie_breaker=lambda row: row["article"]["id"],
    )
    return {
        "stories": shown,
        "storyAttentionTotal": total,
        "articles": article_entries,
    }


def read_today(
    *,
    stories_path,
    inbox_path,
    metadata_root=None,
    article_root=None,
    validation_digests=None,
    article_next_actions=None,
    now=None,
    story_cap=TODAY_STORY_CAP,
    registry_rows=(),
) -> dict:
    """Read and derive Today without writing an attention row or queue.

    Every canonical store is read exactly once here and the result is joined
    in memory, so the cost of this projection is proportional to the corpus and
    not to the number of rows it returns. `list_stories` is the reference for
    that batching shape. There is no cache layer: the fix is to stop re-reading
    the same JSON file once per Story, not to remember it.
    """
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
        now=now,
        story_cap=story_cap,
        registry_rows=registry_rows or _registry_rows(inbox_path),
    )
