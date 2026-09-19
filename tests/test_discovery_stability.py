"""M3D Part P: discovery-stability harness tests (offline, no network ever).

The replay runner must never touch the network/transcriber/search, deterministic
stages must be reproducible, the failure taxonomy must distinguish execution
surfaces from legitimate model-zero, and a zero-yield execution failure must not
silently become an editorial no-story outcome.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from editor_assistant.workflow import discovery as D
from editor_assistant.workflow import intake as intake_mod
from editor_assistant.workflow import transcripts as T

ROOT = Path(__file__).resolve().parents[1]
_RUNNER_PATH = ROOT / "scripts" / "evals" / "discovery_stability.py"
_spec = importlib.util.spec_from_file_location("discovery_stability", _RUNNER_PATH)
HARNESS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HARNESS)


SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\nТочка първа от дневния ред.\n\n"
    "2\n00:00:03,500 --> 00:00:06,000\nДокладна записка за финансиране на училище.\n\n"
    "3\n00:00:06,500 --> 00:00:09,000\nОбщинският съвет прие бюджетът.\n\n"
    "4\n00:00:09,500 --> 00:00:12,000\nСледваща точка: отчет на кмета.\n"
)


@pytest.fixture()
def doc():
    return T.load_srt(SRT, transcript_id="M3DTEST", language="bg")


def _two_fact_stages(no_model):
    stages = HARNESS.run_discovery_stages(doc_factory(), use_model=False)
    stages["fact_extraction"]["fact_texts"] = [
        "Общинският съвет прие бюджета 2026",
        "Кметът представи годишния отчет",
    ]
    stages["fact_extraction"]["facts"] = [
        {"text": t} for t in stages["fact_extraction"]["fact_texts"]
    ]
    return stages


def doc_factory():
    return T.load_srt(SRT, transcript_id="M3DTEST", language="bg")


@pytest.fixture()
def no_model(monkeypatch):
    """Hermetic guard: any model call inside these tests fails the test."""
    monkeypatch.setattr(
        D.gen, "call_model", lambda *a, **k: pytest.fail("model called in offline test")
    )
    yield
    D.extract_facts.skipped_topics = []
    D.extract_facts.dropped = []


# ---------- Part P: replay runner isolation ----------


def test_replay_runner_never_uses_network_or_transcriber(no_model):
    """The harness makes no sockets and imports no transcriber/search module."""
    source = _RUNNER_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "urlopen",
        "urllib.request",
        "import transcriber",
        "from editor_assistant.workflow.transcriber",
        "workflow.search",
        "workflow import search",
        "requests",
        "httpx",
        "youtube_dl",
        "yt_dlp",
    ):
        assert forbidden not in source, f"harness must not reference {forbidden!r}"


def test_same_srt_hash_preserved_across_runs(doc, no_model, tmp_path):
    raw = SRT
    a = HARNESS.run_once("V1", doc, raw, 1, use_model=False, out_dir=tmp_path)
    b = HARNESS.run_once("V1", doc, raw, 2, use_model=False, out_dir=tmp_path)
    expected = __import__("hashlib").sha256(raw.encode()).hexdigest()
    assert a["input"]["transcript_hash"] == expected == b["input"]["transcript_hash"]
    assert a["config_fp"] == b["config_fp"] == HARNESS.stability_version()


def test_deterministic_stages_identical_between_runs(doc, no_model):
    a = HARNESS.run_discovery_stages(doc, use_model=False)
    b = HARNESS.run_discovery_stages(doc, use_model=False)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["segmentation"]["topic_ids"] == b["segmentation"]["topic_ids"]


def test_check_determinism_flags_no_bug_and_never_calls_model(no_model, tmp_path, monkeypatch):
    results = HARNESS.check_determinism(tmp_path)
    assert all(r["status"] in ("IDENTICAL", "SKIPPED_MISSING_SRT") for r in results)
    assert any(r["status"] == "IDENTICAL" for r in results)


# ---------- Part E: failure taxonomy ----------


def test_taxonomy_distinguishes_empty_vs_prose_vs_invalid_json(doc, monkeypatch):
    """Each scripted response drives ONE full extract_facts pass over the doc's
    topics; every topic in a pass gets the same execution surface."""
    topics = D.segment_topics(doc)
    assert topics
    expectations = [
        ("", "EMPTY_MODEL_OUTPUT"),  # empty completion
        ("нямам отговор без json", "NO_JSON"),  # prose without braces
        (
            '{"facts": "не е списък"}',  # parsable JSON, wrong-shaped payload
            "INVALID_JSON",  # unusable output; must NOT crash the batch (M3D)
        ),
        ('{"facts": []}', "VALID_EMPTY_FACT_LIST"),  # honest model-zero
        (
            '{"facts": [{"text": "х", "segment_ids": ["M3DTEST-s9999"]}]}',
            "NO_BINDABLE_FACT",  # proposed but nothing binds to labeled ids
        ),
        (
            # braces present but content unparsable -> INVALID_JSON
            '{"facts": [{"text": "х", "segment_ids": ["M3DTEST-s0001"]},}',
            "INVALID_JSON",
        ),
    ]

    def _pass(response):
        def scripted_call(prompt, **kwargs):
            return response, {}

        monkeypatch.setattr(D.gen, "call_model", scripted_call)
        try:
            D.extract_facts(doc, topics)
            reasons = [s["reason"] for s in D.extract_facts.skipped_topics]
            dropped = D.extract_facts.dropped
        finally:
            D.extract_facts.skipped_topics = []
            D.extract_facts.dropped = []
        return reasons, dropped

    seen = set()
    for response, expected in expectations:
        reasons, dropped = _pass(response)
        assert len(reasons) == len(topics)
        assert set(reasons) == {expected}, f"{response!r} -> {reasons}"
        if expected == "NO_BINDABLE_FACT":
            assert not dropped  # unbindable facts never enter the grounding gate
        seen.add(expected)
    assert seen == {e for _, e in expectations}


def test_taxonomy_classifies_rate_limit_and_timeout(doc, monkeypatch):
    topics = D.segment_topics(doc)

    def rate_limited(prompt, **kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")

    def timeout(prompt, **kwargs):
        raise TimeoutError("timed out")

    try:
        monkeypatch.setattr(D.gen, "call_model", rate_limited)
        D.extract_facts(doc, topics)
        assert {s["reason"] for s in D.extract_facts.skipped_topics} == {
            "RATE_LIMITED: RuntimeError"
        }

        monkeypatch.setattr(D.gen, "call_model", timeout)
        D.extract_facts(doc, topics)
        assert {s["reason"] for s in D.extract_facts.skipped_topics} == {
            "MODEL_TIMEOUT: TimeoutError"
        }
    finally:
        D.extract_facts.skipped_topics = []
        D.extract_facts.dropped = []


# ---------- Part M: zero-yield execution failure is not editorial no-story ----------


def test_zero_yield_execution_failure_becomes_discovery_degraded(doc):
    topics = D.segment_topics(doc)
    analysis = {
        "topics": topics,
        "facts": [],
        "dropped": [],
        "skips": [{"topic_id": topics[0]["topic_id"], "reason": "RATE_LIMITED: RuntimeError"}],
        "proposals": [],
        "candidates": [],
        "assessment": {"status": "NO_EXTRACTED_FACTS", "candidates": []},
        "readiness": {"status": "NOT_RUN"},
        "support_texts": {},
    }
    assert intake_mod._outcome_from(analysis) == intake_mod.OUTCOME_DISCOVERY_DEGRADED


def test_legitimate_model_zero_stays_no_extracted_facts(doc):
    topics = D.segment_topics(doc)
    analysis = {
        "topics": topics,
        "facts": [],
        "dropped": [],
        "skips": [{"topic_id": t["topic_id"], "reason": "VALID_EMPTY_FACT_LIST"} for t in topics],
        "proposals": [],
        "candidates": [],
        "assessment": {"status": "NO_EXTRACTED_FACTS", "candidates": []},
        "readiness": {"status": "NOT_RUN"},
        "support_texts": {},
    }
    assert intake_mod._outcome_from(analysis) == intake_mod.OUTCOME_NO_FACTS


def test_harness_zero_yield_execution_surface_is_discovery_degraded(doc, no_model):
    stages = HARNESS.run_discovery_stages(doc, use_model=False)
    assert stages["outcome"] == "MODEL_DISABLED_BY_HARNESS"
    assert stages["zero_yield"] is False


def test_model_failure_reason_distinguishes_quota_from_generic_failure():
    """Part E: an exhausted provider budget must not look like a generic call
    failure. Measured: after the free tier was spent the surfacing error carried
    `HTTP Error 400`, while the transport had recorded every pool model as
    quota-exhausted."""
    from editor_assistant.drafting import generate as gen

    saved = set(getattr(gen, "_GEMINI_EXHAUSTED", set()))
    try:
        gen._GEMINI_EXHAUSTED = set()
        assert D._model_failure_reason(RuntimeError("boom")).startswith("MODEL_CALL_FAILED")
        assert D._model_failure_reason(RuntimeError("429 quota")).startswith("RATE_LIMITED")
        assert D._model_failure_reason(TimeoutError("timed out")).startswith("MODEL_TIMEOUT")
        # Every judge-pool bucket known exhausted -> the 400-shaped error is a
        # rate limit, not an unexplained failure.
        gen._GEMINI_EXHAUSTED = set(gen.JUDGE_MODEL_POOL)
        reason = D._model_failure_reason(RuntimeError("HTTP Error 400: Bad Request"))
        assert reason.startswith("RATE_LIMITED"), reason
    finally:
        gen._GEMINI_EXHAUSTED = saved


def test_model_output_unusable_when_model_fails_mid_run(doc, monkeypatch):
    """A live-run model outage must surface as DISCOVERY_DEGRADED, not as
    NO_EXTRACTED_FACTS (Part E: infrastructure failure ≠ editorial evidence).
    The runner uses the production intake outcome name as a literal so the
    offline harness never imports the intake orchestrator."""

    def failing_call(prompt, **kwargs):
        raise RuntimeError("429 quota exceeded")

    monkeypatch.setattr(D.gen, "call_model", failing_call)
    try:
        stages = HARNESS.run_discovery_stages(doc, use_model=True)
    finally:
        D.extract_facts.skipped_topics = []
        D.extract_facts.dropped = []
    assert stages["outcome"] == "DISCOVERY_DEGRADED"
    assert stages["outcome"] == intake_mod.OUTCOME_DISCOVERY_DEGRADED
    assert stages["zero_yield"] is False
    assert stages["failure_taxonomy"]["rate_limited"] == len(stages["segmentation"]["topic_ids"])


def test_production_intake_never_sees_the_harness_mode(doc, no_model):
    """The MODEL_DISABLED_BY_HARNESS skip reason must not leak into intake."""
    assert "MODEL_DISABLED_BY_HARNESS" not in D.EXECUTION_FAILURE_REASONS
    assert (
        intake_mod._model_zero_execution_surfaces(
            {"skips": [{"topic_id": "t", "reason": "MODEL_DISABLED_BY_HARNESS"}]}
        )
        == []
    )


# ---------- Part G/O: Jev shadow cannot affect production output ----------


def test_jev_shadow_is_recorded_and_cannot_change_stages(doc, monkeypatch):
    from editor_assistant.workflow import jev

    def fake_evaluate(state, questions, **kwargs):
        return {
            "status": jev.JEV_OK,
            "model_requested": "jev-latest",
            "model_effective": "jev-test",
            "latency_ms": 1,
            "usage": {},
            "answers": {
                name: {
                    "type": spec["kind"],
                    "answer": "SAME_CLAIM",
                    "probabilities": {"SAME_CLAIM": 0.9},
                    "confidence": 0.9,
                }
                for name, spec in questions.items()
            },
        }

    stages = _two_fact_stages(no_model)
    before = json.dumps(stages, sort_keys=True)
    monkeypatch.setattr(jev, "capability_status", lambda **k: (True, "ok"))
    monkeypatch.setattr(jev, "evaluate", fake_evaluate)
    shadow = HARNESS.jev_shadow_relation(stages, doc_factory())
    assert shadow["status"] == "OK"
    assert shadow["rows"][0]["claim_relation"] == "SAME_CLAIM"
    assert json.dumps(stages, sort_keys=True) == before  # production stages untouched


def test_jev_shadow_unavailable_reports_cleanly(doc, monkeypatch):
    from editor_assistant.workflow import jev

    monkeypatch.setattr(jev, "capability_status", lambda **k: (False, "no sdk"))
    stages = HARNESS.run_discovery_stages(doc, use_model=False)
    shadow = HARNESS.jev_shadow_relation(stages, doc)
    assert shadow["status"] == jev.JEV_CAPABILITY_UNAVAILABLE


# ---------- Part F/H: taxonomy + aggregation ----------


def _row_with_outcome(run_id, outcome, facts, *, zero=None):
    stages = {
        "outcome": outcome,
        "zero_yield": (
            (outcome in ("NO_EXTRACTED_FACTS", "NO_PUBLISHABLE_ANGLE") and not facts)
            if zero is None
            else zero
        ),
        "fact_extraction": {
            "facts": [{"text": t} for t in facts],
            "fact_texts": facts,
            "retained_facts": [{"text": t} for t in facts],
            "dropped": [],
        },
        "segmentation": {"topic_ids": ["t01", "t02"]},
        "angle_assessment": {
            "candidates": (
                [
                    {"angle_id": "a", "new_proposition": t, "semantic_status": "PUBLISHABLE_ANGLE"}
                    for t in facts
                ]
                if facts
                else []
            )
        },
        "failure_taxonomy": {"topic_skips": {}},
    }
    return {"run_id": run_id, "stages": stages}


def test_classify_pair_taxonomy():
    same = _row_with_outcome("a", "RESEARCH_MORE", ["Общинският съвет прие бюджета 2026"])
    same2 = _row_with_outcome("b", "RESEARCH_MORE", ["Общинският съвет прие бюджет 2026 год."])
    assert HARNESS.classify_pair(same, same2) == HARNESS.STABLE

    benign = _row_with_outcome("b", "RESEARCH_MORE", ["Съветът одобри нова програма за паркове"])
    # Completely different fact claims with the same readiness outcome:
    # SEMANTIC_VARIATION (Part F: different claims found, state similar).
    assert HARNESS.classify_pair(same, benign) == HARNESS.SEMANTIC

    flip = _row_with_outcome("b", "NO_PUBLISHABLE_ANGLE", ["Съветът гласува за нова тарифа"])
    assert HARNESS.classify_pair(same, flip) == HARNESS.FLIP

    cat = _row_with_outcome("b", "NO_EXTRACTED_FACTS", [])
    assert HARNESS.classify_pair(same, cat) == HARNESS.CATASTROPHIC

    both_zero = _row_with_outcome("b", "NO_EXTRACTED_FACTS", [])
    assert HARNESS.classify_pair(cat, both_zero) == HARNESS.STABLE

    diff_ready = _row_with_outcome("b", "DRAFT_READY", ["Общинският съвет прие бюджета 2026"])
    # Part F names DRAFT_READY <-> RESEARCH_MORE as an OUTCOME_FLIP: the editor
    # either gets a draftable story or is told to research more.
    assert HARNESS.classify_pair(same, diff_ready) == HARNESS.FLIP


def test_zero_yield_is_flagged_by_the_row_not_recomputed():
    """classify_pair trusts the persisted zero_yield flag (Part C capture),
    so a DISCOVERY_DEGRADED run is never misread as editorial zero."""
    story = _row_with_outcome("a", "RESEARCH_MORE", ["факт прие"])
    unusable = _row_with_outcome("b", "DISCOVERY_DEGRADED", [])
    unusable["stages"]["zero_yield"] = False
    assert HARNESS.classify_pair(story, unusable) != HARNESS.CATASTROPHIC


def test_aggregate_video_reports_distribution_not_average():
    rows = [
        _row_with_outcome("r1", "RESEARCH_MORE", ["факт едно прие"]),
        _row_with_outcome("r2", "RESEARCH_MORE", ["факт едно прие"]),
        _row_with_outcome("r3", "NO_EXTRACTED_FACTS", []),
    ]
    agg = HARNESS.aggregate_video(rows)
    assert agg["runs"] == 3
    assert agg["outcome_distribution"] == {"RESEARCH_MORE": 2, "NO_EXTRACTED_FACTS": 1}
    assert agg["readiness_distribution"] == agg["outcome_distribution"]
    assert agg["fact_count_range"] == [0, 1]
    assert agg["retained_fact_count_range"] == [0, 1]
    assert agg["zero_yield_frequency"]["runs"] == 1
    assert agg["catastrophic_zero_yield_runs"] == ["r3"]
    assert agg["taxonomy_vs_first_run"].get(HARNESS.CATASTROPHIC) == 1


def test_aggregate_ignores_harness_disabled_runs_as_outcomes():
    """MODEL_DISABLED_BY_HARNESS rows are execution-context, never outcomes."""
    row = _row_with_outcome("r1", "MODEL_DISABLED_BY_HARNESS", [], zero=False)
    agg = HARNESS.aggregate_video([row])
    assert agg["zero_yield_frequency"]["runs"] == 0


def test_semantic_fact_overlap_greedy_matching():
    a = ["Общинският съвет прие бюджет 2026", "Кметът представи годишния отчет"]
    b = ["Съветът прие бюджета за 2026", "Годишният отчет беше представен от кмета"]
    assert HARNESS.fact_overlap(a, b) > 0.5
    assert HARNESS.fact_overlap(a, []) == 0.0
    assert HARNESS.fact_overlap([], []) == 1.0


# ---------- Part P: L4 cache verification on the production path ----------


def test_cache_verify_proves_replay_stability_and_force_variance(tmp_path, doc, monkeypatch):
    """`verify_cache` separates STABILITY (cached replay) from CORRECTNESS
    visibility (force rerun must still be able to vary)."""
    calls = {"n": 0}

    def scripted(prompt, **kwargs):
        calls["n"] += 1
        if "ID-та" in prompt:  # fact-extraction prompt (unique marker)
            # Groundable wording that still varies run to run (natural variance).
            suffix = " днес" if calls["n"] % 2 else ""
            return (
                json.dumps(
                    {
                        "facts": [
                            {
                                "text": f"Общинският съвет прие бюджетът{suffix}",
                                "segment_ids": ["M3DTEST-s0003"],
                                "risk_flags": [],
                                "uncertain": False,
                            }
                        ]
                    }
                ),
                {},
            )
        # Angle-proposal prompt: a valid proposal bound to the retained fact id.
        return (
            json.dumps(
                {
                    "angles": [
                        {
                            "angle_id": "a1",
                            "title": "Бюджетно решение",
                            "new_proposition": f"Съветът прие бюджета{suffix}",
                            "fact_ids": ["M3DTEST-f001"],
                            "reason": "решение",
                        }
                    ]
                }
            ),
            {},
        )

    monkeypatch.setattr(D.gen, "call_model", scripted)
    try:
        evidence = HARNESS.verify_cache(
            "V1",
            doc,
            SRT,
            cached_runs=4,
            forced_runs=3,
            cache_dir=tmp_path / "cache",
            out_dir=tmp_path,
        )
    finally:
        D.extract_facts.skipped_topics = []
        D.extract_facts.dropped = []

    assert evidence["cached_runs"][0]["facts"] >= 1, "the population run must retain facts"
    assert evidence["first_run_was_population"] is True
    assert evidence["cached_hits_only_after_first"] is True
    assert evidence["cached_replay_identical"] is True  # operational reproducibility
    assert evidence["forced_always_bypassed_cache"] is True
    assert evidence["forced_rerun_observes_variance"] is True  # not hidden by the cache
    assert evidence["cache_stores_failures"]["empty_result_refused"] is True
    assert evidence["cache_stores_failures"]["frozen_failure_entries"] == []
    assert (tmp_path / "cache_replay_V1.jsonl").exists()


# ---------- resume semantics (Part I: never reuse cached model responses) ----------


def test_run_resume_by_run_id_and_config(tmp_path, doc, no_model):
    HARNESS.run_once("V1", doc, SRT, 1, use_model=False, out_dir=tmp_path)
    ids = HARNESS.done_run_ids(HARNESS._runs_path(tmp_path), HARNESS.stability_version())
    assert "V1__r001" in ids


def test_different_config_fp_does_not_resume(tmp_path, doc, no_model):
    HARNESS.run_once("V1", doc, SRT, 1, use_model=False, out_dir=tmp_path)
    other = HARNESS.stability_version() + "-other"
    ids = HARNESS.done_run_ids(HARNESS._runs_path(tmp_path), other)
    assert "V1__r001" not in ids
