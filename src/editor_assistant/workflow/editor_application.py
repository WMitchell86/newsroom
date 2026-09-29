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

from editor_assistant.drafting import model_router
from editor_assistant.drafting.evidence import EvidenceError, validate_packet
from editor_assistant.workflow import (
    article_draft_failure,
    article_generation,
    article_readiness,
    article_rewrite,
    article_validation,
    draft_enrichment,
    draft_material,
    editor_article_store,
    editor_projections,
    editor_queries,
    editorial_title,
    focus_suggestions,
    grouping_health,
    inbox_store,
    live_store,
    newsroom_refresh,
    newsroom_run,
    publication_material,
    quick_draft,
    rewrite_feedback,
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
    #: The editor-safe sentence for a refusal that is raised by class rather
    #: than by instance. The API boundary sends `str(exc)`, so a class with no
    #: message of its own must still say something true.
    default_message = ""

    def __str__(self) -> str:
        return super().__str__() or self.default_message


class EditorNotFound(EditorApplicationError):
    code = "NOT_FOUND"
    status = 404


class EditorInvalidTransition(EditorApplicationError):
    code = "INVALID_TRANSITION"
    status = 409


class EditorResearchUnavailable(EditorApplicationError):
    """Research cannot run at all right now: no search provider or route.

    V1.2-G2.2 §3. This is an OPERATIONAL refusal, and it is deliberately not one
    of the evidence reasons. Telling the editor that "no opened source was
    found" when nothing was ever searched for is the conflation this class
    exists to end. No route id, model name, HTTP status or provider detail ever
    crosses this boundary.
    """

    code = "RESEARCH_UNAVAILABLE"
    status = 503
    default_message = "Автоматичното проучване временно не е налично."


class EditorResearchQuotaExhausted(EditorApplicationError):
    """The bounded research-round budget for THIS Story is spent.

    V1.2-G2.2 §3, corrected by owner review: `MAX_RESEARCH_ROUNDS` is a
    per-Story bound, NOT a provider, daily or account quota. The old wording
    ("...е изчерпан за момента") let an editor conclude the account had run out
    of quota, which is a different and wrong fact. The sentence now names the
    real scope: the limit of this Story.

    The HTTP 429 status is kept for the client, but the sentence never implies an
    external quota the backend cannot actually observe. A genuine external quota
    or provider outage stays under RESEARCH_UNAVAILABLE.
    """

    code = "RESEARCH_QUOTA_EXHAUSTED"
    status = 429
    default_message = "Достигнат е лимитът за автоматично проучване на тази история."


class EditorVersionConflict(EditorApplicationError):
    code = "ARTICLE_VERSION_CONFLICT"
    status = 409


# --- V1.2-G2.4 §R4: every research terminal outcome has its own sentence ----
#
# The owner's regression showed one generic sentence standing in for at least
# five different real branches. These classes are that branch made explicit.


class EditorResearchNoSource(EditorApplicationError):
    """Research completed but opened no usable page at all."""

    code = "RESEARCH_NO_SOURCE"
    status = 409
    default_message = "Не успяхме да отворим подходящ източник."


class EditorResearchNotConfirmed(EditorApplicationError):
    """Sources were opened and read; the information is simply not confirmed.

    This is the branch the owner's real case took. It is emphatically NOT a
    failure: the round completed, pages opened, claims were extracted, and the
    gate declined them for want of an independent second publisher.
    """

    code = "RESEARCH_NOT_CONFIRMED"
    status = 409
    default_message = "Намерени са източници, но информацията още не е достатъчно потвърдена."


class EditorResearchInterrupted(EditorApplicationError):
    """A genuine technical interruption. The only "try again" branch."""

    code = "RESEARCH_INTERRUPTED"
    status = 503
    default_message = "Проучването прекъсна поради технически проблем. Опитайте отново."


class EditorResearchNotApplicable(EditorApplicationError):
    """This Story is not in a researchable state at all.

    A distinct class AND a distinct code rather than reusing the generic
    `EditorInvalidTransition`, because §R4 requires the editor-facing sentence to
    name the real branch, and `INVALID_TRANSITION` is shared with unrelated
    lifecycle refusals whose sentence is about the Article, not about research.
    The wording is the one the async start path has always used, so nothing
    editor-visible changes for this branch.
    """

    code = "RESEARCH_NOT_APPLICABLE"
    status = 409
    default_message = "Проучването не е налично за тази Story."


#: §R4 — reason -> the refusal class that describes it truthfully. Every entry is
#: a real, distinguishable branch; a reason outside this map can only ever be
#: reported as a technical interruption, never as an evidence statement.
_RESEARCH_REFUSALS = {
    story_research.ROUNDS_EXHAUSTED: EditorResearchQuotaExhausted,
    story_research.PROVIDER_UNAVAILABLE: EditorResearchUnavailable,
    story_research.NOT_RESEARCHABLE: EditorResearchNotApplicable,
    story_research.NOTHING_OPENED: EditorResearchNoSource,
    story_research.INSUFFICIENT_CORROBORATION: EditorResearchNotConfirmed,
    story_research.TECHNICAL_FAILURE: EditorResearchInterrupted,
}

#: §R4 — the one sentence allowed to mean "something broke". It exists only for
#: a genuine technical interruption, and a test asserts that no other terminal
#: research outcome can produce it.
RESEARCH_TECHNICAL_MESSAGE = EditorResearchInterrupted.default_message


def _research_refusal(exc) -> EditorApplicationError:
    """Map a research failure onto the editor-facing class for its real branch."""
    reason = str(getattr(exc, "reason", "") or "")
    cls = _RESEARCH_REFUSALS.get(reason, EditorResearchInterrupted)
    message = str(exc or "").strip()
    if cls is EditorResearchInterrupted or not message:
        # A transport or programming detail never reaches the editor; the
        # honest "try again" sentence does.
        message = cls.default_message
    return cls(message)


class EditorDraftNotReady(EditorApplicationError):
    """V1.1-B — the refusal class for every evidence-remedy reason.

    V1.2-G4.1 §B: this family is now just two members — `STORY_UNASSESSED` (the
    Story was never researched) and `NO_DRAFT_MATERIAL` (it was, and there is
    genuinely nothing to write from). They share an HTTP status and a remedy
    (research the owning Story), so they share a class — but the instance
    `code` is always the exact readiness code, never a collapsed umbrella code.
    The editor and the API therefore receive the same string the preparation
    projection reported.

    `BLOCKING_GAP` is no longer a member: an unresolved question is a warning on
    the Draft, not a refusal to start it.
    """

    status = 409

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class EditorBlockingGap(EditorDraftNotReady):
    """The canonical Story basis still has a blocking gap. No generation.

    V1.2-G4.1 §B: **this is no longer a Draft-gate refusal.** A Story-level
    blocking gap by itself no longer prevents `MAKE_DRAFT`; the gap travels with
    the Draft as a warning. The class is kept only because the generation
    pipeline itself — the angle gate and its own sufficiency check — still raises
    `BLOCKING_GAP` for material it cannot draft from at all, which is a
    different condition with a different moment.
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


def _registry_title_identities() -> tuple:
    """Registry rows for title cleaning, resolved from the canonical newsroom.

    Resolved through the newsroom root exactly like the collector resolves its
    own files. `sources_registry.sources_path()` with no argument would read the
    repository's real registry even when the newsroom root is redirected, which
    is precisely the isolation every test and every browser fixture depends on.
    """
    return editorial_title.load_registry_rows(
        newsroom_refresh.newsroom_paths(_newsroom_root())["sources"]
    )


def _registry_rows_by_domain() -> dict[str, list[dict]]:
    """Registry rows grouped by publisher domain, for authority resolution.

    Same rows, same newsroom root and therefore same isolation as every other
    registry read here; only the grouping differs, because authority is
    resolved by publisher identity and not by source id.
    """
    rows = _registry_title_identities()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        domain = str((row or {}).get("domain") or "").lower()
        if domain:
            grouped.setdefault(domain, []).append(row)
    return grouped


def _opened_source_projection(source: dict) -> dict:
    """One opened publication, resolved to the authority the editor configured.

    V1.2-G4.1 §B3/§G. Authority comes from the SAME registry the research path
    already consults, matched by publisher identity so `www.burgas.bg` resolves
    to the `burgas.bg` row. This introduces no new trust system: G4's
    `Надежден за факти` remains the only authority in the product, and a source
    the registry does not know is simply not a factual authority.

    `claims` are the verbatim sentences this opened page yielded. They are NOT
    confirmed facts and are never presented as such — they are what an attributed
    Draft may be written from, and they travel with their own locator so the text
    can always be traced back to this page.
    """
    url = str((source or {}).get("url") or "")
    host = (urlsplit(url).hostname or "").lower()
    resolved = newsroom_run.resolve_publisher_policy(
        host,
        _registry_rows_by_domain(),
        publisher_identity=story_store.publisher_identity,
    )
    return {
        "id": str((source or {}).get("id") or ""),
        "name": str((source or {}).get("name") or ""),
        "url": url,
        "domain": str((source or {}).get("domain") or host),
        "factualAuthority": bool(resolved["factual_authority"]),
        "authority": "PRIMARY" if resolved["factual_authority"] else "CORROBORATING",
        "claims": [
            {
                "text": str(claim.get("text") or ""),
                "locator": str(claim.get("locator") or ""),
            }
            for claim in ((source or {}).get("claims") or [])
            if str(claim.get("text") or "").strip()
        ],
    }


def _story_title(story: dict, items_by_id: dict) -> str:
    """The Story's editorial title: the headline, without publisher decoration.

    V1.2-G2.1 §A5. This is the single funnel every editor-facing title passes
    through - the Story workspace, the Today row, the research query and both
    Article-creation paths - so the rule lives here once and nowhere else. The
    raw inbox title and the Publication title are untouched (§A2): only what the
    editor reads is cleaned, and the source material keeps the exact string the
    feed delivered.
    """
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    meaningful = editor_projections.meaningful_developments(story, items_by_id)
    latest = meaningful[0] if meaningful else {}
    item = representative if representative.get("title") else (latest or {})
    return editorial_title.editorial_title_for_item(
        item, registry_rows=_registry_title_identities()
    )


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
    # V1.2-G4.1 §B3: the opened publications, with the authority the editor's own
    # source settings give them. A basis may now hold an opened page that
    # promoted no fact, and that page is exactly the material the single-source
    # Draft rule needs. Carried on the `missing` mapping rather than returned as
    # a third value so every existing call site keeps its shape.
    missing_projection = {
        "items": unique_gaps,
        "assessedAt": assessed_at,
        "evidenceStatus": evidence_status,
        "openedSources": [_opened_source_projection(item) for item in basis["sources"]],
    }
    return unique_facts, missing_projection


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
        readiness = readiness or article_readiness.DraftReadiness(
            eligible=False,
            reason_code=article_readiness.STORY_UNAVAILABLE,
            reason_message=article_readiness.REASON_MESSAGES[article_readiness.STORY_UNAVAILABLE],
        )
        # V1.2-G4.3 §C: an unconfirmed Focus no longer hides `Чернова`. The
        # command writes the deterministic default, so the editor is never made
        # to type a sentence before they can write. `SELECT_FOCUS` stays
        # OFFERED - changing the Focus is still a real choice - it simply stops
        # being the only thing they can do.
        actions = (
            ["CHANGE_FOCUS"] if editor_projections.focus_is_confirmed(article)
            else ["SELECT_FOCUS", "CHANGE_FOCUS"]
        )
        if manual_continuation:
            actions.append("EDIT")
        if readiness.eligible:
            actions.append("MAKE_DRAFT")
            return actions, _next_action("MAKE_DRAFT", readiness.reason_code, "Направи чернова")
        if readiness.reason_code == article_readiness.DRAFT_FROM_UNREAD_SOURCE:
            # Nothing is read yet, but the Draft command reads the Story's own
            # publication itself, so attempting is the right action. `draftEligible`
            # stays false - the material is not confirmed - while the button is
            # offered, because the editor should not have to research first.
            actions.append("MAKE_DRAFT")
            return actions, _next_action(
                "MAKE_DRAFT", readiness.reason_code, "Направи чернова"
            )
        # Focus is no longer a refusal source, so the only remaining refusals are
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
    # V1.2-G4.3 §D/§E: on a real Draft the editor gets the two secondary writing
    # controls. `CHANGE_VOICE` is a style preference and `REWRITE` is the
    # comment-driven loop; neither is a state, neither is ever the next action,
    # and both stay available whatever the warnings say. Warnings warn; they do
    # not take away the editor's ability to keep working on the text.
    if str(content.get("body") or "").strip():
        actions.append("CHANGE_VOICE")
        actions.append("REWRITE")
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


def _voice_label(voice) -> str:
    """The editor wording for a Voice id, with automatic as the honest default.

    §D forbids model/provider terminology in the editor UI, so this is a label
    read from the one place the option list is built, never a formatted id.
    """
    value = str(voice or "").strip()
    for option in editor_article_store.editorial_voice_options():
        if option["id"] == value:
            return str(option["label"])
    return "Автоматично"


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
    readiness_snapshot = article_readiness.build_snapshot(
        article,
        content,
        story,
        facts,
        missing,
        missing.get("openedSources") or (),
        # V1.2-G4.3 §A: the projection cannot fetch, so it states the purely
        # local half of the question - is this Story's own publication worth
        # one bounded read? That is what keeps `Чернова` offered for a Story the
        # command can actually write, instead of only for one already researched.
        readable_publication=bool(
            story
            and _original_publication_is_readable(
                story.get("story_id"), story, resolve=False
            )
        ),
    )
    readiness = article_readiness.evaluate(readiness_snapshot)
    # V1.2-G4.1 §B3 — the material warnings a Draft inherits from its basis. They
    # are recomputed from the SAME canonical basis, not stored on the Article, so
    # they can never go stale: a second source arriving clears the single-source
    # warning by itself, with no migration and no state to reconcile.
    basis_decision = draft_material.assess(
        facts=facts,
        sources=missing.get("openedSources") or (),
        blocking_gaps=missing["items"],
        evidence_status=str(missing.get("evidenceStatus") or ""),
    )
    draft_warnings = list(basis_decision["warnings"])
    # V1.2-G4.2 §16: for an Article that already has a generated Draft, the
    # material basis recorded WITH the text is the authority — it describes what
    # was actually written, including a publication read outside Research, which
    # by construction leaves the research basis empty and would otherwise warn
    # about nothing.
    recorded = article.get("draft_material_basis") or {}
    if recorded.get("basis") and state != "preparation":
        draft_warnings = []
        if recorded.get("attributionRequired"):
            draft_warnings.append(draft_material.WARNING_SINGLE_SOURCE)
        # V1.2-G4.3: the open question is NOT repeated here. `article_validation`
        # already raises one `blocking_gap_open` warning that states the same
        # condition AND carries the actual question, and the evidence rail lists
        # that question. A third phrasing of "there is still an open question" is
        # what made the Draft screen say the same thing four times.
        if not draft_warnings:
            draft_warnings = list(basis_decision["warnings"])
        # §A2: what the automatic gathering did is part of what this Draft was
        # written from, so it is reported beside the material warnings. These
        # are the sentences four specifications promise the editor will see.
        draft_warnings.extend(recorded.get("enrichmentWarnings") or [])
    elif state != "preparation" and draft_material.WARNING_OPEN_GAPS in draft_warnings:
        # Once a Draft exists, `blocking_gap_open` above is the authority for the
        # open questions; the Preparation wording ("преди черновата да е готова")
        # is wrong for a Draft and duplicative of it.
        draft_warnings = [
            warning for warning in draft_warnings if warning != draft_material.WARNING_OPEN_GAPS
        ]
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
        # §D2: the quiet alternatives, derived deterministically and served with
        # the projection so the page never recomputes them. `[]` is a normal
        # outcome, never an error, and it never blocks a Draft.
        _focus_text, alternatives = _suggested_focus(article["story_id"], story)
        preparation = {
            "focusConfirmed": focus_confirmed,
            "focusAlternatives": list(alternatives),
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
            # V1.2-G4.3 §D: the optional Voice choice, the label the editor sees,
            # and the small set they may choose from. `""` is Автоматично.
            "style": {
                "voice": str(article.get("editorial_voice") or ""),
                "label": _voice_label(article.get("editorial_voice")),
                "options": [
                    dict(option) for option in editor_article_store.editorial_voice_options()
                ],
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
            # V1.2-G4.1 §B3/§C2 — the material warnings this Draft carries,
            # recomputed from the canonical basis on every read. A single-source
            # Draft says so, and says so here rather than only in the audit of the
            # generation that produced it.
            "draftWarnings": draft_warnings,
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
        # V1.2-G2.1 §A5: the Story projection shows the editorial title, so it
        # goes through the same helper as Today, Article creation and research.
        "title": _story_title(story, items_by_id),
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
    facts, missing = _story_evidence_projection(story_id, articles)
    related_articles = _story_related_articles(
        story_id, articles, story, items_by_id, facts, missing
    )
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
            # V1.2-G2 §3: the independent-publisher count, surfaced from the
            # `story_store.metrics` computation the system already uses for
            # Today. Already-existing domain data, no new semantics: React must
            # never count a source itself, and the count is corroboration
            # context, never evidence authority.
            "publisherCount": story_store.metrics(story, items_by_id)["publisher_count"],
            # V1.2-G2.2 §9: which grouped publication IS the original. The
            # Story already stores it as `representative_item_id` (the ORIGIN
            # member), so this only names it — already-existing domain data, and
            # it is what lets the workspace offer `Отвори оригинала` without
            # React ever guessing which member came first.
            "originPublicationId": editor_projections.publication_id_for(
                "", str(story.get("representative_item_id") or "")
            )
            if story.get("representative_item_id")
            else None,
            "correction": {"available": False, "actions": []},
        }
    )
    return result


def _story_article_state(
    article: dict,
    content: dict,
    *,
    story: dict,
    items_by_id: dict,
    facts: list[dict],
    missing: dict,
) -> str | None:
    """The canonical Article state, decided exactly as the workspace decides it.

    V1.2-G2 §22: the Story page shows which state each of its Articles is in, so
    the editor can see at a glance whether a Story already has a Preparation, a
    Draft or a Готова piece. That word is not a second decision: it comes from
    the same `_current_validation` digest and the same
    `editor_projections.derive_article_state` the Article workspace and Today
    read, so the three surfaces can never disagree about one Article.
    """
    _, validation = _current_validation(
        article,
        content,
        story=story,
        facts=facts,
        gaps=list(missing["items"]),
        headline=_story_headline(article, story, items_by_id),
        assessed_at=str(missing.get("assessedAt") or ""),
    )
    digest = validation.digest if validation is not None else None
    return editor_projections.derive_article_state(article, content, digest)


def _story_related_articles(
    story_id: str,
    articles: list[dict],
    story: dict,
    items_by_id: dict,
    facts: list[dict],
    missing: dict,
) -> list[dict]:
    """The Story's Articles, each with its canonical state.

    A finalized Article stays related to its Story; the link then targets the
    Archive, and `derive_article_state` answers `None` for it, which is the
    truth: it has left the active workflow.
    """
    rows = []
    for record in articles:
        if record.get("story_id") != story_id:
            continue
        content = editor_article_store.get_article_content(record["article_id"])
        rows.append(
            {
                "id": record["article_id"],
                "title": record["working_title"],
                "updatedAt": record["updated_at"],
                "finalizedAt": record.get("finalized_at"),
                "state": _story_article_state(
                    record,
                    content,
                    story=story,
                    items_by_id=items_by_id,
                    facts=facts,
                    missing=missing,
                ),
            }
        )
    return rows


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
    # §3: the round budget and the provider chain are two different operational
    # problems and must never reach the editor as one "cannot research" wall —
    # and neither may ever be dressed up as missing evidence.
    if basis["research_rounds"] >= readiness_mod.MAX_RESEARCH_ROUNDS:
        raise EditorResearchQuotaExhausted
    if not search_mod.provider_chain(capability=search_mod.CAP_WEB)[0]:
        raise EditorResearchUnavailable
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
    # NOTE: no global lock across the executor. `execute_story_research`
    # performs the search/page/model work; holding `_COMMAND_LOCK` here would
    # serialize every unrelated command behind a slow research round. The
    # executor owns its own store atomicity.
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
        # §R4: the editor must be told which of the real branches produced
        # this. The owner's real case read "Проучването не можа да завърши."
        # for a round that had actually completed and simply found no
        # second publisher, which told the editor nothing about whether to
        # wait, retry, or look for another source. Every branch now maps to
        # its own truthful sentence.
        raise _research_refusal(exc) from exc
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
    # §3: an unassessed Story and a real gap are the two states research answers.
    # Everything else is a refusal, and the three refusals are three different
    # things: this Story is not in a researchable state, the bounded round budget
    # is spent, or no search provider is available at all.
    if story.get("status") == "IGNORED" or (not gaps and not unassessed):
        raise EditorInvalidTransition("Проучването не е налично за тази Story.")
    if basis["research_rounds"] >= readiness_mod.MAX_RESEARCH_ROUNDS:
        raise EditorResearchQuotaExhausted
    if not search_mod.provider_chain(capability=search_mod.CAP_WEB)[0]:
        raise EditorResearchUnavailable

    def work():
        return research_story(story_id)

    token, view = story_operations.start(
        story_id, signature, work, generation=generation, key=idempotency_key
    )
    return {"operationToken": token, "status": view["status"]}


#: G4.5-hardening: the generic operation envelope no longer hardcodes
#: `SOURCE_UNAVAILABLE`. Research workers raise `StoryResearchError` with a
#: closed `reason`; refresh workers raise `RefreshUnavailable` / `RefreshBusy`
#: with their own sentences. Both survive the registry as `error_code` /
#: `error`; the map below reports each classified branch truthfully, and
#: anything unclassified stays a neutral technical failure - never a guessed
#: source, quota or provider cause.
_GENERIC_OPERATION_ERRORS = {
    # --- research (story_research.RESEARCH_REASONS) ---
    "ROUNDS_EXHAUSTED": (
        "RESEARCH_QUOTA_EXHAUSTED",
        EditorResearchQuotaExhausted.default_message,
        False,
    ),
    "PROVIDER_UNAVAILABLE": (
        "RESEARCH_UNAVAILABLE",
        EditorResearchUnavailable.default_message,
        True,
    ),
    "NOT_RESEARCHABLE": (
        "RESEARCH_NOT_APPLICABLE",
        EditorResearchNotApplicable.default_message,
        False,
    ),
    "NOTHING_OPENED": (
        "RESEARCH_NO_SOURCE",
        EditorResearchNoSource.default_message,
        False,
    ),
    "INSUFFICIENT_CORROBORATION": (
        "RESEARCH_NOT_CONFIRMED",
        EditorResearchNotConfirmed.default_message,
        False,
    ),
    "TECHNICAL_FAILURE": (
        "RESEARCH_INTERRUPTED",
        EditorResearchInterrupted.default_message,
        True,
    ),
    # --- refresh (newsroom_refresh) ---
    "REFRESH_BUSY": (
        "REFRESH_BUSY",
        "Обновяването вече тече. Изчакайте да завърши.",
        True,
    ),
    "REFRESH_UNAVAILABLE": (
        "REFRESH_UNAVAILABLE",
        (
            "Обновяването не е налично: няма активни източници или източниците "
            "не могат да бъдат прочетени."
        ),
        False,
    ),
}
_GENERIC_OPERATION_DEFAULT = (
    "OPERATION_UNAVAILABLE",
    "Операцията не можа да завърши поради технически проблем. Опитайте отново.",
    True,
)
_GENERIC_REFRESH_DEFAULT = (
    "REFRESH_UNAVAILABLE",
    "Обновяването не можа да завърши поради технически проблем. Опитайте отново.",
    True,
)


def _generic_operation_error(scope: str, code: str, detail: str) -> dict:
    """Truthful envelope for a failed Research / Refresh operation.

    A classified worker code keeps its own editor sentence. Anything else is a
    neutral technical failure with its own code: the raw exception text is NOT
    echoed here (it can carry a provider name, a filesystem path or an echoed
    credential), and no source/quota/provider cause is invented for it. The raw
    text stays in the operation log for the operator.
    """
    entry = _GENERIC_OPERATION_ERRORS.get(str(code or ""))
    if entry is not None:
        name, message, retryable = entry
        return {"code": name, "message": message, "retryable": retryable}
    if scope == REFRESH_SCOPE:
        name, message, retryable = _GENERIC_REFRESH_DEFAULT
    else:
        name, message, retryable = _GENERIC_OPERATION_DEFAULT
    return {"code": str(code or name)[:64] or name, "message": message, "retryable": retryable}


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
                "error": article_generation.operation_error(
                    row.get("error_code") or "", row.get("error") or ""
                ),
            }
        if article_rewrite.is_rewrite_scope(row.get("story_id")):
            # §E4: the same contract for a rewrite, with its own wording. The
            # editor's comment and the current body are both still on screen.
            return {
                "operationToken": token,
                "status": row["status"],
                "error": article_rewrite.operation_error(row.get("error_code") or ""),
            }
        if quick_draft.is_quick_draft_scope(row.get("story_id")):
            # §19: a Quick Draft failure carries only a bounded code and one
            # editor sentence. No provider, no model id, no search internals.
            return {
                "operationToken": token,
                "status": row["status"],
                "error": quick_draft.operation_error(),
            }
        # G4.5-hardening: the remaining scopes are Research and Refresh. Their
        # workers raise classified refusals (research reasons, RefreshBusy /
        # RefreshUnavailable) whose codes survive in `error_code`; the raw
        # exception text survives in `error`. Anything else keeps the unknown
        # code and a neutral technical sentence - never a guessed source,
        # quota or provider cause the system did not observe.
        return {
            "operationToken": token,
            "status": row["status"],
            "error": _generic_operation_error(
                row.get("story_id") or "",
                row.get("error_code") or "",
                row.get("error") or "",
            ),
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


def _draft_readiness_basis(article_id: str) -> dict:
    """The store-only half of the Draft snapshot: canonical reads, no I/O.

    V1.2-G4.4. Every read here is a local store read, so this is the whole of
    the Draft command that is allowed to run inside the HTTP request. It is
    deliberately the SAME builder the Article preparation projection uses
    (V1.1-B), so the button the editor is shown and the refusal the command
    raises are still one decision computed from one state.

    What is NOT here is the slow half: opening the Story's own publication and
    the bounded enrichment. Those run in the worker, after the token exists.
    """
    article = _active_article(article_id)
    content = editor_article_store.get_article_content(article_id)
    story = _story(article["story_id"])
    facts, missing = _story_evidence_projection(article["story_id"])
    items_by_id = _story_items()
    snapshot = article_readiness.build_snapshot(
        article,
        content,
        story,
        facts,
        missing,
        missing.get("openedSources") or (),
        # The SAME locally-computed "is this worth one read" the projection uses.
        # Without it the projection and the command reach different conclusions
        # about the same Article, which is the one thing this file exists to
        # prevent: the editor would see a button the command then refuses.
        # `resolve=False` is what keeps this offline: it inspects the URL the
        # Story already carries and never opens one.
        readable_publication=bool(
            _original_publication_is_readable(article["story_id"], story, resolve=False)
        ),
    )
    return {
        "article": article,
        "content": content,
        "story": story,
        "facts": facts,
        "missing": missing,
        "items_by_id": items_by_id,
        "snapshot": snapshot,
    }


def _draft_preflight(article_id: str) -> None:
    """The request path's authority to accept a Draft, at store-read cost.

    V1.2-G4.4 made the request return `202` before the slow work, and the first
    implementation dropped the readiness decision with it. That silently
    converted four refusals the editor used to get as an immediate, named
    reason into an accepted operation that failed later: an ignored Story
    (`STORY_UNAVAILABLE`), a Story with nothing to write from
    (`NO_DRAFT_MATERIAL` / `STORY_UNASSESSED`) and an Article the editor had
    already typed into (`ARTICLE_HAS_TEXT`) all became "202, then red".

    This is cheap on purpose - it opens no page, runs no enrichment and calls
    no model - and it is not the last word: `_run_draft_generation` re-runs the
    identical decision over the enriched snapshot before any generation, so a
    Story that becomes workable while the operation is queued still drafts.
    """
    readiness = article_readiness.evaluate(_draft_readiness_basis(article_id)["snapshot"])
    if not readiness.eligible and (
        readiness.reason_code != article_readiness.DRAFT_FROM_UNREAD_SOURCE
    ):
        _raise_draft_refusal(
            article_generation.DraftRefused(readiness.reason_code, readiness.reason_message)
        )
    _draft_route_preflight()


def _draft_route_preflight() -> None:
    """Refuse a Draft when no Draft route is worth calling.

    V1.2-G4.8. Measured 2026-09-29 10:17-10:21: the editor pressed «Направи
    чернова», walked away, came back, and found the button still active and
    nothing ready — because the operation took 3 min 49 s to fail. The routes
    are not independent: all four are Gemini on one key sharing one daily
    quota, so when that quota is spent they all fail together, and the router
    discovers it one 60-second timeout at a time. Three of the four are now
    recorded EXHAUSTED, so this check answers in milliseconds.

    It is a *routing* preflight, not a model call: no key is spent, no prompt is
    built, and a route that merely looks unhealthy but may still answer is left
    alone. Only a role with no usable route left is refused, and the refusal
    names the real cause instead of a spinner that never resolves.
    """
    # Only an explicit `False` is a refusal. `None` means the router could not
    # judge (no route table in this environment); refusing then would invent an
    # outage out of missing configuration.
    if model_router.role_has_usable_route("draft") is not False:
        return
    blocked = model_router.exhausted_routes_for("draft")
    detail = ", ".join(f"{row['route'].split(':')[-1]} ({row['status']})" for row in blocked)
    _raise_draft_refusal(
        article_generation.DraftRefused(
            "DRAFT_ROUTE_UNAVAILABLE",
            "Няма достъпен модел за чернова — всички маршрути за ролята са изчерпани"
            + (f": {detail}." if detail else "."),
        )
    )


def _draft_snapshot(article_id: str, *, enrich: bool = True) -> dict:
    """Everything the Draft command is bound to, read from canonical stores.

    Deliberately a snapshot of *server* state: the request carries no facts, no
    focus, no title and no evidence, so a client cannot talk the backend into
    drafting from material it chose.

    **V1.2-G4.3 §E2 — `enrich=False` for a rewrite.** A `Пренапиши` is a
    WRITING operation over the material the editor already judged, so it must
    not go looking for new material. Passing this false keeps the factual basis
    of a rewrite identical to the basis of the Draft it replaces; the automatic
    enrichment stays exactly where the owner put it, on the way to the FIRST
    Draft. The Story's own publication is still read here, because that is the
    same canonical material the first Draft used rather than something newly
    discovered - without it a single-source Draft could not be rewritten at all.

    **V1.1-B:** the readiness-relevant part is now assembled by the shared
    `article_readiness.build_snapshot`, the very builder the Article preparation
    projection uses. There is exactly one evidence snapshot in the product, and
    the command adds only its own packet metadata (headline, summary) on top.
    """
    basis = _draft_readiness_basis(article_id)
    article = basis["article"]
    story = basis["story"]
    facts = basis["facts"]
    missing = basis["missing"]
    items_by_id = basis["items_by_id"]
    snapshot = basis["snapshot"]
    headline = _story_title(story, items_by_id) or article["working_title"]
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    opened = list(missing.get("openedSources") or ())
    # V1.2-G4.2 §2/§3C: when the evidence basis holds no usable material, the
    # Story's OWN publication is read. This happens ONCE per Draft command, on
    # the canonical representative Publication, through the same fetch guards
    # research uses. It is source material for a work-in-progress Draft and is
    # never written to the research store, so no fact is promoted and no gap is
    # cleared.
    if not facts and not any(row.get("claims") for row in opened):
        # The Story's own publication, in the order it can actually be read:
        # a member URL that is a real publisher page first, then — for the very
        # common case of a `news.google.com` collection — the publisher URL the
        # newsroom's own discovery audit already recorded when it collected the
        # item. Both are one bounded read of the Story's own article.
        read = None
        for member in story.get("members") or []:
            item = items_by_id.get(member.get("item_id")) or {}
            read = publication_material.read_publication(str(item.get("url") or ""), topic=headline)
            if read:
                break
        if not read:
            # Every publisher URL this Story's article might be readable at,
            # tried in turn. Two passes: the keyless provider rate-limits, and a
            # throttled lookup must not be what decides that a Story with a real
            # article has no readable material.
            for attempt in (False, True):
                for resolved in publication_material.publication_urls(headline, refresh=attempt):
                    read = publication_material.read_publication(resolved, topic=headline)
                    if read:
                        break
                if read:
                    break
        if read:
            authoritative = _original_publication_is_authoritative(read["domain"])
            opened = [
                {
                    "id": "src_original_publication",
                    "name": read["domain"] or representative.get("publisher_domain") or "източник",
                    "url": read["url"],
                    "domain": read["domain"],
                    # A publication read outside Research carries no authority
                    # claim of its own: whether it is a factual authority is the
                    # editor's own source setting, resolved exactly as before.
                    "factualAuthority": authoritative,
                    "authority": "PRIMARY" if authoritative else "CORROBORATING",
                    "claims": read["claims"],
                    "origin": "original_publication",
                }
            ]
    # V1.2-G4.3 §A: the automatic, bounded enrichment that runs INSIDE `Чернова`.
    #
    # The editor pressed one button and said "give me an Article"; they did not
    # press `Проучи още`. So the system now does the useful part of it by itself,
    # once, here - and this is the ONLY place it runs, so a Draft costs at most
    # one enrichment round no matter how many times the command is re-evaluated.
    #
    # It is opportunistic by construction (§A2): whatever it finds is APPENDED to
    # the opened sources and whatever it fails to find becomes a warning that
    # travels with the Draft. It can never remove material, never promote a fact,
    # never close a gap, and never refuse the command that called it.
    enrichment = _bounded_draft_enrichment(
        headline=headline,
        existing_sources=opened,
    ) if enrich else {"sources": [], "queries": [], "warnings": []}
    opened = draft_enrichment.merge_sources(opened, enrichment["sources"])
    snapshot.update(
        {
            "headline": headline,
            "summary": str(representative.get("summary") or ""),
            "sources": opened,
            # §A2/§I — the enrichment outcome travels WITH the material, so the
            # warnings the editor sees afterwards describe what actually happened
            # and not merely what the canonical basis happens to say.
            "enrichment_warnings": list(enrichment["warnings"]),
            "enrichment_queries": list(enrichment["queries"]),
        }
    )
    return snapshot


def _bounded_draft_enrichment(*, headline: str, existing_sources: list[dict]) -> dict:
    """Run the bounded enrichment, degrading to a warning on ANY problem.

    This wrapper is what makes the promise in §A2 true at the call site rather
    than only inside the enrichment module: whatever happens in there, the
    snapshot still has its original material and a set of editor-safe warnings.

    The open path is deliberately the DEFAULT one (`None` means
    `publication_material` uses its own guarded fetch), so the blocked-domain,
    wrapper and on-topic rules that protect the original read protect the
    discovered pages identically — there is no second fetch implementation.
    """
    try:
        return draft_enrichment.enrich(
            topic=headline,
            existing_urls=[row.get("url") for row in existing_sources],
            questions=draft_enrichment.plan_questions(headline),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # A defect that must not cost the editor their Draft. The material the
        # Story already has is still enough to write one.
        LOG.warning("draft enrichment degraded to a warning: %s", type(exc).__name__)
        return {
            "sources": [],
            "queries": [],
            "warnings": [draft_enrichment.WARNING_ENRICHMENT_UNAVAILABLE],
        }


def _original_publication_is_authoritative(domain: str) -> bool:
    """Whether the editor's own registry marks this publisher a factual authority.

    Read through the SAME registry and the same publisher-identity resolution the
    rest of the product uses, so reading a Story's own publication introduces no
    new trust system (G4 `Надежден за факти` remains the only authority).
    """
    if not domain:
        return False
    try:
        resolved = newsroom_run.resolve_publisher_policy(
            domain,
            _registry_rows_by_domain(),
            publisher_identity=story_store.publisher_identity,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return bool(resolved.get("factual_authority"))


def _draft_signature(snapshot: dict) -> str:
    """Canonical state a Draft command is bound to, so a new one gets a new token.

    NOTE: the live request path pins the operation to the Idempotency-Key
    alone (signature ""), so this stays the binding for keyless callers and
    for documentation of what "the same Draft" means.
    """
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
    if code == "BLOCKING_GAP":
        # V1.2-G4.1: this is now only the generation pipeline's own angle /
        # sufficiency refusal. A Story-level blocking gap never reaches here,
        # because it no longer refuses `MAKE_DRAFT`.
        raise EditorBlockingGap(exc.message) from exc
    # Every remaining evidence-readiness refusal is reported with its own exact
    # code at 409, so the editor can act on the reason and the wording is the
    # one the projection already showed.
    raise EditorDraftNotReady(code, exc.message) from exc


def _record_draft_failure(article_id: str, snapshot: dict, basis: str, code: str) -> None:
    """Persist the durable manual-continuation marker, if this failure qualifies.

    **V1.1-C — the ordering contract.** This is called only from the worker, only
    after the deterministic preflight passed and generation was actually
    attempted, and only when no Draft was published. A preflight refusal
    (`STORY_UNASSESSED`, `NO_DRAFT_MATERIAL`, a stale version, an Article that
    already has text) never reaches it, which is why those can never open the
    editor.

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


def _ensure_default_focus(article_id: str) -> None:
    """Give the Article its deterministic default Focus if it has none (V1.2-G4.3 §C).

    This is what replaces the removed `FOCUS_NOT_CONFIRMED` gate. The Focus is
    still a real, stored, editable field — the editor can change it at any time
    and a changed Focus is used by the next Draft or Rewrite — but a Story the
    editor decided to write about is never blocked from being written.

    Written through the ONE canonical Focus save, deliberately: a default Focus
    must be indistinguishable from an editor-typed one in the store, in the
    projection and in the audit, or "who chose this?" becomes unanswerable.
    """
    article = _active_article(article_id)
    if editor_projections.focus_is_confirmed(article):
        return
    story = _maybe_story(article["story_id"])
    focus, _alternatives = _suggested_focus(
        article["story_id"], story, str(article.get("working_title") or "")
    )
    if not focus:
        # A Story with no usable subject genuinely has no honest Focus. The
        # canonical readiness decision then reports WORKING_TITLE_REQUIRED on
        # its own terms; inventing a sentence here would be worse than useless.
        return
    # NOTE: a short store write only; the canonical Focus save owns its
    # atomicity. Never hold the global lock across network/model work - this
    # runs inside the Draft worker.
    try:
        editor_article_store.update_editor_focus(article_id, focus)
    except editor_article_store.ArticleStoreError as exc:
        LOG.warning("could not store the default Focus for %s", article_id)
        raise article_generation.DraftRefused(
            "FOCUS_NOT_CONFIRMED", "Фокусът на статията не може да бъде определен."
        ) from exc


def _revalidate_before_generation(article_id: str, bound: dict) -> None:
    """Stop a queued Draft if the editor changed the Article after it was bound.

    V1.2-G4.4. The store's expected-version publish is the last line of defence
    and it is sufficient for SAFETY, but it fires only after the whole
    generation has been paid for. This is the cheap check that fires first.

    It asks only about the Article's OWN preconditions, deliberately not
    re-deciding the evidence: `bound` may legitimately hold material the store
    basis does not, because the Story's own publication was read for this very
    command, and re-asking the evidence question would refuse a Draft the
    command can actually write. What cannot have changed underneath the
    generation is the editor's own text, version and lineage.
    """
    try:
        content = editor_article_store.get_article_content(article_id)
    except (editor_article_store.ArticleStoreError, OSError, ValueError, KeyError, TypeError):
        # An unreadable Article is not evidence of a change. The store's own
        # publish check remains the authority, exactly as before this existed.
        return
    if int(content.get("content_version", 0)) == int(bound.get("content_version", -1)):
        return
    # The editor changed something. Re-ask the ONE canonical decision so the
    # refusal names what is actually wrong now: `ARTICLE_HAS_TEXT` tells the
    # editor their text is safe, which a bare version conflict does not.
    readiness = article_readiness.evaluate(_draft_readiness_basis(article_id)["snapshot"])
    code = (
        article_readiness.ARTICLE_VERSION_CONFLICT
        if readiness.eligible
        else readiness.reason_code
    )
    # A `DraftRefused`, not the request path's `_raise_draft_refusal`: this runs
    # inside the worker, where the code is the operation's own stable reason.
    # Going through the HTTP mapping would collapse `ARTICLE_HAS_TEXT` into a
    # generic `INVALID_TRANSITION` and lose the one sentence that tells the
    # editor their text is safe.
    raise article_generation.DraftRefused(
        code,
        article_readiness.REASON_MESSAGES.get(
            code, "Статията е променена, преди черновата да се създаде."
        ),
    )


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
        # V1.2-G4.3 §C: the Draft always has a Focus. When the editor has not
        # written one, the deterministic default is stored here — through the
        # ONE canonical Focus write, so this is indistinguishable from the editor
        # having typed it. That is what makes Focus guidance rather than a gate,
        # and it also keeps `Готова`/finalization reachable afterwards, because
        # both of those still require a confirmed Focus.
        _ensure_default_focus(article_id)
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
        # V1.2-G4.4: one more short canonical read, immediately before the
        # generation. The operation is bound to the state at click time, so an
        # editor edit landing while it is queued must stop the attempt HERE -
        # before a model call is spent - instead of being discovered by the
        # store's expected-version publish after the generation is complete.
        # Without this the editor's text was still safe, but a full Draft was
        # generated, audited and stored for an Article they had already written.
        _revalidate_before_generation(article_id, current)
        # NOTE: no global lock is held across generation. The per-Article
        # guard (`acquire` in the request path, `release` in `finally`)
        # already serializes generations for one Article; holding
        # `_COMMAND_LOCK` here as well would serialize every unrelated
        # command behind a slow provider call (the measured G4.4 defect).
        try:
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
        # V1.2-G4.5: this used to claim "Source unavailable" for EVERY
        # unclassified failure. That is a lie in the common case and it cost a
        # full day of debugging: a quota-exhausted model and an unreadable
        # source produce byte-identical editor screens, so the only visible
        # symptom was a red badge with no cause.
        #
        # The message is now the real exception type plus the provider's own
        # reason when the router supplies one, so the editor sees WHICH class of
        # failure happened. The cause is never invented: if the exception has
        # nothing to say, the type is still more useful than a wrong claim.
        assert not isinstance(exc, article_generation.DraftRefused), (
            "a classified refusal must keep its own code, not be relabelled"
        )
        # Only text the ROUTER produced may reach the editor. An arbitrary
        # exception's `str()` is untrusted, and measured, it did exactly that:
        # "openrouter/gemini-3 failed at /home/test/.config/router.json" was
        # shown to the editor as the reason, naming a provider and this
        # machine's filesystem path for a failure nobody had diagnosed. The
        # router's own `reason` and `trace` are structured and bounded, so the
        # cause is still named - and the exception TYPE is still reported,
        # because a class is a fact and a path is not.
        reason = str(getattr(exc, "reason", "") or "").strip()
        trace = getattr(exc, "trace", None) or []
        blocked = [t for t in trace if t.get("event") in {"SKIPPED", "FAILED"}]
        detail = reason
        if blocked:
            skipped = f"{blocked[0].get('route')}: {blocked[0].get('reason')}"
            detail = f"{detail} ({skipped})" if detail else skipped
        if not detail:
            detail = type(exc).__name__
        # No failure marker is recorded here: the preflight marker contract is
        # that it is written only against a basis this attempt actually used,
        # and an unclassified provider failure has no basis digest.
        raise article_generation.DraftRefused(
            "PROVIDER_UNAVAILABLE", f"Черновата не можа да бъде създадена: {detail}"
        ) from exc
    finally:
        article_generation.release(article_id, token)


def start_article_draft(article_id: str, *, idempotency_key: str = "") -> dict:
    """Begin the one editor-facing Draft action (C2 «Направи чернова»).

    Transport only: the token carries a bounded poll, nothing else. The
    request path does only cheap validation, Article lookup, idempotency /
    in-flight reattachment and operation creation, then returns the token.
    The slow work (canonical snapshot, source opening, bounded enrichment,
    readiness re-check, generation) runs inside the worker before any
    provider work happens. A repeated request with the same Idempotency-Key
    returns the still-valid operation instead of generating twice, and a
    generation already in flight is returned rather than raced.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise EditorApplicationError("Idempotency key is required.")
    key = idempotency_key.strip()
    # Cheap synchronous preflight: the ONE canonical readiness decision over
    # the store-only snapshot. This is what makes the request authoritative
    # WITHOUT making it slow - no page is opened, no enrichment runs and no
    # model is called, and no global lock is held across any of it. The slow
    # half (opening the Story's own publication, enrichment, generation) runs in
    # the worker, and the worker re-runs this same decision before generating,
    # so nothing is decided by a stale render and nothing is decided twice.
    _draft_preflight(article_id)
    in_flight = _running_draft(article_id)
    if in_flight is not None:
        return in_flight
    scope = article_generation.scope_for(article_id)
    # An explicit key pins the operation to that request alone. Binding it to
    # mutable Article state would hand a repeated request a *new* token and
    # generate the same Draft twice.
    token = story_operations.token_for(scope, "", 0, key)
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
        operation_token, view = story_operations.start(scope, "", work, key=key)
    except story_operations.BusyError as exc:
        article_generation.release(article_id, token)
        raise EditorInvalidTransition("Операциите са заети; опитайте след малко.") from exc
    return {"operationToken": operation_token, "status": view["status"]}


# --------------------------------------------------------------------------
# V1.2-G4.3 §E — `Пренапиши` (rewrite this Draft from the editor's comment)
# --------------------------------------------------------------------------


def _rewrite_published(article_id: str, before: dict) -> bool:
    """Whether the rewrite actually replaced the text.

    The store is the authority: if the content version moved past the one this
    attempt started from, the publish happened, whatever raised afterwards.
    """
    try:
        current = int(editor_article_store.get_article_content(article_id)["content_version"])
    except (editor_article_store.ArticleStoreError, OSError, ValueError, KeyError, TypeError):
        return False
    return current > int(before.get("content_version", 0))


def _running_rewrite(article_id: str) -> dict | None:
    """A rewrite for this Article already in flight, as a still-valid operation."""
    token = article_rewrite.active_token(article_id)
    if not token:
        return None
    row = story_operations.get(token)
    if row is None or row["status"] not in {"pending", "running"}:
        return None
    return {"operationToken": token, "status": row["status"]}


def _raise_rewrite_refusal(exc: article_rewrite.RewriteRefused) -> None:
    """Map a stable rewrite refusal onto the editor error contract."""
    if exc.code == article_rewrite.OP_INVALID_TRANSITION:
        raise EditorInvalidTransition(exc.message) from exc
    if exc.code == "ARTICLE_VERSION_CONFLICT":
        raise EditorVersionConflict(exc.message) from exc
    if exc.code in {"NOT_IN_DRAFT", "EMPTY_COMMENT"}:
        raise EditorInvalidTransition(exc.message) from exc
    raise EditorApplicationError(exc.message) from exc


def _record_failed_rewrite_feedback(article_id: str, comment: str) -> None:
    """Record a rewrite request that did not produce a new text. Never raises.

    §E4: no new content version exists, and the record says so honestly rather
    than implying a rewrite that never happened. Losing a learning record must
    never turn a reported failure into a different, more confusing failure.
    """
    text = " ".join(str(comment or "").split())
    if not text:
        return
    try:
        article = _article(article_id)
        content = editor_article_store.get_article_content(article_id)
        rewrite_feedback.record(
            article_id=article_id,
            editor_comment=text,
            focus=str(article.get("editorial_focus") or ""),
            voice=str(article.get("editorial_voice") or ""),
            draft_version_before=int(content["content_version"]),
            draft_version_after=int(content["content_version"]),
            generated_by_model=False,
            root=_editorial_root(),
        )
    except (editor_article_store.ArticleStoreError, OSError, ValueError, KeyError, TypeError):
        pass


def _run_rewrite(article_id: str, comment: str, token: str) -> dict:
    """The one synchronous rewrite execution.

    **§E4 - failure preserves everything.** Every refusal path leaves the current
    body exactly as the editor last confirmed it, and the editor's comment is
    still in the page because it is never sent anywhere until the work succeeds.
    The feedback record is still written on failure, because a request the editor
    made and the product could not satisfy is real editorial signal (§F).
    """
    try:
        article = _active_article(article_id)
        content = editor_article_store.get_article_content(article_id)
        # §C: a rewrite also always has a Focus. An Article whose owner typed
        # the body by hand may never have had one, and rewriting it with an
        # empty editorial focus would produce a text with no editorial
        # instruction at all.
        _ensure_default_focus(article_id)
        article = _active_article(article_id)
        # §E2 - the factual basis is read ONCE, from the same canonical stores
        # the first Draft read, and `enrich=False` keeps the automatic gathering
        # out of a rewrite entirely. A rewrite must not silently introduce
        # unreviewed web material into text the editor has already judged.
        snapshot = _draft_snapshot(article_id, enrich=False)
        article_rewrite.rewrite(
            article=article,
            content=content,
            comment=comment,
            snapshot=snapshot,
            root=_editorial_root(),
        )
        return _article_dto_by_id(article_id)
    except article_rewrite.RewriteRefused as exc:
        _record_failed_rewrite_feedback(article_id, comment)
        _raise_rewrite_refusal(exc)
    except editor_article_store.ArticleVersionConflict as exc:
        raise article_rewrite.RewriteRefused(
            "ARTICLE_VERSION_CONFLICT",
            "Статията е променена, преди пренаписването да завърши.",
        ) from exc
    except Exception as exc:
        # V1.2-G4.3: the publish may have SUCCEEDED and something after it (the
        # projection read) failed. Reporting that as a failed rewrite tells the
        # editor their text was lost when it was in fact replaced - and a retry
        # then rewrites it again, so the same comment is recorded twice with
        # contradictory outcomes. The STORE decides, not whether an exception
        # happened to be raised afterwards.
        LOG.exception("rewrite failed after the publish step for %s", article_id)
        if not _rewrite_published(article_id, content):
            _record_failed_rewrite_feedback(article_id, comment)
        raise article_rewrite.RewriteRefused(
            "REWRITE_UNAVAILABLE", "Пренаписването не можа да се извърши."
        ) from exc
    finally:
        article_rewrite.release(article_id, token)


def start_article_rewrite(article_id: str, comment: str, *, idempotency_key: str = "") -> dict:
    """`Пренапиши` — begin one rewrite of THIS Article from the editor's comment.

    Transport only, exactly like `Направи чернова`: the token carries a bounded
    poll and nothing else. The backend is the authority, the preconditions are
    re-checked inside the worker, and a repeated request with the same key
    addresses the same operation instead of rewriting twice.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise EditorApplicationError("Idempotency key is required.")
    key = idempotency_key.strip()
    text = " ".join(str(comment or "").split())
    with _COMMAND_LOCK:
        article = _active_article(article_id)
        content = editor_article_store.get_article_content(article_id)
        try:
            article_rewrite.evaluate(article=article, content=content, comment=text)
        except article_rewrite.RewriteRefused as exc:
            _raise_rewrite_refusal(exc)
    in_flight = _running_rewrite(article_id)
    if in_flight is not None:
        return in_flight
    scope = article_rewrite.scope_for(article_id)
    # A rewrite is bound to the exact text it was asked to rewrite, so a new
    # comment is a new operation even though the Article is the same one.
    signature = hashlib.sha256(
        f"{content['content_version']}\0{text}".encode()
    ).hexdigest()[:24]
    if key:
        signature = ""
    token = story_operations.token_for(scope, signature, 0, key)
    if key:
        accepted = story_operations.get(token)
        if accepted is not None and accepted["status"] in {"pending", "running", "succeeded"}:
            return {"operationToken": token, "status": accepted["status"]}
    try:
        article_rewrite.acquire(article_id, token)
    except article_rewrite.RewriteRefusal as exc:
        existing = _running_rewrite(article_id)
        if existing is not None:
            return existing
        _raise_rewrite_refusal(exc)

    def work():
        return _run_rewrite(article_id, text, token)

    try:
        operation_token, view = story_operations.start(scope, signature, work, key=key)
    except story_operations.BusyError as exc:
        article_rewrite.release(article_id, token)
        raise EditorInvalidTransition("Операциите са заети; опитайте след малко.") from exc
    return {"operationToken": operation_token, "status": view["status"]}


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
        # Every gap, not only the blocking ones: a detected conflict is an
        # editorial obstacle the Draft gate must see (V1.2-G4.1 §C2).
        blocking_gaps=missing["items"],
        source_url=article_readiness._first_source_url(facts),
        sources=missing.get("openedSources") or (),
    )


