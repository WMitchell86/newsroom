"""V1.2-G2.3 §9-§12: which sentences may even be considered a fact.

Two narrow jobs, both deterministic and both BEFORE any promotion:

* **Content quality (§11/§12).** Reject navigation chrome, cookie banners,
  footer and category lists, and text that is not shaped like a proposition.
  G2.1's single promoted "fact" was a navigation menu, so this is a measured
  failure, not a hypothetical one.
* **Bounded multi-claim extraction (§9/§10).** Return a small candidate set per
  opened page instead of the first matching sentence, each associated with the
  research question it can answer, so corroboration can compare like with like
  (§7, §22).

Nothing here decides whether a claim is TRUE, and nothing here grants
authority. It only removes text that cannot be a fact.
"""

from __future__ import annotations

import re

#: §11 — the G2.1 false success, kept verbatim so the regression is permanent.
KNOWN_CHROME = "НОВИНИ КУЛТУРНА ПРОГРАМА СПОРТНА ПРОГРАМА"

_CHROME_PATTERNS = (
    r"doctype|<\s*html|<\s*body|<\s*div|<\s*a\s|cookie|бисквитк",
    r"\bnav\b|\bменю\b|\bнавигац|хлебни трохи|\bхлебни\b",
    r"вход\s*[:·]|\blogin\b|регистрац|\bабонирайт|\bабони|\bсподеляне\b",
    r"^\s*(обяви|контакти|реклама|рекламна|задължителна|условия за|поверителност)",
    r"всички права запазени|©|\bcopyright\b|всички изображения са",
)
_CATEGORY_ONLY = re.compile(
    r"^[\sА-ЯA-Zа-яa-z0-9&-]{0,400}$"
)
#: A run of short all-caps labels with no sentence punctuation is a menu bar.
_MENU_RUN = re.compile(r"(?:\b[А-ЯЪ]{3,12}\b[\s|/]+){3,}")
_SENTENCE_END = re.compile(r"[.!?…]")
_MIN_CHARS = 25
_MAX_CHARS = 600

#: §10 — which research question a candidate answers, and the answer shape that
#: makes a sentence a plausible answer to it.
_DIMENSIONS = {
    "event_schedule": (
        r"\bкога\b|\bграфик\b|\bдата\b|\bвреме\b|програм",
        r"\b\d{1,2}[.:]\d{2}\s*ч\b|\b\d{1,2}\s+(?:януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември)\b|\b\d{4}\s*г|\bпрез\b",
    ),
    "participants": (
        r"\bкой\b|\bкои\b|\bорган\b|\bлице\b|\bзамесен",
        r"\bкмет\w*|\bминистър\w*|\bсъвет\w*|\bкомиси\w*|\bдиректор\w*|\bсъд\w*|\bполици\w*",
    ),
    "venue": (
        r"\bкъде\b|\bзал\b|\bадрес\b|\bплощад\b|\bобласт\b|\bград\b|\bсело\b",
        r"\bна\b|\bв\b|\bул\.|\bбулевард|\bплощад|\bград|\bсело|\bобласт",
    ),
    "amount": (
        r"\bколко\b|\bсума\b|\bфинанс|\bцена\b|\bлева\b|\bевро\b",
        r"\b\d[\d\s.,]*\s*(?:лева|лв|евро|милиона?|милион|млн\.?|млрд\.?|хиляди|хиляда|хил\.?|%)\b",
    ),
    "decision_status": (
        r"\bрешение\b|\bрешен\b|\bприет|\bодобрен|\bотхвърлен|\bстатус",
        r"\bприет|\bодобр|\bотхвърл|\bрешени|\bпостанови|\bзабрани|\bразреши",
    ),
}


def is_chrome(text: str) -> bool:
    """True when the text is page furniture rather than content (§11)."""
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.casefold()
    for pattern in _CHROME_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            return True
    if _MENU_RUN.search(value):
        return True
    # A block of bare all-caps labels separated by whitespace/pipes is a menu.
    letters = re.sub(r"[^A-Za-zА-Яа-я]", "", value)
    # A block of bare all-caps labels with no sentence punctuation is a menu bar.
    if (
        letters
        and sum(ch.isupper() for ch in letters) / len(letters) > 0.7
        and not _SENTENCE_END.search(value)
    ):
        return True
    # A real navigation bar is often title case, not caps: a run of short
    # one-or-two word labels separated by wide spacing, with no sentence
    # punctuation. `Начало   Новини   Култура   Спортна програма` is the shape.
    if not _SENTENCE_END.search(value):
        labels = [part for part in re.split(r"\s{2,}|[|/]", value) if part.strip()]
        if len(labels) >= 3 and all(len(part.split()) <= 3 for part in labels):
            return True
    return False


def is_factual_candidate(text: str) -> bool:
    """True when the text is shaped like a proposition (§12).

    Conservative guards only: a minimum length, a sentence ending, and a real
    proportion of letters. Short but legitimate facts are not rejected merely
    for being short - the floor is deliberately low.
    """
    value = str(text or "").strip()
    if not value or is_chrome(value):
        return False
    if not (_MIN_CHARS <= len(value) <= _MAX_CHARS):
        return False
    if not _SENTENCE_END.search(value):
        return False
    letters = re.findall(r"[A-Za-zА-Яа-я]", value)
    if len(letters) < 0.5 * len(value.replace(" ", "")):
        return False
    # A proposition carries verbs-ish word variety; a bare fragment of two
    # repeated words is not one.
    words = {w.casefold() for w in re.findall(r"[\wа-яА-Я]+", value) if len(w) > 2}
    return len(words) >= 4


def answering_dimensions(sentence: str, questions) -> set[str]:
    """Which research dimensions this sentence can plausibly answer (§10, §22)."""
    question_blob = " ".join(str(q or "") for q in questions).casefold()
    sentence_blob = str(sentence or "").casefold()
    out = set()
    for name, (question_pattern, answer_pattern) in _DIMENSIONS.items():
        if re.search(question_pattern, question_blob, re.IGNORECASE) and re.search(
            answer_pattern, sentence_blob, re.IGNORECASE
        ):
            out.add(name)
    return out


def select_candidate_claims(sentences, questions, *, limit: int = 4) -> list[dict]:
    """A small, ordered candidate set from one opened page (§9, §10).

    At most ``limit`` claims (3-5 by default) are returned, each with the
    dimension it answers, so corroboration compares claims that were extracted
    for the same reason rather than arbitrary sentences. The order is by
    relevance to the Story's questions, and duplicates are dropped.
    """
    pool = []
    seen = set()
    for index, raw in enumerate(sentences or []):
        value = str(raw or "").strip()
        if not value or not is_factual_candidate(value):
            continue
        marker = value.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        dimensions = answering_dimensions(value, questions)
        pool.append(
            {
                "text": value,
                "dimensions": sorted(dimensions),
                "position": index,
            }
        )
    # Prefer a sentence that answers an actual research question, then keep the
    # reading order of the page.
    pool.sort(key=lambda row: (not row["dimensions"], row["position"]))
    return pool[: max(1, int(limit))]
