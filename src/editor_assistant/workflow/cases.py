"""M2.8/M2.9 editorial workflow cases: lineage, editor revisions, learning signal.

A case binds IdeaCard -> EvidencePacket -> VOICE/MODE -> draft (with lineage
and factual audit) -> editor final -> deterministic diff. The AI draft is
immutable: `record_editor_final` never mutates it, the pair is the learning
artifact. Only the editor can complete a case; the module has no publish
action of any kind.

Minimal LIVE-only feedback (M2.10): LIVE cases also record the editor's
`prefer_ai_start` verdict (YES/MIXED/NO). It is never asked of
GROUND_TRUTH_DRYRUN cases and is aggregated only for LIVE cases
(workflow_metrics keeps effort and feedback live-only even when live_only=False).
"""

from __future__ import annotations

import json
from pathlib import Path

from editor_assistant.workflow.diff import classify_diff, diff_draft_final

EDITING_WEIGHTS = ("LIGHT", "MODERATE", "HEAVY", "REWRITE", "REJECTED")
TIME_BUCKETS = ("<5 min", "5-15 min", "15-30 min", ">30 min")
EDITOR_OUTCOMES = ("ACCEPTED_FOR_EDIT", "REJECTED", "MIXED")
GATE_STATUSES = ("FACTUAL_GATE_PASS", "FACTUAL_GATE_REVIEW")

# M2.7-9 tracks (editor decision 2026-09-16): only LIVE_EDITORIAL_PILOT cases
# count toward time/adoption/workflow-usefulness metrics. GROUND_TRUTH_DRYRUN
# cases (AI draft vs the already-published article) are a factual/structural
# benchmark ONLY - recording effort metrics on them would fabricate savings.
TRACK_DRYRUN = "GROUND_TRUTH_DRYRUN"
TRACK_LIVE = "LIVE_EDITORIAL_PILOT"
TRACKS = (TRACK_DRYRUN, TRACK_LIVE)
PREFER_AI_START_VALUES = ("YES", "MIXED", "NO")

# M2R §23/§33: editor verdicts on the readiness layer's decisions. Persisted on
# finalized LIVE cases so newsworthiness thresholds and hook rules can later be
# calibrated from AGGREGATED editor corrections (never auto-learned).
READINESS_OUTCOMES = ("ANGLE_ACCEPTED", "ANGLE_CHANGED", "NO_STORY_CONFIRMED", "RESEARCH_REQUESTED")
_DRYRUN_FORBIDDEN_FIELDS = ("time_saved_estimate", "editing_weight", "editor_outcome")
_CHERNOMORIE_HOST = "chernomorie-bg.com"
CIRCULAR_NOTE = (
    "Published Chеrnomorie article must never be used as factual "
    "input for its own pilot draft (no circular evaluation)."
)


_DEFAULT_VOICE = "VOICE_HOUSE"
_OPT_IN_VOICE = "VOICE_DESISLAVA_RECENT"


class CaseError(ValueError):
    pass


def is_chernomorie_source(source_url):
    """True if the URL points at a published Chеrnomorie article."""
    return _CHERNOMORIE_HOST in (source_url or "")


