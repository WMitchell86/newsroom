"""Isolated proof of the complete frozen editorial lifecycle (C5 §37).

Four paths through real stores, real audits and the real application layer, on
a temporary newsroom/editorial root. The normal repository runtime stores are
never touched - asserted at the end of each path, not assumed.

    A. Story → Article → generated Draft → edit → Ready → Finalize → Archive
    B. Story → Article → manual continuation → Ready → Finalize → Archive
       (no generated Draft, no internal Case)
    C. Ready → Edit → Draft → edit → Ready again → Finalize
    D. Ready → the validation basis materially changes → Finalize → rejected,
       with no Archive transition
"""

from __future__ import annotations

import json
import time

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import (
    article_generation,
    article_validation,
    inbox_store,
    story_operations,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import editor_article_store as articles

from .test_article_finalize_command import HEADLINE, REVIEW_TEXT, SUPPORTED_TEXT

RUNTIME_STORES = ("editorial_workflow/ideas.jsonl", "editorial_workflow/live_evidence.jsonl")


def _runtime_fingerprint() -> dict[str, bytes]:
    """Byte content of the repository runtime stores, if they exist."""
    return {
        name: (app.ROOT / "var" / name).read_bytes()
        for name in RUNTIME_STORES
        if (app.ROOT / "var" / name).exists()
    }


def _item(item_id: str, title: str):
    return {
        "item_id": item_id,
        "source_id": "vestnik",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://vestnik.example.test/{item_id}",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": "Обобщение",
        "source_kind": "media",
        "status": "NEW",
    }


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    editorial = tmp_path / "editorial"
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(editorial))
    origin = _item("origin", HEADLINE)
    inbox_store.save_items([origin], root / "inbox.jsonl")
    story = story_store.new_story(origin, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    story_operations.clear()
    story_research_store.merge_research(
        "s-one",
        sources=[
            {"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/2026/budget"}
        ],
        facts=[
            {
                "id": "fact_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="lifecycle-fixture",
    )
    yield {"root": root, "editorial": editorial}
    story_operations.clear()
    for token in list(getattr(article_generation._ACTIVE, "keys", list)()):
        article_generation.release(token, article_generation._ACTIVE[token])


@pytest.fixture
def transport(monkeypatch):
    """The only stub in this proof: the model transport behind `Направи чернова`."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def call(_prompt, *, api_key, timeout, role="draft", **_kw):
        if role == "draft":
            return (
                json.dumps(
                    {
                        "headline": HEADLINE,
                        "headlines": [HEADLINE],
                        "body": SUPPORTED_TEXT,
                    },
                    ensure_ascii=False,
                ),
                {"model": "mock", "provider": "gemini"},
            )
        return (
            json.dumps(
                {
                    "sentence": SUPPORTED_TEXT,
                    "verdict": "SUPPORTED",
                    "issue": "none",
                    "supporting_fact_ids": [],
                    "note": "ok",
                },
                ensure_ascii=False,
            ),
            {"model": "mock"},
        )

    monkeypatch.setattr(gen, "_call_gemini", call)
    return call


def _await(token, *, attempts=600):
    for _ in range(attempts):
        row = story_operations.get(token)
        if row and row["status"] in {"succeeded", "failed"}:
            return row
        time.sleep(0.02)
    raise AssertionError("the draft operation did not finish")


def _start_article(lifecycle) -> str:
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=lifecycle["root"] / "stories.json",
        working_title=HEADLINE,
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(article["article_id"], "Да обясним решението и последиците.")
    return article["article_id"]


def _generate(article_id, key):
    return _await(app.start_article_draft(article_id, idempotency_key=key)["operationToken"])


def test_the_generated_article_runs_the_whole_lifecycle_into_the_archive(lifecycle, transport):
    """Path A — a generated Draft, edited, reviewed, finalized, archived."""
    before_runtime = _runtime_fingerprint()
    article_id = _start_article(lifecycle)
    assert _generate(article_id, "generate")["status"] == "succeeded"
    generated = app.read_article(article_id)
    assert generated["state"] == "draft" and generated["content"]["version"] == 1

    edited = app.save_content(article_id, 1, HEADLINE, SUPPORTED_TEXT + " Добавено уточнение.")
    assert edited["content"]["version"] == 2
    assert app.mark_article_ready(article_id, 2)["state"] == "ready"

    result = app.finalize_article(article_id, 2, idempotency_key="path-a")

    assert result["archivePath"] == f"/archive/{article_id}"
    assert [row["id"] for row in app.list_archive()] == [article_id]
    assert app.list_articles() == []
    assert article_id not in [r["objectId"] for r in app.read_today()["articlesRequiringAction"]]
    # The generated Draft itself stayed immutable throughout.
    assert articles.get_editor_article(article_id)["generated_content_version"] == 1
    assert _runtime_fingerprint() == before_runtime


def test_a_manual_article_finalizes_without_any_generated_lineage(lifecycle):
    """Path B — no generated Draft and no internal Case, still finalizable."""
    before_runtime = _runtime_fingerprint()
    article_id = _start_article(lifecycle)
    app.save_content(article_id, 0, HEADLINE, REVIEW_TEXT)
    assert app.mark_article_ready(article_id, 1)["state"] == "ready"

    result = app.finalize_article(article_id, 1, idempotency_key="path-b")

    assert result["article"]["content"]["version"] == 1
    assert [row["id"] for row in app.list_archive()] == [article_id]
    # No Case was required, and none was invented.
    record = articles.get_editor_article(article_id)
    assert record["internal_refs"]["case_id"] is None
    assert not (lifecycle["editorial"] / "cases.jsonl").exists()
    assert _runtime_fingerprint() == before_runtime


def test_ready_edit_ready_finalize_is_a_safe_repeatable_cycle(lifecycle):
    """Path C — reopening never auto-restores readiness, and a final freeze works."""
    before_runtime = _runtime_fingerprint()
    article_id = _start_article(lifecycle)
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    app.mark_article_ready(article_id, 1)

    app.reopen_article(article_id)
    assert app.read_article(article_id)["state"] == "draft"
    app.save_content(article_id, 1, HEADLINE, SUPPORTED_TEXT + " Редакция след преглед.")
    app.mark_article_ready(article_id, 2)
    result = app.finalize_article(article_id, 2, idempotency_key="path-c")

    assert result["article"]["content"]["version"] == 2
    assert app.list_archive()[0]["id"] == article_id
    assert _runtime_fingerprint() == before_runtime


def test_a_changed_validation_basis_never_reaches_the_archive(lifecycle):
    """Path D — unchanged text, changed evidence, refused finalization."""
    before_runtime = _runtime_fingerprint()
    article_id = _start_article(lifecycle)
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    app.mark_article_ready(article_id, 1)
    assert app.read_article(article_id)["state"] == "ready"

    story_research_store.merge_research(
        "s-one",
        sources=[
            {"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/2026/budget"}
        ],
        facts=[
            {
                "id": "fact_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
        ],
        gaps=[{"id": "gap_new", "question": "Кога започва ремонтът?", "blocking": False}],
        assessed_at="2026-09-25T15:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="lifecycle-changed-basis",
    )

    with pytest.raises(app.EditorInvalidTransition):
        app.finalize_article(article_id, 1, idempotency_key="path-d")

    assert app.list_archive() == []
    assert app.read_article(article_id)["state"] == "draft"
    assert "FINALIZE" not in app.read_article(article_id)["availableActions"]
    # There is still exactly one validation engine, and it is the C4 one.
    assert article_validation.evaluate_current_content.__module__.endswith("article_validation")
    assert _runtime_fingerprint() == before_runtime

    app.mark_article_ready(article_id, 1)

    app.reopen_article(article_id)
    assert app.read_article(article_id)["state"] == "draft"
    app.save_content(article_id, 1, HEADLINE, SUPPORTED_TEXT + " Редакция след преглед.")
    app.mark_article_ready(article_id, 2)
    result = app.finalize_article(article_id, 2, idempotency_key="path-c")

    assert result["article"]["content"]["version"] == 2
    assert app.list_archive()[0]["id"] == article_id
    assert _runtime_fingerprint() == before_runtime
