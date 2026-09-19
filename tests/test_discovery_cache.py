"""M3D Part P: successful-stage cache (L4) tests — offline, no network."""

import json

import pytest

from editor_assistant.workflow import discovery_cache as C
from editor_assistant.workflow import intake as intake_mod
from editor_assistant.workflow import transcripts as T

SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\nТочка първа от дневния ред.\n\n"
    "2\n00:00:03,500 --> 00:00:06,000\nДокладна записка за финансиране на училище.\n\n"
    "3\n00:00:06,500 --> 00:00:09,000\nОбщинският съвет прие бюджетът.\n"
)

FACTS = [
    {
        "text": "Общинският съвет прие бюджетът.",
        "segment_ids": ["M3DTEST-s0003"],
        "supporting_segment_ids": ["M3DTEST-s0003"],
        "risk_flags": ["final_decision"],
        "uncertain": False,
        "span": None,
        "span_ms": [6500, 9000],
        "fact_id": "M3DTEST-f001",
        "topic_id": "M3DTEST-t01",
        "corroboration_required": True,
        "fact_grounding_status": "GROUNDED",
        "entailment_coverage": 0.9,
        "procedural_status": "COUNCIL_ADOPTED",
    }
]
PROPOSALS = [
    {
        "angle_id": "a1",
        "title": "Бюджетът е приет",
        "new_proposition": "Съветът прие бюджета на общината.",
        "fact_ids": ["M3DTEST-f001"],
        "reason": "конкретно решение",
        "proposal_only": True,
    }
]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield tmp_path


def _doc():
    return T.load_srt(SRT, transcript_id="M3DTEST", language="bg")


# ---------- store / load round trip ----------


def test_store_then_load_round_trips_exact_stages(env):
    path = C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS)
    assert path.exists()
    cached = C.load(C.transcript_hash(SRT))
    assert cached is not None
    assert cached["facts"] == FACTS
    assert cached["proposals"] == PROPOSALS
    assert cached["success"] is True
    assert cached["cache_key"] == C.cache_key(C.transcript_hash(SRT))


def test_load_miss_without_store(env):
    assert C.load(C.transcript_hash(SRT)) is None


# ---------- failed result is never cached as successful (Part P) ----------


def test_empty_facts_are_never_cached(env):
    path = C.store(C.transcript_hash(SRT), facts=[], proposals=[])
    assert path is None
    assert C.load(C.transcript_hash(SRT)) is None


def test_cached_row_marked_unsuccessful_is_ignored(env):
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS)
    path = C._path(C.transcript_hash(SRT))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["success"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert C.load(C.transcript_hash(SRT)) is None


def test_truncated_cache_file_is_a_miss_not_a_crash(env):
    path = C._path(C.transcript_hash(SRT))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert C.load(C.transcript_hash(SRT)) is None


# ---------- key / version invalidation (Part P) ----------


def test_different_transcript_bytes_do_not_share_entries(env):
    other = SRT + "\n4\n00:00:09,000 --> 00:00:10,000\nОще един ред.\n"
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS)
    assert C.load(C.transcript_hash(other)) is None


def test_stage_version_bump_invalidates(env, monkeypatch):
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS)
    monkeypatch.setattr(C, "STAGE_VERSION", "discovery-stage-cache-v2")
    assert C.load(C.transcript_hash(SRT)) is None


def test_model_config_change_invalidates(env, monkeypatch):
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS)
    from editor_assistant.drafting import generate as gen

    monkeypatch.setattr(gen, "GENERATION_SETTINGS", {"temperature": 0.9, "max_tokens": 128})
    assert C.load(C.transcript_hash(SRT)) is None


def test_cache_format_bump_invalidates(env):
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS)
    path = C._path(C.transcript_hash(SRT))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cache_format"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert C.load(C.transcript_hash(SRT)) is None


# ---------- operator rerun semantics (Part P) ----------


def test_force_rerun_overwrites_and_records_provenance(env):
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS, source={"run": "first"})
    first = C.load(C.transcript_hash(SRT))
    assert first["source"] == {"run": "first"}
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS, source={"run": "rerun"})
    second = C.load(C.transcript_hash(SRT))
    assert second["source"] == {"run": "rerun"}
    assert C.cached_result_status(second).startswith("HIT")


# ---------- integration: default_analyze uses the cache, output unchanged ----------


