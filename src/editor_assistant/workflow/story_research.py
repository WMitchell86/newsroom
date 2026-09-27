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
    claim_equivalence,
    claim_quality,
    live_store,
    newsroom_run,
    publication_identity,
    research,
    search,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import readiness as readiness_mod


class StoryResearchError(ValueError):
    """Research could not safely update the Story basis.

    V1.2-G2.4 §R4/§R5: the owner saw this reach the editor as one generic
    sentence ("Проучването не можа да завърши.") for a Story whose research had
    actually *completed* and simply found no second publisher. Every raise
    therefore carries an explicit `reason` from the closed set below, and the
    application layer maps that reason to a precise editor-facing outcome. An
    unclassified raise is the only thing allowed to remain a technical failure,
    and even that has its own honest sentence.
    """

    def __init__(self, message: str, *, reason: str = ""):
        super().__init__(message)
        self.reason = reason or ""


# --- §R4: the closed set of real research outcomes -------------------------
#
# Each of these is a *true* statement about what happened, and each tells the
# editor whether to wait, retry, or accept a gap. "Research failed" is not in
# this set, because it is never a useful thing to tell an editor.

#: The bounded per-Story round budget for this basis is spent.
ROUNDS_EXHAUSTED = "ROUNDS_EXHAUSTED"
#: No search provider is available at all, so nothing was searched for.
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
#: The Story is not in a researchable state (no gaps and never assessed).
NOT_RESEARCHABLE = "NOT_RESEARCHABLE"
#: Nothing was found to open, and therefore nothing was assessed.
NOTHING_OPENED = "NOTHING_OPENED"
#: Sources opened and claims were extracted, but none could be corroborated.
#: This is an EVIDENCE outcome, not a failure — and it is the branch the
#: owner's real case actually took.
INSUFFICIENT_CORROBORATION = "INSUFFICIENT_CORROBORATION"
#: A genuine technical fault: transport, an unexpected exception, a store
#: invariant. The only branch allowed to be reported as "try again".
TECHNICAL_FAILURE = "TECHNICAL_FAILURE"

RESEARCH_REASONS = frozenset(
    {
        ROUNDS_EXHAUSTED,
        PROVIDER_UNAVAILABLE,
        NOT_RESEARCHABLE,
        NOTHING_OPENED,
        INSUFFICIENT_CORROBORATION,
        TECHNICAL_FAILURE,
    }
)


#: V1.2-G2.2 §12 — the editor-visible reason a first round produced no usable
#: fact. These were three different outcomes behind ONE sentence, and the
#: sentence that was persisted claimed no source had been opened. G2.1 measured
#: 23 of 23 real failures carrying that false text while the page *had* opened.
#:
#: Only the wording changes here. Which cases count as evidence, what a PRIMARY
#: source is, and the corroboration gate are exactly as V1.1-A left them; this
#: slice only stops the product from misreporting which branch it took.
GAP_NOTHING_OPENED = "Не успяхме да отворим подходящ източник."
GAP_NOTHING_PROMOTED = (
    "Намерени са източници, но информацията още не е достатъчно потвърдена."
)
GAP_NEEDS_CORROBORATION = "Нужен е още независим източник за потвърждение."

#: §9 — a small bounded candidate set per opened page, never the whole page.
CLAIMS_PER_PAGE = 4
#: §7/§30 — semantic comparison is a model call, so the number of candidate
#: PAIRS is bounded per round and counted. Deterministic verdicts (equality and
#: hard contradiction) are free and are always checked first.
MAX_SEMANTIC_COMPARISONS = 12


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


#: §18 - a page that is still a WRAPPER is not a publisher, and never evidence.
#:
#: G2.3's replay of the frozen 24-Story sample opened `news.google.com` 23 times
#: and `facebook.com` 16 times: search results whose redirect did not resolve to
#: the publisher. Counting those as publishers would let one aggregator invent
#: the "independent" second source that corroboration requires, so they are
#: refused here. Authority and independence always derive from the publisher
#: actually reached (§18).
_NON_PUBLISHER_HOSTS = frozenset(
    {
        "news.google.com",
        "google.com",
        "facebook.com",
        "fb.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "tiktok.com",
        "youtube.com",
        "youtu.be",
        "linkedin.com",
        "t.me",
        "telegram.me",
        "reddit.com",
    }
)

