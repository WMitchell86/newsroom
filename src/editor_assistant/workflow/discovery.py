"""Generic transcript discovery (M2S Track T): segments -> facts -> angles.

V2 corrective pass (semantic audit findings A-H): boundary-first topic
segmentation, labeled fact binding + entailment verification, strict
proposal/assessment split, procedural-scope guard, batch repeated-agenda
context, real readiness invocation.

Generic machinery only: no committee, agenda item, person, number, or
expected outcome is ever encoded. All patterns are language-generic BG
agenda/procedure cues.
"""

from __future__ import annotations

import json
import os
import re

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import angles as _angles_mod
from editor_assistant.workflow import transcripts as T

TOPIC_FALLBACK_LABEL = "тема без разпознат дневен ред"
MAX_TOPICS_DEFAULT = 12
INSUFFICIENT_ANGLES = "INSUFFICIENT_CANDIDATE_ANGLES"
PIPELINE_VERSION = "transcript-discovery-v2"

# V2 ordinals: all common BG spellings + digit forms. Generic agenda
# morphology, never entity-specific.
_ORDINALS = (
    r"първа|първо|1-ва|1ва|1-во",
    r"втора|второ|2-ра|2ра|2-ро",
    r"трета|трето|3-та|3та",
    r"четвърта|четвърто|4-та|4та",
    r"пета|пето|5-та|5та",
    r"шеста|шесто|6-та|6та",
    r"седма|седмо|7-ма|7ма",
    r"осма|осмо|8-ма|8ма",
    r"девета|девето|9-та|9та",
    r"десета|десето|10-та|10та",
)

_AGENDA_CUE = re.compile(
    r"точка\s*(?:" + "|".join(_ORDINALS) + r"|\d+)"
    r"|(?:^|[\s\u201e\u201c\"'(\-–—.:;!?])"
    r"(?:" + "|".join(_ORDINALS) + r")\s+точка"
    r"|дневен\s+ред|следваща(?:та)?\s+точка|последна(?:та)?\s+точка"
    r"|преминаваме\s+към|по\s+следващата\s+точка"
    r"|(?:^|[\s\u201e\u201c\"'(\-–—.:;!?])следва(?:щата)?\b"
    r"|(?:^|[\s\u201e\u201c\"'(\-–—.:;!?])продължаваме\b",
    re.IGNORECASE,
)


def _segment_agenda_hits(text):
    """All agenda-boundary match spans inside one raw segment text."""
    return [m for m in _AGENDA_CUE.finditer(text or "")]


# ---------- topic segmentation V2 (audit finding A) ----------


def segment_topics(doc, *, max_topics=MAX_TOPICS_DEFAULT):
    """Boundary-first segmentation: detect agenda cues on RAW segments, then
    normalize overlap only INSIDE each topic (V2 flow).

    Raw SRT segments -> boundary detection on full segment text (any
    position, never just [:120]) -> overlap normalization inside each
    topic -> topic text. Rolling-caption merging can no longer destroy
    the boundary surface.
    """
    boundaries = set()
    for idx, seg in enumerate(doc.segments):
        if _segment_agenda_hits(seg.raw_text):
            boundaries.add(idx)
    groups = []
    current = []
    for idx, seg in enumerate(doc.segments):
        if idx in boundaries and current:
            groups.append(current)
            current = []
        current.append(seg)
        if len(groups) + (1 if current else 0) >= max_topics and idx + 1 < len(doc.segments):
            # cap: remaining segments attach to last group
            rest = list(doc.segments[idx + 1 :])
            current.extend(rest)
            break
    if current:
        groups.append(current)

    out = []
    for i, segs in enumerate(groups, start=1):
        spans = T.normalize_overlap_segments(segs)
        label_cue = None
        for span in spans:
            hits = _segment_agenda_hits(span["text"])
            if hits:
                pos = hits[0].start()
                label_cue = span["text"][max(0, pos - 20) : pos + 70].strip()[:90]
                break
        seg_ids = [sid for s in spans for sid in s["segment_ids"]]
        out.append(
            {
                "topic_id": f"{doc.transcript_id}-t{i:02d}",
                "start_ms": spans[0]["start_ms"] if spans else segs[0].start_ms,
                "end_ms": spans[-1]["end_ms"] if spans else segs[-1].end_ms,
                "start": T._ms_to_clock(spans[0]["start_ms"] if spans else segs[0].start_ms),
                "end": T._ms_to_clock(spans[-1]["end_ms"] if spans else segs[-1].end_ms),
                "label": (
                    label_cue or (spans[0]["text"][:90] if spans else segs[0].raw_text[:90])
                ).strip(),
                "deterministic_boundary": label_cue is not None,
                "segment_ids": seg_ids,
                "text": " ".join(s["text"] for s in spans),
            }
        )
    if not out and doc.segments:
        spans = T.normalize_overlap(doc)
        out.append(
            {
                "topic_id": f"{doc.transcript_id}-t01",
                "start_ms": spans[0]["start_ms"] if spans else doc.segments[0].start_ms,
                "end_ms": spans[-1]["end_ms"] if spans else doc.segments[-1].end_ms,
                "start": T._ms_to_clock(
                    spans[0]["start_ms"] if spans else doc.segments[0].start_ms
                ),
                "end": T._ms_to_clock(spans[-1]["end_ms"] if spans else doc.segments[-1].end_ms),
                "label": TOPIC_FALLBACK_LABEL,
                "deterministic_boundary": False,
                "segment_ids": [s.segment_id for s in doc.segments],
                "text": " ".join(s["text"] for s in spans),
            }
        )
    return out


