"""M2S Track T: timestamped transcript foundation (audit/harness B1-B9).

Raw SRT is the authoritative input; exact timestamps are provenance; auto
captions are discovery evidence, not automatically publication-grade factual
authority. No committee or entity is encoded anywhere here.
"""

import pytest

from editor_assistant.workflow import transcripts as T

SRT = """1
00:00:01,000 --> 00:00:03,500
Комисията откри заседанието

2
00:00:03,000 --> 00:00:06,200
Комисията откри заседанието с всички членове

3
00:00:06,500 --> 00:00:09,000
Точка първа от дневния ред

4
00:00:09,200 --> 00:00:12,000
Докладна записка за финансиране

5
00:00:12,500 --> 00:00:15,000
Предложението е прието единодушно

6
00:00:15,500 --> 00:00:18,000
Разгледани са и две писма от граждани
"""


def test_standard_srt_parsing_preserves_everything():
    doc = T.load_srt(SRT, transcript_id="VID1", title="Тест")
    assert len(doc.segments) == 6
    first = doc.segments[0]
    assert first.cue_index == 1
    assert first.start_ms == 1_000
    assert first.end_ms == 3_500
    assert first.raw_text == "Комисията откри заседанието"
    assert doc.segments[4].start_ms == 12_500
    assert doc.trust_level == T.TRUST_AUTO_CAPTION  # default for YouTube orig


def test_exact_timestamp_becomes_locator_span():
    doc = T.load_srt(SRT, transcript_id="VID1")
    ids = [doc.segments[3].segment_id]
    span = doc.span(ids)
    assert span == [9_200, 12_000]
    assert T._ms_to_clock(span[0]) == "00:00:09.200"
    assert T._ms_to_clock(span[1]) == "00:00:12.000"


def test_malformed_srt_raises_instead_of_guessing():
    with pytest.raises(T.TranscriptError):
        T.load_srt("just some text without timestamps", transcript_id="BAD")
    bad = "1\n00:00:05,000 --> 00:00:02,000\nобърнат ред"
    with pytest.raises(T.TranscriptError):
        T.load_srt(bad, transcript_id="BAD2")


def test_overlapping_caption_normalization_keeps_provenance():
    doc = T.load_srt(SRT, transcript_id="VID1")
    spans = T.normalize_overlap(doc)
    # cue 1 and cue 2 overlap: the echo "Комисията откри заседанието" merges
    assert len(spans) == 5
    merged = spans[0]
    assert "всички членове" in merged["text"]
    assert merged["segment_ids"] == [
        doc.segments[0].segment_id,
        doc.segments[1].segment_id,
    ]
    assert merged["start_ms"] == 1_000
    assert merged["end_ms"] == 6_200
    # every original segment survives exactly once across spans
    all_ids = [sid for s in spans for sid in s["segment_ids"]]
    assert sorted(all_ids) == sorted(s.segment_id for s in doc.segments)


def test_raw_document_is_never_mutated_by_normalization():
    doc = T.load_srt(SRT, transcript_id="VID1")
    before = [s.normalized_text for s in doc.segments]
    T.normalize_overlap(doc)
    assert [s.normalized_text for s in doc.segments] == before


def test_auto_caption_decision_claim_requires_corroboration():
    doc = T.load_srt(SRT, transcript_id="VID1")
    risks = T.classify_claim_risks("Предложението е прието единодушно с 5 млн. лв.")
    assert T.RISK_DECISION in risks and T.RISK_MONEY in risks
    assert T.corroboration_required(doc, risks)


def test_negation_sensitive_claim_is_flagged_for_auto_caption():
    doc = T.load_srt(SRT, transcript_id="VID1")
    risks = T.classify_claim_risks("Комисията не прие предложението.")
    assert T.RISK_NEGATION in risks
    assert T.corroboration_required(doc, risks)


def test_human_verified_transcript_may_carry_decision_claims():
    doc = T.load_srt(SRT, transcript_id="VID1", trust_level=T.TRUST_HUMAN_VERIFIED)
    assert not T.corroboration_required(doc, [T.RISK_DECISION, T.RISK_MONEY])


def test_human_transcript_still_guards_negation_and_quotes():
    doc = T.load_srt(SRT, transcript_id="VID1", trust_level=T.TRUST_HUMAN_TRANSCRIPT)
    assert T.corroboration_required(doc, [T.RISK_NEGATION])
    assert not T.corroboration_required(doc, [T.RISK_MONEY])


def test_bad_trust_level_refused():
    with pytest.raises(T.TranscriptError):
        T.load_srt(SRT, transcript_id="V", trust_level="WHATSAPP_FORWARD")


