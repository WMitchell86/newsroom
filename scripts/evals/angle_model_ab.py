#!/usr/bin/env python3
"""M3D follow-up diagnostic (measurement only): is OUTCOME_FLIP a model-capacity effect?

The M3D report root-caused the flip to the **angle layer**: the model proposes
different *proposition wording* per run, the wording decides which facts get
cited into the readiness rubric, and ±1 rubric point around the threshold flips
`RESEARCH_MORE` <-> `NO_PUBLISHABLE_ANGLE`. In production that stage runs on the
cheap Gemini judge pool (`discovery.propose_angles`, role="judge"), so the
natural hypothesis is: a stronger model on that one stage reduces the wording
variance.

This script measures exactly that, and nothing else:

* the **fact set is pinned** (`--facts-from <run_id>` reuses a real measured
  run's facts, or they are extracted once), so the only variable between arms is
  the model that writes the propositions;
* each arm is one model config on the same evidence, run N times;
* the downstream gate (deterministic `assess_candidates` + `assess_angles` +
  `run_readiness`) is always the production one, unchanged — it is what turns
  wording into an editorial outcome.

Arms (select with `--arms`):

```text
prod-lite   the shipped Gemini judge pool (GEMINI_JUDGE_MODELS) — production config
free        a FREE OpenRouter model (default qwen/qwen3.8-27b:free)
luna-5.6    openai/gpt-5.6-luna-pro via OpenRouter — PAID, needs --allow-paid
```

Provider note: `generate.call_model` resolves an explicit key or `GEMINI_API_KEY`
*before* `OPENROUTER_API_KEY`, so the OpenRouter arms REQUIRE the process to have
no `GEMINI_API_KEY` (the script refuses rather than silently mislabel an arm).

The paid arm is an explicit, one-off, repo-owner-authorised exception for this
diagnostic; the production guard against paid models is NOT changed here.

It calls the same `run_discovery_stages` the M3D harness uses, so its numbers are
comparable with the measured corpus. It writes no production state.

Usage:
  PYTHONPATH=src python3 scripts/evals/angle_model_ab.py --runs 5 \
      --facts-from YsqD4T0D850__r003 --facts-rows-dir var/discovery_stability_corpus \
      --arms free,luna-5.6 --allow-paid
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
# Reuse the M3D harness (loading + overlap helpers) so no measurement logic is
# duplicated between the corpus runner and this diagnostic.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import discovery_stability as ds

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import discovery

OUT_DIR = ROOT / "var" / "angle_model_ab"

#: Arm definitions. `provider` selects the transport; Gemini arms walk the given
#: pool (or the configured production pool when `pool` is None).
ARMS = {
    "prod-lite": {"provider": "gemini", "pool": None, "paid": False},
    "free": {
        "provider": "openrouter",
        "model": "qwen/qwen3.8-27b:free",
        "fallback_model": "google/gemma-4-31b-it:free",
        "paid": False,
    },
    "luna-5.6": {"provider": "openrouter", "model": "openai/gpt-5.6-luna-pro", "paid": True},
}


def _use_gemini_pool(pool):
    """Point Gemini at an arm's pool (None = the configured production pool)."""
    if pool is not None:
        gen.JUDGE_MODEL_POOL = list(pool)
    gen._GEMINI_EXHAUSTED.clear()


def _use_openrouter(model, fallback=None):
    """Select the OpenRouter model for this arm.

    `propose_angles` calls `call_model` without a model argument, so the arm is
    selected through the same knobs the process reads: any explicit
    OPENROUTER_MODEL wins over the free-tier default.
    """
    os.environ["OPENROUTER_MODEL"] = model
    os.environ["OPENROUTER_FREE_MODEL"] = fallback or model
    gen.OPENROUTER_MODEL = model
    gen.OPENROUTER_FALLBACK_MODEL = model


def _provider_ready(arm_spec):
    """Refuse to run an OpenRouter arm in a Gemini-configured process."""
    if arm_spec["provider"] != "openrouter":
        return
    if os.environ.get("GEMINI_API_KEY"):
        raise SystemExit(
            "OpenRouter arm requested but GEMINI_API_KEY is set — call_model would silently "
            "use Gemini and the arm would be mislabelled. Re-run with the key unset:\n"
            "  env -u GEMINI_API_KEY PYTHONPATH=src python3 scripts/evals/angle_model_ab.py ..."
        )


