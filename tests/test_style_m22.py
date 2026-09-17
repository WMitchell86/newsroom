"""M2.2 multi-style discovery tests - offline, deterministic, stdlib only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from editor_assistant.style.corpus import author_class
from editor_assistant.style.features import extract_style_features, opening_class
from editor_assistant.style.profiles import (
    FROZEN_MODES,
    FROZEN_VOICES,
    ProfileError,
    compose_draft_spec,
    composition_fallback,
    validate_profile,
    validate_site_dna,
)
from editor_assistant.style.store import read_jsonl

CORPUS = Path(__file__).resolve().parents[1] / "var" / "style_corpus" / "articles.jsonl"
ANALYSIS = Path(__file__).resolve().parents[1] / "var" / "style_analysis"
FROZEN = ANALYSIS / "style_profiles.json"


def _recs():
    return read_jsonl(CORPUS)


def test_feature_extraction_deterministic():
    recs = _recs()
    first = [extract_style_features(r) for r in recs]
    second = [extract_style_features(r) for r in recs]
    assert first == second
    row = first[0]
    for key in (
        "article_id",
        "url",
        "author",
        "category",
        "published_date",
        "opening_class",
        "hl_chars",
        "hl_words",
        "body_chars",
        "body_paragraphs",
        "body_avg_sentence_words",
        "body_quote_mark_density",
        "body_number_density",
        "body_local_name_hits",
        "lex_word_count",
    ):
        assert key in row, key


def test_grouping_by_author():
    rows = [extract_style_features(r) for r in _recs()]
    house = [r for r in rows if (r["author"] or "") == "Черноморие-бг"]
    desi = [r for r in rows if (r["author"] or "") == "Десислава Георгиева"]
    assert len(house) == 83 and len(desi) == 59
    assert author_class("Черноморие-бг") == "house"
    assert author_class("Десислава Георгиева") == "named"
    assert author_class(None) == "unknown"


def test_grouping_by_category():
    rows = [extract_style_features(r) for r in _recs()]
    cats = {}
    for r in rows:
        cats.setdefault(r["category"], []).append(r)
    assert len(cats["Култура"]) == 39
    assert len(cats["Общество"]) == 35
    assert len(cats["Спорт"]) == 17


def test_house_material_separate_from_named():
    rows = [extract_style_features(r) for r in _recs()]
    house_ids = {r["article_id"] for r in rows if (r["author"] or "") == "Черноморие-бг"}
    desi_ids = {r["article_id"] for r in rows if (r["author"] or "") == "Десислава Георгиева"}
    assert not house_ids & desi_ids
    profiles = json.loads((FROZEN).read_text(encoding="utf-8"))
    hn = next(p for p in profiles if p["profile_id"] == "VOICE_HOUSE")
    assert hn["source_authors"] == ["Черноморие-бг"]
    assert "Десислава Георгиева" not in hn["source_authors"]


def test_low_sample_authors_not_proven():
    profiles = json.loads((FROZEN).read_text(encoding="utf-8"))
    for p in profiles:
        if p["sample_size"] < 20:
            assert p["status"] == "PROVISIONAL", p["profile_id"]
    with pytest.raises(ProfileError):
        validate_profile(
            {
                "profile_id": "X",
                "status": "PROVEN",
                "sample_size": 5,
                "example_article_ids": ["a", "b", "c"],
                "headline": {},
                "opening": {},
                "body": {},
                "quotes": {},
                "tone": {},
                "numbers_dates": {},
                "lexical_notes": {},
                "avoidances": ["x"],
                "display_name": "x",
                "scope": "x",
                "source_authors": [],
                "source_categories": [],
                "preferred_use": "x",
                "site_dna_inherited": "x",
                "evidence_notes": [],
            }
        )


def test_profile_serialization_roundtrip():
    profiles = json.loads((FROZEN).read_text(encoding="utf-8"))
    dna = json.loads((ANALYSIS / "site_dna.json").read_text(encoding="utf-8"))
    for p in profiles:
        assert validate_profile(p) is True
        assert json.loads(json.dumps(p, ensure_ascii=False)) == p
    assert validate_site_dna(dna) is True
    assert dna["profile_id"] == "CHERNOMORIE_SITE_DNA"


def test_same_snapshot_same_metrics():
    snap = json.loads(
        (
            Path(__file__).resolve().parents[1] / "var" / "style_corpus" / "corpus_snapshot.json"
        ).read_text(encoding="utf-8")
    )
    dna = json.loads((ANALYSIS / "site_dna.json").read_text(encoding="utf-8"))
    assert dna["corpus_snapshot"]["sha256_canonical"] == snap["sha256_canonical"]
    assert dna["corpus_snapshot"]["article_count"] == 150
    matrix = (ANALYSIS / "feature_matrix.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(matrix) == 150
    assert len({json.loads(l)["article_id"] for l in matrix}) == 150


def test_no_radar_dependency():
    import subprocess
    import sys

    mods = ["editor_assistant.style.features", "editor_assistant.style.profiles"]
    code = "import json;" + ";".join(f"__import__('{m}')" for m in mods) + ";print('ok')"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert out.returncode == 0, out.stderr
    for banned in ("sources.rss", "sources.live", "state.store", "notify", "poll"):
        for m in mods:
            path = Path(__file__).resolve().parents[1] / "src" / (m.replace(".", "/") + ".py")
            assert banned not in path.read_text(encoding="utf-8")


def test_opening_classes_bounded():
    allowed = {
        "headline_repeated",
        "event_date_first",
        "place_first",
        "person_institution_first",
        "quote_first",
        "immediate_fact",
    }
    for r in _recs():
        assert opening_class(r.headline, r.body) in allowed


def test_frozen_voice_mode_architecture():
    profiles = json.loads(FROZEN.read_text(encoding="utf-8"))
    by_id = {p["profile_id"]: p for p in profiles}
    assert set(by_id) == set(FROZEN_VOICES) | set(FROZEN_MODES)
    assert by_id["VOICE_HOUSE"]["kind"] == "voice" and by_id["VOICE_HOUSE"]["status"] == "PROVEN"
    assert (
        by_id["VOICE_DESISLAVA_RECENT"]["kind"] == "voice"
        and by_id["VOICE_DESISLAVA_RECENT"]["status"] == "PROVISIONAL"
    )
    for m in FROZEN_MODES:
        assert by_id[m]["kind"] == "story_mode"
    spec = compose_draft_spec("VOICE_DESISLAVA_RECENT", "MODE_CULTURE_FEATURE")
    assert spec == {
        "site_dna": "CHERNOMORIE_SITE_DNA",
        "voice": "VOICE_DESISLAVA_RECENT",
        "mode": "MODE_CULTURE_FEATURE",
    }
    chain = composition_fallback("VOICE_DESISLAVA_RECENT", "MODE_EVENT_PREVIEW")
    assert chain[0]["voice"] == "VOICE_DESISLAVA_RECENT" and chain[-1] == {
        "site_dna": "CHERNOMORIE_SITE_DNA",
        "voice": "VOICE_HOUSE",
        "mode": "MODE_STANDARD_NEWS",
    }
    try:
        compose_draft_spec("AUTHOR_X", "MODE_BRIEF")
    except ProfileError:
        pass
    else:
        raise AssertionError("unknown voice must fail")


def test_soft_style_language_no_hard_rules():
    profiles = json.loads(FROZEN.read_text(encoding="utf-8"))
    for p in profiles:
        blob = json.dumps(
            {
                k: p[k]
                for k in (
                    "headline",
                    "opening",
                    "body",
                    "quotes",
                    "tone",
                    "numbers_dates",
                    "lexical_notes",
                    "avoidances",
                )
            },
            ensure_ascii=False,
        )
        for hard in (
            "ONLY here",
            "requires multi-speaker",
            "P1 must use",
            "Highest number density",
            "Longest headlines",
            "Strongly factual",
        ):
            assert hard not in blob, (p["profile_id"], hard)
