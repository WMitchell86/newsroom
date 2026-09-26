"""Phase B1 editor application queries and commands.

This module is the stable application boundary behind ``/api/v1``. It composes
Phase A stores and projections, returns explicit editor DTOs, and contains no
HTTP parsing, response formatting, provider work, or orchestration.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from editor_assistant.drafting.evidence import EvidenceError, validate_packet
from editor_assistant.workflow import (
    article_draft_failure,
    article_generation,
    article_readiness,
    article_validation,
    editor_article_store,
    editor_projections,
    editor_queries,
    inbox_store,
    live_store,
    newsroom_refresh,
    quick_draft,
    source_health,
    story_editor_metadata,
    story_identity,
    story_operations,
    story_research,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import readiness as readiness_mod
from editor_assistant.workflow import research as research_mod
from editor_assistant.workflow import search as search_mod

ROOT = Path(__file__).resolve().parents[3]
LOG = logging.getLogger(__name__)
_COMMAND_LOCK = threading.RLock()
STORY_FILTERS = ("all", "followed", "developments", "ignored")
ARTICLE_FILTERS = ("all", "preparation", "draft", "ready")
#: Operation scope for the newsroom-wide «Обнови» action (B4B). It is not a
#: Story id: it only tells the shared operation registry which editor wording a
#: transport result belongs to.
REFRESH_SCOPE = "today-refresh"


class EditorApplicationError(ValueError):
    """Base class for errors safe to classify at the API boundary."""

    code = "VALIDATION_ERROR"
    status = 400


class EditorNotFound(EditorApplicationError):
    code = "NOT_FOUND"
    status = 404


class EditorInvalidTransition(EditorApplicationError):
    code = "INVALID_TRANSITION"
    status = 409


class EditorResearchUnavailable(EditorApplicationError):
    code = "SOURCE_UNAVAILABLE"
    status = 503


class EditorVersionConflict(EditorApplicationError):
    code = "ARTICLE_VERSION_CONFLICT"
    status = 409


class EditorDraftNotReady(EditorApplicationError):
    """V1.1-B — the refusal class for every evidence-remedy reason.

    `STORY_UNASSESSED`, `NO_CONFIRMED_FACTS`, `NO_OPEN_SOURCE` and
    `BLOCKING_GAP` are four distinct semantic reasons, not one generic
    "something is missing". They share an HTTP status and a remedy (research the
    owning Story), so they share a class — but the instance `code` is always the
    exact readiness code, never a collapsed umbrella code. The editor and the
    API therefore receive the same string the preparation projection reported.
    """

    status = 409

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class EditorBlockingGap(EditorDraftNotReady):
    """The canonical Story basis still has a blocking gap. No generation.

    A named subclass rather than a separate contract: `BLOCKING_GAP` is one
    member of the `EditorDraftNotReady` family, kept as its own class so
    existing callers that catch it specifically keep working unchanged.
    """

    def __init__(self, message: str):
        super().__init__("BLOCKING_GAP", message)


class EditorSafetyBlocked(EditorApplicationError):
    """A safety or validation guard stopped the command before any write.

    `warnings` carries the editor-safe blocking context the workspace needs to
    explain what must be addressed. It is never a raw audit trace.
    """

    code = "SAFETY_BLOCKED"
    status = 409

    def __init__(self, message: str, *, warnings=None):
        super().__init__(message)
        self.warnings = [dict(row) for row in warnings or []]


class EditorValidationUnavailable(EditorApplicationError):
    """The current content could not be validated. Fail closed, allow a retry.

    This is deliberately NOT "no warnings": an Article whose validation could
    not run is never ready, and the editor gets a calm, sanitized retry.
    """

    code = "INTERNAL_ERROR"
    status = 500


def _newsroom_root() -> Path:
    return Path(
        os.environ.get("WB_NEWSROOM_DIR")
        or os.environ.get("NEWSROOM_DIR")
        or ROOT / "var" / "newsroom"
    )


def _paths() -> dict:
    root = _newsroom_root()
    return {
        "stories": root / "stories.json",
        "inbox": root / "inbox.jsonl",
        "metadata_root": root,
    }


def _editorial_root() -> Path:
    return Path(
        os.environ.get("WB_EDITORIAL_WORKFLOW_DIR") or (ROOT / "var" / "editorial_workflow")
    )


def _opaque_id(prefix: str, *parts: str) -> str:
    seed = "\0".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(seed).hexdigest()[:15]}"


def _story_title(story: dict, items_by_id: dict) -> str:
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    meaningful = editor_projections.meaningful_developments(story, items_by_id)
    latest = meaningful[0] if meaningful else {}
    return str(representative.get("title") or latest.get("title") or "")


_UNSET = object()


def _maybe_story(story_id: str) -> dict | None:
    """The canonical Story, or `None` when its lineage is no longer readable."""
    try:
        return _story(story_id)
    except EditorNotFound:
        return None


def _story_reference(article: dict, items_by_id: dict | None = None, story=_UNSET) -> dict:
    if story is _UNSET:
        story = _maybe_story(article["story_id"])
    if story is None:
        return {"id": article["story_id"]}
    if items_by_id is None:
        items_by_id = _story_items()
    reference = {"id": story["story_id"]}
    title = _story_title(story, items_by_id)
    if title:
        reference["title"] = title
    return reference


def _opened_sources_by_id() -> dict[str, dict]:
    sources: dict[str, dict] = {}
    ambiguous: set[str] = set()
    research_root = _editorial_root() / "research"
    if not research_root.exists():
        return sources
    for path in sorted(research_root.glob("*.json")):
        try:
            bundle = research_mod.load_bundle(path)
        except (OSError, ValueError, AttributeError, TypeError, research_mod.ResearchError):
            continue
        for source_id, source in research_mod.promotable_sources(bundle).items():
            if source_id in ambiguous:
                continue
            previous = sources.get(source_id)
            if previous is not None:
                previous_identity = (previous.get("url"), previous.get("source_name"))
                current_identity = (source.get("url"), source.get("source_name"))
                if previous_identity != current_identity:
                    sources.pop(source_id, None)
                    ambiguous.add(source_id)
                    continue
            sources[source_id] = source
    return sources


def _evidence_rows() -> dict[str, dict]:
    return live_store.read_live_evidence(_editorial_root() / "live_evidence.jsonl")


def _source_projection(source: dict) -> dict:
    url = str(source.get("url") or "")
    projected = {
        "id": str(source.get("id") or source.get("source_id") or ""),
        "name": str(
            source.get("name") or source.get("source_name") or source.get("id") or "Източник"
        ),
        "url": url,
    }
    domain = urlsplit(url).netloc
    if domain:
        projected["domain"] = domain
    return projected


def _legacy_story_evidence(
    story_id: str, articles: list[dict]
) -> tuple[list[dict], list[dict], str]:
    evidence_by_id = _evidence_rows()
    opened = _opened_sources_by_id()
    facts, gaps, assessed = [], [], ""
    for article in sorted(
        (row for row in articles if row.get("story_id") == story_id),
        key=lambda row: row.get("updated_at") or "",
        reverse=True,
    ):
        evidence_id = str((article.get("internal_refs") or {}).get("evidence_id") or "")
        row = evidence_by_id.get(evidence_id)
        packet = (row or {}).get("packet") or {}
        if not row:
            continue
        try:
            validate_packet(packet)
        except EvidenceError:
            continue
        assessed = max(assessed, str(row.get("observed_at") or packet.get("observed_at") or ""))
        for fact in packet.get("facts") or []:
            refs = [ref for ref in fact.get("source_refs") or [] if ref.get("source_id") in opened]
            if not refs:
                continue
            ref = refs[0]
            source = opened[ref["source_id"]]
            facts.append(
                {
                    "id": _opaque_id(
                        "legacy_fact",
                        evidence_id,
                        str(fact.get("id") or ""),
                        str(fact.get("text") or ""),
                    ),
                    "text": str(fact.get("text") or ""),
                    "source": _source_projection(source),
                    "locator": str(ref.get("locator") or ""),
                    "scope": "background"
                    if fact.get("scope") == "historical_background"
                    else "current",
                }
            )
        readiness = row.get("readiness") or {}
        questions = [str(value).strip() for value in packet.get("unknowns") or []]
        if readiness.get("status") == readiness_mod.RESEARCH_MORE:
            suff = readiness.get("sufficiency") or {}
            questions.extend(str(value).strip() for value in suff.get("research_questions") or [])
        for question in questions:
            if question:
                gaps.append(
                    {
                        "id": _opaque_id("legacy_gap", evidence_id, question),
                        "question": question,
                        "kind": "unresolved",
                        "blocking": readiness.get("status") == readiness_mod.RESEARCH_MORE,
                    }
                )
    return facts, gaps, assessed


def _evidence_status(basis) -> str:
    """Canonical V1.1-A evidence status: absence is UNASSESSED, not clean."""
    return story_research_store.evidence_status_of(basis)


def _story_evidence_projection(
    story_id: str, articles: list[dict] | None = None
) -> tuple[list[dict], dict]:
    """Compose verified legacy Article lineage with the canonical Story basis."""
    basis = story_research_store.get_story_research(story_id)
    evidence_status = _evidence_status(basis)
    sources = {item["id"]: item for item in basis["sources"]}
    facts = [
        {
            "id": item["id"],
            "text": item["text"],
            "source": _source_projection(sources[item["sourceId"]]),
            "locator": item["locator"],
            "scope": item["scope"],
        }
        for item in basis["facts"]
    ]
    gaps = list(basis["gaps"])
    assessed_at = basis.get("assessed_at")
    if articles is not None:
        legacy_facts, legacy_gaps, assessed = _legacy_story_evidence(story_id, articles)
        facts.extend(legacy_facts)
        gaps.extend(legacy_gaps)
        if assessed:
            assessed_at = max(assessed_at, assessed) if assessed_at else assessed
            # Verified legacy lineage is itself an assessment: it must never
            # leave an UNASSESSED projection paired with a real timestamp.
            if evidence_status == story_research_store.EVIDENCE_UNASSESSED and (facts or gaps):
                evidence_status = story_research_store.EVIDENCE_ASSESSED
        basis = {
            **basis,
            "assessed_at": assessed_at,
        }
    facts.extend(
        {
            "id": item["id"],
            "text": item["text"],
            "source": _source_projection(sources[item["sourceId"]]),
            "locator": item["locator"],
            "scope": item["scope"],
        }
        for item in basis["facts"]
    )
    seen_facts, seen_gaps = set(), set()
    unique_facts, unique_gaps = [], []
    for fact in facts:
        key = (fact["text"], fact["source"].get("url"), fact.get("locator"))
        if key not in seen_facts:
            seen_facts.add(key)
            unique_facts.append(fact)
    for gap in gaps:
        key = gap["question"]
        if key not in seen_gaps:
            seen_gaps.add(key)
            unique_gaps.append(gap)
    return unique_facts, {
        "items": unique_gaps,
        "assessedAt": assessed_at,
        "evidenceStatus": evidence_status,
    }


def _story(story_id: str) -> dict:
    store = story_store.read_store(_paths()["stories"])
    story = story_store.story_by_id(store, story_id)
    if story is None:
        raise EditorNotFound("Story не е намерена.")
    return story


def _article(article_id: str) -> dict:
    try:
        return editor_article_store.get_editor_article(article_id)
    except editor_article_store.ArticleStoreError as exc:
        if "unknown article_id" in str(exc):
            raise EditorNotFound("Статията не е намерена.") from exc
        raise


def _next_action(action: str, reason: str, label: str, *, primary: bool = True) -> dict:
    return {
        "action": action,
        "reasonCode": reason,
        "label": label,
        "primary": primary,
    }


def _current_validation(
    article: dict,
    content: dict,
    *,
    story: dict | None,
    facts: list[dict],
    gaps: list[dict],
    headline: str,
    assessed_at: str,
) -> tuple[dict, object]:
    """The current-content validation of one Article, read for the editor.

    A read never fabricates a clean result: if the validation itself cannot run,
    the projection reports it as blocking and not current, so the Article can
    never look `Готова` on a check that did not happen.
    """
    try:
        validation = article_validation.evaluate_current_content(
            article,
            content,
            story=story,
            facts=facts,
            gaps=gaps,
            headline=headline,
            assessed_at=assessed_at,
        )
    except article_validation.ValidationUnavailable:
        LOG.exception("current-content validation is unavailable")
        return {
            "contentVersion": int(content.get("content_version", 0)),
            "current": False,
            "blocking": True,
            "readyEligible": False,
        }, None
    return (
        {
            "contentVersion": validation.content_version,
            "current": True,
            "blocking": validation.blocking,
            "readyEligible": False,
        },
        validation,
    )


def validate_article_current_content(article_id: str) -> dict:
    """`validate_article_current_content(article_id)` — the one C4 operation.

    Loads the canonical Article, its exact current content version, the
    canonical Story and the canonical Story evidence basis, validates the Story
    lineage and the current title/body, runs the applicable current-content
    audits, projects editor-facing warnings, classifies blocking vs
    non-blocking and computes the deterministic digest. No workflow entity is
    persisted: this is a pure read over canonical state.
    """
    article = _article(article_id)
    content = editor_article_store.get_article_content(article_id)
    facts, missing = _story_evidence_projection(article["story_id"])
    story = _maybe_story(article["story_id"])
    validation = article_validation.evaluate_current_content(
        article,
        content,
        story=story,
        facts=facts,
        gaps=list(missing["items"]),
        headline=_story_headline(article, story),
        assessed_at=str(missing.get("assessedAt") or ""),
    )
    return {
        "contentVersion": validation.content_version,
        "validationDigest": validation.digest,
        "warnings": [dict(row) for row in validation.warnings],
        "blocking": validation.blocking,
        "validatedAt": validation.validated_at,
    }


def _story_headline(article: dict, story: dict | None, items_by_id: dict | None = None) -> str:
    """The canonical Story headline, used only as packet metadata."""
    if story is None:
        return str(article.get("working_title") or "")
    if items_by_id is None:
        items_by_id = _story_items()
    return _story_title(story, items_by_id) or str(article.get("working_title") or "")


def _article_actions(
    article: dict,
    content: dict,
    state: str | None,
    validation,
    readiness: article_readiness.DraftReadiness | None = None,
    manual_continuation: bool = False,
) -> tuple[list[str], dict | None]:
    """The available actions and the one next action, for the editor.

    **V1.1-B:** `MAKE_DRAFT` is no longer decided here. It comes from the SAME
    `article_readiness` evaluation that `start_article_draft` enforces, so the
    two can never disagree: there is no separate action predicate left to drift.

    **V1.1-C:** `EDIT` on a Preparation Article is a *recovery* path, not an
    alternative to `Направи чернова`. It is offered only when a durable marker
    records that an eligible generation genuinely failed on this exact basis
    (`manual_continuation`), so a clean preparation Article no longer shows it.
    `MAKE_DRAFT` remains the next action when readiness allows, and both are
    offered together after a failure, because a provider outage is worth a retry
    before the editor writes the story by hand.
    """
    if article.get("finalized_at"):
        return [], None
    if state == "preparation":
        if not editor_projections.focus_is_confirmed(article):
            return ["SELECT_FOCUS"], _next_action("SELECT_FOCUS", "FOCUS_REQUIRED", "Избери фокус")
        # Backend-authorized manual continuation uses the same editor and the
        # same atomic content save. There is no separate manual Draft mode.
        actions = ["CHANGE_FOCUS"]
        if manual_continuation:
            actions.append("EDIT")
        readiness = readiness or article_readiness.DraftReadiness(
            eligible=False,
            reason_code=article_readiness.STORY_UNAVAILABLE,
            reason_message=article_readiness.REASON_MESSAGES[article_readiness.STORY_UNAVAILABLE],
        )
        if readiness.eligible:
            actions.append("MAKE_DRAFT")
            return actions, _next_action("MAKE_DRAFT", readiness.reason_code, "Направи чернова")
        # Focus is already confirmed here, so the only remaining refusals are
        # evidence ones. Those whose remedy is research route the editor to the
        # owning Story — which stays the sole owner of research orchestration.
        # A refusal with no research remedy (a stopped safety guard, an
        # unavailable Story) must not pretend that research would help.
        if readiness.is_researchable:
            actions.append("RESEARCH_MORE")
            return actions, _next_action("RESEARCH_MORE", readiness.reason_code, "Проучи още")
        return actions, _next_action("CHANGE_FOCUS", readiness.reason_code, "Промени фокуса")
    if state == "ready":
        # C5 completes the Ready surface: the editor may go back to `Чернова` or
        # freeze this exact validated version. The backend still offers nothing
        # else here - no publish, no approve, no send.
        return ["EDIT", "FINALIZE"], _next_action("FINALIZE", "READY_TO_FINALIZE", "Финализирай")
    actions = []
    if editor_projections.focus_is_confirmed(article):
        actions.append("CHANGE_FOCUS")
        next_action = _next_action("EDIT", "CONTENT_EDIT", "Редактирай")
    else:
        actions.append("SELECT_FOCUS")
        next_action = _next_action("SELECT_FOCUS", "FOCUS_REQUIRED", "Избери фокус")
    actions.append("EDIT")
    if validation is not None and article_validation.ready_eligible(article, content, validation):
        actions.append("MARK_READY")
        return actions, _next_action("MARK_READY", "READY_ELIGIBLE", "Отбележи като готова")
    return actions, next_action


def _article_dto(
    article: dict,
    content: dict,
    story_reference: dict,
    story: dict | None = None,
    items_by_id: dict | None = None,
) -> dict:
    return _article_projection(article, content, story_reference, story, items_by_id)[0]


def _article_projection(
    article: dict,
    content: dict,
    story_reference: dict,
    story: dict | None = None,
    items_by_id: dict | None = None,
) -> tuple[dict, str | None]:
    """The editor projection plus the current-content digest it came from.

    The digest travels with the projection instead of being recomputed, so the
    Article workspace and Today can never disagree about what was validated.
    """
    facts, missing = _story_evidence_projection(article["story_id"])
    if story is None and story is not _UNSET:
        story = _maybe_story(article["story_id"])
    validation_view, validation = _current_validation(
        article,
        content,
        story=story,
        facts=facts,
        gaps=list(missing["items"]),
        headline=_story_headline(article, story, items_by_id),
        assessed_at=str(missing.get("assessedAt") or ""),
    )
    digest = validation.digest if validation is not None else None
    state = editor_projections.derive_article_state(article, content, digest)
    if validation is not None and article_validation.ready_eligible(article, content, validation):
        validation_view["readyEligible"] = True
    blocking_gaps = [item for item in missing["items"] if item.get("blocking")]
    non_blocking_gaps = [item for item in missing["items"] if not item.get("blocking")]
    focus_confirmed = editor_projections.focus_is_confirmed(article)
    # V1.1-B: the projection and the Draft command read the SAME decision. The
    # snapshot is assembled from state this projection already loaded, so no
    # second evidence read and no second predicate exist.
    readiness_snapshot = article_readiness.build_snapshot(article, content, story, facts, missing)
    readiness = article_readiness.evaluate(readiness_snapshot)
    # V1.1-C: manual continuation is a SEPARATE question from readiness, not a
    # second half of it. It is answered from one durable marker bound to this
    # exact basis, so it survives a reload and expires by itself when the
    # material changes — no attempt counter, no process state, no client state.
    failure = article.get("draft_generation_failure")
    manual_continuation = article_draft_failure.is_current(article, readiness_snapshot)
    actions, next_action = _article_actions(
        article, content, state, validation, readiness, manual_continuation
    )
    preparation = None
    if state == "preparation":
        preparation = {
            "focusConfirmed": focus_confirmed,
            # The editor-facing reason comes from the backend decision. React
            # never derives it, and never renders a second, competing message.
            "draftReadiness": readiness.as_dto(),
            "blockingGaps": blocking_gaps,
            "nonBlockingGaps": non_blocking_gaps,
            "draftEligible": readiness.eligible,
            # V1.1-C: the recovery context, or null. It is the reason class and
            # when it happened — never a provider error, a model name or a path.
            "draftFailure": None
            if not manual_continuation
            else {
                "reasonCode": str(failure["reason_code"]),
                "failedAt": str(failure["failed_at"]),
            },
            "availableActions": actions,
        }
    return (
        {
            "id": article["article_id"],
            "story": story_reference,
            "title": content["title"],
            "state": state,
            "isFinalized": bool(article.get("finalized_at")),
            "editorialFocus": {
                "text": article["editorial_focus"],
                "confirmedAt": article["focus_confirmed_at"],
            },
            "content": {
                "title": content["title"],
                "body": content["body"],
                "version": content["content_version"],
            },
            "preparation": preparation,
            "readiness": {
                "isCurrent": editor_projections.readiness_is_current(article, content, digest),
                "readyVersion": article.get("ready_version"),
                "readyAt": article.get("ready_at"),
            },
            # Current-content warnings: never the generation-time audit of an
            # immutable Draft, and never an empty set invented by a failed check.
            "warnings": [dict(row) for row in validation.warnings] if validation else [],
            "validation": validation_view,
            "availableActions": actions,
            "nextAction": next_action,
            "createdAt": article["created_at"],
            "updatedAt": article["updated_at"],
            "finalizedAt": article.get("finalized_at"),
            "factsAndSources": facts,
            "missingInformation": missing,
        },
        digest,
    )


def _article_dto_by_id(article_id: str) -> dict:
    return _article_projection_by_id(article_id)[0]


def _article_projection_by_id(article_id: str) -> tuple[dict, str | None]:
    article = _article(article_id)
    content = editor_article_store.get_article_content(article_id)
    story = _maybe_story(article["story_id"])
    items_by_id = _story_items()
    return _article_projection(
        article,
        content,
        _story_reference(article, items_by_id, story),
        story=story,
        items_by_id=items_by_id,
    )


def _story_items() -> dict:
    items = inbox_store.read_items(_paths()["inbox"])
    return {row["item_id"]: row for row in items}


def _development_dto(row: dict, unreviewed: bool) -> dict:
    return {
        "id": row["id"],
        "publicationId": row["publication_id"],
        "title": row["title"],
        "summary": row["summary"],
        "changedAt": row["changed_at"],
        "unreviewed": unreviewed,
    }


def _publication_dto(item: dict) -> dict:
    publisher = item.get("publisher_domain") or ""
    return {
        "id": editor_projections.publication_id_for("", item["item_id"]),
        "title": item.get("title") or "",
        "source": {
            "id": item.get("source_id") or "",
            "name": publisher or "Източник",
            "domain": publisher,
        },
        "url": item.get("url") or "",
        "publishedAt": item.get("published_at") or None,
        "discoveredAt": item.get("discovered_at") or "",
        "summary": item.get("summary") or "",
        "factsAndSourceIds": [],
    }


def _story_summary(story: dict, metadata: dict, items_by_id: dict, articles: list[dict]) -> dict:
    projected = editor_projections.project_story_editor(story, metadata, items_by_id, articles)
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    meaningful = editor_projections.meaningful_developments(story, items_by_id)
    latest = projected["latest_development"] or (meaningful[0] if meaningful else None)
    actions = (
        ["REVIEW"]
        if story.get("status") in {"NEW", "IGNORED"} or projected["unreviewed_development_count"]
        else []
    )
    actions.append("UNFOLLOW" if projected["followed"] else "FOLLOW")
    basis = story_research_store.get_story_research(story["story_id"])
    evidence_status = _evidence_status(basis)
    # V1.1-A §11: RESEARCH_MORE is available for an UNASSESSED Story or for
    # an assessed Story with a real researchable gap — never merely to
    # create noise on an assessed clean basis.
    _, legacy_gaps, _ = _legacy_story_evidence(story["story_id"], articles)
    meaningful_gaps = list(basis["gaps"]) + legacy_gaps
    has_research_gap = any(item.get("question") for item in meaningful_gaps)
    has_blocking_gap = any(item.get("blocking") for item in meaningful_gaps)
    research_available = story.get("status") != "IGNORED" and bool(
        search_mod.provider_chain(capability=search_mod.CAP_WEB)[0]
    )
    research_rounds_left = basis["research_rounds"] < readiness_mod.MAX_RESEARCH_ROUNDS
    unassessed = evidence_status == story_research_store.EVIDENCE_UNASSESSED
    if research_available and research_rounds_left and (unassessed or has_research_gap):
        actions.append("RESEARCH_MORE")
    if not projected["ignored"]:
        actions.append("IGNORE")
        actions.append("START_ARTICLE")
    next_action = None
    if story.get("status") in {"NEW", "IGNORED"} or projected["unreviewed_development_count"]:
        next_action = _next_action("REVIEW", "UNREVIEWED_STORY", "Прегледай")
    elif not projected["followed"]:
        next_action = _next_action("FOLLOW", "NOT_FOLLOWED", "Следи", primary=False)
    elif has_blocking_gap and "RESEARCH_MORE" in actions and not projected["ignored"]:
        next_action = _next_action("RESEARCH_MORE", "BLOCKING_GAP", "Проучи още", primary=True)
    return {
        "id": story["story_id"],
        "title": representative.get("title") or (latest or {}).get("title") or "",
        "summary": representative.get("summary") or (latest or {}).get("summary") or "",
        "reviewed": projected["reviewed"],
        "ignored": projected["ignored"],
        "followed": projected["followed"],
        "hasNewDevelopment": bool(meaningful),
        "unreviewedDevelopmentCount": projected["unreviewed_development_count"],
        "latestDevelopment": _development_dto(latest, True) if latest else None,
        "latestChangeAt": story.get("latest_material_change_at") or story.get("last_seen_at") or "",
        "availableActions": actions,
        "nextAction": next_action,
    }


def _story_detail(story_id: str) -> dict:
    story = _story(story_id)
    items_by_id = _story_items()
    metadata = story_editor_metadata.get_story_editor_metadata(
        story_id, root=_paths()["metadata_root"]
    )
    articles = editor_article_store.read_editor_articles()
    result = _story_summary(story, metadata, items_by_id, articles)
    developments = editor_projections.meaningful_developments(story, items_by_id)
    reviewed = set(metadata.get("reviewed_development_ids") or [])
    members = {row["item_id"]: row for row in story.get("members") or []}
    chronology = []
    for item_id, item in items_by_id.items():
        member = members.get(item_id)
        if not member:
            continue
        chronology.append(
            {
                "publicationId": editor_projections.publication_id_for(
                    member.get("publication_key") or "", item_id
                ),
                "at": item.get("discovered_at") or member.get("added_at") or "",
                "kind": (
                    "NEW_DEVELOPMENT" if member.get("relation") == "NEW_DEVELOPMENT" else "EVENT"
                ),
                "title": item.get("title") or "",
            }
        )
    chronology.sort(key=lambda row: (row["at"], row["publicationId"]), reverse=True)
    related_articles = [
        {
            "id": row["article_id"],
            "title": row["working_title"],
            "updatedAt": row["updated_at"],
            # A finalized Article stays related to its Story; the link then
            # targets the Archive instead of an active workspace.
            "finalizedAt": row.get("finalized_at"),
        }
        for row in articles
        if row.get("story_id") == story_id
    ]
    facts, missing = _story_evidence_projection(story_id, articles)
    result.update(
        {
            "whatHappened": result["summary"],
            "publications": [
                _publication_dto(items_by_id[item_id])
                for item_id in members
                if item_id in items_by_id
            ],
            "chronology": chronology,
            "newDevelopments": [
                _development_dto(row, row["id"] not in reviewed) for row in developments
            ],
            "relatedArticles": related_articles,
            "factsAndSources": facts,
            "missingInformation": missing,
            "correction": {"available": False, "actions": []},
        }
    )
    return result


def _research_bootstrap_context(story: dict, items_by_id: dict) -> dict:
    """Canonical Story context for the V1.1-A bootstrap first round (§6-§8).

    Representative/origin publication, source identity, URL, timestamp and
    members — never archive material, never snippet-invented facts.
    """
    members = list(story.get("members") or [])
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    origin_member = next(
        (row for row in members if row.get("relation") == "ORIGIN"), members[0] if members else {}
    )
    origin_item = items_by_id.get((origin_member or {}).get("item_id")) or {}
    # Prefer the origin item, then the representative, then any member item.
    ordered_items = []
    for candidate in (origin_item, representative):
        if isinstance(candidate, dict) and candidate.get("item_id"):
            ordered_items.append(candidate)
    for member in members:
        candidate = items_by_id.get(member.get("item_id")) or {}
        if candidate.get("item_id") and candidate not in ordered_items:
            ordered_items.append(candidate)
    seed_urls: list[str] = []
    for candidate in ordered_items:
        url = str(candidate.get("url") or "").strip()
        if url and url not in seed_urls:
            seed_urls.append(url)
    return {
        "title": _story_title(story, items_by_id),
        "items": ordered_items,
        "seed_urls": seed_urls,
        "representative": representative,
        "origin": origin_item,
    }


def research_story(story_id: str, *, provider=None, page_opener=None, now=None) -> dict:
    story = _story(story_id)
    basis = story_research_store.get_story_research(story_id)
    if story.get("status") == "IGNORED":
        raise EditorInvalidTransition("Игнорирана Story не може да се проучва.")
    if basis["research_rounds"] >= readiness_mod.MAX_RESEARCH_ROUNDS:
        raise EditorInvalidTransition("Лимитът на проучванията е изчерпан.")
    if not search_mod.provider_chain(capability=search_mod.CAP_WEB)[0]:
        raise EditorInvalidTransition("Няма наличен източник за проучване.")
    basis = story_research_store.get_story_research(story_id)
    _, legacy_gaps, _ = _legacy_story_evidence(
        story_id, editor_article_store.read_editor_articles()
    )
    all_gaps = list(basis["gaps"]) + legacy_gaps
    questions = [
        item["question"]
        for item in sorted(
            all_gaps,
            key=lambda item: (
                not item.get("blocking"),
                item.get("kind") != "conflict",
                item["question"],
            ),
        )
    ]
    items = _story_items()
    title = _story_title(story, items)
    unassessed = _evidence_status(basis) == story_research_store.EVIDENCE_UNASSESSED
    readiness_result = None
    bootstrap_context: dict = {}
    if unassessed:
        # V1.1-A §5: the first round must NOT require gaps. Bootstrap
        # questions come from Story context; the executor builds them.
        bootstrap_context = _research_bootstrap_context(story, items)
        title = bootstrap_context["title"] or title
    else:
        if not questions:
            raise EditorInvalidTransition("Няма блокираща липсваща информация за проучване.")
        readiness_result = {
            "status": readiness_mod.RESEARCH_MORE,
            "sufficiency": {"missing_dimensions": [], "research_questions": questions},
        }
    with _COMMAND_LOCK:
        try:
            story_research.execute_story_research(
                story_id,
                topic=title,
                readiness_result=readiness_result,
                root=_editorial_root(),
                provider=provider,
                page_opener=page_opener,
                canonical_story=story,
                existing_publication_keys=[
                    member.get("publication_key")
                    for member in story.get("members", [])
                    if member.get("publication_key")
                ],
                now=now,
                story_title=bootstrap_context.get("title", title) if unassessed else title,
                story_items=bootstrap_context.get("items", ()) if unassessed else (),
                seed_urls=bootstrap_context.get("seed_urls", ()) if unassessed else (),
            )
        except (
            story_research.StoryResearchError,
            story_research_store.StoryResearchStoreError,
        ) as exc:
            raise EditorResearchUnavailable(
                "Проучването не можа да завърши. Липсващата информация остава непроменена."
            ) from exc
    return _story_detail(story_id)


def start_story_research(story_id: str, *, idempotency_key: str = "") -> dict:
    story = _story(story_id)
    basis = story_research_store.get_story_research(story_id)
    evidence_status = _evidence_status(basis)
    _, legacy_gaps, _ = _legacy_story_evidence(
        story_id, editor_article_store.read_editor_articles()
    )
    gaps = list(basis["gaps"]) + legacy_gaps
    unassessed = evidence_status == story_research_store.EVIDENCE_UNASSESSED
    if unassessed:
        # V1.1-A §15: two simultaneous bootstrap rounds for the same Story
        # basis must not duplicate work — the identity is the unassessed
        # basis itself (no gaps yet), plus the round generation.
        signature = "bootstrap:unassessed"
    else:
        signature = "\0".join(sorted(f"{x['id']}={x['question']}" for x in gaps))
    generation = basis["research_rounds"]
    operation_token = story_operations.token_for(story_id, signature, generation, idempotency_key)
    if idempotency_key:
        accepted = story_operations.get(operation_token)
        if accepted is not None and accepted["status"] in {"pending", "running", "succeeded"}:
            return {"operationToken": operation_token, "status": accepted["status"]}
    if (
        story.get("status") == "IGNORED"
        or (not gaps and not unassessed)
        or basis["research_rounds"] >= readiness_mod.MAX_RESEARCH_ROUNDS
        or not search_mod.provider_chain(capability=search_mod.CAP_WEB)[0]
    ):
        raise EditorInvalidTransition("Проучването не е налично за тази Story.")

    def work():
        return research_story(story_id)

    token, view = story_operations.start(
        story_id, signature, work, generation=generation, key=idempotency_key
    )
    return {"operationToken": token, "status": view["status"]}


def operation_status(token: str) -> dict:
    if not re.fullmatch(r"op_[0-9a-f]{24}", token):
        raise EditorNotFound("Операцията не е намерена.")
    row = story_operations.get(token)
    if row is None:
        raise EditorNotFound("Операцията не е намерена.")
    if row["status"] == "succeeded":
        return {"operationToken": token, "status": row["status"], "result": row["result"]}
    if row["status"] == "failed":
        if article_generation.is_draft_scope(row.get("story_id")):
            # The worker already classified its own stable failure. Only the
            # bounded editor wording crosses this boundary; the raw provider
            # text never does, and an unclassified failure stays retryable.
            return {
                "operationToken": token,
                "status": row["status"],
                "error": article_generation.operation_error(row.get("error_code") or ""),
            }
        if quick_draft.is_quick_draft_scope(row.get("story_id")):
            # §19: a Quick Draft failure carries only a bounded code and one
            # editor sentence. No provider, no model id, no search internals.
            return {
                "operationToken": token,
                "status": row["status"],
                "error": quick_draft.operation_error(),
            }
        return {
            "operationToken": token,
            "status": row["status"],
            "error": {
                "code": "SOURCE_UNAVAILABLE",
                "message": (
                    "Новините не можаха да се обновят."
                    if row.get("story_id") == REFRESH_SCOPE
                    else "Проучването не можа да завърши."
                ),
                "retryable": True,
            },
        }
    return {"operationToken": token, "status": row["status"]}


def _refresh_signature(root: Path) -> str:
    """Canonical state a refresh is bound to, so a new one gets a new token."""
    paths = newsroom_refresh.newsroom_paths(root)
    last = source_health.read_last_run(paths["last_run"]) or {}
    try:
        stories = story_store.read_store(paths["stories"])["stories"]
    except (OSError, ValueError):
        stories = []
    seed = f"{last.get('finished_at', '')}\0{len(stories)}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _running_refresh() -> dict | None:
    """A refresh already in flight, as a still-valid operation, if there is one."""
    running = newsroom_refresh.active_token()
    if not running:
        return None
    row = story_operations.get(running)
    if row is None or row["status"] not in {"pending", "running"}:
        return None
    return {"operationToken": running, "status": row["status"]}


def start_newsroom_refresh(*, idempotency_key: str = "") -> dict:
    """Begin the one editor-facing newsroom refresh action («Обнови»).

    Transport only: the token carries progress for a bounded poll and nothing
    else. A repeated request carrying the same Idempotency-Key returns the
    still-valid operation instead of collecting the newsroom twice, and a
    refresh already in flight is returned rather than raced. The backend is
    the authority — the editor never decides alone that it may refresh.
    """
    root = _newsroom_root()
    state = newsroom_refresh.capability(root=root)
    if not state["canRefresh"]:
        raise EditorInvalidTransition(
            "няма активни източници за обновяване"
            if state["reason"] == "no_active_sources"
            else "източниците не могат да бъдат прочетени"
        )
    in_flight = _running_refresh()
    if in_flight is not None:
        return in_flight
    signature = _refresh_signature(root)
    if idempotency_key:
        # An explicit key pins the operation to that request alone. Binding it
        # to mutable newsroom state would hand a repeated request a *new* token
        # and collect the whole newsroom twice.
        signature = ""
    token = story_operations.token_for(REFRESH_SCOPE, signature, 0, idempotency_key)
    if idempotency_key:
        accepted = story_operations.get(token)
        if accepted is not None and accepted["status"] in {"pending", "running", "succeeded"}:
            return {"operationToken": token, "status": accepted["status"]}
    try:
        newsroom_refresh.acquire(token)
    except newsroom_refresh.RefreshBusy as busy:
        existing = _running_refresh()
        if existing is not None:
            return existing
        raise EditorInvalidTransition(str(busy)) from busy

    def work():
        try:
            return newsroom_refresh.refresh_newsroom(root=root)
        finally:
            newsroom_refresh.release(token)

    try:
        operation_token, view = story_operations.start(
            REFRESH_SCOPE, signature, work, generation=0, key=idempotency_key
        )
    except story_operations.BusyError as exc:
        newsroom_refresh.release(token)
        raise EditorInvalidTransition("новостите вече се обновяват; опитайте след малко") from exc
    return {"operationToken": operation_token, "status": view["status"]}


# ---------------------------------------------------------------- C2 «Направи чернова»


def _draft_snapshot(article_id: str) -> dict:
    """Everything the Draft command is bound to, read from canonical stores.

    Deliberately a snapshot of *server* state: the request carries no facts, no
    focus, no title and no evidence, so a client cannot talk the backend into
    drafting from material it chose.

    **V1.1-B:** the readiness-relevant part is now assembled by the shared
    `article_readiness.build_snapshot`, the very builder the Article preparation
    projection uses. There is exactly one evidence snapshot in the product, and
    the command adds only its own packet metadata (headline, summary) on top.
    """
    article = _active_article(article_id)
    content = editor_article_store.get_article_content(article_id)
    story = _story(article["story_id"])
    facts, missing = _story_evidence_projection(article["story_id"])
    items_by_id = _story_items()
    snapshot = article_readiness.build_snapshot(article, content, story, facts, missing)
    snapshot.update(
        {
            "headline": _story_title(story, items_by_id) or article["working_title"],
            "summary": str(
                (items_by_id.get(story.get("representative_item_id")) or {}).get("summary") or ""
            ),
        }
    )
    return snapshot


def _draft_signature(snapshot: dict) -> str:
    """Canonical state a Draft command is bound to, so a new one gets a new token."""
    gaps = "\0".join(sorted(str(item.get("id") or "") for item in snapshot["gaps"]))
    seed = f"{snapshot['content_version']}\0{snapshot['article']['updated_at']}\0{gaps}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _running_draft(article_id: str) -> dict | None:
    """A generation for this Article already in flight, as a still-valid operation."""
    token = article_generation.active_token(article_id)
    if not token:
        return None
    row = story_operations.get(token)
    if row is None or row["status"] not in {"pending", "running"}:
        return None
    return {"operationToken": token, "status": row["status"]}


def _raise_draft_refusal(exc: article_generation.DraftRefused) -> None:
    """Map a stable refusal onto the editor error contract, never its raw text.

    **V1.1-B:** the code is carried through unchanged, so the HTTP refusal names
    the same semantic reason the preparation projection already showed. The
    wording comes from the one `article_readiness` message table, so the command
    and the UI can never describe one state with two different sentences.
    """
    code = exc.code
    if code == article_generation.OP_INVALID_TRANSITION:
        # A transport-level refusal (a generation already in flight), not a
        # readiness decision, so it keeps its own class and code.
        raise EditorInvalidTransition(exc.message) from exc
    if code in article_readiness.LIFECYCLE_CODES:
        # Lifecycle and lineage are transition problems, not evidence-readiness
        # problems. They keep the historical `INVALID_TRANSITION` contract while
        # the editor still receives the specific, actionable message.
        raise EditorInvalidTransition(exc.message) from exc
    if code == article_readiness.SAFETY_BLOCKED:
        raise EditorSafetyBlocked(exc.message) from exc
    if code == article_readiness.ARTICLE_VERSION_CONFLICT:
        raise EditorVersionConflict(exc.message) from exc
    if code == article_readiness.BLOCKING_GAP:
        raise EditorBlockingGap(exc.message) from exc
    # Every evidence-readiness refusal — including the three that are not a
    # blocking gap and used to be silently collapsed into one — is reported with
    # its own exact code at 409. The editor can therefore act on the reason, and
    # the wording is the one the projection already showed.
    raise EditorDraftNotReady(code, exc.message) from exc


def _record_draft_failure(article_id: str, snapshot: dict, basis: str, code: str) -> None:
    """Persist the durable manual-continuation marker, if this failure qualifies.

    **V1.1-C — the ordering contract.** This is called only from the worker, only
    after the deterministic preflight passed and generation was actually
    attempted, and only when no Draft was published. A preflight refusal
    (`STORY_UNASSESSED`, `BLOCKING_GAP`, a stale version, an Article that already
    has text) never reaches it, which is why those can never open the editor.

    A non-qualifying code, or a marker that cannot be written, is not an error:
    the operation still fails with its own stable code. The recovery path is a
    convenience of a genuine failure, never a precondition for reporting one, so
    it must never mask the real refusal or turn it into a different one.
    """
    reason = article_draft_failure.reason_for(code)
    if not reason:
        return
    try:
        editor_article_store.record_draft_generation_failure(
            article_id,
            content_version=int(snapshot["content_version"]),
            basis_digest=basis,
            reason_code=reason,
            root=_editorial_root(),
        )
    except (editor_article_store.ArticleStoreError, OSError):
        # The failure itself is still reported truthfully; only the recovery
        # affordance is lost, and it returns on the next genuine failure.
        LOG.warning("could not persist the draft failure marker for %s", article_id)


def _run_draft_generation(article_id: str, token: str) -> dict:
    """The one synchronous C2 Draft execution, shared by both callers (§7 D2).

    Extracted from the `Направи чернова` operation worker so the Quick Draft
    orchestration runs the *same* code rather than a simplified copy. Nothing
    here is aware of which caller asked: the preflight, the V1.1-C failure
    marker, the version guards and the published result are identical.

    Raising `article_generation.DraftRefused` (with a stable `code`) is the
    contract: the normal operation turns it into a bounded operation failure,
    and the Quick Draft orchestration turns the same refusal into an
    editor-facing `needs_attention` result.
    """
    try:
        # Stale revalidation: the Article may have been edited, refocused or
        # re-gapped while this operation was queued. That is a stable
        # refusal, never a silent overwrite of the editor's text.
        current = _draft_snapshot(article_id)
        try:
            article_generation.evaluate(current)
        except article_generation.DraftRefused as exc:
            # Re-raise as the classified refusal so the bounded operation
            # keeps the stable code instead of a generic failure. This is the
            # preflight: it raises BEFORE any generation is attempted, which is
            # exactly why it must never record a failure marker.
            raise article_generation.DraftRefused(exc.code, exc.message) from exc
        # V1.1-C: the preflight is crossed, so from here a failure is a real
        # generation failure. The marker is written only for the classes that
        # qualify, and only against the basis this attempt actually used, so a
        # readiness refusal can never open the manual editor.
        attempted_basis = article_draft_failure.basis_digest(current)
        try:
            with _COMMAND_LOCK:
                article_generation.generate(current, root=_editorial_root())
        except article_generation.DraftRefused as exc:
            _record_draft_failure(article_id, current, attempted_basis, exc.code)
            raise
        except editor_article_store.ArticleVersionConflict as exc:
            raise article_generation.DraftRefused(
                "ARTICLE_VERSION_CONFLICT",
                "Статията е променена, преди черновата да се създаде.",
            ) from exc
        except Exception:
            # An unclassified transport/provider failure: the attempt happened
            # and produced no Draft, so it is the one case the empty refusal
            # code stands for.
            _record_draft_failure(article_id, current, attempted_basis, "")
            raise
        return _article_dto_by_id(article_id)
    except article_generation.DraftRefused:
        raise
    except EditorApplicationError as exc:
        raise article_generation.DraftRefused(exc.code, str(exc)) from exc
    except editor_article_store.ArticleVersionConflict as exc:
        raise article_generation.DraftRefused(
            "ARTICLE_VERSION_CONFLICT",
            "Статията е променена, преди черновата да се създаде.",
        ) from exc
    except Exception as exc:
        raise article_generation.DraftRefused("", "Source unavailable") from exc
    finally:
        article_generation.release(article_id, token)


def start_article_draft(article_id: str, *, idempotency_key: str = "") -> dict:
    """Begin the one editor-facing Draft action (C2 «Направи чернова»).

    Transport only: the token carries a bounded poll, nothing else. The backend
    is the authority - the command is refused unless the server itself currently
    offers `MAKE_DRAFT` for this Article, and every precondition is re-checked
    inside the worker before any provider work happens. A repeated request with
    the same Idempotency-Key returns the still-valid operation instead of
    generating twice, and a generation already in flight is returned rather than
    raced.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise EditorApplicationError("Idempotency key is required.")
    key = idempotency_key.strip()
    with _COMMAND_LOCK:
        article = _active_article(article_id)
        snapshot = _draft_snapshot(article_id)
        # **V1.1-B:** the command evaluates the ONE canonical readiness decision
        # and refuses with its exact current reason. Stale frontend eligibility
        # is never trusted: canonical state is re-read here, so a gap that
        # appeared after the render refuses instead of generating over it.
        readiness = article_readiness.evaluate(snapshot)
        if not readiness.eligible:
            _raise_draft_refusal(
                article_generation.DraftRefused(readiness.reason_code, readiness.reason_message)
            )
        dto = _article_dto(article, snapshot["content"], _story_reference(article))
        if "MAKE_DRAFT" not in dto["availableActions"]:
            # The invariant in code: `MAKE_DRAFT` is derived from the very same
            # decision evaluated above. If it were ever derived from anything
            # else, the command fails loudly here instead of the UI silently
            # diverging from the backend.
            raise EditorApplicationError("Черновата не е налична в текущото състояние на статията.")
    in_flight = _running_draft(article_id)
    if in_flight is not None:
        return in_flight
    scope = article_generation.scope_for(article_id)
    signature = _draft_signature(snapshot)
    if key:
        # An explicit key pins the operation to that request alone. Binding it to
        # mutable Article state would hand a repeated request a *new* token and
        # generate the same Draft twice.
        signature = ""
    token = story_operations.token_for(scope, signature, 0, key)
    if key:
        accepted = story_operations.get(token)
        if accepted is not None and accepted["status"] in {"pending", "running", "succeeded"}:
            return {"operationToken": token, "status": accepted["status"]}
    try:
        article_generation.acquire(article_id, token)
    except article_generation.DraftRefused as exc:
        existing = _running_draft(article_id)
        if existing is not None:
            return existing
        _raise_draft_refusal(exc)

    def work():
        # The same synchronous execution the Quick Draft orchestration calls.
        return _run_draft_generation(article_id, token)

    try:
        operation_token, view = story_operations.start(scope, signature, work, key=key)
    except story_operations.BusyError as exc:
        article_generation.release(article_id, token)
        raise EditorInvalidTransition("Операциите са заети; опитайте след малко.") from exc
    return {"operationToken": operation_token, "status": view["status"]}


