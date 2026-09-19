"""Shared Jev shadow definitions (M3B Part H/N, M3J).

One place for the typed question sets so the eval runner and the YouTube intake
cannot drift. Jev stays a **shadow** signal: nothing here changes fact retention,
angle selection, readiness or drafting, and the production result is identical
whether Jev is enabled or disabled.

`semantic_rescue_candidates.jsonl` (ignored runtime) collects the cases that
matter for a later M3J.1 decision - deterministic reject vs Jev support, and the
reverse. **No automatic rescue, no automatic rejection.**
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from editor_assistant.workflow import jev

ROOT = Path(__file__).resolve().parents[3]

SUPPORT_RELATIONS = ("EXACT_SUPPORT", "PARTIAL_SUPPORT", "NOT_ADDRESSED", "CONTRADICTED")
EVENT_RELATIONS = ("SAME_EVENT", "RELATED_BACKGROUND", "DIFFERENT_EVENT", "UNCLEAR")
PROCEDURAL_RELATIONS = ("SAME_STAGE", "DIFFERENT_STAGE", "NOT_STATED", "UNCLEAR")

OVERALL_SUPPORT = ("EXACT_SUPPORT", "PARTIAL_SUPPORT", "NOT_SUPPORTED", "CONTRADICTED")
ACTOR_RELATIONS = ("SUPPORTED", "WRONG", "NOT_STATED")
NUMBER_RELATIONS = ("SUPPORTED", "CONFLICT", "NOT_APPLICABLE", "NOT_STATED")
NEGATION_RELATIONS = ("PRESERVED", "REVERSED", "NOT_APPLICABLE", "UNCLEAR")
DECISION_STATUS = ("SUPPORTED", "OVERSTATED", "UNDERSTATED", "NOT_APPLICABLE", "UNCLEAR")

DEVELOPMENT_TYPES = ("CONCRETE_ACTION", "ROUTINE_PROCESS", "STATIC_BACKGROUND", "UNCLEAR")
EVIDENCE_COMPLETENESS = ("SUFFICIENT", "NEEDS_MORE", "INSUFFICIENT")
PROCEDURAL_SCOPES = ("SUPPORTED", "OVERSTATED", "UNCLEAR")
PRESENCE = ("PRESENT", "ABSENT", "UNCLEAR")

#: Deterministic grounding statuses treated as "deterministic reject".
REJECT_STATUSES = ("DROPPED_UNGROUNDED", "DROPPED", "REJECTED")
#: Jev answers treated as "Jev says supported".
SUPPORTING_ANSWERS = ("EXACT_SUPPORT", "PARTIAL_SUPPORT")


def corroboration_request(case):
    state = {
        "claim": case.get("claim"),
        "source_passage": case.get("source_excerpt"),
        "source_authority": case.get("source_authority"),
        "claim_procedural_status": case.get("claim_procedural_status"),
        "source_context": case.get("source_context"),
    }
    questions = {
        "support_relation": jev.question(
            jev.QUESTION_CHOICE,
            "Does the source passage support the claim (exactly, partially, not at all, or contradict it)?",
            SUPPORT_RELATIONS,
        ),
        "event_relation": jev.question(
            jev.QUESTION_CHOICE,
            "Does the source describe the same event as the claim?",
            EVENT_RELATIONS,
        ),
        "procedural_relation": jev.question(
            jev.QUESTION_CHOICE,
            "Is the claimed procedural stage the same as the source's stage?",
            PROCEDURAL_RELATIONS,
        ),
    }
    return state, questions


def grounding_request(case):
    state = {
        "claim": case.get("claim_text") or case.get("claim"),
        "support_passage": case.get("support_text") or case.get("support_passage"),
        "claim_procedural_status": case.get("procedural_status")
        or case.get("claim_procedural_status"),
    }
    questions = {
        "overall_support": jev.question(
            jev.QUESTION_CHOICE, "Do the transcript segments support the claim?", OVERALL_SUPPORT
        ),
        "actor_relation": jev.question(
            jev.QUESTION_CHOICE, "Is the claimed actor supported by the segments?", ACTOR_RELATIONS
        ),
        "number_relation": jev.question(
            jev.QUESTION_CHOICE,
            "Are the claimed numbers supported by the segments?",
            NUMBER_RELATIONS,
        ),
        "negation_relation": jev.question(
            jev.QUESTION_CHOICE,
            "Is any negation in the claim preserved by the segments?",
            NEGATION_RELATIONS,
        ),
        "decision_status_relation": jev.question(
            jev.QUESTION_CHOICE,
            "Is the claimed decision/procedural status supported?",
            DECISION_STATUS,
        ),
    }
    return state, questions


def angles_request(case):
    state = {
        "proposition": case.get("proposition"),
        "supporting_facts": case.get("supporting_facts"),
        "deterministic_assessment": case.get("deterministic_assessment"),
    }
    questions = {
        "development_type": jev.question(
            jev.QUESTION_CHOICE,
            "What kind of development does the proposition describe?",
            DEVELOPMENT_TYPES,
        ),
        "evidence_completeness": jev.question(
            jev.QUESTION_CHOICE,
            "Is the evidence in state sufficient to report the proposition?",
            EVIDENCE_COMPLETENESS,
        ),
        "procedural_scope": jev.question(
            jev.QUESTION_CHOICE,
            "Does the proposition overstate the procedural scope of its facts?",
            PROCEDURAL_SCOPES,
        ),
        "affected_party": jev.question(
            jev.QUESTION_CHOICE, "Is a concrete affected party present in the facts?", PRESENCE
        ),
        "current_change": jev.question(
            jev.QUESTION_CHOICE,
            "Does the proposition describe a current change (not only background)?",
            PRESENCE,
        ),
    }
    return state, questions


REQUEST_BUILDERS = {
    "corroboration": corroboration_request,
    "grounding": grounding_request,
    "angles": angles_request,
}


def build_request(experiment, case):
    return REQUEST_BUILDERS[experiment](case)


# ---------- semantic-rescue collection (Part N) ----------


def semantic_rescue_path(path=None):
    if path is not None:
        return Path(path)
    return Path(os.environ.get("JEV_EVAL_DIR") or (ROOT / "var" / "jev_eval")) / (
        "semantic_rescue_candidates.jsonl"
    )


def _top(record, question):
    return (((record or {}).get("answers") or {}).get(question) or {}).get("answer")


def classify_grounding_case(row):
    """Label a grounding shadow row as a rescue candidate, or None.

    * `DETERMINISTIC_REJECT__JEV_SUPPORTS` - possible false negative to review;
    * `DETERMINISTIC_RETAIN__JEV_REJECTS` - possible false positive to review.
    """
    deterministic = row.get("deterministic_status")
    jev_answer = _top(row.get("result"), "overall_support")
    if deterministic in REJECT_STATUSES and jev_answer in SUPPORTING_ANSWERS:
        return "DETERMINISTIC_REJECT__JEV_SUPPORTS"
    if deterministic not in REJECT_STATUSES and jev_answer in ("NOT_SUPPORTED", "CONTRADICTED"):
        return "DETERMINISTIC_RETAIN__JEV_REJECTS"
    return None


def collect_fact_grounding(facts, *, evaluate_fn, env=None, source=None):
    """Shadow each fact against its own supporting segment text (no authority)."""
    rows = []
    for fact in facts:
        case = {
            "case_id": fact.get("fact_id") or fact.get("case_id"),
            "claim_text": fact.get("text") or fact.get("claim_text"),
            "support_text": fact.get("support_text"),
            "procedural_status": fact.get("procedural_status"),
            "deterministic_status": fact.get("fact_grounding_status"),
            "deterministic_reason": (fact.get("grounding_failures") or [None])[0],
        }
        _state, questions = grounding_request(case)
        try:
            result = evaluate_fn(_state, questions, env=env)
        except jev.JevError as exc:
            rows.append({**case, "result": None, "error": {"code": exc.code, "message": str(exc)}})
            continue
        row = {
            **case,
            "video_id": (source or {}).get("video_id"),
            "canonical_url": (source or {}).get("canonical_url"),
            "timestamp": (source or {}).get("retrieved_at"),
            "support_excerpt": (case.get("support_text") or "")[:500],
            "result": result,
            "error": None,
        }
        row["rescue_class"] = classify_grounding_case(row)
        rows.append(row)
    return rows


def collect_angle_signals(candidate_angles, *, evaluate_fn, env=None, source=None):
    """Shadow each angle candidate with narrow semantic signals (no authority)."""
    rows = []
    for case in candidate_angles:
        _state, questions = angles_request(case)
        try:
            result = evaluate_fn(_state, questions, env=env)
        except jev.JevError as exc:
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "result": None,
                    "error": {"code": exc.code, "message": str(exc)},
                }
            )
            continue
        rows.append(
            {
                "case_id": case.get("case_id"),
                "video_id": (source or {}).get("video_id"),
                "result": result,
                "error": None,
            }
        )
    return rows


def write_rows(rows, path=None):
    """Append-only write of shadow rows to an ignored runtime file."""
    target = Path(path) if path is not None else semantic_rescue_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return target


def rescue_candidates(grounding_rows):
    return [row for row in grounding_rows if row.get("rescue_class")]
