"""C2 — the one editor-facing Article Draft command (`MAKE_DRAFT`).

**Orchestration only.** This module adds no generation, prompt, audit, packet or
case logic of its own. Every generation step delegates to the mature, already
exercised live pipeline:

* `live.new_idea` and `workbench.state.prepare_case` — the IdeaCard, the
  canonical draftability guard, the angle gate and the mode suggestion;
* `workbench.state.generate_draft` — readiness gating, style retrieval, the
  model call, the lexical and semantic factual gates, the deterministic
  originality guard, the immutable generated Draft and the internal Case;
* `evidence` / `research` — the M2.3B packet contract and claim provenance;
* `editor_article_store` — the validated atomic Article writes.

The only new work here is the narrow adapter that turns the canonical Story
evidence basis into one EvidencePacket, and the re-evaluation of the editor
preconditions. Nothing here invents a fact, a quote or a source.

**Preconditions are re-evaluated, never trusted.** A command is accepted only
when the backend itself currently offers `MAKE_DRAFT` for that Article. The same
evaluation runs again immediately before any model call, so an editor edit that
landed while the operation was queued fails the operation instead of overwriting
that text.

**Failure never leaves a fabricated Article.** A provider failure, a refusal or
a safety stop writes no Draft, no Case and no Article content. On success the
immutable Draft and the internal Case are appended first, then the immutable
working-content document, and only then the Article record that points at the
new version and carries the internal refs — so an interrupted run leaves the
previous content version readable instead of a half-published Article.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.drafting import evidence as evidence_mod
from editor_assistant.workflow import (
    angles,
    blocked_domains,
    editor_article_store,
    editor_projections,
    live,
    live_store,
    story_operations,
)
from editor_assistant.workflow import ideas as ideas_mod
from editor_assistant.workflow import research as research_mod
from editor_assistant.workflow.workbench import state as pipeline_state

#: Operation scope prefix for this command. It is not a Story id: it only tells
#: the shared bounded-operation registry which editor wording a transport result
#: belongs to.
SCOPE_PREFIX = "article-draft:"

#: Editor wording for every stable failure this command can end in. Anything not
#: listed here is a provider/transport problem and stays retryable.
_OPERATION_ERRORS = {
    "BLOCKING_GAP": (
        "BLOCKING_GAP",
        "Има непопълнена информация, която пречи да продължите.",
        False,
    ),
    "SAFETY_BLOCKED": ("SAFETY_BLOCKED", "Проверката за безопасност спря операцията.", False),
    "INVALID_TRANSITION": (
        "INVALID_TRANSITION",
        "Това действие не е налично в текущото състояние.",
        False,
    ),
    "ARTICLE_VERSION_CONFLICT": (
        "ARTICLE_VERSION_CONFLICT",
        "Черновата е променена в друга сесия. Няма загубени локални промени.",
        False,
    ),
    "DRAFT_UNAVAILABLE": (
        "DRAFT_UNAVAILABLE",
        "Черновата не може да бъде създадена от този материал.",
        False,
    ),
}
_DEFAULT_OPERATION_ERROR = (
    "SOURCE_UNAVAILABLE",
    "Черновата не можа да бъде създадена. Опитайте отново.",
    True,
)

#: In-process guard, one canonical generation per Article. It complements the
#: bounded operation registry, which stops a retried *request* from duplicating
#: work but cannot know about a second command carrying a fresh key.
_LOCK = threading.RLock()
_ACTIVE: dict[str, str] = {}


class DraftRefused(RuntimeError):
    """A stable, already-classified refusal. The reason code is the contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def scope_for(article_id: str) -> str:
    return f"{SCOPE_PREFIX}{article_id}"


def is_draft_scope(scope: str) -> bool:
    return str(scope or "").startswith(SCOPE_PREFIX)


def operation_error(code: str) -> dict:
    """The bounded, sanitized error envelope for a failed draft operation."""
    code_name, message, retryable = _OPERATION_ERRORS.get(code, _DEFAULT_OPERATION_ERROR)
    return {"code": code_name, "message": message, "retryable": retryable}


def active_token(article_id: str) -> str:
    """A draft operation for this Article that is still pending/running, if any."""
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
            raise DraftRefused("INVALID_TRANSITION", "Черновата за тази статия вече се създава.")
        _ACTIVE[article_id] = token


