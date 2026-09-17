"""LIVE pilot research layer: web discovery -> SourceBundle -> EvidencePacket.

Minimal capability per the 5-case checkpoint spec (M2.7-9, LIVE checkpoint):
no crawler, no index, no vector DB - one inspectable, serializable, small
artifact per case. Hard boundaries:

* search-result snippets / aggregators are DISCOVERY_ONLY authority and can
  never back a promoted fact on their own;
* model memory is never factual evidence - every material fact promoted into
  an EvidencePacket carries source_refs {source_id, locator} into an OPENED
  source in the bundle (claim-level provenance);
* a published Chеrnomorie article is never the factual source of its own
  LIVE draft (circular guard lives in cases.py/live.py);
* council "adopted/approved/rejected" claims require PRIMARY authority
  (official protocol/decision record), never discussion alone.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SOFIA = ZoneInfo("Europe/Sofia")
RESEARCH_DIR = Path(__file__).resolve().parents[3] / "var" / "editorial_workflow" / "research"

AUTHORITY_LEVELS = ("PRIMARY", "CORROBORATING", "DISCOVERY_ONLY")
PROMOTABLE_AUTHORITIES = ("PRIMARY", "CORROBORATING")
SOURCE_TYPES = (
    "official_institution",
    "organizer",
    "venue",
    "official_document",
    "official_social",
    "ticket_platform",
    "media",
    "transcript",
    "search_snippet",
    "aggregator",
    "other",
)
DUPLICATE_STATUSES = (
    "NO_DUPLICATE",
    "RELATED_OLDER_COVERAGE",
    "DUPLICATE_CURRENT_STORY",
    "DUPLICATE_CHECK_DEFERRED",
)
RESEARCH_STATUSES = ("OPEN", "COMPLETED", "ABANDONED")
FAILURE_REASONS = (
    "INSUFFICIENT_EVIDENCE",
    "DUPLICATE_CURRENT_STORY",
    "SOURCE_UNRELIABLE",
    "NOT_NEWSWORTHY",
    "EDITOR_REJECTED",
    "ACCESS_BLOCKED",
)

_DECISION_RE = re.compile(
    r"\b(?:прие|одобри|отхвърли|гласува|реши)\w*\b|"
    r"\bрешени[ея]\b|\bпротокол\b|\bприет\b|\bодобрен\b|\bотхвърлен\b",
    re.IGNORECASE,
)
_TIMESTAMP_RE = re.compile(r"\b(?:t=)?(\d{1,2}:\d{2}(?::\d{2})?)\b")
_CHUNK = 2000


class ResearchError(ValueError):
    pass


def sofia_now():
    """Absolute + local time record (Europe/Sofia per the checkpoint spec)."""
    n = datetime.now(timezone.utc)
    local = n.astimezone(SOFIA)
    return {
        "utc": n.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_date": local.strftime("%Y-%m-%d"),
        "local_hhmm": local.strftime("%H:%M"),
    }


def resolve_editor_time(expression):
    """Resolve editor shorthand ('today', 'next upcoming') against the recorded
    local execution time. Persist the resolved value; never guess afterwards."""
    now = sofia_now()
    expr = (expression or "").strip().lower()
    if expr in ("today", "днес"):
        return {"resolved": now["local_date"], "expression": expression, **now}
    if expr in ("next upcoming", "следващото предстоящо", "upcoming"):
        return {
            "resolved": "evaluate_upcoming_against_local_execution_time",
            "expression": expression,
            **now,
        }
    return {"resolved": expression, "expression": expression, **now}


def make_bundle(
    *, research_id, query, editor_request, research_type, started_at=None, local_date=None
):
    """Open a research bundle. research_type gates completion requirements
    (e.g. today_news needs >=3 candidate developments)."""
    now = sofia_now()
    bundle = {
        "research_id": research_id,
        "created_at": started_at or now["utc"],
        "research_started_at": started_at or now["utc"],
        "research_completed_at": None,
        "local_date": local_date or now["local_date"],
        "query": query,
        "editor_request": editor_request,
        "research_type": research_type,
        "status": "OPEN",
        "candidates": [],
        "selected_candidate": None,
        "sources": [],
        "research_notes": "",
        "warnings": [],
        "duplicate_check": {"status": None},
    }
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle):
    for key in ("research_id", "query", "editor_request", "research_type", "status"):
        if not bundle.get(key):
            raise ResearchError(f"bundle missing {key}")
    if bundle["status"] not in RESEARCH_STATUSES:
        raise ResearchError(f"bad research status: {bundle['status']!r}")
    for cand in bundle.get("candidates", []):
        for key in ("candidate_id", "title", "url"):
            if not cand.get(key):
                raise ResearchError(f"candidate missing {key}: {cand}")
        if cand.get("failure_reason") and cand["failure_reason"] not in FAILURE_REASONS:
            raise ResearchError(f"bad failure_reason: {cand['failure_reason']!r}")
    for src in bundle.get("sources", []):
        for key in ("source_id", "url", "source_name", "source_type", "authority"):
            if not src.get(key):
                raise ResearchError(f"source missing {key}: {src}")
        if src["authority"] not in AUTHORITY_LEVELS:
            raise ResearchError(f"bad authority: {src['authority']!r}")
        if src["source_type"] not in SOURCE_TYPES:
            raise ResearchError(f"bad source_type: {src['source_type']!r}")
    dup = bundle.get("duplicate_check", {}).get("status")
    if dup is not None and dup not in DUPLICATE_STATUSES:
        raise ResearchError(f"bad duplicate status: {dup!r}")
    return True


def add_candidate(
    bundle,
    *,
    candidate_id,
    title,
    url,
    source_name,
    source_type,
    published_at="",
    local_relevance="",
    selection_note="",
    failure_reason=None,
):
    """Record a discovery candidate (even rejected ones - §18 no cherry-picking:
    failed attempts stay visible with one explicit reason)."""
    cand = {
        "candidate_id": candidate_id,
        "title": title,
        "url": url,
        "source_name": source_name,
        "source_type": source_type,
        "published_at": published_at,
        "local_relevance": local_relevance,
        "duplicate_status": None,
        "selection_note": selection_note,
        "failure_reason": failure_reason,
    }
    bundle["candidates"].append(cand)
    validate_bundle(bundle)
    return cand


def select_candidate(bundle, candidate_id, *, note=""):
    for cand in bundle["candidates"]:
        if cand["candidate_id"] == candidate_id:
            cand["selection_note"] = note or cand["selection_note"]
            bundle["selected_candidate"] = candidate_id
            return cand
    raise ResearchError(f"unknown candidate: {candidate_id}")


def open_source(
    bundle,
    *,
    source_id,
    url,
    source_name,
    source_type,
    authority,
    title="",
    published_at="",
    relevant_claims=(),
    content_reference="",
):
    """Record an OPENED source (fetched content, not a bare search snippet)."""
    if authority == "DISCOVERY_ONLY" and source_type not in ("search_snippet", "aggregator"):
        raise ResearchError("DISCOVERY_ONLY authority is for snippets/aggregators only")
    src = {
        "source_id": source_id,
        "url": url,
        "source_name": source_name,
        "source_type": source_type,
        "authority": authority,
        "published_at": published_at,
        "retrieved_at": sofia_now()["utc"],
        "title": title,
        "relevant_claims": list(relevant_claims),
        "content_reference": content_reference,
    }
    bundle["sources"].append(src)
    validate_bundle(bundle)
    return src


def set_duplicate_check(bundle, status, *, checked_urls=(), note=""):
    if status not in DUPLICATE_STATUSES:
        raise ResearchError(f"bad duplicate status: {status!r}")
    bundle["duplicate_check"] = {"status": status, "checked_urls": list(checked_urls), "note": note}
    return bundle["duplicate_check"]


def complete_bundle(bundle, *, notes="", warnings=()):
    if bundle["status"] != "OPEN":
        raise ResearchError("bundle already closed")
    if not bundle["selected_candidate"]:
        raise ResearchError("no candidate selected")
    if bundle["duplicate_check"]["status"] is None:
        raise ResearchError("duplicate check must run before completion (§5)")
    if bundle["research_type"] == "today_news" and len(bundle["candidates"]) < 3:
        raise ResearchError("today_news research must persist >=3 candidate developments (LIV-05)")
    primary = [s for s in bundle["sources"] if s["authority"] == "PRIMARY"]
    corroborating = [s for s in bundle["sources"] if s["authority"] == "CORROBORATING"]
    if not primary and len({s["source_name"] for s in corroborating}) < 2:
        raise ResearchError("story needs a PRIMARY source or >=2 independent corroborating sources")
    bundle["research_completed_at"] = sofia_now()["utc"]
    bundle["research_notes"] = notes
    bundle["warnings"] = list(warnings)
    bundle["status"] = "COMPLETED"
    validate_bundle(bundle)
    return bundle


# ---------- claim-level provenance (HARD requirement, §3) ----------


def make_fact_ref(source_id, locator):
    if not source_id or not locator:
        raise ResearchError("provenance needs source_id AND locator")
    return {"source_id": source_id, "locator": str(locator)}


_REF_STOP = r"[0-9a-z\u0400-\u04ff]+"


def _ref_tokens(text):
    """Distinctive tokens only: long words or anything containing a digit.

    Deliberately conservative - short/common words must never link a fact to a
    claim, or provenance becomes decorative instead of verifiable.
    """
    import re as _re

    out = set()
    for token in _re.findall(_REF_STOP, (text or "").lower()):
        if len(token) >= 8 or any(ch.isdigit() for ch in token):
            out.add(token)
    return out


def claim_locator(index):
    """Locator into an opened source's recorded `relevant_claims` list."""
    if index is None or index < 0:
        raise ResearchError("claim locator needs a non-negative index")
    return f"claim:{index}"


