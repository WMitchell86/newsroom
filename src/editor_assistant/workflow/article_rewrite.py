"""V1.2-G4.3 §E - `Пренапиши`: a new version of THIS Article, from a comment.

**The product decision.** An editor with a Draft does not need a new Article,
a new state, or a new research pass. They need to say, in ordinary language,
what is wrong with the text - and get a better version of the same article.
That is this module, and it is the natural continuation of the writing desk.

**What it is NOT**, each of which was an explicit requirement:

* not a new Article - the same `article_id`, the same Story, the same Focus;
* not a new state - `Чернова` stays `Чернова`;
* not finalization - readiness is withdrawn exactly as any content change does;
* not Research - §E2 forbids re-searching on every rewrite, because latency and
  cost are the editor's time too. `Проучи още` remains the explicit way to add
  facts, and a comment that explicitly asks for research is honoured by the
  caller running that action, not by a hidden web round here.

**§E3 - the old text is never destroyed.** A rewrite publishes through the
SAME versioned content store the first Draft used, so each rewrite appends a new
immutable content version and the previous text stays readable on disk. No new
versioning subsystem is introduced; the newsroom already had exactly the right
one, and this is the reuse the brief asks for.

**§E4 - failure preserves everything.** A failed rewrite leaves the current
body, keeps the editor's comment for the retry, and returns a stable code. It
never writes a blank Article and never loses the words the editor typed.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from editor_assistant.workflow import (
    angles,
    article_generation,
    editor_article_store,
    live,
    live_store,
    rewrite_feedback,
    story_operations,
)
from editor_assistant.workflow import ideas as ideas_mod
from editor_assistant.workflow.workbench import state as pipeline_state

#: Operation scope prefix. A rewrite is a distinct bounded operation from the
#: first Draft, so it gets its own scope and its own in-flight guard.
SCOPE_PREFIX = "article-rewrite:"

#: E4 - the stable failure classes an editor can act on. Anything not listed is
#: an unclassified transport problem and stays retryable.
OP_INVALID_TRANSITION = "INVALID_TRANSITION"
OPERATION_ERRORS = {
    "NOT_IN_DRAFT": (
        "NOT_IN_DRAFT",
        "Пренаписването е възможно само върху съществуваща чернова.",
        False,
    ),
    "EMPTY_COMMENT": (
        "EMPTY_COMMENT",
        "Напишете какво да се промени, преди да пренапишете.",
        False,
    ),
    "ARTICLE_VERSION_CONFLICT": (
        "ARTICLE_VERSION_CONFLICT",
        "Черновата е променена в друга сесия. Няма загубени локални промени.",
        False,
    ),
    "REWRITE_UNAVAILABLE": (
        "REWRITE_UNAVAILABLE",
        "Пренаписването не можа да се завърши. Опитайте отново.",
        True,
    ),
}
DEFAULT_OPERATION_ERROR = (
    "REWRITE_UNAVAILABLE",
    "Пренаписването не можа да се завърши. Опитайте отново.",
    True,
)

_LOCK = threading.RLock()
_ACTIVE: dict[str, str] = {}


class RewriteRefused(RuntimeError):
    """A stable, already-classified rewrite refusal. The code is the contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def scope_for(article_id: str) -> str:
    return f"{SCOPE_PREFIX}{article_id}"


def is_rewrite_scope(scope: str) -> bool:
    return str(scope or "").startswith(SCOPE_PREFIX)


def operation_error(code: str) -> dict:
    """The bounded, sanitized error envelope for a failed rewrite."""
    name, message, retryable = OPERATION_ERRORS.get(code, DEFAULT_OPERATION_ERROR)
    return {"code": name, "message": message, "retryable": retryable}


def active_token(article_id: str) -> str:
    """A rewrite for this Article that is still pending/running, if any."""
    
    with _LOCK:
        token = _ACTIVE.get(article_id, "")
    if not token:
        return ""
    row = story_operations.get(token)
    if row is None or row["status"] not in {"pending", "running"}:
        return ""
    return token


