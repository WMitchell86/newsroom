"""M2.3B packet-annotation contract: contradictory headline numbers.

EV-07 defect: source_headline claimed "11 държави" while fact EV-07-f03
enumerates 12 countries. Gemini drafts copied the headline figure and the
semantic judge flagged it as invented_number. source_headline is an editorial
surface, NOT evidence - headline figures that no fact/quote/number confirms
must be annotated into unknowns before drafting.
"""

from __future__ import annotations

import pytest

from editor_assistant.drafting.evidence import (
    ANNOTATION_PREFIX,
    EvidenceError,
    annotate_headline_number_conflicts,
    validate_packet,
)


def _packet(headline, facts, numbers=(), unknowns=()):
    return {
        "evidence_id": "EV-T",
        "source_url": "u",
        "source_type": "t",
        "observed_at": "2026-09-15",
        "source_headline": headline,
        "facts": list(facts),
        "people": [],
        "organizations": [],
        "places": [],
        "dates": [],
        "numbers": list(numbers),
        "quotes": [],
        "unknowns": list(unknowns),
        "source_text": " ".join(f["text"] for f in facts),
    }


def test_conflicting_headline_number_is_annotated():
    pkt = _packet(
        "Фестивалът събра 11 държави във Варна",
        [
            {
                "id": "f01",
                "text": "Ще участват над 500 участници от Германия, Полша и Турция.",
                "source_reference": "source_text",
            }
        ],
    )
    annotated = annotate_headline_number_conflicts(pkt)
    assert annotated == ["11"]
    assert len(pkt["unknowns"]) == 1
    assert pkt["unknowns"][0].startswith(ANNOTATION_PREFIX)
    assert "11" in pkt["unknowns"][0]
    assert validate_packet(pkt) is True


def test_confirmed_headline_number_is_not_annotated():
    pkt = _packet(
        "Над 149 млн. евро трансфери за общините",
        [
            {
                "id": "f01",
                "text": "Одобрени са над 149 млн. евро допълнителни трансфери.",
                "source_reference": "source_text",
            }
        ],
    )
    assert annotate_headline_number_conflicts(pkt) == []
    assert pkt["unknowns"] == []


def test_number_in_numbers_field_counts_as_confirmed():
    pkt = _packet(
        "Финалът е около 15:00 часа",
        [{"id": "f01", "text": "Финалът ще бъде в неделя.", "source_reference": "source_text"}],
        numbers=["15:00 часа"],
    )
    assert annotate_headline_number_conflicts(pkt) == []


def test_substring_numbers_do_not_count_as_confirmed():
    # "60" must not be treated as confirmed merely because "160" appears in a fact.
    pkt = _packet(
        "Ще участват 60 деца",
        [
            {
                "id": "f01",
                "text": "Събитието е с бюджет от 160 000 лева.",
                "source_reference": "source_text",
            }
        ],
    )
    assert annotate_headline_number_conflicts(pkt) == ["60"]


def test_annotation_is_idempotent():
    pkt = _packet(
        "Събраха се 11 отбора",
        [{"id": "f01", "text": "Турнирът е с 12 участника.", "source_reference": "source_text"}],
    )
    annotate_headline_number_conflicts(pkt)
    first = list(pkt["unknowns"])
    annotate_headline_number_conflicts(pkt)
    annotate_headline_number_conflicts(pkt)
    assert pkt["unknowns"] == first


def test_no_headline_means_no_annotation():
    pkt = _packet("", [{"id": "f01", "text": "Някакъв факт.", "source_reference": "source_text"}])
    assert annotate_headline_number_conflicts(pkt) == []
    assert pkt["unknowns"] == []


def test_annotated_packet_still_validates():
    pkt = _packet(
        "Събраха се 11 отбора и 500 зрители",
        [{"id": "f01", "text": "Турнирът е с 12 участника.", "source_reference": "source_text"}],
    )
    annotate_headline_number_conflicts(pkt)
    assert validate_packet(pkt) is True
    with pytest.raises(EvidenceError):
        pkt["facts"] = []
        validate_packet(pkt)