# --------------------------------------------------------------------------
# V1.1-D2 — Quick Draft orchestration («Today → Чернова»)
# --------------------------------------------------------------------------


def _story_articles(story_id: str) -> tuple[list[dict], dict[str, dict]]:
    """Every canonical Article of this Story, with its current content."""
    records = [
        row
        for row in editor_article_store.read_editor_articles()
        if row.get("story_id") == story_id
    ]
    contents = {
        row["article_id"]: editor_article_store.get_article_content(row["article_id"])
        for row in records
    }
    return records, contents


def _research_remedy_needed(story_id: str, story: dict) -> bool:
    """Whether this Story still warrants one *allowed* research round (§8).

    The same three conditions `start_story_research` enforces: the Story is not
    ignored, there is something real to research (an unassessed basis, or a real
    gap), and the existing round cap is not exhausted. Quick Draft therefore
    never runs autonomous research beyond the cap the product already had.
    """
    if story.get("status") == "IGNORED":
        return False
    basis = story_research_store.get_story_research(story_id)
    unassessed = _evidence_status(basis) == story_research_store.EVIDENCE_UNASSESSED
    _, legacy_gaps, _ = _legacy_story_evidence(
        story_id, editor_article_store.read_editor_articles()
    )
    gaps = list(basis["gaps"]) + legacy_gaps
    if not (unassessed or gaps):
        return False
    return basis["research_rounds"] < readiness_mod.MAX_RESEARCH_ROUNDS


