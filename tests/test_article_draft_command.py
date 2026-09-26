"""C2 — the one editor-facing Article Draft command (MAKE_DRAFT).

The real live pipeline runs here: the Story evidence basis becomes an
EvidencePacket, `workbench.state` prepares the case and generates through the
M2.3B path (readiness gate, style retrieval, factual + originality audit,
immutable Draft, internal Case). Only the model transport is stubbed, so a test
failure means a real product defect rather than a missing credential.

What these tests pin is the product contract, not the internals: the backend is
the policy authority, every precondition is revalidated, an accepted retry never
generates twice, a stale Article is never overwritten, and a failure leaves no
Draft, no Case, no content and no leaked provider text.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import (
    article_generation,
    article_readiness,
    inbox_store,
    story_operations,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import (
    editor_application as app,
)
from editor_assistant.workflow import (
    editor_article_store as articles,
)

BODY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
HEADLINE = "Съветът одобри графика за ремонта"


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
    """An isolated newsroom + editorial root; nothing outside tmp_path is touched."""
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
    for token in list(getattr(article_generation._ACTIVE, "keys", list)()):
        article_generation.release(token, article_generation._ACTIVE[token])


@pytest.fixture
def prepared(newsroom):
    """An Article the backend itself currently offers MAKE_DRAFT for."""
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(
        article["article_id"], "Да обясним решението и какво променя за хората."
    )
    story_research_store.merge_research(
        "s-one",
        sources=[
            {
                "id": "vestnik",
                "name": "Вестник",
                "url": "https://vestnik.example.test/2026/budget",
            }
        ],
        facts=[
            {
                "id": "fact_money",
                "text": BODY,
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
            {
                "id": "fact_next",
                "text": "Следващата сесия на съвета ще обсъди графика за следващата улица.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 6",
            },
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="fixture-round",
    )
    return articles.get_editor_article(article["article_id"])


@pytest.fixture
def model(monkeypatch):
    """The only stub: the model transport. Readiness, retrieval and gates are real."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    seen: list[dict] = []

    def call(prompt_text, *, api_key, timeout, role="draft", **_kw):
        seen.append({"role": role, "prompt": prompt_text})
        if role == "draft":
            return (
                json.dumps(
                    {
                        "headlines": [HEADLINE],
                        "headline": HEADLINE,
                        "body": BODY + " Това е първата стъпка от по-широк план.",
                    },
                    ensure_ascii=False,
                ),
                {"model": "mock", "provider": "gemini"},
            )
        return (
            "\n".join(
                json.dumps(
                    {
                        "sentence": BODY,
                        "verdict": "SUPPORTED",
                        "issue": "none",
                        "supporting_fact_ids": [],
                        "note": "ok",
                    }
                )
            ),
            {"model": "mock"},
        )

    monkeypatch.setattr(gen, "_call_gemini", call)
    return seen


def _await(token, *, attempts=600):
    for _ in range(attempts):
        row = story_operations.get(token)
        if row and row["status"] in {"succeeded", "failed"}:
            return row
        time.sleep(0.02)
    raise AssertionError("the draft operation did not finish")


def _editorial() -> Path:
    return app._editorial_root()


def test_draft_identity_survives_body_deletion_and_generation_audit_becomes_stale(
    newsroom, prepared, model
):
    article_id = prepared["article_id"]
    _run(article_id, "edit-generated")
    drafts_before = (_editorial() / "live_drafts.jsonl").read_bytes()
    cases_before = (_editorial() / "cases.jsonl").read_bytes()
    generated = app.read_article(article_id)
    assert generated["warnings"]
    generated_warnings = {row["id"] for row in generated["warnings"]}

    edited = app.save_content(article_id, 1, prepared["working_title"], "Редакторски текст.")
    assert edited["state"] == "draft"
    assert edited["content"]["version"] == 2
    # C4: the editor's own text is validated on its own terms. The generation
    # audit is not carried over - a fresh current-content warning set replaces
    # it, for this exact version.
    assert edited["validation"] == {
        "contentVersion": 2,
        "current": True,
        "blocking": False,
        "readyEligible": True,
    }
    assert {row["id"] for row in edited["warnings"]} != generated_warnings
    assert all(
        not row.get("affectedText") or row["affectedText"] in "Редакторски текст."
        for row in edited["warnings"]
    )
    assert (_editorial() / "live_drafts.jsonl").read_bytes() == drafts_before
    assert (_editorial() / "cases.jsonl").read_bytes() == cases_before

    emptied = app.save_content(article_id, 2, prepared["working_title"], "")
    assert emptied["state"] == "draft"
    assert emptied["content"]["body"] == ""
    assert "MAKE_DRAFT" not in emptied["availableActions"]
    # An emptied Draft has nothing to validate, so readiness is not offered.
    assert emptied["validation"]["blocking"] is True
    assert "MARK_READY" not in emptied["availableActions"]
    with pytest.raises(app.EditorInvalidTransition):
        app.start_article_draft(article_id, idempotency_key="must-not-overwrite")


