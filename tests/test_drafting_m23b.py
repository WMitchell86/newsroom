"""M2.3B corrective-pass contract tests - offline, deterministic, stdlib only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from editor_assistant.drafting.evidence import (
    _sentences,
    classify_scope,
    make_fact,
    read_packets,
    validate_packet,
)
from editor_assistant.drafting.generate import _parse_semantic, _semantic_judge_prompt, draft_id_for
from editor_assistant.drafting.prompt import PROMPT_VERSION, _sanitize_style_rule, build_prompt
from editor_assistant.style.profiles import validate_profile
from editor_assistant.style.store import read_jsonl

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "var" / "style_corpus" / "articles.jsonl"
ANALYSIS = ROOT / "var" / "style_analysis"
PROFILES = ANALYSIS / "style_profiles.json"
SITE_DNA = ANALYSIS / "site_dna.json"
EXP = ROOT / "var" / "draft_experiment"
DRAFTS = EXP / "drafts.jsonl"
BLIND_MAP = EXP / "blind_map.json"


def _profiles():
    profs = {p["profile_id"]: p for p in json.loads(PROFILES.read_text(encoding="utf-8"))}
    return profs, json.loads(SITE_DNA.read_text(encoding="utf-8"))


# 1. abbreviation-aware splitting preserves relational context
def test_sentence_split_never_at_abbreviations():
    src = (
        "Още същата вечер гостува «Декамерон» на студенти в класа на проф. Атанас Атанасов, "
        "а вечерта е „Метаморфози“ под ръководството на доц. Пенко Господинов. Утре е финалът."
    )
    sents = _sentences(src)
    assert len(sents) == 2
    assert "класа на проф. Атанас Атанасов" in sents[0]
    assert "доц. Пенко Господинов" in sents[0]
    s2 = _sentences("Над 149 млн. евро са одобрените трансфери. Утре изтича срокът.")
    assert len(s2) == 2 and "149 млн. евро" in s2[0]


# 2. scope classification
def test_fact_scope_classification():
    assert classify_scope("През 2025 г. в турнира участваха шест клуба.") == "historical_background"
    assert classify_scope("В него ще участват 60 деца.") == "current_event"
    assert classify_scope("Финалът ще бъде около 15:00 часа.") == "current_event"
    f = make_fact("EV-T-f1", "В него ще участват 60 деца.", scope="current_event")
    pkt = {
        "evidence_id": "EV-T",
        "source_url": "u",
        "source_type": "t",
        "observed_at": "2026-09-14",
        "source_headline": "h",
        "facts": [f],
        "people": [],
        "organizations": [],
        "places": [],
        "dates": [],
        "numbers": [],
        "quotes": [],
        "unknowns": [],
        "source_text": "В него ще участват 60 деца.",
    }
    assert validate_packet(pkt) is True
    with pytest.raises(ValueError):
        make_fact("EV-T-f1", "x", scope="history")


# 3. style-rule abstraction neutralizes concrete institutions
def test_style_rule_abstraction_removes_concrete_institutions():
    assert "ОДМВР" not in _sanitize_style_rule("съобщиха от пресцентъра на ОД на МВР в Бургас")
    assert "пресцентъра" not in _sanitize_style_rule(
        "факт + „съобщиха от пресцентъра на ОДМВР Бургас“"
    )
    assert "НИМХ" not in _sanitize_style_rule("съобщават от НИМХ")


def test_rendered_prompt_has_no_concrete_institution_attribution():
    profs, dna = _profiles()
    pkt = read_packets(EXP / "evidence_packets.jsonl")[0]
    example = read_jsonl(CORPUS)[0]
    pt = build_prompt(
        pkt,
        site_dna=dna,
        voice_profile=profs["VOICE_HOUSE"],
        mode_profile=profs["MODE_STANDARD_NEWS"],
        style_examples=[
            {
                "body": example.body,
                "headline": example.headline,
                "author": example.author,
                "category": example.category,
                "published_date": example.published_date,
                "url": example.url,
            }
        ],
    )
    assert PROMPT_VERSION == "m2.3b-prompt-2" and pt["prompt_version"] == PROMPT_VERSION
    text = pt["text"]
    assert "ОДМВР" not in text and "пресцентъра на ОД" not in text
    assert "historical_background" in text and "NEVER transfer" in text and "STYLE ONLY" in text


# 4. semantic judge contract
def test_semantic_judge_prompt_and_parse():
    pkt = read_packets(EXP / "evidence_packets.jsonl")[0]
    pr = _semantic_judge_prompt(pkt, "Тестово изречение.")
    assert "EVIDENCE FACTS" in pr and "DRAFT TEXT" in pr and "historical_background" in pr
    raw = (
        '{"sentence": "Столичните общини получиха шест клуба през 2025 г.", '
        '"verdict": "UNSUPPORTED", "issue": "temporal_rebinding", "supporting_fact_ids": [], '
        '"note": "rebound historical count"}\n'
        '{"sentence": "Финалът е в 15:00 часа.", "verdict": "SUPPORTED", "issue": "none", '
        '"supporting_fact_ids": ["EV-10-f09"], "note": "ok"}'
    )
    claims, _errs = _parse_semantic(raw)
    assert claims[0]["verdict"] == "UNSUPPORTED" and claims[0]["issue"] == "temporal_rebinding"
    assert claims[1]["verdict"] == "SUPPORTED" and claims[1]["issue"] == "none"


# 5. regenerated artifacts
def test_regenerated_artifacts_lineage_and_version():
    drafts = [json.loads(l) for l in DRAFTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(drafts) == 15
    by = {d["retrieval_key"]: d for d in drafts}
    expect = {f"EV-{i:02d}" for i in range(1, 11)} | {
        "EV-01B",
        "EV-05B",
        "EV-04B",
        "EV-02B",
        "EV-10B",
    }
    assert set(by) == expect
    for d in drafts:
        assert d["lineage"]["prompt_version"] == "m2.3b-prompt-1"
        assert d["lineage"]["site_dna_version"] == "CHERNOMORIE_SITE_DNA"
        assert len(d["lineage"]["style_example_ids"]) == 3
        # attempt=0 for first-pass drafts; attempt>=1 only for semantic-judge
        # corrective regeneration (e.g. EV-07), per the M2.3B regeneration policy.
        attempt = (d["lineage"]["generation_settings"] or {}).get("regenerated_attempt", 0)
        assert d["lineage"]["draft_id"] == draft_id_for(
            d["evidence_id"],
            d["lineage"]["voice_id"],
            d["lineage"]["mode_id"],
            d["lineage"]["prompt_version"],
            attempt=attempt,
        )
    packets = read_packets(EXP / "evidence_packets.jsonl")
    assert all("scope" in f for p in packets for f in p["facts"])


def test_blind_map_sealed_and_reproducible():
    from editor_assistant.drafting.evaluation import blind_order

    blind = json.loads(BLIND_MAP.read_text(encoding="utf-8"))
    assert len(blind["pairs"]) >= 3 and len(blind["mode_tests"]) >= 2
    for pair in blind["pairs"]:
        ids = [pair["secret"]["VOICE_HOUSE"], pair["secret"]["VOICE_DESISLAVA_RECENT"]]
        assert sorted(pair["mapping"]["labels"].values()) == sorted(ids)
        assert blind_order(pair["mapping"]["group_id"], ids)["labels"] == pair["mapping"]["labels"]
    for test in blind["mode_tests"]:
        ids = list(test["secret"].values())
        assert blind_order(test["mapping"]["group_id"], ids)["labels"] == test["mapping"]["labels"]


def test_frozen_profiles_still_valid_after_m23b():
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    for p in profiles:
        assert validate_profile(p) is True


def test_no_radar_dependency_m23b():
    mods = (
        "editor_assistant.drafting.evidence",
        "editor_assistant.drafting.prompt",
        "editor_assistant.drafting.generate",
        "editor_assistant.drafting.retrieval",
    )
    for banned in ("sources.rss", "sources.live", "state.store", "notify", "poll"):
        for m in mods:
            path = ROOT / "src" / (m.replace(".", "/") + ".py")
            assert banned not in path.read_text(encoding="utf-8")
    code = "import json;" + ";".join(f"__import__('{m}')" for m in mods) + ";print('ok')"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), check=False
    )
    assert out.returncode == 0, out.stderr


# 6. prompt trimming must never delete the JSON output contract (regression)
def test_prompt_trim_preserves_task_and_json_contract():
    from editor_assistant.drafting.generate import _trim_for_model

    prompt = (
        "H" * 4000
        + "\n\n===== STYLE_EXAMPLES =====\n"
        + ("E" * 3000)
        + "\n\n===== TASK =====\nReturn STRICT JSON\n\n===== FORBIDDEN =====\nnope"
    )
    # a normal-size prompt is passed through untouched
    assert _trim_for_model(prompt) == prompt
    # when a trim is forced, TASK/FORBIDDEN/JSON contract must survive
    trimmed = _trim_for_model(prompt, hard_cap_chars=4000)
    assert len(trimmed) < len(prompt)
    assert "===== TASK =====" in trimmed
    assert "STRICT JSON" in trimmed
    assert "===== FORBIDDEN =====" in trimmed
    # examples were the only thing shortened
    assert "style examples shortened" in trimmed


# 7. blind artifact retired for scoring (M2.3B style-gate closure, 2026-09-16)
def test_blind_map_retired_for_scoring():
    blind = json.loads(BLIND_MAP.read_text(encoding="utf-8"))
    assert blind["retired_for_scoring"] is True
    assert "M2_3B_BLIND_ARTIFACT_RETIREMENT.json" in blind["retirement_note"]
    retirement = ROOT / "m2" / "review" / "M2_3B_BLIND_ARTIFACT_RETIREMENT.json"
    assert retirement.exists()
    record = json.loads(retirement.read_text(encoding="utf-8"))
    assert record["contradicted_pairs_verified"] == ["EV-01", "EV-04", "EV-02"]
    review_text = (EXP / "review.md").read_text(encoding="utf-8")
    assert review_text.lstrip().startswith("> **RETIRED FOR SCORING")