def release(article_id: str, token: str) -> None:
    with _LOCK:
        if _ACTIVE.get(article_id) == token:
            _ACTIVE.pop(article_id, None)


def editorial_root(root=None) -> Path:
    return Path(root or pipeline_state.workflow_dir())


def _evidence_prefix(article_id: str) -> str:
    return "EV-ART-" + hashlib.sha256(f"article-draft\0{article_id}".encode()).hexdigest()[:10]


def _attempts(editorial: Path, prefix: str) -> int:
    """How many generation attempts this Article already left in the evidence store."""
    path = editorial / "live_evidence.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.open(encoding="utf-8") if prefix in line)


def _today(assessed_at: str) -> str:
    stamp = str(assessed_at or "")[:10]
    return stamp or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def evaluate(snapshot: dict) -> None:
    """Re-evaluate every editor precondition from canonical state.

    Raises `DraftRefused` with a stable reason code. It runs once when the
    command is accepted and again inside the worker, so nothing here depends on
    any value the client sent.
    """
    article = snapshot["article"]
    content = snapshot["content"]
    story = snapshot["story"]
    if article.get("finalized_at"):
        raise DraftRefused("INVALID_TRANSITION", "Финализирана статия не може да получи чернова.")
    if story.get("story_id") != article.get("story_id"):
        raise DraftRefused("INVALID_TRANSITION", "Историята на статията вече не е достъпна.")
    if story.get("status") == "IGNORED":
        raise DraftRefused("INVALID_TRANSITION", "Игнорирана Story не може да получи чернова.")
    if int(content.get("content_version", -1)) != int(snapshot["content_version"]):
        # The editor typed (or another command wrote) while this command was
        # queued. Generating now would silently discard that text.
        raise DraftRefused(
            "ARTICLE_VERSION_CONFLICT",
            "Статията е променена, преди черновата да се създаде. Няма загубени локални промени.",
        )
    if str(content.get("body") or "").strip():
        raise DraftRefused("INVALID_TRANSITION", "Статията вече има текст.")
    if not str(content.get("title") or "").strip():
        raise DraftRefused("INVALID_TRANSITION", "Работното заглавие не може да е празно.")
    if not editor_projections.focus_is_confirmed(article):
        raise DraftRefused("INVALID_TRANSITION", "Потвърдете фокуса, преди да правите чернова.")
    if snapshot["blocking_gaps"]:
        raise DraftRefused("BLOCKING_GAP", "Има непопълнена информация, която пречи да продължите.")
    if not snapshot["facts"]:
        raise DraftRefused("BLOCKING_GAP", "Няма потвърдени факти от източници.")
    url = str(snapshot.get("source_url") or "")
    if not url:
        raise DraftRefused("BLOCKING_GAP", "Няма отворен източник за тази история.")
    # Safety: the same two guards the mature pipeline applies to any factual
    # input, re-checked here so a blocked or circular source can never reach a
    # model call from the editor surface.
    if live.is_chernomorie_source(url):
        raise DraftRefused("SAFETY_BLOCKED", "Проверката за безопасност спря операцията.")
    if blocked_domains.is_blocked(url):
        raise DraftRefused("SAFETY_BLOCKED", "Проверката за безопасност спря операцията.")