def _original_publication_is_readable(story_id: str, story: dict, *, resolve: bool = True) -> bool:
    """Whether the Story's own publication can be read right now.

    V1.2-G4.2 §3C/§5: this is the ONLY thing that makes a `NO_DRAFT_MATERIAL`
    verdict final. Research failing, corroboration being absent, an open
    question or a weak angle are all warnings; the absence of readable prose is
    the real blocker.

    Bounded and cheap: the URL is only *resolved* here (no page is fetched). The
    read itself happens once, in the Draft command, and only when it is needed.

    **V1.2-G4.3 §A — `resolve=False` is the STRICTLY OFFLINE half.** Resolving a
    URL from a headline can reach the network (the keyless lookup), which is fine
    inside a Draft command that is about to do real work anyway, and is NOT fine
    inside a READ projection that only has to decide which buttons to draw. The
    projection therefore passes `resolve=False` and answers the purely local
    question: "does this Story already carry a publication URL worth one
    bounded read?". A projection that quietly searched the web on every render
    would be a latency and privacy defect, not a convenience.
    """
    items = _story_items()
    for member in (story or {}).get("members") or []:
        url = str((items.get(member.get("item_id")) or {}).get("url") or "")
        if publication_material.is_readable_publication(url):
            return True
    if not resolve:
        # The offline half: is ANY member URL worth one bounded attempt? This
        # deliberately accepts a redirect wrapper, because the command can
        # resolve it to the real publisher page from the headline.
        return any(
            publication_material.may_resolve_to_publisher(
                str((items.get(member.get("item_id")) or {}).get("url") or "")
            )
            for member in (story or {}).get("members") or []
        )
    title = _story_title(story, items)
    return bool(publication_material.publication_urls(title))


