"""V1.1-C — Preparation manual continuation, and only after a real failure.

`Редактирай` on a Preparation Article is a RECOVERY path, not an alternative to
`Направи чернова`. C3 shipped it as an always-on escape hatch, and the
diagnostic (P1-7) established there was no durable signal anywhere that could
tell "generation failed, so write it yourself" from "deliberately hand written".

What these tests pin is that one question, end to end, through production code
with only the external provider boundary substituted:

* a clean, eligible Preparation Article offers generation and NO manual editor;
* a readiness refusal never records a failure and never opens the editor;
* a genuine generation failure persists a durable marker that survives a store
  reload, and only that marker opens the editor;
* any material change to the generation basis retires the marker;
* success clears it, and a manual Draft fabricates no Case, no immutable Draft
  and no generation provenance.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import (
    article_draft_failure,
    article_generation,
    article_readiness,
    inbox_store,
    story_operations,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import editor_article_store as articles

HEADLINE = "Съветът одобри графика за ремонта"
BODY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."


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
def newsroom(tmp_path, monkeypatch):
    """An isolated newsroom + editorial root; nothing outside tmp_path is touched."""
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    inbox_store.save_items([_item("origin", HEADLINE)], root / "inbox.jsonl")
    story = story_store.new_story(_item("origin", HEADLINE), now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    story_operations.clear()
    yield root
    story_operations.clear()
    for token in list(getattr(article_generation._ACTIVE, "keys", list)()):
        article_generation.release(token, article_generation._ACTIVE[token])


@pytest.fixture
def eligible(newsroom):
    """A Preparation Article the backend itself currently offers MAKE_DRAFT for."""
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(article["article_id"], "Да обясним решението и какво променя.")
    story_research_store.merge_research(
        "s-one",
        sources=[{"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/b"}],
        # Three sourced facts, because the mature pipeline's own evidence gate
        # must genuinely pass: V1.1-C substitutes only the external provider, so
        # every gate between the command and that boundary has to be real.
        facts=[
            {"id": "fact_money", "text": BODY, "sourceId": "vestnik", "locator": "Протокол, т. 4"},
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работа.",
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
    record = articles.get_editor_article(article["article_id"])
    assert "MAKE_DRAFT" in app.read_article(record["article_id"])["availableActions"]
    return record


def install_working_model(monkeypatch) -> None:
    """The only success stub: the model transport. Every gate stays real."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def call(prompt_text, *, api_key, timeout, role="draft", **_kw):
        if role == "draft":
            return (
                json.dumps(
                    {
                        "headlines": [HEADLINE],
                        "headline": HEADLINE,
                        "body": BODY + " Първа стъпка.",
                    },
                    ensure_ascii=False,
                ),
                {"model": "mock", "provider": "gemini"},
            )
        return (
            json.dumps(
                {
                    "sentence": BODY,
                    "verdict": "SUPPORTED",
                    "issue": "none",
                    "supporting_fact_ids": [],
                    "note": "ok",
                }
            ),
            {"model": "mock"},
        )

    monkeypatch.setattr(gen, "_call_gemini", call)


@pytest.fixture
def working_model(monkeypatch):
    install_working_model(monkeypatch)


def break_provider(monkeypatch, error: Exception | None = None) -> list[str]:
    """Fail the DRAFT role only — the real generation boundary.

    The pipeline reaches the draft call after the angle gate, so the substitute
    lets every upstream role answer normally and raises only for `role="draft"`.
    That is the narrowest possible seam: everything between the command and the
    external provider still runs for real, and the failure happens exactly where
    a provider outage would happen in production.
    """
    entered: list[str] = []
    install_working_model(monkeypatch)
    working = gen._call_gemini

    def call(prompt_text, *, api_key, timeout, role="draft", **kwargs):
        if role == "draft":
            entered.append(role)
            raise error or RuntimeError("provider transport is down")
        return working(prompt_text, api_key=api_key, timeout=timeout, role=role, **kwargs)

    monkeypatch.setattr(gen, "_call_gemini", call)
    return entered


def run_draft(article_id: str, key: str) -> dict:
    started = app.start_article_draft(article_id, idempotency_key=key)
    for _ in range(600):
        row = story_operations.get(started["operationToken"])
        if row and row["status"] in {"succeeded", "failed"}:
            return row
        time.sleep(0.02)
    raise AssertionError("the draft operation did not finish")


def _rows(name: str) -> list[dict]:
    path = Path(app._editorial_root()) / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _drafts() -> list[dict]:
    return _rows("live_drafts.jsonl")