#: Subdomain labels that never identify a publisher of their own. Stripping
#: them is the conservative part of §8: it collapses the overwhelmingly common
#: `example.com` / `www.example.com` pair, which is one publisher reached twice,
#: without guessing at eTLD+1 boundaries and risking the opposite error of
#: merging two genuinely different outlets that share a suffix.
#: V1.2-G2.4 §F: the definition now lives in `story_store.publisher_identity`,
#: so the publisher COUNT the editor sees and the independence rule used here
#: are provably the same rule rather than two similar ones.
_PUBLISHER_NEUTRAL_LABELS = story_store.PUBLISHER_NEUTRAL_LABELS


def _publisher_identity(host: str) -> str:
    """The host used to decide whether two opened pages are one publisher."""
    return story_store.publisher_identity(host)


def _needs_official_record(claim: str) -> bool:
    """True for a claim the existing council-decision guard reserves (§15).

    The pattern is the SAME one `research.validate_council_claims` enforces, so
    the two can never drift: a decision claim that this module declines to
    promote from media is exactly the decision claim the guard would refuse.
    """
    return bool(research.decision_claim_pattern().search(str(claim or "")))


def _conflict_id(marker) -> str:
    return _gap_id("conflict", " | ".join(marker))


def _comparable(left: dict, right: dict) -> bool:
    """§7 — only compare claims that were extracted for the same reason.

    Two candidates are comparable when their dimension sets intersect, or when
    one of them is unlabelled. This is what keeps the number of comparisons
    bounded and prevents an arbitrary sentence being matched against an
    unrelated one.
    """
    left_dimensions = set(left.get("dimensions") or ())
    right_dimensions = set(right.get("dimensions") or ())
    if not left_dimensions or not right_dimensions:
        return True
    return bool(left_dimensions & right_dimensions)