# ---------- model-assisted candidate fact extraction V2 (findings B, S5-S6) ----------

_FACTS_PROMPT = """Ти си редакционен асистент. По-долу е машинен транскрипт (автоматични
субтитри, с възможни ASR грешки) от една тема на заседание.

Извлечи САМО констатации, буквално изречени в транскрипта. Абсолютно
не добавяй факти от паметта или от интернет. 2-5 факта максимум; ако няма
поне 2 смислени, върни празен списък.

Всеки източников отрязък е изрично етикетиран. Фактът ТРЯБВА да сочи
точно тези отрязъци, чийто текст го подкрепя — съществуването на ID
не е обосноваване.

ВърНИ СТРОГО JSON:
{{"facts": [{{"text": "...", "segment_ids": ["..."], "risk_flags": ["final_decision|material_number|personal_or_org_name|exact_quote|negation_sensitive|legal_institutional_status"], "uncertain": false}}]}}

Правила:
- "segment_ids" задължително са от подадените етикетирани ID-та;
- не поправяй имена/числа по памет — маркирай risk_flags и uncertain;
- пренапиши минимално (нека изречението е четимо), но не променяй смисъла:
  същият деятел, същото отношение, същият решителен статус, същите числа,
  без обръщане на отрицания.

ТЕМА: {label}

ЕТИКЕТИРАНИ ИЗТОЧНИКОВИ ОТРЯЗЪЦИ:
{blocks}
"""


def _labeled_blocks(topic, doc):
    """Render topic segments as explicit [id | clock-range] labeled blocks (§5)."""
    by_id = {s.segment_id: s for s in doc.segments} if doc is not None else {}
    lines = []
    for sid in topic["segment_ids"]:
        seg = by_id.get(sid)
        if seg is None:
            continue
        lines.append(
            f"[segment_id={sid} | {T._ms_to_clock(seg.start_ms)}-{T._ms_to_clock(seg.end_ms)}]\n"
            f"{seg.raw_text}"
        )
    if not lines:
        return (topic.get("text") or "")[:6000]
    return "\n\n".join(lines)


def _extract_facts_for_topic(topic, doc=None, *, api_key=None, timeout=120):
    blocks = _labeled_blocks(topic, doc)
    id_line = ", ".join(topic["segment_ids"][:60])
    prompt = _FACTS_PROMPT.replace("{label}", topic["label"]).replace(
        "{blocks}", f"{blocks}\n\nID-та: {id_line}"
    )
    raw, _meta = gen.call_model(prompt, api_key=api_key, timeout=timeout, role="judge")
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        _extract_facts_for_topic.last_status = "NO_JSON"
        return []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        _extract_facts_for_topic.last_status = "INVALID_JSON"
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
                "span": None,
            }
        )
    _extract_facts_for_topic.last_status = "OK" if facts else "EMPTY_MODEL_OUTPUT"
    return facts


# Last per-topic outcome, so extract_facts can record *why* a topic produced no
# facts instead of silently reporting zero. "OK" means the model returned a
# usable JSON payload; NO_JSON/INVALID_JSON mean unusable output;
# EMPTY_MODEL_OUTPUT means valid JSON with no fact that binds to the topic.
_extract_facts_for_topic.last_status = "OK"


_NUM_WORDS = {
    "едно": "1",
    "една": "1",
    "един": "1",
    "две": "2",
    "два": "2",
    "двама": "2",
    "три": "3",
    "трима": "3",
    "четири": "4",
    "петима": "5",
    "четирима": "4",
    "пет": "5",
    "шест": "6",
    "седем": "7",
    "осем": "8",
    "девет": "9",
    "десет": "10",
    "единадесет": "11",
    "дванадесет": "12",
    "двадесет": "20",
    "тридесет": "30",
    "сто": "100",
    "хиляда": "1000",
    "хиляди": "1000",
    "милион": "1000000",
    "милиона": "1000000",
}

