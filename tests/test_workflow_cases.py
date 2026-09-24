"""M2.7-9 workflow guarantee tests (spec §27): intake, modes, cases, lineage."""

from __future__ import annotations

import json

import pytest

from editor_assistant.workflow import cases as cases_mod
from editor_assistant.workflow import ideas as ideas_mod
from editor_assistant.workflow.ideas import (
    ANGLE_PREFIX,
    IdeaError,
    make_idea,
    read_ideas,
    request_draft,
    save_ideas,
    validate_idea,
)
from editor_assistant.workflow.modes import suggest_mode


def test_save_cases_never_truncates_the_store_on_a_failure(tmp_path):
    """The case store holds the only copy of an editor's final article.

    Regression: it used to be truncated in place, so a failure part-way through
    the rewrite left the store holding only the cases written before it.
    """
    path = tmp_path / "cases.jsonl"
    cases_mod.save_cases([{"case_id": "LIV-01"}, {"case_id": "LIV-02"}], path)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(TypeError):
        cases_mod.save_cases([{"case_id": "LIV-03"}, {"boom": object()}], path)
    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before.splitlines()[0])["case_id"] == "LIV-01"
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_cases_round_trips(tmp_path):
    path = tmp_path / "cases.jsonl"
    cases_mod.save_cases([{"case_id": "LIV-01", "final_text": "Кирилица"}], path)
    assert cases_mod.read_cases(path) == [{"case_id": "LIV-01", "final_text": "Кирилица"}]


# ---------- fixtures ----------


def _packet(text="", facts=("Факт едно.", "Факт два.", "Факт три."), dates=(), source_text=None):
    return {
        "evidence_id": "EV-T",
        "source_url": "u",
        "source_type": "t",
        "observed_at": "2026-09-16",
        "source_headline": "Заглавие",
        "facts": [
            {
                "id": f"f{i:02d}",
                "text": t,
                "source_reference": "source_text",
                "scope": "current_event",
            }
            for i, t in enumerate(facts, 1)
        ],
        "people": [],
        "organizations": [],
        "places": [],
        "dates": list(dates),
        "numbers": [],
        "quotes": [],
        "unknowns": [],
        "source_text": source_text if source_text is not None else text or " ".join(facts),
    }


def _draft_row():
    return {
        "evidence_id": "EV-XX",
        "voice": "VOICE_HOUSE",
        "mode": "MODE_STANDARD_NEWS",
        "semantic": {"pass": True, "n_unsupported": 0, "claims": []},
        "audit": {"primary": []},
        "draft": {
            "headline": "Черноморце посрещна фестивала",
            "body": "Първи абзац на черновата.\n\nВтори абзац на черновата.",
            "headlines": ["Черноморце посрещна фестивала"],
        },
        "lineage": {
            "draft_id": "deadbeef",
            "evidence_id": "EV-XX",
            "voice_id": "VOICE_HOUSE",
            "mode_id": "MODE_STANDARD_NEWS",
            "style_example_ids": ["a1", "a2"],
            "prompt_version": "m2.3b-prompt-1",
            "model": "test-model",
            "generated_at": "2026-09-16T00:00:00Z",
        },
    }


def _idea(**over):
    base = {
        "idea_id": "IDEA-1",
        "created_at": "2026-09-16T00:00:00Z",
        "source_type": "manual_lead",
        "source_url": "https://x",
        "source_reference": "ref",
        "title": "Заглавие",
        "what_changed": "Какво се е променило.",
        "why_now": "Сега.",
        "location": "Бургас",
        "possible_angle": "Ъгъл тук.",
        "status": "NEW",
    }
    base.update(over)
    return base


# ---------- 1. IdeaCard serialization ----------


def test_ideacard_serialization_roundtrip(tmp_path):
    idea = make_idea(**_idea())
    path = tmp_path / "ideas.jsonl"
    save_ideas([idea], path)
    loaded = read_ideas(path)
    assert loaded == [idea]
    assert loaded[0]["possible_angle"].startswith(ANGLE_PREFIX)


# ---------- G2: one canonical "may this idea enter drafting?" guard ----------