def _cases() -> list[dict]:
    return _rows("cases.jsonl")


# ------------------------------------------------- the recovery path is earned


def test_a_fresh_eligible_preparation_article_offers_no_manual_continuation(eligible):
    """§22 — the permanent lock on the intended behavior.

    Focus confirmed, fully eligible, no previous generation failure. The editor
    is offered generation and nothing else. Before V1.1-C this exact state also
    carried `EDIT`, which is the always-on escape hatch the diagnostic found.
    """
    article_id = eligible["article_id"]
    article = app.read_article(article_id)

    assert article["state"] == "preparation"
    assert article["preparation"]["focusConfirmed"] is True
    assert article["preparation"]["draftEligible"] is True
    assert article["preparation"]["draftReadiness"]["code"] == "DRAFT_ELIGIBLE"
    assert "MAKE_DRAFT" in article["availableActions"]
    assert "EDIT" not in article["availableActions"]
    assert "EDIT" not in article["preparation"]["availableActions"]
    assert article["preparation"]["draftFailure"] is None
    assert articles.get_editor_article(article_id)["draft_generation_failure"] is None


def _degrade_to(reason: str, article_id: str) -> None:
    """Put the canonical Story basis into one specific ineligible state.

    Each state is produced through the real research store, never by patching a
    predicate: a state the store genuinely forbids is not faked here, it is
    arranged the way the product can actually reach it.
    """
    if reason == "FOCUS_NOT_CONFIRMED":
        record = articles.get_editor_article(article_id)
        record["editorial_focus"] = ""
        record["focus_confirmed_at"] = None
        articles.save_editor_articles([record])
        return
    if reason == "STORY_UNASSESSED":
        # V1.1-A: "never researched" is the ABSENCE of a research row, and the
        # readers resolve that to `unassessed`. Writing an explicit empty row
        # would be the false clean state the store deliberately refuses, so the
        # row is removed through the store's own path helper.
        store = story_research_store.story_research_path()
        if store.exists():
            payload = json.loads(store.read_text(encoding="utf-8"))
            payload["stories"] = [row for row in payload["stories"] if row["story_id"] != "s-one"]
            store.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return
    if reason == "BLOCKING_GAP":
        story_research_store.save_story_research(
            {
                "story_id": "s-one",
                "sources": [
                    {"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/b"}
                ],
                "facts": [
                    {"id": "fact_money", "text": BODY, "sourceId": "vestnik", "locator": "т. 4"}
                ],
                "gaps": [
                    {
                        "id": "gap_date",
                        "question": "Кога започва?",
                        "kind": "unresolved",
                        "blocking": True,
                    }
                ],
                "assessed_at": "2026-09-25T10:00:00Z",
                "research_rounds": 1,
                "operation_ids": ["op-fixture"],
            }
        )
        return
    if reason == "NO_CONFIRMED_FACTS":
        # Assessed, but nothing usable was confirmed: one non-blocking gap.
        story_research_store.save_story_research(
            {
                "story_id": "s-one",
                "sources": [],
                "facts": [],
                "gaps": [
                    {"id": "gap_who", "question": "Кой?", "kind": "missing_fact", "blocking": False}
                ],
                "assessed_at": "2026-09-25T10:00:00Z",
                "research_rounds": 1,
                "operation_ids": ["op-fixture"],
            }
        )
        return
    if reason == "NO_OPEN_SOURCE":
        # Unreachable through the canonical store (it refuses a source without a
        # URL) and covered by the dedicated test below through the same seam the
        # C2 suite uses. Kept here so the state list stays closed.
        return
    raise AssertionError(reason)  # pragma: no cover - the parametrization is closed


@pytest.mark.parametrize(
    "reason",
    [
        "STORY_UNASSESSED",
        "BLOCKING_GAP",
        "NO_CONFIRMED_FACTS",
        "FOCUS_NOT_CONFIRMED",
    ],
)
def test_a_readiness_refusal_never_records_a_failure_marker(eligible, reason, working_model):
    """§23 — a preflight refusal is not a generation failure.

    Each state is arranged canonically, the Draft command is invoked for real,
    and the invariant is checked three ways: the command refuses, no durable
    marker is written, and `EDIT` stays absent.
    """
    article_id = eligible["article_id"]
    _degrade_to(reason, article_id)
    before = app.read_article(article_id)
    assert before["preparation"]["draftReadiness"]["code"] == reason

    with pytest.raises(app.EditorApplicationError) as refusal:
        app.start_article_draft(article_id, idempotency_key=f"refused-{reason}")

    assert refusal.value.code == reason
    assert articles.get_editor_article(article_id)["draft_generation_failure"] is None
    after = app.read_article(article_id)
    assert "EDIT" not in after["availableActions"]
    assert after["preparation"]["draftFailure"] is None
    assert not _drafts() and not _cases()