def test_manual_first_save_needs_no_generated_draft_and_keeps_lineage(newsroom, prepared):
    article_id = prepared["article_id"]
    before_story = app.read_story("s-one")["id"]
    assert not _drafts() and not _cases()
    assert "EDIT" in app.read_article(article_id)["availableActions"]

    saved = app.save_content(article_id, 0, prepared["working_title"], "Ръчно написан текст.")

    assert saved["id"] == article_id
    assert saved["story"]["id"] == before_story
    assert saved["state"] == "draft"
    assert saved["content"]["version"] == 1
    # C4: a manual continuation is judged by the same current-content contract
    # as a generated Draft - no generated lineage is required for that.
    assert saved["validation"]["current"] is True
    assert all(not row["blocking"] for row in saved["warnings"])
    assert "MARK_READY" in saved["availableActions"]
    assert "MAKE_DRAFT" not in saved["availableActions"]
    assert not _drafts() and not _cases()
    stored = articles.get_editor_article(article_id)
    assert stored["internal_refs"] == {
        "idea_id": None,
        "evidence_id": None,
        "case_id": None,
        "draft_id": None,
    }
    with pytest.raises(app.EditorInvalidTransition):
        app.start_article_draft(article_id, idempotency_key="overwrite-manual")


def test_malformed_or_rejected_content_save_changes_nothing(newsroom, prepared):
    article_id = prepared["article_id"]
    with pytest.raises(articles.ArticleStoreError, match="body must be a string"):
        articles.save_article_content(article_id, 0, prepared["working_title"], 7)
    assert articles.get_article_content(article_id)["body"] == ""
    assert articles.get_editor_article(article_id)["content_version"] == 0
    articles.save_article_content(article_id, 0, prepared["working_title"], "Първи текст")
    with pytest.raises(articles.ArticleVersionConflict):
        articles.save_article_content(article_id, 0, "Грешно", "Второ")
    assert articles.get_article_content(article_id)["body"] == "Първи текст"
    assert articles.get_editor_article(article_id)["content_version"] == 1


def _drafts() -> list[dict]:
    path = _editorial() / "live_drafts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _cases() -> list[dict]:
    path = _editorial() / "cases.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _run(article_id, key):
    started = app.start_article_draft(article_id, idempotency_key=key)
    return started, _await(started["operationToken"])


# ---------------------------------------------------------------- the happy path


def test_draft_publishes_real_text_and_keeps_the_internal_lineage_private(
    newsroom, prepared, model
):
    """The real pipeline runs; only the Article projection is editor-facing."""
    article_id = prepared["article_id"]
    started, row = _run(article_id, "make-draft-1")

    assert started["operationToken"].startswith("op_")
    assert row["status"] == "succeeded"
    article = row["result"]
    assert article["state"] == "draft"
    assert article["content"]["body"].strip()
    assert article["content"]["version"] == 1
    assert article["title"] == prepared["working_title"]
    assert article["editorialFocus"]["confirmedAt"] is not None
    # The editor may draft again only from a real re-preparation, never twice
    # from the same preparation state.
    assert "MAKE_DRAFT" not in article["availableActions"]
    # C4: after editing, the next editorial action is the readiness checkpoint.
    assert article["nextAction"]["action"] == "MARK_READY"
    assert article["nextAction"]["label"] == "Отбележи като готова"

    # The immutable Draft and the internal Case exist and are linked.
    assert len(_drafts()) == 1 and len(_cases()) == 1
    refs = articles.get_editor_article(article_id)["internal_refs"]
    assert refs["draft_id"] == _drafts()[0]["lineage"]["draft_id"]
    assert refs["case_id"] == _cases()[0]["case_id"]
    assert refs["idea_id"] and refs["evidence_id"]

    serialized = json.dumps(article, ensure_ascii=False)
    for internal in (refs["idea_id"], refs["evidence_id"], refs["case_id"], refs["draft_id"]):
        assert internal not in serialized
    assert "internal_refs" not in serialized
    # Readiness is never implied by a generated draft.
    assert article["readiness"]["isCurrent"] is False


