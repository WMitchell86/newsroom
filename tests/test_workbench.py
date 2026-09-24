"""M3A Editor Workbench tests (offline, env-isolated).

Every test runs against a temp `editorial_workflow` dir via
`WB_EDITORIAL_WORKFLOW_DIR`, so the real editor's pending pilot answers and
canonical `cases.jsonl` are never touched. HTTP tests bind to 127.0.0.1 only.

Covers harness §24: queue, Bulgarian label mapping, immutable draft rendering,
safe source rendering, working-copy save/load + atomicity, "save never
finalizes", stale-generation block, validated finalization through the existing
contract, invalid editor enums, the NO_PUBLISHABLE_ANGLE / RESEARCH_MORE
special cases, the FACTUAL_GATE_REVIEW warning, HTML escaping, and the
localhost default.
"""

from __future__ import annotations

import inspect
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from editor_assistant.workflow import cases as cases_mod
from editor_assistant.workflow.workbench import html, http, labels, state

# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def wf_dir(tmp_path, monkeypatch):
    """Isolated runtime store for every test."""
    wf = tmp_path / "editorial_workflow"
    (wf / "editor_working").mkdir(parents=True)
    (wf / "research").mkdir(parents=True)
    (wf / "superseded").mkdir(parents=True)
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(wf))
    return wf


def _draft_row(draft_id="draft-1", headline="AI заглавие", body="Първи абзац.\n\nВтори абзац."):
    return {
        "draft": {"headline": headline, "body": body},
        "lineage": {
            "draft_id": draft_id,
            "mode_id": "MODE_STANDARD_NEWS",
            "generated_at": "2026-09-17T10:00:00Z",
        },
    }


def _add_case(
    wf,
    case_id="LIV-01",
    draft_id="draft-1",
    gate="FACTUAL_GATE_PASS",
    track=cases_mod.TRACK_LIVE,
    evidence_id=None,
    **kwargs,
):
    evidence_id = evidence_id or f"{case_id}-EVIDENCE"
    case = cases_mod.open_case(
        case_id=case_id,
        idea_id=f"idea-{case_id}",
        evidence_id=evidence_id,
        draft=_draft_row(draft_id),
        factual_gate=gate,
        track=track,
        **kwargs,
    )
    path = wf / "cases.jsonl"
    existing = cases_mod.read_cases(path) if path.exists() else []
    cases_mod.save_cases(existing + [case], path)
    return case


def _add_evidence(wf, evidence_id="LIV-01-EVIDENCE", status="DRAFT_READY", **extra):
    row = {
        "evidence_id": evidence_id,
        "packet": {
            "source_url": "https://example.bg/lead",
            "source_type": "council_transcript",
            "facts": [],
            "unknowns": [],
        },
        "readiness": {"status": status},
    }
    row.update(extra)
    state._live_evidence_save(row)
    return row


def _add_research(wf, case_or_evidence_id, sources):
    (wf / "research" / f"{case_or_evidence_id}.json").write_text(
        json.dumps({"sources": sources}, ensure_ascii=False), encoding="utf-8"
    )


def _normal_case(wf, case_id="LIV-01", **kwargs):
    """A normal DRAFT_READY draft case with its evidence row."""
    case = _add_case(wf, case_id=case_id, evidence_id=f"{case_id}-EVIDENCE", **kwargs)
    _add_evidence(wf, evidence_id=f"{case_id}-EVIDENCE", status="DRAFT_READY")
    return case


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------