def test_default_analyze_replays_identical_semantics_from_cache(env, monkeypatch):
    calls = {"n": 0}

    def scripted(prompt, **kwargs):
        calls["n"] += 1
        if "Извлечи" in prompt or "източников" in prompt:
            return (
                json.dumps(
                    {
                        "facts": [
                            {
                                "text": "Общинският съвет прие бюджетът.",
                                "segment_ids": ["M3DTEST-s0003"],
                                "risk_flags": [],
                                "uncertain": False,
                            }
                        ]
                    }
                ),
                {},
            )
        return (
            json.dumps(
                {
                    "angles": [
                        {
                            "angle_id": "a1",
                            "title": "Бюджетно решение",
                            "new_proposition": "Съветът прие бюджета с гласуване.",
                            "fact_ids": ["M3DTEST-f001"],
                            "reason": "решение",
                        }
                    ]
                }
            ),
            {},
        )

    monkeypatch.setattr(intake_mod.discovery.gen, "call_model", scripted)
    doc = _doc()
    try:
        first = intake_mod.default_analyze(doc, raw_srt=SRT)
        assert first["cache_status"] == "MISS"
        assert calls["n"] >= 2  # extraction + proposal calls happened
        calls_after_first = calls["n"]
        second = intake_mod.default_analyze(doc, raw_srt=SRT)
        assert second["cache_status"].startswith("HIT")
        assert calls["n"] == calls_after_first  # zero new model calls on a hit
    finally:
        intake_mod.discovery.extract_facts.skipped_topics = []
        intake_mod.discovery.extract_facts.dropped = []
    # The deterministic downstream result is identical either way.
    for key in ("candidates", "facts", "proposals"):
        assert first[key] == second[key]
    assert first["assessment"]["status"] == second["assessment"]["status"]
    assert first["readiness"]["status"] == second["readiness"]["status"]


def test_default_analyze_without_raw_srt_skips_cache(env, monkeypatch):
    def scripted(prompt, **kwargs):
        return '{"facts": []}', {}

    monkeypatch.setattr(intake_mod.discovery.gen, "call_model", scripted)
    try:
        analysis = intake_mod.default_analyze(_doc())
    finally:
        intake_mod.discovery.extract_facts.skipped_topics = []
        intake_mod.discovery.extract_facts.dropped = []
    assert analysis["cache_status"] == "DISABLED_NO_RAW_SRT"


def test_force_rerun_bypasses_cache_and_revalidates(env, monkeypatch):
    """Part P: the operator can intentionally rerun (force=True bypasses read,
    rewrites the entry, and reports FORCED_RERUN)."""
    calls = {"n": 0}

    def scripted(prompt, **kwargs):
        calls["n"] += 1
        return (
            json.dumps(
                {
                    "facts": [
                        {
                            "text": "Общинският съвет прие бюджетът.",
                            "segment_ids": ["M3DTEST-s0003"],
                            "risk_flags": [],
                            "uncertain": False,
                        }
                    ]
                }
                if "Извлечи" in prompt or "източников" in prompt
                else {"angles": []}
            ),
            {},
        )

    monkeypatch.setattr(intake_mod.discovery.gen, "call_model", scripted)
    doc = _doc()
    try:
        first = intake_mod.default_analyze(doc, raw_srt=SRT)
        assert first["cache_status"] == "MISS"
        frozen = calls["n"]
        rerun = intake_mod.default_analyze(doc, raw_srt=SRT, force=True)
        assert rerun["cache_status"] == "FORCED_RERUN"
        assert calls["n"] > frozen  # the model really ran again
        assert rerun["facts"] == first["facts"]
    finally:
        intake_mod.discovery.extract_facts.skipped_topics = []
        intake_mod.discovery.extract_facts.dropped = []


def test_cache_hit_preserves_dropped_and_skips_provenance(env):
    """A replayed hit keeps dropped/skips audit rows instead of blanking them."""
    skips = [{"topic_id": "M3DTEST-t01", "reason": "VALID_EMPTY_FACT_LIST"}]
    dropped = [{"fact_id": "M3DTEST-d001", "text": "отхвърлен", "status": "DROPPED_UNGROUNDED"}]
    C.store(
        C.transcript_hash(SRT),
        facts=FACTS,
        proposals=PROPOSALS,
        dropped=dropped,
        skips=skips,
    )
    doc = _doc()
    analysis = intake_mod.default_analyze(doc, raw_srt=SRT)
    assert analysis["cache_status"].startswith("HIT")
    assert analysis["dropped"] == dropped
    assert analysis["skips"] == skips


def test_cache_hit_does_not_change_production_shape(env):
    """A cached analysis carries the same keys as a fresh one (no surface drift)."""
    C.store(C.transcript_hash(SRT), facts=FACTS, proposals=PROPOSALS)
    doc = _doc()
    cached_analysis = intake_mod.default_analyze(doc, raw_srt=SRT)
    assert set(cached_analysis) >= {
        "topics",
        "facts",
        "dropped",
        "skips",
        "proposals",
        "candidates",
        "assessment",
        "readiness",
        "support_texts",
    }
    assert cached_analysis["facts"] == FACTS
    assert cached_analysis["proposals"] == PROPOSALS
