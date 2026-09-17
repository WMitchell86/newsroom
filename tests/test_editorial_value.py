"""Offline proofs of editorial rejection and controlled entertainment color."""

import json

import pytest

from editor_assistant.drafting import generate, prompt
from editor_assistant.workflow import angles, cli, live
from editor_assistant.workflow.ideas import read_ideas, save_ideas


def test_missing_transcript_assessment_stops_before_model(monkeypatch):
    monkeypatch.setattr(live.gen, "call_model", lambda *a, **kw: pytest.fail("model called"))
    monkeypatch.setattr(live, "_load_profile", lambda *a: pytest.fail("profile loaded"))
    with pytest.raises(angles.AngleError, match="ANGLE_REVIEW_REQUIRED"):
        live.live_generate_draft(
            {"source_type": "council_transcript"}, voice="VOICE_HOUSE", mode="MODE_STANDARD_NEWS"
        )


def test_entertainment_hook_guidance_preserves_factual_boundary(monkeypatch):
    monkeypatch.setattr(prompt, "_profile_text", lambda p: p["profile_id"])
    packet = {
        "source_url": "https://organizer.example/show",
        "source_headline": "Комедия",
        "facts": [{"id": "F1", "text": "Комедия за вечеря с неканени гости."}],
    }
    text = prompt.build_prompt(
        packet,
        site_dna={},
        voice_profile={"profile_id": "VOICE_HOUSE"},
        mode_profile={"profile_id": "MODE_EVENT_PREVIEW"},
        style_examples=[],
    )["text"]
    assert "one light editorial hook" in text
    assert "HOOK -> what/when/where" in text
    assert "Do not invent plot points" in text
    assert "CURRENT EVIDENCE" in text


def candidate_list(packet, strong=False):
    result = []
    for n, fact in enumerate(packet["facts"]):
        scores = {key: {"score": 0} for key in angles.CRITERIA}
        if strong and n == 0:
            for key, value in (("concrete_change", 2), ("people_impact", 2), ("burgas_novelty", 1)):
                scores[key] = {
                    "score": value,
                    "reason": "Нова местна услуга.",
                    "fact_ids": [fact["id"]],
                }
        result.append(
            {
                "angle_id": f"A{n}",
                "title": fact["text"],
                "reason": "Оценка на местното значение; процедурните точки нямат новост.",
                "new_proposition": f"Ново: {fact['text']}",
                "fact_ids": [fact["id"]],
                "scores": scores,
            }
        )
    return result


@pytest.fixture
def packet():
    return {
        "source_type": "council_transcript",
        "facts": [
            {"id": "F1", "text": "В Бургас отварят безплатен кабинет за деца."},
            {"id": "F2", "text": "Комисията прие дневния ред."},
            {"id": "F3", "text": "Заседанието приключи."},
        ],
    }


def test_editor_selection_overrides_ranking_but_not_threshold(packet):
    candidates = candidate_list(packet, strong=True)
    for key, value in (("concrete_change", 2), ("people_impact", 2), ("burgas_novelty", 1)):
        candidates[1]["scores"][key] = {
            "score": value,
            "reason": "Друга местна промяна.",
            "fact_ids": [candidates[1]["fact_ids"][0]],
        }
    result = angles.assess_angles(packet, candidates, editor_selection="A1")
    assert result["selected_angle_id"] == "A1" and result["selection_source"] == "editor"
    assert result["candidates"][0]["angle_id"] == "A0"  # ranking preserved, editor overrode
    assert result["candidates"][1]["eligible"] is True and result["candidates"][1]["total"] == 5
    with pytest.raises(angles.AngleError, match="not a supplied angle"):
        angles.assess_angles(packet, candidates, editor_selection="A9")
    weak = candidate_list(packet)
    with pytest.raises(angles.AngleError, match="does not clear the threshold"):
        angles.assess_angles(packet, weak, editor_selection="A0")


def test_scoped_packet_gate_reverifies_binding_but_skips_rescoring(packet):
    candidates = candidate_list(packet, strong=True)
    # A1 must be genuinely eligible to be selectable (M2R §29/§32: an editor
    # may overrule the RANKING, never the gate). Score its own fact (F2 -
    # 'комисията прие дневния ред', a concrete decision) - distinct from A0's.
    for key, value in (("concrete_change", 2), ("people_impact", 1), ("burgas_novelty", 2)):
        candidates[1]["scores"][key] = {
            "score": value,
            "reason": "Реално решение на комисия.",
            "fact_ids": [candidates[1]["fact_ids"][0]],
        }
    assessment = angles.assess_angles(packet, candidates, editor_selection="A1")
    scoped = angles.selected_angle_packet(packet, assessment)
    assert scoped["editorial_assessment"]["resolved_scoped"] is True
    assert len(scoped["facts"]) == 1
    assert angles.check_angle_gate(scoped) == scoped["editorial_assessment"]
    broken = angles.selected_angle_packet(packet, assessment)
    broken["facts"] = [f for f in broken["facts"] if f["id"] not in candidates[1]["fact_ids"]]
    with pytest.raises(angles.AngleError, match="scoped packet lost facts"):
        angles.check_angle_gate(broken)