class TestLabels:
    def test_editor_vocabulary_is_frozen(self):
        assert labels.EDITOR_VOCABULARY == {
            "story": "История",
            "development": "Ново развитие",
            "publication": "Публикация",
            "source": "Източник",
            "facts": "Факти и източници",
            "missing": "Какво липсва",
            "research": "Проучване",
            "angle": "Редакционен ъгъл",
            "article": "Статия",
            "draft": "Чернова",
            "final_article": "Финализирана статия",
        }
        assert labels.EDITOR_ACTIONS == (
            ("review", "Прегледай"),
            ("follow", "Следи"),
            ("ignore", "Игнорирай"),
            ("research_more", "Проучи още"),
            ("start_article", "Започни статия"),
            ("choose_angle", "Избери / промени ъгъл"),
            ("make_draft", "Направи чернова"),
            ("edit", "Редактирай"),
            ("finalize", "Финализирай"),
        )

    def test_readiness_answer_uses_editor_article_not_material(self):
        assert "статия" in labels.ANSWER_LABELS["would_publish"]
        assert "материал" not in labels.ANSWER_LABELS["would_publish"].lower()

    def test_readiness_labels_all(self):
        assert labels.readiness_label("DRAFT_READY") == "Готово за редакторски преглед"
        assert labels.readiness_label("RESEARCH_MORE") == "Нужна е още информация"
        assert labels.readiness_label("NO_PUBLISHABLE_ANGLE") == "Няма достатъчно силна новина"
        assert labels.readiness_label("EDITOR_DECISION_REQUIRED") == "Нужно е редакторско решение"
        assert labels.readiness_label("") == "—"

    def test_gate_labels_all(self):
        assert labels.gate_label("FACTUAL_GATE_PASS") == "Фактологичната проверка е премината"
        assert labels.gate_label("FACTUAL_GATE_REVIEW") == "Нужна е проверка на фактите"
        assert labels.gate_label("") == "—"

    def test_readiness_outcome_labels(self):
        assert labels.READINESS_OUTCOME_LABELS == {
            "ANGLE_ACCEPTED": "Ъгълът е приет",
            "ANGLE_CHANGED": "Ъгълът е променен",
            "NO_STORY_CONFIRMED": "Потвърдено: няма новина",
            "RESEARCH_REQUESTED": "Поискано е още проучване",
        }

    def test_filters_all_present(self):
        assert {k for k, _ in labels.FILTERS} == {
            "all",
            "edit",
            "research",
            "decision",
            "nostory",
            "finalized",
        }

    def test_readiness_answer_keys_match_canonical_contract(self):
        # The UI must not invent keys: `prefer_ai_start` is a separate contract
        # field, never part of `readiness_answers`.
        assert set(labels.ANSWER_LABELS) == set(cases_mod.READINESS_ANSWER_KEYS)
        assert "prefer_ai_start" not in labels.ANSWER_LABELS
        assert [v for v, _ in labels.PREFER_AI_START_VALUES] == list(
            cases_mod.PREFER_AI_START_VALUES
        )

    def test_editing_weight_and_outcome_labels_cover_contract(self):
        assert set(labels.EDITING_WEIGHT_LABELS) == set(cases_mod.EDITING_WEIGHTS)
        assert set(labels.EDITOR_OUTCOME_LABELS) == set(cases_mod.EDITOR_OUTCOMES)
        assert set(labels.TIME_BUCKET_LABELS) == set(cases_mod.TIME_BUCKETS)


# --------------------------------------------------------------------------
# queue
# --------------------------------------------------------------------------