def test_agenda_style_topic_segmentation():
    from editor_assistant.workflow import discovery as D

    doc = T.load_srt(SRT, transcript_id="VID1")
    topics = D.segment_topics(doc)
    # "Точка първа от дневния ред" must start a new deterministic topic
    labels = [t["label"] for t in topics]
    assert any("Точка първа" in label for label in labels)
    boundary_topics = [t for t in topics if t["deterministic_boundary"]]
    assert boundary_topics
    for topic in topics:
        assert set(topic["segment_ids"]) <= {s.segment_id for s in doc.segments}


def test_topic_segmentation_fallback_without_agenda_numbering():
    from editor_assistant.workflow import discovery as D

    plain = """1
00:00:00,000 --> 00:00:04,000
Обсъдихме текущи теми

2
00:00:04,500 --> 00:00:08,000
И още административни въпроси
"""
    doc = T.load_srt(plain, transcript_id="VID2")
    topics = D.segment_topics(doc)
    assert len(topics) == 1  # one neutral fallback topic, not fabricated splits
    assert not topics[0]["deterministic_boundary"]


def test_extracted_fact_refs_must_point_to_real_segments():
    """A fact referencing unknown segments is dropped, never guessed (B8)."""
    from editor_assistant.workflow import discovery as D

    doc = T.load_srt(SRT, transcript_id="VID1")
    topics = D.segment_topics(doc)
    good_topic = topics[0]
    fact = {
        "text": "констатация от транскрипта",
        "segment_ids": [good_topic["segment_ids"][0]],
        "risk_flags": [],
        "uncertain": False,
    }
    # monkeypatch the model call: the model proposes, the binder re-checks
    original = D._extract_facts_for_topic

    def fake_extract(topic, **kwargs):
        assert topic["topic_id"] == good_topic["topic_id"]
        return [dict(fact), {**fact, "segment_ids": ["VID1-s9999"]}]

    D._extract_facts_for_topic = fake_extract
    try:
        out = D.extract_facts(doc, [good_topic])
    finally:
        D._extract_facts_for_topic = original
    assert len(out) == 1  # the unknown-segment fact was dropped
    assert out[0]["segment_ids"] == fact["segment_ids"]
    assert out[0]["fact_id"].startswith("VID1-f")
    assert out[0]["span_ms"] == doc.span(fact["segment_ids"])


def test_candidate_angle_refs_point_to_real_fact_ids():
    """Model angle proposals lose references to unknown fact ids (B9)."""
    from editor_assistant.workflow import discovery as D

    facts = [
        {"fact_id": "V-f001", "text": "факт", "risk_flags": []},
        {"fact_id": "V-f002", "text": "факт 2", "risk_flags": []},
        {"fact_id": "V-f003", "text": "факт 3", "risk_flags": []},
    ]
    import json as _json
    import types

    payload = _json.dumps(
        {
            "angles": [
                {
                    "angle_id": "A1",
                    "title": "Т",
                    "new_proposition": "П",
                    "fact_ids": ["V-f001", "V-f999"],
                    "reason": "r",
                }
            ]
        }
    )

    def fake_call(prompt, **kwargs):
        return payload, {}

    original = D.gen.call_model
    D.gen.call_model = fake_call
    try:
        out = D.propose_angles(facts)
    finally:
        D.gen.call_model = original
    assert len(out) == 1
    assert out[0]["fact_ids"] == ["V-f001"]  # the unknown ref was stripped
    assert isinstance(D.gen, types.ModuleType)


def test_angle_floor_can_be_relaxed_explicitly():
    """1-2 real candidates may pass with min_candidates=1..2 (harness B9)."""
    from editor_assistant.workflow import angles as A

    packet = {
        "facts": [
            {"id": "F1", "text": "Общината прие новата програма вчера.", "scope": "current_event"},
        ]
    }
    candidate = {
        "angle_id": "A1",
        "title": "Нова програма",
        "new_proposition": "Общината прие нова програма вчера.",
        "fact_ids": ["F1"],
        "reason": "конкретно решение",
        "scores": {c: {"score": 2, "reason": "r", "fact_ids": ["F1"]} for c in A.CRITERIA},
    }
    with pytest.raises(A.AngleError):
        A.assess_angles(packet, [candidate])  # pilot floor stays 3
    assessment = A.assess_angles(packet, [candidate], min_candidates=1)
    assert assessment["status"] in (A.READY, A.NEEDS_RESEARCH, A.NO_ANGLE)
    assert assessment["min_candidates"] == 1