def test_article_warnings_are_derived_and_redacted(newsroom, prepared, model):
    _run(prepared["article_id"], "warn-1")
    article = app.read_article(prepared["article_id"])
    # The real audit produced review warnings (the gate flagged the draft and one
    # sentence has no direct support); none of them is blocking, and none of them
    # carries an internal id, a model name or a path.
    assert article["warnings"], "a reviewed draft must surface its warnings"
    assert {w["severity"] for w in article["warnings"]} <= {"info", "review", "blocking"}
    assert all(w["blocking"] is False for w in article["warnings"])
    assert all(w["id"].startswith("warn_") for w in article["warnings"])
    assert all(w["message"].strip() for w in article["warnings"])
    serialized = json.dumps(article["warnings"], ensure_ascii=False)
    for internal in (
        "mock",
        "gemini",
        "EV-ART",
        "LIV-",
        "cases.jsonl",
        "live_drafts",
        "/home",
        "source_text",
    ):
        assert internal not in serialized


def test_a_second_request_with_the_same_key_returns_the_same_operation(newsroom, prepared, model):
    article_id = prepared["article_id"]
    first = app.start_article_draft(article_id, idempotency_key="retry-me")
    second = app.start_article_draft(article_id, idempotency_key="retry-me")
    assert first["operationToken"] == second["operationToken"]
    _await(first["operationToken"])
    assert len(_drafts()) == 1, "an accepted retry must not generate a second Draft"
    assert len(_cases()) == 1


# ------------------------------------------------------ the backend is authority


def test_draft_is_refused_unless_the_backend_offers_make_draft(newsroom, model):
    """A valid key is not enough: the server's own action list decides.

    V1.1-B: an unconfirmed Focus is its own semantic reason
    (`FOCUS_NOT_CONFIRMED`), no longer folded into a generic invalid transition.
    """
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Без потвърден фокус",
        now="2026-09-25T09:00:00Z",
    )
    projection = app.read_article(article["article_id"])
    assert "MAKE_DRAFT" not in projection["availableActions"]
    assert projection["preparation"]["draftEligible"] is False
    assert projection["preparation"]["draftReadiness"]["code"] == "FOCUS_NOT_CONFIRMED"
    with pytest.raises(app.EditorDraftNotReady) as refusal:
        app.start_article_draft(article["article_id"], idempotency_key="no-focus")
    assert refusal.value.code == "FOCUS_NOT_CONFIRMED"
    assert not _drafts() and not _cases()
    assert model == [], "a refused command must not reach the model"


def test_a_blocking_gap_stops_generation_before_any_provider_work(newsroom, prepared, model):
    story_research_store.merge_research(
        "s-one",
        sources=[],
        facts=[],
        gaps=[{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}],
        assessed_at="2026-09-25T11:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="second-round",
    )
    article = app.read_article(prepared["article_id"])
    assert article["preparation"]["draftEligible"] is False
    # V1.1-B: the blocking gap is explained BY the gap, with its own code.
    assert article["preparation"]["draftReadiness"]["code"] == "BLOCKING_GAP"
    assert article["nextAction"]["reasonCode"] == "BLOCKING_GAP"
    assert article["nextAction"]["action"] == "RESEARCH_MORE"
    with pytest.raises(app.EditorBlockingGap) as refusal:
        app.start_article_draft(prepared["article_id"], idempotency_key="blocked")
    assert refusal.value.code == "BLOCKING_GAP"
    assert model == [], "a blocking gap must stop the command before the model"
    assert not _drafts() and not _cases()
    # The Article is exactly as the editor left it.
    stored = articles.get_editor_article(prepared["article_id"])
    assert stored["content_version"] == 0 and stored["internal_refs"]["draft_id"] is None