def test_assert_draftable_status_allows_only_new_follow_up_and_draft_requested():
    for status in ideas_mod.DRAFTABLE_STATUSES:
        idea = make_idea(**_idea(status=status))
        assert ideas_mod.assert_draftable_status(idea) is idea
    assert ideas_mod.DRAFTABLE_STATUSES == ("NEW", "FOLLOW_UP", "DRAFT_REQUESTED")


def test_assert_draftable_status_refuses_closed_and_unknown_states_without_mutation():
    for status in ("IGNORED", "NO_PUBLISHABLE_ANGLE", "AUTO_PUBLISH", None):
        idea = make_idea(**_idea(status="NEW"))
        idea["status"] = status  # bypass validate_idea to model unknown on-disk states
        before = json.dumps(idea, ensure_ascii=False, sort_keys=True)
        with pytest.raises(IdeaError):
            ideas_mod.assert_draftable_status(idea)
        # The refusal never mutates the idea — the store stays byte-identical.
        assert json.dumps(idea, ensure_ascii=False, sort_keys=True) == before
    # Readable Bulgarian refusal names the closed state.
    with pytest.raises(IdeaError, match="IGNORED"):
        ideas_mod.assert_draftable_status(make_idea(**_idea(status="IGNORED")))
    with pytest.raises(IdeaError, match="NO_PUBLISHABLE_ANGLE"):
        ideas_mod.assert_draftable_status(make_idea(**_idea(status="NO_PUBLISHABLE_ANGLE")))


def test_ideacard_validation_rejects_unlabeled_angle_and_bad_status():
    # make_idea auto-labels raw angle input; direct assignment must be rejected
    assert make_idea(**_idea(possible_angle="пързалката е страхотна"))["possible_angle"].startswith(
        ANGLE_PREFIX
    )
    with pytest.raises(IdeaError):
        validate_idea(dict(_idea(), possible_angle="пързалката е страхотна"))
    with pytest.raises(IdeaError):
        validate_idea(dict(_idea(), status="AUTO_PUBLISH"))
    with pytest.raises(IdeaError):
        validate_idea(dict(_idea(), what_changed=""))


# ---------- 2. Idea -> Evidence linkage (id carries through the case) ----------


def test_idea_to_case_linkage():
    idea = make_idea(**_idea())
    request_draft(idea)
    assert idea["status"] == "DRAFT_REQUESTED"
    case = cases_mod.open_case(
        case_id="WFX-99", idea_id=idea["idea_id"], evidence_id="EV-XX", draft=_draft_row()
    )
    assert case["idea_id"] == "IDEA-1" and case["evidence_id"] == "EV-XX"
    assert case["lineage"]["evidence_id"] == "EV-XX"
    assert case["style_example_ids"] == ["a1", "a2"]
    assert case["prompt_version"] == "m2.3b-prompt-1"


# ---------- 3. HOUSE default ----------


def test_house_is_default_voice():
    case = cases_mod.open_case(case_id="WFX-01", idea_id="i", evidence_id="e", draft=_draft_row())
    assert case["voice_selected"] == "VOICE_HOUSE"


# ---------- 4. mode suggestion + editor override ----------


def test_mode_suggestion_event_and_override_recorded():
    suggestion = suggest_mode(
        _packet(
            source_text="Фестивалът ще се проведе на 20 септември от 18:00 ч. на площада.",
            dates=["20 септември", "18:00 ч"],
        )
    )
    assert suggestion["suggested_mode"] == "MODE_EVENT_PREVIEW"
    assert suggestion["reason"]
    case = cases_mod.open_case(
        case_id="WFX-02",
        idea_id="i",
        evidence_id="e",
        draft=_draft_row(),
        mode="MODE_STANDARD_NEWS",
        mode_suggested=suggestion["suggested_mode"],
    )
    assert case["mode_selected"] == "MODE_STANDARD_NEWS"  # editor freely kept/overrode
    assert case["mode_changed"] is True
    case2 = cases_mod.open_case(
        case_id="WFX-03",
        idea_id="i",
        evidence_id="e",
        draft=_draft_row(),
        mode="MODE_EVENT_PREVIEW",
        mode_suggested="MODE_EVENT_PREVIEW",
    )
    assert case2["mode_changed"] is False