def build_packet(snapshot: dict, evidence_id: str) -> dict:
    """Adapt the canonical Story basis into one M2.3B EvidencePacket.

    Every fact is a verbatim canonical fact and carries claim-level provenance
    (`source_id` + locator) into the Story's own opened sources, so the drafting
    gate audits exactly the material the editor was shown. No fact is invented,
    reworded or dropped, and the remaining open questions travel with the packet
    as `unknowns` so the drafter cannot fill them in.
    """
    facts = []
    for index, fact in enumerate(snapshot["facts"], start=1):
        source = fact.get("source") or {}
        source_id = str(source.get("id") or "")
        locator = str(fact.get("locator") or source.get("url") or source_id)
        made = evidence_mod.make_fact(
            f"{evidence_id}-f{index:02d}",
            str(fact.get("text") or ""),
            source_reference=f"{source_id}:{locator}",
            scope=(
                "historical_background" if fact.get("scope") == "background" else "current_event"
            ),
        )
        made["source_refs"] = [research_mod.make_fact_ref(source_id, locator)]
        facts.append(made)
    packet = {
        "evidence_id": evidence_id,
        "source_url": str(snapshot["source_url"]),
        "source_type": "story_research_basis",
        "observed_at": _today(snapshot.get("assessed_at")),
        "source_headline": str(snapshot.get("headline") or ""),
        "facts": facts,
        # Entity lists stay empty rather than guessed: the mature builder's
        # regex finds are for scraped documents, and a wrong entity is a
        # fabrication. Dates and numbers stay inside the canonical fact text.
        "people": [],
        "organizations": [],
        "places": [],
        "dates": [],
        "numbers": [],
        "quotes": [],
        "unknowns": [str(item.get("question") or "") for item in snapshot["gaps"]],
        "source_text": "\n".join(str(fact.get("text") or "") for fact in snapshot["facts"]),
    }
    evidence_mod.annotate_headline_number_conflicts(packet)
    evidence_mod.validate_packet(packet)
    return packet


def _persist_idea(idea: dict, editorial: Path) -> None:
    path = editorial / "ideas.jsonl"
    rows = ideas_mod.read_ideas(path) if path.exists() else []
    rows = [row for row in rows if row["idea_id"] != idea["idea_id"]] + [idea]
    ideas_mod.save_ideas(rows, path)


def _find_case(editorial: Path, case_id: str) -> dict:
    """The internal Case row, or `{}`. A missing store is not an error."""
    path = editorial / "cases.jsonl"
    if not path.exists():
        return {}
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("case_id") == case_id:
            return row
    return {}


def generate(snapshot: dict, *, root=None, now=None) -> dict:
    """Run the whole Draft command for one Article and return its internal ids.

    The returned mapping is internal (`case_id`, `draft_id`, `evidence_id`,
    `idea_id`); the editor API never exposes it. A refusal raises `DraftRefused`
    before anything is published, so a failed command leaves the Article exactly
    as the editor last confirmed it.
    """
    editorial = editorial_root(root)
    article = snapshot["article"]
    article_id = article["article_id"]
    evaluate(snapshot)
    with _LOCK:
        prefix = _evidence_prefix(article_id)
        evidence_id = f"{prefix}-{_attempts(editorial, prefix) + 1:02d}"
        packet = build_packet(snapshot, evidence_id)
        idea = live.new_idea(
            source_type="story_research_basis",
            source_url=packet["source_url"],
            title=packet["source_headline"] or "Работа за статия",
            what_changed=str(snapshot.get("summary") or packet["source_headline"] or ""),
        )
        _persist_idea(idea, editorial)
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
            prepared = pipeline_state.prepare_case(idea["idea_id"], evidence_id, mode="")
        except angles.AngleError as exc:
            # The angle gate refused the material (typically: this kind of source
            # needs assessed editorial angles before it may be drafted). That is
            # incomplete editorial material, reported as a stable gap - never
            # bypassed by inventing an assessment.
            raise DraftRefused("BLOCKING_GAP", "Материалът още не е оценен за ъгъл.") from exc
        except pipeline_state.WorkbenchError as exc:
            raise DraftRefused(
                "DRAFT_UNAVAILABLE", "Материалът не може да бъде подготвен."
            ) from exc
        if prepared.get("status") == angles.NO_ANGLE:
            # The angle gate closed the IdeaCard. No draft, no case, no Article
            # change - the material stays exactly as the editor saw it.
            raise DraftRefused("BLOCKING_GAP", "За този материал няма публикуем ъгъл.")
        try:
            outcome = pipeline_state.generate_draft(idea["idea_id"], evidence_id)
        except angles.AngleError as exc:
            raise DraftRefused("BLOCKING_GAP", "Материалът още не е оценен за ъгъл.") from exc
        except pipeline_state.WorkbenchError as exc:
            raise DraftRefused(
                "DRAFT_UNAVAILABLE", "Материалът не може да бъде подготвен за чернова."
            ) from exc
        if outcome.get("status") != "DRAFTED":
            # A readiness or angle refusal. The pipeline recorded its own
            # refusal state; this command publishes no content.
            raise DraftRefused("BLOCKING_GAP", "Доказателствата още не са достатъчни за чернова.")
        case = _find_case(editorial, str(outcome.get("case_id") or ""))
        draft_id = str((case.get("lineage") or {}).get("draft_id") or "")
        body = str(case.get("draft_text") or "")
        if not case or not draft_id or not body.strip():
            # A generation without real text is a failed generation: publishing
            # it would fabricate a Draft.
            raise DraftRefused("DRAFT_UNAVAILABLE", "Черновата не можа да бъде създадена.")
        internal_refs = {
            "idea_id": idea["idea_id"],
            "evidence_id": evidence_id,
            "case_id": str(case["case_id"]),
            "draft_id": draft_id,
        }
    # The immutable Draft and the internal Case are already durable. The
    # working-content document is written next; the Article record - the atomic
    # current-version pointer that also carries the internal refs - is written
    # last, so an interrupted run leaves the previous version readable.
    editor_article_store.publish_generated_draft(
        article_id,
        snapshot["content_version"],
        title=snapshot["content"]["title"],
        body=body,
        internal_refs=internal_refs,
        now=now,
        root=editorial,
    )
    return {
        "case_id": internal_refs["case_id"],
        "draft_id": draft_id,
        "evidence_id": evidence_id,
        "idea_id": internal_refs["idea_id"],
        "headline": str(case.get("draft_headline") or ""),
        "factual_gate": str(case.get("factual_gate") or ""),
    }