def _create_quick_article(story_id: str, story: dict) -> str | None:
    """Create the one canonical Article, only once evidence is sufficient.

    The working title is the existing canonical Story→Article title; no AI title
    generation is introduced here (§15). The Focus is left unconfirmed and set
    immediately afterwards through the ordinary focus command, so a
    Quick-Draft-created Article is indistinguishable from one the editor started
    by hand.
    """
    title = _story_title(story, _story_items()) or "Работа за статия"
    # NOTE: short canonical create only; the store owns idempotency via the
    # `quick-draft:{story}` key. No global lock: this runs inside the worker.
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
    # NOTE: short canonical Focus write only. No global lock: this runs
    # inside the worker, next to research and generation.
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
    research_problem = ""
    if _research_remedy_needed(story_id, story):
        try:
            research_story(story_id)
        except (
            EditorResearchUnavailable,
            EditorInvalidTransition,
            story_research.StoryResearchError,
            OSError,
            ValueError,
        ) as exc:
            research_problem = str(exc)
        except Exception:  # noqa: BLE001 - a research failure is never fatal (§4)
            # V1.2-G4.2 §4: research is an IMPROVEMENT, not a permission. Any
            # research failure — including an exhausted round cap or a page that
            # yielded no extractable claim — is recorded and carried on to the
            # Draft as a warning. It stops the Draft only if the Story's own
            # publication also cannot be read, which the Draft gate decides.
            research_problem = "Допълнителното проучване не можа да завърши успешно."
            LOG.info(
                "quick draft: research did not complete for %s: %s", story_id, research_problem
            )

    # 3. Re-evaluate the canonical evidence. This is the honest re-check: a
    # completed research round that did not produce usable material stops the
    # command *before* an Article exists, so nothing is left behind to clean up.
    articles, contents = _story_articles(story_id)
    verdict = _quick_evidence_verdict(story_id, articles)
    if not verdict.eligible and not _original_publication_is_readable(story_id, story):
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
    try:
        quick_draft.acquire(story_id, token)
    except quick_draft.GuardBusy as busy:
        # Two fresh keys raced past the check above. The first operation still
        # owns the guard and is still running, so this request reattaches to it
        # instead of overwriting the guard and orphaning the first one.
        #
        # The check below is a time-of-check/time-of-use gap: between reading
        # that row and claiming the guard, the holder can settle and ANOTHER
        # caller can claim it. A bare second `acquire` would then raise
        # `GuardBusy` again, and it is a plain RuntimeError, not an
        # EditorApplicationError - so it would escape the command path and
        # surface as an unhandled 500 on a legitimate second click. So the claim
        # is retried briefly, and whatever still holds the guard at the end is
        # what the caller is told to reattach to.
        for _attempt in range(3):
            row = story_operations.get(busy.token)
            if row is not None and row["status"] in {"pending", "running"}:
                return {"operationToken": busy.token, "status": row["status"]}
            try:
                quick_draft.acquire(story_id, token)
                break
            except quick_draft.GuardBusy as again:
                busy = again
        else:
            holder = quick_draft.active_token(story_id)
            row = story_operations.get(holder) if holder else None
            if row is not None and row["status"] in {"pending", "running"}:
                return {"operationToken": holder, "status": row["status"]}
            raise EditorInvalidTransition(
                "Операциите са заети; опитайте след малко."
            ) from busy

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