def test_an_unassessed_story_is_its_own_reason_not_a_fake_gap(newsroom, model):
    """V1.1-B §3: no evidence yet means `STORY_UNASSESSED`, not "no facts".

    Before V1.1-B this state was reported as a blocking gap, which told the
    editor to research a Story for a gap that did not exist.
    """
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Още непроучена история",
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(article["article_id"], "Да обясним решението и последиците.")
    projection = app.read_article(article["article_id"])
    preparation = projection["preparation"]
    assert preparation["draftEligible"] is False
    assert preparation["draftReadiness"]["code"] == "STORY_UNASSESSED"
    assert preparation["draftReadiness"]["message"] == "Историята трябва първо да бъде проучена."
    # No Article-level fake gap is displayed, and MAKE_DRAFT is absent.
    assert preparation["blockingGaps"] == []
    assert "MAKE_DRAFT" not in projection["availableActions"]
    # The remedy is research, and research stays owned by the Story.
    assert projection["nextAction"]["action"] == "RESEARCH_MORE"
    assert "RESEARCH_MORE" in projection["availableActions"]
    with pytest.raises(app.EditorDraftNotReady) as refusal:
        app.start_article_draft(article["article_id"], idempotency_key="unassessed")
    assert refusal.value.code == "STORY_UNASSESSED"
    assert model == []


def test_facts_without_an_opened_source_is_its_own_reason(newsroom, prepared, model):
    """V1.1-B §5: a fact with no usable source URL is `NO_OPEN_SOURCE`.

    It is not the same condition as a missing factual detail, and it is never
    collapsed into the generic blocking-gap message.

    The canonical research store refuses a source with an empty URL, so this
    state is reached through verified legacy Article lineage — which is exactly
    why the code exists rather than being dead: a fact can carry no usable URL
    without the canonical store ever having allowed one.
    """
    snapshot = app._draft_snapshot(prepared["article_id"])
    # A fact whose source carries no URL: the fact exists, the source does not
    # reach generation.
    snapshot["facts"] = [
        {
            "id": "legacy_fact_1",
            "text": "Съветът е насрочил гласуване за вторник.",
            "source": {"id": "src_1", "name": "Вестник", "url": ""},
            "locator": "Протокол, т. 1",
            "scope": "current",
        }
    ]
    snapshot["blocking_gaps"] = []
    snapshot["evidence_status"] = "assessed"
    snapshot["source_url"] = ""

    readiness = article_readiness.evaluate(snapshot)
    assert readiness.eligible is False
    assert readiness.reason_code == "NO_OPEN_SOURCE"
    assert readiness.fact_count == 1 and readiness.has_open_source is False
    with pytest.raises(article_generation.DraftRefused) as refusal:
        article_generation.evaluate(snapshot)
    assert refusal.value.code == "NO_OPEN_SOURCE"
    assert model == []


def test_without_confirmed_evidence_the_command_names_the_missing_facts(newsroom, model):
    """An assessed Story with no usable fact is `NO_CONFIRMED_FACTS`.

    V1.1-B §4: a distinct, named condition — not the generic blocking gap, and
    not the same as an unassessed Story. The store forbids the false clean state
    `assessed + 0 facts + 0 gaps`, so the honest form carries a non-blocking gap.
    """
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Празна основа",
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(article["article_id"], "Фокус")
    story_research_store.merge_research(
        "s-one",
        sources=[],
        facts=[],
        gaps=[
            {
                "id": "gap_who",
                "question": "Кой е основният заинтересован?",
                "blocking": False,
            }
        ],
        assessed_at="2026-09-25T11:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="no-facts-round",
    )
    projection = app.read_article(article["article_id"])
    assert projection["preparation"]["draftEligible"] is False
    assert projection["preparation"]["draftReadiness"]["code"] == "NO_CONFIRMED_FACTS"
    assert projection["preparation"]["blockingGaps"] == []
    with pytest.raises(app.EditorDraftNotReady) as refusal:
        app.start_article_draft(article["article_id"], idempotency_key="no-facts")
    assert refusal.value.code == "NO_CONFIRMED_FACTS"
    assert model == []


