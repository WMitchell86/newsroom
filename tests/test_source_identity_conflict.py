"""V1.2-G4.19 — a packet whose headline and body are different articles.

The real failure: a Story titled «Бургас влиза в новия Източен район за
планиране» was packed with the URL and body of a ЦИК piece about voting
machines, and the model drafted the ЦИК text under the park's headline. The
park's actual content never reached the writer at all, which is why every
draft felt thin no matter what the editor typed.

The owner chose to CONTINUE and be told, not to refuse: a feed that
rewords a headline is ordinary and refusing every such case would block
real work. So this marks, loudly, and only marks.

These tests exist mostly to pin the FALSE POSITIVES. An earlier version
compared all content words and flagged a perfectly good «ЦИК започна
проверката на машините за изборите» over a ЦИК body — naive word matching
does not survive Bulgarian inflection, and a warning that cries wolf is the
same as no warning at all.
"""

import pytest

from editor_assistant.drafting import evidence

CIK_BODY = (
    "Машините ще бъдат разпределени в страната съвместно с областните "
    "администрации и районните избирателни комисии. Районните избирателни "
    "комисии ще трябва да публикуват на сайтовете си информация кога и къде "
    "гражданите ще могат предварително да се запознаят с начина на гласуване "
    "с машина. ЦИК планира информацията да бъде достъпна и чрез Facebook "
    "страницата на комисията."
)
PARK_BODY = (
    "Община Бургас отвори втората фаза на индустриален и логистичен парк в "
    "Промишлена зона Юг-Запад, където осем български компании са закупили "
    "терени за производство на обща площ шестстотин декара."
)


def _packet(headline, body):
    return {"source_headline": headline, "source_text": body, "unknowns": []}


def test_the_measured_corruption_is_marked():
    packet = _packet("Бургас влиза в новия Източен район за планиране", CIK_BODY)
    assert evidence.annotate_source_identity_conflict(packet) is True
    note = packet["unknowns"][-1]
    assert evidence.IDENTITY_MISMATCH_MARKER in note
    assert "Бургас" in note and "източен" in note.casefold()


def test_a_reworded_headline_over_the_same_body_is_silent():
    """The false positive that a word-set comparison produced, pinned shut."""
    packet = _packet("ЦИК започна проверката на машините за изборите", CIK_BODY)
    assert evidence.annotate_source_identity_conflict(packet) is False
    assert packet["unknowns"] == []


def test_a_generic_sentence_opener_is_not_a_proper_noun():
    packet = _packet("Общият съвет започна проверката на машините", CIK_BODY)
    assert evidence.annotate_source_identity_conflict(packet) is False


def test_a_matching_pair_is_silent():
    packet = _packet("Бургас отвори индустриален парк", PARK_BODY)
    assert evidence.annotate_source_identity_conflict(packet) is False


def test_a_body_too_short_to_compare_is_left_alone():
    packet = _packet("Бургас влиза в нов Източен район", "Кратко.")
    assert evidence.annotate_source_identity_conflict(packet) is False


def test_the_marker_is_added_once_not_on_every_pass():
    packet = _packet("Бургас влиза в новия Източен район за планиране", CIK_BODY)
    assert evidence.annotate_source_identity_conflict(packet) is True
    first = len(packet["unknowns"])
    assert evidence.annotate_source_identity_conflict(packet) is True
    assert len(packet["unknowns"]) == first


def test_existing_unknowns_are_preserved():
    packet = _packet("Бургас влиза в новия Източен район за планиране", CIK_BODY)
    packet["unknowns"] = ["по-existing ъпрос"]
    evidence.annotate_source_identity_conflict(packet)
    assert packet["unknowns"][0] == "по-existing ъпрос"
