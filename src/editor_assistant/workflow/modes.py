"""M2.8 mode suggestion - deterministic, explainable heuristics (no training).

The suggestion is stored alongside the editor's selection so the override
rate becomes a real-world signal. Order: event-native sources first
(future dates/times + future-tense cues), then culture long-form, then very
small factual items (BRIEF), else STANDARD_NEWS.
"""

from __future__ import annotations

import re

_FUTURE_CUE = re.compile(
    r"ще се проведе|ще се състои|ще започне|ще включи|ще участва|ще награди|"
    r"предстои|очаква се|ще открие|откриването|ще бъде|се очаква",
    re.IGNORECASE,
)
_TIME_CUE = re.compile(r"\b\d{1,2}[:.]\d{2}\s*ч\b")
_CULTURE_CUE = re.compile(
    r"фестивал|театър|театралн|изложб|концерт|галерия|музей|премиера|филм|"
    r"литератур|биенале|кукул|спектакл|конкурс за",
    re.IGNORECASE,
)


def suggest_mode(packet):
    """Return {'suggested_mode', 'reason'} for an EvidencePacket (deterministic).

    Future-event intent outranks source length: a future event with
    date/venue is an EVENT_PREVIEW even when the source is short
    (checkpoint lesson: LIV-03's 3 calendar lines were mis-suggested BRIEF).
    """
    text = packet.get("source_text", "") or ""
    facts = packet.get("facts", []) or []
    dates = packet.get("dates", []) or []
    places = packet.get("places", []) or []
    has_time = bool(_TIME_CUE.search(text)) or any("ч" in str(d) for d in dates)
    future = bool(_FUTURE_CUE.search(text))
    culture_hits = len(set(_CULTURE_CUE.findall(text)))
    if (has_time or dates or places) and (future or _event_lead(packet)):
        return {
            "suggested_mode": "MODE_EVENT_PREVIEW",
            "reason": f"future event: date/time/venue present "
            f"({len(dates)} dates, {len(places)} places) + future-tense cues",
        }
    if culture_hits >= 2 and len(text) >= 2500:
        return {
            "suggested_mode": "MODE_CULTURE_FEATURE",
            "reason": f"culture long-form source: {culture_hits} culture cues, {len(text)} chars",
        }
    if len(facts) <= 3 and len(text) < 900:
        return {
            "suggested_mode": "MODE_BRIEF",
            "reason": f"very small factual item: {len(facts)} facts, {len(text)} chars",
        }
    return {
        "suggested_mode": "MODE_STANDARD_NEWS",
        "reason": "default: no strong event/culture/brief signal",
    }


def _event_lead(packet):
    """True when the idea/packet explicitly marks a future event lead."""
    idea_hint = str(packet.get("source_type", ""))
    head = str(packet.get("source_headline", ""))
    return "event" in idea_hint or "preview" in idea_hint.lower() or bool(_FUTURE_CUE.search(head))