def test_mode_suggestion_brief_and_standard():
    small = suggest_mode(
        _packet(facts=("Един факт.",), source_text="Кратко известие. Малко факти. Това е всичко.")
    )
    assert small["suggested_mode"] == "MODE_BRIEF"
    plain = suggest_mode(_packet(source_text="Обикновена новина без особености. " * 60))
    assert plain["suggested_mode"] == "MODE_STANDARD_NEWS"


# ---------- 5. DESISLAVA remains explicit opt-in ----------


def test_desislava_is_explicit_optin():
    case = cases_mod.open_case(
        case_id="WFX-04",
        idea_id="i",
        evidence_id="e",
        draft=_draft_row(),
        voice="VOICE_DESISLAVA_RECENT",
    )
    assert case["voice_selected"] == "VOICE_DESISLAVA_RECENT"
    with pytest.raises(cases_mod.CaseError):
        cases_mod.open_case(
            case_id="WFX-05",
            idea_id="i",
            evidence_id="e",
            draft=_draft_row(),
            voice="VOICE_IMPROVISER",
        )


# ---------- 6. evidence/style separation preserved ----------


def test_style_examples_stay_out_of_factual_authority():
    # the case stores style example ids as retrieval provenance only;
    # the factual authority remains the EvidencePacket (audit/semantic only)
    case = cases_mod.open_case(
        case_id="WFX-11",
        idea_id="i",
        evidence_id="EV-1",
        draft=_draft_row(),
        style_example_ids=["s9"],
    )
    assert case["style_example_ids"] == ["s9"]
    assert "evidence_id" in case and "audit" in case
    assert not any("style" in k for k in case["audit"])


# ---------- 7. factual gate state persisted ----------


def test_factual_gate_state_persisted():
    row = _draft_row()
    row["semantic"] = {"pass": False, "n_unsupported": 2, "claims": []}
    case = cases_mod.open_case(
        case_id="WFX-06",
        idea_id="i",
        evidence_id="e",
        draft=row,
        factual_gate="FACTUAL_GATE_REVIEW",
    )
    assert case["factual_gate"] == "FACTUAL_GATE_REVIEW"
    assert case["audit"]["semantic"]["n_unsupported"] == 2
    with pytest.raises(cases_mod.CaseError):
        cases_mod.open_case(
            case_id="x", idea_id="i", evidence_id="e", draft=row, factual_gate="AUTO_PASSED"
        )


# ---------- 8. draft is never overwritten by final ----------


def test_draft_never_overwritten_by_final():
    original = _draft_row()
    case = cases_mod.open_case(case_id="WFX-07", idea_id="i", evidence_id="e", draft=original)
    before = case["draft_text"]
    cases_mod.record_editor_final(
        case,
        final_headline="Изцяло ново заглавие от редактора",
        final_text="Изцяло нов текст, написан от редактора след тежка редакция.",
        editor_outcome="REJECTED",
        editing_weight="REWRITE",
        time_saved_estimate="<5 min",
        published_or_ready="NOT_READY",
        notes="draft unusable",
    )
    assert case["draft_text"] == before
    assert original["draft"]["body"] == before
    assert case["final_text"] != case["draft_text"]
    assert case["editor_outcome"] == "REJECTED"


def test_load_revisions_refuses_final_identical_to_draft(tmp_path):
    case = cases_mod.open_case(case_id="WFX-08", idea_id="i", evidence_id="e", draft=_draft_row())
    cases_mod.record_editor_final(
        case,
        final_headline=case["draft_headline"],
        final_text=case["draft_text"],
        editor_outcome="ACCEPTED_FOR_EDIT",
        editing_weight="LIGHT",
    )
    path = tmp_path / "cases.jsonl"
    cases_mod.save_cases([case], path)
    with pytest.raises(cases_mod.CaseError):
        cases_mod.load_revisions(path)