def test_a_blocked_or_circular_source_is_a_safety_stop(newsroom, prepared, model):
    """This command re-applies the two safety guards before any model call."""
    snapshot = app._draft_snapshot(prepared["article_id"])
    for url, expected in (
        ("https://flagman.bg/news/1", "SAFETY_BLOCKED"),
        ("https://chernomorie-bg.com/2026/novina", "SAFETY_BLOCKED"),
    ):
        snapshot["source_url"] = url
        with pytest.raises(article_generation.DraftRefused) as refusal:
            article_generation.evaluate(snapshot)
        assert refusal.value.code == expected
    assert model == [], "a safety stop must not reach the model"


def test_an_ignored_story_cannot_receive_a_draft(newsroom, prepared, model):
    app.ignore_story("s-one")
    # V1.1-B: an unavailable Story is a lifecycle/lineage refusal, so it keeps
    # the historical transition class while the message names the real reason.
    with pytest.raises(app.EditorInvalidTransition) as refusal:
        app.start_article_draft(prepared["article_id"], idempotency_key="ignored")
    assert str(refusal.value) == "Историята на статията вече не е достъпна."
    assert model == []


# ------------------------------------------------- failure, staleness, races


def test_a_provider_failure_is_a_retryable_sanitized_operation(newsroom, prepared, monkeypatch):
    def explode(*_a, **_kw):
        raise RuntimeError("openrouter/gemini-3 failed at /home/test/.config/router.json")

    monkeypatch.setattr(gen, "call_model", explode)
    started, row = _run(prepared["article_id"], "provider-down")

    assert row["status"] == "failed"
    status = app.operation_status(started["operationToken"])
    assert status["error"] == {
        "code": "SOURCE_UNAVAILABLE",
        "message": "Черновата не можа да бъде създадена. Опитайте отново.",
        "retryable": True,
    }
    blob = json.dumps(status, ensure_ascii=False)
    assert "gemini" not in blob and "router.json" not in blob and "/home" not in blob
    # The Article, its focus and its content are preserved, and no Draft, no
    # Case and no internal ref was fabricated.
    stored = articles.get_editor_article(prepared["article_id"])
    assert stored["content_version"] == 0
    assert stored["internal_refs"] == {
        "case_id": None,
        "draft_id": None,
        "evidence_id": None,
        "idea_id": None,
    }
    assert articles.get_article_content(prepared["article_id"])["body"] == ""
    assert app.read_article(prepared["article_id"])["state"] == "preparation"
    assert article_generation.active_token(prepared["article_id"]) == ""


def test_a_failed_operation_can_be_retried_with_the_same_key(
    newsroom, prepared, model, monkeypatch
):
    """The accepted operation is reused; a retry never duplicates the work."""
    article_id = prepared["article_id"]
    real_call_model = gen.call_model
    broken = []

    def maybe_fail(*args, **kwargs):
        if broken:
            raise RuntimeError("provider is down")
        return real_call_model(*args, **kwargs)

    monkeypatch.setattr(gen, "call_model", maybe_fail)
    broken.append(1)
    first, failed = _run(article_id, "retry-after-failure")
    assert failed["status"] == "failed"
    broken.clear()
    second = app.start_article_draft(article_id, idempotency_key="retry-after-failure")
    assert second["operationToken"] == first["operationToken"]
    retried = _await(first["operationToken"])
    assert retried["status"] == "succeeded", retried["error"]
    assert len(_drafts()) == 1, "a retry reuses the accepted operation, not a new one"


def test_publishing_over_a_stale_version_keeps_the_editors_text(newsroom, prepared):
    """The store is the last line of defence: an expected-version publish refuses."""
    article_id = prepared["article_id"]
    articles.save_article_content(article_id, 0, prepared["working_title"], "Ръчен текст")
    with pytest.raises(articles.ArticleVersionConflict):
        articles.publish_generated_draft(
            article_id,
            0,
            title=prepared["working_title"],
            body=BODY,
            internal_refs={"draft_id": "d1", "case_id": "LIV-01"},
        )
    assert articles.get_article_content(article_id)["body"] == "Ръчен текст"
    stored = articles.get_editor_article(article_id)
    assert stored["content_version"] == 1
    assert stored["internal_refs"]["draft_id"] is None