def _today_grouping_health() -> dict | None:
    """Story-grouping health for the latest run, or `None` when unknown.

    Today shows a compact warning only when grouping actually degraded. A run
    that predates this field reports `None` ("unknown"), which the frontend
    treats as *no warning*: inventing a warning for historical runs would be a
    claim the data does not support, and a permanent status chip would train the
    editor to ignore the surface entirely.

    Only the aggregate status and counters cross into the editor DTO. Route
    ids, provider names and HTTP categories stay in the operational store.
    """
    # Resolved through `source_health.last_run_path`, not through
    # `newsroom_paths`, so the documented `NEWSROOM_LAST_RUN_PATH` override is
    # honoured and the reading path is identical to the writing path.
    record = source_health.read_last_run(source_health.last_run_path())
    block = grouping_health.read_grouping_health(record)
    if block is None:
        return None
    return {
        "status": block[grouping_health.FIELD_STATUS],
        "lastSuccessfulSemanticClassificationAt": block[grouping_health.FIELD_LAST_SUCCESS],
        "semanticRequired": block[grouping_health.FIELD_REQUIRED],
        "semanticAnswered": block[grouping_health.FIELD_ANSWERED],
        "semanticDegraded": block[grouping_health.FIELD_DEGRADED],
    }


def read_health() -> dict:
    """Per-ROLE routing health, the one thing the product never showed.

    V1.2-G4.5. Careful about what is claimed here. The Today screen already
    carries `groupingHealth` and renders a warning when grouping degrades, so
    the 2026-09-28 outage was not invisible - but nothing on screen said *why*:
    no per-route health existed in the product, and no surface connected that
    warning to the mark which caused it. This fills exactly that gap, and it is
    the same computation `newsroom doctor` prints, so the screen and the
    terminal cannot disagree.

    A pure read: the routing plan the router would actually follow, plus no
    provider call and no spend.
    """
    from editor_assistant.drafting import model_policy as policy_mod
    from editor_assistant.drafting import model_router as router

    policy = policy_mod.load_policy()
    roles = []
    for name in sorted(policy.get("roles") or {}):
        plan = router.plan_routes(name, policy=policy, payload_class="public")
        routes = plan.get("routes") or []
        roles.append(
            {
                "role": name,
                "eligible": len([r for r in routes if r.get("eligible")]),
                "total": len(routes),
                # What actually happens when a role runs out: it does not fail
                # loudly, it does less. Naming it is the useful part.
                "onExhausted": str(plan.get("on_exhausted") or ""),
            }
        )

    unroutable = [r["role"] for r in roles if not r["eligible"]]
    return {
        "ok": not unroutable,
        "roles": roles,
        "unroutableRoles": unroutable,
        # The one command that fixes a wrong mark, so the editor is never left
        # holding a diagnosis with no way to act on it.
        "remedy": "newsroom models validate",
    }


