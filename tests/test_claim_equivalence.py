"""V1.2-G2.3 §28/§36: the claim-equivalence contract and its benchmark.

The safety rule under test is unchanged: a fact needs an authoritative source
OR two independent publishers supporting the SAME FACTUAL PROPOSITION. What is
new is that the proposition is recognised semantically rather than by string
equality - and that a hard contradiction can never be talked into agreeing.
"""

from __future__ import annotations

import pytest

from editor_assistant.workflow import claim_equivalence as ce
from editor_assistant.workflow import claim_quality as cq


def _same_raising(*_args, **_kwargs):
    raise RuntimeError("the semantic route is unavailable")


def _same(*_args, **_kwargs):
    """A model that always agrees - the middle band resolves to SAME_FACT."""
    return ce.SAME_FACT


#: §28 — a labelled benchmark in real Bulgarian newsroom shape, split by the
#: layer that is allowed to decide each pair.
#:
#: `deterministic` pairs are settled WITHOUT a model. `middle` pairs are
#: genuinely ambiguous: with no model the correct answer is UNCERTAIN (which
#: grants nothing), and a model may move them to SAME_FACT.
BENCHMARK_DETERMINISTIC = [
    ("exact", "Общинският съвет одобри 1,2 милиона лева за ремонта.",
     "Общинският съвет одобри 1,2 милиона лева за ремонта.", ce.SAME_FACT),
    ("exact_publisher_suffix", "Ремонтът на улицата започна през октомври - БНР",
     "Ремонтът на улицата започна през октомври.", ce.SAME_FACT),
    ("conflict_number", "При катастрофата пострадаха 3 души.",
     "При катастрофата пострадаха 4 души.", ce.CONFLICT),
    ("conflict_date", "Ремонтът започна през октомври.",
     "Ремонтът започна през ноември.", ce.CONFLICT),
    ("conflict_identity", "Кметът на Созопол заяви, че ремонтът е по график.",
     "Кметът на Несебър заяви, че ремонтът е по график.", ce.CONFLICT),
    ("conflict_negation", "Пуснаха в движение новата чешма на пътя.",
     "Не пуснаха в движение новата чешма на пътя.", ce.CONFLICT),
    ("different_event_similar_words", "Съветът одобри парите за ремонта на улицата.",
     "В Бургас започнаха работите по нов пътен възел.", ce.DIFFERENT_FACT),
    ("same_event_other_fact", "Ремонтът на улицата започна през октомври.",
     "Жителите се оплакват от прака в центъра на града.", ce.DIFFERENT_FACT),
]

BENCHMARK_MIDDLE = [
    ("paraphrase", "Жена и 3-годишно дете пострадаха при катастрофа на пътя Бургас-Созопол.",
     "Майка и дете пострадаха при катастрофата на пътя."),
    ("morphology_pair", "Община Созопол подписа договора за ремонта.",
     "Общината подписа договора за подновяване на улицата."),
    ("same_date_different_wording", "Ремонтът започна през октомври 2026 година.",
     "Ремонтът на улицата е в ход от октомври 2026 г."),
]


@pytest.mark.parametrize(
    ("name", "a", "b", "expected"),
    BENCHMARK_DETERMINISTIC,
    ids=[row[0] for row in BENCHMARK_DETERMINISTIC],
)
def test_deterministic_benchmark_pair(name, a, b, expected):
    # `semantic=False` switches the model off entirely: whatever this returns
    # was decided by the deterministic layer alone.
    assert ce.compare_claims(a, b, semantic=False) == expected


@pytest.mark.parametrize(
    ("name", "a", "b"), BENCHMARK_MIDDLE, ids=[row[0] for row in BENCHMARK_MIDDLE]
)
def test_ambiguous_pairs_grant_nothing_without_a_model(name, a, b):
    # §3/§6: ambiguity resolves to UNCERTAIN, never to a match on similarity.
    assert ce.compare_claims(a, b, semantic=False) == ce.UNCERTAIN
    # ...and a model that agrees may settle it, which is the only way these
    # pairs ever become evidence.
    assert ce.compare_claims(a, b, semantic=_same) == ce.SAME_FACT