def _seed_facts_from_row(run_id, rows_dir):
    """Reuse a REAL measured run's facts (keeps the corpus evidence, costs no calls)."""
    path = Path(rows_dir) / "runs.jsonl"
    if not path.exists():
        return None
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("run_id") != run_id:
            continue
        facts = ((row.get("stages") or {}).get("fact_extraction") or {}).get("facts") or []
        return [{"fact_id": f.get("fact_id"), **f} for f in facts]
    return None


def extract_facts_once(doc):
    """The pinned evidence, when no measured run can be reused (costs N calls)."""
    topics = discovery.segment_topics(doc)
    facts = list(discovery.extract_facts(doc, topics))
    dropped = list(getattr(discovery.extract_facts, "dropped", []) or [])
    skips = list(getattr(discovery.extract_facts, "skipped_topics", []) or [])
    return facts, dropped, skips, len(topics)


def _proposition_list(stages):
    return [
        (c.get("new_proposition") or c.get("angle_id") or "")
        for c in stages["angle_assessment"]["candidates"]
    ]


def _cited_fact_counts(stages):
    return [len(c.get("fact_ids") or []) for c in stages["angle_assessment"]["candidates"]]


def _proposal_titles(stages):
    return [p.get("title") for p in stages["angles"]["proposals"]]


def _run_failed_empty(stages):
    """True when a run produced no candidates because the model call failed."""
    failure = stages["failure_taxonomy"].get("angle_proposal_failure")
    return bool(failure) and not stages["angle_assessment"]["candidates"]


def run_arm(video_id, doc, facts, *, arm, arm_spec, runs, retries=3, retry_sleep=20.0):
    if arm_spec["provider"] == "gemini":
        _use_gemini_pool(arm_spec.get("pool"))
        models = gen._gemini_pool("judge")
    else:
        _use_openrouter(arm_spec["model"], arm_spec.get("fallback_model"))
        models = [arm_spec["model"]]

    rows = []
    for i in range(1, runs + 1):
        attempts = 0
        while True:
            attempts += 1
            t0 = time.monotonic()
            stages = ds.run_discovery_stages(doc, facts_override=facts)
            latency = round((time.monotonic() - t0) * 1000)
            if not _run_failed_empty(stages) or attempts >= retries:
                break
            # Transient provider rate limit (free tiers 429 this way): retry the
            # SAME run rather than recording an execution failure as a measurement.
            time.sleep(retry_sleep)
        rows.append(
            {
                "arm": arm,
                "run_index": i,
                "model_pool": models,
                "attempts": attempts,
                "provider_failure": stages["failure_taxonomy"].get("angle_proposal_failure"),
                "outcome": stages["outcome"],
                "assessment_status": stages["angle_assessment"]["assessment_status"],
                "proposals": _proposal_titles(stages),
                "propositions": _proposition_list(stages),
                "cited_fact_counts": _cited_fact_counts(stages),
                "angles": len(stages["angle_assessment"]["candidates"]),
                "latency_ms": latency,
            }
        )
        print(
            f"  {arm} run {i}: outcome={rows[-1]['outcome']} "
            f"angles={rows[-1]['angles']} cites={rows[-1]['cited_fact_counts']} "
            f"attempts={attempts} latency={latency}ms",
            flush=True,
        )
    return rows