_BG_STOP = frozenset(
    [
        "е",
        "са",
        "си",
        "съм",
        "сте",
        "били",
        "била",
        "било",
        "беше",
        "бяха",
        "ще",
        "да",
        "се",
        "от",
        "на",
        "в",
        "с",
        "за",
        "към",
        "през",
        "под",
        "над",
        "между",
        "и",
        "или",
        "но",
        "ако",
        "че",
        "то",
        "това",
        "тези",
        "този",
        "тази",
        "които",
        "като",
        "със",
        "със",
        "при",
        "по",
        "о",
        "у",
        "а",
        "об",
        "още",
        "вече",
        "само",
        "много",
        "всички",
        "всяка",
        "всеки",
        "също",
        "какво",
        "каква",
        "какъв",
        "тук",
        "там",
        "тогава",
        "когато",
        "който",
        "която",
        "което",
    ]
)

_DECISION_STEMS = ("прие", "приет", "прием", "одобр", "отхвърл", "гласув", "подкреп")

_NAME_SEQ_RX = re.compile(r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+")
_DIGIT_RX = re.compile(r"\d+")
_WORD_RX = re.compile(r"[\w]+", re.UNICODE)
_NEG_RX = re.compile(r"\bне\s+\w+", re.IGNORECASE)


def _span_of(topic, segment_ids):
    return None


def _content_tokens(text):
    toks = _WORD_RX.findall((text or "").casefold())
    return [w for w in toks if len(w) > 2 and w not in _BG_STOP]


def _digits_norm(text):
    out = text or ""
    for word, digit in _NUM_WORDS.items():
        out = re.sub(rf"(?<!\w){word}(?!\w)", digit, out, flags=re.IGNORECASE)
    return out


def verify_fact_entailment(fact_text, support_texts):
    """Strict source-only entailment check (deterministic, generic)."""
    failures = []
    support_joined = " ".join(support_texts or [])
    fact_norm = _digits_norm(fact_text)
    support_norm = _digits_norm(support_joined)
    for digit in _DIGIT_RX.findall(fact_norm):
        if digit not in _DIGIT_RX.findall(support_norm):
            failures.append(f"wrong_number: {digit} not in support")
    fact_neg = bool(_NEG_RX.search(fact_text or ""))
    support_has_neg = "не" in _WORD_RX.findall(support_joined.casefold())
    if fact_neg and not support_has_neg:
        failures.append("negation_reversal: fact negates what support affirms")
    if support_has_neg and not fact_neg:
        for stem in _DECISION_STEMS:
            if stem in (fact_text or "").casefold():
                pat = rf"\bне\s+\w*{stem[:4]}"
                if re.search(pat, support_joined, re.IGNORECASE):
                    failures.append("negation_reversal: support negates decision")
                    break
    fact_dec = [s for s in _DECISION_STEMS if s in (fact_text or "").casefold()]
    slow = support_joined.casefold()
    if fact_dec and not any(slow.count(d[:4]) for d in fact_dec):
        failures.append("wrong_decision_status: no decision stem in support")
    for name in _NAME_SEQ_RX.findall(fact_text or ""):
        if name.casefold() not in support_joined.casefold():
            failures.append(f"wrong_actor: {name!r} absent from support")
    fact_tokens = _content_tokens(fact_norm)
    support_tokens = set(_content_tokens(support_norm))
    coverage = 0.0
    if fact_tokens:
        hits = 0
        for tok in fact_tokens:
            if tok in support_tokens:
                hits += 1
                continue
            for s in support_tokens:
                if len(s) > 4 and (s.startswith(tok[:5]) or tok.startswith(s[:5])):
                    hits += 1
                    break
        coverage = hits / len(fact_tokens)
        if coverage < 0.40:
            failures.append(f"unsupported_paraphrase: coverage {coverage:.2f} < 0.40")
    out = {"entailed": not failures, "failures": failures}
    out["coverage"] = round(coverage, 3)
    return out


_ENTAIL_JUDGE_PROMPT = """Ти си строг съдия. Отговори САМО с JSON.
ФАКТ: @@FACT@@
ОТРЯЗЪЦИ (единствен източник):
@@SUPPORT@@
Върни СТРОГО: {{"entailed": true|false, "reason": "..."}}
true САМО ако всяко твърдение (деятел, отношение, статус, числа,
отрицания) е изрично подкрепено. Без външни знания.
"""


def judge_fact_with_model(fact_text, support_texts, *, api_key=None, timeout=120):
    """Optional model cross-check; None when unavailable (offline-safe)."""
    try:
        raw, _m = gen.call_model(
            _ENTAIL_JUDGE_PROMPT.replace("@@FACT@@", fact_text).replace(
                "@@SUPPORT@@", "\n---\n".join(support_texts or [])
            ),
            api_key=api_key,
            timeout=timeout,
            role="judge",
        )
    except (RuntimeError, ValueError, OSError):
        return None
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload.get("entailed"), bool):
        return None
    return {"entailed": payload["entailed"], "reason": str(payload.get("reason", ""))[:300]}


