"""V1.2-G4.25 — the question is a signal, not a query.

The editor asked for an agent that thinks about what to search. What is
tested here is the shape of that thinking, and it is deterministic on
purpose: the enrichment envelope exists so this step is cheap enough to run
on every Draft, and a model call to guess "where would this live" is exactly
the cost the bounds were written to avoid.

WHAT WAS MEASURED BEFORE. A budget Story produced

    "<subject>" Какво точно се променя.

as a query. That hands a search engine an interrogative nobody writes. It
matches nothing, it costs the round one of three queries, and it asks the
provider for the same coverage again in a different wording.

The questions are not noise — each names a KIND of information, and each kind
has a home. So the question is classified, the SEARCHABLE TERMS for that
kind are taken from the Story's own anchors, and the kind also records
whether the answer is expected on an issuing body's own site.
"""

from editor_assistant.workflow import draft_enrichment as de
from editor_assistant.workflow import event_search as es
from editor_assistant.workflow import research_intent as ri


def _ladder(title: str) -> list[str]:
    questions = de.plan_questions(title)
    return es.event_queries(es.event_anchors(title), missing_dimensions=[questions[0]])


def test_a_question_is_never_sent_as_a_query():
    for title in (
        "Общински съвет прие бюджета на Община Бургас за 2027 година",
        "Концерт на площадката в Бургас",
        "Пожар горя блок на ул. Шипка",
    ):
        question = de.plan_questions(title)[0]
        for query in _ladder(title):
            assert question not in query, (title, question, query)


def test_the_same_words_get_three_different_searches():
    """Different kinds of Story, different terms — that is the thinking."""
    budget = _ladder("Общински съвет прие бюджета на Община Бургас за 2027 година")
    concert = _ladder("Концерт на площадката в Бургас")
    fire = _ladder("Пожар горя блок на ул. Шипка")
    assert any("решение" in q for q in budget), budget
    assert any("програма" in q for q in concert), concert
    assert any("адрес" in q for q in fire), fire


def test_an_authority_kind_searches_the_authority_s_own_site():
    """A decision's text lives on the deciding body's site, not in coverage."""
    ladder = _ladder("Общински съвет прие бюджета на Община Бургас за 2027 година")
    assert any("site:burgas.bg" in q and "решение" in q for q in ladder), ladder


def test_kinds_are_classified_and_flagged_where_they_live():
    kinds = {i.kind: i.prefers_authority for i in ri.classify_all(
        de.plan_questions("Общински съвет прие бюджета на Община Бургас")
    )}
    assert kinds["DECISION_TEXT"] is True
    assert kinds["EFFECTIVE_DATE"] is True


def test_a_concert_is_not_treated_as_a_decision():
    intents = ri.classify_all(de.plan_questions("Концерт на площадката в Бургас"))
    assert {i.kind for i in intents} == {"SCHEDULE", "PROGRAMME", "ACCESS"}
    # None of them claims the answer lives on an authority's own site.
    assert not any(i.prefers_authority for i in intents)


def test_an_unrecognised_question_contributes_nothing():
    """A wrong query costs budget and looks like a real answer."""
    assert ri.classify("Нямам предвид") is None
    assert ri.classify("") is None
    assert ri.classify_all(["Нямам предвид", "  "]) == []
