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

There is deliberately NO publish command: the workflow ends at the editor.
Track A (dry-run vs published articles) never feeds time/weight/adoption.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from editor_assistant.workflow import angles
from editor_assistant.workflow import cases as cases_mod
from editor_assistant.workflow import live as live_mod
from editor_assistant.workflow import readiness as readiness_mod
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
    if not LIVE_EVIDENCE_PATH.exists():
        return {}
    rows = {}
    for line in LIVE_EVIDENCE_PATH.open(encoding="utf-8"):
        if line.strip():
            p = json.loads(line)
            rows[p["evidence_id"]] = p
    return rows


def _save_live_row(row):
    rows = _live_rows()
    rows[row["evidence_id"]] = row
    out = LIVE_EVIDENCE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for p in sorted(rows.values(), key=lambda r: r["evidence_id"]):
            fh.write(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n")


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
                "readiness_outcome: ''               # M2R editor verdict: ANGLE_ACCEPTED | ANGLE_CHANGED | NO_STORY_CONFIRMED | RESEARCH_REQUESTED",
                "readiness_note: ''                  # optional why (recorded with readiness_outcome)",
                "```",
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
            print(
                f"{args.case_id}: finalized | editing_weight={c['editing_weight']} | "
                f"headline_changed={c['diff']['headline_changed']} | categories={active}"
                f"{readiness}"
            )
            return
    sys.exit(f"unknown case_id: {args.case_id}")


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
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
