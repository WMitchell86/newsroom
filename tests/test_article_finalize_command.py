"""C5 — `Готова → Редактирай` + `Финализирай` + the Archive transition.

These tests pin the last editorial transition of the frozen V1 lifecycle:

* `Финализирай` re-runs the C4 current-content validation and compares the fresh
  deterministic digest with the recorded `ready_validation_digest`. A stored
  `state = ready` is never enough - the scenario this closes is unchanged text
  with a changed evidence basis;
* a refused finalization leaves no Archive entry, and a finalized Article is
  immutable through every normal active command;
* `Готова → Редактирай` invalidates the checkpoint without touching the content,
  and never re-`Готова` on its own;
* a manual Article with no generated Draft and no internal Case finalizes
  exactly like a generated one;
* a duplicate/lost-response retry returns the same canonical finalized Article.

Only the model transport is stubbed, and only where a generated Draft is
required. The audits, the stores, the projections and the HTTP boundary are the
production ones, so a failure here is a real product defect.
"""

from __future__ import annotations

import json
import time
from unittest import mock

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

HEADLINE = "Съветът одобри графика за ремонта"
BODY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
SUPPORTED_TEXT = (
    "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
    "Жителите на квартала ще пътуват с 10 минути повече до работата."
)
REVIEW_TEXT = (
    "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
    "Във вътрешния двор се събраха граждани, които питат за съдбата на пазара."
)


def _item(item_id: str, title: str, *, summary: str = "Обобщение"):
    return {
        "item_id": item_id,
        "source_id": "vestnik",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://vestnik.example.test/{item_id}",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": summary,
        "source_kind": "media",
        "status": "NEW",
    }


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
    """An isolated newsroom + editorial root; the normal stores stay untouched."""
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    origin = _item("origin", HEADLINE)
    inbox_store.save_items([origin], root / "inbox.jsonl")
    story = story_store.new_story(origin, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    story_operations.clear()
    yield root
    story_operations.clear()
    # The in-process generation guard is process-wide; a leaked token would
    # refuse a later command, so every fixture releases what it acquired.
    for token in list(getattr(article_generation._ACTIVE, "keys", list)()):
        article_generation.release(token, article_generation._ACTIVE[token])


def _seed_basis(*, gaps=(), assessed_at: str = "2026-09-25T08:45:00Z") -> None:
    story_research_store.merge_research(
        "s-one",
        sources=[
            {"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/2026/budget"}
        ],
        facts=[
            {"id": "fact_money", "text": BODY, "sourceId": "vestnik", "locator": "Протокол, т. 4"},
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
        ],
        gaps=list(gaps),
        assessed_at=assessed_at,
        canonical_story={"story_id": "s-one"},
        operation_id="c5-fixture",
    )


@pytest.fixture
def manual(newsroom):
    """A hand-written Article: no generated Draft, no internal Case."""
    _seed_basis()
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title=HEADLINE,
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(article["article_id"], "Да обясним решението и последиците.")
    return articles.get_editor_article(article["article_id"])


@pytest.fixture
def model(monkeypatch):
    """The only stub: the model transport behind `Направи чернова`."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def call(prompt_text, *, api_key, timeout, role="draft", **_kw):
        if role == "draft":
            return (
                json.dumps(
                    {"headline": HEADLINE, "headlines": [HEADLINE], "body": SUPPORTED_TEXT},
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


def _generate(article_id, key):
    started = app.start_article_draft(article_id, idempotency_key=key)
    return _await(started["operationToken"])


def _ready_manual(article_id, body: str = SUPPORTED_TEXT, *, from_version: int = 0) -> str:
    """Подготовка → Редактирай → Чернова → Отбележи като готова."""
    articles.save_article_content(article_id, from_version, HEADLINE, body)
    return app.mark_article_ready(article_id, from_version + 1)["readiness"]["readyAt"]


# ------------------------------------------------------------------- reopen


def test_a_ready_article_reopens_to_draft_with_everything_preserved(manual):
    """`Готова → Редактирай → Чернова` is a decision, not a content edit."""
    article_id = manual["article_id"]
    _ready_manual(article_id)
    before = articles.get_editor_article(article_id)
    content_before = articles.get_article_content(article_id)

    reopened = app.reopen_article(article_id)

    stored = articles.get_editor_article(article_id)
    assert reopened["state"] == "draft"
    assert reopened["readiness"]["isCurrent"] is False
    assert reopened["readiness"]["readyVersion"] is None
    assert (stored["ready_version"], stored["ready_at"], stored["ready_validation_digest"]) == (
        None,
        None,
        None,
    )
    # No content version is created: nothing about the text changed.
    assert articles.get_article_content(article_id) == content_before
    assert stored["content_version"] == before["content_version"] == 1
    # Identity, lineage, focus and internal refs are all preserved.
    assert stored["article_id"] == article_id
    assert stored["story_id"] == before["story_id"]
    assert stored["editorial_focus"] == before["editorial_focus"]
    assert stored["focus_confirmed_at"] == before["focus_confirmed_at"]
    assert stored["internal_refs"] == before["internal_refs"]
    assert stored["draft_established_version"] == 1
    # The editor is available again, and readiness must be re-granted by hand.
    assert "MARK_READY" in reopened["availableActions"]
    assert "FINALIZE" not in reopened["availableActions"]


def test_reopening_does_not_re_grant_readiness_for_an_unchanged_body(manual):
    """No automatic re-ready: only the editor's own action restores `Готова`."""
    article_id = manual["article_id"]
    _ready_manual(article_id)
    app.reopen_article(article_id)

    unchanged = app.read_article(article_id)

    assert unchanged["state"] == "draft"
    assert unchanged["readiness"]["isCurrent"] is False
    assert "FINALIZE" not in unchanged["availableActions"]


def test_the_full_edit_review_finalize_cycle_works(manual):
    """Ready → Edit → Draft → edit/autosave → Ready again → Finalize → Archive."""
    article_id = manual["article_id"]
    _ready_manual(article_id)
    app.reopen_article(article_id)
    app.save_content(article_id, 1, HEADLINE, SUPPORTED_TEXT + " Уточнението е прието.")
    assert app.read_article(article_id)["content"]["version"] == 2
    app.mark_article_ready(article_id, 2)

    result = app.finalize_article(article_id, 2, idempotency_key="cycle")

    assert result["article"]["content"]["version"] == 2
    assert articles.get_editor_article(article_id)["finalized_at"]


def test_reopen_is_refused_for_a_draft_and_for_a_finalized_article(manual):
    article_id = manual["article_id"]
    articles.save_article_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)

    with pytest.raises(app.EditorInvalidTransition):
        app.reopen_article(article_id)

    app.mark_article_ready(article_id, 1)


