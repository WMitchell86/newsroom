"""Offline contract tests for the LIVE research boundary."""

import pytest

from editor_assistant.drafting.evidence import validate_packet
from editor_assistant.workflow import research as r
from editor_assistant.workflow import transcripts as t


def test_opened_source_to_provenanced_evidence_packet(tmp_path):
    content = tmp_path / "official.txt"
    content.write_text("The Burgas event starts on 20 September 2026.\n", encoding="utf-8")
    bundle = r.make_bundle(
        research_id="LIV-TEST",
        query="Burgas event",
        editor_request="Find event",
        research_type="event",
    )
    url = "https://municipality.example/events/1"
    r.add_candidate(
        bundle,
        candidate_id="C1",
        title="Burgas event",
        url=url,
        source_name="Municipality",
        source_type="official_institution",
    )
    r.select_candidate(bundle, "C1", note="Future local event with preview lead time")
    r.open_source(
        bundle,
        source_id="S1",
        url=url,
        source_name="Municipality",
        source_type="official_institution",
        authority="PRIMARY",
        relevant_claims=[content.read_text(encoding="utf-8").strip()],
        content_reference=str(content),
    )
    r.set_duplicate_check(
        bundle,
        "NO_DUPLICATE",
        checked_urls=["https://chernomorie-bg.com/"],
        note="Stubbed duplicate search: no equivalent occurrence",
    )
    r.complete_bundle(bundle)
    refs = [r.make_fact_ref("S1", "line:1")]
    packet = r.provenanced_packet(
        bundle,
        evidence_id="EV-TEST",
        observed_at=bundle["local_date"],
        headline="Burgas event",
        facts=[
            {"id": "F1", "text": content.read_text(encoding="utf-8").strip(), "source_refs": refs}
        ],
    )
    validate_packet(packet)
    assert packet["source_url"] == url
    assert packet["facts"][0]["source_refs"] == refs
    assert r.validate_provenance(packet, bundle)
    assert r.is_clean_live_case(bundle)
    path = r.save_bundle(bundle, tmp_path / "bundle.json")
    first = path.read_bytes()
    assert r.load_bundle(path) == bundle
    r.save_bundle(bundle, path)
    assert path.read_bytes() == first


def _dup_bundle(tmp_path, dup_status):
    bundle = r.make_bundle(
        research_id="LIV-DUP", query="q", editor_request="e", research_type="event"
    )
    r.add_candidate(
        bundle,
        candidate_id="C1",
        title="t",
        url="https://x.example/1",
        source_name="s",
        source_type="organizer",
    )
    r.select_candidate(bundle, "C1")
    r.open_source(
        bundle,
        source_id="S1",
        url="https://x.example/1",
        source_name="s",
        source_type="organizer",
        authority="PRIMARY",
        relevant_claims=["claim"],
    )
    r.set_duplicate_check(bundle, dup_status)
    r.complete_bundle(bundle)
    return bundle


def test_duplicate_current_story_is_not_a_clean_live_case(tmp_path):
    assert r.is_clean_live_case(_dup_bundle(tmp_path, "NO_DUPLICATE"))
    assert r.is_clean_live_case(_dup_bundle(tmp_path, "RELATED_OLDER_COVERAGE"))
    assert not r.is_clean_live_case(_dup_bundle(tmp_path, "DUPLICATE_CURRENT_STORY"))


def test_deferred_duplicate_check_is_not_a_clean_live_case(tmp_path):
    assert not r.is_clean_live_case(_dup_bundle(tmp_path, "DUPLICATE_CHECK_DEFERRED"))


def test_transcript_claims_keep_timestamp_locator(tmp_path):
    record, pairs = r.ingest_transcript(
        "0:43 Единодушно се приема. 1:05 Колеги, имате ли коментари?",
        source_id="S-TR",
        source_name="Общински съвет Бургас - комисия",
    )
    located = dict(pairs)
    assert any(loc.startswith("t=") for loc in located.values())
    assert record["authority"] == "PRIMARY"
    assert record["source_type"] == "transcript"


def _bundle_with_claim(tmp_path, claim="Боксов клуб „Роял“ организира турнира на 18-20 септември."):
    bundle = r.make_bundle(
        research_id="LIV-PROV", query="q", editor_request="e", research_type="event"
    )
    r.add_candidate(
        bundle,
        candidate_id="C1",
        title="t",
        url="https://org.example/1",
        source_name="s",
        source_type="organizer",
    )
    r.select_candidate(bundle, "C1")
    r.open_source(
        bundle,
        source_id="S1",
        url="https://org.example/1",
        source_name="s",
        source_type="organizer",
        authority="PRIMARY",
        relevant_claims=[claim],
    )
    r.set_duplicate_check(bundle, "NO_DUPLICATE")
    r.complete_bundle(bundle)
    return bundle