def _quick_evidence_verdict(story_id: str, articles: list[dict]):
    """The ONE evidence decision, asked before any Article is created (§10).

    This is `article_readiness.evaluate_evidence` over the canonical Story
    projection — the same function the Article preparation projection and the
    Draft command use, with the same reason codes and the same one message per
    code. It answers a question that exists independently of any Article, which
    is exactly why the Article must be created *after* it: a Story that cannot
    acquire enough evidence should not leave an empty Preparation Article behind
    merely because the editor clicked.
    """
    facts, missing = _story_evidence_projection(story_id, articles)
    return article_readiness.evaluate_evidence(
        evidence_status=str(missing.get("evidenceStatus") or ""),
        facts=facts,
        blocking_gaps=[row for row in missing["items"] if row.get("blocking")],
        source_url=article_readiness._first_source_url(facts),
    )


def _create_quick_article(story_id: str, story: dict) -> str | None:
    """Create the one canonical Article, only once evidence is sufficient.

    The working title is the existing canonical Story→Article title; no AI title
    generation is introduced here (§15). The Focus is left unconfirmed and set
    immediately afterwards through the ordinary focus command, so a
    Quick-Draft-created Article is indistinguishable from one the editor started
    by hand.
    """
    title = _story_title(story, _story_items()) or "Работа за статия"
    with _COMMAND_LOCK:
        try:
            created = editor_article_store.create_editor_article(
                story_id=story_id,
                stories_path=_paths()["stories"],
                working_title=title,
                editorial_focus="",
                idempotency_key=f"quick-draft:{story_id}",
            )
        except editor_article_store.ArticleStoreError as exc:
            if "unknown canonical story_id" in str(exc):
                raise EditorNotFound("Story не е намерена.") from exc
            LOG.warning("quick draft could not create an Article for %s", story_id)
            return None
    return created["article_id"]


