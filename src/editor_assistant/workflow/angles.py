"""Inspectable editorial-value gate; assessments are judgments, never evidence.

Research/editor supplies 3-5 distinct angles, scored 0 (absent), 1 (limited),
2 (strong) per criterion. Every positive score needs a reason and fact IDs.

Rubric v2 adds the SEMANTIC VIABILITY GATE: every candidate must state its
NEW PROPOSITION (one sentence answering "what is new here?"). A candidate is
publishable only when a concrete new event/decision/change is expressible from
its supporting evidence. An explicit semantic veto - or evidence whose facts
contain no new-event signal at all - overrides numeric eligibility: the score
total ranks and diagnoses, it never makes an angle publishable on its own.
"""

from __future__ import annotations

import re
from copy import deepcopy

CRITERIA = (
    "concrete_change",
    "people_impact",
    "money_infrastructure_services",
    "different_positions",
    "unexpected_fact",
    "strong_quote",
    "burgas_novelty",
)
THRESHOLD = 5
NO_ANGLE = "NO_PUBLISHABLE_ANGLE"
READY = "ANGLE_SELECTED"
NEEDS_RESEARCH = "POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH"
VIABLE = "PUBLISHABLE_ANGLE"
NOT_VIABLE = "NO_PUBLISHABLE_ANGLE"
RUBRIC_VERSION = "editorial-value-2"


class AngleError(ValueError):
    pass


# Semantic floor: a candidate whose supporting facts contain none of these
# signals has no expressible concrete new event from evidence ("what is new?"
# cannot be answered), no matter how the rubric scores relevance. It is a
# floor, not a ceiling: a cue alone does not make routine material publishable
# (the explicit veto remains available and decisive). Covers decisions,
# future events, launches/announcements and concrete occurrences (accidents,
# deaths, discoveries) - generic event semantics, never entity-specific.
NOVELTY_CUE = re.compile(
    r"\bприе\b|\bприема\b|\bодобри\b|\bотхвърли\b|\bгласува\b|\bподкрепи\b|"
    r"\bреши\w*|\bприет\w*|\bодобрен\w*|\bотхвърл\w*|"
    r"ще се проведе|ще се състои|ще се играе|ще започне|ще гостува|ще открие|"
    r"ще представи|ще покаже|предстои|\bпремиер\w*|\bоткриване\b|"
    r"\bотварят\b|\bоткриват\b|\bвъвежда\b|\bстартира\b|\bзапочва\b|"
    r"\bподписа\b|\bпредставя\b|\bобяви\b|\bсъобщи\w*\b|\bнагради\b|"
    r"\bвръчи\b|\bпубликува\b|\bизлезе\b|\bгостува\b|\bпосреща\b|\bсъстоя\b|"
    r"\bзагина\w*|\bпочина\b|\bпострада\w*|\bранени?\b|\bкатастрофа\b|"
    r"\bпроизшестви\w+|\bпожар\b|\bоткрадна\w*|\bарестува\w*|\bоткриха\b",
    re.IGNORECASE,
)


def needs_angle_review(packet):
    text = " ".join(str(packet.get(k, "")) for k in ("source_type", "source_url"))
    return any(cue in text.lower() for cue in ("transcript", "council", "транскрипт", "съвет"))


def _validate_candidate(candidate, facts, seen, titles):
    if not isinstance(candidate, dict):
        raise AngleError("candidate must be an object")
    cid = candidate.get("angle_id")
    title = candidate.get("title")
    if not isinstance(cid, str) or not cid.strip() or cid in seen:
        raise AngleError("candidate IDs must be non-empty and unique")
    if not isinstance(title, str) or not title.strip() or title.strip().casefold() in titles:
        raise AngleError("candidate titles must be non-empty and distinct")
    seen.add(cid)
    titles.add(title.strip().casefold())
    if not isinstance(candidate.get("reason"), str) or not candidate["reason"].strip():
        raise AngleError("each angle needs an editorial explanation")
    proposition = candidate.get("new_proposition")
    if not isinstance(proposition, str) or not proposition.strip():
        raise AngleError(
            "each candidate must state its NEW PROPOSITION: what exactly is "
            "new here, in one concrete sentence from the evidence"
        )
    if proposition.strip().casefold() == title.strip().casefold():
        raise AngleError("new_proposition must state the concrete news, not repeat the title")
    refs = candidate.get("fact_ids")
    if (
        not isinstance(refs, list)
        or not refs
        or any(not isinstance(r, str) or r not in facts for r in refs)
    ):
        raise AngleError("angle must reference existing evidence fact IDs")
    scores = candidate.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(CRITERIA):
        raise AngleError("all editorial criteria must be scored")
    total = 0
    for criterion, item in scores.items():
        if (
            not isinstance(item, dict)
            or type(item.get("score")) is not int
            or item["score"] not in (0, 1, 2)
        ):
            raise AngleError("criterion score must be 0, 1 or 2")
        if item["score"]:
            support = item.get("fact_ids")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise AngleError("positive score needs an editorial reason")
            if not isinstance(support, list) or not support or any(r not in refs for r in support):
                raise AngleError("positive score needs supporting angle fact IDs")
            if criterion == "burgas_novelty" and not any(
                facts[r].get("scope", "current_event") == "current_event" for r in support
            ):
                raise AngleError("historical background cannot establish current local novelty")
        total += item["score"]
    return total, refs