def open_case(
    *,
    case_id,
    idea_id,
    evidence_id,
    draft,
    voice=_DEFAULT_VOICE,
    mode=None,
    mode_suggested=None,
    suggestion_reason="",
    factual_gate="FACTUAL_GATE_PASS",
    style_example_ids=(),
    retrieval_reason="",
    fallback_used=False,
    prompt_version="",
    audit=None,
    track=TRACK_LIVE,
    source_url="",
):
    """Open a case from an already-grounded draft (M2.3B path output).

    track: GROUND_TRUTH_DRYRUN (benchmark vs the published article) or
    LIVE_EDITORIAL_PILOT (fresh unpublished lead; the only track that feeds
    effort/adoption metrics). LIVE cases must not use a published Chеrnomorie
    article as factual input (circular evaluation guard).
    """
    if voice not in (_DEFAULT_VOICE, _OPT_IN_VOICE):
        raise CaseError(f"unknown voice: {voice!r}")
    if factual_gate not in GATE_STATUSES:
        raise CaseError(f"bad factual gate status: {factual_gate!r}")
    if track not in TRACKS:
        raise CaseError(f"bad track: {track!r}")
    if track == TRACK_LIVE and is_chernomorie_source(source_url):
        raise CaseError(CIRCULAR_NOTE)
    lin = draft.get("lineage", {})
    mode = mode or lin.get("mode_id")
    if not mode:
        raise CaseError("mode required (draft lineage or explicit)")
    return {
        "case_id": case_id,
        "idea_id": idea_id,
        "evidence_id": evidence_id,
        "track": track,
        "source_url": source_url,
        "draft_id": lin.get("draft_id", ""),
        "voice_selected": voice,
        "mode_suggested": mode_suggested or "",
        "mode_selected": mode,
        "mode_suggestion_reason": suggestion_reason or "",
        "mode_changed": bool(mode_suggested and mode_suggested != mode),
        "draft_headline": draft["draft"]["headline"],
        "final_headline": "",
        "draft_text": draft["draft"]["body"],
        "final_text": "",
        "editor_outcome": "",
        "editing_weight": "",
        "time_saved_estimate": "",
        "prefer_ai_start": "",
        "published_or_ready": "",
        "notes": "",
        "factual_gate": factual_gate,
        "style_example_ids": list(style_example_ids or lin.get("style_example_ids", [])),
        "retrieval_reason": retrieval_reason,
        "fallback_used": bool(fallback_used),
        "prompt_version": prompt_version or lin.get("prompt_version", ""),
        "audit": audit
        if audit is not None
        else {"semantic": draft.get("semantic", {}), "lexical": draft.get("audit")},
        "lineage": dict(lin),
    }


def record_editor_final(
    case,
    *,
    final_headline,
    final_text,
    editor_outcome,
    editing_weight,
    time_saved_estimate="",
    prefer_ai_start="",
    published_or_ready="",
    notes="",
    idea_status="",
    readiness_outcome="",
    readiness_note="",
    _published_reference=False,
):
    """Editor completes the case. Never mutates the AI draft fields.

    GROUND_TRUTH_DRYRUN cases refuse editor-supplied effort/adoption fields
    entirely: their value is the AI-draft-vs-published-article benchmark, and
    recording time/weight/adoption on pre-written material would fabricate
    metrics. (_published_reference=True is internal CLI bookkeeping for
    storing the published article - not an editor effort claim.)

    LIVE cases may also record the minimal workflow feedback signal
    `prefer_ai_start` (YES/MIXED/NO): did the editor prefer starting from the
    AI draft? Never requested for GROUND_TRUTH_DRYRUN cases (a dry-run has no
    editorial start-from-draft experience to report) and refused there,
    exactly like the other effort/adoption fields.

    M2R (§23/§33): LIVE cases also accept the readiness learning verdict
    `readiness_outcome` (READINESS_OUTCOMES) confirming or correcting the
    layer's decision, plus an optional free-text `readiness_note` - persisted
    for future threshold/hook learning, never applied automatically.
    """
    if final_text.strip() and editor_outcome not in EDITOR_OUTCOMES and not _published_reference:
        raise CaseError(f"bad editor_outcome: {editor_outcome!r}")
    if not _published_reference and editing_weight not in EDITING_WEIGHTS:
        raise CaseError(f"bad editing_weight: {editing_weight!r}")
    if not _published_reference and time_saved_estimate and time_saved_estimate not in TIME_BUCKETS:
        raise CaseError(f"bad time_saved_estimate: {time_saved_estimate!r} (use {TIME_BUCKETS})")
    prefer_ai_start = (prefer_ai_start or "").strip()
    if prefer_ai_start and prefer_ai_start not in PREFER_AI_START_VALUES:
        raise CaseError(f"bad prefer_ai_start: {prefer_ai_start!r} (use {PREFER_AI_START_VALUES})")
    readiness_outcome = (readiness_outcome or "").strip()
    readiness_note = (readiness_note or "").strip()
    if readiness_note and not readiness_outcome:
        raise CaseError("readiness_note requires readiness_outcome (the verdict it explains)")
    if readiness_outcome and readiness_outcome not in READINESS_OUTCOMES:
        raise CaseError(f"bad readiness_outcome: {readiness_outcome!r} (use {READINESS_OUTCOMES})")
    if readiness_outcome and case.get("track") != TRACK_LIVE:
        raise CaseError(
            f"{case['case_id']}: readiness_outcome is a LIVE-case learning signal "
            f"(case track is {case.get('track')!r})"
        )
    if (
        case.get("track") == TRACK_DRYRUN
        and not _published_reference
        and (
            editing_weight not in (None, "", "NONE")
            or time_saved_estimate
            or editor_outcome
            or prefer_ai_start
        )
    ):
        raise CaseError(
            f"{case['case_id']} is {TRACK_DRYRUN}: effort/adoption fields "
            "(time_saved_estimate, editing_weight, editor_outcome, prefer_ai_start) "
            "are not valid; use the AI-vs-published benchmark instead"
        )
    case["final_headline"] = final_headline
    case["final_text"] = final_text
    case["editor_outcome"] = editor_outcome
    case["editing_weight"] = editing_weight
    case["time_saved_estimate"] = time_saved_estimate
    case["prefer_ai_start"] = prefer_ai_start
    case["published_or_ready"] = published_or_ready
    case["notes"] = notes
    case["readiness_outcome"] = readiness_outcome
    case["readiness_note"] = readiness_note
    case["diff"] = diff_draft_final(
        case["draft_headline"], case["draft_text"], final_headline, final_text
    )
    case["revision_classification"] = classify_diff(case["diff"])
    case["idea_status"] = idea_status
    return case


