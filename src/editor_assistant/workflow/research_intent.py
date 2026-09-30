"""V1.2-G4.25 — where each kind of question is actually answered.

The editor asked for an agent that thinks about what to search, and the
insight this encodes is simple: the QUESTION is not a query.

Measured. A budget Story produced the ladder

    1. "Общински съвет прие бюджета на Община Бургас за 2027 година"
    2. "Общински съвет прие бюджета ... Какво точно се променя."
    3. "Общински съвет прие бюджета ... От кога влиза решението в сила."

Rung 2 and 3 hand a search engine the editorial question verbatim. A search
engine handed «Какво точно се променя» matches nothing — it is an
interrogative, not a term anyone writes. So the round spends its budget
asking for the same coverage three times, in three wordings, and never asks
where the decision text actually is.

The questions are not noise, though. Each one names a KIND of information,
and each kind lives somewhere specific:

    «От кога влиза решението в сила»  → the deciding body's own text
    «Къде е официалното решение»        → the gazette / decision register
    «Кой е организаторът»               → the organiser's own site
    «Как се влиза — билети»             → the organiser's own site
    «Кога и къде се провежда»            → programme / calendar
    «Има ли официално съобщение на …»   → that institution's press release
    «Кой е засегнат»                    → aftermath / casualty reporting

So the plan is: classify the question into a KIND, take the SEARCHABLE terms
for that kind from the Story's own anchors, and record which kind of
publisher tends to hold the answer. The question's own words are then never
sent — they are consumed as a signal.

Everything here is deterministic. "The agent should think" is served by
knowing the shape of a question and where its answer lives, not by spending a
model call to guess. That keeps it inside the enrichment envelope, which
exists precisely so this step is cheap enough to run on every Draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: kind -> (question patterns, searchable terms for that kind)
#: The terms are BULGARIAN NOUNS a publisher actually uses. They are never
#: the question itself; a question is a sentence addressed to someone.
_INTENTS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "DECISION_TEXT",
        (r"официалното?\s+решение", r"какво\s+точно\s+се\s+променя", r"какво\s+точно"),
        ("решение", "постановление", "за изменение", "прието"),
    ),
    (
        "EFFECTIVE_DATE",
        (r"от\s+кога\s+влиза", r"кога\s+влиза\s+в\s+сила", r"в\s+сила"),
        # V1.2-G4.29. Was `обярвам`, which is grammatically correct Bulgarian and
        # useless as a search term: it is the first person singular, and news
        # copy does not say "I announce". Measured over the corpus:
        #   обярвам 0 · обявява 4 · обявяват 2
        # The stem `обявява` covers every person a publisher actually writes.
        ("влиза в сила", "обявява", "влиза в сила от"),
    ),
    (
        "OFFICIAL_REGISTER",
        (r"къде\s+е\s+официалното", r"официално\s+съобщение", r"официален\s+източник"),
        ("официално съобщение", "съобщение", "пресцентър"),
    ),
    (
        "ORGANISER",
        (r"кой\s+е\s+организатор", r"има\s+ли\s+официална\s+страница", r"организатор"),
        ("организатор", "организират", "официален сайт"),
    ),
    (
        "ACCESS",
        (r"как\s+се\s+влиза", r"билет", r"регистрация", r"вход"),
        ("билети", "вход свободен", "регистрация"),
    ),
    (
        "PROGRAMME",
        (r"кой\s+участва", r"каква\s+е\s+програмата", r"програма"),
        ("програма", "състав", "участие"),
    ),
    (
        "SCHEDULE",
        (r"кога\s+и?\s*къде\s+се\s+провежда", r"кога\s+се\s+провежда", r"къде\s+се\s+провежда"),
        ("програма", "начало", "сцена"),
    ),
    (
        "AFTERMATH",
        (r"кой\s+е\s+засегнат", r"пострадал", r"ранен", r"загинал"),
        ("пострадали", "загинал", "ранени", "актуална информация"),
    ),
    (
        "PLACE",
        (r"къде\s+се\s+е\s+случило", r"къде\s+се\s+случи", r"адрес"),
        ("адрес", "локация", "на място"),
    ),
    (
        "TIME",
        (r"кога\s+се\s+е?\s*случило", r"кога\s+се\s+случило"),
        ("кога", "време", "час"),
    ),
)

_COMPILED: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (kind, re.compile("|".join(patterns), re.IGNORECASE), terms)
    for kind, patterns, terms in _INTENTS
)


@dataclass(frozen=True)
class Intent:
    """One classified question, and what is worth searching for it."""

    kind: str
    question: str
    #: Terms a publisher would actually write. NEVER the question text.
    terms: tuple[str, ...]
    #: True when the kind tends to live on an official or organiser's own site
    #: rather than in coverage. Drives the source preference, not the query.
    prefers_authority: bool = False
    extra: list[str] = field(default_factory=list)


#: Kinds whose answer is normally on the issuing body's own site. Measured
#: against how these questions are actually answered, not assumed.
_AUTHORITY_KINDS = frozenset(
    {"DECISION_TEXT", "EFFECTIVE_DATE", "OFFICIAL_REGISTER", "ORGANISER"}
)


def classify(question: str) -> Intent | None:
    """Classify one editorial question. `None` when nothing matches.

    Returning None matters as much as matching: an unrecognised question must
    contribute nothing rather than a guess, because a wrong query costs the
    round's budget and looks like a real answer.
    """
    text = " ".join(str(question or "").split())
    if not text:
        return None
    for kind, pattern, terms in _COMPILED:
        if pattern.search(text):
            return Intent(
                kind=kind,
                question=text,
                terms=terms,
                prefers_authority=kind in _AUTHORITY_KINDS,
            )
    return None


def classify_all(questions) -> list[Intent]:
    out = []
    for question in questions or ():
        intent = classify(question)
        if intent is not None:
            out.append(intent)
    return out
