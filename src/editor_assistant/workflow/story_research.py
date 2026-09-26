"""Bounded Story research execution using existing search/research primitives."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from editor_assistant.sources import html_desc, web_fetch
from editor_assistant.workflow import blocked_domains as blocked_mod
from editor_assistant.workflow import (
    live_store,
    newsroom_run,
    publication_identity,
    research,
    search,
    story_research_store,
)
from editor_assistant.workflow import readiness as readiness_mod


class StoryResearchError(ValueError):
    """Research could not safely update the Story basis."""


def _fact_id(story_id, source_id, text):
    return "fact_" + hashlib.sha256(f"{story_id}\0{source_id}\0{text}".encode()).hexdigest()[:20]


def _gap_id(story_id, question):
    return "gap_" + hashlib.sha256(f"{story_id}\0{question}".encode()).hexdigest()[:20]


_DIMENSION_PATTERNS = {
    "event_schedule": r"\bкога\b|\bграфик\b|\bдата\b|\bчас\b|\bпрограм",
    "admission": r"\bвход(?:ът|а|ът)?\b|\bбилет(?:ът|а)?\b|\bцена(?:та)?\b|\bбезплат",
    "participants": r"\bучастник|\bизпълнител|\bгост",
    "venue": r"\bкъде\b|\bзал\b|\bадрес|\bплощад|\bvenue",
    "amount": r"\bсума\b|\bколко\b|\bфинанс|\bцена(?:та)?\b|\bлево?в?|\bевро",
    "decision_status": r"\bрешение\b|\bрешен\b|\bприет|\bодобрен|\bотхвърлен",
    "authority": r"\bкой\b|\bорган\b|\bотговорник|\bизточник",
    "conflict": r"\bпротивореч|\bразминава|\bкоично",
}
_ANSWER_PATTERNS = {
    "event_schedule": r"\b\d{1,2}[.:]\d{2}\s*ч\b|\b\d{1,2}\s+(?:януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември)\b|\b\d{4}\s*г",
    "admission": r"\bбезплат|\bвход(?:ът)?\s+свободен|\bвходът\s+е\s+свободен|\bбилет(?:ът)?(?:\s+струва)?|\bцена(?:та)?\s+",
    "participants": r"\bучастник|\bизпълнител|\bгост|\bсъстав",
    "venue": r"\bзал\b|\bадрес|\bплощад|\bдома\b|\bцентър",
    "amount": r"\b\d[\d\s.,]*\s*(?:лева|лв\.?|евро|млн|млрд|хил)\b",
    "decision_status": r"\bприет|\bодобрен|\bотхвърлен|\bрешение\b|\bрешен",
    "authority": r"\bорган\b|\bотговорник\b|\bкмет\b|\bкомисия\b|\bминистър\b",
    "conflict": r"\bпротивореч|\bразминава|\bдве версии",
}
_STOPWORDS = {
    "официалния",
    "официален",
    "официалната",
    "информация",
    "има",
    "каква",
    "какво",
    "как",
    "кой",
    "кога",
    "къде",
    "защо",
    "този",
    "тази",
    "тези",
    "също",
}


def bootstrap_research_questions(*, title="", items=(), max_questions=5):
    """Bounded first-round questions for an UNASSESSED Story (V1.1-A §5-§7).

    Derived only from canonical Story context — title, representative/origin
    publication identity, URL, timestamp, members — never from archive
    material and never invented from snippets. Small on purpose: the first
    round only has to establish what verifiably happened, who is involved,
    when/where (if the source provides it), which opened source supports the
    claim, and what remains unresolved.
    """
    questions: list[str] = []
    clean_title = str(title or "").strip()

    def push(question):
        text = str(question or "").strip()
        if text and text not in questions and len(questions) < max(1, int(max_questions)):
            questions.append(text)

    if clean_title:
        short = clean_title[:160]
        push(f"Кое твърдение от „{short}“ се потвърждава от отворен източник?")
        push("Коя организация или лице е пряко замесено според източника?")
    else:
        push("Кое основно твърдение на историята се потвърждава от отворен източник?")
        push("Коя организация или лице е пряко замесено според източника?")
    push("Кога и къде се е случило или ще се случи събитието според източника?")
    push("Кой отворен авторитетен източник подкрепя основното твърдение?")
    push("Коя важна информация остава непотвърдена?")
    if items:
        push("Има ли втори независим отворен източник за същото събитие?")
    return questions


def is_unassessed_basis(basis) -> bool:
    """True when the canonical basis was never assessed (V1.1-A §2-§3)."""
    if not isinstance(basis, dict):
        return True
    return (
        story_research_store.evidence_status_of(basis) == story_research_store.EVIDENCE_UNASSESSED
    )


def _claim_for_questions(sentences, questions):
    dimensions = {
        name
        for name, pattern in _DIMENSION_PATTERNS.items()
        if re.search(pattern, " ".join(questions).lower())
    }
    meaningful = {
        token
        for question in questions
        for token in re.findall(r"[\wа-яА-Я]{4,}", question.lower())
        if token not in _STOPWORDS
    }
    for sentence in sentences:
        value = sentence.strip()[:1000]
        lowered = value.lower()
        if re.search(r"doctype|cookie|nav|menu|login|subscribe|site|сайт", lowered, re.IGNORECASE):
            continue
        if dimensions:
            if any(
                re.search(_ANSWER_PATTERNS[name], lowered, re.IGNORECASE) for name in dimensions
            ):
                return value
        elif (
            len(value) >= 20 and len(meaningful & set(re.findall(r"[\wа-яА-Я]{4,}", lowered))) >= 2
        ):
            return value
    return ""


def execute_story_research(
    story_id,
    *,
    topic,
    readiness_result=None,
    root=None,
    provider=None,
    page_opener=None,
    canonical_story=None,
    existing_publication_keys=(),
    authority_resolver=None,
    now=None,
    max_open=3,
    story_title="",
    story_items=(),
    seed_urls=(),
):
    """Run one bounded Story research round and persist its canonical outcome.

    V1.1-A bootstrap rule: an UNASSESSED Story (no canonical research row)
    does NOT need pre-existing gaps. The first round builds bounded bootstrap
    questions from Story context instead of reusing gap-driven expansion
    planning. Assessed Stories keep the existing gap-driven path unchanged.

    ``seed_urls`` carries representative/origin publication URLs so the
    bootstrap round can attempt the existing safe fetch path directly (V1.1-A
    §8: the Google News redirect itself is never promoted as evidence; only
    the final canonical URL of an opened page may become a source).

    Outcome honesty (V1.1-A §4/§10/§16): infrastructure failure before any
    assessment (no opened usable page AND no persisted result) raises
    ``StoryResearchError`` and writes nothing — the Story stays UNASSESSED.
    A completed round with insufficient usable evidence persists an ASSESSED
    row with >=1 explicit gap — never facts=0 AND gaps=0.
    """
    if not isinstance(canonical_story, dict) or canonical_story.get("story_id") != story_id:
        raise StoryResearchError("canonical Story proof is required")
    current = story_research_store.get_story_research(story_id, root=root)
    bootstrap = is_unassessed_basis(current)
    if bootstrap:
        bootstrap_questions = bootstrap_research_questions(
            title=story_title or topic or "",
            items=story_items,
        )
        plan = {
            "missing_dimensions": [],
            "research_questions": bootstrap_questions,
            "max_rounds_remaining": max(
                0, readiness_mod.MAX_RESEARCH_ROUNDS - int(current.get("research_rounds") or 0)
            ),
        }
        if not plan["research_questions"] or plan["max_rounds_remaining"] <= 0:
            raise StoryResearchError("няма разрешен нов кръг проучване")
    else:
        if readiness_result is None:
            raise StoryResearchError("няма блокираща липсваща информация за проучване")
        plan = readiness_mod.expansion_plan(
            readiness_result, rounds_used=current["research_rounds"]
        )
        if not plan["research_questions"] or plan["max_rounds_remaining"] <= 0:
            raise StoryResearchError("няма разрешен нов кръг проучване")
    stable_seed = "\0".join([story_id, *sorted(plan["research_questions"])])
    audit_path = (
        Path(root or search.SEARCH_RUNS_DIR.parent)
        / "search_runs"
        / (hashlib.sha256(stable_seed.encode()).hexdigest()[:24] + ".jsonl")
    )
    opened_pages = {}

    def capture(url):
        try:
            page = page_opener(url) if page_opener else web_fetch.fetch_page(url)
        except web_fetch.WebFetchError:
            page = {}
        opened_pages[url] = page
        return {
            "final_url": page.get("final_url", url),
            "content_type": page.get("content_type", "text/plain"),
            "bytes": page.get("bytes", len(str(page.get("text") or ""))),
            "text": page.get("text", ""),
        }

    def open_seed_url(url):
        """Open one representative publication through the safe fetch path.

        V1.1-A §8: the Google News redirect itself is never evidence. The
        fetcher follows the redirect; only the final canonical URL may become
        a source. Returns a search-operation-shaped candidate or None.
        """
        raw = str(url or "").strip()
        if not raw:
            return None
        try:
            page = page_opener(raw) if page_opener else web_fetch.fetch_page(raw)
        except (web_fetch.WebFetchError, OSError, ValueError):
            return None
        if not isinstance(page, dict) or not str(page.get("text") or "").strip():
            return None
        opened_pages[raw] = page
        final_url = str(page.get("final_url") or raw)
        host = (urlsplit(final_url).hostname or "").lower()
        if host == "news.google.com" or host.endswith(".news.google.com"):
            # The redirect did not resolve to the original publisher: the RSS
            # redirect itself must never be promoted as factual evidence.
            return None
        return {
            "title": topic,
            "url": raw,
            "snippet": "",
            "snippet_authority": "DISCOVERY_ONLY",
            "opened": {
                "status": "FETCH_OK",
                "final_url": final_url,
                "content_type": page.get("content_type", "text/plain"),
                "bytes": page.get("bytes", len(str(page.get("text") or ""))),
            },
        }

    operation = search.run_search_operation(
        topic=topic,
        constraints=search.make_constraints(description="Story gap research", location="Бургас"),
        missing_dimensions=plan["missing_dimensions"],
        research_questions=plan["research_questions"],
        provider=provider,
        page_opener=capture,
        max_open=max_open,
        audit_path=audit_path,
    )
    opened = [
        c
        for c in operation.get("candidates", [])
        if (c.get("opened") or {}).get("status") == "FETCH_OK"
    ]
    seed_opened = []
    if bootstrap and seed_urls:
        # V1.1-A §8: attempt the representative publication through the
        # existing safe fetch path, bounded like any other opened page. At most
        # one representative URL per publisher host: several member URLs from
        # the same publisher are still one publication, and must not crowd the
        # independent search candidates out of the bounded opening budget.
        seed_hosts: set[str] = set()
        for seed_url in seed_urls:
            if len(seed_opened) >= max(1, int(max_open)):
                break
            seed_host = (urlsplit(str(seed_url)).hostname or "").lower()
            if seed_host and seed_host in seed_hosts:
                continue
            candidate = open_seed_url(seed_url)
            if candidate is None or candidate["url"] in {c.get("url") for c in opened}:
                continue
            if seed_host:
                seed_hosts.add(seed_host)
            seed_opened.append(candidate)
        opened = [*seed_opened, *opened][: max(1, int(max_open))]
    if not opened:
        if bootstrap:
            # V1.1-A §10/§16: search/fetch found nothing usable, but the
            # round itself completed — persist ASSESSED with an explicit gap
            # (never facts=0 AND gaps=0). Only an infrastructure failure
            # (exception) before any assessment keeps the Story UNASSESSED.
            gap_text = "Не е намерен отворен източник, който потвърждава основното твърдение."
            return story_research_store.merge_research(
                story_id,
                facts=[],
                sources=[],
                gaps=[
                    {
                        "id": _gap_id(story_id, gap_text),
                        "question": gap_text,
                        "kind": "unresolved",
                        "blocking": True,
                    }
                ],
                assessed_at=now,
                root=root,
                canonical_story=canonical_story,
                operation_id=(
                    "story-"
                    + hashlib.sha256(
                        (stable_seed + "\0insufficient-evidence").encode()
                    ).hexdigest()[:16]
                ),
                count_round=True,
                replace_gaps=True,
            )
        raise StoryResearchError(operation.get("reason") or "няма отворени източници")
    research_id = (
        "story-"
        + hashlib.sha256(
            (stable_seed + "\0" + "\0".join(sorted(c["url"] for c in opened))).encode()
        ).hexdigest()[:16]
    )
    bundle = research.make_bundle(
        research_id=research_id,
        query=topic,
        editor_request="Story gap research",
        research_type="story_gap",
        started_at=now,
    )
    sources, facts, source_records, seen_keys = [], [], [], set()
    policy = (authority_resolver or newsroom_run.authority_by_domain)()
    for index, candidate in enumerate(opened[:max_open]):
        page = opened_pages.get(candidate["url"], {})
        final_url = str((candidate.get("opened") or {}).get("final_url") or candidate["url"])
        normalized_url = publication_identity.normalize_publication_url(final_url)
        host = (urlsplit(normalized_url).hostname or "").lower()
        if (
            not normalized_url
            or host == "chernomorie-bg.com"
            or host.endswith(".chernomorie-bg.com")
            or blocked_mod.is_blocked(normalized_url)
        ):
            continue
        publication_key = publication_identity.publication_key_for(normalized_url, host)
        if publication_key in seen_keys or publication_key in set(existing_publication_keys):
            continue
        seen_keys.add(publication_key)
        text = (
            html_desc.normalize_description(str(page.get("text") or ""), base_url=normalized_url)[0]
            or ""
        )
        claim = _claim_for_questions(re.split(r"(?<=[.!?])\s+", text), plan["research_questions"])
        if not claim:
            continue
        row = policy.get(host) if isinstance(policy, dict) else None
        factual = bool(row and row.get("factual_authority"))
        source_type = (
            "official_document"
            if factual and row.get("kind") in {"official", "official_document"}
            else "media"
        )
        authority = "PRIMARY" if factual else "CORROBORATING"
        source_id = "src_" + hashlib.sha256(normalized_url.encode()).hexdigest()[:16]
        source = {
            "id": source_id,
            "name": row.get("name") if isinstance(row, dict) and row.get("name") else host,
            "url": normalized_url,
        }
        sources.append(source)
        source_records.append(
            {"source": source, "claim": claim, "domain": host, "authority": authority}
        )
        research.add_candidate(
            bundle,
            candidate_id=f"C{index + 1}",
            title=candidate.get("title") or normalized_url,
            url=normalized_url,
            source_name=source["name"],
            source_type=source_type,
        )
        if bundle["selected_candidate"] is None:
            research.select_candidate(bundle, f"C{index + 1}")
        research.open_source(
            bundle,
            source_id=source_id,
            url=normalized_url,
            source_name=source["name"],
            source_type=source_type,
            authority=authority,
            relevant_claims=[claim],
        )
        facts.append(
            {
                "id": _fact_id(story_id, source_id, claim),
                "text": claim,
                "source_refs": [{"source_id": source_id, "locator": "claim:0"}],
                "scope": "current_event",
            }
        )
    grouped = {}
    for item in source_records:
        grouped.setdefault(" ".join(item["claim"].lower().split()), []).append(item)
    allowed = {
        item["source"]["id"]
        for items in grouped.values()
        for item in items
        if item["authority"] == "PRIMARY" or len({x["domain"] for x in items}) >= 2
    }
    facts = [fact for fact in facts if fact["source_refs"][0]["source_id"] in allowed]
    if not facts:
        # V1.1-A §10/§16: a completed first round with no usable opened
        # source is ASSESSED with an explicit gap — never an empty assessed
        # basis and never silent UNASSESSED. Later gap-driven rounds keep the
        # historical refusal (nothing to merge, nothing to persist).
        gap_text = "Не е намерен отворен източник, който потвърждава основното твърдение."
        if bootstrap:
            return story_research_store.merge_research(
                story_id,
                facts=[],
                sources=[],
                gaps=[
                    {
                        "id": _gap_id(story_id, gap_text),
                        "question": gap_text,
                        "kind": "unresolved",
                        "blocking": True,
                    }
                ],
                assessed_at=now,
                root=root,
                canonical_story=canonical_story,
                operation_id=(
                    "story-"
                    + hashlib.sha256(
                        (stable_seed + "\0insufficient-evidence").encode()
                    ).hexdigest()[:16]
                ),
                count_round=True,
                replace_gaps=True,
            )
        raise StoryResearchError("non-authoritative claims require two independent opened sources")
    allowed_ids = {fact["source_refs"][0]["source_id"] for fact in facts}
    sources = [source for source in sources if source["id"] in allowed_ids]
    research.set_duplicate_check(
        bundle,
        "NO_DUPLICATE",
        checked_urls=[item["url"] for item in bundle["candidates"]],
        note="exact Story publication identity check",
    )
    research.complete_bundle(bundle, notes="Story research completed")
    packet = research.provenanced_packet(
        bundle,
        evidence_id=research_id,
        observed_at=(now or operation["started_at"])[:10],
        headline=topic,
        facts=facts,
        unknowns=plan["research_questions"],
    )
    research.validate_provenance(packet, bundle)
    research.validate_council_claims(packet, bundle)
    projected_facts = [
        {
            "id": _fact_id(story_id, ref["source_id"], fact["text"]),
            "text": fact["text"],
            "sourceId": ref["source_id"],
            "locator": ref["locator"],
            "scope": "current",
        }
        for fact in packet["facts"]
        for ref in fact["source_refs"]
    ]
    target_dimensions = {
        name
        for name, pattern in _DIMENSION_PATTERNS.items()
        if re.search(pattern, " ".join(plan["research_questions"]).lower())
    }
    merged_rows = [*current.get("facts", []), *projected_facts]
    if target_dimensions & {
        "event_schedule",
        "authority",
        "decision_status",
        "admission",
        "venue",
        "participants",
        "amount",
    }:
        assessment_rows = [row for row in merged_rows if row.get("scope", "current") == "current"]
    else:
        assessment_rows = merged_rows
    merged_packet = {
        **packet,
        "facts": [
            {
                "id": row["id"],
                "text": row["text"],
                "scope": row.get("scope", "current"),
                "source_refs": [{"source_id": row["sourceId"], "locator": row["locator"]}],
            }
            for row in assessment_rows
        ],
    }
    try:
        assessment = readiness_mod.assess_sufficiency(merged_packet, mode=readiness_mod.MODES[0])
    except (readiness_mod.ReadinessError, ValueError) as exc:
        raise StoryResearchError("готовността на Story не можа да се оцени") from exc
    current_gaps = list(current.get("gaps") or [])
    conflicts = [gap for gap in current_gaps if gap.get("kind") == "conflict"]
    if assessment.get("status") == readiness_mod.SUFFICIENT:
        gaps = conflicts
    else:
        gaps = conflicts + [
            {
                "id": _gap_id(story_id, q),
                "question": q,
                "kind": "unresolved",
                "blocking": assessment.get("status") == readiness_mod.RESEARCH_MORE,
            }
            for q in assessment.get("research_questions", [])
            if str(q).strip()
        ]
    if not projected_facts and not gaps:
        # Defensive: the store refuses facts=0 AND gaps=0 for any completed
        # assessment. If sufficiency produced no question (unlikely), persist
        # one explicit gap instead of a false clean state.
        fallback = "Не е намерен отворен източник, който потвърждава основното твърдение."
        gaps = [
            {
                "id": _gap_id(story_id, fallback),
                "question": fallback,
                "kind": "unresolved",
                "blocking": True,
            }
        ]
    bundle_path = (
        Path(root or search.SEARCH_RUNS_DIR.parent) / "search_runs" / f"{research_id}.jsonl"
    )
    try:
        research.validate_bundle(bundle)
        live_store.atomic_write(
            bundle_path, json.dumps(bundle, ensure_ascii=False, sort_keys=True) + "\n"
        )
        return story_research_store.merge_research(
            story_id,
            facts=projected_facts,
            sources=sources,
            gaps=gaps,
            assessed_at=now,
            root=root,
            canonical_story=canonical_story,
            operation_id=research_id,
            count_round=True,
            replace_gaps=True,
        )
    except Exception:
        bundle_path.unlink(missing_ok=True)
        raise