def lineage_problems(cases, ideas, evidence_rows=()):
    """Check the LIVE lineage is 1:1: case <-> idea <-> evidence.

    Returns a list of human-readable problems (empty list = clean).
    Guards the real collision found in the pilot: two cases created in the same
    second shared one idea_id, so a case could not be traced to its own lead.
    """
    problems = []
    by_idea = {i["idea_id"]: i for i in ideas}
    live = [c for c in cases if c.get("track") == TRACK_LIVE]
    seen_idea, seen_evidence = {}, {}
    for case in live:
        cid, idea_id = case["case_id"], case.get("idea_id", "")
        if not idea_id:
            problems.append(f"{cid}: no idea_id")
            continue
        if idea_id in seen_idea:
            problems.append(f"{cid}: idea_id {idea_id} already used by {seen_idea[idea_id]}")
        seen_idea[idea_id] = cid
        idea = by_idea.get(idea_id)
        if idea is None:
            problems.append(f"{cid}: no idea card for {idea_id}")
        else:
            if case.get("source_url") and idea.get("source_url") != case["source_url"]:
                problems.append(f"{cid}: idea card source_url does not match the case")
            if case.get("idea_status") and idea["status"] != case["idea_status"]:
                problems.append(f"{cid}: idea status drifted from the case record")
        ev = case.get("evidence_id", "")
        if not ev:
            problems.append(f"{cid}: no evidence_id")
        elif ev in seen_evidence:
            problems.append(f"{cid}: evidence_id {ev} already used by {seen_evidence[ev]}")
        else:
            seen_evidence[ev] = cid
    by_evidence = {r["evidence_id"]: r for r in evidence_rows}
    for case in live:
        row = by_evidence.get(case.get("evidence_id"))
        if row is None:
            problems.append(f"{case['case_id']}: no evidence row for {case.get('evidence_id')}")
        elif row.get("idea_id") != case.get("idea_id"):
            problems.append(f"{case['case_id']}: evidence row points at idea {row.get('idea_id')}")
    for ev, row in by_evidence.items():
        if not any(c.get("evidence_id") == ev for c in live):
            problems.append(f"{ev}: evidence row without a LIVE case")
    return problems


def save_cases(cases, path):
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def read_cases(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]


def load_revisions(path):
    """Read editor-completed cases with paired artifacts (draft kept intact)."""
    out = []
    for case in read_cases(path):
        if not (case.get("final_text") and case.get("draft_text")):
            continue
        if case["draft_text"] == case["final_text"]:
            raise CaseError(f"{case['case_id']}: final identical to draft - draft was overwritten?")
        out.append(case)
    return out