def matching_claim_indices(fact_text, source, *, min_overlap=2):
    """Indices of recorded claims that genuinely support this fact text.

    A claim matches only with >= min_overlap distinctive shared tokens (or a
    shared 12+ char alphanumeric run). Returns [] when nothing is verifiable -
    callers must NOT invent a locator in that case.
    """
    import re as _re

    text = (fact_text or "").lower()
    hits = []
    for index, claim in enumerate(source.get("relevant_claims") or []):
        shared = _ref_tokens(fact_text) & _ref_tokens(claim)
        if len(shared) >= min_overlap:
            hits.append(index)
            continue
        for run in _re.findall(r"[0-9a-z\u0400-\u04ff]{12,}", (claim or "").lower()):
            if run in text:
                hits.append(index)
                break
    return hits


def attach_bundle_refs(packet, bundle, *, strict=True, min_overlap=2):
    """Attach claim-level source_refs to packet facts, from opened bundle sources.

    Only verifiable links are written: a fact gets refs to the exact recorded
    claims (of PRIMARY/CORROBORATING sources) whose text shares distinctive
    tokens with it. Nothing is inferred, and previously attached refs are kept.
    strict=True fails loudly on facts that cannot be traced (the LIVE intake
    contract); strict=False returns them under "unmatched" for audit.
    Returns {attached, unmatched, sources_used}.
    """
    promotable = promotable_sources(bundle)
    if not promotable:
        raise ResearchError("no promotable (PRIMARY/CORROBORATING) source opened")
    attached, unmatched = {}, []
    for fact in packet.get("facts", []):
        refs = [dict(r) for r in fact.get("source_refs") or []]
        if not refs:
            found = []
            for source_id, source in promotable.items():
                for index in matching_claim_indices(fact["text"], source, min_overlap=min_overlap):
                    ref = make_fact_ref(source_id, claim_locator(index))
                    if ref not in found:
                        found.append(ref)
            if found:
                fact["source_refs"] = found
                refs = found
            else:
                unmatched.append(fact["id"])
        if refs:
            attached[fact["id"]] = refs
    if strict and unmatched:
        raise ResearchError(
            "facts without verifiable claim-level provenance: " + ", ".join(unmatched)
        )
    from editor_assistant.drafting.evidence import validate_packet

    validate_packet(packet)
    return {
        "attached": attached,
        "unmatched": unmatched,
        "sources_used": sorted({r["source_id"] for refs in attached.values() for r in refs}),
    }