def _semantic_viability(candidate, refs, facts, numeric_eligible):
    """Resolve the candidate's semantic status. Order of precedence:

    1. explicit veto -> NO_PUBLISHABLE_ANGLE (veto always wins, needs a reason);
    2. explicit semantic_status from research/editor (validated vocabulary);
    3. novelty floor: no supporting fact carries a concrete new-event signal
       -> NO_PUBLISHABLE_ANGLE regardless of the numeric total;
    4. default: numeric eligibility decides (rubric v1 behavior preserved for
       candidates the assessor left semantically unmarked).
    """
    veto = candidate.get("veto", False)
    if not isinstance(veto, bool):
        raise AngleError("veto must be boolean")
    semantic_reason = candidate.get("semantic_reason")
    if veto and (not isinstance(semantic_reason, str) or not semantic_reason.strip()):
        raise AngleError("semantic veto requires semantic_reason (why there is no story)")
    explicit = candidate.get("semantic_status")
    if explicit is not None and explicit not in (VIABLE, NEEDS_RESEARCH, NOT_VIABLE):
        raise AngleError(f"bad semantic_status: {explicit!r}")
    research_questions = candidate.get("research_questions", [])
    if explicit == NEEDS_RESEARCH and (
        not isinstance(research_questions, list)
        or not research_questions
        or any(not isinstance(q, str) or not q.strip() for q in research_questions)
    ):
        raise AngleError("POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH needs concrete research questions")
    if veto:
        return NOT_VIABLE, True, list(research_questions)
    if explicit:
        return explicit, False, list(research_questions)
    if not any(NOVELTY_CUE.search(facts[r]["text"]) for r in refs):
        return NOT_VIABLE, True, []
    return (VIABLE if numeric_eligible else NOT_VIABLE), False, []


