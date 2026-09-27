"""V1.2-G2.3 §1-§7: is this claim the same factual proposition?

The single narrow service the research path needs. It answers ONE question
about a PAIR of claims and returns a CLOSED verdict:

    SAME_FACT | DIFFERENT_FACT | CONFLICT | UNCERTAIN

Design rules the rest of the slice depends on:

* **The safety rule is unchanged.** A pair is only ``SAME_FACT`` when two
  independent publishers really do support one proposition. This service never
  grants authority, never creates evidence, and never relaxes the
  independent-publisher requirement (§1, §8, §16).
* **Deterministic certainty first (§5).** A hard contradiction is decided here
  and can never be overridden by a model: different explicit dates, different
  incompatible quantities, a negation mismatch, or a different named
  organisation where identity is central.
* **No loose similarity alone (§3).** Token overlap is used only to decide
  whether a differing concrete slot is a *contradiction* or merely a different
  fact. A bare Jaccard threshold can call a contradiction a match, so it is
  never sufficient to answer ``SAME_FACT`` on its own.
* **Conservative by construction (§6).** ``UNCERTAIN`` grants nothing. When the
  semantic route is unavailable - no key, no route, a model failure, malformed
  output - the verdict is ``UNCERTAIN`` and no corroboration is granted.

Bulgarian morphology is handled by a small, conservative suffix stripper
(§28): only well-known endings are removed, and only when a stem of at least
four characters remains, so ordinary words are never mangled.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

#: The closed verdict set. Callers never parse prose (§4, §6).
SAME_FACT = "SAME_FACT"
DIFFERENT_FACT = "DIFFERENT_FACT"
CONFLICT = "CONFLICT"
UNCERTAIN = "UNCERTAIN"
VERDICTS = frozenset({SAME_FACT, DIFFERENT_FACT, CONFLICT, UNCERTAIN})


# ---------------------------------------------------------------------------
# normalisation and morphology
# ---------------------------------------------------------------------------

#: A publisher suffix is not part of the proposition ("... - БНР" and the same
#: sentence without it are one claim), so it is removed before comparing.
_TRAILING_PUBLISHER = re.compile(
    r"\s+[-–—|]\s+[^-–—|]{2,40}$"
)
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[\wа-яА-Я]+", re.UNICODE)
_NUMBER = re.compile(r"\d+")

#: Conservative Bulgarian suffix list, longest first. Only these are stripped,
#: and only from a token of at least ``_MIN_STEM`` characters, so short words
#: and unrelated forms are left alone.
_SUFFIXES = (
    "ията", "отото", "ите", "ия", "ят", "ът", "ата", "ото", "ете", "ем",
    "ах", "те", "ти", "ла", "ло", "ли", "ни", "но", "на", "та", "а", "о",
    "у", "и", "е", "ъ", "я", "й",
)
_MIN_STEM = 4
#: Matching key length. Bulgarian inflects the same lexeme across many surface
#: forms ("съвет" / "съветът" / "съвета", "улица" / "улицата"), and no
#: conservative suffix list collapses all of them. Four leading characters are
#: long enough to identify a lexeme and short enough to survive the endings.
#:
#: This key is deliberately NOT sufficient to answer SAME_FACT on its own
#: (§3): it gates the contradiction check and the clearly-different case, and
#: the actual equivalence decision is the semantic judgement or UNCERTAIN.
_KEY = 4
#: Words that are meaningless as a proposition and must never identify a fact.
_STOP = frozenset(
    [
        "и", "или", "но", "че", "да", "се", "на", "в", "за", "от", "по", "като",
        "при", "след", "преди", "това", "този", "тази", "тези", "също", "много",
        "малко", "повече", "най-много", "около", "следващ", "предишния", "нов",
        "стар", "втори", "първи", "три", "четири", "пет", "шест", "седем",
        "осем", "девет", "десет", "сто", "хиляда", "милион",
    ]
)

_MONTHS = {
    "януари": 1, "февруари": 2, "март": 3, "април": 4, "май": 5, "юни": 6,
    "юли": 7, "август": 8, "септември": 9, "октомври": 10, "ноември": 11,
    "декември": 12,
}
_NEGATORS = ("не", "нито", "без", "изключва", "отрича", "няма", "липсва")
_UNITS = (
    "лева", "лв", "евро", "кг", "км", "м", "часа", "часа", "души", "процент",
    "%", "брой", "години", "дни", "месеца", "километра",
)
_ORG_TITLES = (
    "кмет", "кмета", "министър", "министъра", "губернатор", "комисар",
    "началник", "директор", "председател", "съвет", "община", "общината",
    "полиция", "съд", "прокуратура", "болница", "университет", "компания",
)


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def normalise(text: str) -> str:
    """Casefolded, accent-free, publisher-suffix-free, single-spaced text."""
    value = _strip_accents(str(text or "")).casefold()
    value = value.replace("„", " ").replace("“", " ").replace("”", " ")
    value = value.replace("‑", "-")
    value = _TRAILING_PUBLISHER.sub("", value)
    value = re.sub(r"[^0-9a-zа-я\s-]+", " ", value)
    return _WHITESPACE.sub(" ", value).strip()


def stem(token: str) -> str:
    """A conservative Bulgarian stem: strip a known ending, keep >= 4 chars."""
    for suffix in _SUFFIXES:
        if len(token) - len(suffix) >= _MIN_STEM and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _key(token: str) -> str:
    """The stable matching key of one token."""
    value = stem(token)
    return value[:_KEY] if len(value) >= _KEY else value


def content_tokens(text: str) -> set[str]:
    """Matching keys of a claim's content tokens.

    Stopwords and bare numbers are removed: neither identifies a fact, and a
    shared number is handled explicitly as a quantity instead.
    """
    out = set()
    for raw in _TOKEN.findall(normalise(text)):
        if raw in _STOP or raw.isdigit():
            continue
        key = _key(raw)
        if len(key) >= 3 and key not in _STOP and raw not in _STOP:
            out.add(key)
    return out


def _numbers(text: str) -> list[tuple[str, str]]:
    """(value, unit) pairs, so 3 and 4 injured can be told apart but
    "1,2 милиона лева" is one value with two units."""
    out = []
    for match in re.finditer(r"(\d[\d\s.,]*)\s*([а-яa-z%]*)", normalise(text)):
        digits = re.sub(r"[^\d]", "", match.group(1))
        if not digits:
            continue
        unit = next((u for u in _UNITS if match.group(2).startswith(u[:3])), "")
        out.append((digits, unit))
    return out


def _dates(text: str) -> set[tuple[int, int]]:
    """(year, month) pairs, so "октомври" and "октомври 2025" agree."""
    value = normalise(text)
    out = set()
    for name, number in _MONTHS.items():
        for match in re.finditer(rf"{name}(?:\s+(\d{{4}}))?", value):
            year = match.group(1) or ""
            out.add((int(year) if year else 0, number))
    for match in re.finditer(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", value):
        day, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            year = match.group(3)
            out.add((int(year) if year else 0, month))
    return out


def _is_negated(text: str) -> bool:
    tokens = set(_TOKEN.findall(normalise(text)))
    return any(negator in tokens or any(t.startswith(negator) for t in tokens) for negator in _NEGATORS)


def _named(text: str) -> set[str]:
    """Capitalised spans: candidate people, organisations and places."""
    out = set()
    for match in re.finditer(r"\b([А-Я][а-я]{2,}(?:\s+[А-Я][а-я]{2,}){0,2})", str(text or "")):
        span = normalise(match.group(1))
        if span and span not in _STOP:
            out.add(span)
    return out


def _org_slot(text: str) -> str:
    """The organisation a claim names, when it names one by title.

    ``кметът на Созопол`` and ``кметът на Несебър`` are different facts about
    different people, so the named place is part of the identity.
    """
    value = normalise(text)
    for title in _ORG_TITLES:
        for match in re.finditer(rf"{title}\w*\s+(?:на|в|от)\s+([а-я][а-я\-]+)", value):
            return f"{title}:{match.group(1)}"
    return ""


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# ---------------------------------------------------------------------------
# the service
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Comparison:
    verdict: str
    reason: str = ""


def compare_claims(claim_a: str, claim_b: str, *, semantic=None) -> str:
    """Are these two claims the same factual proposition?

    ``semantic`` is an optional ``(claim_a, claim_b) -> str`` hook used for the
    ambiguous middle band (§6). It may return any of :data:`VERDICTS`; anything
    else, including an exception, is treated as no answer, which yields
    ``UNCERTAIN`` and grants no corroboration.
    """
    return _compare(str(claim_a or ""), str(claim_b or ""), semantic).verdict


def _compare(a: str, b: str, semantic) -> _Comparison:
    norm_a, norm_b = normalise(a), normalise(b)
    if not norm_a or not norm_b:
        return _Comparison(UNCERTAIN, "empty claim")
    if norm_a == norm_b:
        return _Comparison(SAME_FACT, "identical text")

    tokens_a, tokens_b = content_tokens(a), content_tokens(b)
    if not tokens_a or not tokens_b:
        return _Comparison(UNCERTAIN, "no content tokens")
    overlap = _overlap(tokens_a, tokens_b)

    # §3: a difference in a concrete slot is only a CONTRADICTION when the two
    # claims are otherwise about the same thing. Without this guard two
    # unrelated sentences sharing a number would be reported as a conflict.
    if overlap >= 0.30:
        contradiction = _hard_contradiction(a, b)
        if contradiction:
            return _Comparison(CONFLICT, contradiction)

    # §3: a bare overlap threshold may never answer SAME_FACT on its own. It
    # only short-circuits the clearly-different case, which costs nothing.
    if overlap < 0.18:
        return _Comparison(DIFFERENT_FACT, "different subject matter")

    # The ambiguous middle band: plausible, non-contradictory, differently
    # worded. §6 - a model may settle it, and only a closed verdict counts.
    answer = _semantic_verdict(a, b, semantic)
    if answer in VERDICTS:
        return _Comparison(answer, "semantic judgement")
    return _Comparison(UNCERTAIN, "no reliable equivalence signal")


def _hard_contradiction(a: str, b: str) -> str:
    """A deterministic contradiction, or an empty string (§5).

    Checked in a fixed order and never delegated to a model.
    """
    if _is_negated(a) != _is_negated(b):
        return "negation mismatch"

    org_a, org_b = _org_slot(a), _org_slot(b)
    if org_a and org_b and org_a != org_b:
        return "different named organisation"

    dates_a, dates_b = _dates(a), _dates(b)
    if dates_a and dates_b and not (dates_a & dates_b):
        return "different explicit date"

    numbers_a = {value for value, _ in _numbers(a)}
    numbers_b = {value for value, _ in _numbers(b)}
    if numbers_a and numbers_b and not (numbers_a & numbers_b):
        units_a = {unit for _, unit in _numbers(a) if unit}
        units_b = {unit for _, unit in _numbers(b) if unit}
        if units_a & units_b:
            return "different quantity for the same measure"

    named_a, named_b = _named(a), _named(b)
    if named_a and named_b and not (named_a & named_b):
        shared_titles = {t for t in _ORG_TITLES if any(t in n for n in named_a)}
        if shared_titles and _overlap(content_tokens(a), content_tokens(b)) >= 0.5:
            return "different named person or organisation"
    return ""


def _semantic_verdict(a: str, b: str, semantic) -> str | None:
    """Ask the configured semantic hook, tolerating any failure (§6)."""
    if semantic is None:
        semantic = _default_semantic
    if semantic is False:
        return None
    try:
        verdict = semantic(a, b)
    except (ValueError, TypeError, OSError, RuntimeError, LookupError):
        # §29: an unavailable model must never turn into a promotion. A transport
        # or routing failure is one of these; anything else propagates.
        return None
    verdict = str(verdict or "").strip().upper()
    return verdict if verdict in VERDICTS else None


_MODEL_INSTRUCTION = (
    "Отговори С НАЙ-МНО една дума: SAME_FACT, DIFFERENT_FACT, CONFLICT или "
    "UNCERTAIN. Една и съща фактологическа твърдение ли са двата изречения?"
)


def _default_semantic(claim_a: str, claim_b: str) -> str | None:
    """The existing model route, used only for the ambiguous middle band.

    §6: this is the project's own routing (the ``extract`` role - schema-first,
    high volume), not a new provider or a new permanent dependency. When it is
    unavailable the caller already grants nothing, because the result is
    ``UNCERTAIN``.
    """
    from editor_assistant.drafting import generate

    payload = json.dumps(
        {"A": claim_a, "B": claim_b}, ensure_ascii=False
    )
    answer = generate.call_model(
        f"{_MODEL_INSTRUCTION}\n\n{payload}",
        role="extract",
        timeout=30,
    )
    text = answer if isinstance(answer, str) else str(answer)
    match = re.search(
        r"\b(SAME_FACT|DIFFERENT_FACT|CONFLICT|UNCERTAIN)\b", text.upper()
    )
    return match.group(1) if match else None
