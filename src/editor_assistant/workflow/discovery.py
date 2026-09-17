"""Generic transcript discovery (M2S Track T): segments -> facts -> angles.

The audit's central transcript finding: the pipeline had validators but no
*discovery* step, so the committee batch was hand-curated. This module closes
that gap generically (no committee, no entity, no case is ever encoded):

    TranscriptDocument -> normalized spans -> topic segments
    -> candidate facts (grounded in segment ids, ASR risks flagged)
    -> candidate angles -> angles.assess_angles (the unchanged v2 gate)
    -> readiness

Model-assisted but strictly source-bound: the model may only compress and
segment what the transcript says; every fact/angle carries transcript
segment provenance, and the deterministic contracts validate grounding.
Model memory cannot create evidence.
"""

from __future__ import annotations

import json
import os
import re

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import transcripts as T

TOPIC_FALLBACK_LABEL = "тема без разпознат дневен ред"
MAX_TOPICS_DEFAULT = 12
INSUFFICIENT_ANGLES = "INSUFFICIENT_CANDIDATE_ANGLES"

_AGENDA_CUE = re.compile(
    r"^(?:точка|т\.|втора|трета|четвърта|пета|шеста|седма|осма|девета|десета)\b"
    r"|дневен ред|преминаваме към|следващата точка|по отношение на",
    re.IGNORECASE,
)


# ---------- topic segmentation (harness B7) ----------


def segment_topics(doc, *, max_topics=MAX_TOPICS_DEFAULT):
    """Split normalized spans into agenda-style topic segments.

    Deterministic agenda cues start a new topic when they open a span; spans
    without cues attach to the current topic. Topics without any cue become
    one neutral fallback topic (B7: cues are preferred, not required).
    """
    spans = T.normalize_overlap(doc)
    topics = []
    current = None
    for span in spans:
        is_boundary = bool(_AGENDA_CUE.search(span["text"][:120]))
        if current is None or (is_boundary and current["spans"]):
            if current is not None:
                topics.append(current)
            current = {
                "topic_id": f"{doc.transcript_id}-t{len(topics) + 1:02d}",
                "start_ms": span["start_ms"],
                "end_ms": span["end_ms"],
                "spans": [],
            }
        current["spans"].append(span)
        current["end_ms"] = max(current["end_ms"], span["end_ms"])
        if len(topics) >= max_topics:
            break
    if current is not None and len(topics) < max_topics:
        topics.append(current)

    out = []
    for i, topic in enumerate(topics, start=1):
        label_cue = next(
            (s["text"][:90] for s in topic["spans"] if _AGENDA_CUE.search(s["text"][:120])),
            None,
        )
        out.append(
            {
                "topic_id": f"{doc.transcript_id}-t{i:02d}",
                "start_ms": topic["start_ms"],
                "end_ms": topic["end_ms"],
                "start": T._ms_to_clock(topic["start_ms"]),
                "end": T._ms_to_clock(topic["end_ms"]),
                "label": (label_cue or topic["spans"][0]["text"][:90]).strip(),
                "deterministic_boundary": label_cue is not None,
                "segment_ids": [sid for s in topic["spans"] for sid in s["segment_ids"]],
                "text": " ".join(s["text"] for s in topic["spans"]),
            }
        )
    return out


# ---------- model-assisted candidate fact extraction (harness B8) ----------

_FACTS_PROMPT = """Ти си редакционен асистент. По-долу е машинен транскрипт (автоматични
субтитри, с възможни ASR грешки) от една тема на заседание.

Из извлек ИЗОБЩО не добавяй факти от паметта или от интернет. Избери само
констатации, буквално изречени в транскрипта. 2-5 факта максимум; ако няма
поне 2 смислени, върни празен списък.

ВърНИ СТРОГО JSON:
{{"facts": [{{"text": "...", "segment_ids": ["..."], "risk_flags": ["final_decision|material_number|personal_or_org_name|exact_quote|negation_sensitive|legal_institutional_status"], "uncertain": false}}]}}

Правила:
- "segment_ids" задължително са от подадените ID-та;
- не поправяй имена/числа по памет - маркирай risk_flags и uncertain;
- пренапиши минимално (нека изречението е четимо), но не променяй смисъла.

ТЕМА: {label}
ID-та на сегментите: {ids}

ТРАНСКРИПТ:
{text}
"""