def promotable_sources(bundle):
    """Sources a fact may cite: opened PRIMARY/CORROBORATING pages only."""
    return {
        s["source_id"]: s for s in bundle["sources"] if s["authority"] in PROMOTABLE_AUTHORITIES
    }


def provenanced_packet(
    bundle,
    *,
    evidence_id,
    observed_at,
    headline,
    facts,
    quotes=(),
    people=(),
    organizations=(),
    places=(),
    dates=(),
    numbers=(),
    unknowns=(),
    source_text=None,
):
    """Build an M2.3B EvidencePacket where every fact carries source_refs into
    promotable bundle sources. Facts without provenance are REJECTED (fail loud)."""
    from editor_assistant.drafting.evidence import make_fact, make_quote, validate_packet

    promotable = promotable_sources(bundle)
    if not promotable:
        raise ResearchError("no promotable (PRIMARY/CORROBORATING) source opened")
    out_facts = []
    for fact in facts:
        refs = fact.get("source_refs") or []
        if not refs:
            raise ResearchError(
                f"fact rejected (no provenance): {fact.get('id')}: {fact.get('text', '')[:80]}"
            )
        for ref in refs:
            if ref["source_id"] not in promotable:
                raise ResearchError(
                    f"  fact {fact.get('id')} cites non-promotable/unknown source "
                    f"{ref['source_id']} (snippets/aggregators are discovery-only)"
                )
        promoted = make_fact(
            fact["id"],
            fact["text"],
            source_reference=", ".join(f"{r['source_id']}:{r['locator']}" for r in refs),
        )
        promoted["source_refs"] = [dict(ref) for ref in refs]
        out_facts.append(promoted)
    out_quotes = [make_quote(q["text"], q.get("speaker"), q.get("role")) for q in quotes]
    selected = next(
        c for c in bundle["candidates"] if c["candidate_id"] == bundle["selected_candidate"]
    )
    packet = {
        "evidence_id": evidence_id,
        "source_url": selected["url"],
        "source_type": "live_research_bundle",
        "observed_at": observed_at,
        "source_headline": headline,
        "facts": out_facts,
        "people": list(people),
        "organizations": list(organizations),
        "places": list(places),
        "dates": list(dates),
        "numbers": list(numbers),
        "quotes": out_quotes,
        "unknowns": list(unknowns),
        "source_text": source_text
        or "\n".join(s for src in bundle["sources"] for s in src["relevant_claims"]),
    }
    validate_packet(packet)
    return packet


