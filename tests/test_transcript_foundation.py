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
    _by = {s.segment_id: s for s in doc.segments}
    _sup0 = _by[good_topic["segment_ids"][0]].raw_text
    fact = {
        "text": _sup0,
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


# ---------- V2 corrective pass: generic semantic regression tests (S20) ----------


def _rolling_srt(items):
    """Synthetic rolling captions: every cue overlaps the next (auto-caption style).

    Generic fixture: no committee/entity encoded; agenda wording varies.
    """
    blocks = []
    for i, (start, end, text) in enumerate(items, start=1):
        blocks.append(f"{i}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + "\n"


def test_v2_rolling_captions_six_agenda_items_stay_distinguishable():
    """S1: 6 overlapping agenda items must not collapse into one topic."""
    from editor_assistant.workflow import discovery as D

    ordinals = ["първа", "втора", "трета", "четвърта", "пета", "шеста"]
    items = []
    for i, ordinal in enumerate(ordinals):
        start_s = i * 10
        items.append(
            (
                f"00:{start_s:02d}:00,000",
                f"00:{start_s:02d}:08,000",
                f"Точка {ordinal} от дневния ред за обществено обсъждане",
            )
        )
        items.append(
            (
                f"00:{start_s:02d}:05,000",
                f"00:{start_s:02d}:14,000",
                "продължава обсъждането с подробности по предложението",
            )
        )
    doc = T.load_srt(_rolling_srt(items), transcript_id="S1")
    topics = D.segment_topics(doc)
    assert len(topics) == 6
    assert all(t["deterministic_boundary"] for t in topics)


def test_v2_boundary_inside_continuously_overlapping_captions():
    """Boundary cue in the MIDDLE of a giant merged span still splits."""
    from editor_assistant.workflow import discovery as D

    items = [
        ("00:00:00,000", "00:00:06,000", "откриване на заседанието и проверка на кворум"),
        ("00:00:05,000", "00:00:11,000", "проверка на кворум и преглед на материали"),
        ("00:00:10,000", "00:00:16,000", "преглед на материали и преминаваме към точка втора"),
        ("00:00:15,000", "00:00:21,000", "точка втора обсъжда ново предложение за услуга"),
    ]
    doc = T.load_srt(_rolling_srt(items), transcript_id="S1B")
    topics = D.segment_topics(doc)
    # boundary cue sits mid-span in cue 3 AND cue 4 opens with it: 3 topics
    assert len(topics) == 3
    assert topics[1]["deterministic_boundary"]
    assert topics[2]["deterministic_boundary"]


def test_v2_agenda_wording_variants_recover_boundaries():
    """S2: Първа точка / по второ / следва / последна точка variants."""
    from editor_assistant.workflow import discovery as D

    items = [
        ("00:00:00,000", "00:00:05,000", "Първа точка от дневния ред е доклад"),
        ("00:00:05,000", "00:00:10,000", "докладът се обсъжда подробно сега"),
        ("00:00:10,000", "00:00:15,000", "Продължаваме по второ предложение за услуги"),
        ("00:00:15,000", "00:00:20,000", "услугите се обсъждат с въпроси"),
        ("00:00:20,000", "00:00:25,000", "Следва предложение за финансиране"),
        ("00:00:25,000", "00:00:30,000", "финансирането се гласува единодушно"),
        ("00:00:30,000", "00:00:35,000", "Последната точка е разни въпроси"),
    ]
    doc = T.load_srt(_rolling_srt(items), transcript_id="S2")
    topics = D.segment_topics(doc)
    assert len(topics) == 4


def test_v2_fact_binding_wrong_number_rejected():
    from editor_assistant.workflow import discovery as D

    support = ["проектът за бюджет за 2026 година е приет с пет гласа за"]
    check = D.verify_fact_entailment("проектът е приет със седем гласа за", support)
    assert not check["entailed"]
    assert any("wrong_number" in f for f in check["failures"])


def test_v2_fact_binding_wrong_actor_rejected():
    from editor_assistant.workflow import discovery as D

    support = ["Димитър Николов внесе докладна записка за бюджета"]
    check = D.verify_fact_entailment("Иван Петров внесе докладна записка за бюджета", support)
    assert not check["entailed"]
    assert any("wrong_actor" in f for f in check["failures"])


def test_v2_fact_binding_negation_reversal_rejected():
    from editor_assistant.workflow import discovery as D

    support = ["комисията прие предложението единодушно"]
    check = D.verify_fact_entailment("комисията не прие предложението", support)
    assert not check["entailed"]
    assert any("negation" in f for f in check["failures"])


def test_v2_fact_binding_unsupported_paraphrase_rejected():
    from editor_assistant.workflow import discovery as D

    support = ["комисията откри заседанието с проверка на кворум"]
    check = D.verify_fact_entailment("космическа станция ще кацне на луната утре сутрин", support)
    assert not check["entailed"]
    assert any("unsupported_paraphrase" in f for f in check["failures"])


def test_v2_fact_binding_grounded_fact_passes():
    from editor_assistant.workflow import discovery as D

    support = ["проектът за бюджет за 2026 година е приет с пет гласа за"]
    check = D.verify_fact_entailment(
        "проектът за бюджет за 2026 година е приет с пет гласа за", support
    )
    assert check["entailed"]
    assert check["coverage"] >= 0.40


def test_v2_proposer_cannot_self_approve_semantic_status():
    from editor_assistant.workflow import discovery as D

    facts = [{"fact_id": "V-f001", "text": "комисията подкрепи предложението", "risk_flags": []}]
    import json as _json

    payload = _json.dumps(
        {
            "angles": [
                {
                    "angle_id": "A1",
                    "title": "Подкрепа",
                    "new_proposition": "Комисията подкрепи предложението.",
                    "fact_ids": ["V-f001"],
                    "reason": "r",
                    "semantic_status": "PUBLISHABLE_ANGLE",
                    "veto": False,
                    "scores": {"concrete_change": {"score": 2}},
                }
            ]
        }
    )

    def fake_call(prompt, **kwargs):
        assert "СТРОГО ЗАБРАНЕНО" in prompt
        return payload, {}

    original = D.gen.call_model
    D.gen.call_model = fake_call
    try:
        out = D.propose_angles(facts)
    finally:
        D.gen.call_model = original
    assert len(out) == 1
    assert out[0]["proposal_only"] is True
    for field in ("semantic_status", "veto", "scores"):
        assert field not in out[0]


def test_v2_independent_assessor_scores_all_criteria_and_vetoes_routine():
    from editor_assistant.workflow import discovery as D

    facts = [
        {
            "fact_id": "V-f001",
            "text": "комисията прие отчет за изпълнение на бюджета",
            "risk_flags": [],
        }
    ]
    proposals = [
        {
            "angle_id": "A1",
            "title": "Приет отчет",
            "new_proposition": "Комисията прие отчет.",
            "fact_ids": ["V-f001"],
            "reason": "решение",
        }
    ]
    candidates, _diag = D.assess_candidates(proposals, facts, use_model_judge=False)
    assert len(candidates) == 1
    from editor_assistant.workflow import angles as A

    assert set(candidates[0]["scores"]) == set(A.CRITERIA)
    assert candidates[0]["semantic_status"] == A.NOT_VIABLE


def test_v2_committee_supported_is_not_council_adopted():
    from editor_assistant.workflow import discovery as D

    facts = [
        {
            "fact_id": "V-f001",
            "text": "комисията подкрепи проекта за бюджет с пет гласа за",
            "risk_flags": [],
        }
    ]
    assert D.infer_procedural_status(facts[0]["text"]) == "COMMITTEE_SUPPORTED"
    scope = D.check_scope_entailment(
        "Общинският съвет прие бюджета",
        "Общинският съвет прие бюджета за 2026 година.",
        [facts[0]["text"]],
    )
    assert not scope["ok"]
    proposals = [
        {
            "angle_id": "A1",
            "title": "Общинският съвет прие бюджета",
            "new_proposition": "Общинският съвет прие бюджета за 2026 година.",
            "fact_ids": ["V-f001"],
            "reason": "r",
        }
    ]
    candidates, diag = D.assess_candidates(proposals, facts, use_model_judge=False)
    assert candidates[0]["semantic_status"] != "PUBLISHABLE_ANGLE"
    assert diag["scope_downgrades"] == ["A1"]


def test_v2_repeated_agenda_fingerprint_shared_across_recordings():
    from editor_assistant.workflow import discovery as D

    fp1 = D.topic_fingerprint("проектът за бюджет за 2026 година е приет с пет гласа за")
    fp2 = D.topic_fingerprint("проектът за бюджет за 2026 година е приет с пет гласа за")
    assert fp1 == fp2
    ctx = D.batch_repeated_context(
        {"V1": ["проектът за бюджет за 2026 година"], "V2": ["проектът за бюджет за 2026 година"]}
    )
    assert next(iter(ctx.values()))["count"] == 2
    facts = [
        {"fact_id": "V-f001", "text": "проектът за бюджет за 2026 година е приет", "risk_flags": []}
    ]
    proposals = [
        {
            "angle_id": "A1",
            "title": "Бюджет",
            "new_proposition": "Проектът за бюджет за 2026 година е приет с пет гласа.",
            "fact_ids": ["V-f001"],
            "reason": "r",
        }
    ]
    cands_plain, _ = D.assess_candidates(proposals, facts, use_model_judge=False)
    cands_rep, _ = D.assess_candidates(
        proposals, facts, use_model_judge=False, repeated={"repeated_agenda_item": True}
    )
    plain_total = sum(v["score"] for v in cands_plain[0]["scores"].values())
    rep_total = sum(v["score"] for v in cands_rep[0]["scores"].values())
    assert rep_total <= plain_total


def test_v2_readiness_orchestrator_invoked_angle_status_is_not_readiness():
    """Gap F + §13: the real orchestrator runs, with no invented padding topics."""
    from editor_assistant.workflow import angles as A
    from editor_assistant.workflow import discovery as D
    from editor_assistant.workflow import transcripts as _T

    facts = [
        {
            "fact_id": "V-f001",
            "text": "комисията подкрепи нов дневен център за възрастни хора с пет гласа за",
            "risk_flags": [],
        }
    ]
    proposals = [
        {
            "angle_id": "A1",
            "title": "Нов дневен център",
            "new_proposition": "Комисията подкрепи нов дневен център за възрастни хора.",
            "fact_ids": ["V-f001"],
            "reason": "конкретна услуга",
        }
    ]
    candidates, _diag = D.assess_candidates(proposals, facts, use_model_judge=False)
    assert len(candidates) == 1  # one real candidate - padding topics are forbidden
    doc = _T.load_srt(
        "1\n00:00:01,000 --> 00:00:03,000\nкомисията подкрепи нов дневен център", transcript_id="VR"
    )
    packet_facts = [
        {"id": f["fact_id"], "text": f["text"], "scope": "current_event"} for f in facts
    ]
    assessment = A.assess_angles(
        {"facts": packet_facts, "source_type": "transcript", "source_text": facts[0]["text"]},
        candidates,
        min_candidates=1,
    )
    assert assessment["status"] in (A.READY, A.NEEDS_RESEARCH, A.NO_ANGLE)
    packet = D.build_evidence_packet(doc, facts, assessment)
    readiness = D.run_readiness(packet)  # re-verifies through angles.check_angle_gate
    assert readiness["status"] in (
        "DRAFT_READY",
        "RESEARCH_MORE",
        "NO_PUBLISHABLE_ANGLE",
        "EDITOR_DECISION_REQUIRED",
    )
    assert readiness["status"] != assessment["status"] or assessment["status"] != "ANGLE_SELECTED"


def test_v2_relaxed_angle_floor_survives_gate_reverification():
    """The recorded opt-in floor is re-applied on verification, never loosened silently.

    `check_angle_gate` never trusts a cached status: it recomputes scores,
    grounding and semantic viability. The candidate-count floor it recomputes
    under must be the one the assessment was judged under (persisted as
    `min_candidates` only when it differs from the pilot default 3) - otherwise
    a genuine 1-2 candidate transcript assessment can never reach the real
    readiness orchestrator.
    """
    from editor_assistant.workflow import angles as A

    packet = {
        "facts": [
            {"id": "F1", "text": "Общината прие новата програма вчера.", "scope": "current_event"}
        ],
        "source_type": "transcript",
    }
    candidate = {
        "angle_id": "A1",
        "title": "Нова програма",
        "new_proposition": "Общината прие нова програма вчера.",
        "fact_ids": ["F1"],
        "reason": "конкретно решение",
        "scores": {c: {"score": 2, "reason": "r", "fact_ids": ["F1"]} for c in A.CRITERIA},
    }
    relaxed = A.assess_angles(packet, [candidate], min_candidates=1)
    assert relaxed["min_candidates"] == 1
    recheck = A.check_angle_gate({**packet, "editorial_assessment": relaxed})
    assert recheck["status"] == relaxed["status"]
    assert recheck["selected_angle_id"] == relaxed["selected_angle_id"]
    # Without the recorded floor the pilot default stands: one candidate is refused.
    unrecorded = {k: v for k, v in relaxed.items() if k != "min_candidates"}
    with pytest.raises(A.AngleError):
        A.check_angle_gate({**packet, "editorial_assessment": unrecorded})
    # A tampered/absurd floor still fails closed.
    with pytest.raises(A.AngleError):
        A.check_angle_gate({**packet, "editorial_assessment": {**relaxed, "min_candidates": 0}})


def test_v2_zero_fact_topics_are_attributed_not_silently_empty():
    """Quota/parse failures must be distinguishable from an empty topic (S4).

    `extract_facts` never raises on a model outage (a batch must survive it),
    but it may not report the outage as "this topic had no facts" either: every
    zero-yield topic is recorded on `extract_facts.skipped_topics` with a reason.
    """
    from editor_assistant.workflow import discovery as D
    from editor_assistant.workflow import transcripts as _T

    doc = _T.load_srt(
        "1\n00:00:01,000 --> 00:00:03,000\nТочка първа от дневния ред\n\n"
        "2\n00:00:03,500 --> 00:00:06,000\nДокладна записка за финансиране\n",
        transcript_id="VSKIP",
    )
    topics = D.segment_topics(doc)
    assert topics
    topic_ids = {t["topic_id"] for t in topics}
    original = D.gen.call_model

    def failing_call(prompt, **kwargs):
        raise RuntimeError("429 quota exceeded")

    def unparsable_call(prompt, **kwargs):
        return "няма json тук", {}

    def empty_call(prompt, **kwargs):
        return "", {}

    try:
        D.gen.call_model = failing_call
        assert D.extract_facts(doc, topics) == []
        outage = D.extract_facts.skipped_topics
        assert {s["topic_id"] for s in outage} == topic_ids
        # M3D Part E: 429 is a rate limit, not a generic call failure.
        assert all(s["reason"].startswith("RATE_LIMITED") for s in outage)

        D.gen.call_model = unparsable_call
        assert D.extract_facts(doc, topics) == []
        assert {s["reason"] for s in D.extract_facts.skipped_topics} == {"NO_JSON"}

        D.gen.call_model = empty_call
        assert D.extract_facts(doc, topics) == []
        # M3D Part E: a truly empty completion is distinct from valid-but-empty.
        assert {s["reason"] for s in D.extract_facts.skipped_topics} == {"EMPTY_MODEL_OUTPUT"}
    finally:
        D.gen.call_model = original
        D.extract_facts.skipped_topics = []
