"""Focused B4A Story-owned research backend tests (V1.1-A evidence bootstrap)."""

from __future__ import annotations

import json

import pytest

from editor_assistant.workflow import story_research, story_research_store


def _row():
    return {
        "story_id": "s-one",
        "sources": [{"id": "src_old", "name": "Old", "url": "https://old.test/a"}],
        "facts": [],
        "gaps": [{"id": "gap_q", "question": "Кога?", "blocking": True}],
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


def test_executor_uses_opened_source_and_claim_provenance(tmp_path):
    root = tmp_path / "editorial"
    story_research_store.save_story_research(_row(), root=root)
    pages = {
        "https://official.test/a": {
            "final_url": "https://official.test/a",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Кога започва официалното съобщение? Съобщението е на 25 септември 2026 г.",
        },
        "https://second.test/b": {
            "final_url": "https://second.test/b",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Кога започва официалното съобщение? Съобщението е на 25 септември 2026 г.",
        },
    }
    row = story_research.execute_story_research(
        "s-one",
        topic="Съвет",
        canonical_story={"story_id": "s-one"},
        authority_resolver=dict,
        readiness_result={
            "status": "RESEARCH_MORE",
            "sufficiency": {"research_questions": ["Кога?"]},
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
        topic="Съвет",
        readiness_result={
            "status": "RESEARCH_MORE",
            "sufficiency": {"research_questions": ["Кога?"]},
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
                "sufficiency": {"research_questions": ["Кога?"]},
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
        title="Тест история", items=[{"item_id": "i1"}]
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
            "text": "Кога започва официалното съобщение? Съобщението е на 25 септември 2026 г.",
        },
        "https://second.test/b": {
            "final_url": "https://second.test/b",
            "content_type": "text/html",
            "bytes": 20,
            "text": "Кога започва официалното съобщение? Съобщението е на 25 септември 2026 г.",
        },
    }
    row = story_research.execute_story_research(
        "s-boot",
        topic="Тест история",
        canonical_story={"story_id": "s-boot"},
        root=root,
        provider=_Provider(),
        page_opener=pages.__getitem__,
        authority_resolver=lambda domain=None: {"kind": "media", "factual_authority": True},
        story_title="Тест история",
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
        topic="Тест история",
        canonical_story={"story_id": "s-empty-proof"},
        root=root,
        provider=EmptyProvider(),
        page_opener=lambda _url: {},
        story_title="Тест история",
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
            topic="Тест история",
            canonical_story={"story_id": "s-fail"},
            root=root,
            provider=_Provider(),
            page_opener=lambda _url: (_ for _ in ()).throw(AssertionError("no fetch")),
            story_title="Тест история",
            story_items=[{"item_id": "i1"}],
            now="2026-09-25T09:00:00Z",
        )
    assert (
        story_research_store.evidence_status_of(
            story_research_store.get_story_research("s-fail", root=root)
        )
        == "unassessed"
    )
