"""C4 — validation of the CURRENT Article content + `Отбележи като готова`.

These tests pin the readiness product contract:

* validation always runs against the text that exists now, never against the
  immutable generated Draft or its generation-time audit;
* the validation digest is deterministic, order-independent and bound to the
  content version and to the evidence basis;
* `mark_article_ready` is server authority: it revalidates, refuses a stale
  editor version, refuses blocking content and records the checkpoint;
* a validation that could not run is never "no warnings" and never a checkpoint;
* a later edit, a later focus change or later evidence invalidates the
  checkpoint, and a manual Draft needs no generated lineage to become ready.

Only the model transport is stubbed, and only where a generated Draft is
required. The audits, the stores, the projections and the HTTP boundary are the
production ones, so a failure here is a real product defect.
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

HEADLINE = "Съветът одобри графика за ремонта"
BODY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
#: Two canonical sentences. Written back verbatim this reads as supported text;
#: the same facts reworded are what the lexical audit flags for review.
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
        operation_id="c4-fixture",
    )


@pytest.fixture
def prepared(newsroom):
    """A focused Article with a canonical, non-blocking evidence basis."""
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


# ------------------------------------------------------ current-content validation


def test_validation_runs_against_the_current_text_of_a_generated_draft(newsroom, prepared, model):
    """The unedited generated Draft is validated on its own current content."""
    article_id = prepared["article_id"]
    assert _generate(article_id, "generate")["status"] == "succeeded"
    generated = app.read_article(article_id)
    result = app.validate_article_current_content(article_id)

    assert result["contentVersion"] == generated["content"]["version"] == 1
    assert result["blocking"] is False
    assert result["validationDigest"].startswith("vd_")
    assert [row["id"] for row in result["warnings"]] == [row["id"] for row in generated["warnings"]]
    assert generated["validation"]["current"] is True
    # The C4 audit path never reads the generation-time Case audit.
    assert all(row.get("rule") != "gate" for row in result["warnings"])


def test_an_edited_draft_is_revalidated_and_never_reuses_generation_warnings(
    newsroom, prepared, model
):
    article_id = prepared["article_id"]
    _generate(article_id, "generate")
    generated = app.validate_article_current_content(article_id)
    before = articles.get_editor_article(article_id)["generated_content_version"]

    app.save_content(article_id, 1, HEADLINE, REVIEW_TEXT)
    edited = app.validate_article_current_content(article_id)

    assert edited["contentVersion"] == 2
    assert edited["validationDigest"] != generated["validationDigest"]
    # The generation audit belongs to the generated version and is now stale.
    assert articles.get_editor_article(article_id)["generated_content_version"] == before
    assert [row["id"] for row in edited["warnings"]] != [row["id"] for row in generated["warnings"]]


def test_a_manual_draft_is_validated_without_any_generated_lineage(newsroom, prepared):
    """No generated Draft, no Case and no Draft id is required for validation."""
    article_id = prepared["article_id"]
    stored = articles.get_editor_article(article_id)
    assert stored["internal_refs"] == {
        "idea_id": None,
        "evidence_id": None,
        "case_id": None,
        "draft_id": None,
    }
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)

    result = app.validate_article_current_content(article_id)
    assert result["contentVersion"] == 1
    assert result["blocking"] is False


def test_a_manual_draft_is_flagged_for_review_when_it_leaves_the_evidence(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, REVIEW_TEXT)
    result = app.validate_article_current_content(article_id)

    assert result["blocking"] is False
    assert result["warnings"], "text outside the evidence must be surfaced"
    assert all(row["severity"] in {"review", "info"} for row in result["warnings"])
    # affectedText is only ever the editor's own text; no range is invented.
    for row in result["warnings"]:
        assert set(row) <= {
            "id",
            "rule",
            "severity",
            "message",
            "blocking",
            "affectedText",
            "evidenceRefs",
            "range",
        }
        assert row.get("affectedText", REVIEW_TEXT) in REVIEW_TEXT


def test_a_story_without_an_evidence_basis_cannot_be_validated_clean(newsroom):
    """No facts means no audit is possible - blocking, never a silent pass."""
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title=HEADLINE,
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(article["article_id"], "Да обясним решението.")
    app.save_content(article["article_id"], 0, HEADLINE, SUPPORTED_TEXT)
    result = app.validate_article_current_content(article["article_id"])

    assert result["blocking"] is True
    assert [row["rule"] for row in result["warnings"]] == ["evidence_basis_empty"]


def test_an_open_blocking_gap_is_blocking_even_with_a_full_basis(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    _seed_basis(gaps=[{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}])

    result = app.validate_article_current_content(article_id)
    assert result["blocking"] is True
    assert "blocking_gap_open" in [row["rule"] for row in result["warnings"]]
    assert app.read_article(article_id)["validation"]["readyEligible"] is False
    assert "MARK_READY" not in app.read_article(article_id)["availableActions"]


def test_validation_is_synchronous_and_offline(newsroom, prepared, monkeypatch):
    """C4 runs no provider work: a network-bound check cannot be the authority."""
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)

    def explode(*_args, **_kwargs):
        raise AssertionError("validation must not call a provider")

    monkeypatch.setattr(gen, "call_model", explode)
    assert app.validate_article_current_content(article_id)["blocking"] is False


# ------------------------------------------------------------------ the digest


def test_the_same_validation_always_produces_the_same_digest(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, REVIEW_TEXT)

    first = app.validate_article_current_content(article_id)
    second = app.validate_article_current_content(article_id)

    assert first["validationDigest"] == second["validationDigest"]
    assert [row["id"] for row in first["warnings"]] == [row["id"] for row in second["warnings"]]


def test_the_validation_stamp_never_moves_the_digest(newsroom, prepared):
    """A timestamp is a display value, never an input of the readiness identity."""
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, REVIEW_TEXT)
    article = articles.get_editor_article(article_id)
    content = articles.get_article_content(article_id)
    facts, missing = app._story_evidence_projection("s-one")
    basis = {
        "story": app._story("s-one"),
        "facts": facts,
        "gaps": list(missing["items"]),
    }

    early = article_validation.evaluate_current_content(
        article, content, now="2020-01-01T00:00:00Z", **basis
    )
    late = article_validation.evaluate_current_content(
        article, content, now="2030-01-01T00:00:00Z", **basis
    )

    assert early.validated_at != late.validated_at
    assert early.digest == late.digest
    assert early.warnings == late.warnings


def test_warning_order_does_not_change_the_digest():
    base = {"id": "warn_a", "severity": "review", "blocking": False, "affectedText": "а"}
    other = {"id": "warn_b", "severity": "info", "blocking": False}
    common = {
        "article_id": "art-one",
        "content_version": 3,
        "fingerprint": "fp",
        "evidence": "ev",
        "blocking": False,
    }
    assert article_validation.compute_digest(warnings=[base, other], **common) == (
        article_validation.compute_digest(warnings=[other, base], **common)
    )


def test_a_material_change_always_changes_the_digest(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    supported = app.validate_article_current_content(article_id)["validationDigest"]
    app.save_content(article_id, 1, HEADLINE, REVIEW_TEXT)
    review = app.validate_article_current_content(article_id)["validationDigest"]

    # a different version, a different warning set and a different text
    assert supported != review
    # a different evidence basis for the very same text
    assert review == app.validate_article_current_content(article_id)["validationDigest"]
    _seed_basis(assessed_at="2026-09-25T13:00:00Z")
    assert app.validate_article_current_content(article_id)["validationDigest"] == review


def test_evidence_change_alone_moves_the_digest(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    before = app.validate_article_current_content(article_id)["validationDigest"]
    _seed_basis(
        gaps=[{"id": "gap_how", "question": "Как се финансира?", "blocking": False}],
        assessed_at="2026-09-25T13:00:00Z",
    )
    after = app.validate_article_current_content(article_id)["validationDigest"]
    assert before != after, "a different basis is a different validation"


def test_warning_identity_is_stable_and_not_a_counter(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, REVIEW_TEXT)
    first = {row["id"] for row in app.validate_article_current_content(article_id)["warnings"]}
    # Rewriting the same text into another version keeps the same identities.
    app.save_content(article_id, 1, HEADLINE, REVIEW_TEXT + " ")
    second = {row["id"] for row in app.validate_article_current_content(article_id)["warnings"]}
    assert first == second
    assert all(row.startswith("warn_") for row in first)


# ------------------------------------------------- `Отбележи като готова`


def test_a_current_version_is_marked_ready_and_the_checkpoint_is_recorded(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    digest = app.validate_article_current_content(article_id)["validationDigest"]

    ready = app.mark_article_ready(article_id, 1)

    stored = articles.get_editor_article(article_id)
    assert ready["state"] == "ready"
    assert stored["ready_version"] == 1
    assert stored["ready_at"]
    assert stored["ready_validation_digest"] == digest
    assert ready["readiness"] == {
        "isCurrent": True,
        "readyVersion": 1,
        "readyAt": stored["ready_at"],
    }
    # C5 completes the Ready surface: the editor may go back to `Чернова`
    # (`EDIT`) or freeze this exact version (`FINALIZE`). There is no publish.
    assert ready["availableActions"] == ["EDIT", "FINALIZE"]
    assert ready["nextAction"] == {
        "action": "FINALIZE",
        "reasonCode": "READY_TO_FINALIZE",
        "label": "Финализирай",
        "primary": True,
    }


def test_ready_eligibility_comes_from_the_backend_and_not_from_a_warning_count(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, REVIEW_TEXT)
    draft = app.read_article(article_id)

    assert draft["warnings"], "the editor sees real review warnings first"
    assert draft["validation"] == {
        "contentVersion": 1,
        "current": True,
        "blocking": False,
        "readyEligible": True,
    }
    assert draft["availableActions"] == ["CHANGE_FOCUS", "EDIT", "MARK_READY"]
    assert draft["nextAction"]["action"] == "MARK_READY"


def test_a_non_blocking_warning_does_not_prevent_ready(newsroom, prepared):
    """The action itself is the editorial checkpoint - there is no accept step."""
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, REVIEW_TEXT)
    assert app.validate_article_current_content(article_id)["warnings"]

    ready = app.mark_article_ready(article_id, 1)

    assert ready["state"] == "ready"
    assert ready["warnings"], "the recorded warning set stays visible on the exact version"
    assert not any(row["blocking"] for row in ready["warnings"])


def test_a_stale_editor_version_is_refused_and_nothing_is_marked(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    app.save_content(article_id, 1, HEADLINE, SUPPORTED_TEXT + " Добавено.")

    with pytest.raises(app.EditorVersionConflict):
        app.mark_article_ready(article_id, 1)

    stored = articles.get_editor_article(article_id)
    assert stored["ready_version"] is None
    assert stored["ready_at"] is None
    assert app.read_article(article_id)["state"] == "draft"


def test_blocking_content_is_refused_with_editor_facing_context(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    _seed_basis(gaps=[{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}])

    with pytest.raises(app.EditorSafetyBlocked) as refusal:
        app.mark_article_ready(article_id, 1)

    assert refusal.value.status == 409
    assert [row["rule"] for row in refusal.value.warnings] == ["blocking_gap_open"]
    assert all(row["blocking"] for row in refusal.value.warnings)
    stored = articles.get_editor_article(article_id)
    assert stored["ready_version"] is None and stored["ready_validation_digest"] is None
    assert app.read_article(article_id)["state"] == "draft"


def test_ready_is_refused_outside_the_draft_state(newsroom, prepared):
    article_id = prepared["article_id"]
    with pytest.raises(app.EditorInvalidTransition):
        app.mark_article_ready(article_id, 0)
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    app.mark_article_ready(article_id, 1)
    with pytest.raises(app.EditorInvalidTransition):
        app.mark_article_ready(article_id, 1)


def test_ready_is_refused_for_an_empty_draft(newsroom, prepared, model):
    article_id = prepared["article_id"]
    _generate(article_id, "generate")
    app.save_content(article_id, 1, HEADLINE, "")

    with pytest.raises(app.EditorApplicationError):
        app.mark_article_ready(article_id, 2)
    assert articles.get_editor_article(article_id)["ready_version"] is None


def test_a_failed_validation_creates_no_checkpoint_and_never_reports_no_warnings(
    newsroom, prepared, monkeypatch
):
    """Fail closed: a check that could not run is not a pass and not a warning set."""
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)

    def explode(*_args, **_kwargs):
        raise article_validation.ValidationUnavailable("audit store unreadable")

    real_evaluate = article_validation.evaluate_current_content
    monkeypatch.setattr(article_validation, "evaluate_current_content", explode)
    with pytest.raises(app.EditorValidationUnavailable) as failure:
        app.mark_article_ready(article_id, 1)
    assert failure.value.status == 500
    assert failure.value.code == "INTERNAL_ERROR"
    stored = articles.get_editor_article(article_id)
    assert stored["ready_version"] is None and stored["ready_at"] is None
    # The canonical content the editor confirmed is untouched.
    assert articles.get_article_content(article_id)["body"] == SUPPORTED_TEXT

    # A read reports the failure instead of inventing an empty warning set.
    unread = app.read_article(article_id)
    assert unread["state"] == "draft"
    assert unread["validation"] == {
        "contentVersion": 1,
        "current": False,
        "blocking": True,
        "readyEligible": False,
    }
    assert "MARK_READY" not in unread["availableActions"]

    # A retry after the cause is gone is a normal readiness, not a special case.
    monkeypatch.setattr(article_validation, "evaluate_current_content", real_evaluate)
    assert app.mark_article_ready(article_id, 1)["state"] == "ready"


# ------------------------------------------------------------- invalidation


def test_a_later_edit_makes_the_article_draft_again(newsroom, prepared):
    """The C3 invariant still holds after C4: content_version > ready_version."""
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    app.mark_article_ready(article_id, 1)

    edited = app.save_content(article_id, 1, HEADLINE, SUPPORTED_TEXT + " Изречението е уточнено.")

    assert articles.get_editor_article(article_id)["ready_version"] is None
    assert edited["state"] == "draft"
    assert edited["readiness"]["isCurrent"] is False
    assert "MARK_READY" in edited["availableActions"]


def test_a_later_focus_change_makes_the_article_draft_again(newsroom, prepared):
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    app.mark_article_ready(article_id, 1)

    app.update_focus(article_id, "Друг редакторски фокус.")

    assert articles.get_editor_article(article_id)["ready_version"] is None
    assert app.read_article(article_id)["state"] == "draft"


def test_changed_evidence_invalidates_the_checkpoint_without_a_content_change(newsroom, prepared):
    """ready_version still matches, but the validation digest no longer does."""
    article_id = prepared["article_id"]
    app.save_content(article_id, 0, HEADLINE, SUPPORTED_TEXT)
    stored_digest = app.mark_article_ready(article_id, 1)["readiness"]
    assert stored_digest["isCurrent"] is True

    _seed_basis(
        gaps=[{"id": "gap_how", "question": "Как се финансира?", "blocking": False}],
        assessed_at="2026-09-25T13:00:00Z",
    )
    after = app.read_article(article_id)

    record = articles.get_editor_article(article_id)
    assert record["ready_version"] == 1, "the durable checkpoint is still on record"
    assert after["state"] == "draft", "a stale validation never keeps a false `Готова`"
    assert after["readiness"]["isCurrent"] is False
    assert (
        app.validate_article_current_content(article_id)["validationDigest"]
        != (record["ready_validation_digest"])
    )


def test_ready_never_touches_the_immutable_generated_artifacts(newsroom, prepared, model):
    """Marking ready writes three checkpoint fields and nothing else."""
    article_id = prepared["article_id"]
    _generate(article_id, "generate")
    editorial = app._editorial_root()
    watched = {
        path: path.read_bytes()
        for path in (editorial / "live_drafts.jsonl", editorial / "cases.jsonl")
    }
    before = articles.get_editor_article(article_id)

    app.mark_article_ready(article_id, 1)

    after = articles.get_editor_article(article_id)
    assert {path: path.read_bytes() for path in watched} == watched
    assert after["internal_refs"] == before["internal_refs"]
    assert after["generated_content_version"] == before["generated_content_version"]
    assert after["finalized_at"] is None, "readiness is not finalization"
    changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    assert changed <= {"ready_version", "ready_at", "ready_validation_digest", "updated_at"}