def test_a_fact_without_an_opened_source_never_records_a_failure_marker(
    eligible, monkeypatch, working_model
):
    """§23, the fifth readiness code: `NO_OPEN_SOURCE`.

    The canonical research store refuses to persist a source without a URL, so
    this state cannot be produced by writing a research row — it is reachable
    only through a basis whose confirmed fact carries no usable source URL. The
    substitution is the *evidence basis* the command reads, the same seam the
    C2 test uses; the command path itself, and therefore the ordering that
    decides whether a marker is written, is entirely real.
    """
    article_id = eligible["article_id"]
    real_snapshot = app._draft_snapshot

    def without_open_source(article: str) -> dict:
        snapshot = real_snapshot(article)
        snapshot["facts"] = [
            {
                "id": "legacy_fact_1",
                "text": "Съветът е насрочил гласуване за вторник.",
                "source": {"id": "src_1", "name": "Вестник", "url": ""},
                "locator": "Протокол, т. 1",
                "scope": "current",
            }
        ]
        snapshot["source_url"] = ""
        return snapshot

    monkeypatch.setattr(app, "_draft_snapshot", without_open_source)
    try:
        assert (
            article_readiness.evaluate(without_open_source(article_id)).reason_code
            == "NO_OPEN_SOURCE"
        )
        with pytest.raises(app.EditorApplicationError) as refusal:
            app.start_article_draft(article_id, idempotency_key="no-open-source")
        assert refusal.value.code == "NO_OPEN_SOURCE"
    finally:
        # Restore the real reader directly: `monkeypatch.undo()` would also undo
        # the environment this fixture depends on.
        app._draft_snapshot = real_snapshot

    assert articles.get_editor_article(article_id)["draft_generation_failure"] is None
    after = app.read_article(article_id)
    assert "EDIT" not in after["availableActions"]
    assert after["preparation"]["draftFailure"] is None


def test_a_real_generation_failure_records_a_durable_marker(eligible, monkeypatch):
    """§24 — the qualifying failure, substituted only at the provider boundary.

    The Article was eligible, the provider was really called, the provider really
    failed, and the outcome is a Preparation Article that now offers the recovery
    action while `MAKE_DRAFT` retry remains available.
    """
    article_id = eligible["article_id"]
    entered = break_provider(monkeypatch)
    row = run_draft(article_id, "provider-down")

    assert entered, "the real generation path must have called the provider"
    assert row["status"] == "failed"
    stored = articles.get_editor_article(article_id)
    failure = stored["draft_generation_failure"]
    assert failure is not None
    assert failure["reason_code"] == article_draft_failure.PROVIDER_UNAVAILABLE
    assert failure["content_version"] == stored["content_version"]
    assert failure["basis_digest"] and failure["failed_at"]

    projection = app.read_article(article_id)
    assert projection["state"] == "preparation"
    assert "EDIT" in projection["availableActions"]
    # §10: the retry stays available next to the recovery path.
    assert "MAKE_DRAFT" in projection["availableActions"]
    assert projection["nextAction"]["action"] == "MAKE_DRAFT"
    assert projection["preparation"]["draftFailure"] == {
        "reasonCode": article_draft_failure.PROVIDER_UNAVAILABLE,
        "failedAt": failure["failed_at"],
    }
    # A failed generation publishes nothing.
    assert not _drafts() and not _cases()
    assert stored["internal_refs"]["draft_id"] is None


def test_the_recovery_path_survives_a_full_process_reload(eligible, monkeypatch):
    """§24 — durability. Nothing in memory may be load-bearing."""
    article_id = eligible["article_id"]
    break_provider(monkeypatch)
    run_draft(article_id, "provider-down")
    assert "EDIT" in app.read_article(article_id)["availableActions"]

    # Drop every in-process signal the decision could have leaned on: the
    # bounded operation registry, the per-Article generation lock, and the
    # attempt counter. What remains is the canonical store on disk.
    story_operations.clear()
    for token in list(article_generation._ACTIVE):
        article_generation.release(token, article_generation._ACTIVE[token])
    assert article_generation._ACTIVE == {}
    assert article_generation.active_token(article_id) == ""
    assert (
        article_generation._attempts(
            Path(app._editorial_root()),
            article_generation._evidence_prefix(article_id),
        )
        == 1
    )

    reloaded = app.read_article(article_id)
    assert "EDIT" in reloaded["availableActions"]
    assert reloaded["preparation"]["draftFailure"]["reasonCode"] == (
        article_draft_failure.PROVIDER_UNAVAILABLE
    )


