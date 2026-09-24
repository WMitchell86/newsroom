"""M2.3 grounded drafting contract tests - offline, deterministic, stdlib only.

Covers the nine high-value M2.3 contracts (evidence serialization, fact/style
separation, retrieval fallback, DESISLAVA recent lock, style-not-facts labels,
lineage completeness, blind determinism, reproducibility, no Radar dependency).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from editor_assistant.drafting.evaluation import blind_order
from editor_assistant.drafting.evidence import (
    EvidenceError,
    make_fact,
    make_quote,
    read_packets,
    validate_packet,
    write_packets,
)
from editor_assistant.drafting.generate import draft_id_for, make_lineage
from editor_assistant.drafting.prompt import PROMPT_VERSION, SECTIONS, build_prompt
from editor_assistant.drafting.retrieval import (
    StyleRetrievalError,
    retrieve_examples,
    retrieve_examples_for_generation,
)
from editor_assistant.style.profiles import (
    ProfileError,
    compose_draft_spec,
    composition_fallback,
)
from editor_assistant.style.store import read_jsonl

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "var" / "style_corpus" / "articles.jsonl"
ANALYSIS = ROOT / "var" / "style_analysis"
PROFILES = ANALYSIS / "style_profiles.json"
SITE_DNA = ANALYSIS / "site_dna.json"
RETRIEVALS = ROOT / "var" / "draft_experiment" / "retrievals.json"
DRAFTS = ROOT / "var" / "draft_experiment" / "drafts.jsonl"
BLIND_MAP = ROOT / "var" / "draft_experiment" / "blind_map.json"
# frozen Radar runtime modules that drafting must never touch
RADAR_MODULES = ("sources", "state", "rss", "outbox", "renderer", "telegram", "poll")


def _packet():
    return {
        "evidence_id": "EV-TEST",
        "source_url": "https://chernomorie-bg.com/post/test",
        "source_type": "chernomorie_live_article",
        "observed_at": "2026-09-14T10:00:00+00:00",
        "source_headline": "Тестова новина",
        "facts": [make_fact("EV-TEST-f01", "Община Царево купи две метачни машини.")],
        "people": ["Марин Киров"],
        "organizations": ["Община Царево"],
        "places": ["Царево"],
        "dates": ["2026 г"],
        "numbers": ["две машини"],
        "quotes": [make_quote("Машините ще помогнат.", speaker="Марин Киров", role="кмет")],
        "unknowns": ["Няма информация за цена."],
        "source_text": "Община Царево купи две метачни машини. Кметът Марин Киров заяви: Машините ще помогнат.",
    }


def _profiles():
    profs = {p["profile_id"]: p for p in json.loads(PROFILES.read_text(encoding="utf-8"))}
    return profs, json.loads(SITE_DNA.read_text(encoding="utf-8"))


def _rec_dicts(n=3):
    return [
        {
            "body": r.body,
            "headline": r.headline,
            "author": r.author,
            "category": r.category,
            "published_date": r.published_date,
            "url": r.url,
        }
        for r in read_jsonl(CORPUS)[:n]
    ]


# ---------- 1. EvidencePacket serialization ----------
def test_packet_serialization_roundtrip_and_validation(tmp_path):
    packet = _packet()
    assert validate_packet(packet) is True
    path = write_packets([packet], tmp_path / "packets.jsonl")
    loaded = read_packets(path)
    assert len(loaded) == 1
    assert loaded[0] == packet
    with pytest.raises(EvidenceError):
        bad = dict(packet)
        del bad["facts"]
        validate_packet(bad)
    with pytest.raises(EvidenceError):
        dup = dict(packet, facts=[make_fact("f1", "а"), make_fact("f1", "б")])
        validate_packet(dup)
    with pytest.raises(EvidenceError):
        validate_packet(dict(packet, facts=[]))


# ---------- 2. facts/style contexts kept separate ----------
def test_prompt_keeps_evidence_and_style_sections_separate():
    profs, dna = _profiles()
    records = _rec_dicts()
    prompt = build_prompt(
        _packet(),
        site_dna=dna,
        voice_profile=profs["VOICE_HOUSE"],
        mode_profile=profs["MODE_STANDARD_NEWS"],
        style_examples=records,
    )
    assert prompt["prompt_version"] == PROMPT_VERSION
    assert prompt["sections"] == list(SECTIONS)
    text = prompt["text"]
    parts = {}
    for name in SECTIONS:
        header = f"===== {name} ====="
        start = text.index(header)
        body_from = start + len(header)
        nxt = text.find("=====", body_from)
        parts[name] = text[body_from : nxt if nxt > 0 else len(text)]
    example_url = records[0]["url"]
    assert example_url in parts["STYLE_EXAMPLES"]
    assert example_url not in parts["CURRENT_EVIDENCE"]
    assert "Тестова новина" in parts["CURRENT_EVIDENCE"]


# ---------- 3. retrieval respects VOICE/MODE fallback ----------
def test_composition_fallback_chain_matches_frozen_rules():
    spec = compose_draft_spec("VOICE_HOUSE", "MODE_BRIEF")
    assert spec == {
        "site_dna": "CHERNOMORIE_SITE_DNA",
        "voice": "VOICE_HOUSE",
        "mode": "MODE_BRIEF",
    }
    chain = composition_fallback("VOICE_DESISLAVA_RECENT", "MODE_CULTURE_FEATURE")
    assert chain == [
        {
            "site_dna": "CHERNOMORIE_SITE_DNA",
            "voice": "VOICE_DESISLAVA_RECENT",
            "mode": "MODE_CULTURE_FEATURE",
        },
        {
            "site_dna": "CHERNOMORIE_SITE_DNA",
            "voice": "VOICE_HOUSE",
            "mode": "MODE_CULTURE_FEATURE",
        },
        {"site_dna": "CHERNOMORIE_SITE_DNA", "voice": "VOICE_HOUSE", "mode": "MODE_STANDARD_NEWS"},
    ]
    retrs = {r["retrieval_id"]: r for r in json.loads(RETRIEVALS.read_text(encoding="utf-8"))}
    d = retrs["EV-04B"]
    assert d["evidence_id"] == "EV-04" and d["voice"] == "VOICE_DESISLAVA_RECENT"
    assert d["mode"] == "MODE_CULTURE_FEATURE"
    assert all(e["author"] == "Десислава Георгиева" for e in d["examples"])
    assert d["fallback_trail"][0]["mode"] == "MODE_CULTURE_FEATURE"


# ---------- 4. DESISLAVA recent-scope lock ----------
def test_desislava_retrieval_never_returns_legacy_examples():
    packet = dict(_packet(), category_hint="Общество")
    out = retrieve_examples(
        packet,
        voice="VOICE_DESISLAVA_RECENT",
        mode="MODE_STANDARD_NEWS",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    assert len(out) == 3
    for ex in out:
        assert ex["author"] == "Десислава Георгиева"
        assert ex["published_date"] >= "2024-01-01"
    with pytest.raises(ProfileError):
        retrieve_examples(
            packet,
            voice="VOICE_UNKNOWN",
            mode="MODE_STANDARD_NEWS",
            corpus_path=CORPUS,
            analysis_dir=ANALYSIS,
        )


# ---------- 5. style examples can never be labeled factual evidence ----------
def test_style_examples_marked_style_only():
    out = retrieve_examples(
        _packet(),
        voice="VOICE_HOUSE",
        mode="MODE_STANDARD_NEWS",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    assert len(out) == 3
    for ex in out:
        assert ex["why_selected"].startswith("style reference only")
    profs, dna = _profiles()
    prompt = build_prompt(
        _packet(),
        site_dna=dna,
        voice_profile=profs["VOICE_HOUSE"],
        mode_profile=profs["MODE_STANDARD_NEWS"],
        style_examples=out,
    )
    assert "STYLE ONLY" in prompt["text"]
    assert "NOT facts" in prompt["text"]


# ---------- 6. draft lineage complete ----------
def test_lineage_complete_and_validated():
    lin = make_lineage(
        draft_id="dtest",
        evidence_id="EV-TEST",
        voice_id="VOICE_HOUSE",
        mode_id="MODE_STANDARD_NEWS",
        style_example_ids=["a1", "a2", "a3"],
        prompt_version=PROMPT_VERSION,
        model="openai/gpt-oss-20b",
        settings={"temperature": 0.4},
    )
    for key in (
        "draft_id",
        "evidence_id",
        "site_dna_version",
        "voice_id",
        "mode_id",
        "style_example_ids",
        "prompt_version",
        "model",
        "generation_settings",
        "generated_at",
    ):
        assert lin.get(key)
    with pytest.raises(ValueError):
        make_lineage(
            draft_id="dtest",
            evidence_id="EV-TEST",
            voice_id="VOICE_HOUSE",
            mode_id="MODE_STANDARD_NEWS",
            style_example_ids=["a1", "a2"],
            prompt_version=PROMPT_VERSION,
        )
    drafts = [
        json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(drafts) == 15
    for d in drafts:
        lin = d["lineage"]
        assert len(lin["style_example_ids"]) == 3
        assert lin["prompt_version"] == "m2.3b-prompt-1"  # frozen artifact, not current prompt
        assert lin["model"].startswith("gemini-")  # M2.3B: regenerated on Gemini
        assert lin["generation_settings"]["temperature"] == 0.4
        assert lin["generated_at"]


# ---------- 7. blind order deterministic ----------
def test_blind_order_deterministic_and_secret_mapping_stored():
    assert blind_order("EV-01-pair", ["d1", "d2"]) == blind_order("EV-01-pair", ["d1", "d2"])
    first = blind_order("EV-01-pair", ["d1", "d2"])
    assert set(first["labels"].values()) == {"d1", "d2"}
    assert first["labels"]["A"] != first["labels"]["B"]
    assert len(first["fingerprint"]) == 12
    blind = json.loads(BLIND_MAP.read_text(encoding="utf-8"))
    assert len(blind["pairs"]) >= 3 and len(blind["mode_tests"]) >= 2
    for pair in blind["pairs"]:
        ids = [pair["secret"]["VOICE_HOUSE"], pair["secret"]["VOICE_DESISLAVA_RECENT"]]
        assert sorted(pair["mapping"]["labels"].values()) == sorted(ids)
        got = blind_order(pair["mapping"]["group_id"], ids)["labels"]
        assert got == pair["mapping"]["labels"]
    for test in blind["mode_tests"]:
        ids = list(test["secret"].values())
        got = blind_order(test["mapping"]["group_id"], ids)["labels"]
        assert got == test["mapping"]["labels"]


# ---------- 8. same configuration reproducible where deterministic ----------
def test_deterministic_ids_prompts_and_retrieval():
    key = ("EV-05", "VOICE_HOUSE", "MODE_STANDARD_NEWS", PROMPT_VERSION)
    assert draft_id_for(*key) == draft_id_for(*key)
    profs, dna = _profiles()
    packet = _packet()
    records = _rec_dicts()
    args = {
        "site_dna": dna,
        "voice_profile": profs["VOICE_HOUSE"],
        "mode_profile": profs["MODE_STANDARD_NEWS"],
        "style_examples": records,
    }
    assert build_prompt(packet, **args) == build_prompt(packet, **args)
    r1 = retrieve_examples(
        packet,
        voice="VOICE_HOUSE",
        mode="MODE_STANDARD_NEWS",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    r2 = retrieve_examples(
        packet,
        voice="VOICE_HOUSE",
        mode="MODE_STANDARD_NEWS",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    assert r1 == r2
    drafts = [
        json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    ev05 = next(d for d in drafts if d["retrieval_key"] == "EV-05")
    retrs = {r["retrieval_id"]: r for r in json.loads(RETRIEVALS.read_text(encoding="utf-8"))}
    assert ev05["lineage"]["style_example_ids"] == [
        e["article_id"] for e in retrs["EV-05"]["examples"]
    ]


# ---------- 9. no Radar runtime dependency ----------
def test_drafting_modules_import_without_radar_modules():
    pkg = ROOT / "src" / "editor_assistant"
    for sub in ("drafting", "style"):
        for py in sorted((pkg / sub).glob("*.py")):
            for line in py.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    mod = stripped.split()[1]
                    assert not any(mod == r or mod.startswith(r + ".") for r in RADAR_MODULES), (
                        py,
                        stripped,
                    )
    import editor_assistant.drafting.evaluation
    import editor_assistant.drafting.evidence
    import editor_assistant.drafting.generate
    import editor_assistant.drafting.prompt
    import editor_assistant.drafting.retrieval  # noqa: F401


# ---------- scorecard validation helper (used by the review workflow) ----------
def test_scorecard_validation_bounds():
    from editor_assistant.drafting.evaluation import blank_scorecard, validate_scorecard

    card = blank_scorecard()
    assert validate_scorecard(card) is True
    with pytest.raises(ValueError):
        validate_scorecard(dict(card, factual_correctness=6))
    with pytest.raises(ValueError):
        validate_scorecard(dict(card, needs_editing=0))
    with pytest.raises(ValueError):
        validate_scorecard(dict(card, would_publish_after_edit="maybe"))


# ---------- G3: style retrieval is a PRE-GENERATION contract ----------


def test_generation_preflight_returns_three_unique_bodies_without_fallback():
    result = retrieve_examples_for_generation(
        _packet(),
        voice="VOICE_HOUSE",
        mode="MODE_STANDARD_NEWS",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    examples = result["examples"]
    assert len(examples) == 3
    assert len({e["article_id"] for e in examples}) == 3
    # G: bodies are hydrated for the prompt (the legacy helper still omits them)
    assert all(e["body"].strip() for e in examples)
    assert result["fallback_used"] is False
    assert len(result["fallback_trail"]) == 1
    assert "VOICE_HOUSE+MODE_STANDARD_NEWS" in result["retrieval_reason"]


def test_legacy_retrieve_examples_keeps_the_bodyless_shape_by_default():
    out = retrieve_examples(
        _packet(),
        voice="VOICE_HOUSE",
        mode="MODE_STANDARD_NEWS",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    assert len(out) == 3 and all("body" not in e for e in out)


def test_generation_preflight_walks_only_the_documented_fallback_chain(monkeypatch):
    """VOICE+MODE -> HOUSE same MODE -> HOUSE STANDARD_NEWS, deduplicated."""
    from editor_assistant.drafting import retrieval as retrieval_mod

    seen = []
    pools = {
        ("VOICE_DESISLAVA_RECENT", "MODE_BRIEF"): ["d1"],
        ("VOICE_HOUSE", "MODE_BRIEF"): ["h1", "h2"],
        ("VOICE_HOUSE", "MODE_STANDARD_NEWS"): ["s1"],
    }

    def scripted(packet, *, voice, mode, **_kwargs):
        seen.append((voice, mode))
        return [
            {
                "article_id": aid,
                "headline": aid,
                "body": f"текст {aid}",
                "url": "",
                "author": "",
                "category": "",
                "published_date": "",
            }
            for aid in pools[(voice, mode)]
        ]

    monkeypatch.setattr(retrieval_mod, "retrieve_examples", scripted)
    result = retrieval_mod.retrieve_examples_for_generation(
        _packet(),
        voice="VOICE_DESISLAVA_RECENT",
        mode="MODE_BRIEF",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    assert seen == [
        ("VOICE_DESISLAVA_RECENT", "MODE_BRIEF"),  # requested
        ("VOICE_HOUSE", "MODE_BRIEF"),  # HOUSE + same MODE
        # HOUSE + STANDARD_NEWS never needed: three unique ids were reached
    ]
    assert [e["article_id"] for e in result["examples"]] == ["d1", "h1", "h2"]
    assert result["fallback_used"] is True
    assert "fallback:" in result["retrieval_reason"]
    assert "VOICE_HOUSE+MODE_BRIEF" in result["retrieval_reason"]


def test_generation_preflight_refuses_when_three_unique_examples_are_impossible(
    monkeypatch,
):
    from editor_assistant.drafting import retrieval as retrieval_mod

    monkeypatch.setattr(retrieval_mod, "retrieve_examples", lambda *_a, **_k: [])
    with pytest.raises(StyleRetrievalError, match="уникални"):
        retrieval_mod.retrieve_examples_for_generation(
            _packet(),
            voice="VOICE_HOUSE",
            mode="MODE_STANDARD_NEWS",
            corpus_path=CORPUS,
            analysis_dir=ANALYSIS,
        )


# ---------- G3 ROUND 2: hermetic thin corpus, dedupe, MID prose ----------
def _house_row(aid, paras=3):
    """A usable VOICE_HOUSE + MODE_STANDARD_NEWS corpus row (house author, date)."""
    return {
        "article_id": aid,
        "url": f"https://chernomorie-bg.com/post/{aid}",
        "headline": f"Пример {aid}",
        "author": "Черноморие-бг",
        "category": "Община",
        "published_date": "2025-06-01",
        "body": "\n\n".join(f"Абзац {i} на {aid}." for i in range(1, paras + 1)),
    }


def _thin_corpus(tmp_path, rows):
    corpus = tmp_path / "articles.jsonl"
    corpus.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    return corpus


def test_thin_corpus_with_only_two_usable_examples_refuses(tmp_path):
    """C1, corpus level: a REAL corpus yielding only two usable examples fails
    the exactly-3 precondition with the truthful count in the refusal."""
    corpus = _thin_corpus(tmp_path, [_house_row("thin-1"), _house_row("thin-2")])
    with pytest.raises(StyleRetrievalError, match="2/3"):
        retrieve_examples_for_generation(
            _packet(),
            voice="VOICE_HOUSE",
            mode="MODE_STANDARD_NEWS",
            corpus_path=corpus,
            analysis_dir=ANALYSIS,
        )


def test_generation_preflight_dedupes_overlapping_fallback_steps(monkeypatch):
    """C2: the same article_id returned by two chain steps counts ONCE, the
    requested-composition example keeps its preferred first position, and the
    exclusion is real (the next step actually receives the exclude list)."""
    from editor_assistant.drafting import retrieval as retrieval_mod

    def _ex(aid):
        return {
            "article_id": aid,
            "headline": aid,
            "body": f"текст {aid}",
            "url": "",
            "author": "",
            "category": "",
            "published_date": "",
        }

    seen = []

    def scripted(packet, *, voice, mode, exclude_ids=(), **_kwargs):
        seen.append((voice, mode, tuple(sorted(exclude_ids))))
        if (voice, mode) == ("VOICE_DESISLAVA_RECENT", "MODE_BRIEF"):
            return [_ex("d1")]
        if (voice, mode) == ("VOICE_HOUSE", "MODE_BRIEF"):
            pool = ["d1", "h1"]  # d1 already picked by the requested step
            return [_ex(a) for a in pool if a not in set(exclude_ids)]
        return [_ex("s1")]

    monkeypatch.setattr(retrieval_mod, "retrieve_examples", scripted)
    result = retrieval_mod.retrieve_examples_for_generation(
        _packet(),
        voice="VOICE_DESISLAVA_RECENT",
        mode="MODE_BRIEF",
        corpus_path=CORPUS,
        analysis_dir=ANALYSIS,
    )
    ids = [e["article_id"] for e in result["examples"]]
    assert ids == ["d1", "h1", "s1"]  # no duplicates, requested pick kept first
    assert len(set(ids)) == 3
    assert ("VOICE_HOUSE", "MODE_BRIEF", ("d1",)) in seen  # exclusion traveled
    assert result["fallback_used"] is True


def test_prompt_mid_paragraphs_carry_real_prose_for_all_three_examples():
    """D2: with a >3-paragraph archive shape, every example contributes a MID
    block with REAL source prose after the elision marker - not just headers.

    (`_example_text` renders MID as the label, a blank line, the [...] marker,
    then the archive paragraph - so this is asserted on content, not on a
    single line parse.)"""
    profs, dna = _profiles()
    examples = [_house_row(f"mid-{i}", paras=5) for i in (1, 2, 3)]
    prompt = build_prompt(
        _packet(),
        site_dna=dna,
        voice_profile=profs["VOICE_HOUSE"],
        mode_profile=profs["MODE_STANDARD_NEWS"],
        style_examples=examples,
    )
    text = prompt["text"]
    assert text.count("MID:") == 3 and text.count("[...]") == 3
    for i in (1, 2, 3):
        # the genuine middle archive paragraph of each example is present
        assert f"Абзац 3 на mid-{i}." in text
    # and each example still carries its real first and last paragraphs
    for i in (1, 2, 3):
        assert f"Абзац 1 на mid-{i}." in text
        assert f"Абзац 5 на mid-{i}." in text