# ---------- procedural scope contract (S10) ----------

PROCEDURAL_STATUSES = (
    "PROPOSED",
    "DISCUSSED",
    "COMMITTEE_SUPPORTED",
    "COMMITTEE_REJECTED",
    "COUNCIL_ADOPTED",
    "ADMINISTRATIVE_ACTION",
    "UNKNOWN",
)

_COMMITTEE_RX = re.compile(r"комиси\w*|кмет", re.IGNORECASE)
_COUNCIL_RX = re.compile(r"общинск\w*\s+съвет|съветът|съветник", re.IGNORECASE)
_SUPPORT_RX = re.compile(r"прие\w*|одобр\w*|подкреп\w*|приет\w*", re.IGNORECASE)
_REJECT_RX = re.compile(r"отхвърл\w*|не\s+прие|не\s+подкрепи", re.IGNORECASE)
_PROPOSE_RX = re.compile(r"предлагам|предложение|проект|докладна|внасям|внесен\w*", re.IGNORECASE)
_DISCUSS_RX = re.compile(r"обсъди\w*|разгледа\w*|дебат|изслуша\w*|коментирам", re.IGNORECASE)

_SCOPE_UPGRADE_RX = re.compile(
    r"общин\w*\s+съвет\w*\s+(?:прие|одобри|реши)|община\w*\s+(?:прие|одобри)|"
    r"съветът\s+(?:прие|одобри)",
    re.IGNORECASE,
)


def infer_procedural_status(fact_text):
    """Compact source-grounded procedural status for a decision/action fact."""
    text = fact_text or ""
    if _REJECT_RX.search(text) and _COMMITTEE_RX.search(text):
        return "COMMITTEE_REJECTED"
    if _SUPPORT_RX.search(text) and _COMMITTEE_RX.search(text):
        return "COMMITTEE_SUPPORTED"
    if _SUPPORT_RX.search(text) and _COUNCIL_RX.search(text):
        return "COUNCIL_ADOPTED"
    if _PROPOSE_RX.search(text):
        return "PROPOSED"
    if _DISCUSS_RX.search(text):
        return "DISCUSSED"
    if _SUPPORT_RX.search(text):
        return "COMMITTEE_SUPPORTED"
    return "UNKNOWN"


def check_scope_entailment(angle_title, angle_proposition, supporting_fact_texts):
    """Angle must not strengthen institutional status beyond evidence."""
    angle = f"{angle_title or ''} {angle_proposition or ''}"
    if _SCOPE_UPGRADE_RX.search(angle):
        support = " ".join(supporting_fact_texts or [])
        if _SCOPE_UPGRADE_RX.search(support):
            return {"ok": True, "reason": "council-level claim has council-level support"}
        stats = [infer_procedural_status(t) for t in (supporting_fact_texts or [])]
        if "COUNCIL_ADOPTED" in stats:
            return {"ok": True, "reason": "supporting facts carry council-adopted status"}
        return {
            "ok": False,
            "reason": "angle claims council/municipality adoption but support is committee-stage",
        }
    return {"ok": True, "reason": "no institutional upgrade in angle wording"}