def _promote_claims(records):
    """§1/§2/§7/§8/§16/§21 — which sources may support a fact.

    A claim is promoted when EITHER its own opened source is PRIMARY (§15 keeps
    the existing claim-appropriate authority semantics: a source is authoritative
    for what it publishes, not for everything on the page), OR an **independent
    domain** confirms the same factual proposition (§8: two URLs from one
    publisher are one source, never two).

    Returns the set of source ids whose claims are supported, the conflicts that
    must not become corroboration (§21), and how many pairs were compared, so
    the cost of the stage is measurable (§30).
    """
    supported: set[str] = set()
    conflicts: list[dict] = []
    comparisons = 0
    seen_conflicts: set[tuple[str, str]] = set()

    for position, record in enumerate(records):
        if record["authority"] == "PRIMARY":
            # §1-A: an authoritative source supports the claim on its own.
            supported.add(record["source"]["id"])
            continue
        if _needs_official_record(record["claim"]):
            # §15 / the pre-existing M2S council-decision guard: "the council
            # approved X" is a decision claim. It may not be corroborated by two
            # media articles, however well they agree - only an official
            # protocol/decision source can carry it. Leaving it unsupported here
            # is what keeps `research.validate_council_claims` satisfied, and it
            # makes the round finish with a truthful gap instead of aborting on a
            # ResearchError after pages had already been opened.
            continue
        for other in records[position + 1 :]:
            if not _comparable(record, other):
                continue
            # §8: independence is per PUBLISHER, never per URL or per host. A
            # syndication mirror and a subdomain of the same outlet are one.
            if other.get("publisher") == record.get("publisher"):
                continue
            if _needs_official_record(other["claim"]):
                continue
            if other["claim"] == record["claim"] or other["authority"] == "PRIMARY":
                # Exact agreement, or a PRIMARY confirmation, settles it without
                # spending a model call.
                supported.add(record["source"]["id"])
                supported.add(other["source"]["id"])
                continue
            if comparisons >= MAX_SEMANTIC_COMPARISONS:
                break
            comparisons += 1
            verdict = claim_equivalence.compare_claims(record["claim"], other["claim"])
            if verdict == claim_equivalence.SAME_FACT:
                supported.add(record["source"]["id"])
                supported.add(other["source"]["id"])
            elif verdict == claim_equivalence.CONFLICT:
                # §21: a conflict is NOT corroboration. It becomes a visible
                # question instead, so the editor sees the disagreement.
                marker = tuple(sorted((record["claim"], other["claim"])))
                if marker in seen_conflicts:
                    continue
                seen_conflicts.add(marker)
                conflicts.append(
                    {
                        "id": _conflict_id(marker),
                        "question": (
                            "Източниците се разминават: "
                            f"\u201c{record['claim']}\u201d срещу "
                            f"\u201c{other['claim']}\u201d. Кое е вярно?"
                        ),
                        "kind": "conflict",
                        "blocking": False,
                    }
                )
    return supported, conflicts, comparisons


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
    serper_budget=None,
    discovery=None,
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

    ``discovery`` replays a RECORDED `run_event_discovery` operation instead of
    searching (V1.2-G2.4B §2). When given, no search provider is called at all,
    so a downstream measurement can change one variable — for example the
    semantic capacity available — without spending a single discovery credit.
    The pages named by the recorded operation are still opened through the same
    safe fetch path, so nothing about evidence handling is relaxed.

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
            raise StoryResearchError(
                "няма разрешен нов кръг проучване", reason=ROUNDS_EXHAUSTED
            )
    else:
        if readiness_result is None:
            raise StoryResearchError(
                "няма блокираща липсваща информация за проучване", reason=NOT_RESEARCHABLE
            )
        plan = readiness_mod.expansion_plan(
            readiness_result, rounds_used=current["research_rounds"]
        )
        if not plan["research_questions"] or plan["max_rounds_remaining"] <= 0:
            raise StoryResearchError("няма разрешен нов кръг проучване")
    stable_seed = "\0".join([story_id, *sorted(plan["research_questions"])])
    audit_path = (
        Path(root or search.search_runs_dir().parent)
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

    # §2 G2.4B — a recorded discovery operation may be REPLAYED instead of
    # re-searched. The frozen set is the input, so a downstream replay (opening →
    # extraction → corroboration → readiness) can be re-measured while changing
    # exactly one variable, and with no search provider called at all.
    #
    # It is deliberately a parameter rather than a hidden global: production
    # never passes it, and a replay that supplies one is auditable because the
    # operation record carries `frozen_discovery: true`.
    if discovery is not None:
        operation = dict(discovery)
        operation["frozen_discovery"] = True
        # The recorded operation supplies DISCOVERY only. OPENING is part of the
        # downstream pipeline being replayed, so every recorded URL is re-opened
        # here through the same safe fetch path — nothing is trusted from the
        # record except that the URL was once discovered. A page that no longer
        # opens simply records its failure, exactly as in a live round.
        replayed = []
        for entry in operation.get("candidates") or []:
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            opened = capture(url)
            replayed.append({**entry, "opened": {
                "status": web_fetch.FETCH_OK,
                "final_url": opened.get("final_url", url),
                "content_type": opened.get("content_type", "text/plain"),
                "bytes": opened.get("bytes", 0),
                "snippet_authority": "DISCOVERY_ONLY",
            }})
        operation["candidates"] = replayed
        # The rest of the round reads `started_at` for the bundle's observation
        # time; a recorded operation always has one, but a hand-built replay
        # fixture may not, and an absent field must not crash the pipeline.
        operation.setdefault("started_at", now or "")
    else:
        operation = search.run_event_discovery(
            topic=topic,
            constraints=search.make_constraints(
                description="Story gap research", location="Бургас"
            ),
            missing_dimensions=plan["missing_dimensions"],
            provider=provider,
            page_opener=capture,
            max_open=max_open,
            audit_path=audit_path,
            serper_budget=serper_budget,
        )
    # §B2/§18: the bounded opening budget must be spent on REAL publisher pages.
    # An unresolved Google News redirect is fetched successfully but is not a
    # publisher — §18 refuses it as evidence — so counting it against `max_open`
    # meant the first three slots were always wrappers and no publisher page was
    # ever read. Wrappers are still opened and recorded for the audit trail; they
    # simply do not consume the budget that exists to read publishers.
    opened = [
        c
        for c in operation.get("candidates", [])
        if (c.get("opened") or {}).get("status") == "FETCH_OK"
    ]
    publisher_opened = [
        c
        for c in opened
        if (urlsplit(str((c.get("opened") or {}).get("final_url") or c["url"])).hostname or "").lower()
        not in _NON_PUBLISHER_HOSTS
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
        publisher_opened = [
            *seed_opened,
            *publisher_opened,
        ][: max(1, int(max_open))]
    if not publisher_opened:
        if bootstrap:
            # V1.1-A §10/§16: search/fetch found nothing usable, but the
            # round itself completed — persist ASSESSED with an explicit gap
            # (never facts=0 AND gaps=0). Only an infrastructure failure
            # (exception) before any assessment keeps the Story UNASSESSED.
            # §12: this branch really did open nothing, and now says so.
            gap_text = GAP_NOTHING_OPENED
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
        raise StoryResearchError(
            operation.get("reason") or "няма отворени източници", reason=NOTHING_OPENED
        )
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
    # §R1: the default resolver is the full publisher->rows view, so several
    # registry identities sharing one domain (burgas.bg) resolve unanimously and
    # explainably instead of by row order. An injected resolver (tests, the
    # replay harness) is used exactly as before.
    policy = (
        authority_resolver()
        if authority_resolver is not None
        else newsroom_run.rows_by_publisher_domain()
    )
    # §A4: one anchor set per round, derived from the Story's own canonical
    # subject. Computed once, before any page is read.
    anchors = claim_quality.event_anchors(story_title or topic)
    for index, candidate in enumerate(publisher_opened[:max_open]):
        page = opened_pages.get(candidate["url"], {})
        final_url = str((candidate.get("opened") or {}).get("final_url") or candidate["url"])
        normalized_url = publication_identity.normalize_publication_url(final_url)
        host = (urlsplit(normalized_url).hostname or "").lower()
        if (
            not normalized_url
            or host == "chernomorie-bg.com"
            or host.endswith(".chernomorie-bg.com")
            or blocked_mod.is_blocked(normalized_url)
            or host in _NON_PUBLISHER_HOSTS
        ):
            # §18: an unresolved aggregator or social page is not a source.
            continue
        publication_key = publication_identity.publication_key_for(normalized_url, host)
        if publication_key in seen_keys or publication_key in set(existing_publication_keys):
            continue
        seen_keys.add(publication_key)
        text = str(page.get("text") or "")
        # §A2: segment the page into TYPED blocks instead of one flattened run.
        # Only PROSE can become a proposition, which is what structurally
        # prevents a heading from being concatenated into a factual sentence.
        # A plain-text page (no markup) segments as a single PROSE block, so the
        # historical behaviour is preserved for it.
        blocks = html_desc.normalize_blocks(text)
        if not blocks and text.strip():
            blocks = ({"kind": html_desc.PROSE, "text": text},)
        # §9/§10/§11/§12: a small, ordered candidate set instead of the first
        # matching sentence. Navigation chrome and non-propositional text are
        # rejected here, before anything can be promoted, and each surviving
        # candidate remembers which research question it answers.
        # §A4: `anchors` drops a sentence about a different event before claim
        # comparison and before any model call.
        candidates = claim_quality.select_candidate_claims(
            claim_quality.SENTENCE_SPLIT.split(text),
            plan["research_questions"],
            limit=CLAIMS_PER_PAGE,
            topic=story_title or topic,
            blocks=blocks,
            anchors=anchors,
        )
        if not candidates:
            continue
        # §R1/§R2: resolve authority from the PUBLISHER IDENTITY of the page that
        # actually opened, not from the bare host. `www.burgas.bg` is the same
        # publisher as the registry's `burgas.bg`, and looking up the raw host
        # missed it entirely — which is precisely why the owner's real case was
        # refused a corroboration gap its own official source could fill. When
        # the caller injects a resolver (tests, the replay harness) the historical
        # plain-dict lookup is used unchanged.
        if isinstance(policy, dict) and not isinstance(
            next(iter(policy.values()), None), list
        ):
            # An INJECTED resolver is keyed by the registry's publisher domain, so
            # it is consulted with the same publisher IDENTITY as the default
            # resolver. Looking it up with the raw host would reintroduce exactly
            # the §R1 bug this slice fixed: `www.burgas.bg` would miss `burgas.bg`
            # and an official source would be demoted to ordinary media.
            row = policy.get(host) or policy.get(_publisher_identity(host))
            authority_name = row.get("name") if isinstance(row, dict) else ""
            factual = bool(row and row.get("factual_authority"))
            kind = row.get("kind") if isinstance(row, dict) else ""
        else:
            resolved = newsroom_run.resolve_publisher_policy(
                host, policy, publisher_identity=_publisher_identity
            )
            factual = bool(resolved["factual_authority"])
            kind = resolved["kind"]
            authority_name = resolved["name"]
        source_type = (
            "official_document"
            if factual and kind in {"official", "official_document"}
            else "media"
        )
        authority = "PRIMARY" if factual else "CORROBORATING"
        source_id = "src_" + hashlib.sha256(normalized_url.encode()).hexdigest()[:16]
        source = {
            "id": source_id,
            "name": authority_name or host,
            "url": normalized_url,
            # V1.2-G4.1 §B3: the claims this page actually yielded, read verbatim.
            # They are recorded per opened page from the moment they are extracted
            # so that a later decision — promoted or not — never has to invent
            # them. A promoted claim still becomes a `fact`; an unpromoted one
            # stays here as source-backed material for an ATTRIBUTED Draft.
            "claims": [
                {"text": row["text"], "locator": f"claim:{slot}"}
                for slot, row in enumerate(candidates)
                if row.get("text")
            ],
        }
        sources.append(source)
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
            relevant_claims=[row["text"] for row in candidates],
        )
        for slot, row in enumerate(candidates):
            source_records.append(
                {
                    "source": source,
                    "claim": row["text"],
                    "domain": host,
                    # §8: independence is decided by the PUBLISHER identity the
                    # store already computes, so a subdomain and its parent -
                    # or two paths on one site - are one source, not two.
                    "publisher": _publisher_identity(host),
                    "authority": authority,
                    "dimensions": row["dimensions"],
                    "locator": f"claim:{slot}",
                }
            )
    # §2/§16: promotion is decided per CLAIM, not per source, and corroboration
    # means two independent publishers supporting the SAME FACTUAL PROPOSITION
    # rather than the same string. The safety rule is untouched: a claim is
    # promoted when its own source is PRIMARY, or when an independent domain
    # confirms it. Nothing else grants evidence.
    allowed_source_ids, new_conflicts, comparison_count = _promote_claims(source_records)
    assert comparison_count <= MAX_SEMANTIC_COMPARISONS
    # §30: the semantic stage is a model call. `comparison_count` is how many
    # candidate PAIRS this round actually spent, and the cap that bounds it is
    # asserted directly by the test suite, so the cost cannot drift upward
    # silently.
    facts = [
        {
            "id": _fact_id(story_id, item["source"]["id"], item["claim"]),
            # §20: the wording is the supporting source's own sentence. No
            # synthesis is invented, and every supporting source keeps its own
            # fact row, so provenance stays per source.
            "text": item["claim"],
            "source_refs": [
                {"source_id": item["source"]["id"], "locator": item["locator"]}
            ],
            "scope": "current_event",
        }
        for item in source_records
        if item["source"]["id"] in allowed_source_ids and item["claim"]
    ]
    # §12: a claim existed and the gate dropped it is a corroboration problem.
    dropped_by_gate = len(source_records) - len(facts)
    if not facts:
        # V1.1-A §10/§16: a completed first round with no usable opened
        # source is ASSESSED with an explicit gap — never an empty assessed
        # basis and never silent UNASSESSED. Later gap-driven rounds keep the
        # historical refusal (nothing to merge, nothing to persist).
        # §12: the pages DID open. A claim that existed and was dropped by the
        # gate is specifically a corroboration problem: a fact survives only if
        # its source is PRIMARY or its claim was seen on two independent
        # domains, so a dropped single-domain claim is exactly the case where
        # one more independent publisher would settle it. When no claim was
        # extracted at all, nothing is known and the vaguer sentence is the
        # truthful one.
        gap_text = (
            GAP_NEEDS_CORROBORATION if dropped_by_gate else GAP_NOTHING_PROMOTED
        )
        if bootstrap:
            # §21/§23: a contradiction found while promoting is still shown as
            # itself, even when nothing was promoted. The editor must see the
            # disagreement rather than a generic "insufficient" sentence.
            insufficient_gaps = [
                {
                    "id": _gap_id(story_id, gap_text),
                    "question": gap_text,
                    "kind": "unresolved",
                    "blocking": True,
                }
            ] + list(new_conflicts)
            return story_research_store.merge_research(
                story_id,
                facts=[],
                # V1.2-G4.1 §B3: the pages really were opened and really did
                # yield claims, so the opened sources are persisted. The facts
                # stay empty (the corroboration gate declined them) and the
                # blocking gap stays blocking, but the basis can now express
                # "an ordinary publisher page was opened here" — which is what
                # lets the editor start an ATTRIBUTED Draft instead of being
                # refused. It does not promote anything to a confirmed fact.
                sources=list(sources),
                gaps=insufficient_gaps,
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
        # §R4/§R5: this branch splits on a distinction that matters and that the
        # owner hit directly.
        #
        #  * NO claim was extracted from ANY opened page. The round learned
        #    nothing, so there is no assessment to persist and the basis must be
        #    left exactly as it was — the V1.1-A "failed open" contract.
        #  * Claims WERE extracted and the gate declined them. The round
        #    completed and DID assess: pages opened, claims read, gate refused
        #    them for want of an independent second publisher. That is an
        #    evidence outcome and is persisted as exactly the gap it is.
        #    Refusing here is what produced the owner's "Проучването не можа да
        #    завърши." for a round that had actually worked.
        if not source_records:
            raise StoryResearchError(
                "отворените източници не съдържат извлечими твърдения",
                reason=NOTHING_OPENED,
            )
        return story_research_store.merge_research(
            story_id,
            facts=[],
            # V1.2-G4.1 §B3: same reasoning as the bootstrap branch above — the
            # page opened and produced claims, so the opened source is recorded
            # as source-backed material for an attributed Draft. No fact is
            # promoted, and the corroboration gap remains blocking.
            sources=list(sources),
            gaps=[
                {
                    "id": _gap_id(story_id, gap_text),
                    "question": gap_text,
                    "kind": "unresolved",
                    "blocking": True,
                }
            ]
            + list(new_conflicts),
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
        raise StoryResearchError(
            "готовността на Story не можа да се оцени", reason=TECHNICAL_FAILURE
        ) from exc
    current_gaps = list(current.get("gaps") or [])
    conflicts = [gap for gap in current_gaps if gap.get("kind") == "conflict"]
    # §21/§23: a detected contradiction is shown as the plain-language question
    # it is, never absorbed into a generic "insufficient" sentence.
    for gap in new_conflicts:
        if gap["id"] not in {known["id"] for known in conflicts}:
            conflicts.append(gap)
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
        fallback = GAP_NOTHING_PROMOTED
        gaps = [
            {
                "id": _gap_id(story_id, fallback),
                "question": fallback,
                "kind": "unresolved",
                "blocking": True,
            }
        ]
    bundle_path = (
        Path(root or search.search_runs_dir().parent) / "search_runs" / f"{research_id}.jsonl"
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