def validate_provenance(packet, bundle):
    """Contract check: every material fact has >=1 source ref into a promotable
    opened source. Answers 'exactly where did this fact come from?'."""
    promotable = promotable_sources(bundle)
    problems = []
    for fact in packet["facts"]:
        refs = fact.get("source_refs") or []
        if not refs:
            problems.append(f"{fact['id']}: no source_refs")
        for ref in refs:
            if ref["source_id"] not in promotable:
                problems.append(f"{fact['id']}: source {ref['source_id']} not promotable")
            if not ref.get("locator"):
                problems.append(f"{fact['id']}: empty locator")
    if problems:
        raise ResearchError("provenance validation failed: " + "; ".join(problems))
    return True


# ---------- transcript intake (LIV-02, §14) ----------
_CHUNK = 2000

# Auto-caption exports carry player artifacts inside the text:
#   "0:044 secondsКолеги, ..."              -> cue 0:04 + duplicated "4 seconds"
#   "8:138 minutes, 13 secondsгласа за."    -> cue 8:13 + "8 minutes, 13 seconds"
# The normalizer removes ONLY those artifacts and keeps the cue as a locator.
# It never corrects ASR wording - what the editor supplied is the evidence.
_CAPTION_ARTIFACT = re.compile(
    r"(?<![\w:])(\d{1,2}):(\d{2})(?::(\d{2}))?"  # cue clock
    r"(?:\s*\d*\s*seconds?"  # "4 seconds" / "seconds"
    r"|\s*\d+\s*minutes?,?\s*(?:\d+\s*)?seconds?)",  # "8 minutes, 13 seconds"
    re.IGNORECASE,
)
_CUE_AT_LINE_START = re.compile(r"(?m)^[ \t]*(\d{1,2}):(\d{2})(?::(\d{2}))?(?=\s|$)")


def _cue_locator(match):
    parts = [int(match.group(1)), int(match.group(2))]
    if match.group(3) is not None:
        parts.append(int(match.group(3)))
    return "t=" + ":".join(f"{p:02d}" for p in parts)


def normalize_caption_transcript(text):
    """Strip caption artifacts and inline each surviving cue as a marker.

    Returns text where a cue reads ``\\x01t=MM:SS\\x01``; nothing else changes.
    """

    def _marker(match):
        return f"\x01{_cue_locator(match)}\x01"

    normalized = _CAPTION_ARTIFACT.sub(_marker, text or "")
    return _CUE_AT_LINE_START.sub(_marker, normalized)


_MARKER = re.compile(r"\x01(t=[\d:]+)\x01")
_MARKER_TAIL = re.compile(r"\x01")


def marked_claims(text):
    """Clean claims with the caption cue they were spoken under.

    Each cue starts a new caption line, so cues are claim boundaries too - the
    line has no terminal punctuation of its own (that is what merged unrelated
    statements into one giant claim before). Within one cue, sentences stay
    separate but share the cue locator. Claims before the first cue return None
    so the caller can fall back to a deterministic chunk locator.
    """
    from editor_assistant.drafting.evidence import _sentences

    normalized = normalize_caption_transcript(text)
    parts = re.split(r"\x01(t=[\d:]+)\x01", normalized)
    chunks = [(parts[0], None)] + [(parts[i], parts[i - 1]) for i in range(2, len(parts), 2)]
    out = []
    for chunk, locator in chunks:
        for sentence in _sentences(chunk):
            claim = re.sub(r"\s+", " ", sentence).strip()
            if claim:
                out.append((claim, locator))
    return out