def extract_facts(doc, topics, *, api_key=None, use_model_judge=True):
    """Model-assisted extraction per topic + deterministic entailment gate.

    Survivors carry fact_grounding_status=GROUNDED, supporting_segment_ids,
    entailment coverage, exact span_ms, and procedural status. Ungrounded
    candidates are DROPPED (never repaired); recorded on extract_facts.dropped.
    Topics that produced nothing are NOT silently reported as zero facts: every
    one is recorded on extract_facts.skipped_topics with its reason
    (MODEL_CALL_FAILED / NO_JSON / INVALID_JSON / EMPTY_MODEL_OUTPUT /
    EMPTY_TOPIC_TEXT), so a quota outage is distinguishable from an empty topic.
    """
    facts = []
    dropped = []
    skipped = []
    by_id = {s.segment_id: s for s in doc.segments}
    for topic in topics:
        if not topic["text"].strip():
            skipped.append({"topic_id": topic["topic_id"], "reason": "EMPTY_TOPIC_TEXT"})
            continue
        try:
            try:
                cands = _extract_facts_for_topic(topic, doc, api_key=api_key)
            except TypeError:
                cands = _extract_facts_for_topic(topic, api_key=api_key)
        except (RuntimeError, ValueError, OSError) as exc:  # quota/offline must not kill batch
            skipped.append(
                {
                    "topic_id": topic["topic_id"],
                    "reason": f"MODEL_CALL_FAILED: {type(exc).__name__}",
                }
            )
            continue
        status = getattr(_extract_facts_for_topic, "last_status", "OK")
        if status != "OK":
            skipped.append({"topic_id": topic["topic_id"], "reason": status})
        for cand in cands:
            sup = [by_id[s].raw_text for s in cand["segment_ids"] if s in by_id]
            check = verify_fact_entailment(cand["text"], sup)
            if not check["entailed"]:
                dropped.append(
                    {
                        **cand,
                        "fact_grounding_status": "DROPPED_UNGROUNDED",
                        "grounding_failures": check["failures"],
                    }
                )
                continue
            if use_model_judge and check["coverage"] < 0.60:
                # model cross-check only for borderline facts; high-coverage
                # deterministic passes skip the extra judge call (V1 quota lesson)
                verdict = judge_fact_with_model(cand["text"], sup, api_key=api_key)
                if verdict is not None and not verdict["entailed"]:
                    dropped.append(
                        {
                            **cand,
                            "fact_grounding_status": "DROPPED_BY_JUDGE",
                            "grounding_failures": [verdict["reason"]],
                        }
                    )
                    continue
            try:
                span_ms = doc.span(cand["segment_ids"])
            except T.TranscriptError:
                dropped.append(
                    {
                        **cand,
                        "fact_grounding_status": "DROPPED_UNKNOWN_SEGMENTS",
                        "grounding_failures": ["unknown segment ids"],
                    }
                )
                continue
            facts.append(
                {
                    "text": cand["text"],
                    "segment_ids": cand["segment_ids"],
                    "supporting_segment_ids": list(cand["segment_ids"]),
                    "risk_flags": cand["risk_flags"],
                    "uncertain": cand["uncertain"],
                    "span": None,
                    "span_ms": span_ms,
                    "fact_id": f"{doc.transcript_id}-f{len(facts) + 1:03d}",
                    "topic_id": topic["topic_id"],
                    "corroboration_required": T.corroboration_required(doc, cand["risk_flags"]),
                    "fact_grounding_status": "GROUNDED",
                    "entailment_coverage": check["coverage"],
                    "procedural_status": infer_procedural_status(cand["text"]),
                }
            )
    extract_facts.dropped = dropped
    extract_facts.skipped_topics = skipped
    return facts


extract_facts.dropped = []
extract_facts.skipped_topics = []


# ---------- candidate angle discovery V2: proposal/assessment split (S7-S9) ----------

_ANGLES_PROMPT = """Ти си редакционен асистент. От доказателствените факти по-долу
предложи до 4 РЕАЛНИ кандидат-ъгъла за новина. Не измисляй теми: всеки ъгъл
трябва да има конкретна новост от фактите. Ако материалът няма поне 3
правдоподобни ъгъла, предложи само тези, които има - не пълни с изкуствени.

ВърНИ СТРОГО JSON:
{{"angles": [{{"angle_id": "...", "title": "...", "new_proposition": "...",
"fact_ids": ["..."], "reason": "...", "possible_research_questions": []}}]}}}

СТРОГО ЗАБРАНЕНО е да извеждаш: semantic_status, veto, semantic_reason,
rubric scores. Всяко такова поле в отговора се игнорира.
- не повтаряй заглавието в new_proposition

ФАКТИ:
{facts}
"""


def propose_angles(facts, *, max_angles=4):
    """Model proposals only; authoritative judgment lives in assess_candidates."""
    if not facts:
        return []
    listing = "\n".join(
        f"- {f['fact_id']} [{','.join(f['risk_flags']) or 'без рискове'}]: {f['text']}"
        for f in facts
    )
    prompt = _ANGLES_PROMPT.replace("{facts}", listing)
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
        for _f in ("semantic_status", "veto", "semantic_reason", "scores", "total"):
            angle.pop(_f, None)
        angle["fact_ids"] = refs
        angle["proposal_only"] = True
        out.append(angle)
    return out


# ---------- independent candidate assessment V2 (S8-S9, S12) ----------