def read_today(scope: str = editor_queries.SCOPE_REGION, *, now=None) -> dict:
    """Today for the working desk.

    `now` is the projection's clock, and Today is a projection *of* a clock: a
    Story collected three days ago is no longer current. Production omits it and
    gets the real time; a test that pins the horizon passes the moment its
    fixture describes, so the assertion does not depend on the wall clock.
    """
    result = editor_queries.read_today(
        stories_path=_paths()["stories"],
        inbox_path=_paths()["inbox"],
        metadata_root=_paths()["metadata_root"],
        # V1.2-G2.1 §A5: a Today row shows the same editorial title the Story
        # it opens shows, from the same rule and the same registry.
        registry_rows=_registry_title_identities(),
        # V1.2-G4.1 §A4: `region` is the default Burgas working desk; `all` is
        # the quiet escape hatch. An unknown value falls back to the default
        # inside `project_today` rather than failing the whole read.
        scope=scope,
        now=now,
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
            # V1.2-G4.5: WHO said this, and take me there. Added HERE as well as in
            # `_story_attention_row`, because a first attempt added it only to the
            # attention projection — and running the real app showed the field
            # arriving as `null` on every row, since the desk is built from these
            # items. The publisher count below says "how many"; these name one
            # publisher and open their page.
            "sourceUrl": row.get("sourceUrl", ""),
            "sourceName": row.get("sourceName", ""),
            # V1.2-G1 §10: the independent-publisher count, surfaced from the one
            # place that already computes it. It lets the editor sort by
            # corroboration without React ever counting a source, and it is
            # explicitly NOT evidence authority — see `_story_attention_row`.
            "publisherCount": row["publisherCount"],
            "availableActions": ["REVIEW", "IGNORE"]
            + (["QUICK_DRAFT"] if quick["available"] else []),
            "quickDraft": {
                "available": quick["available"],
                "label": quick["label"],
                "articleId": quick["articleId"],
                # The reason a row withholds the button, so the projection is
                # inspectable and the frontend never has to re-derive it.
                "reasonCode": quick["reasonCode"],
                # V1.2-G4.6: the row knows a Quick Draft is already running for
                # this Story, so the pending state survives a navigation.
                "inFlight": quick["inFlight"],
                # V1.2-G4.6: a failed attempt has no Article to show, so the
                # outcome travels with the row. Without it the editor is told
                # nothing by the place they acted on.
                "lastAttempt": quick["lastAttempt"],
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
        "groupingHealth": _today_grouping_health(),
        # V1.2-G4.1 §A4: the scope this projection was actually built with, echoed
        # from the projection that decided it rather than re-derived. The editor
        # (and any consumer of the DTO) can therefore see which desk they are
        # reading without guessing from the rows.
        "scope": result["scope"],
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
    # V1.2-G4.7. The four filters look like a partition of the corpus and are
    # not: measured on the live store, «Всички» was 427 while «Следени» was 1,
    # «Нови развития» 2 and «Игнорирани» 3 — 421 stories in no named bucket at
    # all. An editor reading the nav that way clicks a filter and gets an
    # incomprehensible result. Counting all four in this same pass costs nothing;
    # the alternative is four full store reads to learn what the nav implies.
    counts = {"all": 0, "followed": 0, "developments": 0, "ignored": 0}
    for story in stories:
        metadata = metadata_by_id.get(story["story_id"]) or (
            story_editor_metadata.default_story_editor_metadata(story["story_id"])
        )
        dto = _story_summary(story, metadata, items_by_id, articles)
        counts["all"] += 1
        if dto["followed"]:
            counts["followed"] += 1
        if dto["unreviewedDevelopmentCount"]:
            counts["developments"] += 1
        if dto["ignored"]:
            counts["ignored"] += 1
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
    # Only meaningful without a search: typing narrows the list, and a count
    # taken from the unfiltered corpus next to a filtered result is a lie.
    if not query:
        list_stories.last_counts = counts
    return result


def list_story_counts() -> dict:
    """Filter counts for the Stories nav, from the last unfiltered listing.

    Returning them alongside the list is what keeps the nav honest at no extra
    cost; a separate endpoint would read and project the whole store again.
    """
    return dict(getattr(list_stories, "last_counts", None) or
                {"all": 0, "followed": 0, "developments": 0, "ignored": 0})


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


def _suggested_focus(
    story_id: str, story: dict | None = None, title: str = ""
) -> tuple[str, tuple[str, ...]]:
    """§D1/§D2 — the prepared Focus text and its quiet alternatives.

    Both come from `focus_suggestions`, which is deterministic and spends no
    model call (§D4). The Story's own confirmed facts and open gaps shape the
    wording; a Story with no usable subject gets an empty Focus and no
    alternatives, and the canonical readiness decision then reports
    `WORKING_TITLE_REQUIRED` on its own terms.
    """
    if story is None:
        story = _story(story_id)
    subject = title or _story_title(story, _story_items())
    facts, missing = _story_evidence_projection(story_id)
    return (
        focus_suggestions.primary_focus(subject, facts=facts),
        focus_suggestions.alternatives(
            subject, facts=facts, gaps=[item.get("question", "") for item in missing["items"]]
        ),
    )


def start_article(story_id: str, *, idempotency_key: str) -> dict:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise EditorApplicationError("Idempotency key is required.")
    with _COMMAND_LOCK:
        story = _validate_story_action(story_id, "START_ARTICLE")
        items_by_id = _story_items()
        title = _story_title(story, items_by_id) or "Работа за статия"
        # §D1/§D5: the Article enters Preparation with a usable Focus ALREADY in
        # the field. The editor may accept everything by doing nothing and press
        # `Направи чернова`; there is no confirmation step, because a saved
        # non-empty Focus has always been its own confirmation (V1.2-G2.2 §5).
        # The old generic placeholder sentence is gone: it named no Story.
        focus, _ = _suggested_focus(story_id, story, title)
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
        # §D1: the pre-filled Focus is saved through the ONE canonical Focus
        # command, which is also where confirmation is decided (a non-empty saved
        # Focus is its own confirmation — V1.2-G2.2 §5). Going through the command
        # rather than setting a field keeps `Направи чернова` genuinely
        # zero-friction: open the Article, do nothing, press the button. An
        # existing Article returned by the idempotency key is never re-focused.
        if focus and not editor_projections.focus_is_confirmed(record):
            try:
                record = editor_article_store.update_editor_focus(record["article_id"], focus)
            except editor_article_store.ArticleStoreError:
                # The Article exists; the editor can still set the Focus. Readiness
                # then reports FOCUS_NOT_CONFIRMED on its own terms, which is the
                # honest state rather than a failure of this command.
                record = editor_article_store.get_editor_article(record["article_id"])
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


def update_voice(article_id: str, voice: str) -> dict:
    """`Стил` — the editor's optional Voice choice for the next Draft/Rewrite (§D).

    Server-authoritative like every other editor command: the client sends a
    voice id, the store validates it against the canonical frozen list, and the
    Article projection that comes back is the truth the page re-renders from.

    It deliberately does not create an Article, does not rewrite the current
    Draft, and does not withdraw the readiness checkpoint — a style preference is
    not a factual or editorial-verification change.
    """
    _active_article(article_id)
    with _COMMAND_LOCK:
        try:
            editor_article_store.update_editor_voice(article_id, voice)
        except editor_article_store.ArticleStoreError as exc:
            if "unknown article_id" in str(exc):
                raise EditorNotFound("Статията не е намерена.") from exc
            raise EditorApplicationError("Стилът не може да бъде запазен.") from exc
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
                "Добавете редакционен фокус, преди да отбележите черновата като готова."
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
            raise EditorInvalidTransition(
                "Добавете редакционен фокус, преди да финализирате статията."
            )
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
