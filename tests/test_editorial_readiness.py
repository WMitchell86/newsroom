"""M2R Editorial Readiness Layer: general semantic fixtures + loop contracts.

Fixtures A-F are semantic (M2R §27), never entity-specific: routine meeting,
incomplete-but-important, thin event listing, enriched event, supported-playful
entertainment, serious sensitive story. LIVE case IDs are deliberately absent.
"""

import json

import pytest

from editor_assistant.workflow import angles, live, readiness
from editor_assistant.workflow.readiness import (
    DRAFT_READY,
    NO_ANGLE,
    RESEARCH_MORE,
    SUFFICIENT,
    apply_editor_override,
    assess_readiness,
    assess_sufficiency,
    expansion_plan,
    hook_task_extra,
    plan_reader_interest,
    readiness_for_candidate,
    register_research_round,
)


def packet(facts, *, dates=(), places=(), headline="", quotes=(), source_type="organizer"):
    return {
        "source_type": source_type,
        "source_url": "https://upstream.example/lead",
        "source_headline": headline,
        "evidence_id": "EV-FIXTURE",
        "facts": [
            {"id": f"F{i + 1}", "text": t, "scope": "current_event"} for i, t in enumerate(facts)
        ],
        "dates": list(dates),
        "places": list(places),
        "quotes": [{"id": f"Q{i + 1}", "text": t} for i, t in enumerate(quotes)],
        "unknowns": [],
    }


def criterion_scores(mapping=None):
    base = {k: {"score": 0, "reason": "", "fact_ids": []} for k in angles.CRITERIA}
    base.update(mapping or {})
    return base


def candidate(
    cid, title, proposition, fact_ids, scores, *, reason="Редакторска оценка.", **semantic
):
    out = {
        "angle_id": cid,
        "title": title,
        "reason": reason,
        "new_proposition": proposition,
        "fact_ids": fact_ids,
        "scores": scores,
    }
    out.update(semantic)
    return out


# ---------- Fixture A: routine meeting, no concrete result (§27) ----------

FIXTURE_A = packet(
    [
        "Комисията се събра и прие порядъка на деня.",
        "Обсъдени бяха рутинни доклади без конкретни решения.",
    ],
    dates=["2026-09-10"],
    places=["Бургас"],
    source_type="council_transcript",
)


def test_fixture_a_routine_meeting_is_no_publishable_angle():
    cands = [
        candidate(
            "A1",
            "Редовно заседание",
            "Комисията прие порядъка на деня и обсъди рутинни доклади.",
            ["F1", "F2"],
            criterion_scores(),
            veto=True,
            semantic_reason="Приет е само порядъка на деня; няма решение, "
            "сума или получател - рутина без новост.",
        ),
        candidate("A2", "Доклади", "Обсъдени са рутинни доклади.", ["F2"], criterion_scores()),
        candidate("A3", "Заседание", "Комисията се е събрала.", ["F1"], criterion_scores()),
    ]
    result = angles.assess_angles(FIXTURE_A, cands)
    assert result["status"] == angles.NO_ANGLE
    vetoed = next(c for c in result["candidates"] if c["angle_id"] == "A1")
    assert vetoed["veto_applied"] is True and vetoed["eligible"] is False
    stored = dict(FIXTURE_A)
    stored["editorial_assessment"] = result
    rec = assess_readiness(stored, mode="MODE_STANDARD_NEWS")
    assert rec["status"] == NO_ANGLE
    assert rec["editorial_value_status"] == angles.NOT_VIABLE
    assert rec["hook_strategy"] is None  # no hook planned for a non-story


# ---------- Fixture B: important topic, incomplete specifics (§6, §27) ----------

FIXTURE_B = packet(
    ["Обсъжда се финансово подпомагане на граждани.", "Хората може да бъдат засегнати от мерките."],
    dates=["2026-09-11"],
    places=["Бургас"],
)