def transcript_chunk_locator(text_len, offset):
    """Deterministic chunk locator when the transcript has no timestamps."""
    base = (offset // _CHUNK) * _CHUNK
    return f"chunk:{base}-{min(base + _CHUNK, text_len)}"


def _cue_seconds(locator):
    if not locator or not locator.startswith("t="):
        return None
    parts = [int(p) for p in locator[2:].split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def segment_qualified_locators(locators):
    """Qualify cue locators with a segment index when the clock restarts.

    A transcript file may concatenate several recordings; the same t=06:21 then
    addresses two different statements. Locators are prefixed seg<N>@ only when
    a restart is actually detected, so single-recording intake is unchanged.
    """
    if not _has_restart(locators):
        return list(locators)
    out, index, previous = [], 1, None
    for locator in locators:
        seconds = _cue_seconds(locator)
        if seconds is None:
            out.append(locator)
            continue
        if previous is not None and seconds < previous:
            index += 1
        previous = seconds
        out.append(f"seg{index}@{locator}")
    return out


def _has_restart(locators):
    previous = None
    for locator in locators:
        seconds = _cue_seconds(locator)
        if seconds is None:
            continue
        if previous is not None and seconds < previous:
            return True
        previous = seconds
    return False


def ingest_transcript(text, *, source_id, source_name, url=""):
    """Editor-supplied transcript -> source record with deterministic locators.

    Caption artifacts are stripped and each cue is preserved per claim
    (t=MM:SS, seg<N>@t=MM:SS for concatenated recordings); claims without a cue
    get deterministic chunk locators. Returns the source record plus the
    sentence->locator map used for provenance.
    """
    text = text or ""
    raw = marked_claims(text)
    locators = [
        locator or transcript_chunk_locator(len(text), max(text.find(claim[:60]), 0))
        for claim, locator in raw
    ]
    qualified = segment_qualified_locators(locators)
    claims = [claim for claim, _ in raw]
    record = {
        "source_id": source_id,
        "url": url,
        "source_name": source_name,
        "source_type": "transcript",
        "authority": "PRIMARY",
        "published_at": "",
        "retrieved_at": sofia_now()["utc"],
        "title": f"Transcript: {source_name}",
        "relevant_claims": claims,
        "content_reference": "editor-supplied transcript",
    }
    return record, list(zip(claims, qualified))


# ---------- council safeguard (§14, test 8) ----------


def council_decision_claims(packet):
    """Facts asserting adopted/approved/rejected/voted outcomes (BG verbs)."""
    return [f for f in packet["facts"] if _DECISION_RE.search(f["text"])]


def validate_council_claims(packet, bundle):
    """ "Council approved/adopted/rejected" requires PRIMARY authority (official
    protocol/decision record/transcript) - never discussion alone."""
    promotable = promotable_sources(bundle)
    for fact in council_decision_claims(packet):
        for ref in fact.get("source_refs") or []:
            src = promotable.get(ref["source_id"])
            if (
                src is None
                or src["authority"] != "PRIMARY"
                or src["source_type"]
                not in ("official_institution", "official_document", "transcript")
            ):
                raise ResearchError(
                    f"decision claim {fact['id']} needs PRIMARY official "
                    "protocol/decision/transcript provenance, not discussion alone"
                )
    return True


def is_clean_live_case(bundle):
    """DUPLICATE_CURRENT_STORY can never count as a clean LIVE case (§5).

    DUPLICATE_CHECK_DEFERRED (duplicate check postponed to human-review stage
    per editor decision) also cannot count as clean — it must resolve to
    NO_DUPLICATE or RELATED_OLDER_COVERAGE before the case counts.
    """
    return bundle.get("status") == "COMPLETED" and bundle["duplicate_check"]["status"] in (
        "NO_DUPLICATE",
        "RELATED_OLDER_COVERAGE",
    )


def save_bundle(bundle, path=None):
    out = Path(path) if path else RESEARCH_DIR / f"{bundle['research_id'].replace('RES-', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    validate_bundle(bundle)
    out.write_text(
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    return out


def load_bundle(path):
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_bundle(bundle)
    return bundle