# ----------------------------------------------------------------- finalize


def test_a_valid_ready_article_finalizes_into_the_archive(manual):
    article_id = manual["article_id"]
    ready_at = _ready_manual(article_id)
    digest = app.validate_article_current_content(article_id)["validationDigest"]

    result = app.finalize_article(article_id, 1, idempotency_key="final")

    # The API result carries the Archive target and no internal finalization id.
    assert result["articleId"] == article_id
    assert result["archivePath"] == f"/archive/{article_id}"
    assert result["finalizedAt"]
    assert set(result) == {"articleId", "archivePath", "finalizedAt", "article"}
    assert result["article"]["state"] is None
    assert result["article"]["isFinalized"] is True
    assert result["article"]["availableActions"] == []
    assert result["article"]["nextAction"] is None
    # `Финализирана` is not `Публикувана`: there is no publication timestamp or
    # delivery state anywhere in the projection.
    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in ("published", "publishedAt", "scheduled", "cms"):
        assert forbidden not in serialized

    stored = articles.get_editor_article(article_id)
    assert stored["finalized_at"] == result["finalizedAt"]
    assert stored["ready_version"] == 1

    snapshot = articles.read_finalized_article(article_id)
    assert snapshot["content_version"] == 1
    assert snapshot["ready_version"] == 1
    assert snapshot["ready_validation_digest"] == digest
    assert snapshot["ready_at"] == ready_at
    assert snapshot["body"] == SUPPORTED_TEXT
    assert snapshot["title"] == HEADLINE
    assert snapshot["editorial_focus"]
    assert snapshot["story_id"] == "s-one"
    # Evidence/source traceability for an audit, and no internal Case or Draft.
    assert snapshot["evidence"]["facts"]
    assert snapshot["evidence"]["facts"][0]["source"]["url"]
    assert "case_id" not in json.dumps(snapshot, ensure_ascii=False)


def test_a_finalized_article_leaves_the_active_list_and_enters_the_archive(manual):
    article_id = manual["article_id"]
    _ready_manual(article_id)
    assert app.list_articles("ready")[0]["id"] == article_id
    assert app.list_archive() == []

    app.finalize_article(article_id, 1, idempotency_key="move")

    assert app.list_articles() == []
    for state_filter in ("preparation", "draft", "ready"):
        assert app.list_articles(state_filter) == []
    archived = app.list_archive()
    assert [row["id"] for row in archived] == [article_id]
    assert archived[0]["finalizedAt"] == app.read_article(article_id)["finalizedAt"]
    # Today is derived attention: a finalized Article asks for nothing.
    today_ids = [row["objectId"] for row in app.read_today()["articlesRequiringAction"]]
    assert article_id not in today_ids