def test_a_successful_generation_leaves_no_recovery_marker(eligible, working_model):
    """§25 — success is normal C2: a real Draft, unchanged lineage, no fallback."""
    article_id = eligible["article_id"]
    row = run_draft(article_id, "real-success")

    assert row["status"] == "succeeded"
    result = row["result"]
    assert result["state"] == "draft"
    assert result["content"]["body"].strip()
    # The immutable Draft and internal Case are exactly the C2 lineage.
    assert len(_drafts()) == 1 and len(_cases()) == 1
    stored = articles.get_editor_article(article_id)
    assert stored["internal_refs"]["draft_id"] == _drafts()[0]["lineage"]["draft_id"]
    assert stored["internal_refs"]["case_id"] == _cases()[0]["case_id"]
    # No Preparation fallback survives into the Draft.
    assert stored["draft_generation_failure"] is None
    assert stored["generated_content_version"] == stored["content_version"]
    assert result["preparation"] is None
    assert "MAKE_DRAFT" not in result["availableActions"]


def test_a_retry_that_succeeds_clears_the_earlier_failure(eligible, monkeypatch):
    """§7 — the exact sequence: fail, retry, succeed, marker gone."""
    article_id = eligible["article_id"]
    break_provider(monkeypatch)
    assert run_draft(article_id, "attempt-1")["status"] == "failed"
    assert articles.get_editor_article(article_id)["draft_generation_failure"] is not None

    # The provider recovers. `install_working_model` re-patches the transport seam.
    install_working_model(monkeypatch)
    assert run_draft(article_id, "attempt-2")["status"] == "succeeded"
    assert articles.get_editor_article(article_id)["draft_generation_failure"] is None
    assert app.read_article(article_id)["state"] == "draft"


def test_manual_continuation_creates_the_same_article_without_fabricating_lineage(
    eligible, monkeypatch
):
    """§16/§27 — the manual Draft is genuinely manual."""
    article_id = eligible["article_id"]
    story_before = app.read_story("s-one")["id"]
    break_provider(monkeypatch)
    run_draft(article_id, "provider-down")

    saved = app.save_content(article_id, 0, eligible["working_title"], "Ръчно написан текст.")

    assert saved["id"] == article_id
    assert saved["story"]["id"] == story_before
    assert saved["state"] == "draft"
    assert saved["content"]["version"] == 1
    assert saved["editorialFocus"]["confirmedAt"] == eligible["focus_confirmed_at"]
    # Nothing generated: no Case, no immutable Draft, no fake provenance.
    assert not _drafts() and not _cases()
    stored = articles.get_editor_article(article_id)
    assert stored["internal_refs"] == {
        "idea_id": None,
        "evidence_id": None,
        "case_id": None,
        "draft_id": None,
    }
    assert stored["generated_content_version"] is None
    assert stored["draft_generation_failure"] is None
    # §18: the Article is an ordinary Draft now, with the normal Draft actions.
    assert "MAKE_DRAFT" not in saved["availableActions"]
    assert "MARK_READY" in saved["availableActions"]


def test_an_empty_manual_body_never_establishes_draft_identity(eligible, monkeypatch):
    """§17 — entering the editor and leaving it empty keeps Preparation."""
    article_id = eligible["article_id"]
    break_provider(monkeypatch)
    run_draft(article_id, "provider-down")

    # An empty save changes nothing at all: no version, no state, no marker.
    unchanged = app.save_content(article_id, 0, eligible["working_title"], "")
    assert unchanged["state"] == "preparation"
    assert unchanged["content"]["version"] == 0
    assert articles.get_editor_article(article_id)["draft_generation_failure"] is not None

    # Type, then delete, before any successful non-empty save.
    app.save_content(article_id, 0, eligible["working_title"], "Начаен текст")
    emptied = app.save_content(article_id, 1, eligible["working_title"], "")
    assert emptied["content"]["body"] == ""
    # Once a non-empty body has been saved the Draft identity is durable, which
    # is C3 semantics: the editor cannot un-publish a Draft by emptying it.
    assert emptied["state"] == "draft"
    assert articles.get_editor_article(article_id)["draft_established_version"] == 1