def summarize_arm(rows):
    usable = [r for r in rows if r["angles"]]
    outcomes = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    if not usable:
        return {
            "runs": len(rows),
            "model_pool": rows[0]["model_pool"],
            "outcome_distribution": outcomes,
            "usable_runs": 0,
            "provider_blocked": True,
            "outcome_flip_vs_first": None,
            "outcome_flip_fraction": None,
            "proposition_overlap_mean": None,
            "proposition_overlap_min": None,
            "cited_fact_count_mean": None,
            "cited_fact_count_range": None,
            "angle_count_range": None,
        }
    baseline = usable[0]
    overlaps = [ds.fact_overlap(baseline["propositions"], r["propositions"]) for r in usable[1:]]
    flips = [r["outcome"] != baseline["outcome"] for r in usable[1:]]
    cites = [c for r in usable for c in r["cited_fact_counts"]]
    return {
        "runs": len(rows),
        "model_pool": rows[0]["model_pool"],
        "usable_runs": len(usable),
        "outcome_distribution": outcomes,
        "distinct_outcomes": sorted({r["outcome"] for r in usable}),
        "outcome_flip_vs_first": sum(flips),
        "outcome_flip_fraction": round(sum(flips) / max(len(flips), 1), 3),
        "proposition_overlap_mean": round(statistics.fmean(overlaps), 3) if overlaps else 1.0,
        "proposition_overlap_min": round(min(overlaps), 3) if overlaps else 1.0,
        "cited_fact_count_mean": round(statistics.fmean(cites), 2) if cites else 0.0,
        "cited_fact_count_range": [min(cites), max(cites)] if cites else [0, 0],
        "angle_count_range": [min(r["angles"] for r in usable), max(r["angles"] for r in usable)],
    }


