#!/usr/bin/env python3
"""M3J Jev shadow-evaluation runner (no production authority).

Runs the three frozen shadow experiments over `fixtures/evals/jev/`:

  corroboration  semantic support of a claim by an opened public-source passage
  grounding      transcript fact entailment (shadow of verify_fact_entailment)
  angles         narrow semantic signals for the 24 V2 candidate angles

Guarantees:
* never mutates fixtures, workflow/runtime state, or drafts;
* results are append-only under the ignored `var/jev_eval/` and the run resumes
  safely (a case already evaluated is skipped);
* without a TypeSafe key/package it reports `JEV_CAPABILITY_UNAVAILABLE` and
  changes nothing.

Usage:
  PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment corroboration
  PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from editor_assistant.workflow import jev, jev_shadow

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "fixtures" / "evals" / "jev"
DEFAULT_OUT_DIR = ROOT / "var" / "jev_eval"

EXPERIMENTS = {
    "corroboration": "corroboration_candidates_v2.jsonl",
    "grounding": "transcript_fact_grounding_v2.jsonl",
    "angles": "transcript_angles_v2.jsonl",
}


# ---------- fixture loading (read-only) ----------


def load_fixture(experiment, fixtures_dir=None):
    base = Path(fixtures_dir or FIXTURES_DIR)
    path = base / EXPERIMENTS[experiment]
    rows = []
    for line in path.open(encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
    return rows  # ---------- typed requests (shared with the YouTube intake, M3B) ----------


build_request = jev_shadow.build_request


# ---------- append-only, resumable result store ----------


def _results_path(experiment, out_dir=None):
    return Path(out_dir or DEFAULT_OUT_DIR) / f"{experiment}.jsonl"


def _done_case_ids(path):
    if not path.exists():
        return set()
    ids = set()
    for line in path.open(encoding="utf-8"):
        if line.strip():
            try:
                ids.add(json.loads(line)["case_id"])
            except (KeyError, json.JSONDecodeError):
                continue
    return ids


def _append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def run_experiment(
    experiment,
    *,
    env=None,
    out_dir=None,
    evaluate_fn=None,
    limit=None,
    fixtures_dir=None,
):
    """Run one experiment, resuming from prior results; returns a summary dict."""
    if experiment not in EXPERIMENTS:
        raise ValueError(f"unknown experiment: {experiment!r}")
    fixture = load_fixture(experiment, fixtures_dir)
    path = _results_path(experiment, out_dir)

    if evaluate_fn is None:
        available, reason = jev.capability_status(env=env)
        if not available:
            return {
                "experiment": experiment,
                "status": jev.JEV_CAPABILITY_UNAVAILABLE,
                "reason": reason,
                "total": len(fixture),
                "evaluated": 0,
                "errors": 0,
                "skipped_existing": 0,
                "results_path": str(path),
            }
        evaluate_fn = jev.evaluate

    done = _done_case_ids(path)
    skipped = len(done)
    evaluated = errors = processed = 0
    for case in fixture:
        if case["case_id"] in done:
            continue
        state, questions = build_request(experiment, case)
        try:
            record = evaluate_fn(state, questions, env=env)
            row = {
                "case_id": case["case_id"],
                "experiment": experiment,
                "result": record,
                "error": None,
            }
            evaluated += 1
        except jev.JevError as exc:
            row = {
                "case_id": case["case_id"],
                "experiment": experiment,
                "result": None,
                "error": {"code": exc.code, "message": str(exc)},
            }
            errors += 1
        _append(path, row)
        done.add(case["case_id"])
        processed += 1
        if limit is not None and processed >= limit:
            break

    return {
        "experiment": experiment,
        "status": jev.JEV_OK,
        "total": len(fixture),
        "evaluated": evaluated,
        "errors": errors,
        "skipped_existing": skipped,
        "results_path": str(path),
    }


# ---------- summarization (evaluation, never truth) ----------


def _top_answer(row, question):
    result = row.get("result") or {}
    answer = ((result.get("answers") or {}).get(question) or {}).get("answer")
    return answer


def summarize(experiment, out_dir=None, fixtures_dir=None):
    fixture = {c["case_id"]: c for c in load_fixture(experiment, fixtures_dir)}
    path = _results_path(experiment, out_dir)
    rows = [
        json.loads(line)
        for line in (path.open(encoding="utf-8") if path.exists() else [])
        if line.strip()
    ]
    summary = {"experiment": experiment, "rows": len(rows), "errors": 0, "latency_ms": []}
    models = {}
    answer_question = {
        "corroboration": "support_relation",
        "grounding": "overall_support",
        "angles": "development_type",
    }[experiment]
    distribution = {}
    labeled = correct = 0
    for row in rows:
        if row.get("error"):
            summary["errors"] += 1
            continue
        result = row.get("result") or {}
        summary["latency_ms"].append(result.get("latency_ms") or 0)
        models[result.get("model_effective")] = models.get(result.get("model_effective"), 0) + 1
        answer = _top_answer(row, answer_question)
        distribution[answer] = distribution.get(answer, 0) + 1
        case = fixture.get(row["case_id"], {})
        if experiment == "corroboration":
            expected = case.get("manual_support_relation")
        elif experiment == "angles":
            expected = case.get("manual_audit_conclusion")
        else:
            expected = None
        if expected:
            labeled += 1
            correct += int(answer == expected)
    latency = summary["latency_ms"]
    summary["latency_avg_ms"] = int(statistics.fmean(latency)) if latency else None
    summary["latency_max_ms"] = max(latency) if latency else None
    summary["models_effective"] = models
    summary[f"{answer_question}_distribution"] = distribution
    summary["labeled_compared"] = labeled
    summary["labeled_matches"] = correct
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="M3J Jev shadow evaluation (no production authority)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    for name in EXPERIMENTS:
        group.add_argument(f"--{name}", action="store_true", help=f"run the {name} experiment")
    group.add_argument("--experiment", choices=sorted(EXPERIMENTS), help="run one named experiment")
    group.add_argument("--all", action="store_true", help="run all three experiments")
    parser.add_argument("--out-dir", default=None, help="override the ignored result dir")
    parser.add_argument("--limit", type=int, default=None, help="evaluate at most N new cases")
    parser.add_argument(
        "--summary", action="store_true", help="only print summaries of existing results"
    )
    args = parser.parse_args(argv)

    if args.experiment:
        names = [args.experiment]
    elif args.all:
        names = list(EXPERIMENTS)
    else:
        names = [name for name in EXPERIMENTS if getattr(args, name)]

    exit_code = 0
    for name in names:
        if args.summary:
            print(json.dumps(summarize(name, args.out_dir), ensure_ascii=False, indent=2))
            continue
        result = run_experiment(name, out_dir=args.out_dir, limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == jev.JEV_CAPABILITY_UNAVAILABLE:
            print(f"{jev.JEV_CAPABILITY_UNAVAILABLE}: {result['reason']}", file=sys.stderr)
        else:
            print(json.dumps(summarize(name, args.out_dir), ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
