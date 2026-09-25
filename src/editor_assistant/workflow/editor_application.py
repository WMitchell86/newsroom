"""Phase B1 editor application queries and commands.

This module is the stable application boundary behind ``/api/v1``. It composes
Phase A stores and projections, returns explicit editor DTOs, and contains no
HTTP parsing, response formatting, provider work, or orchestration.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from editor_assistant.drafting.evidence import EvidenceError, validate_packet
from editor_assistant.workflow import (
    article_generation,
    editor_article_store,
    editor_projections,
    editor_queries,
    inbox_store,
    live_store,
    newsroom_refresh,
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


class EditorBlockingGap(EditorApplicationError):
    """The canonical Story basis still has a blocking gap. No generation."""

    code = "BLOCKING_GAP"
    status = 409


class EditorSafetyBlocked(EditorApplicationError):
    """A safety guard stopped the command before any provider work."""

    code = "SAFETY_BLOCKED"
    status = 409


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


def _story_reference(article: dict, items_by_id: dict | None = None) -> dict:
    try:
        story = _story(article["story_id"])
    except EditorNotFound:
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


def _story_evidence_projection(
    story_id: str, articles: list[dict] | None = None
) -> tuple[list[dict], dict]:
    """Compose verified legacy Article lineage with the canonical Story basis."""
    basis = story_research_store.get_story_research(story_id)
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
    if articles is not None:
        legacy_facts, legacy_gaps, assessed = _legacy_story_evidence(story_id, articles)
        facts.extend(legacy_facts)
        gaps.extend(legacy_gaps)
        basis = {
            **basis,
            "assessed_at": max(basis["assessed_at"], assessed) or basis["assessed_at"],
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
    return unique_facts, {"items": unique_gaps, "assessedAt": basis["assessed_at"]}


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


def _article_actions(
    article: dict, content: dict, blocking_gaps: list[dict] | None = None
) -> tuple[list[str], dict | None]:
    if article.get("finalized_at"):
        return [], None
    state = editor_projections.derive_article_state(article, content, None)
    if state == "preparation":
        blocking_gaps = blocking_gaps or []
        if not editor_projections.focus_is_confirmed(article):
            return ["SELECT_FOCUS"], _next_action("SELECT_FOCUS", "FOCUS_REQUIRED", "Избери фокус")
        # Backend-authorized manual continuation uses the same editor and the
        # same atomic content save. There is no separate manual Draft mode.
        actions = ["CHANGE_FOCUS", "EDIT"]
        if blocking_gaps:
            actions.append("RESEARCH_MORE")
            return actions, _next_action("RESEARCH_MORE", "BLOCKING_GAP", "Проучи още")
        actions.append("MAKE_DRAFT")
        return actions, _next_action("MAKE_DRAFT", "DRAFT_ELIGIBLE", "Направи чернова")
    actions = []
    if editor_projections.focus_is_confirmed(article):
        actions.append("CHANGE_FOCUS")
        next_action = _next_action("EDIT", "CONTENT_EDIT", "Редактирай")
    else:
        actions.append("SELECT_FOCUS")
        next_action = _next_action("SELECT_FOCUS", "FOCUS_REQUIRED", "Избери фокус")
    actions.append("EDIT")
    return actions, next_action


def _article_dto(article: dict, content: dict, story_reference: dict) -> dict:
    state = editor_projections.derive_article_state(article, content, None)
    facts, missing = _story_evidence_projection(article["story_id"])
    blocking_gaps = [item for item in missing["items"] if item.get("blocking")]
    non_blocking_gaps = [item for item in missing["items"] if not item.get("blocking")]
    focus_confirmed = editor_projections.focus_is_confirmed(article)
    actions, next_action = _article_actions(article, content, blocking_gaps)
    preparation = None
    if state == "preparation":
        preparation = {
            "focusConfirmed": focus_confirmed,
            "blockingGaps": blocking_gaps,
            "nonBlockingGaps": non_blocking_gaps,
            "draftEligible": focus_confirmed and not blocking_gaps,
            "availableActions": actions,
        }
    return {
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
            "isCurrent": editor_projections.readiness_is_current(article, content, None),
            "readyVersion": article.get("ready_version"),
            "readyAt": article.get("ready_at"),
        },
        "warnings": (
            article_generation.warnings_for(article, content, root=_editorial_root())
            if article.get("generated_content_version") == content["content_version"]
            else []
        ),
        "availableActions": actions,
        "nextAction": next_action,
        "createdAt": article["created_at"],
        "updatedAt": article["updated_at"],
        "finalizedAt": article.get("finalized_at"),
        "factsAndSources": facts,
        "missingInformation": missing,
    }


def _article_dto_by_id(article_id: str) -> dict:
    article = _article(article_id)
    content = editor_article_store.get_article_content(article_id)
    return _article_dto(article, content, _story_reference(article))


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
    _, legacy_gaps, _ = _legacy_story_evidence(story["story_id"], articles)
    meaningful_gaps = list(basis["gaps"]) + legacy_gaps
    has_research_gap = any(item.get("question") for item in meaningful_gaps)
    has_blocking_gap = any(item.get("blocking") for item in meaningful_gaps)
    if (
        has_research_gap
        and story.get("status") != "IGNORED"
        and basis["research_rounds"] < readiness_mod.MAX_RESEARCH_ROUNDS
        and bool(search_mod.provider_chain(capability=search_mod.CAP_WEB)[0])
    ):
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
    if not questions:
        raise EditorInvalidTransition("Няма блокираща липсваща информация за проучване.")
    items = _story_items()
    title = _story_title(story, items)
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
    _, legacy_gaps, _ = _legacy_story_evidence(
        story_id, editor_article_store.read_editor_articles()
    )
    gaps = list(basis["gaps"]) + legacy_gaps
    signature = "\0".join(sorted(f"{x['id']}={x['question']}" for x in gaps))
    generation = basis["research_rounds"]
    operation_token = story_operations.token_for(story_id, signature, generation, idempotency_key)
    if idempotency_key:
        accepted = story_operations.get(operation_token)
        if accepted is not None and accepted["status"] in {"pending", "running", "succeeded"}:
            return {"operationToken": operation_token, "status": accepted["status"]}
    if (
        story.get("status") == "IGNORED"
        or not gaps
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
    """
    article = _active_article(article_id)
    content = editor_article_store.get_article_content(article_id)
    story = _story(article["story_id"])
    facts, missing = _story_evidence_projection(article["story_id"])
    items_by_id = _story_items()
    source_url = next(
        (
            str((fact.get("source") or {}).get("url") or "")
            for fact in facts
            if str((fact.get("source") or {}).get("url") or "")
        ),
        "",
    )
    return {
        "article": article,
        "content": content,
        "story": story,
        "content_version": int(content["content_version"]),
        "facts": facts,
        "gaps": list(missing["items"]),
        "blocking_gaps": [item for item in missing["items"] if item.get("blocking")],
        "assessed_at": missing.get("assessedAt"),
        "headline": _story_title(story, items_by_id) or article["working_title"],
        "summary": str(
            (items_by_id.get(story.get("representative_item_id")) or {}).get("summary") or ""
        ),
        "source_url": source_url,
    }


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
    """Map a stable refusal onto the editor error contract, never its raw text."""
    if exc.code == "BLOCKING_GAP":
        raise EditorBlockingGap("Има непопълнена информация, която пречи да продължите.") from exc
    if exc.code == "SAFETY_BLOCKED":
        raise EditorSafetyBlocked("Проверката за безопасност спря операцията.") from exc
    if exc.code == "ARTICLE_VERSION_CONFLICT":
        raise EditorVersionConflict(
            "Статията е променена, преди черновата да се създаде. Няма загубени локални промени."
        ) from exc
    if exc.code == "INVALID_TRANSITION":
        raise EditorInvalidTransition(str(exc)) from exc
    raise EditorApplicationError("Черновата не може да бъде създадена от този материал.") from exc


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
        try:
            article_generation.evaluate(snapshot)
        except article_generation.DraftRefused as exc:
            _raise_draft_refusal(exc)
        dto = _article_dto(article, snapshot["content"], _story_reference(article))
        if "MAKE_DRAFT" not in dto["availableActions"]:
            # The same derivation that produced `availableActions` is the policy
            # authority; the client never decides that it may draft.
            raise EditorInvalidTransition(
                "Черновата не е налична в текущото състояние на статията."
            )
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
        try:
            # Stale revalidation: the Article may have been edited, refocused or
            # re-gapped while this operation was queued. That is a stable
            # refusal, never a silent overwrite of the editor's text.
            current = _draft_snapshot(article_id)
            try:
                article_generation.evaluate(current)
            except article_generation.DraftRefused as exc:
                # Re-raise as the classified refusal so the bounded operation
                # keeps the stable code instead of a generic failure.
                raise article_generation.DraftRefused(exc.code, exc.message) from exc
            with _COMMAND_LOCK:
                article_generation.generate(current, root=_editorial_root())
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

    try:
        operation_token, view = story_operations.start(scope, signature, work, key=key)
    except story_operations.BusyError as exc:
        article_generation.release(article_id, token)
        raise EditorInvalidTransition("Операциите са заети; опитайте след малко.") from exc
    return {"operationToken": operation_token, "status": view["status"]}