def _confirm_quick_focus(article_id: str, story_id: str) -> str:
    """Confirm the default straight-news Focus, unless one is already confirmed.

    A confirmed editor Focus is never touched (§14) — the quick Focus exists only
    to remove an unnecessary screen when the editor has not chosen an angle, and
    the click itself is the confirmation of this default (§13).

    Returns `""` on success, or the editor-safe reason the Focus could not be
    established. It never returns an internal exception text.
    """
    article = _article(article_id)
    if editor_projections.focus_is_confirmed(article):
        return ""
    story = _story(story_id)
    focus = quick_draft.default_focus(_story_title(story, _story_items()))
    if not focus:
        # No clean Story title means no honest subject. The Article is left
        # untouched, and the canonical readiness decision reports the real
        # reason (WORKING_TITLE_REQUIRED) when the command asks it.
        return article_readiness.REASON_MESSAGES[article_readiness.WORKING_TITLE_REQUIRED]
    with _COMMAND_LOCK:
        try:
            editor_article_store.update_editor_focus(article_id, focus)
        except editor_article_store.ArticleStoreError as exc:
            if "unknown article_id" in str(exc):
                raise EditorNotFound("Статията не е намерена.") from exc
            LOG.warning("quick draft could not confirm the Focus for %s", article_id)
            return quick_draft.FOCUS_UNCONFIRMABLE_MESSAGE
    return ""