def test_fixture_b_high_relevance_does_not_force_publication():
    scores = criterion_scores(
        {
            "people_impact": {"score": 2, "reason": "Засяга граждани", "fact_ids": ["F1", "F2"]},
            "burgas_novelty": {"score": 1, "reason": "Местна мярка", "fact_ids": ["F1"]},
        }
    )
    cands = [
        candidate(
            "B1",
            "Финансова помощ",
            "Обсъжда се финансово подпомагане на граждани, без прието решение.",
            ["F1", "F2"],
            scores,
            semantic_status=angles.NEEDS_RESEARCH,
            research_questions=[
                "Каква е сумата?",
                "Кои са получателите?",
                "Прието ли е решението?",
            ],
        ),
        candidate("B2", "Мерки", "Обсъждат се мерки.", ["F1"], criterion_scores()),
        candidate("B3", "Заседание", "Имало е заседание.", ["F1"], criterion_scores()),
    ]
    result = angles.assess_angles(FIXTURE_B, cands)
    assert result["status"] == angles.NEEDS_RESEARCH
    assert result["pending_angle_id"] == "B1"
    assert "сумата" in " ".join(result["research_questions"])
    # the surface alone must not become DRAFT_READY either (§26 regression)
    rec = readiness_for_candidate(
        FIXTURE_B, {"angle_id": "B1", "fact_ids": ["F1", "F2"]}, mode="MODE_STANDARD_NEWS"
    )
    assert rec["article_readiness"]["status"] != DRAFT_READY


def test_fixture_b_high_score_with_explicit_veto_still_rejected():
    """§26/§29 regression: numeric eligibility must not beat the veto."""
    scores = criterion_scores(
        {
            "concrete_change": {"score": 2, "reason": "x", "fact_ids": ["F1"]},
            "people_impact": {"score": 2, "reason": "x", "fact_ids": ["F1"]},
            "burgas_novelty": {"score": 1, "reason": "x", "fact_ids": ["F1"]},
        }
    )
    cands = [
        candidate(
            "B1",
            "Финансова помощ",
            "Обсъжда се подпомагане.",
            ["F1"],
            scores,
            veto=True,
            semantic_reason="Няма прието решение, сума и получатели.",
        ),
        candidate("B2", "Мерки", "Обсъждат се мерки.", ["F1"], criterion_scores()),
        candidate("B3", "Заседание", "Имало е заседание.", ["F1"], criterion_scores()),
    ]
    result = angles.assess_angles(FIXTURE_B, cands)
    assert result["status"] == angles.NO_ANGLE
    assert result["candidates"][0]["numeric_eligible"] is True
    assert result["candidates"][0]["eligible"] is False


# ---------- Fixture C: thin event listing (§27) ----------

FIXTURE_C = packet(
    ["Боксов турнир ще се състои в Бургас.", "Организатор е местен клуб."],
    dates=["2026-10-01"],
    places=["Бургас"],
)


def test_fixture_c_thin_listing_needs_research_not_brief_bypass():
    rec = assess_readiness(FIXTURE_C, mode="MODE_EVENT_PREVIEW")
    assert rec["status"] == RESEARCH_MORE
    assert rec["evidence_sufficiency_status"] == RESEARCH_MORE
    suff = rec["sufficiency"]
    assert suff["bare_announcement"] is True
    assert suff["research_questions"], "gap-driven questions must be present"
    # BRIEF must NOT rescue the thin listing (§9/§27 prohibited bypass):
    # it still recognizes the bare announcement and stays RESEARCH_MORE.
    rec_brief = assess_sufficiency(FIXTURE_C, mode="MODE_BRIEF")
    assert rec_brief["status"] == RESEARCH_MORE
    assert rec_brief["bare_announcement"] is True


# ---------- Fixture D: enriched event (§27) ----------

FIXTURE_D = packet(
    [
        "Боксов турнир ще се състои в залата на ДК.",
        "Програмата започва в 18:30 ч.",
        "Участници са състезатели от шест клуба.",
        "Входът е безплатен.",
    ],
    dates=["2026-10-01"],
    places=["ДК Бургас"],
)