def test_weak_angles_block_direct_generation(packet, monkeypatch):
    packet["editorial_assessment"] = angles.assess_angles(packet, candidate_list(packet))
    monkeypatch.setattr(live.gen, "call_model", lambda *a, **kw: pytest.fail("model called"))
    result = live.live_generate_draft(packet, voice="VOICE_HOUSE", mode="MODE_STANDARD_NEWS")
    assert result["status"] == angles.NO_ANGLE
    assert result["reason"] and "draft" not in result


def test_threshold_selection_and_cached_status_not_trusted(packet):
    candidates = candidate_list(packet, strong=True)
    result = angles.assess_angles(packet, candidates)
    assert result["status"] == angles.READY
    assert result["selected_angle_id"] == "A0"
    assert result["candidates"][0]["total"] == 5
    candidates[0]["scores"]["people_impact"]["score"] = 1
    packet["editorial_assessment"] = {"status": angles.READY, "candidates": candidates}
    assert angles.check_angle_gate(packet)["status"] == angles.NO_ANGLE


@pytest.mark.parametrize("invalid", ["count", "duplicate", "unknown_fact", "boolean", "background"])
def test_invalid_assessment_rejected(packet, invalid):
    candidates = candidate_list(packet, strong=True)
    if invalid == "count":
        candidates.pop()
    elif invalid == "duplicate":
        candidates[1]["angle_id"] = "A0"
    elif invalid == "unknown_fact":
        candidates[0]["fact_ids"] = ["missing"]
    elif invalid == "boolean":
        candidates[0]["scores"]["concrete_change"]["score"] = True
    else:
        packet["facts"][0]["scope"] = "historical_background"
    with pytest.raises(angles.AngleError):
        angles.assess_angles(packet, candidates)


def test_cli_rejection_persists_and_creates_no_article(packet, tmp_path, monkeypatch, capsys):
    for name in ("IDEAS_PATH", "LIVE_EVIDENCE_PATH", "LIVE_DRAFTS_PATH", "CASES_PATH"):
        monkeypatch.setattr(cli, name, tmp_path / f"{name}.jsonl")
    idea = live.new_idea(
        source_type="council_transcript",
        source_url="transcript://test",
        title="Комисия",
        what_changed="Процедурни точки",
    )
    save_ideas([idea], cli.IDEAS_PATH)
    packet["evidence_id"] = "EV-TEST"
    cli._save_live_row({"evidence_id": "EV-TEST", "idea_id": idea["idea_id"], "packet": packet})
    path = tmp_path / "angles.json"
    path.write_text(json.dumps(candidate_list(packet)), encoding="utf-8")
    monkeypatch.setattr(
        live, "live_generate_draft", lambda *a, **kw: pytest.fail("generation called")
    )
    cli.main(["live-angles", "EV-TEST", str(path)])
    cli.main(["live-case", "EV-TEST", "--idea", idea["idea_id"]])
    cli.main(["live-generate", "EV-TEST"])
    assert angles.NO_ANGLE in capsys.readouterr().out
    assert read_ideas(cli.IDEAS_PATH)[0]["status"] == angles.NO_ANGLE
    saved = cli._live_rows()["EV-TEST"]
    assert saved["packet"]["editorial_assessment"]["status"] == angles.NO_ANGLE
    assert "prepared" not in saved
    assert not cli.LIVE_DRAFTS_PATH.exists() and not cli.CASES_PATH.exists()
    # A new, explicit assessment may reopen the idea, but must not auto-draft.
    path.write_text(json.dumps(candidate_list(packet, strong=True)), encoding="utf-8")
    cli.main(["live-angles", "EV-TEST", str(path)])
    assert read_ideas(cli.IDEAS_PATH)[0]["status"] == "FOLLOW_UP"
    assert not cli.LIVE_DRAFTS_PATH.exists()


def test_judge_still_checks_hook_factual_premises(packet):
    text = generate._semantic_judge_prompt(packet, "Какво може да се обърка?")
    assert "Check EVERY" in text and "Do not exempt a sentence" in text
    assert "invent plot points, reactions, reviews, audience response" in text