def test_editor_final_validates_enums():
    case = cases_mod.open_case(case_id="WFX-09", idea_id="i", evidence_id="e", draft=_draft_row())
    with pytest.raises(cases_mod.CaseError):
        cases_mod.record_editor_final(
            case,
            final_headline="h",
            final_text="t",
            editor_outcome="PUBLISHED_IT",
            editing_weight="LIGHT",
        )
    with pytest.raises(cases_mod.CaseError):
        cases_mod.record_editor_final(
            case,
            final_headline="h",
            final_text="t",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="SORT_OF_LIGHT",
        )
    with pytest.raises(cases_mod.CaseError):
        cases_mod.record_editor_final(
            case,
            final_headline="h",
            final_text="t",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            time_saved_estimate="about an hour",
        )


# ---------- CLI editor-surface roundtrip ----------


def _args(**kw):
    return type("A", (), kw)()


def test_cli_new_idea_and_request_draft(tmp_path, monkeypatch):
    from editor_assistant.workflow import cli

    ideas_path = tmp_path / "ideas.jsonl"
    monkeypatch.setattr(cli, "IDEAS_PATH", ideas_path)
    payload = tmp_path / "ideas_in.json"
    payload.write_text(json.dumps([_idea(idea_id="IDEA-9")], ensure_ascii=False), encoding="utf-8")
    cli.cmd_new_idea(_args(file=str(payload)))
    cli.cmd_request_draft(_args(idea_id="IDEA-9"))
    loaded = read_ideas(ideas_path)
    assert loaded[0]["idea_id"] == "IDEA-9" and loaded[0]["status"] == "DRAFT_REQUESTED"


