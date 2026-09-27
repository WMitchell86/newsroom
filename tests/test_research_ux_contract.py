"""V1.2-G2.2 — the editor-facing research and Focus contract.

Four defects the owner found while using the real product, pinned here at the
canonical layer:

* a research refusal that cannot be told apart from missing evidence;
* an unassessed Story phrased as an error instead of a next step;
* a Focus that demanded a second confirmation click;
* one persisted sentence claiming no source was opened on a page that had opened.

None of this touches corroboration, extraction, authority or any evidence
threshold — those assertions live in the V1.1-A/B suites and must keep passing
unchanged.
"""

from __future__ import annotations

import pytest

from editor_assistant.sources import web_fetch
from editor_assistant.workflow import (
    article_readiness,
    inbox_store,
    story_research,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import (
    editor_application as app,
)
from editor_assistant.workflow import (
    editor_article_store as articles,
)
from editor_assistant.workflow import (
    search as search_mod,
)

HEADLINE = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата"
SOURCE_URL = "https://vestnik.example.test/protokol"


def _item(item_id: str, title: str = HEADLINE):
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
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    inbox_store.save_items([_item("origin")], root / "inbox.jsonl")
    story = story_store.new_story(_item("origin"), now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    yield root


@pytest.fixture
def article(newsroom):
    record = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Ремонтът на улицата",
        editorial_focus="Да разкажем какво е одобрено и какво следва.",
        now="2026-09-25T09:00:00Z",
        root=newsroom.parent / "editorial",
    )
    return record


# --------------------------------------------------------------------------
# §5/§6/§7 the Focus contract
# --------------------------------------------------------------------------


def test_saving_a_non_empty_focus_is_its_own_confirmation(newsroom, article):
    editorial = newsroom.parent / "editorial"
    changed = articles.update_editor_focus(
        article["article_id"],
        "Да обясним последиците за жителите.",
        now="2026-09-25T10:00:00Z",
        root=editorial,
    )
    assert changed["editorial_focus"] == "Да обясним последиците за жителите."
    assert changed["focus_confirmed_at"] is not None


def test_clearing_the_focus_withdraws_the_confirmation(newsroom, article):
    # §6: clearing removes confirmation, so Draft readiness refuses again. The
    # editor is never offered a "confirmed but empty" Focus.
    editorial = newsroom.parent / "editorial"
    cleared = articles.update_editor_focus(
        article["article_id"], "", now="2026-09-25T10:00:00Z", root=editorial
    )
    assert cleared["editorial_focus"] == ""
    assert cleared["focus_confirmed_at"] is None

    detail = app.read_article(article["article_id"])
    assert detail["editorialFocus"]["confirmedAt"] is None
    assert detail["preparation"]["draftReadiness"]["code"] == article_readiness.FOCUS_NOT_CONFIRMED
    assert "MAKE_DRAFT" not in detail["availableActions"]


def test_an_empty_focus_refuses_the_draft_with_one_actionable_sentence():
    # §7: the message names the remedy, and there is no confirmation concept.
    assert article_readiness.REASON_MESSAGES[article_readiness.FOCUS_NOT_CONFIRMED] == (
        "Добавете редакционен фокус, за да създадете чернова."
    )
    assert "потвърд" not in article_readiness.REASON_MESSAGES[
        article_readiness.FOCUS_NOT_CONFIRMED
    ].casefold()


def test_an_unassessed_story_is_a_preparation_step_not_an_error():
    # §4: the sentence says what is needed, not that something went wrong.
    message = article_readiness.REASON_MESSAGES[article_readiness.STORY_UNASSESSED]
    assert message == "За чернова първо е нужно проучване на историята."
    assert "трябва първо да бъде проучена" not in message


# --------------------------------------------------------------------------
# §3 an operational refusal is never an evidence statement
# --------------------------------------------------------------------------


def test_the_operational_codes_and_their_api_wording_can_never_drift():
    from editor_assistant.workflow.workbench import api

    for error_class in (app.EditorResearchUnavailable, app.EditorResearchQuotaExhausted):
        assert api._MESSAGES[error_class.code] == error_class.default_message


def test_a_spent_round_budget_is_quota_not_a_missing_source(newsroom, monkeypatch):
    editorial = newsroom.parent / "editorial"
    story_research_store.merge_research(
        "s-one",
        sources=[{"id": "vestnik", "name": "Вестник", "url": SOURCE_URL}],
        facts=[
            {
                "id": "fact_g22_budget",
                "text": "Улицата се ремонтира.",
                "sourceId": "vestnik",
                "locator": "т. 1",
            }
        ],
        gaps=[
            {
                "id": "gap_g22_budget",
                "question": "Кога започва ремонтът?",
                "kind": "missing_fact",
                "blocking": True,
            }
        ],
        assessed_at="2026-09-25T09:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="g22-quota",
        count_round=True,
        root=editorial,
    )
    # Exhaust the canonical round budget through the real store, not a stub.
    for _ in range(6):
        current = story_research_store.get_story_research("s-one", root=editorial)
        story_research_store.merge_research(
            "s-one",
            sources=current["sources"],
            facts=current["facts"],
            gaps=current["gaps"],
            assessed_at=current.get("assessed_at"),
            canonical_story={"story_id": "s-one"},
            operation_id=f"g22-quota-{current['research_rounds']}",
            count_round=True,
            root=editorial,
        )
    monkeypatch.setattr(
        search_mod, "provider_chain", lambda capability=None, env=None: ([object()], [])
    )

    with pytest.raises(app.EditorResearchQuotaExhausted) as refusal:
        app.start_story_research("s-one", idempotency_key="g22-quota-key")
    # §3: quota wording only where the backend KNOWS the budget is the cause.
    assert refusal.value.code == "RESEARCH_QUOTA_EXHAUSTED"
    assert "лимит" in str(refusal.value).casefold()
    for forbidden in ("източник", "429", "route", "модел"):
        assert forbidden not in str(refusal.value).casefold()


def test_no_search_provider_is_an_operational_refusal(newsroom, monkeypatch):
    monkeypatch.setattr(search_mod, "provider_chain", lambda capability=None, env=None: ([], []))

    with pytest.raises(app.EditorResearchUnavailable) as refusal:
        app.start_story_research("s-one", idempotency_key="g22-no-provider")
    assert refusal.value.code == "RESEARCH_UNAVAILABLE"
    assert refusal.value.status == 503
    # §3: never rendered as an evidence statement.
    for forbidden in ("отворен източник", "липсва", "достовер"):
        assert forbidden not in str(refusal.value).casefold()


def test_a_healthy_story_without_a_gap_is_still_a_state_refusal(newsroom, monkeypatch):
    # The three refusals stay three different things: this Story is simply not
    # in a researchable state, which is NOT an operational outage.
    story_research_store.merge_research(
        "s-one",
        sources=[{"id": "vestnik", "name": "Вестник", "url": SOURCE_URL}],
        facts=[
            {
                "id": "fact_g22_clean",
                "text": "Улицата се ремонтира.",
                "sourceId": "vestnik",
                "locator": "т. 1",
            }
        ],
        gaps=[],
        assessed_at="2026-09-25T09:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="g22-clean",
        count_round=True,
        root=newsroom.parent / "editorial",
    )
    monkeypatch.setattr(
        search_mod, "provider_chain", lambda capability=None, env=None: ([object()], [])
    )
    with pytest.raises(app.EditorInvalidTransition):
        app.start_story_research("s-one", idempotency_key="g22-clean-key")


# --------------------------------------------------------------------------
# §12 the persisted reason must describe what actually happened
# --------------------------------------------------------------------------


def test_the_three_insufficient_evidence_reasons_are_distinct_and_truthful():
    reasons = {
        story_research.GAP_NOTHING_OPENED,
        story_research.GAP_NOTHING_PROMOTED,
        story_research.GAP_NEEDS_CORROBORATION,
    }
    assert len(reasons) == 3
    # Only the branch that really opened nothing may claim that.
    assert "отворим" in story_research.GAP_NOTHING_OPENED
    for reason in reasons - {story_research.GAP_NOTHING_OPENED}:
        assert "отворим" not in reason
    # The corroboration reason names the actual obstacle.
    assert "независим" in story_research.GAP_NEEDS_CORROBORATION
    # And none of them invents a trust claim.
    for reason in reasons:
        for forbidden in ("надежден", "ненадежден", "достовер", "проверен"):
            assert forbidden not in reason.casefold()


def test_a_round_that_opens_nothing_says_exactly_that(newsroom, monkeypatch):
    editorial = newsroom.parent / "editorial"

    class _Provider:
        name = "g22-empty"

        def search(self, query, count=10, **_kw):
            return {
                "provider": self.name,
                "query": query,
                "requested_count": count,
                "started_at": "2026-09-25T11:00:00Z",
                "status": search_mod.SEARCH_OK,
                "attempt": 1,
                "http_status": 200,
                "retry_after": None,
                "elapsed_ms": 1,
                "results": [],
            }

    monkeypatch.setattr(
        search_mod,
        "provider_chain",
        lambda capability=None, env=None: ([_Provider()], []),
    )

    def _never(url, **_kw):
        raise web_fetch.WebFetchError("offline in the proof")

    monkeypatch.setattr(web_fetch, "fetch_page", _never)

    story_research.execute_story_research(
        "s-one",
        topic=HEADLINE,
        root=editorial,
        canonical_story={"story_id": "s-one"},
        page_opener=_never,
        story_title=HEADLINE,
    )
    basis = story_research_store.get_story_research("s-one", root=editorial)
    assert [gap["question"] for gap in basis["gaps"]] == [story_research.GAP_NOTHING_OPENED]
    # §B15: an empty first round is still ASSESSED with an explicit gap.
    assert basis["evidence_status"] == story_research_store.EVIDENCE_ASSESSED
    assert basis["facts"] == []


# --------------------------------------------------------------------------
# §9 the original publication is named, not reconstructed
# --------------------------------------------------------------------------


def test_the_story_detail_names_its_original_publication(newsroom):
    detail = app.read_story("s-one")
    origin_id = detail["originPublicationId"]
    assert origin_id
    # It is one of the grouped publications, and it is the representative one.
    assert origin_id in {row["id"] for row in detail["publications"]}
    origin = next(row for row in detail["publications"] if row["id"] == origin_id)
    assert origin["url"] == "https://vestnik.example.test/origin"


def test_the_origin_id_is_derived_from_the_representative_not_guessed(newsroom):
    # §9: the id is computed from the stored representative, so it can never
    # drift from the publications the projection actually returns.
    detail = app.read_story("s-one")
    store = story_store.read_store(newsroom / "stories.json")
    representative = store["stories"][0]["representative_item_id"]
    from editor_assistant.workflow import editor_projections

    assert detail["originPublicationId"] == editor_projections.publication_id_for("", representative)
