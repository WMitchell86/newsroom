"""M2.9 diff/classification + lineage/publish-boundary tests (spec §27)."""

from __future__ import annotations

from editor_assistant.workflow import cases as cases_mod
from editor_assistant.workflow.diff import CATEGORIES, diff_draft_final


def _case(
    final_headline,
    final_text,
    draft_headline="Старата заглавна линия",
    draft_text="Първи абзац на черновата.\n\nВтори абзац на черновата.",
    outcome="ACCEPTED_FOR_EDIT",
    weight="MODERATE",
):
    case = cases_mod.open_case(
        case_id="WFX-T",
        idea_id="IDEA-1",
        evidence_id="EV-1",
        draft={
            "lineage": {
                "draft_id": "d1",
                "evidence_id": "EV-1",
                "mode_id": "MODE_STANDARD_NEWS",
                "style_example_ids": [],
            },
            "draft": {"headline": draft_headline, "body": draft_text},
            "semantic": {"pass": True, "n_unsupported": 0, "claims": []},
            "audit": {},
        },
    )
    cases_mod.record_editor_final(
        case,
        final_headline=final_headline,
        final_text=final_text,
        editor_outcome=outcome,
        editing_weight=weight,
    )
    return case


# ---------- 9. deterministic diff ----------


def test_deterministic_diff_basics():
    d1 = diff_draft_final("H", "Пара едно.\n\nПара две.", "H", "Пара едно.\n\nПара две.")
    assert d1["headline_changed"] is False
    assert d1["paragraphs"] == {"added": [], "removed": [], "reordered": False}
    d2 = diff_draft_final("H1", "А.\n\nБ.", "H2", "А.\n\nБ.\n\nВ.")
    assert d2["headline_changed"] is True
    assert d2["paragraphs"]["added"] == ["В."]
    assert not d2["paragraphs"]["removed"]
    d3 = diff_draft_final("H", "А.\n\nБ.", "H", "Б.\n\nА.")
    assert d3["paragraphs"]["reordered"] is True
    # determinism: same inputs -> identical output
    assert diff_draft_final("H1", "А.\n\nБ.", "H2", "А.\n\nБ.\n\nВ.") == d2


# ---------- 10. revision classification schema ----------


def test_classification_schema_valid():
    assert set(CATEGORIES) == {
        "FACT",
        "STYLE",
        "STRUCTURE",
        "TONE",
        "HEADLINE",
        "LOCAL_TERMINOLOGY",
        "FORMAT",
        "OTHER",
    }
    case = _case("Ново заглавие", "Първи абзац на черновата.\n\nВтори абзац на черновата.")
    rc = case["revision_classification"]
    assert set(rc["counts"]) == set(CATEGORIES)
    assert rc["counts"]["HEADLINE"] == 1
    assert rc["dominant"] in CATEGORIES


def test_fact_beats_style_for_number_changes():
    draft = "Събитието събра 500 участници от 11 държави."
    final = "Събитието събра 500 участници от 12 държави."
    case = _case("H", final, draft_text=draft)
    counts = case["revision_classification"]["counts"]
    assert counts["FACT"] == 1
    assert counts["STYLE"] == 0


def test_paragraph_move_is_structure_not_style():
    case = _case("H", "Втори абзац на черновата.\n\nПърви абзац на черновата.")
    assert case["revision_classification"]["counts"]["STRUCTURE"] >= 1


def test_removed_sentence_is_structure_and_rewording_is_style():
    case = _case("H", "Първи абзац на черновата.")  # second paragraph removed
    counts = case["revision_classification"]["counts"]
    assert counts["STRUCTURE"] >= 1
    case2 = _case("H", "Първи абзац на черновата, леко преразказан.\n\nВтори абзац на черновата.")
    assert case2["revision_classification"]["counts"]["STYLE"] >= 1


# ---------- 11. full lineage reconstructable ----------


def test_full_lineage_reconstructable(tmp_path):
    case = _case("H", "Финален текст.")
    path = tmp_path / "cases.jsonl"
    cases_mod.save_cases([case], path)
    loaded = cases_mod.read_cases(path)[0]
    lin = loaded["lineage"]
    assert lin["draft_id"] == "d1" and lin["evidence_id"] == "EV-1"
    assert loaded["case_id"] == "WFX-T" and loaded["idea_id"] == "IDEA-1"
    assert loaded["factual_gate"] == "FACTUAL_GATE_PASS"
    assert loaded["style_example_ids"] == []
    # idea -> evidence -> voice/mode -> draft -> audit -> final -> diff chain present
    for key in (
        "case_id",
        "idea_id",
        "evidence_id",
        "draft_id",
        "voice_selected",
        "mode_selected",
        "draft_text",
        "final_text",
        "diff",
        "revision_classification",
        "audit",
    ):
        assert key in loaded


# ---------- 12. no auto-publish action exists ----------


def test_no_auto_publish_in_workflow_module():
    import editor_assistant.workflow as wf
    from editor_assistant.workflow import cases, cli

    names = set(dir(wf)) | set(dir(cli)) | set(dir(cases))
    for token in ("publish", "wordpress", "schedule_post", "auto_approve"):
        assert not any(token in n.lower() for n in names)
    assert not hasattr(cases, "publish")


# ---------- 13. no frozen Radar mutation ----------


def test_no_radar_state_mutation():
    import inspect

    from editor_assistant.workflow import cli

    src = inspect.getsource(cli)
    for token in ("state.save", "outbox.append", "Item(", "radar_state"):
        assert token not in src


# ---------- aggregation + metrics smoke ----------


def test_aggregate_patterns_threshold_and_metrics():
    cases = []
    for i in range(6):
        c = _case(
            "H",
            "Първи абзац на черновата, леко преразказан.\n\nВтори абзац на черновата.",
            draft_headline="H",
            outcome="ACCEPTED_FOR_EDIT",
            weight="LIGHT",
        )
        c["case_id"] = f"WFX-{i:02d}"
        cases.append(c)
    agg = cases_mod.aggregate_patterns(cases, min_count=5)
    assert agg["threshold"] == 5
    assert agg["recurring_above_threshold"], agg["patterns"]
    m = cases_mod.workflow_metrics(cases)
    assert m["completed"] == 6 and m["light_or_moderate"] == 6
    assert m["headline_modified"] == 0 and m["start_from_draft_yes"] == 6