def _run_quick_draft(story_id: str) -> dict:
    """The one Quick Draft sequence, run synchronously inside the worker.

    The canonical order, and every step delegated to existing machinery:

    1. reload the canonical Story;
    2. if the evidence basis still warrants an *allowed* research round, run the
       SAME `research_story` implementation the «Проучи още» command runs;
    3. reload the canonical evidence and re-evaluate it honestly — research
       completion never implies a Draft (§9);
    4. resolve the Article, creating one only if evidence is already sufficient
       (§10) and only when the existing-Article situation is unambiguous (§11);
    5. establish the quick straight-news Focus if none is confirmed (§13/§14);
    6. ask the ONE V1.1-B readiness decision for the concrete Article (§16);
    7. generate through the SAME C2 pipeline, sharing the V1.1-C failure marker
       (§17/§18);
    8. return the narrow, editor-facing result (§19).

    A step that cannot safely complete stops here with the real blocker. It
    never fabricates a Draft, never invents a fact, and never bypasses a safety
    guard — the orchestration may automate steps, never override a result.
    """
    story = _story(story_id)
    if story.get("status") == "IGNORED":
        return quick_draft.result_needs_attention(
            story_id,
            quick_draft.STORY_IGNORED,
            "Историята е игнорирана и не може да се направи чернова.",
        )

    # 2. Research, when the canonical basis warrants it and the round cap allows.
    # `research_story` is the same synchronous implementation the normal command
    # runs, including the cap; a transport failure stops rather than degrades.
    if _research_remedy_needed(story_id, story):
        try:
            research_story(story_id)
        except (EditorResearchUnavailable, EditorInvalidTransition) as exc:
            return quick_draft.result_needs_attention(
                story_id, quick_draft.DRAFT_GENERATION_FAILED, str(exc)
            )

    # 3. Re-evaluate the canonical evidence. This is the honest re-check: a
    # completed research round that did not produce usable material stops the
    # command *before* an Article exists, so nothing is left behind to clean up.
    articles, contents = _story_articles(story_id)
    verdict = _quick_evidence_verdict(story_id, articles)
    if not verdict.eligible:
        return quick_draft.result_needs_attention(
            story_id, verdict.reason_code, verdict.reason_message
        )

    # 4. Existing-Article resolution. Multiple active Articles is a supported
    # canonical feature, so ambiguity stops and asks instead of guessing.
    resolved = quick_draft.plan(articles, contents, story_id)
    if resolved["outcome"] == quick_draft.PLAN_AMBIGUOUS:
        return quick_draft.result_needs_attention(
            story_id,
            quick_draft.MULTIPLE_ACTIVE_ARTICLES,
            "Историята има повече от една активна статия. Изберете коя да продължите.",
        )
    if resolved["outcome"] == quick_draft.PLAN_EXISTING:
        # A Draft already exists, or the Article is Ready. Never regenerate,
        # never reopen: just take the editor to it (§11).
        return quick_draft.result_existing_article(resolved["articleId"])

    article_id = (
        resolved["articleId"]
        if resolved["outcome"] == quick_draft.PLAN_REUSE
        else _create_quick_article(story_id, story)
    )
    if not article_id:
        return quick_draft.result_needs_attention(
            story_id,
            quick_draft.DRAFT_GENERATION_FAILED,
            "Статията не може да бъде създадена за тази история.",
        )

    # 5. The default Focus, only where none is confirmed. An empty string means
    # the Focus is in place; anything else is the real reason it is not.
    focus_problem = _confirm_quick_focus(article_id, story_id)
    if focus_problem:
        return quick_draft.result_needs_attention(
            story_id,
            quick_draft.FOCUS_UNCONFIRMABLE,
            focus_problem,
            article_id=article_id,
        )

    # 6. The ONE readiness decision for the concrete Article now that it exists
    # with a confirmed Focus. Re-read from canonical state: the click, the
    # research round and the Focus write all happened after the click.
    snapshot = _draft_snapshot(article_id)
    readiness = article_readiness.evaluate(snapshot)
    if not readiness.eligible:
        # A refusal with a research remedy is reported with its own exact code.
        # Quick Draft does not research again here: it already spent its one
        # allowed round in step 2, and a second speculative round would be
        # autonomous research the product does not permit.
        return quick_draft.result_needs_attention(
            story_id,
            readiness.reason_code,
            readiness.reason_message,
            article_id=article_id,
        )

    # 7. The SAME C2 generation pipeline the «Направи чернова» command runs,
    # through the same synchronous worker, so safety, audit, originality and the
    # V1.1-C failure marker are identical. A Quick Draft is an ordinary Draft
    # produced through ordinary generation; only the way here was different.
    generation_token = quick_draft.scope_for(story_id)
    try:
        article_generation.acquire(article_id, generation_token)
    except article_generation.DraftRefused:
        return quick_draft.result_needs_attention(
            story_id,
            quick_draft.DRAFT_GENERATION_FAILED,
            "Черновата за тази статия вече се създава.",
            article_id=article_id,
        )
    try:
        _run_draft_generation(article_id, generation_token)
    except article_generation.DraftRefused as exc:
        # V1.1-C already recorded the durable failure marker inside the shared
        # worker. Report the real reason and keep the Preparation Article, where
        # the editor finds the retry plus the earned «Редактирай» (§18, §40).
        return quick_draft.result_needs_attention(
            story_id,
            exc.code or quick_draft.DRAFT_GENERATION_FAILED,
            exc.message,
            article_id=article_id,
        )

    # 8. The one positive result. A plain truthy check, not a claim of success:
    # if the worker returned without publishing a Draft, the editor is told the
    # truth rather than navigated to an empty Article.
    refreshed = editor_article_store.get_article_content(article_id)
    if quick_draft.is_empty_preparation(_article(article_id), refreshed):
        return quick_draft.result_needs_attention(
            story_id,
            quick_draft.DRAFT_GENERATION_FAILED,
            "Черновата не можа да бъде създадена. Опитайте отново.",
            article_id=article_id,
        )
    return quick_draft.result_draft_created(article_id)