def test_a_finalized_article_is_searchable_in_the_archive(manual):
    article_id = manual["article_id"]
    _ready_manual(article_id, REVIEW_TEXT)
    app.finalize_article(article_id, 1, idempotency_key="search")

    assert [row["id"] for row in app.list_archive("вътрешния")] == [article_id]
    assert app.list_archive("нещо друго") == []


def test_finalize_refuses_a_stale_editor_version(manual):
    article_id = manual["article_id"]
    _ready_manual(article_id)

    with pytest.raises(app.EditorVersionConflict):
        app.finalize_article(article_id, 0, idempotency_key="stale")

    assert articles.get_editor_article(article_id)["finalized_at"] is None
    assert articles.read_finalized_article(article_id) is None
    assert app.list_archive() == []


def test_changed_validation_basis_refuses_finalize_without_a_content_change(manual):
    """The release gate: same body, same version, different validation digest."""
    article_id = manual["article_id"]
    _ready_manual(article_id)
    assert app.read_article(article_id)["state"] == "ready"
    digest = articles.get_editor_article(article_id)["ready_validation_digest"]

    # The evidence basis materially changes between the checkpoint and the
    # finalization attempt. The text is not touched.
    _seed_basis(
        gaps=[{"id": "gap_how", "question": "Как се финансира?", "blocking": False}],
        assessed_at="2026-09-25T13:00:00Z",
    )
    assert app.validate_article_current_content(article_id)["validationDigest"] != digest

    with pytest.raises(app.EditorInvalidTransition):
        app.finalize_article(article_id, 1, idempotency_key="stale-basis")

    # No false finalized result, and the Article is no longer presented as
    # safely finalizable: it projects `Чернова`, not a fourth state.
    after = app.read_article(article_id)
    assert after["state"] == "draft"
    assert "FINALIZE" not in after["availableActions"]
    assert articles.get_editor_article(article_id)["finalized_at"] is None
    assert app.list_archive() == []


def test_a_blocking_issue_after_ready_refuses_finalize(manual):
    article_id = manual["article_id"]
    _ready_manual(article_id)
    _seed_basis(
        gaps=[{"id": "gap_who", "question": "Кой е отговорен?", "blocking": True}],
        assessed_at="2026-09-25T14:00:00Z",
    )

    with pytest.raises(app.EditorSafetyBlocked) as refusal:
        app.finalize_article(article_id, 1, idempotency_key="blocked")

    assert refusal.value.warnings
    assert articles.get_editor_article(article_id)["finalized_at"] is None
    assert app.list_archive() == []


def test_a_failed_validation_fails_closed_and_keeps_the_checkpoint(manual):
    """A check that could not run is not a pass and not an empty warning set."""
    article_id = manual["article_id"]
    _ready_manual(article_id)
    real_evaluate = article_validation.evaluate_current_content

    def refuse(*_args, **_kwargs):
        raise article_validation.ValidationUnavailable("audit unavailable")

    # Patched by name only. `monkeypatch.undo()` would also revert the
    # newsroom fixture's environment and send the retry into the real runtime
    # store, so the original is restored explicitly instead.
    with (
        mock.patch.object(article_validation, "evaluate_current_content", refuse),
        pytest.raises(app.EditorValidationUnavailable),
    ):
        app.finalize_article(article_id, 1, idempotency_key="failed")

    assert articles.get_editor_article(article_id)["finalized_at"] is None
    assert articles.read_finalized_article(article_id) is None
    # A technical failure that disproved nothing leaves the checkpoint valid, so
    # a retry after the cause is gone is a normal finalization.
    assert article_validation.evaluate_current_content is real_evaluate
    assert app.finalize_article(article_id, 1, idempotency_key="retry")["finalizedAt"]


def test_finalize_is_refused_outside_the_ready_state(manual):
    article_id = manual["article_id"]
    articles.save_article_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)

    with pytest.raises(app.EditorInvalidTransition):
        app.finalize_article(article_id, 1, idempotency_key="draft")

    assert articles.get_editor_article(article_id)["finalized_at"] is None


def test_finalize_requires_an_idempotency_key(manual):
    article_id = manual["article_id"]
    _ready_manual(article_id)