_CONCRETE_RX = re.compile(
    r"създава|създаване|нова\s+услуга|нов\s+обект|финансиране|средства\s+за|"
    r"данъц\w*|такс\w*|цен\w*\s+на\s+услуги|без\s+промяна|намалява|увеличава|"
    r"засегнати|получател\w*|жител\w*|граждан\w*|против|въздържал|разногласие|"
    r"спор|необичайн\w*|за\s+пръв\s+път|спешн\w*|авари\w*|затваря\w*",
    re.IGNORECASE,
)
_WRAPPER_RX = re.compile(
    r"прие(?:\s+\w+){0,3}\s+отчет|прие(?:\s+\w+){0,3}\s+доклад|"
    r"одобри(?:\s+\w+){0,3}\s+отчет|обсъди\s+бюджет|"
    r"дневен\s+ред\s+(?:е\s+)?приет|годишен\s+отчет|доклад\s+за\s+изпълнение",
    re.IGNORECASE,
)
_MONEY_RX = re.compile(
    r"\d[\d\s.,]*\s*(?:млн|млрд|хил|лев[а-я]*|евро)|\bлв\b|бюджет\w*|финансиране",
    re.IGNORECASE,
)
_PEOPLE_RX = re.compile(
    r"жител\w*|граждан\w*|учениц\w*|студент\w*|пенсионер\w*|семейств\w*|"
    r"деца|пациент\w*|работник\w*|служител\w*",
    re.IGNORECASE,
)
_SPLIT_RX = re.compile(r"против|въздържал|разделен|спор|не\s+единодуш", re.IGNORECASE)
_UNUSUAL_RX = re.compile(
    r"за\s+пръв\s+път|необичайн\w*|изненад\w*|рекорд\w*|спешн\w*|стран\w*",
    re.IGNORECASE,
)

_ROUTINE_VETO_RX = re.compile(
    r"^(?:прие|одобри)\s+(?:годишния\s+)?(?:отчет|доклад)\b.{0,80}$",
    re.IGNORECASE,
)


def _deterministic_scores(proposal, facts_by_id):
    """Evidence-surface scores for all rubric criteria (generic heuristics)."""
    refs = [f for fid in proposal.get("fact_ids", []) if (f := facts_by_id.get(fid))]
    joined = " ".join(f["text"] for f in refs)
    prop = f"{proposal.get('title', '')} {proposal.get('new_proposition', '')}"
    has_novelty = bool(_angles_mod.NOVELTY_CUE.search(joined))
    concrete = bool(_CONCRETE_RX.search(joined) or _CONCRETE_RX.search(prop))
    wrapper_only = bool(_WRAPPER_RX.search(prop) or _ROUTINE_VETO_RX.search(prop.strip()))
    wrapper_only = wrapper_only and not concrete

    def _sc(criterion, score, reason):
        return {"score": score, "reason": reason, "fact_ids": list(proposal.get("fact_ids", []))}

    scores = {}
    if concrete and has_novelty:
        scores["concrete_change"] = _sc(
            "concrete_change", 2, "конкретна новост в подкрепящите факти"
        )
    elif has_novelty:
        scores["concrete_change"] = _sc("concrete_change", 1, "решение без конкретизирана новост")
    else:
        scores["concrete_change"] = _sc("concrete_change", 0, "няма подкрепа от извлечените факти")
    if _PEOPLE_RX.search(joined):
        scores["people_impact"] = _sc("people_impact", 1, "засегната група в подкрепящите факти")
    else:
        scores["people_impact"] = _sc("people_impact", 0, "няма подкрепа от извлечените факти")
    if _MONEY_RX.search(joined):
        scores["money_infrastructure_services"] = _sc(
            "money_infrastructure_services", 1, "пари/инфраструктура в подкрепящите факти"
        )
    else:
        scores["money_infrastructure_services"] = _sc(
            "money_infrastructure_services", 0, "няма подкрепа от извлечените факти"
        )
    if _SPLIT_RX.search(joined):
        scores["different_positions"] = _sc("different_positions", 1, "различни позиции във вота")
    else:
        scores["different_positions"] = _sc(
            "different_positions", 0, "няма подкрепа от извлечените факти"
        )
    if _UNUSUAL_RX.search(joined):
        scores["unexpected_fact"] = _sc("unexpected_fact", 1, "необичаен елемент във фактите")
    else:
        scores["unexpected_fact"] = _sc("unexpected_fact", 0, "няма подкрепа от извлечените факти")
    scores["strong_quote"] = _sc("strong_quote", 0, "авто-субтитри: цитатите искат проверка")
    if concrete and has_novelty:
        scores["burgas_novelty"] = _sc("burgas_novelty", 2, "конкретна местна новост от фактите")
    elif has_novelty:
        scores["burgas_novelty"] = _sc("burgas_novelty", 1, "новост без конкретика")
    else:
        scores["burgas_novelty"] = _sc("burgas_novelty", 0, "няма подкрепа от извлечените факти")
    return scores, {"has_novelty": has_novelty, "concrete": concrete, "wrapper_only": wrapper_only}


