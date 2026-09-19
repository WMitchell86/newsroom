#!/usr/bin/env python3
"""M3D discovery-stability replay harness (measurement only, no production writes).

Replays the frozen discovery V2 chain over **cached raw SRTs** — never network,
never transcriber, never search, never drafting. Reuses the production functions
(`discovery.segment_topics` / `extract_facts` / `propose_angles` /
`assess_candidates` / `angles.assess_angles` / `discovery.run_readiness`);
no discovery logic is duplicated here.

What it does:
* runs the discovery pipeline N times per recording, calling the model every
  run (cached model responses are never reused for variance measurement);
* captures stage-level output per run under the ignored `var/discovery_stability/`;
* verifies deterministic-stage invariants (same SRT bytes + code + config =>
  byte-identical segmentation / fact-ids / grounding / angle scoring / readiness);
* classifies run-to-run differences into the M3D stability taxonomy;
* appends rows to `runs.jsonl` (resumable: an interrupted corpus resumes by
  run_id) and prints a per-recording + corpus summary.

Usage:
  PYTHONPATH=src python3 scripts/evals/discovery_stability.py --list
  PYTHONPATH=src python3 scripts/evals/discovery_stability.py --check-determinism
  PYTHONPATH=src python3 scripts/evals/discovery_stability.py --input <srt-path-or-video-id> --runs 20
  PYTHONPATH=src python3 scripts/evals/discovery_stability.py --suite --runs 10
  PYTHONPATH=src python3 scripts/evals/discovery_stability.py --suite --runs 10 --dry-run   # zero model calls

Model/config observability (Part J) is recorded per run; API keys never are.
Jev remains shadow-only and off by default (--jev-shadow), and even then it
cannot change any production outcome (Part G/O).
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

from editor_assistant.workflow import angles as angles_mod
from editor_assistant.workflow import discovery, transcripts

OUT_DIR = ROOT / "var" / "discovery_stability"
DISCOVERY_VERSION = discovery.PIPELINE_VERSION

#: Known flaky recording (M3B evidence: RESEARCH_MORE once, NO_EXTRACTED_FACTS
#: another, same cached SRT). Gets the higher repetition budget by default.
FLAKY_VIDEO_ID = "YsqD4T0D850"

#: Cached raw SRTs available offline (Part B corpus). No YouTube fetch happens.
CORPUS = {
    # A. known easy/stable committee recording (produced grounded facts in M2S)
    "7k-FZXrcmq8": {
        "path": ROOT / "var/youtube_transcripts/raw/7k-FZXrcmq8.bg-orig.srt",
        "character": "A_stable",
    },
    # B. the known flaky recording (RESEARCH_MORE vs NO_EXTRACTED_FACTS)
    "YsqD4T0D850": {
        "path": ROOT / "var/youtube_transcripts/raw/YsqD4T0D850.bg-orig.srt",
        "character": "B_flaky",
    },
    # C. longer / multi-agenda recording
    "b13U-N_Vk9c": {
        "path": ROOT / "var/youtube_transcripts/raw/b13U-N_Vk9c.bg-orig.srt",
        "character": "C_long",
    },
    # D. unseen/newer public recording (cached from the M2S batch)
    "xvsdi_j7s5c": {
        "path": ROOT / "var/youtube_transcripts/raw/xvsdi_j7s5c.bg-orig.srt",
        "character": "D_other",
    },
}


# ---------- input resolution (read-only, offline) ----------


def _default_corpus_run_id(video_id):
    """Corpus runs keep one run-set per video; SRT-hash binds them to bytes."""
    return f"{video_id}"


def resolve_input(spec):
    """`--input` accepts a video id from CORPUS, a video id under
    var/youtube_intake/transcripts/, or an explicit SRT path."""
    if spec in CORPUS:
        entry = CORPUS[spec]
        return spec, Path(entry["path"]), entry["character"]
    path = Path(spec)
    if path.suffix == ".srt" and path.exists():
        video_id = path.name.split(".")[0]
        character = "EXPLICIT_FILE"
        return video_id, path, character
    intake_copy = ROOT / "var/youtube_intake/transcripts" / f"{spec}.srt"
    matches = (
        sorted((ROOT / "var/youtube_intake/transcripts").glob(f"{spec}.*.srt"))
        if (ROOT / "var/youtube_intake/transcripts").exists()
        else []
    )
    if intake_copy.exists():
        return spec, intake_copy, "EXPLICIT_ID"
    if matches:
        return spec, matches[0], "EXPLICIT_ID"
    raise SystemExit(f"input not found: {spec!r} (use --list to see the corpus)")


def load_document(video_id, path):
    raw_srt = Path(path).read_text(encoding="utf-8")
    doc = transcripts.load_srt(
        raw_srt,
        transcript_id=video_id,
        language="bg",
        origin="youtube_auto_caption",
        trust_level=transcripts.TRUST_AUTO_CAPTION,
    )
    return raw_srt, doc


# ---------- stage runner (reuses production functions; no duplicated logic) ----------


def run_discovery_stages(doc, *, use_model=True):
    """One discovery pass, capturing every stage separately (M3D Part C).

    Deterministic when `use_model=False`; otherwise calls the model for fact
    extraction and angle proposals exactly as production intake does.
    Returns a stage dict; model execution surfaces are recorded, never hidden.
    """
    stages = {}

    topics = discovery.segment_topics(doc)
    stages["segmentation"] = {
        "topic_ids": [t["topic_id"] for t in topics],
        "boundaries": [
            {
                "start_ms": t["start_ms"],
                "end_ms": t["end_ms"],
                "deterministic": t["deterministic_boundary"],
            }
            for t in topics
        ],
        "labels": [t["label"] for t in topics],
        "topic_text_hashes": [
            hashlib.sha256(t["text"].encode("utf-8")).hexdigest()[:16] for t in topics
        ],
        "segment_counts": [len(t["segment_ids"]) for t in topics],
    }

    facts, dropped, skips = [], [], []
    if topics:
        if use_model:
            facts = list(discovery.extract_facts(doc, topics))
            dropped = list(getattr(discovery.extract_facts, "dropped", []))
            skips = list(getattr(discovery.extract_facts, "skipped_topics", []))
        else:
            # Deterministic-mode proxy: no model call, every topic is skipped
            # with an explicit reason so zero-yield stays attributable.
            skips = [
                {"topic_id": t["topic_id"], "reason": "MODEL_DISABLED_BY_HARNESS"} for t in topics
            ]
    stages["fact_extraction"] = {
        "facts": [
            {
                "fact_id": f["fact_id"],
                "text": f["text"],
                "segment_ids": f["segment_ids"],
                "risk_flags": f["risk_flags"],
                "uncertain": f["uncertain"],
                "topic_id": f["topic_id"],
                "procedural_status": f["procedural_status"],
                "entailment_coverage": f["entailment_coverage"],
            }
            for f in facts
        ],
        "fact_ids": [f["fact_id"] for f in facts],
        "fact_texts": [f["text"] for f in facts],
        # Retained = grounded facts that survive to angle generation.
        "retained_facts": [f["fact_id"] for f in facts],
        "retained_fact_count": len(facts),
        "dropped": [
            {
                "text": d.get("text"),
                "status": d.get("fact_grounding_status"),
                "failures": d.get("grounding_failures"),
            }
            for d in dropped
        ],
        "dropped_fact_count": len(dropped),
        "skips": skips,
    }

    # failure taxonomy (Part E) derived from the per-topic skip reasons
    reasons = [str(s.get("reason", "")) for s in skips]
    head = [r.split(":", 1)[0].strip() for r in reasons]
    exec_failures = [r for r in head if r in discovery.EXECUTION_FAILURE_REASONS]
    stages["failure_taxonomy"] = {
        "topic_skips": {h: head.count(h) for h in sorted(set(head))},
        "model_call_failed": sum(1 for h in exec_failures if h == "MODEL_CALL_FAILED"),
        "rate_limited": sum(1 for h in exec_failures if h == "RATE_LIMITED"),
        "model_timeout": sum(1 for h in exec_failures if h == "MODEL_TIMEOUT"),
        "empty_model_output": sum(1 for h in exec_failures if h == "EMPTY_MODEL_OUTPUT"),
        "no_json": sum(1 for h in exec_failures if h == "NO_JSON"),
        "invalid_json": sum(1 for h in exec_failures if h == "INVALID_JSON"),
        "valid_empty_fact_list": head.count("VALID_EMPTY_FACT_LIST"),
        "no_bindable_fact": head.count("NO_BINDABLE_FACT"),
        "empty_topic_text": head.count("EMPTY_TOPIC_TEXT"),
    }

    proposals = []
    if facts and use_model:
        try:
            proposals = discovery.propose_angles(facts)
        except Exception as exc:  # noqa: BLE001 - record, never fabricate
            stages["failure_taxonomy"]["angle_proposal_failure"] = discovery._model_failure_reason(
                exc
            )
    stages["angles"] = {"proposals": proposals}

    candidates, diagnostics = discovery.assess_candidates(
        proposals, facts, repeated={}, use_model_judge=False
    )
    if candidates:
        packet_facts = [
            {"id": f["fact_id"], "text": f["text"], "scope": "current_event"} for f in facts
        ]
        try:
            assessment = angles_mod.assess_angles(
                {
                    "facts": packet_facts,
                    "source_type": "transcript",
                    "source_text": " ".join(f["text"] for f in facts),
                },
                candidates,
                min_candidates=1,
            )
        except angles_mod.AngleError as exc:
            assessment = {
                "status": "INVALID_PROPOSALS",
                "reason": str(exc),
                "candidates": candidates,
            }
    elif facts:
        assessment = {
            "status": discovery.INSUFFICIENT_ANGLES,
            "reason": "фактите не предложиха реални ъгли",
            "candidates": [],
        }
    else:
        assessment = {
            "status": "NO_EXTRACTED_FACTS",
            "reason": "моделът не върна факти",
            "candidates": [],
        }
    assessment["diagnostics"] = diagnostics
    stages["angle_assessment"] = {
        "assessment_status": assessment.get("status"),
        "selected_angle_id": assessment.get("selected_angle_id"),
        "candidates": [
            {
                "angle_id": c.get("angle_id"),
                "title": c.get("title"),
                "new_proposition": c.get("new_proposition"),
                "fact_ids": c.get("fact_ids"),
                "scores": {k: v.get("score") for k, v in (c.get("scores") or {}).items()},
                "semantic_status": c.get("semantic_status"),
                "semantic_reason": c.get("semantic_reason"),
            }
            for c in (assessment.get("candidates") or [])
        ],
        "assessor": diagnostics.get("assessor"),
    }

    readiness = {"status": "NOT_RUN", "reason": f"angle gate: {assessment.get('status')}"}
    if assessment.get("status") in (
        angles_mod.READY,
        angles_mod.NEEDS_RESEARCH,
        angles_mod.NO_ANGLE,
    ):
        packet = discovery.build_evidence_packet(doc, facts, assessment)
        readiness = discovery.run_readiness(packet)
    stages["readiness"] = {
        "status": readiness.get("status"),
        "reason": readiness.get("reason"),
        "missing_dimensions": readiness.get("missing"),
        "research_questions": readiness.get("research_questions"),
    }

    stages["outcome"] = (
        readiness.get("status")
        if readiness.get("status")
        in (
            "DRAFT_READY",
            "RESEARCH_MORE",
            "EDITOR_DECISION_REQUIRED",
        )
        else (
            "NO_PUBLISHABLE_ANGLE"
            if assessment.get("status") in (angles_mod.NO_ANGLE, angles_mod.NOT_VIABLE)
            else "NO_EXTRACTED_FACTS"
            if assessment.get("status") == "NO_EXTRACTED_FACTS"
            else "UNKNOWN"
        )
    )
    stages["zero_yield"] = (
        stages["outcome"] in ("NO_EXTRACTED_FACTS", "NO_PUBLISHABLE_ANGLE") and not facts
    )
    if stages["outcome"] == "NO_EXTRACTED_FACTS" and not facts:
        exec_tax = stages["failure_taxonomy"]
        execution_failed = any(
            exec_tax.get(k)
            for k in (
                "model_call_failed",
                "rate_limited",
                "model_timeout",
                "empty_model_output",
                "no_json",
                "invalid_json",
                "no_bindable_fact",
            )
        )
        harness_disabled = bool(head) and all(h == "MODEL_DISABLED_BY_HARNESS" for h in head)
        if execution_failed:
            # Execution failure is not editorial no-story evidence (Part M).
            # The name matches the production intake contract
            # (intake.OUTCOME_DISCOVERY_DEGRADED); kept as a local literal so
            # this offline runner never imports the intake orchestrator.
            stages["outcome"] = "DISCOVERY_DEGRADED"
            stages["zero_yield"] = False
        elif harness_disabled:
            # The harness itself skipped the model; this says nothing about the
            # transcript and must never enter stability statistics as a story.
            stages["outcome"] = "MODEL_DISABLED_BY_HARNESS"
            stages["zero_yield"] = False
    return stages


def stability_version():
    """Configuration fingerprint: code identity + frozen evaluation config."""
    return hashlib.sha256(
        json.dumps(
            {
                "discovery_version": DISCOVERY_VERSION,
                "max_topics": discovery.MAX_TOPICS_DEFAULT,
                "threshold": angles_mod.THRESHOLD,
                "rubric": angles_mod.RUBRIC_VERSION,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]


# ---------- persistence (ignored runtime dir; resumable) ----------


def _runs_path(out_dir=None):
    return Path(out_dir or OUT_DIR) / "runs.jsonl"


def _append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def done_run_ids(path, config_fp):
    ids = set()
    if not path.exists():
        return ids
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if row.get("config_fp") == config_fp:
                ids.add(row.get("run_id"))
        except json.JSONDecodeError:
            continue
    return ids


# ---------- model/config observability (Part J; never a key) ----------


def prompt_fingerprint():
    """Prompt/config fingerprint: Part C input identity + Part J observability.

    Kept SEPARATE from stability_version() so the 39 already-measured rows
    keep their resume identity: stability_version covers the model side, this
    covers the prompt/rubric side, and every new row persists both.
    """
    identity = {
        "facts_prompt": hashlib.sha256(discovery._FACTS_PROMPT.encode("utf-8")).hexdigest()[:12],
        "angles_prompt": hashlib.sha256(discovery._ANGLES_PROMPT.encode("utf-8")).hexdigest()[:12],
        "rubric_version": angles_mod.RUBRIC_VERSION,
        "angle_threshold": angles_mod.THRESHOLD,
        "max_topics": discovery.MAX_TOPICS_DEFAULT,
        "discovery_version": DISCOVERY_VERSION,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def model_config_observability():
    from editor_assistant.drafting import generate as gen

    return {
        "provider": gen.API_PROVIDER,
        "judge_pool": list(gen.JUDGE_MODEL_POOL),
        "model_alias": "judge",
        "effective_model_version": None,  # filled per-call when available
        "temperature": gen.GENERATION_SETTINGS["temperature"],
        "top_p": None,  # the judge transport sends no top_p
        "seed": None,  # not supported by the current transport; never assumed
        "max_tokens": gen.GENERATION_SETTINGS["max_tokens"],
        "thinking_budget": gen.THINKING_BUDGET,
        # Discovery makes exactly one model call per topic / proposal batch:
        # no prompt-level retries, so retry_count is an explicit 0.
        "retry_count": 0,
        "api_key_present": bool(os.environ.get("GEMINI_API_KEY")),
    }


# ---------- one run ----------


def run_once(
    video_id,
    doc,
    raw_srt,
    run_index,
    *,
    use_model=True,
    jev_shadow_fn=None,
    out_dir=None,
):
    config_fp = stability_version()
    run_id = f"{video_id}__r{run_index:03d}"
    transcript_hash = hashlib.sha256(raw_srt.encode("utf-8")).hexdigest()

    t0 = time.monotonic()
    stages = run_discovery_stages(doc, use_model=use_model)
    latency_ms = round((time.monotonic() - t0) * 1000)

    jev_rows = None
    if jev_shadow_fn is not None:
        # SHADOW ONLY (Part G/O): evaluates semantic relations between facts of
        # this run; its answers are recorded and never alter any stage above.
        jev_rows = jev_shadow_fn(stages, doc)

    row = {
        "run_id": run_id,
        "video_id": video_id,
        "run_index": run_index,
        "config_fp": config_fp,
        "mode": "model" if use_model else "deterministic",
        "input": {
            "transcript_hash": transcript_hash,
            "transcript_bytes": len(raw_srt.encode("utf-8")),
            "discovery_version": DISCOVERY_VERSION,
            "stability_config_fp": config_fp,
        },
        "model": model_config_observability()
        if use_model
        else {"disabled_by": "deterministic-mode"},
        "prompt_fp": prompt_fingerprint(),
        "response": {"latency_ms": latency_ms, "status": "OK" if use_model else "DETERMINISTIC"},
        "stages": stages,
        "jev_shadow": jev_rows,
    }
    _append(_runs_path(out_dir), row)
    return row


# ---------- deterministic-stage invariant (Part D) ----------


def check_determinism(out_dir=None):
    """Same SRT bytes + code + config => all deterministic stages identical.

    Two full pipeline invocations in deterministic mode (no model) must produce
    byte-identical stage captures for every corpus recording. Any difference is
    a BUG (Part D) — never normalized away.
    """
    from editor_assistant.drafting import generate as gen

    results = []
    original_call_model = gen.call_model

    def _forbidden_call(*_a, **_k):
        raise AssertionError("determinism check must never call the model")

    for video_id, entry in CORPUS.items():
        path = Path(entry["path"])
        if not path.exists():
            results.append({"video_id": video_id, "status": "SKIPPED_MISSING_SRT"})
            continue
        raw_srt, doc = load_document(video_id, path)
        gen.call_model = _forbidden_call
        try:
            a = run_discovery_stages(doc, use_model=False)
            b = run_discovery_stages(doc, use_model=False)
        finally:
            gen.call_model = original_call_model
        ja = json.dumps(a, ensure_ascii=False, sort_keys=True)
        jb = json.dumps(b, ensure_ascii=False, sort_keys=True)
        results.append(
            {
                "video_id": video_id,
                "transcript_hash": hashlib.sha256(raw_srt.encode("utf-8")).hexdigest(),
                "status": "IDENTICAL" if ja == jb else "BUG_DETERMINISTIC_STAGE_DIFFERS",
                "segmentation_topics": len(a["segmentation"]["topic_ids"]),
            }
        )
    return results


# ---------- comparison / aggregation (Parts F, G, H) ----------

STABLE = "STABLE"
BENIGN = "BENIGN_VARIATION"
SEMANTIC = "SEMANTIC_VARIATION"
FLIP = "OUTCOME_FLIP"
CATASTROPHIC = "CATASTROPHIC_ZERO_YIELD"

_READINESS_OUTCOMES = ("DRAFT_READY", "RESEARCH_MORE", "EDITOR_DECISION_REQUIRED")
_EDITORIAL_ZERO = ("NO_EXTRACTED_FACTS", "NO_PUBLISHABLE_ANGLE")


def _norm_tokens(text):
    return sorted(discovery._content_tokens(discovery._digits_norm(text or "")))


def _tokens_match(tok, other_set, other_list):
    """Exact or 5-char-prefix match (BG morphology), mirroring production's
    verify_fact_entailment matching. Deterministic, language-generic."""
    if tok in other_set:
        return True
    if len(tok) > 4:
        prefix = tok[:5]
        return any(len(s) > 4 and s[:5] == prefix for s in other_list)
    return False


def _coverage(a_tokens, b_tokens):
    """Fraction of A's distinct tokens matched in B (directional)."""
    if not a_tokens:
        return 1.0 if not b_tokens else 0.0
    sb, bl = set(b_tokens), list(b_tokens)
    hits = sum(1 for t in set(a_tokens) if _tokens_match(t, sb, bl))
    return hits / len(set(a_tokens))