def read_story(story_id: str) -> dict:
    return _story_detail(story_id)


def read_article(article_id: str) -> dict:
    return _article_dto_by_id(article_id)


def read_today() -> dict:
    result = editor_queries.read_today(
        stories_path=_paths()["stories"],
        inbox_path=_paths()["inbox"],
        metadata_root=_paths()["metadata_root"],
    )
    new_developments = []
    new_stories = []
    for entry in result["stories"]:
        detail = _story_detail(entry["story"]["id"])
        item = {
            "objectType": "story",
            "objectId": entry["story"]["id"],
            "title": detail["title"],
            "reason": entry["attention"],
            "summary": detail["summary"],
            "timestamp": detail["latestChangeAt"],
            "nextAction": "REVIEW",
            "delta": {"unreviewedDevelopmentCount": detail["unreviewedDevelopmentCount"]},
        }
        if entry["attention"] == "NEW_STORY":
            new_stories.append(item)
        else:
            item["reason"] = "UNREVIEWED_DEVELOPMENT"
            new_developments.append(item)
    articles = []
    for article in editor_article_store.read_editor_articles():
        dto = _article_dto_by_id(article["article_id"])
        content = editor_article_store.get_article_content(article["article_id"])
        concrete_next_action = (dto.get("nextAction") or {}).get("action")
        if not editor_projections.article_today_eligible(
            article,
            content,
            None,
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
        dto = _article_dto(article, content, story_reference)
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


def list_archive(query: str = "") -> list[dict]:
    result = []
    for article in editor_article_store.read_editor_articles():
        if not article.get("finalized_at"):
            continue
        dto = _article_dto_by_id(article["article_id"])
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