def _extract_facts_for_topic(topic, *, api_key=None, timeout=120):
    prompt = _FACTS_PROMPT.format(
        label=topic["label"],
        ids=", ".join(topic["segment_ids"][:40]),
        text=topic["text"][:6000],
    )
    raw, _meta = gen.call_model(prompt, api_key=api_key, timeout=timeout, role="judge")
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    valid_ids = set(topic["segment_ids"])
    facts = []
    for item in (payload.get("facts") or [])[:5]:
        text = (item.get("text") or "").strip()
        ids = [i for i in (item.get("segment_ids") or []) if i in valid_ids]
        if not text or not ids:
            continue
        risks = [r for r in (item.get("risk_flags") or []) if r in T.ALL_RISK_FLAGS]
        facts.append(
            {
                "text": text,
                "segment_ids": ids,
                "risk_flags": risks or T.classify_claim_risks(text),
                "uncertain": bool(item.get("uncertain")),
                "span": _span_of(topic, ids),
            }
        )
    return facts


def _span_of(topic, segment_ids):
    """Approximate ms span for the chosen segments within the topic text.

    The topic carries only merged spans, so the exact per-segment ms come from
    the doc-level binding done by the caller (facts keep segment_ids; the
    caller re-binds exact ms via transcripts.TranscriptDocument.span()).
    """
    return


def extract_facts(doc, topics, *, api_key=None):
    """Model-assisted fact extraction per topic, then deterministic re-binding."""
    facts = []
    for topic in topics:
        if not topic["text"].strip():
            continue
        for fact in _extract_facts_for_topic(topic, api_key=api_key):
            fact_id = f"{doc.transcript_id}-f{len(facts) + 1:03d}"
            # deterministic re-binding: exact ms from the real segments
            try:
                fact["span_ms"] = doc.span(fact["segment_ids"])
            except T.TranscriptError:
                continue  # a fact referencing unknown segments is dropped, never guessed
            fact["fact_id"] = fact_id
            fact["topic_id"] = topic["topic_id"]
            fact["corroboration_required"] = T.corroboration_required(doc, fact["risk_flags"])
            facts.append(fact)
    return facts


# ---------- candidate angle discovery (harness B9) ----------

_ANGLES_PROMPT = """Ти си редакционен асистент. От доказателствените факти по-долу
предложи до 4 РЕАЛНИ кандидат-ъгъла за новина. Не измисляй теми: всеки ъгъл
трябва да има конкретна новост от фактите. Ако материалът няма поне 3
правдоподобни ъгъла, предложи само тези, които има - не пълни с изкуствени.

ВърНИ СТРОГО JSON:
{{"angles": [{{"angle_id": "...", "title": "...", "new_proposition": "...",
"fact_ids": ["..."], "reason": "...", "veto": false, "semantic_reason": "",
"semantic_status": "", "research_questions": []}}]}}

- semantic_status: "" | PUBLISHABLE_ANGLE | POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH
- акоsemantic_status е POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH -> задължително research_questions
- veto=true изисква semantic_reason
- не повтаряй заглавието в new_proposition

ФАКТИ:
{facts}
"""


def propose_angles(facts, *, max_angles=4):
    """Model proposals; validation/ranking stays in angles.assess_angles."""
    if not facts:
        return []
    listing = "\n".join(
        f"- {f['fact_id']} [{','.join(f['risk_flags']) or 'без рискове'}]: {f['text']}"
        for f in facts
    )
    prompt = _ANGLES_PROMPT.format(facts=listing)
    raw, _meta = gen.call_model(
        prompt, api_key=os.environ.get("GEMINI_API_KEY", "") or None, timeout=120, role="judge"
    )
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    valid = {f["fact_id"] for f in facts}
    out = []
    for item in (payload.get("angles") or [])[:max_angles]:
        refs = [x for x in (item.get("fact_ids") or []) if x in valid]
        if not refs or not (item.get("title") or "").strip():
            continue
        angle = {k: v for k, v in item.items() if v not in (None, "")}
        angle["fact_ids"] = refs
        out.append(angle)
    return out