def _overlap_ratio(a_tokens, b_tokens):
    """Symmetric best-direction coverage for a token pair."""
    return max(_coverage(a_tokens, b_tokens), _coverage(b_tokens, a_tokens))


def fact_overlap(a_texts, b_texts):
    """Greedy semantic overlap between two fact lists (>0.5 token Jaccard)."""
    if not a_texts and not b_texts:
        return 1.0
    if not a_texts or not b_texts:
        return 0.0
    used = set()
    hits = 0
    for a in a_texts:
        ta = _norm_tokens(a)
        for j, b in enumerate(b_texts):
            if j in used:
                continue
            if _overlap_ratio(ta, _norm_tokens(b)) > 0.5:
                used.add(j)
                hits += 1
                break
    return hits / max(len(a_texts), len(b_texts))


def classify_pair(run_a, run_b):
    """M3D Part F stability taxonomy for two same-input runs."""
    sa, sb = run_a["stages"], run_b["stages"]
    outcome_a, outcome_b = sa["outcome"], sb["outcome"]

    zero_a = sa["zero_yield"]
    zero_b = sb["zero_yield"]

    if zero_a and zero_b:
        return STABLE if outcome_a == outcome_b else BENIGN
    if zero_a != zero_b:
        # One run found a story, the identical-input run found nothing at all:
        # the highest-severity reliability failure (Part F). Whether the zero
        # side carried an execution surface is reported separately by
        # model_failure_frequency, so the root cause stays visible.
        return CATASTROPHIC
    if outcome_a != outcome_b:
        if {outcome_a, outcome_b} <= set(_READINESS_OUTCOMES):
            return SEMANTIC
        return FLIP
    fa = sa["fact_extraction"]["fact_texts"]
    fb = sb["fact_extraction"]["fact_texts"]
    ov = fact_overlap(fa, fb)
    if ov >= 0.85:
        return STABLE
    if ov >= 0.5:
        return BENIGN
    return SEMANTIC


