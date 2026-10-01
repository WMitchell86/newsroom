# V1.2-G4.22. The fixture asked "Кога?" and answered "Съобщението е на 25
# септември" — one generic word meeting another. `_GENERIC_NEWS_WORDS`
# deliberately neutralises съобщение as vocabulary that can occur in any two
# unrelated stories, so the two shared no identifying anchor and the filter
# correctly kept nothing. That is the feature working. The fixture was
# leaning on a word the precision repair in 6a095c3 had deliberately
# neutralised. The question now carries a real anchor the answer contains.
"""Focused B4A Story-owned research backend tests (V1.1-A evidence bootstrap)."""

from __future__ import annotations

import json

import pytest

from editor_assistant.workflow import research_trace, story_research, story_research_store


def _row():
    return {
        "story_id": "s-one",
        "sources": [{"id": "src_old", "name": "Old", "url": "https://old.test/a"}],
        "facts": [],
        "gaps": [{"id": "gap_q", "question": "Кога изтича срокът за кандидатурите?", "blocking": True}],
        "assessed_at": "2026-09-25T08:00:00Z",
        "research_rounds": 0,
        "operation_ids": [],
    }


def test_store_is_story_keyed_and_rejects_ambiguous_source(tmp_path):
    root = tmp_path / "editorial"
    story_research_store.save_story_research(_row(), root=root)
    assert story_research_store.get_story_research("s-one", root=root)["story_id"] == "s-one"
    with pytest.raises(story_research_store.StoryResearchIdentityError):
        story_research_store.merge_research(
            "s-one",
            sources=[{"id": "src_old", "name": "Different", "url": "https://old.test/b"}],
            facts=[],
            gaps=[],
            canonical_story={"story_id": "s-one"},
            operation_id="op-1",
            root=root,
        )


class _Provider:
    name = "fake"

    def search(self, query):
        return {
            "provider": "fake",
            "query": query,
            "status": "SEARCH_OK",
            "results": [
                {
                    "rank": 1,
                    "title": "Official",
                    "url": "https://official.test/a",
                    "snippet": "snippet",
                },
                {
                    "rank": 2,
                    "title": "Second",
                    "url": "https://second.test/b",
                    "snippet": "snippet",
                },
            ],
        }


class _ProviderWithAggregator(_Provider):
    """`_Provider` plus a non-publisher host, so the §18 drop point is reachable.

    `max_open` defaults to 3 and the shared `_Provider` already returns two
    results, so this is the third page the round actually CONSIDERS - which is
    what makes it the right vehicle for asserting a recorded drop.
    """

    def search(self, query):
        payload = dict(super().search(query))
        payload["results"] = list(payload["results"]) + [
            {
                "rank": 3,
                "title": "Social",
                "url": "https://facebook.com/somepage",
                "snippet": "snippet",
            },
        ]
        return payload