def start_quick_draft(story_id: str, *, idempotency_key: str = "") -> dict:
    """The one Quick Draft command: «Today → Чернова» (§5, §6).

    Transport only. The browser expresses one editorial intent; the application
    layer owns the sequence, and the partial-failure semantics never live in
    React. Returns a bounded operation token for the shared registry — no Celery,
    no queue service, no second job system, no workflow engine.

    **Idempotency (§12).** The Idempotency-Key pins the operation, so a double
    click, a browser retry, a network retry and an editor who returns while the
    work is still running all address the same operation and therefore the same
    research round, the same Article and the same generation attempt.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise EditorApplicationError("Idempotency key is required.")
    key = idempotency_key.strip()
    story = _story(story_id)
    if story.get("status") == "IGNORED":
        raise EditorInvalidTransition("Историята е игнорирана.")
    scope = quick_draft.scope_for(story_id)
    # An explicit key pins the operation to that request alone. Binding it to
    # mutable Story state would hand a repeated request a new token and repeat
    # the whole orchestration.
    token = story_operations.token_for(scope, "", 0, key)
    accepted = story_operations.get(token)
    if accepted is not None and accepted["status"] in {"pending", "running", "succeeded"}:
        return {"operationToken": token, "status": accepted["status"]}
    running = quick_draft.active_token(story_id)
    if running:
        row = story_operations.get(running)
        if row is not None and row["status"] in {"pending", "running"}:
            # §29: a second click while the same work is in flight reattaches to
            # the running operation instead of starting parallel work.
            return {"operationToken": running, "status": row["status"]}
    quick_draft.acquire(story_id, token)

    def work():
        try:
            return _run_quick_draft(story_id)
        finally:
            quick_draft.release(story_id, token)

    try:
        operation_token, view = story_operations.start(scope, "", work, key=key)
    except story_operations.BusyError as exc:
        quick_draft.release(story_id, token)
        raise EditorInvalidTransition("Операциите са заети; опитайте след малко.") from exc
    return {"operationToken": operation_token, "status": view["status"]}


def read_story(story_id: str) -> dict:
    return _story_detail(story_id)


def read_article(article_id: str) -> dict:
    return _article_dto_by_id(article_id)


def _today_last_refresh() -> dict | None:
    """The last run's editor-facing summary, or `None` if no run ever happened.

    Only four numbers and the finish time cross this boundary. The raw
    `last_run.json` shape — per-source problem detail, blocked counts, duplicate
    counts, source ids — stays in the operational store, because Today is an
    attention surface and not source diagnostics.
    """
    record = source_health.read_last_run(
        newsroom_refresh.newsroom_paths(_newsroom_root())["last_run"]
    )
    if not record:
        return None
    finished_at = str(record.get("finished_at") or "")
    if not finished_at:
        return None
    new_stories = record.get("new_stories")
    return {
        "finishedAt": finished_at,
        "newPublications": int(record.get("new") or 0),
        # `None` when the run predates this field: absent is honest, zero is a claim.
        "newStories": None if new_stories is None else int(new_stories),
        "failedSources": int(record.get("failed") or 0),
    }


def read_today() -> dict:
    result = editor_queries.read_today(
        stories_path=_paths()["stories"],
        inbox_path=_paths()["inbox"],
        metadata_root=_paths()["metadata_root"],
    )
    new_developments = []
    new_stories = []
    # The Story row already carries its canonical title, summary, change
    # timestamp and development count from the single in-memory snapshot taken
    # above. The previous implementation called `_story_detail()` per row, which
    # re-read the Story store, the inbox, the metadata store and the whole
    # Article store once for every Story on the page.
    #
    # V1.1-D2: the same snapshot also answers the quick-draft availability of
    # every row, so the triage buttons cost no extra store read either. Read
    # once here and reused by the Story loop and the Article loop below.
    stories = story_store.read_store(_paths()["stories"])["stories"]
    stories_by_id = {row["story_id"]: row for row in stories}
    article_records = editor_article_store.read_editor_articles()
    contents_by_id = {
        row["article_id"]: editor_article_store.get_article_content(row["article_id"])
        for row in article_records
    }
    for row in result["stories"]:
        # V1.1-D2 §4/§43: the backend is the authority for whether this row may
        # offer `Чернова`. It is computed from the same single in-memory snapshot
        # taken above, so the row costs no additional store read and the frontend
        # derives nothing locally. `Прегледай` keeps its existing REVIEW semantics
        # untouched (§25); `Игнорирай` is the ordinary canonical Ignore command.
        quick = quick_draft.availability(
            story=stories_by_id[row["id"]],
            articles=article_records,
            contents=contents_by_id,
        )
        item = {
            "objectType": "story",
            "objectId": row["id"],
            "title": row["title"],
            "reason": row["attention"],
            "summary": row["summary"],
            "timestamp": row["latestChangeAt"],
            "nextAction": "REVIEW",
            "delta": {"unreviewedDevelopmentCount": row["unreviewedDevelopmentCount"]},
            "availableActions": ["REVIEW", "IGNORE"]
            + (["QUICK_DRAFT"] if quick["available"] else []),
            "quickDraft": {
                "available": quick["available"],
                "label": quick["label"],
                "articleId": quick["articleId"],
                # The reason a row withholds the button, so the projection is
                # inspectable and the frontend never has to re-derive it.
                "reasonCode": quick["reasonCode"],
            },
        }
        if row["attention"] == "NEW_STORY":
            new_stories.append(item)
        else:
            item["reason"] = "UNREVIEWED_DEVELOPMENT"
            new_developments.append(item)
    articles = []
    # One snapshot of each canonical store, reused for every Article row. The
    # previous implementation called `_article_projection_by_id()` per Article,
    # and each of those re-read the Story store, the whole inbox, the metadata
    # store and the entire Article index — so the remaining cost still grew
    # with the number of Articles on the page.
    stories = story_store.read_store(_paths()["stories"])["stories"]
    stories_by_id = {row["story_id"]: row for row in stories}
    items_by_id = _story_items()
    for article in article_records:
        # The real current-content digest decides readiness, exactly as it does
        # in the Article workspace: a `Готова` Article stops asking for action
        # and a stale checkpoint starts asking again.
        content = contents_by_id[article["article_id"]]
        story = stories_by_id.get(article["story_id"])
        # An Article whose Story is gone is not today's problem; it keeps its
        # own workspace's handling and is simply absent from this projection.
        if story is None:
            continue
        dto, current_digest = _article_projection(
            article,
            content,
            _story_reference(article, items_by_id, story),
            story,
            items_by_id,
        )
        concrete_next_action = (dto.get("nextAction") or {}).get("action")
        if not editor_projections.article_today_eligible(
            article,
            content,
            current_digest,
            concrete_next_action=concrete_next_action,
        ):
            continue
        articles.append(
            {
                "objectType": "article",
                "objectId": dto["id"],
                "title": dto["title"],
                "reason": dto["state"].upper(),
                "summary": dto["editorialFocus"]["text"],
                "timestamp": dto["updatedAt"],
                "nextAction": dto["nextAction"],
            }
        )
    articles.sort(key=lambda row: (row["timestamp"], row["objectId"]), reverse=True)
    return {
        "lastRefresh": _today_last_refresh(),
        "storyAttentionTotal": result["storyAttentionTotal"],
        "storyAttentionShown": len(new_developments) + len(new_stories),
        "newDevelopments": new_developments,
        "newStories": new_stories,
        "articlesRequiringAction": articles,
        # Derived read-only from the source-health records the real collection
        # pipeline writes. A problem appears only when a configured source
        # actually failed; the editor can retry or mute it from the page.
        "problems": newsroom_refresh.today_problems(root=_newsroom_root()),
    }


def list_stories(filter_name: str = "all", query: str = "") -> list[dict]:
    stories = story_store.read_store(_paths()["stories"])["stories"]
    items_by_id = _story_items()
    metadata_store = story_editor_metadata.read_story_editor_metadata_store(
        root=_paths()["metadata_root"]
    )["stories"]
    metadata_by_id = {row["story_id"]: row for row in metadata_store}
    articles = editor_article_store.read_editor_articles()
    result = []
    for story in stories:
        metadata = metadata_by_id.get(story["story_id"]) or (
            story_editor_metadata.default_story_editor_metadata(story["story_id"])
        )
        dto = _story_summary(story, metadata, items_by_id, articles)
        if filter_name == "followed" and not dto["followed"]:
            continue
        if filter_name == "developments" and not dto["unreviewedDevelopmentCount"]:
            continue
        if filter_name == "ignored" and not dto["ignored"]:
            continue
        if query and query.casefold() not in f"{dto['title']} {dto['summary']}".casefold():
            continue
        result.append(dto)
    result.sort(key=lambda row: (row["latestChangeAt"], row["id"]), reverse=True)
    return result


def list_articles(filter_name: str = "all", query: str = "") -> list[dict]:
    result = []
    stories = story_store.read_store(_paths()["stories"])["stories"]
    stories_by_id = {story["story_id"]: story for story in stories}
    items_by_id = _story_items()
    for article in editor_article_store.read_editor_articles():
        story = stories_by_id.get(article["story_id"])
        content = editor_article_store.get_article_content(article["article_id"])
        story_reference = {"id": article["story_id"]}
        title = _story_title(story, items_by_id) if story else ""
        if title:
            story_reference["title"] = title
        dto = _article_dto(article, content, story_reference, story=story, items_by_id=items_by_id)
        if dto["isFinalized"]:
            continue
        if filter_name != "all" and dto["state"] != filter_name:
            continue
        if (
            query
            and query.casefold()
            not in " ".join(
                (
                    dto["title"],
                    dto["story"].get("title", ""),
                    dto["content"]["title"],
                    dto["content"]["body"],
                )
            ).casefold()
        ):
            continue
        result.append(dto)
    result.sort(key=lambda row: (row["updatedAt"], row["id"]), reverse=True)
    return result


def _archive_dto(article: dict) -> dict:
    """The read-only Archive projection, read from the frozen snapshot alone.

    The Archive never revalidates and never re-reads the working content: what
    the editor finalized is exactly what is shown. There is no action, no next
    step and no publication control here - `Финализирана` is not `Публикувана`.
    """
    snapshot = editor_article_store.read_finalized_article(article["article_id"])
    if snapshot is None:
        # A finalized record without a snapshot can only come from a store
        # written before C5. Report it from the record rather than inventing
        # content: the editor still sees the real title, Story and date.
        return _article_dto(
            article,
            editor_article_store.get_article_content(article["article_id"]),
            _story_reference(article),
        )
    story_reference = _story_reference(article)
    return {
        "id": snapshot["article_id"],
        "story": story_reference,
        "title": snapshot["title"],
        "state": None,
        "isFinalized": True,
        "editorialFocus": {
            "text": snapshot["editorial_focus"],
            "confirmedAt": snapshot["focus_confirmed_at"],
        },
        "content": {
            "title": snapshot["title"],
            "body": snapshot["body"],
            "version": snapshot["content_version"],
        },
        "preparation": None,
        "readiness": {
            "isCurrent": True,
            "readyVersion": snapshot["ready_version"],
            "readyAt": snapshot["ready_at"],
        },
        # The Archive is not re-validated: the validation that authorized
        # finalization is frozen into the snapshot, and its warnings are the
        # editor-facing record of what was known at that moment.
        "warnings": [],
        "validation": {
            "contentVersion": snapshot["content_version"],
            "current": False,
            "blocking": False,
            "readyEligible": False,
        },
        "availableActions": [],
        "nextAction": None,
        "createdAt": article["created_at"],
        "updatedAt": article["updated_at"],
        "finalizedAt": snapshot["finalized_at"],
        "factsAndSources": [dict(row) for row in snapshot["evidence"]["facts"]],
        "missingInformation": dict(snapshot["evidence"]["missing"]),
    }


def list_archive(query: str = "") -> list[dict]:
    result = []
    for article in editor_article_store.read_editor_articles():
        if not article.get("finalized_at"):
            continue
        dto = _archive_dto(article)
        if (
            query
            and query.casefold()
            not in " ".join(
                (dto["title"], dto["story"].get("title", ""), dto["content"]["body"])
            ).casefold()
        ):
            continue
        result.append(dto)
    result.sort(key=lambda row: (row["finalizedAt"], row["id"]), reverse=True)
    return result


def _validate_story_action(story_id: str, action: str) -> dict:
    story = _story(story_id)
    items_by_id = _story_items()
    metadata = story_editor_metadata.get_story_editor_metadata(
        story_id, root=_paths()["metadata_root"]
    )
    available = _story_summary(story, metadata, items_by_id, [])["availableActions"]
    if action not in available:
        raise EditorInvalidTransition("Това действие не е налично за Story.")
    return story


def start_article(story_id: str, *, idempotency_key: str) -> dict:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise EditorApplicationError("Idempotency key is required.")
    with _COMMAND_LOCK:
        story = _validate_story_action(story_id, "START_ARTICLE")
        items_by_id = _story_items()
        title = _story_title(story, items_by_id) or "Работа за статия"
        focus = "Да разкажем какво се е променило в тази история и защо е важно за хората."
        try:
            record = editor_article_store.create_editor_article(
                story_id=story_id,
                stories_path=_paths()["stories"],
                working_title=title,
                editorial_focus=focus,
                idempotency_key=idempotency_key.strip(),
            )
        except editor_article_store.ArticleStoreError as exc:
            if "unknown canonical story_id" in str(exc):
                raise EditorNotFound("Story не е намерена.") from exc
            raise EditorApplicationError("Статията не може да бъде създадена.") from exc
    return _article_dto_by_id(record["article_id"])


def review_story(story_id: str, observed_development_ids: list[str]) -> dict:
    _validate_story_action(story_id, "REVIEW")
    with _COMMAND_LOCK:
        story_editor_metadata.review_story_developments(
            story_id,
            observed_development_ids,
            stories_path=_paths()["stories"],
            inbox_path=_paths()["inbox"],
            root=_paths()["metadata_root"],
        )
    return _story_detail(story_id)


def follow_story(story_id: str, followed: bool) -> dict:
    current = story_editor_metadata.get_story_editor_metadata(
        story_id, root=_paths()["metadata_root"]
    )
    if bool(current.get("followed")) == followed:
        return _story_detail(story_id)
    action = "FOLLOW" if followed else "UNFOLLOW"
    _validate_story_action(story_id, action)
    with _COMMAND_LOCK:
        try:
            story_editor_metadata.set_story_followed(
                story_id, followed, stories_path=_paths()["stories"], root=_paths()["metadata_root"]
            )
        except story_editor_metadata.StoryEditorMetadataError as exc:
            if "unknown canonical story_id" in str(exc):
                raise EditorNotFound("Story не е намерена.") from exc
            raise EditorApplicationError("Следването на Story не е валидно.") from exc
    return _story_detail(story_id)


def ignore_story(story_id: str) -> dict:
    story = _story(story_id)
    if story.get("status") == "IGNORED":
        raise EditorInvalidTransition("Story вече е игнорирана.")
    _validate_story_action(story_id, "IGNORE")
    with _COMMAND_LOCK:
        try:
            story_identity.set_story_status(
                story_id,
                "IGNORED",
                inbox=_paths()["inbox"],
                stories=_paths()["stories"],
            )
        except story_store.StoryStoreError as exc:
            if "unknown story_id" in str(exc):
                raise EditorNotFound("Story не е намерена.") from exc
            raise EditorApplicationError("Story не може да бъде игнорирана.") from exc
    return _story_detail(story_id)


def _active_article(article_id: str) -> dict:
    article = _article(article_id)
    if article.get("finalized_at"):
        raise EditorInvalidTransition("Финализирана статия не може да се редактира.")
    return article


def update_focus(article_id: str, focus: str) -> dict:
    _active_article(article_id)
    with _COMMAND_LOCK:
        try:
            editor_article_store.update_editor_focus(article_id, focus)
        except editor_article_store.ArticleStoreError as exc:
            if "unknown article_id" in str(exc):
                raise EditorNotFound("Статията не е намерена.") from exc
            raise EditorApplicationError("Фокусът не може да бъде запазен.") from exc
    return _article_dto_by_id(article_id)


def update_title(article_id: str, expected_version: int, title: str) -> dict:
    _active_article(article_id)
    with _COMMAND_LOCK:
        try:
            editor_article_store.update_article_title(article_id, expected_version, title)
        except editor_article_store.ArticleVersionConflict as exc:
            raise EditorVersionConflict(
                "Заглавието е променено в друга сесия. Няма загубени локални промени."
            ) from exc
        except editor_article_store.ArticleStoreError as exc:
            if "unknown article_id" in str(exc):
                raise EditorNotFound("Статията не е намерена.") from exc
            raise EditorApplicationError("Заглавието не може да бъде запазено.") from exc
    return _article_dto_by_id(article_id)


def save_content(article_id: str, expected_version: int, title: str, body: str) -> dict:
    _active_article(article_id)
    with _COMMAND_LOCK:
        try:
            editor_article_store.save_article_content(article_id, expected_version, title, body)
        except editor_article_store.ArticleVersionConflict as exc:
            raise EditorVersionConflict(
                "Черновата е променена в друга сесия. Няма загубени локални промени."
            ) from exc
        except editor_article_store.ArticleStoreError as exc:
            if "unknown article_id" in str(exc):
                raise EditorNotFound("Статията не е намерена.") from exc
            raise EditorApplicationError("Съдържанието не може да бъде запазено.") from exc
    return _article_dto_by_id(article_id)


# ---------------------------------------------------------------- C4 «Отбележи като готова»


def mark_article_ready(article_id: str, expected_version: int) -> dict:
    """`Отбележи като готова` — the editor's explicit readiness checkpoint.

    The editor has reviewed the CURRENT text and considers this exact version
    ready for finalization. It does not publish, does not finalize, does not
    freeze the Story and does not accept any future changed content.

    The frontend never decides readiness. It sends only the version it observed;
    the server re-locks the canonical Article, re-checks the state, the version,
    the content, the Story lineage and the current validation, and only then
    records `ready_version`, `ready_at` and `ready_validation_digest`.
    """
    with _COMMAND_LOCK:
        article = _active_article(article_id)
        content = editor_article_store.get_article_content(article_id)
        state = editor_projections.derive_article_state(article, content, None)
        if state != "draft":
            # `Чернова → Готова` is the only transition C4 owns. Preparation has
            # nothing to review yet, and a current `Готова` checkpoint is not
            # re-recorded over a fresh validation.
            raise EditorInvalidTransition(
                "Отбелязване като готова е налично само за чернова в текущо състояние."
            )
        if int(content.get("content_version", -1)) != int(expected_version):
            # The editor must review the current content first. An old version is
            # never validated-then-blessed as a newer one.
            raise EditorVersionConflict(
                "Черновата е променена. Прегледайте текущата версия преди да я отбележите като готова."
            )
        if (
            not str(content.get("title") or "").strip()
            or not str(content.get("body") or "").strip()
        ):
            raise EditorApplicationError(
                "Черновата няма текст, който може да се отбележи като готов."
            )
        if not editor_projections.can_mark_article_ready(article, content):
            raise EditorInvalidTransition(
                "Потвърдете фокуса, преди да отбележите черновата като готова."
            )
        facts, missing = _story_evidence_projection(article["story_id"])
        story = _maybe_story(article["story_id"])
        try:
            validation = article_validation.evaluate_current_content(
                article,
                content,
                story=story,
                facts=facts,
                gaps=list(missing["items"]),
                headline=_story_headline(article, story),
                assessed_at=str(missing.get("assessedAt") or ""),
            )
        except article_validation.ValidationUnavailable as exc:
            # Fail closed: a validation that could not run is not a pass, is not
            # an empty warning set and never writes a readiness checkpoint.
            raise EditorValidationUnavailable(
                "Проверката на черновата не можа да завърши. Опитайте отново."
            ) from exc
        if validation.blocking:
            raise EditorSafetyBlocked(
                "Проверката на текущия текст откри пречи. Разгледайте предупрежденията.",
                warnings=[dict(row) for row in validation.warnings if row["blocking"]],
            )
        if editor_projections.derive_article_state(article, content, validation.digest) != "draft":
            # The checkpoint for this exact version is already current, so the
            # Article really is `Готова`. Re-recording it is not a C4 transition.
            raise EditorInvalidTransition("Статията вече е отбелязана като готова.")
        try:
            editor_article_store.mark_article_ready(
                article_id,
                expected_version=expected_version,
                validation=editor_article_store.ReadinessValidation(
                    content_version=validation.content_version,
                    digest=validation.digest,
                    blocking=validation.blocking,
                ),
            )
        except editor_article_store.ArticleVersionConflict as exc:
            raise EditorVersionConflict(
                "Черновата е променена, преди да бъде отбелязана като готова."
            ) from exc
        except editor_article_store.ArticleStoreError as exc:
            if "unknown article_id" in str(exc):
                raise EditorNotFound("Статията не е намерена.") from exc
            raise EditorApplicationError(
                "Черновата не може да бъде отбелязана като готова. Опитайте отново."
            ) from exc
    return _article_dto_by_id(article_id)


# ------------------------------------- C5 «Редактирай» (Готова → Чернова) / «Финализирай»


def _finalization_evidence(article: dict) -> dict:
    """The editor-visible evidence basis, frozen as finalization traceability."""
    facts, missing = _story_evidence_projection(article["story_id"])
    return {"facts": facts, "missing": missing}


def reopen_article(article_id: str) -> dict:
    """`Готова → Чернова` — the explicit editor decision to keep working.

    It is a decision, not an edit: the readiness checkpoint is invalidated, the
    content version does not move, and the Article id, Story lineage, title,
    body, focus, generated Draft and internal lineage are all preserved. The
    editor has to press `Отбележи като готова` again after the review cycle -
    an unchanged body never becomes `Готова` by itself.
    """
    with _COMMAND_LOCK:
        article = _article(article_id)
        if article.get("finalized_at"):
            raise EditorInvalidTransition("Финализирана статия не може да се редактира.")
        # The canonical projection decides, exactly as everywhere else: a
        # checkpoint whose validation has moved on is no longer `Готова` and is
        # already an ordinary `Чернова`, so there is nothing to reopen.
        projected, current_digest = _article_projection_by_id(article_id)
        if current_digest is None or projected["state"] != "ready":
            # The checkpoint is not current (or never existed), so the Article
            # already projects as `Чернова`/`Подготовка`. Re-recording that is
            # not a C5 transition.
            raise EditorInvalidTransition(
                "Редактиране на готова статия е налично само за текущо готова статия."
            )
        try:
            editor_article_store.reopen_article(article_id)
        except editor_article_store.ArticleStoreError as exc:
            if "unknown article_id" in str(exc):
                raise EditorNotFound("Статията не е намерена.") from exc
            raise EditorApplicationError(
                "Статията не може да се върне към чернова. Опитайте отново."
            ) from exc
    return _article_dto_by_id(article_id)


def _finalize_validation(article: dict):
    """The C4 current-content validation, re-run now for the finalize decision.

    Deliberately the same code path as `Отбележи като готова`: no second
    validation engine, no reuse of a stored digest, and fail-closed when the
    check itself cannot run.
    """
    content = editor_article_store.get_article_content(article["article_id"])
    facts, missing = _story_evidence_projection(article["story_id"])
    story = _maybe_story(article["story_id"])
    try:
        return article_validation.evaluate_current_content(
            article,
            content,
            story=story,
            facts=facts,
            gaps=list(missing["items"]),
            headline=_story_headline(article, story),
            assessed_at=str(missing.get("assessedAt") or ""),
        )
    except article_validation.ValidationUnavailable as exc:
        raise EditorValidationUnavailable(
            "Проверката на текста не можа да завърши. Опитайте отново."
        ) from exc


def _finalized_article_dto(article_id: str) -> dict:
    """The editor-facing finalized projection plus its Archive target."""
    article = _article(article_id)
    dto = _archive_dto(article)
    return {
        "articleId": dto["id"],
        "archivePath": f"/archive/{dto['id']}",
        "finalizedAt": dto["finalizedAt"],
        "article": dto,
    }


def _write_finalized_snapshot(article: dict, validation, expected_version: int) -> dict:
    """Write the immutable snapshot, then the canonical finalized metadata.

    The snapshot document is durable before the Article record that points at
    it, so an interrupted write can only leave an orphan snapshot - never a
    finalized Article whose content is not there.
    """
    try:
        return editor_article_store.finalize_article(
            article["article_id"],
            expected_version=expected_version,
            validation=editor_article_store.ReadinessValidation(
                content_version=validation.content_version,
                digest=validation.digest,
                blocking=validation.blocking,
            ),
            evidence=_finalization_evidence(article),
        )
    except editor_article_store.ArticleVersionConflict as exc:
        raise EditorVersionConflict("Статията е променена, преди да бъде финализирана.") from exc
    except editor_article_store.ArticleStoreError as exc:
        if "unknown article_id" in str(exc):
            raise EditorNotFound("Статията не е намерена.") from exc
        raise EditorApplicationError(
            "Статията не може да бъде финализирана. Опитайте отново."
        ) from exc


def _repeat_finalization(article: dict, expected_version: int) -> dict:
    """Answer a duplicate/lost-response retry with the same finalized Article.

    The store re-checks that the repeat is the *same* attempt - the same exact
    content version and the same readiness digest. A genuinely different
    request against an already finalized Article is refused instead of rewriting
    the snapshot.
    """
    validation = _finalize_validation(article)
    _write_finalized_snapshot(article, validation, expected_version)
    return _finalized_article_dto(article["article_id"])


def finalize_article(article_id: str, expected_version: int, *, idempotency_key: str = "") -> dict:
    """`Финализирай` — freeze one exact validated Article as the Archive copy.

    **This never means "the stored state says ready".** Under the command lock
    the canonical Article is reloaded and the C4 current-content validation is
    re-run from scratch; its fresh deterministic digest must equal the
    `ready_validation_digest` recorded when the editor pressed `Отбележи като
    готова`. That is what protects the case where the text never changed but
    the evidence basis did: the digest moves, the checkpoint is stale, and
    finalization is refused with `INVALID_TRANSITION` instead of blessing an
    old decision.

    Finalization is *not* publishing. Nothing is scheduled, delivered or sent
    anywhere; the only product effect is the immutable Article in `Архив`.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise EditorApplicationError("Idempotency key is required.")
    with _COMMAND_LOCK:
        article = _article(article_id)
        if editor_article_store.read_finalized_article(article_id) is not None:
            # A repeated attempt is answered with the same canonical finalized
            # Article instead of a second Archive entry. The store, not this
            # branch, decides whether the repeat is the same attempt.
            return _repeat_finalization(article, expected_version)
        if article.get("finalized_at"):
            raise EditorInvalidTransition(
                "Статията вече е финализирана и не може да бъде променяна."
            )
        story = _maybe_story(article["story_id"])
        if story is None or story.get("story_id") != article["story_id"]:
            raise EditorInvalidTransition("Историята на статията вече не е достъпна.")
        content = editor_article_store.get_article_content(article_id)
        if int(content.get("content_version", -1)) != int(expected_version):
            # The editor must finalize the version they actually reviewed.
            raise EditorVersionConflict(
                "Статията е променена. Прегледайте текущата версия преди да я финализирате."
            )
        if (
            not str(content.get("title") or "").strip()
            or not str(content.get("body") or "").strip()
        ):
            raise EditorApplicationError("Статията няма текст, който може да бъде финализиран.")
        if not editor_projections.can_mark_article_ready(article, content):
            raise EditorInvalidTransition("Потвърдете фокуса, преди да финализирате статията.")
        if article.get("ready_version") != content.get("content_version") or not article.get(
            "ready_validation_digest"
        ):
            raise EditorInvalidTransition(
                "Статията не е отбелязана като готова. Прегледайте я отново."
            )
        validation = _finalize_validation(article)
        if validation.blocking:
            raise EditorSafetyBlocked(
                "Проверката на текущия текст откри пречи. Разгледайте предупрежденията.",
                warnings=[dict(row) for row in validation.warnings if row["blocking"]],
            )
        if validation.digest != article["ready_validation_digest"]:
            # The release gate: same text, different validation basis. The old
            # Ready decision is not silently accepted, and the Article stops
            # being presented as safely finalizable.
            raise EditorInvalidTransition(
                "Проверката на текста се е променила след отбелязването му като готов. "
                "Прегледайте черновата отново."
            )
        _write_finalized_snapshot(article, validation, expected_version)
    return _finalized_article_dto(article_id)