def baseline_angle_props(row):
    """Candidate proposition list for one run (semantic angle overlap input).

    Pre-L4 rows and unit fixtures lack new_proposition on the stub
    candidates; fall back to angle_id so old rows stay aggregatable.
    """
    out = []
    for c in row["stages"]["angle_assessment"]["candidates"]:
        out.append(c.get("new_proposition") or c.get("angle_id") or "")
    return out


def aggregate_video(rows):
    """Per-recording metrics (Part H). Never hides instability in averages."""
    outcomes = {}
    for r in rows:
        o = r["stages"]["outcome"]
        outcomes[o] = outcomes.get(o, 0) + 1
    fact_counts = [len(r["stages"]["fact_extraction"]["facts"]) for r in rows]
    # Pre-L4 rows (before/after dirs) lack retained_facts; fall back to facts
    # so the already-measured evidence stays readable.
    fx = [r["stages"]["fact_extraction"] for r in rows]
    dropped_counts = [len(f.get("dropped", [])) for f in fx]
    retained_counts = [len(f.get("retained_facts", f.get("facts", []))) for f in fx]
    topic_ids = [tuple(r["stages"]["segmentation"]["topic_ids"]) for r in rows]
    seg_stable = all(t == topic_ids[0] for t in topic_ids)
    topic_counts = [len(r["stages"]["segmentation"]["topic_ids"]) for r in rows]
    angle_counts = [len(r["stages"]["angle_assessment"]["candidates"]) for r in rows]
    retained_angle_ids = [
        len(
            [
                c
                for c in r["stages"]["angle_assessment"]["candidates"]
                if c.get("semantic_status") == "PUBLISHABLE_ANGLE"
            ]
        )
        for r in rows
    ]
    # Semantic angle overlap mirrors semantic fact overlap: same greedy rule
    # over candidate propositions, auditable next to the count range.
    angle_overlaps = []
    for other in rows[1:]:
        angle_overlaps.append(
            fact_overlap(
                baseline_angle_props(rows[0]),
                baseline_angle_props(other),
            )
        )
    zero_runs = [r["run_id"] for r in rows if r["stages"]["zero_yield"]]
    exec_fail_runs = [
        r["run_id"]
        for r in rows
        if any(
            r["stages"]["failure_taxonomy"].get(k)
            for k in (
                "model_call_failed",
                "rate_limited",
                "model_timeout",
                "empty_model_output",
                "no_json",
                "invalid_json",
                "no_bindable_fact",
            )
        )
    ]

    pair_classes = {}
    pairwise_overlaps = []
    baseline = rows[0]
    for r in rows[1:]:
        cls = classify_pair(baseline, r)
        pair_classes[cls] = pair_classes.get(cls, 0) + 1
        pairwise_overlaps.append(
            fact_overlap(
                baseline["stages"]["fact_extraction"]["fact_texts"],
                r["stages"]["fact_extraction"]["fact_texts"],
            )
        )
    n_pairs = max(len(rows) - 1, 0)

    # A catastrophic run is a zero-yield run that coexists with a same-input
    # run that DID produce facts (Part F definition; the zero side is the
    # failure, the producing side is the evidence it is catastrophic).
    produced = [
        r["run_id"]
        for r in rows
        if not r["stages"]["zero_yield"] and (r["stages"]["fact_extraction"]["facts"])
    ]
    catastrophic_runs = sorted(r["run_id"] for r in rows if r["stages"]["zero_yield"] and produced)

    return {
        "runs": len(rows),
        "outcome_distribution": outcomes,
        "readiness_distribution": outcomes,
        "topic_stability": {
            "topic_count_range": [min(topic_counts), max(topic_counts)] if topic_counts else [0, 0],
            "identical_segmentation_across_runs": seg_stable,
        },
        "fact_count_range": [min(fact_counts), max(fact_counts)] if fact_counts else [0, 0],
        "dropped_fact_count_range": [min(dropped_counts), max(dropped_counts)]
        if dropped_counts
        else [0, 0],
        "retained_fact_count_range": [min(retained_counts), max(retained_counts)]
        if retained_counts
        else [0, 0],
        "semantic_fact_overlap_mean": round(statistics.fmean(pairwise_overlaps), 3)
        if pairwise_overlaps
        else 1.0,
        "angle_count_range": [min(angle_counts), max(angle_counts)] if angle_counts else [0, 0],
        "selected_angle_count_range": [min(retained_angle_ids), max(retained_angle_ids)]
        if retained_angle_ids
        else [0, 0],
        "semantic_angle_overlap_mean": round(statistics.fmean(angle_overlaps), 3)
        if angle_overlaps
        else 1.0,
        "zero_yield_frequency": {
            "runs": len(zero_runs),
            "fraction": round(len(zero_runs) / len(rows), 3) if rows else 0.0,
            "run_ids": zero_runs,
        },
        "model_failure_frequency": {
            "runs": len(exec_fail_runs),
            "fraction": round(len(exec_fail_runs) / len(rows), 3) if rows else 0.0,
            "run_ids": exec_fail_runs,
        },
        "taxonomy_vs_first_run": pair_classes,
        "taxonomy_fraction": {k: round(v / n_pairs, 3) for k, v in pair_classes.items()}
        if n_pairs
        else {},
        "catastrophic_zero_yield_runs": catastrophic_runs,
        "catastrophic_zero_yield_fraction": round(
            (len(catastrophic_runs) / len(rows)) if rows else 0.0, 3
        ),
    }