def test_fixture_d_enriched_event_is_draft_ready():
    rec = assess_readiness(FIXTURE_D, mode="MODE_EVENT_PREVIEW")
    assert rec["status"] == DRAFT_READY
    assert rec["evidence_sufficiency_status"] == SUFFICIENT
    assert rec["hook_strategy"] == "PRACTICAL_VALUE"
    assert rec["reader_interest"]["basis_fact_ids"]


# ---------- Fixture E: entertainment with supported playful premise (§18, §27) ----------

FIXTURE_E = packet(
    [
        "Премиерата на комедията ще се състои в театъра.",
        ("Посетителите се превръщат в неканени гости, а лъжите се умножават в забъркана комедия."),
        "Входът е свободен, началото е в 19:00 ч.",
    ],
    dates=["2026-10-05"],
    places=["Театър Бургас"],
)


def test_fixture_e_supported_playful_premise_allows_playful_hook():
    rec = assess_readiness(FIXTURE_E, mode="MODE_EVENT_PREVIEW")
    assert rec["status"] == DRAFT_READY
    assert rec["hook_strategy"] in ("PLAYFUL", "CURIOSITY")
    # every factual premise of the hook stays inside the factual gate (§19)
    assert rec["reader_interest"]["basis_fact_ids"]


def test_fixture_e_playful_requires_supported_premise_not_subject_alone():
    """Same entertainment subject, but calendar-only evidence: no PLAYFUL."""
    thin = packet(
        ["Премиерата на комедията ще се състои в театъра."],
        dates=["2026-10-05"],
        places=["Театър Бургас"],
    )
    hook = plan_reader_interest(thin, mode="MODE_EVENT_PREVIEW")
    assert hook["hook_strategy"] != "PLAYFUL"


# ---------- Fixture F: serious sensitive story (§17, §27) ----------

FIXTURE_F = packet(
    [
        "Тежка катастрофа на пътя към Бургас: загинал човек и трима пострадали.",
        "Пътят е временно затворен; движението се пренасочва.",
        "Пътната полиция разследва произшествието.",
    ],
    dates=["2026-09-12"],
    places=["Бургас"],
    source_type="press_release",
)


def test_fixture_f_serious_story_is_ready_but_never_playful():
    rec = assess_readiness(FIXTURE_F, mode="MODE_STANDARD_NEWS")
    assert rec["status"] == DRAFT_READY
    hook = rec["reader_interest"]
    assert hook["serious_subject"] is True
    assert hook["hook_strategy"] in ("STRONGEST_FACT", "CONSEQUENCE", "LOCAL_IMPACT")


def test_serious_subject_guard_beats_supported_playful_cues():
    """Even with comedy vocabulary present, a serious subject stays serious."""
    mixed = packet(
        [("Загинал човек при катастрофа край театъра; комедината премиера е отложена.")],
        dates=["2026-09-12"],
        places=["Бургас"],
    )
    hook = plan_reader_interest(mixed, mode="MODE_STANDARD_NEWS")
    assert hook["serious_subject"] is True
    assert hook["hook_strategy"] in ("STRONGEST_FACT", "CONSEQUENCE", "LOCAL_IMPACT")


# ---------- §31 inspectable record shape ----------


def test_readiness_record_is_inspectable():
    cands = [
        candidate(
            "D1",
            "Турнир",
            "Турнирът ще се състои с програма и свободен вход.",
            ["F1", "F2", "F3", "F4"],
            criterion_scores(
                {
                    "concrete_change": {"score": 2, "reason": "Събитие", "fact_ids": ["F1"]},
                    "people_impact": {"score": 2, "reason": "Публика", "fact_ids": ["F1"]},
                    "burgas_novelty": {"score": 1, "reason": "Местно", "fact_ids": ["F1"]},
                }
            ),
        ),
        candidate("D2", "Зала", "Използва се залата.", ["F1"], criterion_scores()),
        candidate("D3", "Клубове", "Участват клубове.", ["F3"], criterion_scores()),
    ]
    p = dict(FIXTURE_D)
    p["editorial_assessment"] = angles.assess_angles(p, cands)
    rec = assess_readiness(p, mode="MODE_EVENT_PREVIEW")
    for key in (
        "status",
        "editorial_value_status",
        "evidence_sufficiency_status",
        "hook_strategy",
        "reader_interest",
        "sufficiency",
    ):
        assert key in rec
    assert rec["editorial_value_status"] == angles.VIABLE
    assert rec["sufficiency"]["missing_dimensions"] is not None
    # separate tracking of the three independent statuses (§14)
    assert rec["status"] == DRAFT_READY and rec["evidence_sufficiency_status"] == SUFFICIENT


