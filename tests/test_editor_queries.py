"""Phase A read-only composition over the existing canonical stores."""

from __future__ import annotations

from editor_assistant.workflow import (
    editor_article_store,
    editor_queries,
    inbox_store,
    story_editor_metadata,
    story_store,
)


def _inbox_item(item_id: str, *, title: str = "Развитие"):
    return {
        "item_id": item_id,
        "source_id": "source-a",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://example.test/{item_id}",
        "published_at": "2026-09-25T07:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": "Ново",
        "source_kind": "media",
        "status": "NEW",
    }


def _seed(root):
    stories_path = root / "stories.json"
    inbox_path = root / "inbox.jsonl"
    article_root = root / "editorial_workflow"
    origin = _inbox_item("origin", title="Първоначална")
    development = _inbox_item("development")
    inbox_store.save_items([origin, development], inbox_path)
    story = story_store.new_story(origin, publication_key="publication-origin")
    story["story_id"] = "s-one"
    story_store.add_member(
        story,
        development,
        relation="NEW_DEVELOPMENT",
        relation_source="semantic",
        publication_key="publication-development",
        now="2026-09-25T08:00:00Z",
    )
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, stories_path)
    story_editor_metadata.set_story_followed("s-one", True, stories_path=stories_path, root=root)
    article = editor_article_store.create_editor_article(
        story_id="s-one",
        stories_path=stories_path,
        working_title="Работа",
        now="2026-09-25T09:00:00Z",
        root=article_root,
    )
    return stories_path, inbox_path, article_root, article


def test_read_today_composes_story_article_and_writes_no_attention_state(tmp_path):
    stories_path, inbox_path, article_root, article = _seed(tmp_path)
    metadata_path = story_editor_metadata.story_editor_metadata_path(root=tmp_path)
    watched = {
        stories_path: stories_path.read_bytes(),
        inbox_path: inbox_path.read_bytes(),
        metadata_path: metadata_path.read_bytes(),
        editor_article_store.editor_articles_path(
            root=article_root
        ): editor_article_store.editor_articles_path(root=article_root).read_bytes(),
    }

    result = editor_queries.read_today(
        stories_path=stories_path,
        inbox_path=inbox_path,
        metadata_root=tmp_path,
        article_root=article_root,
        article_next_actions={article["article_id"]: "SELECT_FOCUS"},
    )

    assert [entry["attention"] for entry in result["stories"]] == ["FOLLOWED_DEVELOPMENT"]
    assert result["stories"][0]["story"]["unreviewed_development_count"] == 1
    assert result["articles"][0]["article"]["id"] == article["article_id"]
    assert result["articles"][0]["article"]["state"] == "preparation"
    assert result["articles"][0]["next_action"] == "SELECT_FOCUS"
    serialized = str(result)
    assert "internal_refs" not in serialized
    assert "evidence_id" not in serialized
    assert "case_id" not in serialized
    assert all(path.read_bytes() == before for path, before in watched.items())


def test_article_query_returns_narrow_projection_and_hides_internal_refs(tmp_path):
    stories_path, inbox_path, article_root, article = _seed(tmp_path)
    article_root_record = editor_article_store.get_editor_article(
        article["article_id"], root=article_root
    )
    article_root_record["internal_refs"]["idea_id"] = "I-internal"
    editor_article_store.save_editor_articles([article_root_record], root=article_root)

    projected = editor_queries.read_editor_article_projection(
        article["article_id"],
        current_validation_digest=None,
        stories_path=stories_path,
        article_root=article_root,
    )
    story_projection = editor_queries.read_story_editor_projection(
        "s-one",
        stories_path=stories_path,
        inbox_path=inbox_path,
        metadata_root=tmp_path,
        article_root=article_root,
    )

    assert projected["state"] == "preparation"
    assert "internal_refs" not in projected
    assert story_projection["related_articles"][0]["id"] == article["article_id"]


def test_read_today_rejects_orphan_article_lineage(tmp_path):
    stories_path, inbox_path, article_root, article = _seed(tmp_path)
    record = editor_article_store.get_editor_article(article["article_id"], root=article_root)
    orphan = {**record, "article_id": "art_orphan", "story_id": "s-missing"}
    orphan["content_path"] = "editor_articles/art_orphan/v00000000.json"
    editor_article_store.save_editor_articles([record, orphan], root=article_root)

    try:
        editor_queries.read_today(
            stories_path=stories_path,
            inbox_path=inbox_path,
            metadata_root=tmp_path,
            article_root=article_root,
        )
    except editor_queries.EditorQueryError as exc:
        assert "unknown Story" in str(exc)
    else:
        raise AssertionError("orphan Article lineage must fail closed")