def load_rows(out_dir=None, config_fp=None, video_id=None, mode=None):
    rows = []
    path = _runs_path(out_dir)
    if not path.exists():
        return rows
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if config_fp and row.get("config_fp") != config_fp:
            continue
        if video_id and row.get("video_id") != video_id:
            continue
        if mode and row.get("mode") != mode:
            continue
        rows.append(row)
    return rows


def corpus_summary(out_dir=None, config_fp=None):
    config_fp = config_fp or stability_version()
    rows = load_rows(out_dir, config_fp, mode="model")  # deterministic-mode rows never enter stats
    by_video = {}
    for row in rows:
        by_video.setdefault(row["video_id"], []).append(row)
    per_video = {vid: aggregate_video(vrows) for vid, vrows in sorted(by_video.items())}
    totals = {}
    catastrophic_total = 0
    for agg in per_video.values():
        for k, v in agg["taxonomy_fraction"].items():
            totals[k] = totals.get(k, 0.0) + v
        catastrophic_total += len(agg["catastrophic_zero_yield_runs"])
    n_videos = len(per_video)
    corpus_fractions = {k: round(v / n_videos, 3) for k, v in totals.items()} if n_videos else {}
    return {
        "config_fp": config_fp,
        "stability_config": stability_version(),
        "discovery_version": DISCOVERY_VERSION,
        "videos": per_video,
        "corpus_taxonomy_fraction": corpus_fractions,
        "catastrophic_zero_yield_total": catastrophic_total,
    }