def aggregate_patterns(cases, *, min_count=5):
    """Aggregate recurring correction patterns (>= min_count occurrences)."""
    patterns = {}
    for case in cases:
        counts = (case.get("revision_classification") or {}).get("counts", {})
        for cat, count in counts.items():
            if not count:
                continue
            entry = patterns.setdefault(cat, {"count": 0, "cases": []})
            entry["count"] += count
            if case["case_id"] not in entry["cases"]:
                entry["cases"].append(case["case_id"])
    recurring = {cat: e for cat, e in patterns.items() if e["count"] >= min_count}
    return {"patterns": patterns, "recurring_above_threshold": recurring, "threshold": min_count}


def workflow_metrics(cases, *, live_only=True):
    """M2.7-9 §22 real-world metrics.

    live_only (default): only LIVE_EDITORIAL_PILOT cases count toward
    time/editing-weight/adoption metrics — GROUND_TRUTH_DRYRUN cases are a
    benchmark and would fabricate savings. Pass live_only=False to see raw
    per-track counts.
    """
    cases = list(cases)
    all_cases = list(cases)
    if live_only:
        cases = [c for c in cases if c.get("track") == TRACK_LIVE]
        effort_cases = cases
    else:
        effort_cases = list(cases)
    done = [c for c in effort_cases if c.get("final_text")]
    if not done:
        return {"total_cases": len(cases), "completed": 0}
    weights = {w: sum(1 for c in done if c["editing_weight"] == w) for w in EDITING_WEIGHTS}
    return {
        "total_cases": len(cases),
        "completed": len(done),
        "tracks": {t: sum(1 for c in all_cases if c.get("track") == t) for t in TRACKS},
        "effort_basis": TRACK_LIVE if live_only else "all-cases (incl. dryrun)",
        "editor_outcomes": {
            o: sum(1 for c in done if c["editor_outcome"] == o) for o in EDITOR_OUTCOMES
        },
        "editing_weight": weights,
        "light_or_moderate": weights["LIGHT"] + weights["MODERATE"],
        "headline_accepted_unchanged": sum(1 for c in done if not c["diff"]["headline_changed"]),
        "headline_modified": sum(1 for c in done if c["diff"]["headline_changed"]),
        "mode_changed_by_editor": sum(1 for c in cases if c.get("mode_changed")),
        "factual_gate": {
            "pass": sum(1 for c in cases if c.get("factual_gate") == "FACTUAL_GATE_PASS"),
            "review": sum(1 for c in cases if c.get("factual_gate") == "FACTUAL_GATE_REVIEW"),
        },
        "editor_fact_corrections": sum(
            (c.get("revision_classification") or {}).get("counts", {}).get("FACT", 0) for c in done
        ),
        "semantic_gate_catches": sum(
            1
            for c in cases
            if (c.get("audit") or {}).get("semantic", {}).get("n_unsupported", 0) > 0
        ),
        "time_saved_estimates": {
            t: sum(1 for c in done if c["time_saved_estimate"] == t) for t in TIME_BUCKETS
        },
        "voice_usage": {
            v: sum(1 for c in cases if c.get("voice_selected") == v)
            for v in (_DEFAULT_VOICE, _OPT_IN_VOICE)
        },
        "desislava_case_count": sum(1 for c in cases if c.get("voice_selected") == _OPT_IN_VOICE),
        "start_from_draft_yes": sum(1 for c in done if c["editor_outcome"] == "ACCEPTED_FOR_EDIT"),
        "start_from_draft_no": sum(1 for c in done if c["editor_outcome"] == "REJECTED"),
        "start_from_draft_mixed": sum(1 for c in done if c["editor_outcome"] == "MIXED"),
        # M2R §23/§33: readiness learning verdicts (LIVE-only, aggregated only;
        # no automatic threshold/profile mutation is derived from them here).
        "readiness_outcomes": {
            o: sum(1 for c in done if c.get("readiness_outcome") == o) for o in READINESS_OUTCOMES
        },
        "readiness_outcome_recorded": sum(1 for c in done if c.get("readiness_outcome")),
    }