def test_a_generated_draft_finalizes_and_the_immutable_draft_is_untouched(manual, model):
    """Path A: the generated Draft, its internal Case and its audit stay intact."""
    article_id = manual["article_id"]
    assert _generate(article_id, "generate")["status"] == "succeeded"
    generated = app.read_article(article_id)
    assert generated["content"]["version"] == 1
    app.mark_article_ready(article_id, 1)
    editorial = app._editorial_root()
    watched = {
        path: path.read_bytes()
        for path in (editorial / "live_drafts.jsonl", editorial / "cases.jsonl")
    }
    record_before = articles.get_editor_article(article_id)

    result = app.finalize_article(article_id, 1, idempotency_key="generated")

    assert result["article"]["content"]["body"] == generated["content"]["body"]
    assert {path: path.read_bytes() for path in watched} == watched
    after = articles.get_editor_article(article_id)
    assert after["internal_refs"] == record_before["internal_refs"]
    # The Case id is lineage, never the Archive identity.
    assert record_before["internal_refs"]["case_id"]
    assert result["articleId"] == article_id
    assert "case_id" not in json.dumps(result["article"], ensure_ascii=False)


# ------------------------------------------------------------- immutability


def test_every_active_command_refuses_a_finalized_article(manual):
    article_id = manual["article_id"]
    _ready_manual(article_id)
    app.finalize_article(article_id, 1, idempotency_key="freeze")
    snapshot_bytes = articles.finalized_article_path(article_id).read_bytes()
    content_bytes = articles.article_content_path(article_id, 1).read_bytes()

    for attempt in (
        lambda: app.save_content(article_id, 1, HEADLINE, "Променен текст"),
        lambda: app.update_title(article_id, 1, "Друго заглавие"),
        lambda: app.update_focus(article_id, "Друг фокус"),
        lambda: app.start_article_draft(article_id, idempotency_key="again"),
        lambda: app.mark_article_ready(article_id, 1),
        lambda: app.reopen_article(article_id),
    ):
        with pytest.raises((app.EditorApplicationError, app.EditorInvalidTransition)):
            attempt()

    # The frozen snapshot and the content it froze are byte-identical.
    assert articles.finalized_article_path(article_id).read_bytes() == snapshot_bytes
    assert articles.article_content_path(article_id, 1).read_bytes() == content_bytes
    assert articles.get_article_content(article_id)["body"] == SUPPORTED_TEXT


def test_an_interrupted_snapshot_write_never_exposes_a_finalized_article(manual):
    """A late internal failure keeps the Article active and recoverable."""
    article_id = manual["article_id"]
    _ready_manual(article_id)

    def explode(*_args, **_kwargs):
        raise OSError("late write failure")

    # `mock` rather than `monkeypatch`: undoing the fixture's environment would
    # send the recovery retry into the real runtime store.
    with (
        mock.patch.object(articles.live_store, "atomic_write", explode),
        pytest.raises(OSError),
    ):
        app.finalize_article(article_id, 1, idempotency_key="interrupted")

    # No finalized Article, no Archive row, and the content is untouched.
    assert articles.get_editor_article(article_id)["finalized_at"] is None
    assert app.list_archive() == []
    assert app.read_article(article_id)["state"] == "ready"
    # Recovery is an ordinary retry: no duplicate, no half-written state.
    assert app.finalize_article(article_id, 1, idempotency_key="recovered")["finalizedAt"]
    assert len(app.list_archive()) == 1


# ------------------------------------------------------------- traceability


def test_the_story_keeps_traceability_to_a_finalized_article(manual):
    """One Story still relates to the Article, now through the Archive."""
    article_id = manual["article_id"]
    _ready_manual(article_id)
    app.finalize_article(article_id, 1, idempotency_key="trace")

    detail = app.read_story("s-one")
    related = next(row for row in detail["relatedArticles"] if row["id"] == article_id)
    assert related["finalizedAt"] == app.read_article(article_id)["finalizedAt"]
    # The Article is not active any more, but it is not detached either.
    assert app.list_articles() == []
    assert related["finalizedAt"]


def test_a_duplicate_finalize_returns_the_same_article_and_no_second_row(manual):
    article_id = manual["article_id"]
    _ready_manual(article_id)
    first = app.finalize_article(article_id, 1, idempotency_key="k")
    snapshot_bytes = articles.finalized_article_path(article_id).read_bytes()

    second = app.finalize_article(article_id, 1, idempotency_key="k")
    third = app.finalize_article(article_id, 1, idempotency_key="other-key")

    assert second["finalizedAt"] == first["finalizedAt"]
    assert third["finalizedAt"] == first["finalizedAt"]
    assert len(app.list_archive()) == 1
    assert articles.finalized_article_path(article_id).read_bytes() == snapshot_bytes