# ---------- Skill C: targeted research loop (§11-13) ----------


def test_research_loop_plan_rounds_and_limit():
    rec = assess_readiness(FIXTURE_C, mode="MODE_EVENT_PREVIEW")
    assert rec["status"] == RESEARCH_MORE
    plan = expansion_plan(rec, rounds_used=0)
    assert plan["max_rounds_remaining"] == 2
    assert plan["missing_dimensions"]
    assert plan["research_questions"]
    assert expansion_plan(rec, rounds_used=2)["max_rounds_remaining"] == 0
    with pytest.raises(readiness.ReadinessError):
        expansion_plan({"status": DRAFT_READY})


def test_register_research_round_stops_after_two():
    record = {}
    for expected in (1, 2):
        record = register_research_round(
            record,
            missing_dimensions=["event_schedule"],
            research_questions=["В колко часа започва?"],
        )
        assert record["targeted_research_rounds"] == expected
    with pytest.raises(readiness.ReadinessError, match="limit"):
        register_research_round(
            record, missing_dimensions=["admission"], research_questions=["Безплатен ли е входът?"]
        )
    assert record["research_rounds"][0]["missing_dimensions"] == ["event_schedule"]


# ---------- §32 editor override ----------


def test_editor_override_is_recorded_never_silent():
    rec = assess_readiness(FIXTURE_C, mode="MODE_EVENT_PREVIEW")
    assert rec["status"] == RESEARCH_MORE
    forced = apply_editor_override(rec, action="FORCE_DRAFT", reason="Редакторът иска чернова.")
    assert forced["status"] == DRAFT_READY
    assert forced["pre_override_status"] == RESEARCH_MORE
    assert forced["editor_override"] == {
        "action": "FORCE_DRAFT",
        "reason": "Редакторът иска чернова.",
    }
    for action in ("CHANGE_ANGLE", "REQUEST_MORE_RESEARCH", "REJECT_STORY"):
        kept = apply_editor_override(rec, action=action, reason="r")
        assert kept["status"] == RESEARCH_MORE and kept["editor_override"]["action"] == action
    with pytest.raises(readiness.ReadinessError, match="reason"):
        apply_editor_override(rec, action="FORCE_DRAFT", reason=" ")


def test_live_readiness_records_force_draft_override():
    rec = live.live_readiness(FIXTURE_C, mode="MODE_EVENT_PREVIEW", editor_override="FORCE_DRAFT")
    assert rec["status"] == DRAFT_READY and rec["pre_override_status"] == RESEARCH_MORE
    with pytest.raises(live.LiveError, match="override"):
        live.live_readiness(FIXTURE_C, editor_override="NOPE")


# ---------- hook -> prompt fragment (§19-21) ----------


def test_hook_task_extra_is_grounded_and_clickbait_free():
    hook = {
        "hook_strategy": "PRACTICAL_VALUE",
        "basis_fact_ids": ["F3", "F4"],
        "rationale": "r",
        "serious_subject": False,
    }
    frag = hook_task_extra(hook)
    assert "PRACTICAL_VALUE" in frag and "F3" in frag
    assert "заглавия" in frag
    for banned in ("Няма да повярвате", "Ето какво", "Шок", "Скандал"):
        assert banned not in frag
    serious_hook = {
        "hook_strategy": "LOCAL_IMPACT",
        "basis_fact_ids": ["F1"],
        "rationale": "r",
        "serious_subject": True,
    }
    sfrag = hook_task_extra(serious_hook)
    assert "сериозна" in sfrag and "без игривост" in sfrag


