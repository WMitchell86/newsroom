"""Timestamped transcript foundation (M2S Track T).

Raw SRT becomes the authoritative machine input (audit B2): auto-captions are
discovery evidence with exact time provenance, not automatically perfect
factual authority. Contracts here:

* `parse_srt` - deterministic standard SRT parsing (sequence, start, end, text);
* `TranscriptDocument` - segments with ms precision + trust level vocabulary;
* `normalize_overlap` - time-aware dedup of auto-caption overlap, where every
  normalized span keeps binding back to original segment ids/ms (B4); the raw
  transcript is never mutated;
* high-risk claim classification for AUTO_CAPTION material (B6): final
  decisions, material numbers, names, exact quotes, negation-sensitive claims
  need corroboration before publication - while still being enough to
  *discover* the story and formulate research questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TRUST_AUTO_CAPTION = "AUTO_CAPTION"
TRUST_HUMAN_TRANSCRIPT = "HUMAN_TRANSCRIPT"
TRUST_HUMAN_VERIFIED = "HUMAN_VERIFIED"
TRUST_OFFICIAL_VERBATIM = "OFFICIAL_VERBATIM"

TRUST_LEVELS = (
    TRUST_AUTO_CAPTION,
    TRUST_HUMAN_TRANSCRIPT,
    TRUST_HUMAN_VERIFIED,
    TRUST_OFFICIAL_VERBATIM,
)

# Trust levels allowed to carry high-risk claims without corroboration.
STRONG_TRUST = (TRUST_HUMAN_VERIFIED, TRUST_OFFICIAL_VERBATIM)


class TranscriptError(ValueError):
    pass


# ---------- SRT parsing (harness B3) ----------

_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _to_ms(h, m, s, ms):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0")[:3])


def parse_srt(text):
    """Parse standard SRT into cue dicts; malformed blocks raise.

    Preserves: sequence number, start/end timestamps (exact ms), caption text.
    """
    cues = []
    blocks = re.split(r"\n\s*\n", (text or "").strip())
    for index, block in enumerate(blocks, start=1):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        seq = None
        time_line = None
        text_lines = []
        if len(lines) >= 2 and _TIME_RE.search(lines[1]):
            seq, time_line, text_lines = lines[0], lines[1], lines[2:]
        elif _TIME_RE.search(lines[0]):
            time_line, text_lines = lines[0], lines[1:]
        else:
            raise TranscriptError(f"SRT block {index} has no timestamp line: {block[:60]!r}")
        match = _TIME_RE.search(time_line)
        start = _to_ms(*match.group(1, 2, 3, 4))
        end = _to_ms(*match.group(5, 6, 7, 8))
        if end < start:
            raise TranscriptError(f"SRT block {index} ends before it starts")
        text = re.sub(r"\s+", " ", " ".join(text_lines)).strip()
        if not text:
            continue
        cues.append(
            {
                "cue_index": int(seq) if seq and seq.strip().isdigit() else index,
                "start_ms": start,
                "end_ms": end,
                "raw_text": text,
            }
        )
    if not cues:
        raise TranscriptError("no SRT cues found")
    return cues


# ---------- document ----------


@dataclass
class TranscriptSegment:
    segment_id: str
    cue_index: int
    start_ms: int
    end_ms: int
    raw_text: str
    normalized_text: str


@dataclass
class TranscriptDocument:
    transcript_id: str
    source_url: str
    title: str
    language: str
    origin: str
    trust_level: str
    segments: list = field(default_factory=list)

    def to_dict(self):
        return {
            "transcript_id": self.transcript_id,
            "source_url": self.source_url,
            "title": self.title,
            "language": self.language,
            "origin": self.origin,
            "trust_level": self.trust_level,
            "segments": [
                {
                    "segment_id": s.segment_id,
                    "cue_index": s.cue_index,
                    "start_ms": s.start_ms,
                    "end_ms": s.end_ms,
                    "raw_text": s.raw_text,
                    "normalized_text": s.normalized_text,
                }
                for s in self.segments
            ],
        }

    def span(self, segment_ids):
        """[start_ms, end_ms] covering the given segments (provenance binding)."""
        chosen = [s for s in self.segments if s.segment_id in set(segment_ids)]
        if not chosen:
            raise TranscriptError("span() over unknown segment ids")
        return [min(s.start_ms for s in chosen), max(s.end_ms for s in chosen)]


def _ms_to_clock(ms):
    s, ms = divmod(int(ms), 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def load_srt(
    text,
    *,
    transcript_id,
    source_url="",
    title="",
    language="bg",
    origin="youtube_auto_caption",
    trust_level=TRUST_AUTO_CAPTION,
):
    """Raw SRT text -> TranscriptDocument with id/ms provenance per segment."""
    if trust_level not in TRUST_LEVELS:
        raise TranscriptError(f"bad trust_level: {trust_level!r} (use {TRUST_LEVELS})")
    doc = TranscriptDocument(
        transcript_id=transcript_id,
        source_url=source_url,
        title=title,
        language=language,
        origin=origin,
        trust_level=trust_level,
    )
    for cue in parse_srt(text):
        doc.segments.append(
            TranscriptSegment(
                segment_id=f"{transcript_id}-s{cue['cue_index']:04d}",
                cue_index=cue["cue_index"],
                start_ms=cue["start_ms"],
                end_ms=cue["end_ms"],
                raw_text=cue["raw_text"],
                normalized_text=cue["raw_text"],
            )
        )
    return doc


# ---------- time-aware overlap normalization (harness B4) ----------

_WORD = re.compile(r"[\w'’-]+", re.UNICODE)


def _tail_head_overlap(a, b, max_words=6):
    """Word count where the tail of `a` equals the head of `b` (auto-caption echo)."""
    wa, wb = _WORD.findall(a.lower()), _WORD.findall(b.lower())
    for size in range(min(max_words, len(wa), len(wb)), 0, -1):
        if wa[-size:] == wb[:size]:
            return size
    return 0


def normalize_overlap(doc):
    """Merge overlapping caption echoes into flowing normalized spans.

    Returns spans: {text, segment_ids, start_ms, end_ms}. Each span maps back
    to one or more original segments; the document itself is not mutated.
    Non-adjacent overlaps are never merged.
    """
    spans = []
    current = None
    for seg in doc.segments:
        text = seg.normalized_text
        if current is not None and seg.start_ms <= current["end_ms"]:
            overlap = _tail_head_overlap(current["text"], text)
            merged = text
            if overlap:
                words = _WORD.findall(text)
                kept = words[overlap:]
                merged = " ".join(kept) if kept else ""
            if merged:
                joined = f"{current['text']} {merged}".strip()
                current = {
                    "text": joined,
                    "segment_ids": current["segment_ids"] + [seg.segment_id],
                    "start_ms": current["start_ms"],
                    "end_ms": max(current["end_ms"], seg.end_ms),
                }
            else:
                current["segment_ids"].append(seg.segment_id)
                current["end_ms"] = max(current["end_ms"], seg.end_ms)
            continue
        if current is not None:
            spans.append(current)
        current = {
            "text": text,
            "segment_ids": [seg.segment_id],
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
        }
    if current is not None:
        spans.append(current)
    return spans


# ---------- auto-caption risk classification (harness B6) ----------

_DECISION_RE = re.compile(
    r"\bприе\w*|\bодобри\w*|\bотхвърли\w*|\bгласува\w*|\bреши\w*|"
    r"\bрешени[ея]\b|\bприет\w*|\bодобрен\w*|\bотхвърл\w*|\bединодуш\w*",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"\b\d[\d\s.,]*\s*(?:млн|млрд|хил|лев[а-я]*|евро)\b|\bлв\.?\b", re.IGNORECASE
)
_QUOTE_RE = re.compile(r"[«“„\"]")
_NEGATION_RE = re.compile(
    r"\bне\s+(?:прие|одобри|отхвърли|гласува|подкрепи|съгласен)\w*", re.IGNORECASE
)
_NAME_RE = re.compile(r"\b(?:д-р|проф\.?|инж\.?|г-н|г-жа)\s+[А-ЯЁ][а-яё]+", re.IGNORECASE)


RISK_DECISION = "final_decision"
RISK_MONEY = "material_number"
RISK_NAME = "personal_or_org_name"
RISK_QUOTE = "exact_quote"
RISK_NEGATION = "negation_sensitive"
RISK_LEGAL = "legal_institutional_status"

ALL_RISK_FLAGS = (RISK_DECISION, RISK_MONEY, RISK_NAME, RISK_QUOTE, RISK_NEGATION, RISK_LEGAL)

_RISKS = (
    (RISK_NEGATION, _NEGATION_RE),
    (RISK_DECISION, _DECISION_RE),
    (RISK_MONEY, _MONEY_RE),
    (RISK_NAME, _NAME_RE),
    (RISK_QUOTE, _QUOTE_RE),
)


def classify_claim_risks(text):
    """Generic risk flags for a claim; empty list = no high-risk surface."""
    risks = []
    for risk, pattern in _RISKS:
        if pattern.search(text or ""):
            risks.append(risk)
    if re.search(r"\bсъд\w*|\bпрокурату\w*|\bрегистрац\w*|\bлиценз\w*", text or "", re.IGNORECASE):
        risks.append(RISK_LEGAL)
    return risks


def corroboration_required(doc, risks):
    """True when AUTO_CAPTION carries any high-risk surface (harness B6).

    HUMAN_VERIFIED / OFFICIAL_VERBATIM transcripts carry more authority.
    The transcript still suffices to discover the story and ask questions.
    """
    if doc.trust_level in STRONG_TRUST:
        return False
    if doc.trust_level == TRUST_HUMAN_TRANSCRIPT:
        return RISK_NEGATION in risks or RISK_QUOTE in risks
    return bool(risks)