def _packet(facts):
    return {
        "evidence_id": "EV-P",
        "source_url": "u",
        "source_type": "t",
        "observed_at": "2026-09-17",
        "source_headline": "h",
        "facts": facts,
        "people": [],
        "organizations": [],
        "places": [],
        "dates": [],
        "numbers": [],
        "quotes": [],
        "unknowns": [],
        "source_text": " ".join(f["text"] for f in facts),
    }


def test_claim_level_provenance_attaches_only_verifiable_links(tmp_path):
    from editor_assistant.drafting.evidence import make_fact

    bundle = _bundle_with_claim(tmp_path)
    packet = _packet([make_fact("F1", "Боксов клуб „Роял“ организира турнира на 18-20 септември.")])
    report = r.attach_bundle_refs(packet, bundle, strict=True)
    assert packet["facts"][0]["source_refs"] == [{"source_id": "S1", "locator": "claim:0"}]
    assert report["unmatched"] == [] and report["sources_used"] == ["S1"]


def test_unverifiable_fact_is_refused_not_invented(tmp_path):
    from editor_assistant.drafting.evidence import make_fact

    bundle = _bundle_with_claim(tmp_path)
    packet = _packet([make_fact("F1", "Залата е ремонтирана с 3 милиона лева.")])
    with pytest.raises(r.ResearchError, match="claim-level provenance"):
        r.attach_bundle_refs(packet, bundle, strict=True)
    assert "source_refs" not in packet["facts"][0]
    soft = r.attach_bundle_refs(packet, bundle, strict=False)
    assert soft["unmatched"] == ["F1"] and soft["attached"] == {}


def test_short_common_words_do_not_link_a_fact_to_a_claim(tmp_path):
    bundle = _bundle_with_claim(tmp_path, claim="Новият клуб отваря врати в центъра на града.")
    from editor_assistant.drafting.evidence import make_fact

    packet = _packet([make_fact("F1", "Новият клуб отваря врати в центъра и града.")])
    with pytest.raises(r.ResearchError):
        r.attach_bundle_refs(packet, bundle, strict=True)


def test_live_intake_with_bundle_attaches_provenance_and_refuses_untraceable(tmp_path):
    from editor_assistant.workflow import live

    bundle = _bundle_with_claim(tmp_path)
    path = r.save_bundle(bundle, tmp_path / "b.json")
    idea = live.new_idea(
        source_type="organizer",
        source_url="https://org.example/1",
        title="Турнир",
        what_changed="Нов турнир",
    )
    packet = live.build_live_packet(
        idea,
        evidence_id="EV-B",
        bundle_path=path,
        record={
            "url": "https://org.example/1",
            "headline": "Турнир",
            "body": "Боксов клуб „Роял“ организира турнира на 18-20 септември.",
        },
    )
    assert packet["facts"][0]["source_refs"][0]["source_id"] == "S1"
    assert packet["provenance"]["unmatched"] == []
    with pytest.raises(r.ResearchError):
        live.build_live_packet(
            idea,
            evidence_id="EV-B2",
            bundle_path=path,
            record={
                "url": "https://org.example/1",
                "headline": "Турнир",
                "body": "Залата е ремонтирана с 3 милиона лева.",
            },
        )


def test_mode_suggestion_and_reason_are_persisted_in_cases():
    from editor_assistant.workflow import cases

    draft = {
        "draft": {"headline": "h", "body": "b"},
        "lineage": {"mode_id": "MODE_BRIEF"},
        "semantic": {"pass": True},
    }
    case = cases.open_case(
        case_id="LIV-90",
        idea_id="IDEA-1",
        evidence_id="EV-1",
        draft=draft,
        voice="VOICE_HOUSE",
        mode="MODE_BRIEF",
        mode_suggested="MODE_EVENT_PREVIEW",
        suggestion_reason="future event: date/time/venue present",
    )
    assert case["mode_suggested"] == "MODE_EVENT_PREVIEW"
    assert case["mode_suggestion_reason"] == "future event: date/time/venue present"
    assert case["mode_changed"] is True
    assert (
        cases.open_case(
            case_id="LIV-91",
            idea_id="IDEA-2",
            evidence_id="EV-2",
            draft=draft,
            voice="VOICE_HOUSE",
            mode="MODE_BRIEF",
        )["mode_suggestion_reason"]
        == ""
    )