def print_summary(summary):
    print(f"config_fp={summary['config_fp']} discovery={summary['discovery_version']}")
    for vid, agg in summary["videos"].items():
        print(f"\n== {vid} ==  runs={agg['runs']}")
        print(f"  outcomes: {agg['outcome_distribution']}")
        print(
            f"  fact_count_range: {agg['fact_count_range']}  dropped: {agg['dropped_fact_count_range']}"
        )
        print(f"  angle_count_range: {agg['angle_count_range']}")
        print(f"  semantic_fact_overlap_mean: {agg['semantic_fact_overlap_mean']}")
        print(f"  semantic_angle_overlap_mean: {agg['semantic_angle_overlap_mean']}")
        print(f"  topic_stability: {agg['topic_stability']}")
        print(f"  zero_yield: {agg['zero_yield_frequency']['runs']}/{agg['runs']}")
        print(f"  model_failures: {agg['model_failure_frequency']['runs']}/{agg['runs']}")
        print(f"  taxonomy(vs r001): {agg['taxonomy_vs_first_run']}")
        print(f"  CATASTROPHIC_ZERO_YIELD runs: {agg['catastrophic_zero_yield_runs']}")
    print(f"\ncorpus_taxonomy_fraction: {summary['corpus_taxonomy_fraction']}")
    print(f"catastrophic_zero_yield_total: {summary['catastrophic_zero_yield_total']}")