def assess_angles(
    packet, candidates, *, editor_selection=None, editor_override_reason=None, min_candidates=3
):
    """Rank supplied research judgments, validate grounding, permit no story.

    candidate: {angle_id, title, reason, new_proposition, fact_ids, scores:
    {criterion: {score: 0|1|2, reason, fact_ids}}}. All criteria are required.
    Local novelty is mandatory; conflict or a quote alone is not enough.

    Semantic fields (rubric v2): `new_proposition` is mandatory; `veto` +
    `semantic_reason` mark a semantically non-viable candidate (overrides any
    score); `semantic_status` may explicitly mark the candidate
    PUBLISHABLE_ANGLE (promotes a concise, concrete development even below the
    numeric threshold) or POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH (meaningful
    story, required specifics missing - then `research_questions` are needed).

    editor_selection: an angle_id the editor explicitly chose. It must exist
    and be eligible - the editor may overrule the ranking, never the gate.
    editor_override_reason: with editor_selection, selects an otherwise
    ineligible candidate; the override is recorded, never silent (§32).

    M2S: `min_candidates` relaxes the pilot's 3-candidate floor for generic
    transcript discovery (1-2 real candidates instead of fabricated padding;
    harness B9). The LIVE pilot default stays 3 - the relaxation is opt-in,
    explicit at the call site, and its result carries `min_candidates` so the
    relaxed floor is visible in the persisted record.
    """
    if not isinstance(min_candidates, int) or not 1 <= min_candidates <= 3:
        raise AngleError("min_candidates must be an integer in [1..3]")
    if not isinstance(candidates, list) or not min_candidates <= len(candidates) <= 5:
        raise AngleError(
            f"review requires {min_candidates}-5 candidate angles; do not invent padding topics"
        )
    if editor_override_reason is not None:
        if editor_selection is None:
            raise AngleError("editor override requires an explicit angle selection")
        if not isinstance(editor_override_reason, str) or not editor_override_reason.strip():
            raise AngleError("editor override requires a non-empty recorded reason")
    facts = {f["id"]: f for f in packet.get("facts", [])}
    seen, titles, ranked = set(), set(), []
    for candidate in candidates:
        total, refs = _validate_candidate(candidate, facts, seen, titles)
        numeric_eligible = total >= THRESHOLD and candidate["scores"]["burgas_novelty"]["score"] > 0
        semantic, veto_applied, research_questions = _semantic_viability(
            candidate, refs, facts, numeric_eligible
        )
        ranked.append(
            {
                **deepcopy(candidate),
                "total": total,
                "eligible": semantic == VIABLE,
                "numeric_eligible": numeric_eligible,
                "semantic_status": semantic,
                "veto_applied": veto_applied,
                "research_questions": research_questions,
            }
        )
    ranked.sort(key=lambda c: (-c["total"], c["angle_id"]))
    selected = next((c for c in ranked if c["eligible"]), None)
    selection_source = "ranking" if selected else "none"
    override_record = None
    if editor_selection is not None:
        chosen = next((c for c in ranked if c["angle_id"] == editor_selection), None)
        if chosen is None:
            raise AngleError(f"editor selection {editor_selection!r} is not a supplied angle")
        if not chosen["eligible"] and editor_override_reason is None:
            raise AngleError(
                f"editor selection {editor_selection!r} does not clear the threshold "
                f"({chosen['total']}/{THRESHOLD} + current Burgas novelty; semantic_status "
                f"{chosen['semantic_status']}) - either the angle lacks editorial value or "
                "the evidence must be strengthened"
            )
        selected = chosen
        selection_source = "editor" if chosen["eligible"] else "editor_override"
        if editor_override_reason is not None:
            override_record = {
                "type": "FORCE_DRAFT" if not chosen["eligible"] else "SELECTION_NOTE",
                "angle_id": editor_selection,
                "reason": editor_override_reason.strip(),
            }
    if selected:
        status = READY
        reason = selected["reason"]
        merged_questions, pending = [], None
    else:
        pending_candidates = [c for c in ranked if c["semantic_status"] == NEEDS_RESEARCH]
        if pending_candidates:
            status = NEEDS_RESEARCH
            pending = pending_candidates[0]["angle_id"]
            merged_questions = []
            for cand in pending_candidates:
                for q in cand["research_questions"]:
                    if q not in merged_questions:
                        merged_questions.append(q)
            reason = (
                "Има потенциална тема, но липсват конкретни факти. Нужни са целенасочени "
                "проучвания по въпросите; статия не се създава преди тях."
            )
        else:
            status = NO_ANGLE
            reason = (
                "Нито една тема не описва конкретна новост, подкрепена от доказателствата. "
                "Вижте аргументите и semantic_status по кандидати; статия не се създава."
            )
    assessment = {
        "status": status,
        "rubric_version": RUBRIC_VERSION,
        "threshold": THRESHOLD,
        "candidates": ranked,
        "selected_angle_id": selected["angle_id"] if selected else None,
        "selection_source": selection_source,
        "editor_selection": editor_selection,
        "reason": reason,
    }
    if min_candidates != 3:
        assessment["min_candidates"] = min_candidates  # relaxed floor stays visible
    if override_record:
        assessment["editor_override"] = override_record
    if status == NEEDS_RESEARCH:
        assessment["research_questions"] = merged_questions
        assessment["pending_angle_id"] = pending
    return assessment


def check_angle_gate(packet):
    """Recompute from judgments: never trust cached status/total on disk."""
    assessment = packet.get("editorial_assessment")
    if assessment is None:
        if needs_angle_review(packet):
            raise AngleError(
                "ANGLE_REVIEW_REQUIRED: supply 3-5 assessed research angles via live-angles"
            )
        return None
    if not isinstance(assessment, dict):
        raise AngleError("editorial_assessment must be an object")
    if assessment.get("resolved_scoped"):
        # Scoped packet: it is the deterministic product of a decision already
        # re-verified against the full packet. Only the binding must still hold:
        # every fact the selected angle references must be present here.
        chosen = next(
            (
                c
                for c in assessment.get("candidates", [])
                if c.get("angle_id") == assessment.get("selected_angle_id")
            ),
            None,
        )
        ids = {f["id"] for f in packet.get("facts", [])}
        if chosen is None or any(ref not in ids for ref in chosen.get("fact_ids", [])):
            raise AngleError("scoped packet lost facts referenced by the selected angle")
        return assessment
    if assessment.get("rubric_version") == "editorial-value-1":
        raise AngleError(
            "stored assessment uses superseded rubric editorial-value-1; re-assess via "
            "live-angles under editorial-value-2 (semantic viability gate)"
        )
    stored = assessment.get("editor_selection")
    return assess_angles(packet, assessment.get("candidates"), editor_selection=stored)


def selected_angle_packet(packet, assessment):
    """Limit generation to the chosen angle, not the entire meeting agenda."""
    selected = next(
        c for c in assessment["candidates"] if c["angle_id"] == assessment["selected_angle_id"]
    )
    out = deepcopy(packet)
    out["facts"] = [f for f in out["facts"] if f["id"] in selected["fact_ids"]]
    out["source_text"] = "\n".join(f["text"] for f in out["facts"])
    # Unmapped meeting-wide quotes must not leak into the selected story.
    out["quotes"] = []
    # Mark the scoping so a later gate check re-verifies the binding (the fact
    # set is narrower than the assessment's universe by construction).
    out["editorial_assessment"] = {**deepcopy(assessment), "resolved_scoped": True}
    return out