def warnings_for(article: dict, content: dict, *, root=None) -> list[dict]:
    """DEPRECATED in C4 — the generation audit is not the editor's warning source.

    A generation audit belongs to the immutable generated content version, not
    to arbitrary later editor text, and C4 validates the CURRENT working
    content instead (see `article_validation.evaluate_current_content`). This
    projection is kept only so the generation-time Case audit stays inspectable
    in the workbench; no editor path may read it any more: doing so is exactly
    the stale-warning bug C4 closes.
    """
    if article.get("generated_content_version") != content.get("content_version"):
        return []
    case_id = str((article.get("internal_refs") or {}).get("case_id") or "")
    if not case_id:
        return []
    try:
        case = _find_case(editorial_root(root), case_id)
    except (OSError, ValueError):
        return []
    return project_warnings(case, seed=case_id)


def project_warnings(case: dict, *, seed: str = "") -> list[dict]:
    """The editor Warning shape over the real factual and originality audit.

    Every warning is `blocking: false` here: blocking is a readiness/gap
    decision owned by the canonical Story basis, never a consequence of one
    generated sentence. `affectedText` is only ever the editor's own draft text,
    truncated.
    """
    case = case or {}
    audit = case.get("audit") or {}
    semantic = audit.get("semantic") or {}
    lexical = audit.get("lexical") or {}
    originality = audit.get("originality") or {}
    warnings: list[dict] = []

    def add(kind: str, severity: str, message: str, affected: str = "") -> None:
        warnings.append(
            {
                "id": "warn_"
                + hashlib.sha256(f"{seed}\0{kind}\0{len(warnings)}".encode()).hexdigest()[:15],
                "severity": severity,
                "message": message,
                "blocking": False,
                **({"affectedText": affected} if affected else {}),
            }
        )

    if str(case.get("factual_gate")) == "FACTUAL_GATE_REVIEW":
        add("gate", "review", "Проверката на фактите изисква преглед преди финализиране.")
    count = semantic.get("n_unsupported")
    if not isinstance(count, int):
        count = len(semantic.get("unsupported") or [])
    if count:
        add(
            "semantic",
            "review",
            f"{count} твърдения в черновата не са подкрепени от източниците. Прегледайте ги.",
        )
    for sentence in list(lexical.get("unsupported") or [])[:5]:
        text = sentence if isinstance(sentence, str) else str((sentence or {}).get("sentence", ""))
        text = " ".join(text.split())[:200]
        if text:
            add("lexical", "review", "Изречение без директна опора в източниците.", text)
    if originality.get("checked") and not originality.get("pass", True):
        add(
            "originality",
            "review",
            "Черновата повтаря дословно текст от източника. Препишете със свои думи.",
        )
    if int(semantic.get("parse_errors") or 0):
        add(
            "parse",
            "info",
            "Проверката на твърденията не е завършена изцяло. Прегледайте черновата.",
        )
    return warnings