_ASSESS_PROMPT = """Ти си независим редакционен оценител. Оценяваш ЕДИН кандидат-ъгъл
САМО по подкрепящите го факти. Отговори САМО с JSON.

КАНДИДАТ:
заглавие: @@TITLE@@
ново твърдение: @@PROP@@
обосновка на предложилия: @@REASON@@

ПОДКРЕПЯЩИ ФАКТИ (единствена опора):
@@FACTS@@

КРИТЕРИИ (всеки 0=няма, 1=ограничено, 2=силно; положителна оценка иска reason и fact_ids от опората):
concrete_change, people_impact, money_infrastructure_services, different_positions,
unexpected_fact, strong_quote, burgas_novelty

Различавай "темата звучи важно" от "има конкретна нова новина". Рутинни процедурни
материали (приемане на отчет/доклад, одобряване на дневен ред, обсъждане без
решение) са NO_PUBLISHABLE_ANGLE дори да споменават бюджет/граждани/пари.
Потенциално значимо, но непълно/непроверено развитие е POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH
със задължителни конкретни research_questions.

Върни СТРОГО: {{"scores": {{"concrete_change": {{"score": 0, "reason": "...", "fact_ids": [...]}}}}, "semantic_status": "PUBLISHABLE_ANGLE|POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH|NO_PUBLISHABLE_ANGLE", "semantic_reason": "...", "research_questions": []}}
"""


def _model_assess(proposal, refs, *, api_key=None, timeout=120):
    listing = "\n".join(f"- {f['fact_id']}: {f['text']}" for f in refs)
    try:
        raw, _m = gen.call_model(
            _ASSESS_PROMPT.replace("@@TITLE@@", proposal.get("title", ""))
            .replace("@@PROP@@", proposal.get("new_proposition", ""))
            .replace("@@REASON@@", proposal.get("reason", ""))
            .replace("@@FACTS@@", listing),
            api_key=api_key,
            timeout=timeout,
            role="judge",
        )
    except (RuntimeError, ValueError, OSError):
        return None
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    scores = payload.get("scores")
    status = payload.get("semantic_status")
    if not isinstance(scores, dict) or set(scores) != set(_angles_mod.CRITERIA):
        return None
    if status not in (_angles_mod.VIABLE, _angles_mod.NEEDS_RESEARCH, _angles_mod.NOT_VIABLE):
        return None
    valid = {f["fact_id"] for f in refs}
    cleaned = {}
    for crit in _angles_mod.CRITERIA:
        item = scores.get(crit)
        if not isinstance(item, dict) or item.get("score") not in (0, 1, 2):
            return None
        sup = item.get("fact_ids", [])
        if item["score"] and (not sup or any(r not in valid for r in sup)):
            return None
        cleaned[crit] = {
            "score": item["score"],
            "reason": str(item.get("reason", ""))[:300],
            "fact_ids": list(sup) if sup else [],
        }
    return {
        "scores": cleaned,
        "semantic_status": status,
        "semantic_reason": str(payload.get("semantic_reason", ""))[:400],
        "research_questions": [
            q for q in (payload.get("research_questions") or []) if isinstance(q, str) and q.strip()
        ][:6],
    }


