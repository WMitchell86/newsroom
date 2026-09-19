"""M3J Part C/J: fixture schema + runner behavior (offline, no live Jev)."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from editor_assistant.workflow import jev

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "evals" / "jev"
_RUNNER_PATH = ROOT / "scripts" / "evals" / "jev_shadow_eval.py"
_spec = importlib.util.spec_from_file_location("jev_shadow_eval", _RUNNER_PATH)
EVAL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EVAL)


def _rows(name):
    return [json.loads(line) for line in (FIXTURES / name).open(encoding="utf-8") if line.strip()]


# ---------- fixture schema ----------


def test_angles_fixture_has_all_24_and_the_7_disagreements():
    rows = _rows("transcript_angles_v2.jsonl")
    assert len(rows) == 24
    assert all(r["case_id"] and r["proposition"] for r in rows)
    disagreements = [
        r for r in rows if r["prior_llm_shadow"]["agreement_with_deterministic"] is False
    ]
    assert len(disagreements) == 7
    assert all(r["manual_audit_conclusion"] for r in disagreements)
    assert all(r["deterministic_assessment"]["semantic_status"] for r in rows)


def test_grounding_fixture_has_retained_and_dropped_with_support_text():
    rows = _rows("transcript_fact_grounding_v2.jsonl")
    assert len(rows) == 109
    assert any(r["retained"] for r in rows) and any(not r["retained"] for r in rows)
    assert all(r["claim_text"] for r in rows)
    assert all(r["support_text"] for r in rows)  # exact segment text resolved
    dropped = [r for r in rows if not r["retained"]]
    assert all(r["deterministic_grounding_status"] == "DROPPED_UNGROUNDED" for r in dropped)


def test_corroboration_fixture_has_excerpts_and_honest_labels():
    rows = _rows("corroboration_candidates_v2.jsonl")
    assert len(rows) == 16
    assert {r["case_id"].split("::")[0] for r in rows}  # multiple facts
    assert all(r["source_url"] and r["source_excerpt"] for r in rows)
    assert all(r["lexical_decision"] == "LEXICAL_CANDIDATE" for r in rows)
    # labeled rows carry a source; unlabeled rows stay explicitly null
    for r in rows:
        if r["manual_support_relation"]:
            assert r["manual_label_source"]
        else:
            assert r["manual_label_source"] is None
            assert r["manual_event_relation"] is None


def test_fixtures_contain_no_secrets_or_drafts():
    for name in EVAL.EXPERIMENTS.values():
        text = (FIXTURES / name).read_text(encoding="utf-8").lower()
        for forbidden in ("api_key", "typesafe_api", "token", "draft_text", "final_text"):
            assert forbidden not in text, f"{name} must not contain {forbidden!r}"


# ---------- runner: capability, resume, idempotence ----------


def _fake_evaluate(state, questions, env=None):
    return {
        "status": jev.JEV_OK,
        "model_requested": "jev-latest",
        "model_effective": "jev-test",
        "latency_ms": 7,
        "usage": {},
        "answers": {
            name: {"type": spec["kind"], "answer": None, "probabilities": {}, "confidence": 0.5}
            for name, spec in questions.items()
        },
    }


def _hash_fixtures():
    return {
        name: hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        for name in EVAL.EXPERIMENTS.values()
    }


def test_missing_capability_reports_cleanly_and_writes_nothing(tmp_path):
    result = EVAL.run_experiment("angles", env={}, out_dir=tmp_path)
    assert result["status"] == jev.JEV_CAPABILITY_UNAVAILABLE
    assert result["evaluated"] == 0
    assert not (tmp_path / "angles.jsonl").exists()  # nothing fabricated


def test_runner_evaluates_and_resumes_idempotently(tmp_path):
    before = _hash_fixtures()
    first = EVAL.run_experiment("corroboration", out_dir=tmp_path, evaluate_fn=_fake_evaluate)
    assert first["evaluated"] == 16 and first["skipped_existing"] == 0
    lines = (tmp_path / "corroboration.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 16

    second = EVAL.run_experiment("corroboration", out_dir=tmp_path, evaluate_fn=_fake_evaluate)
    assert second["evaluated"] == 0 and second["skipped_existing"] == 16
    assert (
        len((tmp_path / "corroboration.jsonl").read_text(encoding="utf-8").strip().splitlines())
        == 16
    )
    assert _hash_fixtures() == before  # fixtures never mutated


def test_runner_resumes_a_partial_run(tmp_path):
    EVAL.run_experiment("angles", out_dir=tmp_path, evaluate_fn=_fake_evaluate, limit=5)
    assert len((tmp_path / "angles.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 5
    rest = EVAL.run_experiment("angles", out_dir=tmp_path, evaluate_fn=_fake_evaluate)
    assert rest["skipped_existing"] == 5
    assert rest["evaluated"] == 19


def test_provider_errors_are_recorded_and_do_not_stop_the_run(tmp_path):
    class Boom(jev.JevProviderError):
        pass

    def failing(state, questions, env=None):
        raise Boom("JEV_PROVIDER_ERROR: boom")

    result = EVAL.run_experiment("grounding", out_dir=tmp_path, evaluate_fn=failing, limit=3)
    assert result["errors"] == 3
    rows = [
        json.loads(l)
        for l in (tmp_path / "grounding.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(r["error"]["code"] == jev.JEV_PROVIDER_ERROR for r in rows)


def test_summary_compares_against_manual_labels(tmp_path):
    manual = {
        c["case_id"]: c["manual_support_relation"]
        for c in EVAL.load_fixture("corroboration")
        if c["manual_support_relation"]
    }

    def labeled(state, questions, env=None):
        answer = manual.get(state.get("_case_id"))
        record = _fake_evaluate(state, questions, env)
        record["answers"]["support_relation"]["answer"] = answer
        return record

    # feed the case id through state to let the fake echo the manual label
    original = EVAL.build_request
    try:
        EVAL.build_request = lambda exp, case: (
            {"_case_id": case["case_id"], **original(exp, case)[0]},
            original(exp, case)[1],
        )
        EVAL.run_experiment("corroboration", out_dir=tmp_path, evaluate_fn=labeled)
    finally:
        EVAL.build_request = original

    summary = EVAL.summarize("corroboration", out_dir=tmp_path)
    assert summary["labeled_compared"] == len(manual)
    assert summary["labeled_matches"] == len(manual)


def test_runner_has_no_drafting_or_publishing_path():
    source = _RUNNER_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("record_editor_final", "publish", "wordpress", "drafting"):
        assert forbidden not in source


@pytest.mark.parametrize("experiment", sorted(EVAL.EXPERIMENTS))
def test_every_experiment_builds_a_typed_request(experiment):
    case = EVAL.load_fixture(experiment)[0]
    state, questions = EVAL.build_request(experiment, case)
    assert state and questions
    for spec in questions.values():
        assert spec["kind"] in (jev.QUESTION_CHOICE, jev.QUESTION_NOUL, jev.QUESTION_SCORE)