def test_cli_finalize_roundtrip(tmp_path, monkeypatch):
    from editor_assistant.workflow import cli

    wf = tmp_path / "editorial_workflow"
    wf.mkdir()
    cases_path = wf / "cases.jsonl"
    cases_mod.save_cases(
        [
            cases_mod.open_case(
                case_id="WFX-50", idea_id="IDEA-1", evidence_id="EV-XX", draft=_draft_row()
            )
        ],
        cases_path,
    )
    monkeypatch.setattr(cli, "CASES_PATH", cases_path)
    scorecard = wf / "WFX-50.json"
    scorecard.write_text(
        json.dumps(
            {
                "final_headline": "Редакторско заглавие",
                "final_text": "Редакторски финален текст, различен от черновата.",
                "editor_outcome": "ACCEPTED_FOR_EDIT",
                "editing_weight": "MODERATE",
                "time_saved_estimate": "5-15 min",
                "published_or_ready": "READY",
                "notes": "ок",
                "idea_status": "FOLLOW_UP",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cli.cmd_finalize(_args(case_id="WFX-50", file=str(scorecard)))
    loaded = cases_mod.read_cases(cases_path)[0]
    assert loaded["final_text"].startswith("Редакторски")
    assert loaded["draft_text"] == "Първи абзац на черновата.\n\nВтори абзац на черновата."
    assert loaded["idea_status"] == "FOLLOW_UP"
    m = cases_mod.workflow_metrics(cases_mod.read_cases(cases_path))
    assert m["completed"] == 1 and m["headline_modified"] == 1
    assert m["light_or_moderate"] == 1 and m["start_from_draft_yes"] == 1


# ---------- tracks: GROUND_TRUTH_DRYRUN vs LIVE_EDITORIAL_PILOT ----------


def test_dryrun_case_refuses_effort_metrics():
    """Track A cases reject editor effort/adoption fields (no fabricated savings)."""
    case = cases_mod.open_case(
        case_id="WFX-90",
        idea_id="IDEA-X",
        evidence_id="EV-01",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
        source_url="https://chernomorie-bg.com/някаква-статия",
    )
    assert case["track"] == cases_mod.TRACK_DRYRUN
    with pytest.raises(cases_mod.CaseError, match="GROUND_TRUTH_DRYRUN"):
        cases_mod.record_editor_final(
            case,
            final_headline="Публикувано",
            final_text="Текст на публикацията.",
            editor_outcome=cases_mod.EDITOR_OUTCOMES[0],
            editing_weight="MODERATE",
            time_saved_estimate="5-15 min",
        )


def test_dryrun_stores_published_reference_without_effort():
    case = cases_mod.open_case(
        case_id="WFX-91",
        idea_id="IDEA-X",
        evidence_id="EV-01",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
    )
    cases_mod.record_editor_final(
        case,
        final_headline="Публикуванo заглавие",
        final_text="Публикуван текст.",
        editor_outcome=None,
        editing_weight="NONE",
        _published_reference=True,
    )
    assert case["final_text"] == "Публикуван текст."
    assert not case["editor_outcome"] and case["editing_weight"] == "NONE"


def test_live_metrics_exclude_dryrun_cases():
    """Effort metrics count LIVE cases only; tracks are reported separately."""
    live = cases_mod.open_case(
        case_id="LIV-01",
        idea_id="IDEA-X",
        evidence_id="EV-01",
        draft=_draft_row(),
        track=cases_mod.TRACK_LIVE,
        source_url="https://burgas.очаквано/news",
    )
    cases_mod.record_editor_final(
        live,
        final_headline="Ф",
        final_text="Т",
        editor_outcome=cases_mod.EDITOR_OUTCOMES[0],
        editing_weight="LIGHT",
        time_saved_estimate="5-15 min",
        published_or_ready="PUBLISHED",
    )
    dry = cases_mod.open_case(
        case_id="WFX-92",
        idea_id="IDEA-X",
        evidence_id="EV-02",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
    )
    cases_mod.record_editor_final(
        dry,
        final_headline="P",
        final_text="P",
        editor_outcome=None,
        editing_weight="NONE",
        _published_reference=True,
    )
    m = cases_mod.workflow_metrics([live, dry])
    assert m["effort_basis"] == cases_mod.TRACK_LIVE
    assert m["tracks"][cases_mod.TRACK_LIVE] == 1
    assert m["tracks"][cases_mod.TRACK_DRYRUN] == 1
    assert m["total_cases"] == 1 and m["completed"] == 1  # dry-run not in effort basis


def test_live_case_refuses_published_chernomorie_source():
    """No circular evaluation: published Chеrnomorie article can't feed its own LIVE case."""
    with pytest.raises(cases_mod.CaseError, match="circular"):
        cases_mod.open_case(
            case_id="LIV-02",
            idea_id="IDEA-X",
            evidence_id="EV-01",
            draft=_draft_row(),
            track=cases_mod.TRACK_LIVE,
            source_url="https://chernomorie-bg.com/публикувано-днес",
        )
    # the same URL is fine for the benchmark track
    case = cases_mod.open_case(
        case_id="WFX-93",
        idea_id="IDEA-X",
        evidence_id="EV-01",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
        source_url="https://chernomorie-bg.com/публикувано-днес",
    )
    assert case["track"] == cases_mod.TRACK_DRYRUN


def test_track_validation():
    with pytest.raises(cases_mod.CaseError, match="bad track"):
        cases_mod.open_case(
            case_id="X", idea_id="I", evidence_id="E", draft=_draft_row(), track="SOMETHING_ELSE"
        )


def test_benchmark_case_shape(tmp_path):
    from editor_assistant.workflow.benchmark import benchmark_case

    case = cases_mod.open_case(
        case_id="WFX-94",
        idea_id="IDEA-X",
        evidence_id="EV-01",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
    )
    out = benchmark_case(
        case,
        "Черноморце посрещна фестивала днес",
        "Първи абзац на публикацията.\n\nВтори абзац, малко променен.",
    )
    assert 0.0 <= out["headline_overlap"] <= 1.0
    assert 0.0 <= out["structural_similarity"] <= 1.0
    assert out["factual"]["semantic_pass"] is True
    assert "benchmark only" in out["factual"] or isinstance(out["word_delta_vs_published"], int)


def test_benchmark_report_skips_unmeasured(tmp_path):
    from editor_assistant.workflow.benchmark import benchmark_report

    path = tmp_path / "cases.jsonl"
    case = cases_mod.open_case(
        case_id="WFX-95",
        idea_id="IDEA-X",
        evidence_id="EV-01",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
    )
    cases_mod.save_cases([case], path)
    rep = benchmark_report(path)
    assert rep["summary"]["cases"] == 1 and rep["summary"]["measured"] == 0
    assert rep["summary"]["pending_published"] == ["WFX-95"]


def test_cli_refuses_double_finalize(tmp_path, monkeypatch, capsys):
    from editor_assistant.workflow import cli

    wf = tmp_path / "editorial_workflow"
    wf.mkdir()
    cases_path = wf / "cases.jsonl"
    case = cases_mod.open_case(
        case_id="WFX-51", idea_id="IDEA-1", evidence_id="EV-XX", draft=_draft_row()
    )
    cases_mod.record_editor_final(
        case,
        final_headline="Финал",
        final_text="Финален текст.",
        editor_outcome="ACCEPTED_FOR_EDIT",
        editing_weight="LIGHT",
    )
    cases_mod.save_cases([case], cases_path)
    monkeypatch.setattr(cli, "CASES_PATH", cases_path)
    scorecard = wf / "again.json"
    scorecard.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.cmd_finalize(_args(case_id="WFX-51", file=str(scorecard)))


# ---------- M2R §23/§33: editor readiness-outcome learning signal ----------


def _live_case(case_id="LIV-77"):
    return cases_mod.open_case(
        case_id=case_id,
        idea_id="IDEA-R",
        evidence_id="EV-R",
        draft=_draft_row(),
        track=cases_mod.TRACK_LIVE,
        source_url="https://upstream.example/lead",
    )


def test_open_case_keeps_headline_candidates():
    draft = _draft_row()
    draft["draft"]["headlines"] = [
        "Основно заглавие",
        "Алтернативен ъгъл",
    ]
    case = cases_mod.open_case(
        case_id="LIV-90",
        idea_id="IDEA-T",
        evidence_id="EV-T",
        draft=draft,
    )
    assert case["draft_headlines"] == ["Основно заглавие", "Алтернативен ъгъл"]
    assert case["draft_headline"] == draft["draft"]["headline"]


def test_readiness_outcome_recorded_on_live_case():
    case = _live_case()
    cases_mod.record_editor_final(
        case,
        final_headline="Финал",
        final_text="Финален текст, различен от черновата.",
        editor_outcome="ACCEPTED_FOR_EDIT",
        editing_weight="LIGHT",
        readiness_outcome="ANGLE_ACCEPTED",
        readiness_note="хук-ът беше точен",
    )
    assert case["readiness_outcome"] == "ANGLE_ACCEPTED"
    assert case["readiness_note"] == "хук-ът беше точен"


def test_readiness_outcome_validated_against_vocabulary():
    case = _live_case()
    with pytest.raises(cases_mod.CaseError, match="readiness_outcome"):
        cases_mod.record_editor_final(
            case,
            final_headline="Ф",
            final_text="Т",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            readiness_outcome="SOUNDED_FINE",
        )


def test_readiness_note_requires_outcome():
    case = _live_case()
    with pytest.raises(cases_mod.CaseError, match="readiness_note"):
        cases_mod.record_editor_final(
            case,
            final_headline="Ф",
            final_text="Т",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            readiness_note="само бележка без присъда",
        )


def test_readiness_outcome_refused_on_dryrun_case():
    case = cases_mod.open_case(
        case_id="WFX-93",
        idea_id="IDEA-R",
        evidence_id="EV-R",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
    )
    with pytest.raises(cases_mod.CaseError, match="LIVE-case learning signal"):
        cases_mod.record_editor_final(
            case,
            final_headline="P",
            final_text="P",
            editor_outcome=None,
            editing_weight="NONE",
            _published_reference=True,
            readiness_outcome="ANGLE_ACCEPTED",
        )


def test_readiness_outcomes_aggregated_in_metrics():
    a = _live_case("LIV-80")
    cases_mod.record_editor_final(
        a,
        final_headline="Ф1",
        final_text="Финален текст един.",
        editor_outcome="ACCEPTED_FOR_EDIT",
        editing_weight="LIGHT",
        readiness_outcome="ANGLE_ACCEPTED",
    )
    b = _live_case("LIV-81")
    cases_mod.record_editor_final(
        b,
        final_headline="Ф2",
        final_text="Финален текст два.",
        editor_outcome="REJECTED",
        editing_weight="REWRITE",
        readiness_outcome="NO_STORY_CONFIRMED",
    )
    c = _live_case("LIV-82")
    cases_mod.record_editor_final(
        c,
        final_headline="Ф3",
        final_text="Финален текст три.",
        editor_outcome="MIXED",
        editing_weight="MODERATE",
    )
    m = cases_mod.workflow_metrics([a, b, c])
    assert m["readiness_outcomes"]["ANGLE_ACCEPTED"] == 1
    assert m["readiness_outcomes"]["NO_STORY_CONFIRMED"] == 1
    assert m["readiness_outcomes"]["RESEARCH_REQUESTED"] == 0
    assert m["readiness_outcome_recorded"] == 2


def test_cli_finalize_persists_readiness_outcome(tmp_path, monkeypatch, capsys):
    from editor_assistant.workflow import cli

    wf = tmp_path / "editorial_workflow"
    wf.mkdir()
    cases_path = wf / "cases.jsonl"
    cases_mod.save_cases([_live_case("LIV-83")], cases_path)
    monkeypatch.setattr(cli, "CASES_PATH", cases_path)
    scorecard = wf / "LIV-83.json"
    scorecard.write_text(
        json.dumps(
            {
                "final_headline": "Редакторско заглавие",
                "final_text": "Редакторски финален текст, различен от черновата.",
                "editor_outcome": "MIXED",
                "editing_weight": "MODERATE",
                "readiness_outcome": "RESEARCH_REQUESTED",
                "readiness_note": "трябва още проверка на сумата",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cli.cmd_finalize(_args(case_id="LIV-83", file=str(scorecard)))
    loaded = cases_mod.read_cases(cases_path)[0]
    assert loaded["readiness_outcome"] == "RESEARCH_REQUESTED"
    assert loaded["readiness_note"] == "трябва още проверка на сумата"
    m = cases_mod.workflow_metrics(cases_mod.read_cases(cases_path))
    assert m["readiness_outcomes"]["RESEARCH_REQUESTED"] == 1
    assert "readiness_outcome=RESEARCH_REQUESTED" in capsys.readouterr().out


def test_readiness_answers_recorded_and_validated():
    case = _live_case()
    cases_mod.record_editor_final(
        case,
        final_headline="Финал",
        final_text="Финален текст, различен от черновата.",
        editor_outcome="ACCEPTED_FOR_EDIT",
        editing_weight="LIGHT",
        readiness_outcome="ANGLE_CHANGED",
        readiness_answers={"would_publish": "YES", "angle_right": "CHANGE"},
    )
    assert case["readiness_answers"] == {"would_publish": "YES", "angle_right": "CHANGE"}
    with pytest.raises(cases_mod.CaseError, match="readiness_answers"):
        cases_mod.record_editor_final(
            case,
            final_headline="Ф",
            final_text="Т",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            readiness_answers={"would_publish": "MAYBE"},
        )
    with pytest.raises(cases_mod.CaseError, match="unknown readiness_answers keys"):
        cases_mod.record_editor_final(
            case,
            final_headline="Ф",
            final_text="Т",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="LIGHT",
            readiness_answers={"style": "YES"},
        )


def test_readiness_answers_refused_on_dryrun_case():
    case = cases_mod.open_case(
        case_id="WFX-94",
        idea_id="IDEA-S",
        evidence_id="EV-S",
        draft=_draft_row(),
        track=cases_mod.TRACK_DRYRUN,
    )
    with pytest.raises(cases_mod.CaseError, match="LIVE-case learning signal"):
        cases_mod.record_editor_final(
            case,
            final_headline="Ф",
            final_text="Т",
            editor_outcome="ACCEPTED_FOR_EDIT",
            editing_weight="NONE",
            _published_reference=True,
            readiness_answers={"would_publish": "YES"},
        )
