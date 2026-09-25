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
    editor_article_store,
    editor_projections,
    editor_queries,
    inbox_store,
    live_store,
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
        except (OSError, ValueError, research_mod.ResearchError):
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


def _article_actions(article: dict, content: dict) -> tuple[list[str], dict | None]:
    if article.get("finalized_at"):
        return [], None
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
    actions, next_action = _article_actions(article, content)
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
        "readiness": {
            "isCurrent": editor_projections.readiness_is_current(article, content, None),
            "readyVersion": article.get("ready_version"),
            "readyAt": article.get("ready_at"),
        },
        "warnings": [],
        "availableActions": actions,
        "nextAction": next_action,
        "createdAt": article["created_at"],
        "updatedAt": article["updated_at"],
        "finalizedAt": article.get("finalized_at"),
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
        return {
            "operationToken": token,
            "status": row["status"],
            "error": {
                "code": "SOURCE_UNAVAILABLE",
                "message": "Проучването не можа да завърши.",
                "retryable": True,
            },
        }
    return {"operationToken": token, "status": row["status"]}


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
        if dto["state"] is None or dto["nextAction"] is None:
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
        "problems": [],
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