def _verdict(summaries):
    """Decision rule, fixed BEFORE measuring: only a clear effect justifies a switch.

    Compared arms are the cheapest *usable* arm vs the strongest *usable* arm.
    'Clearly eliminated' = the strongest arm stops flipping AND its propositions
    overlap tighter. Anything weaker keeps the shipped config and records the
    flip rate as residual risk.
    """
    usable = {a: s for a, s in summaries.items() if s.get("usable_runs")}
    if len(usable) < 2:
        return {
            "decision": "INCONCLUSIVE",
            "reason": f"fewer than two usable arms ({sorted(usable)} usable; "
            f"{sorted(set(summaries) - set(usable))} provider-blocked)",
        }
    rank = ["prod-lite", "free", "luna-5.6"]
    ordered = [a for a in rank if a in usable]
    low, high = usable[ordered[0]], usable[ordered[-1]]
    if high["outcome_flip_vs_first"] == 0 and (
        high["proposition_overlap_mean"] > low["proposition_overlap_mean"]
    ):
        return {
            "decision": "USE_STRONGER_MODEL_FOR_ANGLE_ASSESSMENT",
            "reason": (
                f"{ordered[-1]} is flip-free over {high['usable_runs']} usable runs and its "
                f"propositions are tighter ({high['proposition_overlap_mean']} vs "
                f"{low['proposition_overlap_mean']} for {ordered[0]})"
            ),
        }
    if high["outcome_flip_vs_first"] < low["outcome_flip_vs_first"]:
        return {
            "decision": "PARTIAL_IMPROVEMENT_KEEP_CURRENT",
            "reason": (
                f"flips {high['outcome_flip_vs_first']} vs {low['outcome_flip_vs_first']} — "
                "not a clear elimination; no architecture change without observed production pain"
            ),
        }
    return {
        "decision": "KEEP_CURRENT_MODEL",
        "reason": (
            f"no measured advantage (flips {high['outcome_flip_vs_first']} vs "
            f"{low['outcome_flip_vs_first']}, overlap {high['proposition_overlap_mean']} vs "
            f"{low['proposition_overlap_mean']}) — the flip is not model-capacity-driven"
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=ds.FLAKY_VIDEO_ID, help="video id or SRT path")
    parser.add_argument("--runs", type=int, default=5, help="runs PER ARM")
    parser.add_argument("--arms", default="prod-lite,free,luna-5.6")
    parser.add_argument("--allow-paid", action="store_true", help="authorise the paid arm")
    parser.add_argument("--retries", type=int, default=3, help="retries per run on a 429")
    parser.add_argument(
        "--retry-sleep",
        type=float,
        default=20.0,
        help="seconds between retries (free tiers rate-limit per minute)",
    )
    parser.add_argument(
        "--facts-from",
        help="reuse the fact set of a measured run_id instead of extracting again",
    )
    parser.add_argument(
        "--facts-rows-dir",
        default=str(ROOT / "var" / "discovery_stability_corpus"),
        help="runs.jsonl dir for --facts-from",
    )
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args(argv)

    selected = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in selected if a not in ARMS]
    if unknown:
        parser.error(f"unknown arms: {unknown} (choose from {sorted(ARMS)})")
    if any(ARMS[a]["paid"] for a in selected) and not args.allow_paid:
        parser.error("a selected arm is a PAID model — pass --allow-paid to run it")

    video_id, path, character = ds.resolve_input(args.input)
    raw_srt, doc = ds.load_document(video_id, path)
    transcript_hash = hashlib.sha256(raw_srt.encode("utf-8")).hexdigest()
    print(f"input={video_id} ({character}) transcript_hash={transcript_hash[:16]}")

    facts = None
    if args.facts_from:
        facts = _seed_facts_from_row(args.facts_from, args.facts_rows_dir)
        if facts is None:
            print(f"--facts-from {args.facts_from!r} not found; extracting instead")
    if facts is None:
        facts, dropped, skips, topic_count = extract_facts_once(doc)
        print(
            f"extracted {len(facts)} facts from {topic_count} topics "
            f"(dropped={len(dropped)} skipped={len(skips)})"
        )
    else:
        print(f"pinned {len(facts)} facts from {args.facts_from}")
    if not facts:
        print("NO FACTS: the evidence could not be fixed (provider unavailable) — A/B not run.")
        return 2

    all_rows = {}
    skipped_arms = {}
    for arm in selected:
        spec = ARMS[arm]
        try:
            _provider_ready(spec)
        except SystemExit as exc:
            skipped_arms[arm] = str(exc)
            print(f"\n== arm {arm} SKIPPED: {str(exc).splitlines()[0]}")
            continue
        label = spec.get("pool") or spec.get("model")
        print(f"\n== arm {arm} provider={spec['provider']} model={label}")
        all_rows[arm] = run_arm(
            video_id,
            doc,
            facts,
            arm=arm,
            arm_spec=spec,
            runs=args.runs,
            retries=args.retries,
            retry_sleep=args.retry_sleep,
        )

    summaries = {arm: summarize_arm(rows) for arm, rows in all_rows.items()}
    evidence = {
        "video_id": video_id,
        "character": character,
        "transcript_hash": transcript_hash,
        "facts_held_constant": len(facts),
        "facts_source": args.facts_from or "fresh extraction",
        "fact_hash": hashlib.sha256(
            json.dumps([f["text"] for f in facts], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:16],
        "stage": "propose_angles (role=judge) + deterministic gate",
        "runs_per_arm": args.runs,
        "prompt_fp": ds.prompt_fingerprint(),
        "stability_config_fp": ds.stability_version(),
        "paid_model_authorisation": (
            "repo owner authorised openai/gpt-5.6-luna-pro for this diagnostic; the "
            "production paid-model guard is unchanged"
        )
        if args.allow_paid
        else None,
        "arms": {
            arm: {"spec": ARMS[arm], "runs": rows, "summary": summaries[arm]}
            for arm, rows in all_rows.items()
        },
        "arms_not_run": skipped_arms,
        "verdict": _verdict(summaries),
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Arms are measured in separate invocations (a free-tier arm can be slow):
    # one file per arm set, so a partial run never overwrites a finished one.
    out_path = out_dir / f"ab_{video_id}__{'-'.join(selected)}.json"
    out_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n== summary")
    for arm in selected:
        s = summaries.get(arm)
        if s is None:
            print(f"{arm:10s} NOT RUN ({skipped_arms.get(arm, '').splitlines()[0]})")
            continue
        print(
            f"{arm:10s} pool={s['model_pool']}\n"
            f"           usable={s['usable_runs']}/{s['runs']} outcomes={s['outcome_distribution']}"
            f" flips={s['outcome_flip_vs_first']}/{max(s['usable_runs'] - 1, 0)}"
            f" ({s['outcome_flip_fraction']})"
        )
        if s.get("usable_runs"):
            print(
                f"           proposition_overlap mean={s['proposition_overlap_mean']} "
                f"min={s['proposition_overlap_min']}\n"
                f"           cited_facts mean={s['cited_fact_count_mean']} "
                f"range={s['cited_fact_count_range']} angles={s['angle_count_range']}"
            )
    print(f"\nverdict: {evidence['verdict']['decision']} — {evidence['verdict']['reason']}")
    print(f"evidence: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