def acquire(article_id: str, token: str) -> None:
    with _LOCK:
        current = _ACTIVE.get(article_id, "")
        if current and current != token:
            raise RewriteRefused("INVALID_TRANSITION", "Вече се пренаписва тази статия.")
        _ACTIVE[article_id] = token


def release(article_id: str, token: str) -> None:
    with _LOCK:
        if _ACTIVE.get(article_id) == token:
            _ACTIVE.pop(article_id, None)


def editorial_root(root=None) -> Path:
    return Path(root or pipeline_state.workflow_dir())


def _rewrite_evidence_prefix(article_id: str) -> str:
    """Rewrites get their own evidence ids.

    They are a DIFFERENT generation from the first Draft - a new text from a new
    instruction - and they must never collide with or reopen the first Draft's
    case. A distinct prefix makes each rewrite a separate, traceable attempt.
    """
    return "EV-RW-" + hashlib.sha256(f"article-rewrite\0{article_id}".encode()).hexdigest()[:10]


def evaluate(*, article: dict, content: dict, comment: str) -> None:
    """Re-evaluate every rewrite precondition from canonical state.

    The check is deliberately narrow and is about the EDITOR's situation, not
    about research: an Article that has text and a comment can be rewritten. It
    does NOT re-assert Draft eligibility, because an existing Draft is by
    definition no longer Draft-eligible and refusing on that would make
    `Пренапиши` impossible exactly when it is needed.
    """
    text = str(comment or "").strip()
    if not text:
        code, message, _retryable = OPERATION_ERRORS["EMPTY_COMMENT"]
        raise RewriteRefused(code, message)
    if article.get("finalized_at") or not str(content.get("body") or "").strip():
        # A finalized Article is immutable, and an Article with no text has
        # nothing to rewrite: both are the same honest answer to the editor.
        code, message, _retryable = OPERATION_ERRORS["NOT_IN_DRAFT"]
        raise RewriteRefused(code, message)


def _attempts(editorial: Path, prefix: str) -> int:
    path = editorial / "live_evidence.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.open(encoding="utf-8") if prefix in line)


def _voice_for(article: dict) -> str:
    """The Voice this rewrite must use, resolved from the editor's choice.

    §D: an empty choice means AUTOMATIC, which is exactly the historical
    default the pipeline already uses. A named choice is passed through
    unchanged, and the style system validates it.
    """
    chosen = str(article.get("editorial_voice") or "").strip()
    return chosen or live.DEFAULT_VOICE


#: V1.2-G4.18. The three lengths the editor may ask for on a rewrite.
#:
#: Measured before this existed: an editor typed "разшири до пълна статия"
#: and got a SHORTER draft back, because the material is auto-suggested
#: MODE_BRIEF and that mode's prompt says "1-2 dense paragraphs, do not
#: inflate to a feature". The instruction and the mode were fighting and the
#: mode won without saying so.
#:
#: The bounds are instructions to the writer, not a post-hoc truncation, and
#: they never ask for a single new fact — the factual gate is unchanged. They
#: are deliberately in the same words the editor picked, so the prompt never
#: says something the UI did not show.
REWRITE_LENGTHS = {
    "short": "КРАТКО: 2-3 абзаца, само най-важното. Без разширяване.",
    "standard": "СТАНДАРТНО: 4-6 абзаца с водещ абзац, ключовите факти и "
                "кратък контекст. Без повторения и без раздуване.",
    "full": "ПЪЛНА СТАТИЯ: 7-10 абзаца с водещ абзац, фактите от източника "
            "изредени, кратък контекст и завършващ извод. Без нови факти извън "
            "доказаните.",
}


def _with_length(comment: str, length: str) -> str:
    """The editor's words, plus the length they chose, as one instruction.

    The length is a request about FORM, never about facts: adding a clause
    here does not touch the factual gate, so a longer draft still has to pass
    every check a short one does.
    """
    instruction = REWRITE_LENGTHS.get(str(length or "").strip())
    if not instruction:
        return comment
    return f"{comment.strip()}\n\n{instruction}".strip() if comment.strip() else instruction


