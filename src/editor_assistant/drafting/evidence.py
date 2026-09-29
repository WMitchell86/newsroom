"""M2.3 EvidencePacket contract - facts-only authority for drafting.

Stdlib only. Archive articles are NEVER evidence. Every material draft
claim must trace to one EvidencePacket fact/quote/entity.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED_TOP = (
    "evidence_id",
    "source_url",
    "source_type",
    "observed_at",
    "source_headline",
    "facts",
    "people",
    "organizations",
    "places",
    "dates",
    "numbers",
    "quotes",
    "unknowns",
    "source_text",
)


class EvidenceError(ValueError):
    pass


def _need(mapping, keys, where):
    for key in keys:
        if key not in mapping:
            raise EvidenceError(f"{where} missing key: {key}")


def make_fact(fact_id, text, source_reference="source_text", scope="current_event"):
    text = (text or "").strip()
    if not text:
        raise EvidenceError("fact text must be non-empty")
    if scope not in ("current_event", "historical_background"):
        raise EvidenceError(f"bad scope: {scope!r}")
    return {"id": fact_id, "text": text, "source_reference": source_reference, "scope": scope}


def make_quote(text, speaker=None, role=None):
    text = (text or "").strip()
    if not text:
        raise EvidenceError("quote text must be non-empty")
    return {"text": text, "speaker": speaker, "role": role}


ANNOTATION_PREFIX = "ANNOTATION:"


def annotate_headline_number_conflicts(packet):
    """Append an `ANNOTATION:` entry to packet['unknowns'] for headline figures
    that no fact/quote/number confirms.

    source_headline is an editorial surface, NOT evidence. When it disagrees
    with the enumerated facts (EV-07: headline said "11 държави", fact
    EV-07-f03 enumerates 12 countries), models copy the headline figure and
    the semantic judge correctly flags it as invented_number. The annotation
    tells the drafter the headline number is unreliable. Deterministic and
    additive; returns the list of annotated numbers (empty if none).
    """
    facts_text = " ".join(f.get("text", "") for f in packet.get("facts", []))
    quotes_text = " ".join(q.get("text", "") for q in packet.get("quotes", []))
    numbers_text = " ".join(str(n) for n in packet.get("numbers", []))
    prior = [u for u in packet.get("unknowns", []) if str(u).startswith(ANNOTATION_PREFIX)]
    known = " ".join([facts_text, quotes_text, numbers_text] + [str(u) for u in prior])
    # Standalone-token match, not substring: "60" must not count as confirmed
    # just because "160" or a date like "2016-01-11" appears in the facts.
    missing = [
        n
        for n in re.findall(r"\d+", packet.get("source_headline") or "")
        if not re.search(rf"(?<!\d){re.escape(n)}(?!\d)", known)
    ]
    if not missing:
        return []
    packet["unknowns"] = list(packet.get("unknowns", [])) + [
        (
            f"{ANNOTATION_PREFIX} source_headline numbers {', '.join(missing)} are not "
            "confirmed by any fact or quote; do not use them in drafts - facts carry "
            "the actual values."
        )
    ]
    return missing


def validate_packet(packet):
    if not isinstance(packet, dict):
        raise EvidenceError("packet must be a dict")
    _need(packet, REQUIRED_TOP, "packet")
    if not packet["evidence_id"] or not packet["source_url"]:
        raise EvidenceError("evidence_id and source_url required")
    if not isinstance(packet["facts"], list) or not packet["facts"]:
        raise EvidenceError("facts must be a non-empty list")
    seen = set()
    for fact in packet["facts"]:
        _need(fact, ("id", "text", "source_reference"), "fact")
        if fact["id"] in seen:
            raise EvidenceError(f"duplicate fact id: {fact['id']}")
        seen.add(fact["id"])
        if not fact["text"].strip():
            raise EvidenceError("fact text must be non-empty")
        # Claim-level provenance (LIVE checkpoint): facts MAY carry
        # machine-readable source_refs [{source_id, locator}]. Packets
        # without them stay valid (M2.3 legacy) — drafting falls back to
        # source_reference/source_text.
        for ref in fact.get("source_refs") or []:
            _need(ref, ("source_id", "locator"), "fact.source_refs")
            if not ref["source_id"] or not str(ref.get("locator", "")).strip():
                raise EvidenceError(f"fact {fact.get('id')} has empty source_ref")
        if fact.get("scope") is not None and fact["scope"] not in (
            "current_event",
            "historical_background",
        ):
            raise EvidenceError(f"bad fact scope: {fact['scope']!r}")
    for quote in packet.get("quotes") or []:
        _need(quote, ("text", "speaker", "role"), "quote")
    for key in ("people", "organizations", "places", "dates", "numbers", "unknowns"):
        if not isinstance(packet.get(key), list):
            raise EvidenceError(f"{key} must be a list")
    if not isinstance(packet.get("source_text"), str) or not packet["source_text"].strip():
        raise EvidenceError("source_text must be non-empty")
    return True


def attach_provenance(packet, refs_by_fact_id):
    """Attach machine-readable provenance to packet facts.

    refs_by_fact_id: {fact_id: [{"source_id": ..., "locator": ...}]}.
    Facts without an entry keep legacy source_reference only (valid for
    M2.3 packets; LIVE packets should cover every material fact).
    Returns the list of fact ids still lacking source_refs.
    """
    missing = []
    for fact in packet["facts"]:
        refs = refs_by_fact_id.get(fact["id"]) or []
        if refs:
            fact["source_refs"] = [dict(r) for r in refs]
        else:
            missing.append(fact["id"])
    validate_packet(packet)
    return missing


def packet_claims_text(packet):
    parts = [f["text"] for f in packet.get("facts", [])]
    parts += [q["text"] for q in packet.get("quotes", [])]
    parts += list(packet.get("people", []) + packet.get("organizations", []))
    parts += list(packet.get("places", []) + packet.get("dates", []) + packet.get("numbers", []))
    return "\n".join(parts)


def write_packets(packets, path):
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for packet in packets:
            # Freeze-time rule: contradictory headline numbers are annotated
            # before any packet version lands on disk (M2.3B EV-07 corrective).
            annotate_headline_number_conflicts(packet)
            validate_packet(packet)
            fh.write(json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def read_packets(path):
    out = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                packet = json.loads(line)
                # Load-time rule: legacy packets are annotated in memory at
                # their current version, without touching the file on disk.
                annotate_headline_number_conflicts(packet)
                validate_packet(packet)
                out.append(packet)
    return out


_ABBR = re.compile(r"\b(?:проф|доц|д-р|инж|г|ул|пл|обл|т|с|др|млн|млрд)\.", re.IGNORECASE)
_ABBR_MASK = "\x00"


def _sentences(text):
    """Split on sentence enders, but NEVER at abbreviation periods.

    Treats проф. / доц. / д-р / инж. / г. / ул. / пл. / обл. / с. as mid-sentence
    abbreviations so relational context (professor names bound to their plays,
    village names, years) is preserved instead of fragmented into pseudo-atoms.
    """
    masked = _ABBR.sub(lambda m: m.group(0)[:-1] + _ABBR_MASK, text or "")
    raw = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", masked) if s.strip()]
    return [s.replace(_ABBR_MASK, ".") for s in raw if s.replace(_ABBR_MASK, ".").strip()]


_BACKGROUND_CUE = re.compile(
    r"\bпрез 20\d\d\s*г\.?\b|\bпреди\b|\bоще от предишни|\b(?:в|от) предишни(?:те)? "
    r"(?:издания|години|\b)|\bдосегашни|\bтрадиционно\b",
    re.IGNORECASE,
)


def classify_scope(text):
    """current_event vs historical_background heuristic for fact scoping."""
    if _BACKGROUND_CUE.search(text or ""):
        return "historical_background"
    return "current_event"


#: V1.2-G4.19. The marker the editor sees when the packet's own two halves
#: describe different articles. Measured: a Story titled «Бургас влиза в новия
#: Източен район» was packed with the URL and body of a completely unrelated
#: ЦИК piece about voting machines, and the model drafted the ЦИК text under
#: the park's headline. The owner chose to CONTINUE and be told, rather than
#: refuse — a feed that rewords a headline is normal, and refusing every such
#: case would block real work. So it is marked, loudly, in both places that
#: matter: the packet the model reads, and the Article screen the editor reads.
IDENTITY_MISMATCH_MARKER = "⚠ ЗАГЛАВИЕТО И ТЕКСТЪТ НЕ СЪВПАДАТ"

#: Cheap, deterministic identity signals. Deliberately conservative: a
#: disagreement only COUNTS when the two sides have enough to compare, so a
#: short body or a long headline can never manufacture a warning.
_IDENTITY_STOPWORDS = {
    "по", "на", "с", "за", "от", "при", "и", "в", "да", "се", "не", "ще",
    "а", "но", "че", "как", "вече", "още", "също", "така", "този", "това",
}


def _proper_nouns(text: str) -> set:
    """Capitalised words that are not simply the first word of a sentence.

    A headline's own proper nouns — the place, the institution, the company —
    are the part a rewording feed KEEPS. That is what makes them usable here:
    a headline reworded from "ЦИК започна проверката" to "ЦИК започна
    проверката на машините" still says ЦИК, so the check stays silent. The
    measured corruption replaced "Бургас / Източен район" with a story that
    never says either, and that is the case worth stopping the editor for.
    """
    found = set()
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        for word in re.findall(r"[^\W\d_]{3,}", sentence):
            # The first word is included deliberately: a Bulgarian headline is
            # usually one sentence, and its place or institution sits exactly
            # there. Dropping it is what hid «Бургас» in the measured case.
            if word[0].isupper():
                # Both spellings: matching is case-folded, the message shows the
                # editor the name as the headline wrote it.
                found.add((word, word.casefold()))
    return found


def annotate_source_identity_conflict(packet):
    """Mark a packet whose headline and body describe different articles.

    The number-conflict annotator above catches one narrow symptom: a figure in
    the headline that the body never mentions. This catches the general case
    the real failure was — every figure could be internally consistent and the
    two halves still belonged to different stories, because NOTHING compared
    them. The model then wrote the ЦИК text under the park's headline, and the
    park's actual content never reached it at all.

    It fires only when the headline names something the body never says. A
    reworded headline keeps its proper nouns and stays silent, and a body too
    short to compare is left alone. Refusing nothing and marking is the
    owner's explicit choice: a feed that lightly rewords a headline is normal,
    and refusing every such case would block real work.
    """
    named = _proper_nouns(packet.get("source_headline"))
    body = (packet.get("source_text") or "").casefold()
    if not named or len(body) < 120:
        return False
    missing = {word for word, folded in named if folded not in body}
    # One unseen name is normal; every one of them is a different story.
    if len(missing) < 2 or len(missing) < len(named):
        return False
    unknowns = list(packet.get("unknowns") or [])
    note = (
        f"{IDENTITY_MISMATCH_MARKER}: заглавието и текстът изглеждат като за "
        f"различни материали — в текста няма: {', '.join(sorted(missing)[:5])}. "
        f"Провери източника преди публикуване."
    )
    if note in unknowns:
        return True
    packet["unknowns"] = unknowns + [note]
    return True


def build_packet_from_record(record, *, evidence_id, observed_at, max_facts=14):
    """Deterministic packet builder from an extracted ArticleRecord.

    Human must review/cut before freezing: every fact is one source sentence
    (verbatim), entities are conservative regex finds, unknowns explicit.
    """
    body = record.body or ""
    sentences = _sentences(body)
    facts = [
        make_fact(f"{evidence_id}-f{i + 1:02d}", s, scope=classify_scope(s))
        for i, s in enumerate(sentences[:max_facts])
    ]
    quotes = [make_quote(q) for q in (record.quotes or ())]
    in_body = [q for q in quotes if q["text"] in body]
    cap = (record.caption or "").strip()
    unknowns = []
    if not quotes:
        unknowns.append("No direct quotes in source; drafts must not invent any.")
    people = sorted(set(re.findall(r"[А-Я][а-я]+\s+[А-Я][а-я]+(?:\s+[А-Я][а-я]+)?", body)))[:20]
    orgs = sorted(
        set(
            re.findall(
                r"(?:Община|Областна|Фондация|Бургаския|Бургаският|УМБАЛ|МБАЛ|КОЦ|БДУ|РИОСВ|МВР)[^.,;\n]{0,60}",
                body,
            )
        )
    )[:20]
    dates = sorted(
        set(
            re.findall(
                r"\d{1,2}-[тв]и\s+[а-я]+|\d{1,2}:\d{2}\s*ч|\d{1,2}-\d{1,2}-\d{4}|\d{4}\s*г", body
            )
        )
    )[:20]
    numbers = sorted(
        set(
            re.findall(
                r"\d[\d\s.,]*\s*(?:млн|млрд|хил|лева|евро|€|%|км|метра|деца|участници)", body
            )
        )
    )[:20]
    places = sorted(set(re.findall(r"[А-Я][а-я]+(?:\s+[А-Я][а-я]+)?", cap)))[:10] if cap else []
    packet = {
        "evidence_id": evidence_id,
        "source_url": record.url,
        "source_type": "chernomorie_live_article",
        "observed_at": observed_at,
        "source_headline": record.headline,
        "facts": facts,
        "people": people,
        "organizations": [o.strip() for o in orgs],
        "places": places,
        "dates": dates,
        "numbers": numbers,
        "quotes": in_body,
        "unknowns": unknowns,
        "source_text": body,
    }
    validate_packet(packet)
    return packet
