"""M2.7-9 minimal editor surface (CLI).

Commands:
  status                         case/artifact overview (by track)
  show <draft_key>               print a grounded draft
  ideas [path]                   list idea cards
  new-idea FILE                  register idea cards from a JSON file
  request-draft <idea_id>        explicit editor trigger (NEW/FOLLOW_UP only)
  seed-cases                     open TRACK A cases from frozen M2.3B drafts
                                 (GROUND_TRUTH_DRYRUN - benchmark only)
  live-evidence <id> FILE        TRACK B: upstream lead -> IdeaCard+Packet
  live-case <id> --idea ID       TRACK B: voice/mode selection (explicit step)
  live-generate <id>             TRACK B: fresh grounded draft (M2.3B path)
  dryrun-benchmark               Track A: AI draft vs published article
  review [outdir]                write editor review files (draft + scorecard)
  finalize <case_id> FILE        record the editor final from a JSON file
  report                         real-world metrics (LIVE cases only)
  youtube-intake <url>           M3B: one YouTube URL -> transcript -> discovery
  youtube-batch add|run|status|reset
                                 M3B.1: the queue + the cron entry point
                                 (`run` is invoked by cron; no daemon here)
  workbench                      M3A: local browser Editor Workbench (127.0.0.1)

There is deliberately NO publish command: the workflow ends at the editor.
Track A (dry-run vs published articles) never feeds time/weight/adoption.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from editor_assistant.workflow import angles, live_store
from editor_assistant.workflow import cases as cases_mod
from editor_assistant.workflow import live as live_mod
from editor_assistant.workflow import readiness as readiness_mod
from editor_assistant.workflow import transcriber as transcriber_mod
from editor_assistant.workflow.benchmark import benchmark_report
from editor_assistant.workflow.cases import TRACK_DRYRUN, TRACK_LIVE
from editor_assistant.workflow.ideas import (
    make_idea,
    read_ideas,
    request_draft,
    save_ideas,
)
from editor_assistant.workflow.modes import suggest_mode

ROOT = Path(__file__).resolve().parents[3]
VAR = ROOT / "var"
CASES_PATH = VAR / "editorial_workflow" / "cases.jsonl"
IDEAS_PATH = VAR / "editorial_workflow" / "ideas.jsonl"
DRAFTS_PATH = VAR / "draft_experiment" / "drafts.jsonl"
PACKETS_PATH = VAR / "draft_experiment" / "evidence_packets.jsonl"
LIVE_EVIDENCE_PATH = VAR / "editorial_workflow" / "live_evidence.jsonl"
LIVE_DRAFTS_PATH = VAR / "editorial_workflow" / "live_drafts.jsonl"


def _load_drafts():
    rows = [json.loads(line) for line in DRAFTS_PATH.open(encoding="utf-8") if line.strip()]
    return (
        {r["evidence_id"]: r for r in rows if r.get("lineage", {}).get("attempt") != "variant"}
        if rows and "attempt" in rows[0]
        else {r["evidence_id"]: r for r in rows}
    )


def _primary_rows():
    """M2.3B stored primary drafts per evidence id (variant rows excluded)."""
    rows = [json.loads(line) for line in DRAFTS_PATH.open(encoding="utf-8") if line.strip()]
    primary = {}
    for r in rows:
        ev = r["evidence_id"]
        if ev.endswith("B") or r.get("blind_group"):
            continue
        primary.setdefault(ev, r)
    return primary


def cmd_status(_args):
    packets = [json.loads(l) for l in PACKETS_PATH.open(encoding="utf-8") if l.strip()]
    drafts = _primary_rows()
    ideas = read_ideas(IDEAS_PATH) if IDEAS_PATH.exists() else []
    cases = cases_mod.read_cases(CASES_PATH) if CASES_PATH.exists() else []
    print(f"evidence packets : {len(packets)}")
    print(f"grounded drafts  : {len(drafts)} (frozen M2.3B path)")
    print(f"idea cards       : {len(ideas)}")
    print(
        f"cases            : {len(cases)} "
        f"({sum(1 for c in cases if c.get('final_text'))} editor-finalized)"
    )
    for t in (TRACK_DRYRUN, TRACK_LIVE):
        sub = [c for c in cases if c.get("track", TRACK_LIVE) == t]
        print(f"  {t:24s}: {len(sub)}")
    for c in cases:
        state = "FINAL" if c.get("final_text") else "awaiting editor"
        print(
            f"  {c['case_id']:8s} [{(c.get('track') or '?')[:4]}] "
            f"{c['voice_selected']:24s} {c['mode_selected']:22s} {state}"
        )


def cmd_show(args):
    row = _primary_rows().get(args.draft_key.upper())
    if not row:
        sys.exit(f"no primary draft for {args.draft_key}")
    d = row["draft"]
    print(f"{row['voice']} + {row['mode']} | draft_id {row['lineage']['draft_id']}")
    print(f"headline: {d['headline']}\n")
    print(d["body"])


def cmd_ideas(args):
    ideas = (
        read_ideas(args.path)
        if args.path
        else (read_ideas(IDEAS_PATH) if IDEAS_PATH.exists() else [])
    )
    if not ideas:
        print("no idea cards yet - use 'new-idea FILE'")
        return
    for i in ideas:
        print(f"{i['idea_id']:10s} [{i['status']:15s}] {i['title'][:60]}")
        print(f"            {i['what_changed'][:80]}")


def cmd_new_idea(args):
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else [payload]
    ideas = [make_idea(**item) for item in items]
    existing = read_ideas(IDEAS_PATH) if IDEAS_PATH.exists() else []
    known = {i["idea_id"] for i in existing}
    fresh = [i for i in ideas if i["idea_id"] not in known]
    save_ideas(existing + fresh, IDEAS_PATH)
    print(f"registered {len(fresh)} idea card(s) -> {IDEAS_PATH}")


def cmd_request_draft(args):
    ideas = read_ideas(IDEAS_PATH)
    for i in ideas:
        if i["idea_id"] == args.idea_id:
            request_draft(i)
            save_ideas(ideas, IDEAS_PATH)
            print(f"{args.idea_id}: status -> DRAFT_REQUESTED (explicit editor trigger)")
            return
    sys.exit(f"unknown idea_id: {args.idea_id}")


def _live_rows():
    """Canonical store reader (workflow/live_store.py)."""
    return live_store.read_live_evidence(LIVE_EVIDENCE_PATH)


def _save_live_row(row):
    """Canonical store writer (workflow/live_store.py): atomic, deterministic."""
    live_store.save_live_evidence_row(row, LIVE_EVIDENCE_PATH)


def _idea_by_id(idea_id, ideas):
    for i in ideas:
        if i["idea_id"] == idea_id:
            return i
    sys.exit(f"unknown idea_id: {idea_id}")


def cmd_live_evidence(args):
    """Record an upstream lead: idea card + EvidencePacket (M2.3B contract)."""
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    idea = live_mod.new_idea(
        source_type=payload.get("source_type", "upstream_press_release"),
        source_url=payload.get("source_url", ""),
        title=payload["title"],
        what_changed=payload["what_changed"],
        why_now=payload.get("why_now", ""),
        location=payload.get("location", ""),
        possible_angle=payload.get("possible_angle", ""),
    )
    packet = live_mod.build_live_packet(
        idea,
        record=payload["record"],
        evidence_id=args.evidence_id,
        observed_at=payload.get("observed_at"),
        bundle_path=payload.get("source_bundle"),
    )
    _save_live_row(
        {
            "evidence_id": args.evidence_id,
            "idea_id": idea["idea_id"],
            "packet": packet,
            "observed_at": packet["observed_at"],
        }
    )
    existing = read_ideas(IDEAS_PATH) if IDEAS_PATH.exists() else []
    known = {i["idea_id"] for i in existing}
    save_ideas(existing + ([idea] if idea["idea_id"] not in known else []), IDEAS_PATH)
    suggestion = suggest_mode(packet)
    print(f"{idea['idea_id']} + {args.evidence_id} recorded ({len(packet['facts'])} facts)")
    print(
        f"next: live-case {args.evidence_id} --idea {idea['idea_id']} "
        f"(suggested mode: {suggestion['suggested_mode']} — {suggestion['reason']})"
    )


def cmd_live_angles(args):
    """Persist research/editor judgments; no article or model call on rejection."""
    rows = _live_rows()
    if args.evidence_id not in rows:
        sys.exit(f"unknown live evidence_id: {args.evidence_id}")
    cases = cases_mod.read_cases(CASES_PATH) if CASES_PATH.exists() else []
    if any(c["evidence_id"] == args.evidence_id for c in cases):
        sys.exit("case already open; use new evidence for a new editorial assessment")
    row = rows[args.evidence_id]
    candidates = json.loads(Path(args.file).read_text(encoding="utf-8"))
    override_reason = getattr(args, "override_reason", None)
    if getattr(args, "override", None):
        if not args.select:
            sys.exit("--override requires --select <angle_id> (recorded, never silent)")
        if not (override_reason or "").strip():
            sys.exit("--override requires --override-reason (M2R §32: recorded, never silent)")
    assessment = angles.assess_angles(
        row["packet"],
        candidates,
        editor_selection=getattr(args, "select", None),
        editor_override_reason=override_reason if getattr(args, "override", None) else None,
    )
    row["packet"]["editorial_assessment"] = assessment
    row.pop("prepared", None)
    ideas = read_ideas(IDEAS_PATH)
    idea = _idea_by_id(row["idea_id"], ideas)
    idea["status"] = angles.NO_ANGLE if assessment["status"] == angles.NO_ANGLE else "FOLLOW_UP"
    save_ideas(ideas, IDEAS_PATH)
    _save_live_row(row)
    print(json.dumps(assessment, ensure_ascii=False, indent=2))


def cmd_live_case(args):
    """Prepare a LIVE case: voice/mode selection + explicit trigger check."""
    rows = _live_rows()
    if args.evidence_id not in rows:
        sys.exit(f"unknown live evidence_id: {args.evidence_id}")
    row = rows[args.evidence_id]
    ideas = read_ideas(IDEAS_PATH)
    if args.idea != row["idea_id"]:
        sys.exit("idea does not belong to this evidence packet")
    idea = _idea_by_id(args.idea, ideas)
    if idea["status"] == angles.NO_ANGLE:
        print(f"{args.evidence_id}: {angles.NO_ANGLE}; no article")
        return
    if idea["status"] not in ("NEW", "FOLLOW_UP", "DRAFT_REQUESTED"):
        sys.exit(f"idea {idea['idea_id']} status {idea['status']!r} cannot be drafted")
    prepared = live_mod.live_case_request(
        idea,
        row["packet"],
        voice=args.voice,
        mode=args.mode or live_mod.modes_mod.suggest_mode(row["packet"])["suggested_mode"]
        if args.mode is None
        else args.mode,
    )
    save_ideas(ideas, IDEAS_PATH)
    row["prepared"] = prepared
    _save_live_row(row)
    if prepared.get("status") == angles.NO_ANGLE:
        print(f"{args.evidence_id}: {angles.NO_ANGLE}: {prepared['reason']}")
        return
    print(
        f"{args.evidence_id}: prepared voice={prepared['voice']} mode={prepared['mode']} "
        f"(suggested_by_tool={prepared['mode_suggested']})"
    )
    print(f"next: live-generate {args.evidence_id}  (explicit editor trigger)")


def cmd_live_readiness(args):
    """M2R: readiness decision; targeted research rounds; editor overrides.

    Read-only by default (prints the readiness record). --round registers one
    targeted enrichment round (max 2, §13); --mark-* records the decision
    after the loop; --override records an explicit editor decision (§32).
    """
    rows = _live_rows()
    if args.evidence_id not in rows:
        sys.exit(f"unknown live evidence_id: {args.evidence_id}")
    row = rows[args.evidence_id]
    packet = row["packet"]
    marks = [
        k
        for k in ("mark_sufficient", "mark_insufficient", "mark_editor_decision")
        if getattr(args, k)
    ]
    if len(marks) > 1:
        sys.exit("choose at most one --mark-* decision")
    if marks and getattr(args, "override", None):
        sys.exit("--mark-* and --override are mutually exclusive")
    if args.round:
        payload = (
            json.loads(Path(args.round_file).read_text(encoding="utf-8")) if args.round_file else {}
        )
        if not payload.get("missing_dimensions") or not payload.get("research_questions"):
            sys.exit(
                "--round needs {missing_dimensions, research_questions} "
                "(inline or via --round-file); gap-driven, not site-specific"
            )
        record = readiness_mod.register_research_round(
            row.setdefault("readiness_rounds", {}),
            missing_dimensions=payload["missing_dimensions"],
            research_questions=payload["research_questions"],
            sources=payload.get("sources", ()),
        )
        row["readiness_rounds"] = record
        _save_live_row(row)
        rounds = record["targeted_research_rounds"]
        print(
            f"{args.evidence_id}: targeted research round {rounds}/"
            f"{readiness_mod.MAX_RESEARCH_ROUNDS} registered"
        )
        return
    readiness = live_mod.live_readiness(packet, mode=args.mode, editor_override=args.override)
    if marks:
        decision = {
            "mark_sufficient": readiness_mod.SUFFICIENT,
            "mark_insufficient": readiness_mod.INSUFFICIENT,
            "mark_editor_decision": readiness_mod.EDITOR_DECISION,
        }[marks[0]]
        if not (args.reason or "").strip():
            sys.exit("--mark-* requires --reason (decisions must be inspectable)")
        readiness = readiness_mod.apply_editor_override(
            readiness,
            action="FORCE_DRAFT"
            if decision == readiness_mod.SUFFICIENT
            else "REQUEST_MORE_RESEARCH"
            if decision == readiness_mod.EDITOR_DECISION
            else "REJECT_STORY",
            reason=args.reason,
        )
        readiness["post_loop_decision"] = decision
    row["readiness"] = readiness
    _save_live_row(row)
    print(
        json.dumps(
            {k: v for k, v in readiness.items() if k != "assessment"}, ensure_ascii=False, indent=2
        )
    )


def cmd_live_generate(args):
    """Fresh grounded draft via the proven M2.3B path (requires API key)."""
    rows = _live_rows()
    if args.evidence_id not in rows:
        sys.exit(f"unknown live evidence_id: {args.evidence_id}")
    row = rows[args.evidence_id]
    idea = _idea_by_id(row["idea_id"], read_ideas(IDEAS_PATH))
    assessment = angles.check_angle_gate({**row["packet"], "source_type": idea["source_type"]})
    if assessment and assessment["status"] == angles.NO_ANGLE:
        print(f"{args.evidence_id}: {angles.NO_ANGLE}: {assessment['reason']}")
        return
    prepared = row.get("prepared") or sys.exit(f"{args.evidence_id}: run 'live-case' first")
    if prepared.get("mode_suggested"):
        sys.exit(
            "editor must confirm or override the suggested mode first: run "
            f"'live-case {args.evidence_id} --idea ... --mode <MODE>'"
        )
    if getattr(args, "force_reason", None) and not args.force_draft:
        sys.exit("--force-reason requires --force-draft")
    if args.force_draft and not (args.force_reason or "").strip():
        sys.exit("--force-draft requires --force-reason (M2R §32: recorded, never silent)")
    cases = cases_mod.read_cases(CASES_PATH) if CASES_PATH.exists() else []
    case_id = getattr(args, "case_id", None)
    if any(c["evidence_id"] == args.evidence_id and c.get("track") == TRACK_LIVE for c in cases):
        sys.exit(f"{args.evidence_id}: LIVE case already open; draft/final are immutable")
    used_ids = {c["case_id"] for c in cases}
    if case_id in used_ids:
        sys.exit(f"{case_id}: case ID already used")
    if not case_id:
        n = 1
        while f"LIV-{n:02d}" in used_ids:
            n += 1
        case_id = f"LIV-{n:02d}"
    result = live_mod.live_generate_draft(
        row["packet"],
        voice=prepared["voice"],
        mode=prepared["mode"],
        api_key=args.api_key,
        force_draft=args.force_draft,
        editor_override_reason=args.force_reason,
    )
    if result.get("status") in (angles.NO_ANGLE, readiness_mod.RESEARCH_MORE):
        print(f"{args.evidence_id}: {result['status']}: {result['reason']}")
        return
    store = {
        "evidence_id": args.evidence_id,
        "idea_id": prepared["idea_id"],
        "draft": result["draft"],
        "lineage": result["lineage"],
        "lexical": result["lexical"],
        "semantic": result["semantic"],
        "factual_gate": result["factual_gate"],
        "readiness": result["readiness"],
        "voice": prepared["voice"],
        "mode": prepared["mode"],
        "mode_suggested_by_tool": prepared["mode_suggested"],
        "retrieval": {k: v for k, v in result["retrieval"].items() if k != "examples"},
        "retrieval_example_ids": [e["article_id"] for e in result["retrieval"]["examples"]],
    }
    LIVE_DRAFTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LIVE_DRAFTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(store, ensure_ascii=False, sort_keys=True) + "\n")
    case = cases_mod.open_case(
        case_id=case_id,
        idea_id=prepared["idea_id"],
        evidence_id=args.evidence_id,
        draft=store,
        voice=prepared["voice"],
        mode=prepared["mode"],
        mode_suggested=prepared.get("suggested_mode"),
        suggestion_reason=prepared.get("suggestion_reason", ""),
        factual_gate=store["factual_gate"],
        prompt_version=store["lineage"]["prompt_version"],
        audit={"semantic": store["semantic"], "lexical": store["lexical"]},
        track=TRACK_LIVE,
        source_url=row["packet"].get("source_url", ""),
    )
    cases.append(case)
    cases_mod.save_cases(cases, CASES_PATH)
    print(f"case {case['case_id']} opened (LIVE_EDITORIAL_PILOT)")
    gate = store["factual_gate"]
    print(f"{args.evidence_id}: draft {store['lineage']['draft_id']} | gate: {gate}")
    print(f"headline: {store['draft']['headline']}")
    if gate == "FACTUAL_GATE_REVIEW":
        print("REVIEW required before presenting the draft (M2.3B §10 policy).")


def cmd_lineage_check(_args):
    """Prove the LIVE lineage is 1:1 (case <-> idea <-> evidence)."""
    cases = cases_mod.read_cases(CASES_PATH) if CASES_PATH.exists() else []
    ideas = read_ideas(IDEAS_PATH) if IDEAS_PATH.exists() else []
    problems = cases_mod.lineage_problems(cases, ideas, list(_live_rows().values()))
    if problems:
        for problem in problems:
            print(f"PROBLEM: {problem}")
        sys.exit(1)
    n = sum(1 for c in cases if c.get("track") == TRACK_LIVE)
    print(f"lineage OK: {n} LIVE cases, each with its own idea card and evidence row")


def cmd_dryrun_benchmark(_args):
    """Track A: AI draft vs published article (benchmark only)."""
    out = benchmark_report(CASES_PATH)
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))


def cmd_seed_cases(args):
    """Open TRACK A cases from frozen M2.3B drafts (GROUND_TRUTH_DRYRUN)."""
    packets = {
        p["evidence_id"]: p
        for p in (json.loads(l) for l in PACKETS_PATH.open(encoding="utf-8") if l.strip())
    }
    primary = _primary_rows()
    cases = cases_mod.read_cases(CASES_PATH) if CASES_PATH.exists() else []
    existing = {c["evidence_id"] for c in cases}
    for idx, (ev, row) in enumerate(sorted(primary.items()), start=1):
        packet = packets[ev]
        if ev in existing:
            # legacy case (pre-tracks): reclassify in place as dry-run benchmark
            for c in cases:
                if c["evidence_id"] == ev and not c.get("track"):
                    c["track"] = TRACK_DRYRUN
                    c["source_url"] = packet.get("source_url", "")
                    c["benchmark_note"] = (
                        "GROUND_TRUTH_DRYRUN: benchmark AI draft vs the "
                        "published article only - excluded from time/"
                        "weight/adoption metrics"
                    )
            continue
        packet = packets[ev]
        suggestion = suggest_mode(packet)
        case = cases_mod.open_case(
            case_id=f"WFX-{idx:02d}",
            idea_id=f"IDEA-{ev}",
            evidence_id=ev,
            draft=row,
            voice=row["voice"],
            mode=row["mode"],
            mode_suggested=suggestion["suggested_mode"],
            factual_gate="FACTUAL_GATE_PASS" if row["semantic"]["pass"] else "FACTUAL_GATE_REVIEW",
            prompt_version=row["lineage"].get("prompt_version", ""),
            audit={"semantic": row["semantic"], "lexical": row.get("audit")},
            track=TRACK_DRYRUN,
            source_url=packet.get("source_url", ""),
        )
        case["benchmark_note"] = (
            "GROUND_TRUTH_DRYRUN: benchmark AI draft vs the "
            "published article only - excluded from time/"
            "weight/adoption metrics"
        )
        case["mode_suggestion_reason"] = suggestion["reason"]
        cases.append(case)
    cases_mod.save_cases(cases, CASES_PATH)
    print(
        f"cases -> {CASES_PATH} ({len(cases)} total, mode suggestions stored, editor override allowed)"
    )


def cmd_review(args):
    outdir = Path(args.outdir) if args.outdir else VAR / "editorial_workflow" / "review"
    outdir.mkdir(parents=True, exist_ok=True)
    for c in cases_mod.read_cases(CASES_PATH):
        dryrun = c.get("track") == TRACK_DRYRUN
        lines = [
            f"# Case {c['case_id']} — {c['evidence_id']}",
            "",
            f"- track: **{c.get('track')}**"
            + (
                " (benchmark only — NOT part of time/weight/adoption metrics)"
                if dryrun
                else " (LIVE pilot — the metrics track)"
            ),
            f"- lineage: idea `{c['idea_id']}` -> evidence `{c['evidence_id']}` -> draft `{c['draft_id']}`",
            f"- voice: **{c['voice_selected']}** (HOUSE is default; DESISLAVA_RECENT is opt-in)",
            (
                "- mode: suggested `{}` -> selected `{}` (override allowed; reason: {})".format(
                    c["mode_suggested"] or "(none)",
                    c["mode_selected"],
                    c.get("mode_suggestion_reason", ""),
                )
            ),
            f"- factual gate: **{c['factual_gate']}**",
            "",
            f"## AI DRAFT (immutable — headline: {c['draft_headline']})",
            "",
            c["draft_text"],
            "",
        ]
        if dryrun:
            lines += [
                "## PUBLISHED ARTICLE REFERENCE (Track A benchmark)",
                "",
                "Paste the actually-published article for this source —",
                "the deterministic diff compares AI draft vs published output.",
                "Effort metrics are NOT recorded for this case.",
                "",
                "```yaml",
                "published_headline:",
                "published_text: |",
                "  <paste the published article text here>",
                "notes: ''",
                "```",
                "",
            ]
        else:
            readiness = c.get("readiness") or {}
            headline_options = ""
            alt = [h for h in (c.get("draft_headlines") or []) if h != c["draft_headline"]]
            if alt:
                headline_options = (
                    "\n\nAlternative headline candidates (same draft, §20):\n"
                    + "\n".join(f"- {h}" for h in alt)
                )
            lines += [
                "## EDITOR SCORECARD (fill in, then run `finalize`)",
                "",
                "```yaml",
                "final_headline:",
                "final_text: |",
                "  <paste your edited final article here>",
                "editor_outcome: ACCEPTED_FOR_EDIT   # ACCEPTED_FOR_EDIT | REJECTED | MIXED",
                "editing_weight: MODERATE            # LIGHT | MODERATE | HEAVY | REWRITE | REJECTED",
                "time_saved_estimate: 5-15 min       # <5 min | 5-15 min | 15-30 min | >30 min",
                "published_or_ready: READY           # PUBLISHED | READY | NOT_READY",
                "notes: ''",
                "idea_status: FOLLOW_UP              # optional new IdeaCard status",
                "# M2R readiness feedback (LIVE learning signals, never auto-applied):",
                "readiness_outcome: ''               # ANGLE_ACCEPTED | ANGLE_CHANGED | NO_STORY_CONFIRMED | RESEARCH_REQUESTED",
                "readiness_note: ''                  # optional why (recorded with readiness_outcome)",
                "# readiness answers (YES | NO | CHANGE per question):",
                "readiness_answers:",
                "  would_publish: ''                 # Would you publish a story on this topic?",
                "  angle_right: ''                   # Is the selected angle right? (NO/CHANGE -> ANGLE_CHANGED)",
                "  headline_strong: ''               # Is the headline strong enough? (AI offers 3 candidates above)",
                "  opening_engaging: ''              # Is the opening engaging enough?",
                "```",
                "",
            ] + ([headline_options, ""] if headline_options else [])
            if readiness:
                lines += [
                    (
                        f"Readiness layer: **{readiness.get('status')}** | "
                        f"value: {readiness.get('editorial_value_status')} | "
                        f"sufficiency: {readiness.get('evidence_sufficiency_status')} | "
                        f"hook: {readiness.get('hook_strategy')}"
                    ),
                    "",
                ]
        lines += [
            "Tip: keep the draft body above untouched — paste your final separately;",
            "the deterministic diff + FACT/STYLE/STRUCTURE classification runs on save.",
        ]
        (outdir / f"{c['case_id']}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"review files -> {outdir}")


def cmd_finalize(args):
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    all_cases = cases_mod.read_cases(CASES_PATH)
    for c in all_cases:
        if c["case_id"] == args.case_id:
            if c.get("final_text"):
                sys.exit(f"{args.case_id} already finalized — draft/final are immutable; use notes")
            if c.get("track") == TRACK_DRYRUN:
                # benchmark-only case: no effort/adoption scorecard; supply the
                # PUBLISHED article instead (headline + text) for the Track-A diff.
                published_headline = payload.get("published_headline", "")
                published_text = payload.get("published_text", "")
                if not published_headline or not published_text:
                    sys.exit(
                        f"{args.case_id} is {TRACK_DRYRUN}: provide "
                        "published_headline + published_text (the actually "
                        "published article) - effort metrics are not valid here"
                    )
                for key in ("time_saved_estimate", "editor_outcome"):
                    if payload.get(key):
                        sys.exit(
                            f"{args.case_id}: '{key}' is excluded from "
                            f"{TRACK_DRYRUN} cases (fabricated metric)"
                        )
                cases_mod.record_editor_final(
                    c,
                    final_headline=published_headline,
                    final_text=published_text,
                    editor_outcome="ACCEPTED_FOR_EDIT",
                    editing_weight="NONE",
                    published_or_ready="PUBLISHED",
                    notes=payload.get("notes", ""),
                    _published_reference=True,
                )
                cases_mod.save_cases(all_cases, CASES_PATH)
                print(
                    f"{args.case_id}: published reference stored (Track A benchmark; "
                    "run 'dryrun-benchmark' for the comparison)"
                )
                return
            cases_mod.record_editor_final(c, **payload)
            cases_mod.save_cases(all_cases, CASES_PATH)
            counts = c["revision_classification"]["counts"]
            active = {k: v for k, v in counts.items() if v}
            readiness = (
                f" | readiness_outcome={c['readiness_outcome']}"
                if c.get("readiness_outcome")
                else ""
            )
            answers = c.get("readiness_answers") or {}
            if answers:
                readiness += " | answers=" + ",".join(
                    f"{k}={v}" for k, v in sorted(answers.items())
                )
            print(
                f"{args.case_id}: finalized | editing_weight={c['editing_weight']} | "
                f"headline_changed={c['diff']['headline_changed']} | categories={active}"
                f"{readiness}"
            )
            return
    sys.exit(f"unknown case_id: {args.case_id}")


def cmd_youtube_intake(args):
    """M3B: YouTube URL -> transcript -> discovery V2 -> readiness (no drafting).

    Shares the run lock with the cron queue: an editor pasting a URL while the
    nightly run is working would otherwise put two concurrent requests on the
    same IP, which is exactly what the anti-ban policy exists to prevent.
    """
    from editor_assistant.workflow import intake as intake_mod
    from editor_assistant.workflow import intake_run as run_mod
    from editor_assistant.workflow import jev as jev_mod
    from editor_assistant.workflow import youtube_policy as policy_mod

    policy = policy_mod.load_policy()
    _print_policy(policy)
    if not run_mod.acquire_lock(stale_after_s=policy.lock_stale_s):
        print("another intake run holds the lock - try again when it finishes")
        sys.exit(run_mod.EXIT_LOCKED)

    try:
        evaluate_fn = None
        if not args.skip_jev_shadow:
            available, reason = jev_mod.capability_status()
            if available:
                evaluate_fn = jev_mod.evaluate
            else:
                print(f"jev shadow: {jev_mod.JEV_CAPABILITY_UNAVAILABLE}: {reason}")

        result = intake_mod.intake_youtube(
            args.url,
            language=args.language,
            force_retranscribe=args.force_retranscribe,
            force_discovery=args.force_discovery,
            jev_shadow_enabled=not args.skip_jev_shadow,
            jev_evaluate_fn=evaluate_fn,
        )
        _print_intake(result)
        stages = result.get("stages") or {}
        category = (stages.get("transcription") or {}).get("category")
        if category == transcriber_mod.TRANSCRIBER_BLOCKED:
            # A flag is about the IP, not about this video: record the cooldown so
            # the nightly run does not immediately re-poke YouTube.
            record = run_mod.write_cooldown(
                (stages.get("transcription") or {}).get("reason") or "blocked",
                hours=policy.block_cooldown_h,
            )
            print(
                f"circuit breaker: YouTube pushed back - cooling down until "
                f"{record['blocked_until']}"
            )
        if result.get("outcome") in (
            intake_mod.OUTCOME_INVALID_URL,
            intake_mod.OUTCOME_TRANSCRIPTION_FAILED,
            intake_mod.OUTCOME_DISCOVERY_FAILED,
        ):
            sys.exit(1)
    finally:
        run_mod.release_lock()


def cmd_youtube_batch(args):
    """M3B.1: the cron-facing queue (add / run / status / reset). No daemon."""
    from editor_assistant.workflow import intake_queue as queue_mod
    from editor_assistant.workflow import intake_run as run_mod
    from editor_assistant.workflow import youtube_policy as policy_mod

    action = args.action
    if action == "add":
        queue = queue_mod.read_queue()
        for url in args.urls:
            entry, added = queue_mod.add_url(queue, url)
            label = entry.get("video_id") or entry.get("url")
            print(f"{'queued ' if added else 'known  '} {entry['status']:12s} {label}")
        queue_mod.save_queue(queue)
        _print_queue_summary(queue_mod.summarize(queue))
        return

    if action == "status":
        queue = queue_mod.read_queue()
        _print_queue_summary(queue_mod.summarize(queue))
        cooldown = run_mod.active_cooldown()
        if cooldown:
            print(
                f"cooldown: ACTIVE until {cooldown.get('blocked_until')} ({cooldown.get('reason')})"
            )
        else:
            print("cooldown: none")
        _print_policy(policy_mod.load_policy())
        runs = queue_mod.recent_runs(limit=5)
        if runs:
            print("last runs:")
            for record in runs:
                print(
                    f"  {record.get('finished_at')} exit={record.get('exit_code')} "
                    f"breaker={record.get('breaker')} {record.get('note')}"
                )
        else:
            print("last runs: none")
        return

    if action == "reset":
        queue = queue_mod.read_queue()
        revived = queue_mod.reset(queue, include_no_captions=args.include_nocaps)
        queue_mod.save_queue(queue)
        print(f"revived {len(revived)} entr(y/ies) -> pending")
        _print_queue_summary(queue_mod.summarize(queue))
        return

    # action == "run": the cron entry point
    policy = policy_mod.load_policy()
    evaluate_fn = None
    if args.jev_shadow:
        from editor_assistant.workflow import jev as jev_mod

        available, reason = jev_mod.capability_status()
        if available:
            evaluate_fn = jev_mod.evaluate
        else:
            print(f"jev shadow: {jev_mod.JEV_CAPABILITY_UNAVAILABLE}: {reason}")
    _print_policy(policy)
    result = run_mod.run_once(
        policy=policy,
        cap=args.cap,
        cron=args.cron and not args.no_jitter,
        jev_shadow_enabled=args.jev_shadow,
        jev_evaluate_fn=evaluate_fn,
    )
    run_mod.finish_run(result)
    if result.get("jitter_slept_s"):
        print(f"startup jitter: slept {result['jitter_slept_s']}s")
    for entry in result.get("entries") or []:
        print(
            f"  {entry.get('kind'):9s} {entry.get('transcription_status') or '-':8s} "
            f"{entry.get('video_id') or entry.get('url')} "
            f"outcome={entry.get('outcome')} readiness={entry.get('readiness')}"
        )
    stats = result.get("stats") or {}
    print(
        f"processed={stats.get('processed')} reused={stats.get('reused')} "
        f"done={stats.get('done')} retry={stats.get('retry')} "
        f"parked={stats.get('permanent')} blocked={stats.get('blocked')}"
    )
    print(f"{result.get('note')}")
    sys.exit(result.get("exit_code", 0))


def _print_policy(policy):
    """One line of effective policy, then any silent clamp made while loading it."""
    print(f"policy: {policy.describe()}")
    for warning in policy.warnings:
        print(f"policy warning: {warning}")


def _print_queue_summary(counts):
    print(
        "queue: "
        f"pending={counts.get('pending')} retry={counts.get('retry')} "
        f"done={counts.get('done')} blocked={counts.get('blocked')} "
        f"no_captions={counts.get('no_captions')} unavailable={counts.get('unavailable')} "
        f"invalid_url={counts.get('invalid_url')} total={counts.get('total')}"
    )


def cmd_sources(args):
    """M4A: manage the editor-owned source registry.

    The Workbench has the editor-facing UI; this is the same registry from the
    command line (scripting, ops, review). Nothing here collects or fetches.
    """
    from editor_assistant.workflow import sources_registry as reg

    action = args.action
    try:
        if action == "list":
            rows = reg.describe_all()
            counts = reg.summary()
            print(
                f"sources: {counts['total']} total · {counts['active']} active · "
                f"{counts['muted']} muted · {counts['disabled']} disabled · "
                f"{counts['monitoring_only']} monitoring-only"
            )
            for row in rows:
                flags = []
                if not row["factual_authority"]:
                    flags.append("monitoring-only")
                if row["mute_expired"]:
                    flags.append(f"mute expired {row['muted_until']}")
                elif row["status"] == "muted":
                    flags.append(f"muted until {row['muted_until']}")
                print(
                    f"{row['effective_status']:<9} {row['priority']:<6} {row['kind']:<10} "
                    f"{row['source_id']:<26} {row['name']}"
                    + (f"  [{', '.join(flags)}]" if flags else "")
                )
            if not rows:
                print("(empty — add one with: cli sources add --id ... --name ...)")
            return
        if action == "add":
            entry = reg.add_source(
                source_id=args.source_id,
                name=args.name,
                kind=args.kind,
                domain=args.domain or "",
                collector=args.collector,
                url=args.url or "",
                query=args.query or "",
                priority=args.priority,
                cadence=args.cadence,
                factual_authority=not args.monitoring_only,
                note=args.note or "",
            )
            print(f"added {entry['source_id']} ({entry['kind']}, {entry['collector']})")
            return
        if action == "seed":
            result = reg.seed_defaults(dry_run=args.dry_run)
            verb = "would add" if args.dry_run else "added"
            print(f"{verb}: {', '.join(result['added']) or '(nothing)'}")
            if result["skipped"]:
                print(f"kept as-is (already present): {', '.join(result['skipped'])}")
            return
        if action == "defaults":
            result = reg.apply_defaults(preview=not args.apply)
            mode = "ПРЕДГЛЕД (без запис)" if result["preview"] else "ПРИЛОЖЕНИ"
            print(
                f"{mode}: добавени {len(result['added'])} · вече налични "
                f"{len(result['present'])} · непроменени (редакторски) {len(result['present'])}"
            )
            for source_id in result["added"]:
                print(f"  + {source_id}")
            if result["present"]:
                print("  = " + ", ".join(result["present"]))
            print(
                "  изключени по подразбиране (активирайте ръчно): " + ", ".join(result["optional"])
            )
            return
        if action == "remove":
            reg.remove_source(args.source_id)
            print(f"removed {args.source_id} (collected evidence is untouched)")
            return
        if action == "mute":
            reg.set_status(args.source_id, "muted", muted_until=args.until)
            print(f"muted {args.source_id} until {args.until}")
            return
        if action in ("enable", "disable"):
            status = "active" if action == "enable" else "disabled"
            reg.set_status(args.source_id, status)
            print(f"{args.source_id}: {status}")
            return
        if action == "priority":
            reg.set_priority(args.source_id, args.value)
            print(f"{args.source_id}: priority={args.value}")
            return
        if action == "cadence":
            reg.set_cadence(args.source_id, args.value)
            print(f"{args.source_id}: cadence={args.value}")
            return
        if action == "authority":
            reg.set_factual_authority(args.source_id, args.value == "yes")
            print(
                f"{args.source_id}: factual_authority={args.value == 'yes'}"
                + ("" if args.value == "yes" else " (monitoring only)")
            )
            return
        raise SystemExit(f"unknown sources action: {action}")
    except reg.RegistryError as exc:
        raise SystemExit(f"sources: {exc}") from exc


def cmd_newsroom(args):
    """M4A/M4C: one-shot collection + story identity (cron calls this; no daemon).

    Reads the editor-owned registry and writes the story-inbox store. Collection
    only READS public sources; the only writes are to our own inbox and story
    store. `--dry-run` makes no network call at all.
    """
    from editor_assistant.workflow import newsroom_run

    if args.action == "collect":
        summary = newsroom_run.collect(
            dry_run=args.dry_run,
            source_ids=args.source or None,
            limit=args.limit,
            force=args.force,
        )
        newsroom_run.print_summary(summary)
        if summary.get("locked"):
            # Another run (cron or the Workbench button) holds the lock; do nothing.
            raise SystemExit(3)
        if summary["failed"]:
            # Partial failure is visible in the exit code so cron mail surfaces it,
            # while the successful sources still keep their items.
            raise SystemExit(1)
        return
    if args.action == "stories":
        _run_newsroom_stories(args)
        return
    if args.action == "refresh":
        _run_newsroom_refresh(args)
        return
    raise SystemExit(f"unknown newsroom action: {args.action}")


def _run_newsroom_stories(args):
    """M4C: incremental story assignment (or an explicit full rebuild)."""
    from editor_assistant.workflow import story_identity

    if args.action == "stories" and args.stories_action == "rebuild":
        result = story_identity.rebuild(
            semantic=not args.no_semantic, preview=not args.apply, force=args.force
        )
        if result.get("refused"):
            print(f"ПРЕИЗГРАЖДАНЕТО Е ОТКАЗАНО: {result['reason']}")
            return
        print(story_identity.render_summary(result))
        return
    semantic = not getattr(args, "no_semantic", False)
    summary = story_identity.update(dry_run=args.dry_run, semantic=semantic)
    print(story_identity.render_summary(summary))


def _run_newsroom_refresh(args):
    """PART 11: collect -> assign new items to stories -> one readable summary.

    A story failure must not roll back a successful collection (and vice versa):
    collection runs first and its items are on disk before stories are touched.
    """
    from editor_assistant.workflow import newsroom_run, story_identity

    collect = newsroom_run.collect(
        dry_run=args.dry_run,
        source_ids=args.source or None,
        limit=args.limit,
        force=args.force,
    )
    if collect.get("locked"):
        newsroom_run.print_summary(collect)
        raise SystemExit(3)
    story_summary, story_error = None, ""
    try:
        story_summary = story_identity.update(dry_run=args.dry_run, semantic=not args.no_semantic)
    except Exception as exc:  # noqa: BLE001 - a story failure must not lose the collection
        story_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    print(render_refresh_summary(collect, story_summary, story_error))
    if collect["failed"]:
        raise SystemExit(1)


def render_refresh_summary(collect, stories, story_error):
    """The editor-facing one-shot summary (PART 11)."""
    lines = []
    if collect.get("dry_run"):
        lines.append("ПРОБЕН ПРЕГЛЕД (без мрежа и без запис)")
    lines.append(f"източници: {len(collect.get('sources') or [])}")
    lines.append(f"нови материали: {int(collect.get('new') or 0)}")
    if stories is None:
        lines.append("истории: НЕ СА ОБНОВЕНИ")
    else:
        lines.append(f"нови истории: {stories['new_stories']}")
        lines.append(f"нови развития: {stories['relations'].get('NEW_DEVELOPMENT', 0)}")
        lines.append(
            "добавени към съществуващи: "
            f"{stories['deterministic_matches'] + stories['semantic_matches'] + stories['exact_duplicates']}"
        )
        lines.append(f"за преглед: {stories['needs_review']}")
    errors = int(collect.get("failed") or 0) + (1 if story_error else 0)
    lines.append(f"грешки: {errors}")
    if story_error:
        lines.append(f"  истории: {story_error}")
    return "\n".join(lines)


def _add_newsroom_subcommands(sub):
    """M4A/M4C: the cron entry point for daily collection + story building."""
    p = sub.add_parser("newsroom", help="daily newsroom operations (collection + stories)")
    actions = p.add_subparsers(dest="action", required=True)
    collect = actions.add_parser(
        "collect", help="collect from the registered sources once (cron entry point)"
    )
    collect.add_argument(
        "--dry-run", action="store_true", help="show what would be collected, with no network"
    )
    collect.add_argument(
        "--source", action="append", default=None, help="only this source_id (repeatable)"
    )
    collect.add_argument("--limit", type=int, default=None, help="collect at most N sources")
    collect.add_argument(
        "--force", action="store_true", help="ignore cadence (collect even if already done today)"
    )

    stories = actions.add_parser("stories", help="M4C story identity")
    story_actions = stories.add_subparsers(dest="stories_action", required=True)
    upd = story_actions.add_parser("update", help="assign newly collected items to stories")
    upd.add_argument("--dry-run", action="store_true", help="report the plan, write nothing")
    upd.add_argument(
        "--no-semantic",
        action="store_true",
        help="deterministic only (no model call); uncertain items stay separate",
    )
    reb = story_actions.add_parser(
        "rebuild", help="rebuild every story from raw items (refuses to lose editor fixes)"
    )
    reb.add_argument("--preview", action="store_true", help="show the plan (default: no write)")
    reb.add_argument("--apply", action="store_true", help="write the rebuilt store")
    reb.add_argument(
        "--force", action="store_true", help="allow a rebuild that discards editor split/merge"
    )
    reb.add_argument("--no-semantic", action="store_true", help="deterministic only")

    refresh = actions.add_parser(
        "refresh", help="collect, then assign the new material to stories, one summary"
    )
    refresh.add_argument("--dry-run", action="store_true", help="no network, no writes")
    refresh.add_argument(
        "--source", action="append", default=None, help="only this source_id (repeatable)"
    )
    refresh.add_argument("--limit", type=int, default=None, help="collect at most N sources")
    refresh.add_argument("--force", action="store_true", help="ignore cadence")
    refresh.add_argument("--no-semantic", action="store_true", help="deterministic story only")
    p.set_defaults(func=cmd_newsroom)


def _add_sources_subcommands(sub):
    """M4A: source registry actions (the Workbench exposes the same store)."""
    from editor_assistant.workflow import sources_registry as reg

    p = sub.add_parser("sources", help="manage the editor-owned source registry")
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="show every source with its effective status")

    seed = actions.add_parser(
        "seed", help="add the default seed (declared sources only; never overwrites)"
    )
    seed.add_argument("--dry-run", action="store_true", help="show what would be added")

    defaults = actions.add_parser(
        "defaults", help="apply the default source catalogue additively (never overwrites)"
    )
    defaults.add_argument(
        "--preview", action="store_true", help="report what would change, write nothing"
    )
    defaults.add_argument(
        "--apply", action="store_true", help="add only the missing default source IDs"
    )

    add = actions.add_parser("add", help="add a source")
    add.add_argument("--id", dest="source_id", required=True, help="slug, e.g. bnr-burgas")
    add.add_argument("--name", required=True)
    add.add_argument("--kind", required=True, choices=reg.KINDS)
    add.add_argument(
        "--domain", default="", help="publisher domain (the authority key for its articles)"
    )
    add.add_argument("--collector", required=True, choices=reg.COLLECTORS)
    add.add_argument("--url", default="", help="feed/page URL (rss, web, youtube)")
    add.add_argument("--query", default="", help="search query (google_news_rss)")
    add.add_argument("--priority", default="normal", choices=reg.PRIORITIES)
    add.add_argument("--cadence", default="each_run", choices=reg.CADENCES)
    add.add_argument(
        "--monitoring-only",
        action="store_true",
        help="collect it, but never treat it as a factual authority",
    )
    add.add_argument("--note", default="")

    for name, help_text in (
        ("enable", "collect this source again"),
        ("disable", "stop collecting this source"),
        ("remove", "delete the source entry (evidence is kept)"),
    ):
        actions.add_parser(name, help=help_text).add_argument("source_id")

    mute = actions.add_parser("mute", help="pause until a date, then resume automatically")
    mute.add_argument("source_id")
    mute.add_argument("--until", required=True, help="YYYY-MM-DD (UTC)")

    for name, choices, help_text in (
        ("priority", reg.PRIORITIES, "high / normal / low"),
        ("cadence", reg.CADENCES, "each_run / daily / weekly"),
        ("authority", ("yes", "no"), "is this a factual authority?"),
    ):
        setter = actions.add_parser(name, help=help_text)
        setter.add_argument("source_id")
        setter.add_argument("value", choices=choices)

    p.set_defaults(func=cmd_sources)


def _add_youtube_batch_subcommands(sub):
    """M3B.1: queue actions. The run action is what cron calls."""
    p = sub.add_parser(
        "youtube-batch",
        help="queue YouTube URLs and work them slowly (cron entry point; no daemon)",
    )
    actions = p.add_subparsers(dest="action", required=True)

    add = actions.add_parser("add", help="queue one or more YouTube URLs")
    add.add_argument("urls", nargs="+", help="YouTube URLs (any normalizable form)")

    run = actions.add_parser("run", help="work due queue entries once (cron entry point)")
    run.add_argument("--cron", action="store_true", help="sleep a random startup jitter first")
    run.add_argument("--cap", type=int, default=None, help="max entries this run")
    run.add_argument("--no-jitter", action="store_true", help="skip the startup jitter")
    run.add_argument(
        "--jev-shadow",
        action="store_true",
        help="also collect Jev shadow observations (no authority)",
    )

    actions.add_parser("status", help="queue counts, cooldown, recent runs")

    reset = actions.add_parser("reset", help="revive blocked/retry entries -> pending")
    reset.add_argument(
        "--include-nocaps", action="store_true", help="also retry no_captions entries"
    )

    p.set_defaults(func=cmd_youtube_batch)


def _print_intake(result):
    stages = result.get("stages") or {}
    video = result.get("video") or {}
    analysis = result.get("analysis") or {}
    print(f"outcome: {result.get('outcome')}")
    print(f"original_url: {result.get('original_url')}")
    print(
        f"video: {video.get('video_id')} | {video.get('title') or '(title unresolved)'} | "
        f"trust {video.get('transcript_trust_level')}"
    )
    print(f"canonical: {video.get('canonical_url')}")
    for name in ("normalize", "metadata", "transcription", "validate", "persist", "discovery"):
        stage = stages.get(name)
        if stage:
            detail = ", ".join(f"{k}={v}" for k, v in stage.items() if k != "status")
            print(f"  {name:13s} {stage['status']:8s} {detail}")
    shadow = stages.get("jev_shadow")
    if shadow:
        detail = shadow.get("reason") or (
            f"grounding={shadow.get('grounding_cases')} angles={shadow.get('angle_cases')} "
            f"rescue_candidates={shadow.get('rescue_candidates')}"
        )
        print(f"  jev_shadow    {shadow.get('status'):8s} {detail}")
    assessment = analysis.get("assessment") or {}
    readiness = analysis.get("readiness") or {}
    print(
        f"topics: {len(analysis.get('topics') or [])} | facts: {len(analysis.get('facts') or [])}"
    )
    print(f"angle assessment: {assessment.get('status')} | readiness: {readiness.get('status')}")
    strongest = _strongest_angle(assessment)
    if strongest:
        print(
            f"strongest candidate: {strongest.get('angle_id')} — {strongest.get('new_proposition')}"
        )
    elif assessment.get("reason"):
        print(f"no viable candidate: {str(assessment['reason'])[:200]}")
    for key, value in (result.get("artifacts") or {}).items():
        print(f"artifact {key}: {value}")


def _strongest_angle(assessment):
    candidates = assessment.get("candidates") or []
    selected = assessment.get("selected_angle_id")
    if selected:
        return next((c for c in candidates if c.get("angle_id") == selected), None)
    viable = [c for c in candidates if c.get("eligible")]
    return viable[0] if viable else (candidates[0] if candidates else None)


def cmd_report(_args):
    cases = cases_mod.read_cases(CASES_PATH) if CASES_PATH.exists() else []
    m = cases_mod.workflow_metrics(cases)
    benchmark = benchmark_report(CASES_PATH)
    print(
        json.dumps(
            {
                "LIVE_EDITORIAL_PILOT (the verdict metrics)": m,
                "GROUND_TRUTH_DRYRUN (benchmark only, excluded from effort metrics)": benchmark[
                    "summary"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    done = cases_mod.load_revisions(CASES_PATH) if CASES_PATH.exists() else []
    if done:
        agg = cases_mod.aggregate_patterns(done, min_count=5)
        print(
            "recurring patterns (>=5):",
            json.dumps(agg["recurring_above_threshold"], ensure_ascii=False),
        )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="editorial-workflow", description="M2.7-9 real editorial workflow pilot"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="artifact/case overview").set_defaults(func=cmd_status)
    p = sub.add_parser("show", help="print a grounded draft")
    p.add_argument("draft_key")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("ideas", help="list idea cards")
    p.add_argument("path", nargs="?", default=None)
    p.set_defaults(func=cmd_ideas)
    p = sub.add_parser("new-idea", help="register idea cards from a JSON file")
    p.add_argument("file")
    p.set_defaults(func=cmd_new_idea)
    p = sub.add_parser("request-draft", help="explicit editor trigger for drafting")
    p.add_argument("idea_id")
    p.set_defaults(func=cmd_request_draft)
    sub.add_parser("seed-cases", help="open pilot cases from the frozen M2.3B drafts").set_defaults(
        func=cmd_seed_cases
    )
    p = sub.add_parser("live-evidence", help="record an upstream lead (idea + EvidencePacket)")
    p.add_argument("evidence_id")
    p.add_argument("file")
    p.set_defaults(func=cmd_live_evidence)
    p = sub.add_parser(
        "live-angles", help="assess 3-5 research angles; weak stories produce no article"
    )
    p.add_argument("evidence_id")
    p.add_argument("file", help="JSON list of candidate assessments")
    p.add_argument(
        "--select", default=None, help="editor's angle_id (must exist and clear the threshold)"
    )
    p.add_argument(
        "--override",
        action="store_true",
        help="editor override: select an angle that fails the gate (recorded, §32)",
    )
    p.add_argument(
        "--override-reason", default=None, help="reason recorded with --override (required with it)"
    )
    p.set_defaults(func=cmd_live_angles)
    p = sub.add_parser("live-case", help="select voice/mode for a LIVE case (explicit step)")
    p.add_argument("evidence_id")
    p.add_argument("--idea", required=True)
    p.add_argument("--voice", default="VOICE_HOUSE")
    p.add_argument("--mode", default=None)
    p.set_defaults(func=cmd_live_case)
    p = sub.add_parser("live-generate", help="fresh grounded draft via the proven M2.3B path")
    p.add_argument("evidence_id")
    p.add_argument("--api-key", default=None)
    p.add_argument(
        "--case-id", default=None, help="override the auto LIV-xx id (editor-fixed case ids)"
    )
    p.add_argument(
        "--force-draft",
        action="store_true",
        help="editor override: draft despite RESEARCH_MORE (recorded, §32)",
    )
    p.add_argument(
        "--force-reason", default=None, help="reason recorded with --force-draft (required with it)"
    )
    p.set_defaults(func=cmd_live_generate)
    p = sub.add_parser("live-readiness", help="M2R readiness: newsworthiness + sufficiency + hook")
    p.add_argument("evidence_id")
    p.add_argument("--mode", default=None)
    p.add_argument(
        "--round", action="store_true", help="register a targeted research round (max 2)"
    )
    p.add_argument(
        "--round-file", default=None, help="JSON {missing_dimensions, research_questions, sources}"
    )
    p.add_argument("--mark-sufficient", action="store_true")
    p.add_argument("--mark-insufficient", action="store_true")
    p.add_argument("--mark-editor-decision", action="store_true")
    p.add_argument("--reason", default="", help="reason for --mark-* decisions")
    p.add_argument(
        "--override",
        default=None,
        choices=("FORCE_DRAFT", "REQUEST_MORE_RESEARCH", "REJECT_STORY"),
        help="editor override (recorded, never silent)",
    )
    p.set_defaults(func=cmd_live_readiness)
    sub.add_parser(
        "lineage-check", help="verify 1:1 case <-> idea <-> evidence lineage"
    ).set_defaults(func=cmd_lineage_check)
    p = sub.add_parser("dryrun-benchmark", help="Track A: AI draft vs published article")
    p.set_defaults(func=cmd_dryrun_benchmark)
    p = sub.add_parser("review", help="write editor review files")
    p.add_argument("outdir", nargs="?", default=None)
    p.set_defaults(func=cmd_review)
    p = sub.add_parser("finalize", help="record the editor final from a JSON scorecard")
    p.add_argument("case_id")
    p.add_argument("file")
    p.set_defaults(func=cmd_finalize)
    sub.add_parser("report", help="real-world workflow metrics").set_defaults(func=cmd_report)

    # M3B YouTube URL intake
    p = sub.add_parser(
        "youtube-intake",
        help="YouTube URL -> transcript -> discovery V2 -> readiness (no drafting)",
    )
    p.add_argument("url", help="YouTube URL (watch/youtu.be/live/shorts/embed forms)")
    p.add_argument("--language", default=None, help="subtitle language code (e.g. bg)")
    p.add_argument("--force-retranscribe", action="store_true", help="ignore the cached transcript")
    p.add_argument(
        "--force-discovery",
        action="store_true",
        help=(
            "rerun the model discovery stages instead of replaying the cached "
            "facts/proposals; the previous snapshot is kept as *.prev.json"
        ),
    )
    p.add_argument(
        "--skip-jev-shadow", action="store_true", help="do not run the optional Jev shadow"
    )
    p.set_defaults(func=cmd_youtube_intake)
    _add_youtube_batch_subcommands(sub)

    # M4A source registry (editor-owned configuration) + cron collection entry point
    _add_sources_subcommands(sub)
    _add_newsroom_subcommands(sub)

    # M3A Editor Workbench
    from editor_assistant.workflow.workbench.cli import add_workbench_subcommand

    add_workbench_subcommand(sub)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
