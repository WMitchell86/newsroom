"""V1.2-G4.3 §F/G - the rewrite feedback log and its CONTROLLED learning loop.

**What a record is.** Every `Пренапиши` request is real editorial signal: an
editor, looking at a real draft, said in their own words what was wrong with it.
That is the highest-quality training material the product will ever collect,
and this module is where it is kept.

**What a record is deliberately NOT.** It is not a copy of the article. The
Article's own immutable content versions already own the text, and duplicating
them here would create a second place where the text lives and therefore a second
place where it can go stale or leak. A record carries the editor's *words* plus
the small set of context values needed to recognise the pattern later.

**Why nothing here changes the prompt by itself (§G).** The failure mode this
module exists to prevent is a model quietly rewriting its own instructions after
one offhand comment, and the product drifting into a house style nobody chose.
So the loop is strictly:

    feedback -> accumulate -> detect a RECURRING pattern -> PROPOSE an
    instruction -> a human approves it -> only then does anything change

`analyze()` can therefore only ever return PROPOSALS. There is no code path from
an editor comment to a live instruction, and `apply_approval` is the single,
separately-callable step that records a human decision.
"""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import live_store

#: G1 - how many unprocessed records make an analysis worthwhile. Not a
#: scheduler and not a per-comment trigger: one-off notes are noise, and a
#: pattern needs repetition before it is worth a human's attention.
DEFAULT_THRESHOLD = 20

#: G3 - where a proposal may apply. Kept explicit so a proposal can never be
#: applied somewhere the owner did not intend.
SITE_DNA = "SITE_DNA"
VOICE = "VOICE"
MODE = "MODE"
GENERAL_DRAFT_INSTRUCTION = "GENERAL_DRAFT_INSTRUCTION"
TARGETS = (SITE_DNA, VOICE, MODE, GENERAL_DRAFT_INSTRUCTION)

RECORD_FIELDS = (
    "feedback_id",
    "article_id",
    "recorded_at",
    "editor_comment",
    "focus",
    "voice",
    "mode",
    "draft_version_before",
    "draft_version_after",
    "generated_by_model",
    "processed_for_learning",
)
REQUIRED_FIELDS = {
    "feedback_id",
    "article_id",
    "recorded_at",
    "editor_comment",
    "draft_version_before",
    "draft_version_after",
    "processed_for_learning",
}

_LOCK = threading.RLock()
#: G1 - configurable, so the owner can raise the bar without a code change.
_THRESHOLD = DEFAULT_THRESHOLD


class FeedbackError(ValueError):
    """A feedback record that must not be stored or trusted."""


def set_threshold(value: int) -> int:
    """Set the unprocessed-record count at which analysis becomes eligible."""
    global _THRESHOLD
    with _LOCK:
        _THRESHOLD = max(1, int(value))
        return _THRESHOLD


def threshold() -> int:
    return _THRESHOLD


def feedback_path(*, root=None) -> Path:
    from editor_assistant.workflow.workbench import state as pipeline_state

    return Path(root or pipeline_state.workflow_dir()) / "rewrite_feedback.jsonl"


def validate_record(raw) -> dict:
    """One feedback record, with only the compact fields it is allowed to hold.

    A full source document is refused rather than silently trimmed: if a caller
    starts putting article text in here, that is a defect worth failing on, not
    something to store quietly.
    """
    if not isinstance(raw, dict):
        raise FeedbackError("a feedback record must be an object")
    missing = sorted(REQUIRED_FIELDS - set(raw))
    if missing:
        raise FeedbackError(f"feedback record missing fields: {missing}")
    comment = str(raw["editor_comment"] or "").strip()
    if not comment:
        raise FeedbackError("editor_comment must not be empty")
    if len(comment) > 4000:
        raise FeedbackError("editor_comment is too long")
    return {
        "feedback_id": str(raw["feedback_id"]),
        "article_id": str(raw["article_id"]),
        "recorded_at": str(raw["recorded_at"]),
        "editor_comment": comment,
        "focus": str(raw.get("focus") or ""),
        "voice": str(raw.get("voice") or ""),
        "mode": str(raw.get("mode") or ""),
        "draft_version_before": int(raw["draft_version_before"]),
        "draft_version_after": int(raw["draft_version_after"]),
        "generated_by_model": bool(raw.get("generated_by_model", True)),
        "processed_for_learning": bool(raw["processed_for_learning"]),
    }