def test_executor_uses_opened_source_and_claim_provenance(tmp_path):
    root = tmp_path / "editorial"
    story_research_store.save_story_research(_row(), root=root)
    pages = {
        "https://official.test/a": {
            "final_url": "https://official.test/a",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
        "https://second.test/b": {
            "final_url": "https://second.test/b",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
    }
    row = story_research.execute_story_research(
        "s-one",
        topic="Срок за кандидатурите изтича през септември",
        canonical_story={"story_id": "s-one"},
        authority_resolver=dict,
        readiness_result={
            "status": "RESEARCH_MORE",
            "sufficiency": {"research_questions": ["Кога изтича срокът за кандидатурите?"]},
        },
        root=root,
        provider=_Provider(),
        page_opener=pages.__getitem__,
        now="2026-09-25T09:00:00Z",
    )
    assert row["facts"][0]["sourceId"].startswith("src_")
    assert row["facts"][0]["locator"] == "claim:0"
    assert row["research_rounds"] == 1
    assert (
        json.loads((root / "search_runs").glob("*.jsonl").__next__().read_text(encoding="utf-8"))[
            "status"
        ]
        == "COMPLETED"
    )
    again = story_research.execute_story_research(
        "s-one",
        topic="Срок за кандидатурите изтича през септември",
        readiness_result={
            "status": "RESEARCH_MORE",
            "sufficiency": {"research_questions": ["Кога изтича срокът за кандидатурите?"]},
        },
        root=root,
        provider=_Provider(),
        page_opener=pages.__getitem__,
        canonical_story={"story_id": "s-one"},
        authority_resolver=dict,
        now="2026-09-25T09:00:00Z",
    )
    assert again["research_rounds"] == 1
    assert len(again["facts"]) == len(row["facts"])


def test_admission_definite_forms_and_price_are_dimension_aware():
    assert story_research._claim_for_questions(["Входът е безплатен."], ["Входът е свободен?"])
    assert story_research._claim_for_questions(
        ["Входът е свободен за всички посетители."], ["Входът е свободен?"]
    )
    assert story_research._claim_for_questions(
        ["Билетът струва 20 лева."], ["Колко струва билетът?"]
    )


def test_background_fact_is_not_used_for_current_schedule_assessment():
    current = {
        "facts": [
            {
                "id": "fact_bg",
                "text": "Събитието беше на 25 септември 2024 г.",
                "sourceId": "src_old",
                "locator": "claim:0",
                "scope": "background",
            }
        ],
        "sources": [{"id": "src_old", "name": "Old", "url": "https://old.test/a"}],
        "gaps": [
            {
                "id": "gap_date",
                "question": "Кога е събитието?",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
    }
    assert story_research._claim_for_questions(
        ["Събитието е на 25 септември 2024 г."], ["Кога е събитието?"]
    )
    assert current["facts"][0]["scope"] == "background"


def test_failed_open_does_not_mutate_story_basis(tmp_path):
    root = tmp_path / "editorial"
    before = _row()
    story_research_store.save_story_research(before, root=root)

    class BadProvider(_Provider):
        def search(self, query):
            return {
                "provider": "bad",
                "query": query,
                "status": "SEARCH_OK",
                "results": [{"rank": 1, "title": "x", "url": "https://x.test/a", "snippet": "x"}],
            }

    with pytest.raises(story_research.StoryResearchError):
        story_research.execute_story_research(
            "s-one",
            topic="x",
            readiness_result={
                "status": "RESEARCH_MORE",
                "sufficiency": {"research_questions": ["Кога изтича срокът за кандидатурите?"]},
            },
            root=root,
            canonical_story={"story_id": "s-one"},
            authority_resolver=dict,
            provider=BadProvider(),
            page_opener=lambda _url: {},
            now="2026-09-25T09:00:00Z",
        )
    assert story_research_store.get_story_research("s-one", root=root)["facts"] == []


def test_bootstrap_questions_come_from_story_context():
    questions = story_research.bootstrap_research_questions(
        title="Срок за кандидатурите изтича през септември", items=[{"item_id": "i1"}]
    )
    assert 1 <= len(questions) <= 6
    assert any("отворен" in question for question in questions)


def test_first_research_round_starts_without_preexisting_gaps(tmp_path):
    root = tmp_path / "editorial"
    pages = {
        "https://official.test/a": {
            "final_url": "https://official.test/a",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
        "https://second.test/b": {
            "final_url": "https://second.test/b",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
    }
    row = story_research.execute_story_research(
        "s-boot",
        topic="Срок за кандидатурите изтича през септември",
        canonical_story={"story_id": "s-boot"},
        root=root,
        provider=_Provider(),
        page_opener=pages.__getitem__,
        authority_resolver=lambda domain=None: {"kind": "media", "factual_authority": True},
        story_title="Срок за кандидатурите изтича през септември",
        story_items=[{"item_id": "i1"}],
        now="2026-09-25T09:00:00Z",
    )
    assert row["evidence_status"] == "assessed"
    assert row["research_rounds"] == 1
    assert row["facts"] and row["sources"]


def test_insufficient_evidence_persists_assessed_gap(tmp_path):
    root = tmp_path / "editorial"

    class EmptyProvider(_Provider):
        def search(self, query):
            return {"provider": "empty", "query": query, "status": "NO_RESULTS", "results": []}

    row = story_research.execute_story_research(
        "s-empty-proof",
        topic="Срок за кандидатурите изтича през септември",
        canonical_story={"story_id": "s-empty-proof"},
        root=root,
        provider=EmptyProvider(),
        page_opener=lambda _url: {},
        story_title="Срок за кандидатурите изтича през септември",
        story_items=[{"item_id": "i1"}],
        now="2026-09-25T09:00:00Z",
    )
    assert row["evidence_status"] == "assessed"
    assert row["facts"] == [] and len(row["gaps"]) >= 1


def test_assessed_store_refuses_empty_facts_and_gaps(tmp_path):
    root = tmp_path / "editorial"
    with pytest.raises(story_research_store.StoryResearchStoreError):
        story_research_store.save_story_research(
            {
                "story_id": "s-empty",
                "sources": [],
                "facts": [],
                "gaps": [],
                "assessed_at": "2026-09-25T08:00:00Z",
                "research_rounds": 0,
                "operation_ids": [],
            },
            root=root,
        )


def test_unassessed_basis_reports_evidence_status(tmp_path):
    root = tmp_path / "editorial"
    row = story_research_store.get_story_research("s-missing", root=root)
    assert row["evidence_status"] == "unassessed"
    assert row["assessed_at"] is None
    assert story_research_store.evidence_status_of(row) == "unassessed"


def test_provider_failure_before_assessment_writes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "editorial"
    monkeypatch.setattr(
        story_research.search,
        "run_search_operation",
        lambda **_kw: (_ for _ in ()).throw(
            story_research.StoryResearchError("provider exploded before any assessment")
        ),
    )
    with pytest.raises(story_research.StoryResearchError):
        story_research.execute_story_research(
            "s-fail",
            topic="Срок за кандидатурите изтича през септември",
            canonical_story={"story_id": "s-fail"},
            root=root,
            provider=_Provider(),
            page_opener=lambda _url: (_ for _ in ()).throw(AssertionError("no fetch")),
            story_title="Срок за кандидатурите изтича през септември",
            story_items=[{"item_id": "i1"}],
            now="2026-09-25T09:00:00Z",
        )
    assert (
        story_research_store.evidence_status_of(
            story_research_store.get_story_research("s-fail", root=root)
        )
        == "unassessed"
    )


# ---------------------------------------------------------------- V1.2-G4.20
# Why a page did or did not reach the draft model. Before this, `continue` in the
# research loop dropped pages with no record, so "did it look anywhere else?" was
# unanswerable from the product.


def test_a_dropped_page_is_recorded_with_its_reason(tmp_path, monkeypatch):
    """A social/aggregator page leaves a row, not silence.

    The whole feature is the negative case: `story_research.json` can only show
    what survived, so a test that asserts a KEPT page exists would pass even if
    every drop point were still silent.
    """
    root = tmp_path / "editorial"
    story_research_store.save_story_research(_row(), root=root)
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("RESEARCH_TRACE_PATH", str(trace_file))
    pages = {
        "https://facebook.com/somepage": {
            "final_url": "https://facebook.com/somepage",
            "content_type": "text/html",
            "bytes": 10,
            "text": "Приятели, вижте новата публикация на страницата ни днес в 18 часа.",
        },
        "https://official.test/a": {
            "final_url": "https://official.test/a",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
        "https://second.test/b": {
            "final_url": "https://second.test/b",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
    }
    story_research.execute_story_research(
        "s-one",
        topic="Срок за кандидатурите изтича през септември",
        canonical_story={"story_id": "s-one"},
        authority_resolver=dict,
        readiness_result={
            "status": "RESEARCH_MORE",
            "sufficiency": {"research_questions": ["Кога изтича срокът за кандидатурите?"]},
        },
        root=root,
        provider=_ProviderWithAggregator(),
        page_opener=pages.__getitem__,
        now="2026-09-25T09:00:00Z",
    )

    rows = research_trace.read_trace()
    by_outcome = {r["outcome"] for r in rows}
    assert research_trace.SKIPPED_NON_PUBLISHER in by_outcome, by_outcome
    dropped = [r for r in rows if r["outcome"] == research_trace.SKIPPED_NON_PUBLISHER]
    assert any("facebook.com" in r["url"] for r in dropped), [r["url"] for r in dropped]
    assert all(r["reason"] for r in dropped), "a drop must name a cause"
    # ...and the kept page is recorded too, so the list is a whole picture.
    assert research_trace.KEPT in by_outcome, by_outcome


def test_the_round_summary_counts_pages_without_arithmetic(tmp_path, monkeypatch):
    """`considered`/`kept`/`facts` are known only after the claim gate runs."""
    root = tmp_path / "editorial"
    story_research_store.save_story_research(_row(), root=root)
    monkeypatch.setenv("RESEARCH_TRACE_PATH", str(tmp_path / "trace.jsonl"))
    pages = {
        "https://official.test/a": {
            "final_url": "https://official.test/a",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
        "https://second.test/b": {
            "final_url": "https://second.test/b",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
    }
    story_research.execute_story_research(
        "s-one",
        topic="Срок за кандидатурите изтича през септември",
        canonical_story={"story_id": "s-one"},
        authority_resolver=dict,
        readiness_result={
            "status": "RESEARCH_MORE",
            "sufficiency": {"research_questions": ["Кога изтича срокът за кандидатурите?"]},
        },
        root=root,
        provider=_Provider(),
        page_opener=pages.__getitem__,
        now="2026-09-25T09:00:00Z",
    )

    rounds = [r for r in research_trace.read_trace() if r["outcome"] == "ROUND"]
    assert len(rounds) == 1, rounds
    summary = rounds[0]
    pages_seen = [r for r in research_trace.read_trace() if r["outcome"] != "ROUND"]
    # `considered` must equal the pages actually listed. This is the assertion
    # that caught the wrapper-filter bug: facebook was traced but not counted
    # because its drop happens before the counter is declared.
    assert summary["considered"] == len(pages_seen), (summary, len(pages_seen))
    assert summary["kept"] == sum(
        1 for r in pages_seen if r["outcome"] == research_trace.KEPT
    ), summary
    assert summary["questions"], "the round must record what it asked"
    assert summary["story_id"] == "s-one"


def test_the_trace_store_is_private_and_tolerates_a_missing_file(tmp_path, monkeypatch):
    """A url plus its verdict is still a record of what the newsroom was reading."""
    monkeypatch.delenv("RESEARCH_TRACE_PATH", raising=False)
    assert research_trace.read_trace(root=tmp_path) == []

    research_trace.record_page(
        story_id="s-one",
        url="https://x.test/a",
        outcome=research_trace.KEPT,
        root=tmp_path,
    )
    path = tmp_path / "editorial_workflow" / research_trace.FILENAME
    assert oct(path.stat().st_mode)[-3:] == "600"

    path.write_text('{"outcome": "KEPT"}\nbroken line\n\n', encoding="utf-8")
    assert len(research_trace.read_trace(root=tmp_path)) == 1


def test_a_broken_trace_never_breaks_a_research_round(tmp_path, monkeypatch):
    """Same contract as the prompt log: the audit trail is best effort."""
    root = tmp_path / "editorial"
    story_research_store.save_story_research(_row(), root=root)
    monkeypatch.setenv("RESEARCH_TRACE_PATH", str(tmp_path / "trace.jsonl"))

    def boom(**_kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(research_trace, "_write", boom)
    pages = {
        "https://official.test/a": {
            "final_url": "https://official.test/a",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
        "https://second.test/b": {
            "final_url": "https://second.test/b",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Срокът за кандидатурите изтича на 25 септември 2026 година.",
        },
    }
    row = story_research.execute_story_research(
        "s-one",
        topic="Срок за кандидатурите изтича през септември",
        canonical_story={"story_id": "s-one"},
        authority_resolver=dict,
        readiness_result={
            "status": "RESEARCH_MORE",
            "sufficiency": {"research_questions": ["Кога изтича срокът за кандидатурите?"]},
        },
        root=root,
        provider=_Provider(),
        page_opener=pages.__getitem__,
        now="2026-09-25T09:00:00Z",
    )
    assert row["facts"], "the round must still return its facts"
    assert row["research_rounds"] == 1


def test_the_trace_never_reaches_the_operator_store_from_a_test(monkeypatch, tmp_path):
    """`RESEARCH_TRACE_PATH` belongs in the autouse isolation fixture.

    Same accident as `MODEL_PROMPT_LOG`, and worse in one way: the trace records
    the real urls a round fetched, so an unisolated suite would leave fixture
    traffic in the operator's own file.
    """
    from editor_assistant.workflow import research_trace as module

    monkeypatch.setenv("RESEARCH_TRACE_PATH", str(tmp_path / "isolated.jsonl"))
    module.record_page(story_id="s-x", url="https://fixture.test/x", outcome=module.KEPT)

    assert (tmp_path / "isolated.jsonl").exists(), "the write went to the override"
    real = module.ROOT / "var" / "editorial_workflow" / module.FILENAME
    if real.exists():
        assert "fixture.test" not in real.read_text(encoding="utf-8")