def test_a_conflict_is_decided_without_any_model():
    # §5: a hard contradiction is deterministic and a model must never be able
    # to override it. The hook here would answer SAME_FACT if it were asked.
    called = []

    def model(*_args, **_kwargs):
        called.append(True)
        return ce.SAME_FACT

    assert ce.compare_claims("Пострадаха 3 души.", "Пострадаха 4 души.", semantic=model) == ce.CONFLICT
    assert called == [], "a hard contradiction must not consult the model"


def test_one_source_alone_does_not_corroborate():
    # §16 — a single publisher is never enough, whatever the wording. The
    # verdict may be UNCERTAIN or DIFFERENT_FACT; the only forbidden answer is
    # SAME_FACT, which only two independent sources may produce.
    for pair in (
        ("Ремонтът започна през октомври.", "Ремонтът на улицата е в ход."),
        ("Жена и дете пострадаха при катастрофата.", "Майка с дете пострадаха при катастрофата."),
    ):
        assert ce.compare_claims(*pair, semantic=False) != ce.SAME_FACT


def test_no_model_means_uncertain_and_grants_nothing(monkeypatch):
    # §6/§29 — the conservative fallback. An unavailable route, a raising hook
    # and the real default path with a failing model must all land in the same
    # place, and that place grants no corroboration.
    from editor_assistant.drafting import generate

    def _no_route(*_args, **_kwargs):
        raise RuntimeError("no route available")

    monkeypatch.setattr(generate, "call_model", _no_route)
    pair = (
        "Майка и дете пострадаха при катастрофата.",
        "Жена и дете пострадаха при катастрофата.",
    )
    for hook in (False, _same_raising, None):
        assert ce.compare_claims(*pair, semantic=hook) == ce.UNCERTAIN


def test_similarity_alone_never_grants_same_fact():
    # §3 — two similar headlines can contradict each other, so overlap must
    # never be sufficient. Without a model the answer is UNCERTAIN.
    assert ce.compare_claims(
        "В Бургас пострадаха при катастрофата на пътя.",
        "В Бургас пострадаха при катастрофата на шосеето.",
        semantic=False,
    ) == ce.UNCERTAIN


def test_a_malformed_model_answer_is_ignored():
    assert ce.compare_claims(
        "Общинският съвет одобри бюджет за ремонта.",
        "Съветът одобри средствата за ремонта на улицата.",
        semantic=lambda *_: "maybe they are the same",
    ) == ce.UNCERTAIN


# ---------------------------------------------------------------------------
# §11/§12 content quality
# ---------------------------------------------------------------------------


def test_the_known_navigation_menu_is_rejected_permanently():
    # §11/§26: the G2.1 false success. This exact string must never become a
    # claim, whatever else changes.
    assert cq.is_chrome(cq.KNOWN_CHROME)
    assert not cq.is_factual_candidate(cq.KNOWN_CHROME)
    assert cq.select_candidate_claims([cq.KNOWN_CHROME], ["Кога се случи?"]) == []


@pytest.mark.parametrize(
    "chrome",
    [
        "Използваме бисквитки, за да продължим浏览.",
        "Всички права запазени.",
        "Начало   Новини   Култура   Спортна програма",
        "Вход: потребител име парола",
        "Обяви   Контакти   Реклама   Условия за ползване",
    ],
)
def test_page_furniture_is_rejected(chrome):
    assert cq.is_chrome(chrome)


def test_a_real_sentence_survives():
    assert cq.is_factual_candidate("Ремонтът на улицата започна през октомври 2026 година.")


def test_the_extractor_returns_several_question_answering_claims():
    # §9/§10 — several candidates per page, each tied to a research question.
    questions = ["Кога и къде се е случило събитието?", "Колко струва ремонтът?"]
    page = [
        "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
        "Ремонтът започна през октомври 2026 година.",
        "Кметът на града заяви, че работите вървят по график.",
        cq.KNOWN_CHROME,
    ]
    claims = cq.select_candidate_claims(page, questions, limit=4)
    assert len(claims) >= 3
    assert all(cq.is_factual_candidate(c["text"]) for c in claims)
    assert any("amount" in c["dimensions"] for c in claims)
    assert any("event_schedule" in c["dimensions"] for c in claims)
    assert cq.KNOWN_CHROME not in {c["text"] for c in claims}
