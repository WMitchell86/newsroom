"""Phase A: canonical editor Article records, working content, focus and readiness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from editor_assistant.workflow import editor_article_store as articles
from editor_assistant.workflow import story_store


@pytest.fixture
def editorial_root(tmp_path, monkeypatch):
    root = tmp_path / "editorial_workflow"
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(root))
    stories = []
    for story_id in ("s-one", "s-two"):
        story = story_store.new_story(
            {
                "item_id": f"origin-{story_id}",
                "discovered_at": "2026-09-20T08:00:00Z",
                "published_at": "2026-09-20T07:00:00Z",
            },
            now="2026-09-20T08:00:00Z",
        )
        story["story_id"] = story_id
        stories.append(story)
    story_store.write_store({"stories": stories}, root.parent / "stories.json")
    return root


def _create(root, **over):
    values = {
        "story_id": "s-one",
        "stories_path": root.parent / "stories.json",
        "working_title": "Работа заглавие",
        "now": "2026-09-25T08:00:00Z",
    }
    values.update(over)
    return articles.create_editor_article(**values)


def test_article_identity_is_stable_requires_story_and_allows_many_per_story(editorial_root):
    first = _create(editorial_root)
    second = _create(editorial_root, now="2026-09-25T08:01:00Z")
    other = _create(editorial_root, story_id="s-two", now="2026-09-25T08:02:00Z")

    assert first["article_id"].startswith("art_")
    assert first["article_id"] == articles.get_editor_article(first["article_id"])["article_id"]
    assert {first["story_id"], second["story_id"]} == {"s-one"}
    assert other["story_id"] == "s-two"
    assert len({first["article_id"], second["article_id"], other["article_id"]}) == 3
    with pytest.raises(articles.ArticleStoreError, match="story_id"):
        _create(editorial_root, story_id="")
    with pytest.raises(articles.ArticleStoreError, match="unknown canonical story_id"):
        _create(editorial_root, story_id="s-missing")
    assert {row["article_id"] for row in articles.read_editor_articles(root=editorial_root)} == {
        first["article_id"],
        second["article_id"],
        other["article_id"],
    }


def test_story_lineage_and_internal_refs_are_strict_and_immutable(editorial_root):
    record = _create(
        editorial_root,
        internal_refs={"idea_id": "I-1", "evidence_id": "E-1", "case_id": "C-1", "draft_id": "D-1"},
    )
    assert record["internal_refs"] == {
        "idea_id": "I-1",
        "evidence_id": "E-1",
        "case_id": "C-1",
        "draft_id": "D-1",
    }
    with pytest.raises(articles.ArticleStoreError, match="story_id"):
        articles.save_editor_articles([{**record, "story_id": "s-moved"}], root=editorial_root)
    raw = {**record, "internal_refs": {**record["internal_refs"], "provider": "secret"}}
    with pytest.raises(articles.ArticleStoreError, match="internal_refs"):
        articles.validate_editor_article(raw)


def test_initial_content_is_empty_then_first_body_and_versions_are_monotonic(editorial_root):
    record = _create(editorial_root)
    content = articles.get_article_content(record["article_id"])
    assert content == {
        "article_id": record["article_id"],
        "title": "Работа заглавие",
        "body": "",
        "content_version": 0,
        "updated_at": record["created_at"],
    }

    content = articles.save_article_content(
        record["article_id"],
        0,
        "Ново заглавие",
        "Първи абзац.",
        now="2026-09-25T09:00:00Z",
    )
    assert content["content_version"] == 1
    assert articles.get_editor_article(record["article_id"])["content_version"] == 1
    assert articles.get_editor_article(record["article_id"])["working_title"] == "Ново заглавие"
    same = articles.save_article_content(record["article_id"], 1, "Ново заглавие", "Първи абзац.")
    assert same["content_version"] == 1
    with pytest.raises(articles.ArticleVersionConflict):
        articles.save_article_content(record["article_id"], 0, "Конфликт", "Ново")


def test_content_reads_are_strict_and_atomic_failure_keeps_existing_bytes(
    editorial_root, monkeypatch
):
    record = _create(editorial_root)
    articles.save_article_content(record["article_id"], 0, "T", "Body")
    content_path = articles.article_content_path(record["article_id"], 1)
    before = content_path.read_bytes()

    def fail_write(_path, _data):
        raise OSError("disk full")

    monkeypatch.setattr(articles.live_store, "atomic_write", fail_write)
    with pytest.raises(OSError, match="disk full"):
        articles.save_article_content(record["article_id"], 1, "T2", "Body2")
    assert content_path.read_bytes() == before
    content_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(articles.ArticleStoreError, match="unreadable"):
        articles.get_article_content(record["article_id"])


def test_working_content_never_mutates_generated_draft_store(editorial_root):
    drafts = editorial_root / "live_drafts.jsonl"
    drafts.parent.mkdir(parents=True, exist_ok=True)
    drafts.write_text('{"draft_id":"generated"}\n', encoding="utf-8")
    before = drafts.read_bytes()
    record = _create(editorial_root)
    articles.save_article_content(record["article_id"], 0, "T", "Manual body")
    assert drafts.read_bytes() == before


def test_editor_focus_update_replaces_text_and_refreshes_confirmation(editorial_root):
    record = _create(editorial_root, editorial_focus="AI предложение")
    assert articles.focus_is_confirmed(record) is False
    confirmed = articles.update_editor_focus(
        record["article_id"], "Редакторски избран фокус.", now="2026-09-25T08:30:00Z"
    )
    assert confirmed["editorial_focus"] == "Редакторски избран фокус."
    assert confirmed["focus_confirmed_at"] == "2026-09-25T08:30:00Z"
    changed = articles.update_editor_focus(
        record["article_id"], "Нов фокус.", now="2026-09-25T08:31:00Z"
    )
    assert changed["focus_confirmed_at"] == "2026-09-25T08:31:00Z"


def test_readiness_rejects_unconfirmed_focus_stale_version_and_blocking_result(editorial_root):
    record = _create(editorial_root, editorial_focus="Предложение")
    articles.save_article_content(record["article_id"], 0, "T", "Body")
    with pytest.raises(articles.ArticleStoreError, match="confirmed focus"):
        articles.mark_article_ready(
            record["article_id"],
            expected_version=1,
            validation=articles.ReadinessValidation(content_version=1, digest="d"),
        )
    articles.update_editor_focus(record["article_id"], "Потвърден фокус")
    with pytest.raises(articles.ArticleVersionConflict):
        articles.mark_article_ready(
            record["article_id"],
            expected_version=1,
            validation=articles.ReadinessValidation(content_version=0, digest="old"),
        )
    with pytest.raises(articles.ArticleStoreError, match="blocking"):
        articles.mark_article_ready(
            record["article_id"],
            expected_version=1,
            validation=articles.ReadinessValidation(
                content_version=1, digest="blocked", blocking=True
            ),
        )


def test_focus_change_after_ready_invalidates_checkpoint(editorial_root):
    from editor_assistant.workflow import editor_projections

    record = _create(editorial_root)
    articles.save_article_content(record["article_id"], 0, "T", "Body")
    articles.update_editor_focus(record["article_id"], "Първи фокус")
    ready = articles.mark_article_ready(
        record["article_id"],
        expected_version=1,
        validation=articles.ReadinessValidation(content_version=1, digest="digest-focus"),
    )
    changed = articles.update_editor_focus(record["article_id"], "Нов фокус")

    assert changed["focus_confirmed_at"] is not None
    assert changed["ready_version"] is None
    assert changed["ready_validation_digest"] is None
    assert changed["ready_at"] is None
    content = articles.get_article_content(record["article_id"])
    assert editor_projections.derive_article_state(changed, content, "digest-focus") == "draft"
    with pytest.raises(ValueError, match="readiness"):
        editor_projections.validate_finalization_preconditions(changed, content, "digest-focus")
    assert ready["ready_version"] == 1


def test_ready_checkpoint_binds_digest_and_content_edit_invalidates_it(editorial_root):
    from editor_assistant.workflow import editor_projections

    record = _create(editorial_root, editorial_focus="Предложение")
    articles.save_article_content(record["article_id"], 0, "T", "Body")
    articles.update_editor_focus(record["article_id"], "Потвърден фокус")
    ready = articles.mark_article_ready(
        record["article_id"],
        expected_version=1,
        validation=articles.ReadinessValidation(content_version=1, digest="warnings-1"),
        now="2026-09-25T10:00:00Z",
    )
    content = articles.get_article_content(record["article_id"])
    assert ready["ready_version"] == 1
    assert ready["ready_validation_digest"] == "warnings-1"
    assert editor_projections.derive_article_state(ready, content, "warnings-1") == "ready"
    assert editor_projections.derive_article_state(ready, content, "warnings-2") == "draft"
    editor_projections.validate_finalization_preconditions(ready, content, "warnings-1")
    edited = articles.save_article_content(record["article_id"], 1, "T", "Changed")
    reopened = articles.get_editor_article(record["article_id"])
    assert edited["content_version"] == 2
    assert reopened["ready_version"] is None
    assert reopened["ready_at"] is None
    assert reopened["ready_validation_digest"] is None
    assert editor_projections.derive_article_state(reopened, edited, "warnings-1") == "draft"
    with pytest.raises(ValueError, match="readiness"):
        editor_projections.validate_finalization_preconditions(reopened, edited, "warnings-1")


def test_article_store_rejects_corrupt_rows_and_impossible_checkpoints(editorial_root):
    record = _create(editorial_root)
    path = articles.editor_articles_path(root=editorial_root)
    path.write_text("{broken\n", encoding="utf-8")
    with pytest.raises(articles.ArticleStoreError, match="line 1"):
        articles.read_editor_articles(root=editorial_root)
    record["state"] = "Готова"
    with pytest.raises(articles.ArticleStoreError, match="unknown Article fields"):
        articles.validate_editor_article(record)
    record.pop("state")
    record["ready_version"] = 0
    with pytest.raises(articles.ArticleStoreError, match="all set or all null"):
        articles.validate_editor_article(record)
    record["ready_at"] = "2026-09-25T09:00:00Z"
    record["ready_validation_digest"] = "digest"
    assert articles.validate_editor_article(record)["ready_version"] == 0
    record["finalized_at"] = "2026-09-25T10:00:00Z"
    record["focus_confirmed_at"] = None
    with pytest.raises(articles.ArticleStoreError, match="confirmed editorial focus"):
        articles.validate_editor_article(record)


def test_article_ids_are_closed_and_cannot_escape_content_directory(editorial_root):
    record = _create(editorial_root)
    with pytest.raises(articles.ArticleStoreError, match="article_id must match"):
        articles.validate_editor_article({**record, "article_id": "../../escape"})
    with pytest.raises(articles.ArticleStoreError, match="article_id must match"):
        articles.article_content_path("../escape", 0, root=editorial_root)


def test_metadata_pointer_failure_keeps_previous_version_readable(editorial_root, monkeypatch):
    record = _create(editorial_root)
    articles.save_article_content(record["article_id"], 0, "T", "Original")
    old_path = articles.article_content_path(record["article_id"], 1)
    before_content = old_path.read_bytes()
    before_record = articles.editor_articles_path(root=editorial_root).read_bytes()
    real_write = articles.live_store.atomic_write

    def fail_index(path, data):
        if Path(path) == articles.editor_articles_path(root=editorial_root):
            raise OSError("index unavailable")
        return real_write(path, data)

    monkeypatch.setattr(articles.live_store, "atomic_write", fail_index)
    with pytest.raises(OSError, match="index unavailable"):
        articles.save_article_content(record["article_id"], 1, "T2", "Changed")
    assert old_path.read_bytes() == before_content
    assert articles.editor_articles_path(root=editorial_root).read_bytes() == before_record
    assert articles.get_article_content(record["article_id"])["body"] == "Original"


def test_creation_failure_removes_orphan_content(editorial_root, monkeypatch):
    real_write = articles.live_store.atomic_write

    def fail_index(path, data):
        if Path(path) == articles.editor_articles_path(root=editorial_root):
            raise OSError("index unavailable")
        return real_write(path, data)

    monkeypatch.setattr(articles.live_store, "atomic_write", fail_index)
    with pytest.raises(OSError, match="index unavailable"):
        _create(editorial_root)
    assert list((editorial_root / "editor_articles").rglob("*.json")) == []


def test_finalized_article_rejects_focus_mutation(editorial_root):
    record = _create(editorial_root)
    articles.save_article_content(record["article_id"], 0, "T", "Body")
    articles.update_editor_focus(record["article_id"], "Confirmed")
    ready = articles.mark_article_ready(
        record["article_id"],
        expected_version=1,
        validation=articles.ReadinessValidation(content_version=1, digest="digest-1"),
    )
    ready["finalized_at"] = "2026-09-25T11:00:00Z"
    articles.save_editor_articles([ready], root=editorial_root)
    before = articles.editor_articles_path(root=editorial_root).read_bytes()
    with pytest.raises(articles.ArticleStoreError, match="focus is immutable"):
        articles.update_editor_focus(record["article_id"], "Changed")
    with pytest.raises(articles.ArticleStoreError, match="record is immutable"):
        articles.save_editor_articles([{**ready, "editorial_focus": "Bypass"}], root=editorial_root)
    assert articles.editor_articles_path(root=editorial_root).read_bytes() == before


def test_content_preserves_text_exactly_and_version_documents_are_immutable(
    editorial_root, monkeypatch
):
    record = _create(editorial_root)
    content = articles.save_article_content(
        record["article_id"], 0, "  Заглавие  ", "  Тяло  \n", now="2026-09-25T09:00:00Z"
    )
    assert content["title"] == "Заглавие"
    assert content["body"] == "  Тяло  \n"

    real_write = articles.live_store.atomic_write

    def fail_index(path, data):
        if Path(path) == articles.editor_articles_path(root=editorial_root):
            raise OSError("index unavailable")
        return real_write(path, data)

    monkeypatch.setattr(articles.live_store, "atomic_write", fail_index)
    with pytest.raises(OSError, match="index unavailable"):
        articles.save_article_content(
            record["article_id"], 1, "Следващо", "Body", now="2026-09-25T09:01:00Z"
        )
    monkeypatch.setattr(articles.live_store, "atomic_write", real_write)
    retried = articles.save_article_content(
        record["article_id"], 1, "Следващо", "Body", now="2026-09-25T09:01:00Z"
    )
    assert retried["content_version"] == 2
    assert articles.get_article_content(record["article_id"]) == retried


def test_active_article_records_cannot_be_removed_or_replaced(editorial_root):
    first = _create(editorial_root)
    second = _create(editorial_root, now="2026-09-25T08:01:00Z")
    rows = articles.read_editor_articles(root=editorial_root)
    with pytest.raises(articles.ArticleStoreError, match="cannot remove"):
        articles.save_editor_articles([first], root=editorial_root)
    replacement = {
        **second,
        "article_id": first["article_id"],
        "content_path": first["content_path"],
    }
    with pytest.raises(articles.ArticleStoreError, match="cannot remove"):
        articles.save_editor_articles([first, replacement], root=editorial_root)
    assert articles.read_editor_articles(root=editorial_root) == rows


def test_schema_rejects_wrong_types_timestamps_and_content_title_drift(editorial_root):
    record = _create(editorial_root)
    with pytest.raises(articles.ArticleStoreError, match="working_title must be a string"):
        articles.validate_editor_article({**record, "working_title": 7})
    with pytest.raises(articles.ArticleStoreError, match="timezone"):
        articles.validate_editor_article({**record, "updated_at": "2026-09-25"})
    content = articles.get_article_content(record["article_id"])
    path = articles.article_content_path(record["article_id"], 0, root=editorial_root)
    path.write_text(json.dumps({**content, "title": "Друг"}), encoding="utf-8")
    with pytest.raises(articles.ArticleStoreError, match="title does not match"):
        articles.get_article_content(record["article_id"])