# ---------- optional Jev shadow (Part G/O; zero authority) ----------


def jev_shadow_relation(stages, doc):
    """SHADOW ONLY: pair the run's facts for semantic-relation judgment.

    Records full probabilities and a typed claim_relation; results land in the
    run row and cannot influence any production surface (Part G).
    """
    try:
        from editor_assistant.workflow import jev
    except ImportError:
        return None
    available, reason = jev.capability_status()
    if not available:
        return {"status": jev.JEV_CAPABILITY_UNAVAILABLE, "reason": reason}
    facts = stages["fact_extraction"]["fact_texts"]
    if len(facts) < 2:
        return {"status": "SKIPPED", "reason": "fewer than two facts to relate"}
    rows = []
    for i in range(min(len(facts) - 1, 6)):
        state = {"claim_a": facts[i], "claim_b": facts[i + 1]}
        questions = {
            "claim_relation": jev.question(
                jev.QUESTION_CHOICE,
                "What is the relation between claim A and claim B?",
                (
                    "SAME_CLAIM",
                    "OVERLAPPING_CLAIM",
                    "DIFFERENT_CLAIM",
                    "CONTRADICTORY_CLAIM",
                    "UNCLEAR",
                ),
            ),
        }
        try:
            record = jev.evaluate(state, questions)
        except Exception as exc:  # noqa: BLE001 - shadow failures never fatal
            rows.append({"status": "JEV_PROVIDER_ERROR", "reason": type(exc).__name__})
            break
        rows.append(
            {
                "status": "OK",
                "pair": [facts[i][:80], facts[i + 1][:80]],
                "claim_relation": (record.get("answers", {}).get("claim_relation") or {}).get(
                    "answer"
                ),
                "probabilities": (record.get("answers", {}).get("claim_relation") or {}).get(
                    "probabilities"
                ),
            }
        )
    return {"status": "OK", "rows": rows}