class TestQueue:
    def test_renders_live_case(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        q = state.queue()
        assert [r["case_id"] for r in q["live"]] == ["LIV-01"]
        assert q["dryrun"] == []

    def test_dryrun_separated_from_live(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        _add_case(wf_dir, "WFX-01", track=cases_mod.TRACK_DRYRUN, evidence_id="EV-1")
        q = state.queue()
        assert [r["case_id"] for r in q["live"]] == ["LIV-01"]
        assert [r["case_id"] for r in q["dryrun"]] == ["WFX-01"]

    def test_filter_nav_labels(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        page = html.render_queue(state.queue(), active_filter="all")
        for label in (
            "Всички",
            "За редакция",
            "Нужна информация",
            "Нужно решение",
            "Без достатъчна новина",
            "Финализирани",
        ):
            assert label in page

    def test_edit_filter_contains_draft_case(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        q = state.queue()
        assert q["live"][0]["filter"] == "edit"
        page = html.render_queue(q, active_filter="edit")
        assert "LIV-01" in page

    def test_finalized_case_goes_to_finalized_bucket(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="Финално заглавие",
            body="Финалният текст.",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            time_saved_estimate="5-15 min",
            base_draft_id="draft-1",
        )
        q = state.queue()
        row = next(r for r in q["live"] if r["case_id"] == "LIV-01")
        assert row["final"] is True
        assert row["filter"] == "finalized"

    def test_filter_agrees_with_the_surfaces_the_page_offers(self, wf_dir):
        """Bucket and page must not contradict each other.

        A decision-only page must never sit in «За редакция», and an editable
        case must never be filed under «Нужно решение» (where its page would
        offer no decision form to resolve it).
        """
        _normal_case(wf_dir, "LIV-01")
        _add_case(wf_dir, "LIV-04", evidence_id="LIV-04-EVIDENCE")
        _add_evidence(wf_dir, "LIV-04-EVIDENCE", status="RESEARCH_MORE")
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        rows = state.queue()["live"]
        assert {r["case_id"] for r in rows} == {"LIV-01", "LIV-04", "LIV-06"}
        for row in rows:
            page = html.render_case(state.case_view(row["case_id"]))
            if row["filter"] == "edit":
                assert 'id="workspace"' in page, row["case_id"]
                assert 'id="decision"' not in page, row["case_id"]
            else:
                assert 'id="workspace"' not in page, row["case_id"]
                assert 'id="decision"' in page, row["case_id"]

    def test_queue_headline_xss_escaped(self, wf_dir):
        _add_case(wf_dir, "LIV-02", draft_id="d1")
        _add_evidence(wf_dir, "LIV-02-EVIDENCE")
        case = state.find_case("LIV-02")
        case["draft_headline"] = "<script>alert(1)</script>"
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        page = html.render_queue(state.queue(), active_filter="all")
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page


# --------------------------------------------------------------------------
# case page
# --------------------------------------------------------------------------


class TestCasePage:
    def test_draft_rendered_without_mutating_store(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        path = wf_dir / "cases.jsonl"
        before = path.read_bytes()
        view = state.case_view("LIV-01")
        assert view is not None
        page = html.render_case(view)
        assert "AI чернова (неизменима)" in page
        assert "AI заглавие" in page
        assert "Първи абзац." in page
        assert path.read_bytes() == before

    def test_draft_headline_alternatives_rendered(self, wf_dir):
        _add_case(wf_dir, "LIV-02", draft_id="d1")
        _add_evidence(wf_dir, "LIV-02-EVIDENCE")
        case = state.find_case("LIV-02")
        case["draft_headlines"] = ["Основно заглавие", "Алтернативно заглавие"]
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        page = html.render_case(state.case_view("LIV-02"))
        assert "Алтернативно заглавие" in page

    def test_sources_render_safely(self, wf_dir):
        _normal_case(wf_dir, "LIV-04")
        _add_research(
            wf_dir,
            "LIV-04",
            [
                {
                    "source_id": "S-1",
                    "source_name": "<script>alert(1)</script>",
                    "authority": "PRIMARY",
                    "url": "https://example.bg/a",
                    "relevant_claims": ["Твърдение"],
                },
                {"source_id": "S-2", "source_name": "Опасен линк", "url": "javascript:alert(1)"},
            ],
        )
        page = html.render_case(state.case_view("LIV-04"))
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page
        assert 'href="https://example.bg/a"' in page
        # An unsafe scheme is shown as plain text, never as a clickable link.
        assert 'href="javascript' not in page
        assert "Опасен линк" in page

    def test_article_body_xss_escaped(self, wf_dir):
        _add_case(
            wf_dir,
            "LIV-07",
            draft_id="d1",
        )
        case = state.find_case("LIV-07")
        case["draft_text"] = "<img src=x onerror=alert(1)>"
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        _add_evidence(wf_dir, "LIV-07-EVIDENCE")
        page = html.render_case(state.case_view("LIV-07"))
        assert "<img src=x" not in page
        assert "&lt;img src=x" in page

    def test_factual_gate_review_warning_renders(self, wf_dir):
        _add_case(wf_dir, "LIV-05", draft_id="d1", gate="FACTUAL_GATE_REVIEW")
        _add_evidence(wf_dir, "LIV-05-EVIDENCE", status="DRAFT_READY")
        page = html.render_case(state.case_view("LIV-05"))
        assert "Нужна е проверка на фактите" in page

    def test_unsupported_claim_warning_renders(self, wf_dir):
        _add_case(wf_dir, "LIV-08", draft_id="d1", audit={"semantic": {"n_unsupported": 1}})
        _add_evidence(wf_dir, "LIV-08-EVIDENCE")
        page = html.render_case(state.case_view("LIV-08"))
        assert "Нужна проверка" in page

    def test_originality_warning_renders(self, wf_dir):
        """M4F F5: a failed no-copy verdict surfaces like the factual gates."""
        _add_case(
            wf_dir,
            "LIV-77",
            draft_id="d1",
            audit={
                "semantic": {},
                "lexical": {},
                "originality": {
                    "pass": False,
                    "checked": True,
                    "threshold": 8,
                    "longest_run_words": 12,
                    "copied": ["Общинският съвет прие бюджета на заседание."],
                },
            },
        )
        page = html.render_case(state.case_view("LIV-77"))
        assert "повтаря дословно 12 думи" in page
        assert "Дословно повторено" in page

    def test_bg_status_badges_on_case_page(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        page = html.render_case(state.case_view("LIV-01"))
        assert "Готово за редакторски преглед" in page
        assert "DRAFT_READY" in page  # internal id stays visible next to the label


# --------------------------------------------------------------------------
# special cases (no draft)
# --------------------------------------------------------------------------


class TestSpecialCases:
    def test_no_publishable_angle_without_case_row(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        q = state.queue()
        assert [r["case_id"] for r in q["live"]] == ["LIV-06"]
        assert q["live"][0]["filter"] == "nostory"
        view = state.case_view("LIV-06")
        assert view is not None
        assert view["kind"] == "nostory"

    def test_nostory_page_has_no_article_editor(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        page = html.render_case(state.case_view("LIV-06"))
        assert 'id="workspace"' not in page
        assert "Няма достатъчно силен и проверим новинарски ъгъл" in page
        assert "Редакторско решение" in page
        assert "Няма достатъчно силна новина" in page

    def test_rejected_case_leaves_the_edit_queue(self, wf_dir):
        """Recording "не публикувай" must not bounce the case back to "за редакция"."""
        _normal_case(wf_dir, "LIV-03")
        state.record_decision("LIV-03", decision="REJECT_STORY", reason="Няма новост.")
        row = next(r for r in state.queue()["live"] if r["case_id"] == "LIV-03")
        assert row["kind"] == "nostory"
        assert row["filter"] == "nostory"
        page = html.render_case(state.case_view("LIV-03"))
        assert 'id="workspace"' not in page
        assert "Записано решение" in page

    def test_research_request_moves_case_to_research_queue(self, wf_dir):
        _normal_case(wf_dir, "LIV-09")
        state.record_decision("LIV-09", decision="REQUEST_MORE_RESEARCH", reason="Липсва дата.")
        row = next(r for r in state.queue()["live"] if r["case_id"] == "LIV-09")
        assert row["filter"] == "research"

    def test_nostory_decision_recorded_without_body(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        case = state.record_decision(
            "LIV-06",
            decision="REJECT_STORY",
            reason="Няма новост в записа.",
            readiness_outcome="NO_STORY_CONFIRMED",
        )
        assert case is not None
        row = state._live_evidence_rows()["LIV-06-EVIDENCE"]
        assert row["workbench_decision"]["decision"] == "REJECT_STORY"
        assert row["workbench_decision"]["readiness_outcome"] == "NO_STORY_CONFIRMED"
        assert row["readiness"]["editor_override"]["action"] == "REJECT_STORY"
        # No case row was ever created and no draft exists.
        assert state.load_cases() == []

    def test_research_more_can_request_research(self, wf_dir):
        _add_evidence(
            wf_dir,
            "LIV09-EVIDENCE",
            status="RESEARCH_MORE",
            packet={
                "source_url": "transcript://editor-supplied",
                "source_type": "council_transcript",
                "facts": [{"id": "f1", "text": "Известен факт"}],
                "unknowns": ["липсва дата"],
            },
            readiness_rounds={
                "research_rounds": [
                    {
                        "round": 1,
                        "missing_dimensions": ["when_where"],
                        "research_questions": ["Кога и къде?"],
                        "sources": [],
                    }
                ],
                "targeted_research_rounds": 1,
            },
        )
        view = state.case_view("LIV-09")
        assert view["kind"] == "research"
        page = html.render_case(view)
        assert "Какво е известно" in page
        assert "Известен факт" in page
        assert "when_where" in page
        assert "Кога и къде?" in page
        case = state.record_decision(
            "LIV-09",
            decision="REQUEST_MORE_RESEARCH",
            reason="Липсват дата и място.",
            readiness_outcome="RESEARCH_REQUESTED",
        )
        assert case["workbench_decision"]["decision"] == "REQUEST_MORE_RESEARCH"
        row = state._live_evidence_rows()["LIV09-EVIDENCE"]
        assert row["readiness"]["post_loop_decision"] == "EDITOR_DECISION_REQUIRED"

    def test_editor_decision_required_case(self, wf_dir):
        _add_evidence(
            wf_dir,
            "LIV03-EVIDENCE",
            status="RESEARCH_MORE",
            readiness={
                "status": "RESEARCH_MORE",
                "post_loop_decision": "EDITOR_DECISION_REQUIRED",
            },
        )
        view = state.case_view("LIV-03")
        assert view is not None
        assert view["kind"] == "decision"
        page = html.render_case(view)
        assert 'id="workspace"' not in page
        assert "Редакторско решение" in page

    def test_decision_requires_reason(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        with pytest.raises(state.WorkbenchError, match="причина"):
            state.record_decision("LIV-06", decision="REJECT_STORY", reason="")

    def test_unknown_decision_rejected(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        with pytest.raises(state.WorkbenchError, match="непознато решение"):
            state.record_decision("LIV-06", decision="BOGUS", reason="x")

    def test_invalid_readiness_outcome_rejected(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        with pytest.raises(state.WorkbenchError, match="невалиден readiness_outcome"):
            state.record_decision(
                "LIV-06", decision="REJECT_STORY", reason="x", readiness_outcome="BOGUS"
            )

    def test_nostory_has_no_finalize_surface(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        page = html.render_case(state.case_view("LIV-06"))
        assert 'id="finalize"' not in page

    def test_finalize_refuses_evidence_only_case(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        with pytest.raises(state.WorkbenchError, match="няма AI чернова"):
            state.finalize(
                "LIV-06",
                headline="x",
                body="y",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="LIGHT",
            )


# --------------------------------------------------------------------------
# working copy
# --------------------------------------------------------------------------


class TestWorkingCopy:
    def test_save_and_load(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        case = state.find_case("LIV-01")
        doc = state.save_working_copy(
            case,
            headline="Редакторско заглавие",
            body="Редакторски текст.",
            review_answers={"would_publish": "YES"},
        )
        assert doc["case_id"] == "LIV-01"
        assert doc["base_draft_id"] == "draft-1"
        loaded = state.load_working_copy("LIV-01")
        assert loaded["headline"] == "Редакторско заглавие"
        assert loaded["review_answers"] == {"would_publish": "YES"}

    def test_save_never_finalizes(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.save_working_copy(
            state.find_case("LIV-01"), headline="H", body="B", review_answers={"angle_right": "NO"}
        )
        case = state.find_case("LIV-01")
        assert not case.get("final_text")
        assert not case.get("editor_outcome")

    def test_save_does_not_mutate_ai_draft(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.save_working_copy(state.find_case("LIV-01"), headline="H", body="B")
        case = state.find_case("LIV-01")
        assert case["draft_headline"] == "AI заглавие"
        assert case["draft_text"].startswith("Първи абзац.")

    def test_unknown_answer_key_rejected(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        with pytest.raises(state.WorkbenchError, match="unknown working-copy answer keys"):
            state.save_working_copy(
                state.find_case("LIV-01"),
                headline="H",
                body="B",
                review_answers={"prefer_ai_start": "YES"},
            )

    def test_blank_answers_dropped(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        doc = state.save_working_copy(
            state.find_case("LIV-01"),
            headline="H",
            body="B",
            review_answers={"would_publish": "", "angle_right": "NO"},
        )
        assert doc["review_answers"] == {"angle_right": "NO"}

    def test_atomic_write_leaves_valid_json_and_no_temp_files(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        wc_path = wf_dir / "editor_working" / "LIV-01.json"
        wc_path.write_text("{\n", encoding="utf-8")
        state.save_working_copy(state.find_case("LIV-01"), headline="H", body="B")
        assert json.loads(wc_path.read_text(encoding="utf-8"))["headline"] == "H"
        assert list((wf_dir / "editor_working").glob("*.tmp")) == []

    def test_stale_detection(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.save_working_copy(state.find_case("LIV-01"), headline="H", body="B")
        case = state.find_case("LIV-01")
        assert state.working_copy_is_stale(case, state.load_working_copy("LIV-01")) is False
        case["draft_id"] = "draft-2"
        assert state.working_copy_is_stale(case, state.load_working_copy("LIV-01")) is True

    def test_stale_case_flagged_in_queue(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.save_working_copy(state.find_case("LIV-01"), headline="H", body="B")
        case = state.find_case("LIV-01")
        case["draft_id"] = "draft-2"
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        row = next(r for r in state.queue()["live"] if r["case_id"] == "LIV-01")
        assert row["stale"] is True
        # A stale working copy needs attention: it stays in the editing queue.
        assert row["filter"] == "edit"

    def test_corrupt_working_copy_reads_as_missing(self, wf_dir):
        """A truncated working-copy file is non-authoritative state, not a 500."""
        _normal_case(wf_dir, "LIV-01")
        (wf_dir / "editor_working" / "LIV-01.json").write_text("{", encoding="utf-8")
        assert state.load_working_copy("LIV-01") is None
        case = state.find_case("LIV-01")
        assert state.working_copy_is_stale(case, None) is False
        assert state.queue()["live"][0]["wc"] is None
        assert 'id="workspace"' in html.render_case(state.case_view("LIV-01"))

    def test_rebase_adopts_new_generation_keeps_text(self, wf_dir):
        """Only an explicit accept-new-base re-bases; a plain save never does."""
        _normal_case(wf_dir, "LIV-01")
        state.save_working_copy(state.find_case("LIV-01"), headline="H", body="B")
        case = state.find_case("LIV-01")
        case["draft_id"] = "draft-2"
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        fresh = state.find_case("LIV-01")
        state.save_working_copy(fresh, headline="H2", body="B2")
        doc = state.load_working_copy("LIV-01")
        assert doc["base_draft_id"] == "draft-1"
        assert state.working_copy_is_stale(fresh, doc) is True
        state.save_working_copy(fresh, headline="H3", body="B3", accept_new_base=True)
        doc = state.load_working_copy("LIV-01")
        assert doc["base_draft_id"] == "draft-2"
        assert doc["headline"] == "H3"
        assert state.working_copy_is_stale(fresh, doc) is False

    def test_save_on_finalized_case_refused(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="H",
            body="B",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            base_draft_id="draft-1",
        )
        with pytest.raises(state.WorkbenchError, match="вече финализиран"):
            state.save_working_copy(state.find_case("LIV-01"), headline="X", body="Y")
        assert state.load_working_copy("LIV-01") is None


# --------------------------------------------------------------------------
# finalization
# --------------------------------------------------------------------------


class TestFinalize:
    def test_valid_finalization_uses_contract(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="Финално заглавие",
            body="Финалният текст.",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="MODERATE",
            time_saved_estimate="5-15 min",
            prefer_ai_start="YES",
            readiness_outcome="ANGLE_ACCEPTED",
            readiness_answers={"would_publish": "YES", "headline_strong": "NO"},
            base_draft_id="draft-1",
        )
        case = state.find_case("LIV-01")
        assert case["final_text"] == "Финалният текст."
        assert case["final_headline"] == "Финално заглавие"
        assert case["editing_weight"] == "MODERATE"
        assert case["prefer_ai_start"] == "YES"
        assert case["readiness_outcome"] == "ANGLE_ACCEPTED"
        assert case["readiness_answers"] == {"would_publish": "YES", "headline_strong": "NO"}
        # Deterministic diff + classification are computed by the contract.
        assert case["diff"]["headline_changed"] is True
        assert "counts" in case["revision_classification"]
        # AI draft untouched.
        assert case["draft_headline"] == "AI заглавие"
        # Audit row recorded.
        assert any(
            a["action"] == "editor_final_submitted" and a["case_id"] == "LIV-01"
            for a in state.read_actions("LIV-01")
        )

    def test_second_finalization_refused(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="H",
            body="B",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            base_draft_id="draft-1",
        )
        with pytest.raises(state.WorkbenchError, match="вече финализиран"):
            state.finalize(
                "LIV-01",
                headline="H2",
                body="B2",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="LIGHT",
            )

    def test_invalid_editing_weight_rejected(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        with pytest.raises(cases_mod.CaseError, match="bad editing_weight"):
            state.finalize(
                "LIV-01",
                headline="H",
                body="B",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="BOGUS",
            )

    def test_invalid_editor_outcome_rejected(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        with pytest.raises(cases_mod.CaseError, match="bad editor_outcome"):
            state.finalize(
                "LIV-01",
                headline="H",
                body="B",
                editor_outcome="PUBLISH_NOW",
                editing_weight="LIGHT",
            )

    def test_invalid_readiness_answers_rejected(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        with pytest.raises(cases_mod.CaseError, match="unknown readiness_answers"):
            state.finalize(
                "LIV-01",
                headline="H",
                body="B",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="LIGHT",
                readiness_answers={"prefer_ai_start": "YES"},
            )

    def test_stale_generation_finalization_blocked(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        with pytest.raises(state.StaleDraftError, match="по-нова AI версия"):
            state.finalize(
                "LIV-01",
                headline="H",
                body="B",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="LIGHT",
                base_draft_id="draft-0",
            )
        assert not state.find_case("LIV-01").get("final_text")

    def test_stale_working_copy_finalization_blocked(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.save_working_copy(state.find_case("LIV-01"), headline="H", body="B")
        case = state.find_case("LIV-01")
        case["draft_id"] = "draft-2"
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        with pytest.raises(state.StaleDraftError):
            state.finalize(
                "LIV-01",
                headline="H",
                body="B",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="LIGHT",
            )

    def test_dryrun_finalization_refused(self, wf_dir):
        _add_case(wf_dir, "WFX-01", track=cases_mod.TRACK_DRYRUN, evidence_id="EV-1")
        with pytest.raises(state.WorkbenchError, match="еталонни случаи"):
            state.finalize(
                "WFX-01",
                headline="H",
                body="B",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="LIGHT",
            )

    def test_readiness_answers_absent_by_default(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="H",
            body="B",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            base_draft_id="draft-1",
        )
        assert state.find_case("LIV-01").get("readiness_answers") in ({}, None)

    def test_empty_body_finalization_refused(self, wf_dir):
        """An article final needs a headline and a body (a decision does not)."""
        _normal_case(wf_dir, "LIV-01")
        with pytest.raises(state.WorkbenchError, match="изисква заглавие и текст"):
            state.finalize(
                "LIV-01",
                headline="H",
                body="   ",
                editor_outcome="ACCEPTED_FOR_EDIT",
                editing_weight="LIGHT",
            )
        assert not state.find_case("LIV-01").get("final_text")


# --------------------------------------------------------------------------
# HTML helper surfaces
# --------------------------------------------------------------------------


class TestHtmlSurfaces:
    def test_esc(self):
        assert html.esc("<b>&") == "&lt;b&gt;&amp;"
        assert html.esc(None) == ""

    def test_filter_nav_marks_active(self):
        nav = html.filter_nav("edit")
        assert 'class="active" href="/cases?filter=edit"' in nav

    def test_finalize_form_exposes_contract_fields(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        page = html.render_case(state.case_view("LIV-01"))
        for field in (
            'name="headline"',
            'name="body"',
            'name="editor_outcome"',
            'name="editing_weight"',
            'name="time_saved_estimate"',
            'name="prefer_ai_start"',
            'name="readiness_outcome"',
            'name="base_draft_id"',
        ):
            assert field in page
        assert "Финализирай редакторската версия" in page
        # The answers prefix must match what the POST handler reads.
        assert 'name="answer_would_publish"' in page

    def test_workspace_hidden_once_finalized(self, wf_dir):
        """No editor workspace on an immutable final (nothing could apply it)."""
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="Финал",
            body="Финалният текст.",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            base_draft_id="draft-1",
        )
        page = html.render_case(state.case_view("LIV-01"))
        assert 'id="workspace"' not in page
        assert "/finalize" not in page
        assert "Финализирана статия (неизменима)" in page

    def test_stale_workspace_offers_explicit_rebase(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.save_working_copy(state.find_case("LIV-01"), headline="H", body="B")
        case = state.find_case("LIV-01")
        case["draft_id"] = "draft-2"
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        page = html.render_case(state.case_view("LIV-01"))
        assert 'name="accept_base"' in page
        assert "Междувременно е генерирана по-нова AI версия." in page
        assert "Приемам новата AI версия за основа" in page
        # The finalize surface states why it is blocked.
        assert "Финализирането е блокирано" in page

    def test_transcript_trust_label_and_human_locator(self, wf_dir):
        """§16/§17: friendly recording time + translated trust level."""
        _add_case(wf_dir, "LIV-02", evidence_id="LIV-02-EVIDENCE")
        _add_evidence(
            wf_dir,
            "LIV-02-EVIDENCE",
            status="DRAFT_READY",
            packet={
                "source_url": "transcript://editor-supplied",
                "source_type": "council_transcript",
                "facts": [{"id": "f1", "text": "Известен факт"}],
                "provenance": {
                    "sources_used": ["S-TR"],
                    "attached": {
                        "f1": [{"locator": "seg1@t=08:42.250-09:17", "source_id": "S-TR"}]
                    },
                },
            },
        )
        view = state.case_view("LIV-02")
        assert view["trust"] == "AUTO_CAPTION"
        page = html.render_case(view)
        assert "Автоматичен YouTube транскрипт" in page
        assert "08:42–09:17" in page
        assert "08:42.250" not in page
        assert "seg1@t=" not in page

    def test_final_surface_translates_prefer_ai_start(self, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="H",
            body="B",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            prefer_ai_start="MIXED",
            base_draft_id="draft-1",
        )
        page = html.render_case(state.case_view("LIV-01"))
        assert "Предпочитание за AI начало</dt><dd>Частично</dd>" in page

    def test_decision_form_marks_reason_required(self, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        page = html.render_case(state.case_view("LIV-06"))
        assert "Причина (задължително" in page


# --------------------------------------------------------------------------
# HTTP layer (localhost only)
# --------------------------------------------------------------------------


# A private opener: several other test modules patch `urllib.request.urlopen`
# as a module global, so these HTTP tests must not depend on it.
_OPENER = urllib.request.build_opener()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(url):
    return _OPENER.open(url, timeout=5)


def _post(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as err:
        return err


@pytest.fixture
def server(wf_dir):  # depends on wf_dir so the env is set before the server starts
    httpd = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


class TestHttp:
    def test_serve_defaults_to_localhost(self):
        assert inspect.signature(http.serve).parameters["host"].default == "127.0.0.1"

    def test_queue_page(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        with _get(f"{server}/cases") as resp:
            page = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "LIV-01" in page

    def test_home_landing_shows_daily_entry_point(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        with _get(f"{server}/") as resp:
            page = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "Начало" in page and "Прегледай историите" in page
        assert "Редакторски работен плот" not in page

    def test_unknown_case_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"{server}/case/NOPE")
        assert exc.value.code == 404

    def test_save_redirects_and_persists(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        resp = _post(
            f"{server}/case/LIV-01/save",
            {"headline": "Запазено заглавие", "body": "Запазен текст."},
        )
        assert resp.code == 303
        assert resp.headers["Location"].startswith("/case/LIV-01")
        doc = state.load_working_copy("LIV-01")
        assert doc["headline"] == "Запазено заглавие"
        # Saving alone never finalizes.
        assert not state.find_case("LIV-01").get("final_text")

    def test_finalize_redirects_and_persists(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        resp = _post(
            f"{server}/case/LIV-01/finalize",
            {
                "headline": "Финално",
                "body": "Финално тяло.",
                "editor_outcome": "ACCEPTED_FOR_EDIT",
                "editing_weight": "LIGHT",
                "base_draft_id": "draft-1",
            },
        )
        assert resp.code == 303
        assert state.find_case("LIV-01")["final_text"] == "Финално тяло."

    def test_finalize_invalid_enum_400(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        resp = _post(
            f"{server}/case/LIV-01/finalize",
            {
                "headline": "H",
                "body": "B",
                "editor_outcome": "ACCEPTED_FOR_EDIT",
                "editing_weight": "NOPE",
            },
        )
        assert resp.code == 400
        assert "bad editing_weight" in resp.read().decode("utf-8")

    def test_finalize_stale_409(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        resp = _post(
            f"{server}/case/LIV-01/finalize",
            {
                "headline": "H",
                "body": "B",
                "editor_outcome": "ACCEPTED_FOR_EDIT",
                "editing_weight": "LIGHT",
                "base_draft_id": "draft-old",
            },
        )
        assert resp.code == 409
        assert "по-нова AI версия" in resp.read().decode("utf-8")

    def test_decision_endpoint_for_nostory(self, server, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        resp = _post(
            f"{server}/case/LIV-06/decision",
            {"decision": "REJECT_STORY", "reason": "Потвърждавам: няма новина."},
        )
        assert resp.code == 303
        assert resp.headers["Location"].startswith("/case/LIV-06")
        row = state._live_evidence_rows()["LIV-06-EVIDENCE"]
        assert row["workbench_decision"]["decision"] == "REJECT_STORY"

    def test_decision_requires_reason_400(self, server, wf_dir):
        _add_evidence(wf_dir, "LIV-06-EVIDENCE", status="NO_PUBLISHABLE_ANGLE")
        resp = _post(f"{server}/case/LIV-06/decision", {"decision": "REJECT_STORY"})
        assert resp.code == 400

    def test_case_page_escapes_injected_source(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-04")
        _add_research(
            wf_dir,
            "LIV-04",
            [{"source_id": "S-1", "source_name": "<script>alert(1)</script>"}],
        )
        with _get(f"{server}/case/LIV-04") as resp:
            page = resp.read().decode("utf-8")
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_rebase_then_finalize_through_the_ui(self, server, wf_dir):
        """The stale guard is not a dead end: an explicit re-base opens the way."""
        _normal_case(wf_dir, "LIV-01")
        _post(f"{server}/case/LIV-01/save", {"headline": "H", "body": "B"})
        case = state.find_case("LIV-01")
        case["draft_id"] = "draft-2"
        cases_mod.save_cases([case], wf_dir / "cases.jsonl")
        final_form = {
            "headline": "H",
            "body": "B",
            "editor_outcome": "ACCEPTED_FOR_EDIT",
            "editing_weight": "LIGHT",
            "base_draft_id": "draft-2",
        }
        assert _post(f"{server}/case/LIV-01/finalize", final_form).code == 409
        rebase = _post(
            f"{server}/case/LIV-01/save",
            {"headline": "H", "body": "B", "accept_base": "1"},
        )
        assert rebase.code == 303
        doc = state.load_working_copy("LIV-01")
        assert doc["base_draft_id"] == "draft-2"
        assert state.working_copy_is_stale(state.find_case("LIV-01"), doc) is False
        assert _post(f"{server}/case/LIV-01/finalize", final_form).code == 303
        assert state.find_case("LIV-01")["final_text"] == "B"

    def test_save_on_finalized_case_400(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        state.finalize(
            "LIV-01",
            headline="H",
            body="B",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            base_draft_id="draft-1",
        )
        resp = _post(f"{server}/case/LIV-01/save", {"headline": "X", "body": "Y"})
        assert resp.code == 400
        assert state.load_working_copy("LIV-01") is None

    def test_finalize_empty_body_400(self, server, wf_dir):
        _normal_case(wf_dir, "LIV-01")
        resp = _post(
            f"{server}/case/LIV-01/finalize",
            {
                "headline": "H",
                "body": "",
                "editor_outcome": "ACCEPTED_FOR_EDIT",
                "editing_weight": "LIGHT",
            },
        )
        assert resp.code == 400
        assert not state.find_case("LIV-01").get("final_text")