def assess_candidates(proposals, facts, *, api_key=None, use_model_judge=True, repeated=None):
    """Independent assessment pass: deterministic scores + scope guard.

    Returns (candidates, diagnostics) where candidates are ready for
    angles.assess_angles (all criteria scored, semantic fields authored by
    the ASSESSOR, never the proposer) and diagnostics records scope
    downgrades, routine vetoes, and repeated-agenda notes.
    """
    facts_by_id = {f["fact_id"]: f for f in facts}
    candidates, diagnostics = [], {"scope_downgrades": [], "routine_vetoes": [], "assessor": []}
    for proposal in proposals or []:
        refs = [facts_by_id[fid] for fid in proposal.get("fact_ids", []) if fid in facts_by_id]
        if not refs:
            continue
        det_scores, signals = _deterministic_scores(proposal, facts_by_id)
        verdict = None
        if use_model_judge:
            verdict = _model_assess(proposal, refs, api_key=api_key)
        if verdict is not None:
            scores, sem_status = verdict["scores"], verdict["semantic_status"]
            sem_reason = verdict["semantic_reason"]
            research_qs = verdict["research_questions"]
            assessor = "model"
        else:
            scores = det_scores
            research_qs = list(proposal.get("possible_research_questions") or [])[:6]
            if signals["wrapper_only"] and not signals["concrete"]:
                sem_status = _angles_mod.NOT_VIABLE
                sem_reason = "рутинен процедурен материал без конкретна новост в опората"
                diagnostics["routine_vetoes"].append(proposal.get("angle_id"))
            elif not signals["has_novelty"]:
                sem_status = _angles_mod.NOT_VIABLE
                sem_reason = "няма конкретна новост, изразима от подкрепящите факти"
            elif signals["concrete"]:
                sem_status = _angles_mod.VIABLE
                sem_reason = "конкретна новост, подкрепена от фактите"
            else:
                sem_status = _angles_mod.NEEDS_RESEARCH
                sem_reason = "възможна новост, но липсват конкретика/проверка"
                if not research_qs:
                    research_qs = ["Кое точно е новото развитие и как се потвърждава независимо?"]
            assessor = "deterministic"
        scope = check_scope_entailment(
            proposal.get("title", ""),
            proposal.get("new_proposition", ""),
            [f["text"] for f in refs],
        )
        if not scope["ok"]:
            sem_status = _angles_mod.NEEDS_RESEARCH
            sem_reason = scope["reason"] + "; " + sem_reason
            research_qs = list(
                dict.fromkeys(
                    research_qs + ["Кой орган точно е взел решението и с какъв акт се потвърждава?"]
                )
            )
            diagnostics["scope_downgrades"].append(proposal.get("angle_id"))
        if repeated and (repeated.get("repeated_agenda_item")) and sem_status == _angles_mod.VIABLE:
            for crit in ("concrete_change", "burgas_novelty"):
                if scores[crit]["score"] == 2:
                    scores[crit] = {
                        **scores[crit],
                        "score": 1,
                        "reason": scores[crit]["reason"] + "; повторна точка без нов елемент",
                    }
        cand = {
            "angle_id": proposal.get("angle_id"),
            "title": proposal.get("title"),
            "new_proposition": proposal.get("new_proposition"),
            "fact_ids": [f["fact_id"] for f in refs],
            "reason": proposal.get("reason", ""),
            "scores": scores,
            "semantic_status": sem_status,
            "semantic_reason": sem_reason,
            "research_questions": research_qs,
        }
        diagnostics["assessor"].append({"angle_id": cand["angle_id"], "assessor": assessor})
        candidates.append(cand)

    # S12: prefer concrete development over procedural wrapper when both viable
    def _rank_key(c):
        conc = 1 if _CONCRETE_RX.search(f"{c['title']} {c['new_proposition']}") else 0
        wrap = 1 if _WRAPPER_RX.search(f"{c['title']} {c['new_proposition']}") else 0
        return (conc - wrap, sum(v["score"] for v in c["scores"].values()))

    candidates.sort(key=_rank_key, reverse=True)
    return candidates, diagnostics


# ---------- batch-level repeated-agenda context (S11) ----------


def topic_fingerprint(text):
    """Generic session fingerprint: normalized content-token multiset hash."""
    import hashlib

    toks = sorted(_content_tokens(_digits_norm(text)))
    return hashlib.sha256(" ".join(toks).encode("utf-8")).hexdigest()[:16]


def batch_repeated_context(transcript_fact_texts):
    """Map fingerprint -> {seen_in_recordings, count} over the batch."""
    index = {}
    for vid, texts in (transcript_fact_texts or {}).items():
        for text in texts:
            fp = topic_fingerprint(text)
            index.setdefault(fp, set()).add(vid)
    return {fp: {"seen_in_recordings": sorted(v), "count": len(v)} for fp, v in index.items()}


# ---------- evidence packet + real readiness (S13) ----------


def build_evidence_packet(doc, facts, assessment):
    """Packet-shaped dict so readiness.assess_readiness() runs for real."""
    packet = {
        "facts": [{"id": f["fact_id"], "text": f["text"], "scope": "current_event"} for f in facts],
        "source_type": "transcript",
        "source_url": doc.source_url or f"https://www.youtube.com/watch?v={doc.transcript_id}",
        "source_headline": doc.title or doc.transcript_id,
        "source_text": " ".join(f["text"] for f in facts),
        "editorial_assessment": assessment,
    }
    return packet


def run_readiness(packet, *, mode=None):
    """Invoke the REAL readiness orchestrator (S13); no drafting."""
    from editor_assistant.workflow import modes as _modes_mod
    from editor_assistant.workflow import readiness as _readiness_mod

    if mode is None:
        mode = _modes_mod.suggest_mode(packet)["suggested_mode"]
    return _readiness_mod.assess_readiness(packet, mode=mode)