@pytest.mark.parametrize("change", ["focus", "title", "evidence"])
def test_a_material_change_retires_the_failure(eligible, newsroom, monkeypatch, change):
    """§26 — a failure authorizes the manual editor only for its own basis.

    Each case changes exactly one generation input after the failure. The old
    marker must stop authorizing `EDIT`, and only a new genuine failure on the
    new basis can bring the path back.
    """
    article_id = eligible["article_id"]
    break_provider(monkeypatch)
    run_draft(article_id, "provider-down")
    assert "EDIT" in app.read_article(article_id)["availableActions"]

    if change == "focus":
        app.update_focus(article_id, "Друг, променен фокус за същата история.")
    elif change == "title":
        app.update_title(article_id, 0, "Друго работно заглавие")
    else:
        # A materially new fact on the SAME opened source, so the source identity
        # stays unambiguous and only the evidence basis changes.
        story_research_store.merge_research(
            "s-one",
            sources=[],
            facts=[
                {
                    "id": "fact_new",
                    "text": "Новият факт променя основата, върху която би се генерирала черновата.",
                    "sourceId": "vestnik",
                    "locator": "Протокол, т. 9",
                }
            ],
            gaps=[],
            assessed_at="2026-09-26T09:00:00Z",
            canonical_story={"story_id": "s-one"},
            operation_id="post-failure-research",
        )

    projection = app.read_article(article_id)
    assert projection["state"] == "preparation"
    assert "EDIT" not in projection["availableActions"]
    assert projection["preparation"]["draftFailure"] is None

    # The marker may still be on disk, but it is inert against the new basis —
    # which is what stops a stale failure from authorizing the editor forever.
    record = articles.get_editor_article(article_id)
    snapshot = article_readiness.build_snapshot(
        record,
        articles.get_article_content(article_id),
        app._maybe_story("s-one"),
        *_evidence_basis(article_id),
    )
    assert not article_draft_failure.is_current(record, snapshot)

    # And a NEW genuine failure on the NEW basis restores the path.
    assert run_draft(article_id, "second-failure")["status"] == "failed"
    restored = app.read_article(article_id)
    assert "EDIT" in restored["availableActions"]
    assert restored["preparation"]["draftFailure"]["reasonCode"] == (
        article_draft_failure.PROVIDER_UNAVAILABLE
    )


def _evidence_basis(article_id: str) -> tuple[list[dict], dict]:
    """The canonical facts/gaps projection, for a readiness snapshot."""
    story_id = articles.get_editor_article(article_id)["story_id"]
    return app._story_evidence_projection(story_id)


def test_the_marker_schema_refuses_anything_but_the_four_editor_safe_fields():
    """§3/§19 — the closed schema is the privacy guarantee."""
    valid = {
        "content_version": 3,
        "basis_digest": "abc123",
        "failed_at": "2026-09-26T09:00:00Z",
        "reason_code": article_draft_failure.GENERATION_FAILED,
    }
    assert articles._validate_draft_failure(valid) == valid
    assert articles._validate_draft_failure(None) is None
    for leaked in ("error", "exception", "prompt", "payload", "model", "secret", "traceback"):
        with pytest.raises(articles.ArticleStoreError, match="unknown draft_generation_failure"):
            articles._validate_draft_failure({**valid, leaked: "secret-value"})
    with pytest.raises(articles.ArticleStoreError, match="missing fields"):
        articles._validate_draft_failure({k: v for k, v in valid.items() if k != "basis_digest"})
    # An internal exception name can never be persisted as a reason class.
    with pytest.raises(articles.ArticleStoreError, match="not a known class"):
        articles._validate_draft_failure({**valid, "reason_code": "HTTPError_500"})


def test_every_readiness_and_transition_code_is_non_qualifying():
    """§5 — the allow-list, asserted against the live taxonomies."""
    must_not_qualify = (
        set(article_readiness.REASON_MESSAGES)
        | set(article_readiness.LIFECYCLE_CODES)
        | {article_generation.OP_INVALID_TRANSITION, "SOURCE_UNAVAILABLE", "DRAFT_ELIGIBLE"}
    )
    for code in sorted(must_not_qualify):
        assert article_draft_failure.reason_for(code) == "", code
    assert article_draft_failure.reason_for("DRAFT_UNAVAILABLE") == (
        article_draft_failure.GENERATION_FAILED
    )
    assert article_draft_failure.reason_for("") == article_draft_failure.PROVIDER_UNAVAILABLE
    # Every class the marker can store is a real class, and there are only two.
    assert set(article_draft_failure.QUALIFYING_REFUSALS.values()) == set(
        article_draft_failure.REASON_CODES
    )