# ---------- CLI ----------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", help="video id or SRT path")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--suite", action="store_true", help="run the whole corpus")
    parser.add_argument("--list", action="store_true", help="list the corpus and exit")
    parser.add_argument("--check-determinism", action="store_true", help="Part D invariant check")
    parser.add_argument(
        "--dry-run", action="store_true", help="deterministic mode: zero model calls"
    )
    parser.add_argument("--summary", action="store_true", help="aggregate existing runs and exit")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--jev-shadow", action="store_true", help="optional Jev SHADOW comparison")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)

    if args.list:
        for vid, entry in CORPUS.items():
            exists = Path(entry["path"]).exists()
            print(f"{vid}\t{entry['character']}\t{'OK' if exists else 'MISSING'}\t{entry['path']}")
        return 0

    if args.check_determinism:
        results = check_determinism(out_dir)
        ok = all(r["status"] in ("IDENTICAL", "SKIPPED_MISSING_SRT") for r in results)
        for r in results:
            print(json.dumps(r, ensure_ascii=False))
        print("DETERMINISTIC_STAGE_STABILITY =", "PROVEN" if ok else "NOT_PROVEN")
        return 0 if ok else 1

    if args.summary:
        print_summary(corpus_summary(out_dir))
        return 0

    if not args.runs or args.runs < 1:
        parser.error("--runs must be >= 1")

    if args.suite:
        targets = [(vid, Path(e["path"])) for vid, e in CORPUS.items() if Path(e["path"]).exists()]
    elif args.input:
        vid, path, _character = resolve_input(args.input)
        targets = [(vid, path)]
    else:
        parser.error(
            "one of --input / --suite / --list / --check-determinism / --summary is required"
        )

    use_model = not args.dry_run
    config_fp = stability_version()
    already = done_run_ids(_runs_path(out_dir), config_fp)
    jev_fn = jev_shadow_relation if args.jev_shadow else None

    for video_id, path in targets:
        raw_srt, doc = load_document(video_id, path)
        completed = 0
        for i in range(1, args.runs + 1):
            run_id = f"{video_id}__r{i:03d}"
            if run_id in already:
                completed += 1
                continue
            row = run_once(
                video_id,
                doc,
                raw_srt,
                i,
                use_model=use_model,
                jev_shadow_fn=jev_fn,
                out_dir=out_dir,
            )
            already.add(run_id)
            completed += 1
            stages = row["stages"]
            print(
                f"{run_id}: outcome={stages['outcome']} facts={len(stages['fact_extraction']['facts'])} "
                f"angles={len(stages['angle_assessment']['candidates'])} "
                f"skips={stages['failure_taxonomy']['topic_skips']} latency={row['response']['latency_ms']}ms",
                flush=True,
            )
        print(f"{video_id}: {completed}/{args.runs} runs present (config {config_fp})")

    print()
    print_summary(corpus_summary(out_dir, config_fp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