def rewrite(
    *,
    article: dict,
    content: dict,
    comment: str,
    mode: str = "",
    length: str = "",
    snapshot: dict,
    root=None,
    now=None,
) -> dict:
    """Produce a new content version of THIS Article from the editor's comment.

    `snapshot` is the SAME canonical basis the first Draft used - the Story's
    facts, its opened sources and its gaps - read by the application layer. §E2
    is honoured by construction: this function never calls search, never calls
    research and never promotes a fact, so the factual basis of the new text is
    identical to the factual basis of the old one by definition rather than by
    careful bookkeeping.

    Returns a small internal mapping; raises `RewriteRefused` before anything is
    published if the preconditions or the generation fail.
    """
    editorial = editorial_root(root)
    article_id = article["article_id"]
    text = " ".join(str(comment or "").split())
    evaluate(article=article, content=content, comment=text)

    # V1.2-G4.3 - the module lock guards the store mutations BELOW, and is
    # deliberately NOT held across `generate_draft`, which is a blocking model
    # call of up to 240 s. Holding it there blocked `start_article_rewrite` for
    # every OTHER Article for the whole generation, because the guard functions
    # take the same lock.
    with _LOCK:
        prefix = _rewrite_evidence_prefix(article_id)
        evidence_id = f"{prefix}-{_attempts(editorial, prefix) + 1:02d}"
        # §E1 - the packet is the current factual basis, built by the SAME
        # adapter the first Draft used, so the rewrite is grounded exactly like
        # the original and the audit gates mean what they meant before.
        packet = article_generation.build_packet(snapshot, evidence_id)
        # The rewrite still starts from the current canonical headline and the
        # editor's own Focus: a comment can change how the article reads, never
        # silently replace what the article is about.
        idea = live.new_idea(
            source_type="story_research_basis",
            source_url=packet["source_url"],
            title=packet["source_headline"] or content.get("title") or "Работа за статия",
            what_changed=str(snapshot.get("summary") or packet["source_headline"] or ""),
        )
        ideas_mod.save_ideas(
            [*ideas_mod.read_ideas(editorial / "ideas.jsonl"), idea],
            editorial / "ideas.jsonl",
        )
        live_store.save_live_evidence_row(
            {
                "evidence_id": evidence_id,
                "idea_id": idea["idea_id"],
                "packet": packet,
                "observed_at": packet["observed_at"],
            },
            path=editorial / "live_evidence.jsonl",
        )
        try:
            # V1.2-G4.18. Measured: this Article's material (3 facts, 369 chars) is
            # auto-suggested MODE_BRIEF, whose prompt says "1-2 dense paragraphs, do
            # not inflate to a feature". So an editor who typed "разшири" got a
            # SHORTER draft back — the instruction and the mode were fighting, and
            # the mode won silently. An explicit mode now overrides the suggestion.
            prepared = pipeline_state.prepare_case(idea["idea_id"], evidence_id, mode=mode)
        except angles.AngleError as exc:
            raise RewriteRefused(
                "REWRITE_UNAVAILABLE", "Материалът не може да бъде подготвен за пренаписване."
            ) from exc
        except pipeline_state.WorkbenchError as exc:
            raise RewriteRefused(
                "REWRITE_UNAVAILABLE", "Материалът не може да бъде подготвен за пренаписване."
            ) from exc
        if prepared.get("status") == angles.NO_ANGLE:
            raise RewriteRefused(
                "REWRITE_UNAVAILABLE", "За този материал няма публикуем ъгъл."
            )

    # ---- store mutations above; the MODEL CALL below runs WITHOUT the lock ----
    voice = _voice_for(article)
    try:
        outcome = pipeline_state.generate_draft(
            idea["idea_id"],
            evidence_id,
            force=True,
            # §E2 - the honest recorded reason for the same override the
            # first Draft uses: a rewrite is explicitly requested on
            # material the editor has already seen and judged draftable.
            force_reason=(
                "V1.2-G4.3 §E: пренаписване по изрично редакторско указание. "
                "Материалът е проверен от редактора; липсващото покритие остава "
                "предупреждение, не отказ."
            ),
            # §B/E1 - the editorial context and the editor's own words.
            title=str(content.get("title") or ""),
            focus=str(article.get("editorial_focus") or ""),
            # The length choice is the EDITOR's instruction, so it travels as
            # one: prepended to their own words rather than hidden in a system
            # section, so what the model is told is what the editor can see.
            editor_comment=_with_length(text, length),
            voice=voice,
            # G4: the human-approved permanent rules apply here too, not
            # only to a first Draft.
            learned_instructions=rewrite_feedback.active_instruction_texts(
                root=editorial
            ),
        )
    except angles.AngleError as exc:
        raise RewriteRefused(
            "REWRITE_UNAVAILABLE", "Материалът още не е оценен за ъгъл."
        ) from exc
    except pipeline_state.WorkbenchError as exc:
        raise RewriteRefused(
            "REWRITE_UNAVAILABLE", "Пренаписването не можа да се извърши."
        ) from exc
    if outcome.get("status") != "DRAFTED":
        raise RewriteRefused(
            "REWRITE_UNAVAILABLE", "Пренаписването не можа да се извърши."
            )

    case = _find_case(editorial, str(outcome.get("case_id") or ""))
    draft_id = str((case.get("lineage") or {}).get("draft_id") or "")
    body = str(case.get("draft_text") or "")
    if not draft_id or not body.strip():
        # §E4 - a generation without real text is a failed generation. Writing it
        # would replace the editor's draft with a blank Article.
        raise RewriteRefused("REWRITE_UNAVAILABLE", "Пренаписването не върна текст.")

    version_before = int(content["content_version"])
    try:
        published = editor_article_store.publish_generated_draft(
            article_id,
            version_before,
            # §E3 - the title is the editor's own; a rewrite changes the text, not
            # the headline the editor is working under.
            title=str(content.get("title") or ""),
            body=body,
            internal_refs={
                "idea_id": idea["idea_id"],
                "evidence_id": evidence_id,
                "case_id": str(case["case_id"]),
                "draft_id": draft_id,
            },
            # The material basis is UNCHANGED by design (§E2), so the Draft keeps
            # exactly the warnings its factual basis already justified.
            draft_material_basis=article_generation.material_basis(snapshot),
            now=now,
            root=editorial,
        )
    except editor_article_store.ArticleVersionConflict as exc:
        # §E4 - the editor's own text moved on. Their body survives untouched.
        raise RewriteRefused("ARTICLE_VERSION_CONFLICT", str(exc)) from exc
    except editor_article_store.ArticleStoreError as exc:
        raise RewriteRefused("REWRITE_UNAVAILABLE", str(exc)) from exc

    version_after = int(published["content_version"])
    # §F - the feedback record is written AFTER a successful publish and also on
    # the failure paths in the caller, because a request the editor made and the
    # product could not satisfy is still real editorial signal.
    _record_feedback(
        article=article,
        comment=text,
        version_before=version_before,
        version_after=version_after,
        root=editorial,
        now=now,
    )
    return {
        "case_id": str(case["case_id"]),
        "draft_id": draft_id,
        "content_version": version_after,
        "voice": voice,
    }


def _record_feedback(
    *, article: dict, comment: str, version_before: int, version_after: int, root=None, now=None
) -> None:
    """Persist the compact feedback record for one rewrite. Never raises."""
    try:
        rewrite_feedback.record(
            article_id=article["article_id"],
            # The audit trail records the editor's WORDS, not the instruction
            # this function added on top of them. What the model was told is
            # recorded above, at the call that told it.
            editor_comment=comment,
            focus=str(article.get("editorial_focus") or ""),
            voice=str(article.get("editorial_voice") or ""),
            draft_version_before=version_before,
            draft_version_after=version_after,
            generated_by_model=True,
            now=now,
            root=root,
        )
    except (rewrite_feedback.FeedbackError, OSError):
        # §F - learning is a side effect of a rewrite, never a precondition for
        # one. A failure to log must not cost the editor their new text.
        pass


def _find_case(editorial: Path, case_id: str) -> dict:
    """The internal Case row, or `{}`. A missing store is not an error."""
    import json

    path = editorial / "cases.jsonl"
    if not case_id or not path.exists():
        return {}
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("case_id") == case_id:
            return row
    return {}