def test_lineage_problems_detects_shared_idea_and_missing_card():
    from editor_assistant.workflow import cases

    shared = {
        "case_id": "LIV-01",
        "track": cases.TRACK_LIVE,
        "idea_id": "IDEA-A",
        "evidence_id": "EV-A",
        "source_url": "u",
    }
    other = {
        "case_id": "LIV-03",
        "track": cases.TRACK_LIVE,
        "idea_id": "IDEA-A",
        "evidence_id": "EV-B",
        "source_url": "u2",
    }
    ideas = [{"idea_id": "IDEA-A", "source_url": "u", "status": "DRAFT_REQUESTED"}]
    evidence = [
        {"evidence_id": "EV-A", "idea_id": "IDEA-A"},
        {"evidence_id": "EV-B", "idea_id": "IDEA-A"},
    ]
    problems = cases.lineage_problems([shared, other], ideas, evidence)
    assert any("already used by LIV-01" in p for p in problems)
    assert any("LIV-03: idea card source_url does not match" in p for p in problems)
    mismatched = {
        "case_id": "LIV-03",
        "track": cases.TRACK_LIVE,
        "idea_id": "IDEA-A",
        "evidence_id": "EV-B",
        "source_url": "u",
    }
    assert any(
        "LIV-03: evidence row points at idea" in p
        for p in cases.lineage_problems(
            [mismatched], ideas, [{"evidence_id": "EV-B", "idea_id": "IDEA-OTHER"}]
        )
    )
    orphan = {
        "case_id": "LIV-05",
        "track": cases.TRACK_LIVE,
        "idea_id": "IDEA-MISSING",
        "evidence_id": "EV-C",
        "source_url": "u3",
    }
    assert any("LIV-05: no idea card" in p for p in cases.lineage_problems([orphan], ideas, []))
    assert any(
        "LIV-05: no evidence row for EV-C" in p for p in cases.lineage_problems([orphan], [], [])
    )
    lonely = cases.lineage_problems([], [], [{"evidence_id": "EV-ORPHAN", "idea_id": "IDEA-A"}])
    assert any("evidence row without a LIVE case" in p for p in lonely)
    clean = [{**shared}, {**other, "idea_id": "IDEA-B", "source_url": "u2"}]
    assert (
        cases.lineage_problems(
            clean,
            ideas + [{"idea_id": "IDEA-B", "source_url": "u2", "status": "DRAFT_REQUESTED"}],
            [
                {"evidence_id": "EV-A", "idea_id": "IDEA-A"},
                {"evidence_id": "EV-B", "idea_id": "IDEA-B"},
            ],
        )
        == []
    )


def test_snippet_source_cannot_back_a_promoted_fact(tmp_path):
    bundle = r.make_bundle(
        research_id="LIV-SNIP", query="q", editor_request="e", research_type="event"
    )
    r.add_candidate(
        bundle,
        candidate_id="C1",
        title="t",
        url="https://s.example/1",
        source_name="search",
        source_type="search_snippet",
    )
    r.select_candidate(bundle, "C1")
    r.open_source(
        bundle,
        source_id="S1",
        url="https://s.example/1",
        source_name="search",
        source_type="search_snippet",
        authority="DISCOVERY_ONLY",
        relevant_claims=["snippet line"],
    )
    r.set_duplicate_check(bundle, "NO_DUPLICATE")
    with pytest.raises(r.ResearchError):
        r.complete_bundle(bundle)  # no promotable source -> cannot complete


def test_council_decision_claim_requires_primary_official_provenance(tmp_path):
    packet = {
        "facts": [
            {
                "id": "F1",
                "text": "Общинският съвет прие бюджета.",
                "source_refs": [r.make_fact_ref("S1", "t=6:46")],
            }
        ]
    }
    bundle = _dup_bundle(tmp_path, "NO_DUPLICATE")
    # S1 is an organizer page (PRIMARY but not official) -> decision claim refused
    with pytest.raises(r.ResearchError):
        r.validate_council_claims(packet, bundle)
    bundle2 = _dup_bundle(tmp_path, "NO_DUPLICATE")
    bundle2["sources"][0]["source_type"] = "transcript"
    # M2S: an auto-caption transcript alone no longer carries a decision claim
    with pytest.raises(r.ResearchError, match="auto-caption transcript alone"):
        r.validate_council_claims(packet, bundle2)
    # ... but a human-verified transcript does (stronger provenance quality)
    bundle2["sources"][0]["transcript_trust_level"] = t.TRUST_HUMAN_VERIFIED
    assert r.validate_council_claims(packet, bundle2)
    # ... and an explicit corroboration marker vouches for the fragile claim
    bundle2["sources"][0]["transcript_trust_level"] = t.TRUST_AUTO_CAPTION
    packet["facts"][0]["corroborated"] = True
    assert r.validate_council_claims(packet, bundle2)