def test_a_queued_operation_refuses_to_overwrite_editor_text(newsroom, prepared, model):
    """Stale revalidation: the worker re-reads state, and new text stops it."""
    article_id = prepared["article_id"]
    original = app._draft_snapshot
    calls = []

    def snapshot_after_an_editor_edit(article):
        calls.append(1)
        if len(calls) == 1:
            accepted = original(article)
            # The editor wins the race right after the command was accepted.
            articles.save_article_content(
                article_id, 0, accepted["content"]["title"], "Текст на редактора"
            )
            return accepted
        return original(article)

    app._draft_snapshot = snapshot_after_an_editor_edit
    try:
        started, row = _run(article_id, "raced")
    finally:
        app._draft_snapshot = original

    assert len(calls) >= 2, "the worker must re-read the canonical state"
    assert row["status"] == "failed"
    status = app.operation_status(started["operationToken"])
    # V1.1-B: the editor's text is a named refusal (`ARTICLE_HAS_TEXT`), not a
    # generic invalid transition. The invariant — no model, no overwrite — is
    # unchanged; only the reason is now specific and actionable.
    assert status["error"]["code"] == "ARTICLE_HAS_TEXT"
    assert status["error"]["retryable"] is False
    assert model == [], "a stale operation must not reach the model"
    assert not _drafts() and not _cases()
    assert articles.get_article_content(article_id)["body"] == "Текст на редактора"
    assert articles.get_editor_article(article_id)["internal_refs"]["draft_id"] is None


def test_two_commands_at_once_produce_one_generation(newsroom, prepared, model, monkeypatch):
    """The per-Article guard makes a concurrent command return the live one."""
    article_id = prepared["article_id"]
    gate = threading.Event()
    real_generate = article_generation.generate

    def slow(snapshot, **kw):
        gate.wait(5)
        return real_generate(snapshot, **kw)

    monkeypatch.setattr(article_generation, "generate", slow)
    first = app.start_article_draft(article_id, idempotency_key="a")
    second = app.start_article_draft(article_id, idempotency_key="b")
    assert second["operationToken"] == first["operationToken"]
    gate.set()
    assert _await(first["operationToken"])["status"] == "succeeded"
    assert len(_drafts()) == 1 and len(_cases()) == 1
    assert article_generation.active_token(article_id) == "", "the guard is released"


# ------------------------------------------------------------ packet integrity


def test_the_packet_carries_only_canonical_facts_with_provenance(newsroom, prepared):
    """The Story basis is the evidence authority; nothing is reworded or invented."""
    snapshot = app._draft_snapshot(prepared["article_id"])
    packet = article_generation.build_packet(snapshot, "EV-TEST-01")
    canonical = [fact["text"] for fact in snapshot["facts"]]
    assert [fact["text"] for fact in packet["facts"]] == canonical
    assert [fact["id"] for fact in packet["facts"]] == [
        f"EV-TEST-01-f{index:02d}" for index in range(1, len(canonical) + 1)
    ]
    for fact in packet["facts"]:
        ref = fact["source_refs"][0]
        assert ref["source_id"] and ref["locator"]
    assert packet["source_url"] == snapshot["source_url"]
    assert packet["source_text"].split("\n") == canonical
    # No invented entity or quote, and the open questions travel with the packet.
    assert (packet["people"], packet["quotes"], packet["dates"]) == ([], [], [])
    assert packet["unknowns"] == []


def test_the_packet_travels_with_the_storys_open_questions(newsroom, prepared):
    story_research_store.merge_research(
        "s-one",
        sources=[],
        facts=[],
        gaps=[{"id": "gap_how", "question": "Как се финансира работата?", "blocking": False}],
        assessed_at="2026-09-25T11:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="third-round",
    )
    snapshot = app._draft_snapshot(prepared["article_id"])
    packet = article_generation.build_packet(snapshot, "EV-TEST-02")
    assert packet["unknowns"] == ["Как се финансира работата?"]
    assert packet["observed_at"] == "2026-09-25"