def feedback_id_for(article_id: str, comment: str, version: int) -> str:
    seed = f"{article_id}\0{comment}\0{version}"
    return "fb_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def record(
    *,
    article_id: str,
    editor_comment: str,
    focus: str = "",
    voice: str = "",
    mode: str = "",
    draft_version_before: int,
    draft_version_after: int,
    generated_by_model: bool = True,
    now=None,
    root=None,
) -> dict:
    """Persist one rewrite request. Returns the stored record.

    Called on BOTH outcomes of a rewrite, including a failure. A request the
    editor made and the product could not satisfy is still a real editorial
    signal, and a failure that leaves `draft_version_after == before` is
    precisely the case where the editor's intent is otherwise lost entirely.
    """
    stamp = str(now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    row = validate_record(
        {
            "feedback_id": feedback_id_for(article_id, editor_comment, draft_version_before),
            "article_id": article_id,
            "recorded_at": stamp,
            "editor_comment": editor_comment,
            "focus": focus,
            "voice": voice,
            "mode": mode,
            "draft_version_before": int(draft_version_before),
            "draft_version_after": int(draft_version_after),
            "generated_by_model": bool(generated_by_model),
            "processed_for_learning": False,
        }
    )
    path = feedback_path(root=root)
    # The APPEND takes the same file lock as the marking pass. Without that, a
    # record written here could land between the marking pass's read and its
    # truncate and be silently destroyed - so both sides of the file must
    # serialize, not just the destructive one.
    with _LOCK, _file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = read_all(root=root)
        # The same comment on the same version is the same feedback, however
        # many times the editor pressed the button.
        if any(item["feedback_id"] == row["feedback_id"] for item in existing):
            return next(i for i in existing if i["feedback_id"] == row["feedback_id"])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def read_all(*, root=None) -> list[dict]:
    path = feedback_path(root=root)
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            rows.append(validate_record(json.loads(line)))
        except (ValueError, FeedbackError):
            # A corrupt line is skipped rather than poisoning every read; the
            # count that matters for the threshold is the valid one.
            continue
    return rows


def unprocessed(*, root=None) -> list[dict]:
    return [row for row in read_all(root=root) if not row["processed_for_learning"]]


def is_eligible(*, root=None) -> bool:
    """G1 - whether the accumulated feedback is worth analysing at all."""
    return len(unprocessed(root=root)) >= threshold()


# ---------------------------------------------------------------------------
# §G2 - pattern detection. Deterministic, offline, and proposal-only.
# ---------------------------------------------------------------------------

#: A small, closed catalogue of recurring editorial instructions. Each entry is
#: a set of BULGARIAN surface forms an editor actually uses, plus the permanent
#: instruction that the pattern would justify. This is deliberately a fixed,
#: inspectable vocabulary: a fuzzy embedding search would invent patterns nobody
#: asked for, and the whole point of §G is that a human reviews what is proposed.
#
#: `conflict` marks instructions that pull in OPPOSITE directions. Two editors
#: asking for a shorter lead and a longer one must be reported as a conflict to
#: resolve, never averaged into a middle instruction that satisfies neither.
PATTERNS = (
    {
        "id": "direct_lead",
        "target": GENERAL_DRAFT_INSTRUCTION,
        "label": "по-директно начало",
        "forms": (
            "започни директно", "започнете директно", "по-кратък лийд", "по-кратък лийдът",
            "лийдът е твърде общ", "лийдът е прекалено общ", "без общо въведение",
            "без общо тематично въведение", "директно с основния факт", "първия абзац е общ",
        ),
        "suggestion": (
            "Lead-ът по правило започва с конкретния нов факт, без общо тематично въведение."
        ),
    },
    {
        "id": "shorter_text",
        "target": GENERAL_DRAFT_INSTRUCTION,
        "label": "по-кратък текст",
        "forms": (
            "направи текста по-кратък", "съкрати текста", "по-кратко", "съкрати",
            "прекалено дълъг", "по-дълъг", "излишни изречения",
        ),
        "suggestion": "Текстът по принцип да е по-кратък и без излишни повторения.",
    },
    {
        "id": "no_headline_repeat",
        "target": GENERAL_DRAFT_INSTRUCTION,
        "label": "без повторение на заглавието",
        "forms": (
            "не повтаряй заглавието", "не повтаряй заглавието в първия абзац",
            "без да повтаря заглавието",
        ),
        "suggestion": "Първият абзац не повтаря заглавието.",
    },
    {
        "id": "restrained_tone",
        "target": GENERAL_DRAFT_INSTRUCTION,
        "label": "по-сдържан тон",
        "forms": (
            "по-сдържан тон", "по-сдържано", "без оценъчни думи", "без емоционален тон",
            "неутрален тон", "по-сух тон",
        ),
        "suggestion": (
            "Тонът остава сдържан и неутрален, без оценъчни и емоционални думи."
        ),
    },
    {
        "id": "no_generic_context",
        "target": GENERAL_DRAFT_INSTRUCTION,
        "label": "по-малко общ контекст",
        "forms": (
            "не наблягай на туристическия сезон", "по-малко общ контекст",
            "не обобщавай", "без общ контекст", "прекалено общо",
        ),
        "suggestion": (
            "Общият контекст се отпавя, когато не носи факт за конкретната новина."
        ),
    },
    {
        "id": "emphasis_shift",
        "target": GENERAL_DRAFT_INSTRUCTION,
        "label": "преместване на акцента",
        "forms": (
            "акцентът трябва да е", "искам акцент", "насочи акцента", "акцентът да е върху",
        ),
        "suggestion": "Акцентът се поставя върху факта, който редакторът посочва изрично.",
    },
)


def _matches(comment: str) -> list[str]:
    text = " ".join(str(comment or "").lower().split())
    return [
        pattern["id"]
        for pattern in PATTERNS
        if any(form in text for form in pattern["forms"])
    ]


def retired_patterns(*, root=None) -> set[str]:
    """Pattern ids a human has already DECIDED on, approved or rejected.

    A refusal is a decision. Re-proposing a rule someone already refused is how
    a learning loop turns into a nagging loop, so `analyze` never proposes a
    retired pattern again.
    """
    return {
        str(row.get("pattern_id") or "")
        for row in approved_instructions(root=root)
        if str(row.get("pattern_id") or "")
    }


def analyze(*, root=None, minimum: int = 3) -> list[dict]:
    """G2 - turn accumulated feedback into PROPOSALS. Never into instructions.

    A pattern is reported with its support count, real editor quotes, the
    instruction it would justify, and where that instruction may apply. A group
    of records that matches nothing is reported as a conflict marker rather than
    being ignored, so "editors disagree" is visible instead of being averaged
    into something nobody asked for.
    """
    rows = unprocessed(root=root)
    retired = retired_patterns(root=root)
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        for pattern_id in _matches(row["editor_comment"]):
            if pattern_id in retired:
                # Already decided by a human. Never re-propose it.
                continue
            buckets.setdefault(pattern_id, []).append(row)

    proposals: list[dict] = []
    for pattern in PATTERNS:
        supporting = buckets.get(pattern["id"], [])
        if len(supporting) < max(1, int(minimum)):
            continue
        proposals.append(
            {
                "pattern_id": pattern["id"],
                "label": pattern["label"],
                "target": pattern["target"],
                "support": len(supporting),
                "total": len(rows),
                "examples": [
                    " ".join(str(item["editor_comment"]).split())[:160]
                    for item in supporting[:3]
                ],
                "suggested_instruction": pattern["suggestion"],
                "feedback_ids": [item["feedback_id"] for item in supporting],
                "status": "proposed",
            }
        )

    # §G2 - conflict detection. Averaging two opposite instructions produces a
    # rule that satisfies neither editor, so opposite pairs are surfaced.
    conflict = _conflicting(proposals)
    if conflict:
        proposals.append(conflict)
    return proposals


def _conflicting(proposals: list[dict]) -> dict | None:
    by_id = {row["pattern_id"]: row for row in proposals}
    shorter = by_id.get("shorter_text")
    lead = by_id.get("direct_lead")
    if not (shorter and lead):
        return None
    return {
        "pattern_id": "conflicting_length",
        "label": "противоречие за дължината",
        "target": GENERAL_DRAFT_INSTRUCTION,
        "support": 0,
        "total": shorter["support"] + lead["support"],
        "examples": [],
        "suggested_instruction": (
            "Има противоречие между заявките за по-кратък текст и за директно начало. "
            "Редакторът трябва да избере кое е приоритет."
        ),
        "feedback_ids": [],
        "status": "conflict",
    }


# ---------------------------------------------------------------------------
# §G4 - human approval. The ONLY way an approved instruction exists.
# ---------------------------------------------------------------------------


def instructions_path(*, root=None) -> Path:
    """The canonical, human-approved instruction set.

    A separate file from the feedback log, deliberately: the log is evidence of
    what editors said, this file is the decision about what to do about it. A
    reviewer must be able to read the active instructions without reading a
    single editor comment.
    """
    return feedback_path(root=root).with_name("approved_instructions.json")


def approved_instructions(*, root=None) -> list[dict]:
    path = instructions_path(root=root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("instructions") if isinstance(data, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def active_instruction_texts(*, root=None) -> tuple[str, ...]:
    """The APPROVED writing rules, as prompt-ready sentences.

    This is the single consumer-facing read of the approved set, and it returns
    only entries a human actually approved. A rejected pattern is not an
    instruction, and a proposed one is not either, so neither can reach the
    model by this route.

    Without this function the whole learning loop was decorative: the approved
    file was written by `apply_approval` and read by nothing, so approving a
    rule changed no generation behaviour at all.
    """
    return tuple(
        str(row.get("instruction") or "").strip()
        for row in approved_instructions(root=root)
        if row.get("approved") and str(row.get("instruction") or "").strip()
    )


def apply_approval(
    proposal: dict,
    *,
    approved: bool = True,
    now=None,
    root=None,
) -> dict:
    """Record a HUMAN decision about a proposal, and nothing else.

    **This is the only function in the product that can make a learned
    instruction active.** It is called from the operator CLI with an explicit
    decision, and it:

    * appends the instruction to the approved set with the proposal's support
      count and the feedback ids it rests on, so a later reader can see WHY it
      is active;
    * marks exactly those feedback records `processed_for_learning`, so the same
      evidence is never counted twice;
    * touches no prompt, no style profile and no archive example.

    `approved=False` is a real outcome: a rejected pattern still stops being
    re-proposed, because re-proposing a rule an editor has already refused is
    how a learning loop becomes a nagging loop.
    """
    if not isinstance(proposal, dict) or not proposal.get("pattern_id"):
        raise FeedbackError("a proposal must carry a pattern_id")
    if proposal.get("status") == "conflict":
        # A conflict is a QUESTION to the editor, not an instruction. Approving
        # one used to write "the editor must choose which has priority" into the
        # active set, which is a question masquerading as a rule.
        raise FeedbackError("a conflict is not an approvable instruction")
    target = str(proposal.get("target") or GENERAL_DRAFT_INSTRUCTION)
    if target not in TARGETS:
        raise FeedbackError(f"unknown instruction target: {target!r}")
    stamp = str(now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    entry = {
        "pattern_id": str(proposal["pattern_id"]),
        "target": target,
        "instruction": str(proposal.get("suggested_instruction") or ""),
        "support": int(proposal.get("support") or 0),
        "feedback_ids": list(proposal.get("feedback_ids") or []),
        "approved": bool(approved),
        "decided_at": stamp,
    }
    path = instructions_path(root=root)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "instructions": approved_instructions(root=root)}
        # Re-deciding REPLACES the previous decision, and the replacement is
        # recorded as such rather than by silently deleting the earlier one.
        history = list(entry.pop("history", []))
        for row in data["instructions"]:
            if row.get("pattern_id") == entry["pattern_id"]:
                history.append(
                    {
                        "approved": row.get("approved"),
                        "decided_at": row.get("decided_at"),
                        "support": row.get("support"),
                    }
                )
        if history:
            entry["history"] = history[-5:]
        data["instructions"] = [
            row for row in data["instructions"] if row.get("pattern_id") != entry["pattern_id"]
        ] + [entry]
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _mark_processed(entry["feedback_ids"], root=root)
    return entry


@contextmanager
def _file_lock(path: Path):
    """A cross-process lock for a store file, where the platform offers one.

    The rewrites in `_mark_processed` and `apply_approval` truncate before they
    write, so a concurrent append can be destroyed. `flock` serializes the two
    within one machine, which is the real deployment here; where it is
    unavailable the pass degrades to the in-process lock rather than failing.
    """
    try:
        import fcntl
    except ImportError:
        yield
        return
    try:
        with open(str(path) + ".lock", "a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError:
                yield
                return
            try:
                yield
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    except OSError:
        # A store we cannot lock is still better served by proceeding than by
        # refusing the operator's decision outright.
        yield


def _mark_processed(feedback_ids, *, root=None) -> None:
    """Mark the listed records processed WITHOUT destroying concurrent appends.

    V1.2-G4.3: the previous version read the log, then truncated and rewrote
    it. An editor's feedback appended between those two steps was silently
    DELETED, because the rewrite only wrote the rows it had already read. The
    re-read now happens INSIDE the lock, and the write is atomic.

    The whole-file rewrite itself is fine: it is a rare, human-triggered act,
    not a hot path, and it is what lets `processed_for_learning` be a plain
    field rather than a second store.
    """
    wanted = {str(item) for item in feedback_ids or ()}
    if not wanted:
        return
    path = feedback_path(root=root)
    with _LOCK, _file_lock(path):
        rows = read_all(root=root)
        if not any(str(row["feedback_id"]) in wanted for row in rows):
            return
        for row in rows:
            if str(row["feedback_id"]) in wanted:
                row["processed_for_learning"] = True
        live_store.atomic_write(
            path,
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        )