# ---------- semantic floor (§4-5): no novelty cue -> not viable ----------


def test_semantic_floor_no_new_event_signal_blocks_viability():
    p = packet(
        ["Тема е била обсъждана.", "Институцията е запозната с въпроса."],
        dates=["2026-09-10"],
        places=["Бургас"],
    )
    scores = criterion_scores(
        {
            "concrete_change": {"score": 2, "reason": "x", "fact_ids": ["F1"]},
            "people_impact": {"score": 2, "reason": "Засяга хора", "fact_ids": ["F1", "F2"]},
            "burgas_novelty": {"score": 1, "reason": "Местно", "fact_ids": ["F1"]},
        }
    )
    cands = [
        candidate("S1", "Тема", "Тема е била обсъждана.", ["F1", "F2"], scores),
        candidate("S2", "Въпрос", "Институцията е запозната.", ["F2"], criterion_scores()),
        candidate("S3", "Обсъждане", "Имало е обсъждане.", ["F1"], criterion_scores()),
    ]
    result = angles.assess_angles(p, cands)
    top = result["candidates"][0]
    assert top["total"] == 5 and top["numeric_eligible"] is True
    assert top["semantic_status"] == angles.NOT_VIABLE and top["eligible"] is False
    assert result["status"] == angles.NO_ANGLE


# ---------- live generation gate (§24: only DRAFT_READY proceeds) ----------


def _stub_generation(monkeypatch, *, capture=None):
    def fake_call_model(prompt_text, *, api_key=None, timeout=240, role="draft", **kw):
        if capture is not None:
            capture.append(prompt_text)
        if role == "judge":
            return "", {"model": "mock"}
        return (
            json.dumps(
                {
                    "headlines": ["Заглавие"],
                    "headline": "Заглавие",
                    "body": "Програмата започва в 18:30 ч.",
                }
            ),
            {"model": "mock", "provider": "gemini"},
        )

    monkeypatch.setattr(live.gen, "call_model", fake_call_model)
    monkeypatch.setattr(
        live.gen,
        "verify_claims_semantic",
        lambda packet, body, api_key=None, timeout=240: {"pass": True, "lines": []},
    )


def test_live_generate_blocks_research_more_without_force():
    p = FIXTURE_C
    p["editorial_assessment"] = None
    result = live.live_generate_draft(p, voice="VOICE_HOUSE", mode="MODE_EVENT_PREVIEW")
    assert result["status"] == RESEARCH_MORE
    assert "readiness" in result


def test_live_generate_proceeds_when_draft_ready_and_hook_enters_prompt(monkeypatch):
    capture = []
    _stub_generation(monkeypatch, capture=capture)
    result = live.live_generate_draft(FIXTURE_D, voice="VOICE_HOUSE", mode="MODE_EVENT_PREVIEW")
    assert "draft" in result
    assert result["readiness"]["status"] == DRAFT_READY
    assert result["factual_gate"] == "FACTUAL_GATE_PASS"
    assert "РЕДАКТОРСКИ ПЛАН ЗА ИНТЕРЕС" in capture[0]
    assert "PRACTICAL_VALUE" in capture[0]


def test_live_generate_force_draft_records_override(monkeypatch):
    called = {}
    _stub_generation(monkeypatch)

    def fake_override(readiness_record, *, action, reason):
        called["action"] = action
        out = dict(readiness_record)
        out["editor_override"] = {"action": action, "reason": reason}
        return out

    monkeypatch.setattr(live.readiness_mod, "apply_editor_override", fake_override)
    result = live.live_generate_draft(
        FIXTURE_C,
        voice="VOICE_HOUSE",
        mode="MODE_EVENT_PREVIEW",
        force_draft=True,
        editor_override_reason="редакторско решение",
    )
    assert "draft" in result
    assert called["action"] == "FORCE_DRAFT"
    assert result["readiness"]["editor_override"]["reason"] == "редакторско решение"
