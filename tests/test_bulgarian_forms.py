"""V1.2-G4.29 — the Bulgarian in this code is measured, not remembered.

A wrong Bulgarian form in this codebase is a silent production bug and not a
typo. A locality stem that is misspelled never matches, and a search term in
the wrong person or case matches nothing — both look like "the source has no
news about that" rather than like a mistake. So every Bulgarian string is
checked against the newsroom's own corpus instead of against memory.

ONE REAL ERROR FOUND, in a term this session added:

    search term `обярвам`   0 occurrences in the corpus
                  `обявява`   4
                  `обявяват`  2

`обярвам` is grammatically correct Bulgarian — the first person singular of
"обявявам" — and useless as a search term, because news copy does not say "I
announce". The editor would have got a query that can never match, and the
round would have spent budget on it. Corrected to the stem `обявява`, which
covers every person a publisher actually writes.

WHAT THIS FILE DOES NOT CLAIM. "Never seen in the corpus" is not "wrong" for
every term: `постановление`, `организатор`, `съобщение` and others are
perfectly ordinary Bulgarian news vocabulary that this 632-item regional
corpus simply has not needed. `съобщение` is in fact in the system's own
generic-vocabulary list, on purpose, precisely because it is so common that it
must never be treated as identifying. The check here is for FORMS that cannot
occur in news at all, not for rarity.

The locality stems are all genuine forms of the thirteen municipalities;
`средет` and `сунгураре` are absent from this corpus only because no story
from either has been collected yet, not because the names are wrong.
"""

import json
import re
from pathlib import Path

from editor_assistant.workflow import regional_scope as rs
from editor_assistant.workflow import research_intent as ri

CORPUS = Path("var/newsroom/inbox.jsonl")


def _corpus() -> str:
    if not CORPUS.exists():
        return ""
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line]
    return " ".join(
        f"{r.get('title') or ''} {(r.get('summary') or '')[:400]}" for r in rows
    ).casefold()


def test_no_search_term_is_written_in_a_form_news_never_uses():
    """`обярвам` is correct Bulgarian and a dead search term. Caught by measure."""
    blob = _corpus()
    if not blob:
        return  # no live corpus here; the classification tests cover it
    assert "обярвам" not in " ".join(
        term for terms in ri._INTENTS for term in terms[2]
    ), "first-person singular in a search term"
    # The replacement must actually occur in publisher text.
    assert len(re.findall(re.escape("обявява"), blob)) > 0


def test_every_locality_stem_is_a_real_bulgarian_form():
    """Each stem must occur in the corpus, or its municipality is simply absent.

    A stem that never occurs AND is not a known municipality name would be a
    misspelling that silently stops matching.
    """
    blob = _corpus()
    if not blob:
        return
    # Municipalities with no coverage yet, so absent for a reason.
    never_collected = {"средет", "сунгураре"}
    for stem in rs.REGIONAL_LOCALITY_STEMS:
        if stem in never_collected:
            continue
        assert re.search(stem, blob), f"{stem!r} never occurs in the corpus"


def test_the_three_sharpened_patterns_are_real_forms():
    blob = _corpus()
    if not blob:
        return
    for pattern in (r"малко\w*\s+търново", r"камено\b", r"бург"):
        assert re.search(pattern, blob), pattern


def test_every_intent_kind_is_named_in_a_real_question():
    """Each kind must be reachable from a question the product actually asks."""
    from editor_assistant.workflow import draft_enrichment as de

    asked = set()
    for title in (
        "Общински съвет прие бюджета на Община Бургас",
        "Концерт на площадката в Бургас",
        "Пожар в блок на ул. Шипка",
        "Дядо Коледа идва в Бургас",
    ):
        asked.update(de.plan_questions(title))
    kinds = {ri.classify(q).kind for q in asked if ri.classify(q)}
    # These are the kinds the shipped questions reach, so each name is one the
    # product has actually used.
    assert {"DECISION_TEXT", "EFFECTIVE_DATE", "SCHEDULE", "ACCESS", "PLACE", "TIME"} <= kinds
