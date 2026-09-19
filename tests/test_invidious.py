"""M3B.1 offline tests: Invidious fallback engine (every HTTP call is injected)."""

import json

from editor_assistant.workflow import invidious as I
from editor_assistant.workflow.transcripts import parse_srt

VTT = """WEBVTT
Kind: captions
Language: bg

00:00:01.000 --> 00:00:03.000
<c>Здравейте</c>

00:00:03.000 --> 00:00:05.000
Здравейте
добре дошли

00:00:05.000 --> 00:00:07.000
[Music]

00:00:07.000 --> 00:00:09.000
на комисията &amp; гости
"""


def _opener(meta, vtt=VTT, calls=None, failing=()):
    """Fake transport: the bare captions endpoint returns JSON, track URLs VTT."""

    def open_(url, timeout):
        if calls is not None:
            calls.append(url)
        for fragment in failing:
            if fragment in url:
                raise OSError(f"boom: {fragment}")
        if url.rstrip("/").endswith("/api/v1/captions/abc"):
            return json.dumps(meta).encode("utf-8")
        return vtt.encode("utf-8")

    return open_


def _meta(*tracks):
    return {"captions": list(tracks)}


TRACK_BG_AUTO = {
    "label": "Bulgarian (auto-generated)",
    "languageCode": "bg",
    "url": "/api/v1/captions/abc?label=auto",
}
TRACK_BG_MANUAL = {
    "label": "Bulgarian",
    "languageCode": "bg",
    "url": "/api/v1/captions/abc?label=manual",
}
TRACK_EN_MANUAL = {"label": "English", "languageCode": "en", "url": "/api/v1/captions/abc?lang=en"}


# ---------- VTT -> canonical SRT ----------


def test_vtt_is_converted_to_srt_that_the_frozen_parser_accepts():
    srt = I.vtt_to_srt(VTT)
    cues = parse_srt(srt)
    assert [c["raw_text"] for c in cues] == [
        "Здравейте",
        "добре дошли",
        "на комисията & гости",
    ]
    assert cues[0]["start_ms"] == 1000 and cues[0]["end_ms"] == 3000


def test_vtt_strips_header_note_and_markup():
    cues = I.parse_vtt(
        "WEBVTT\n\nNOTE this is a comment\nspanning lines\n\n"
        "STYLE\n::cue { color: white }\n\n"
        "00:00:01.000 --> 00:00:02.000\n<v Speaker>Hello <00:00:01.500>there</v>\n"
    )
    assert [c["text"] for c in cues] == ["Hello there"]


def test_vtt_drops_bracket_artifacts_and_rolling_caption_echoes():
    cues = I.parse_vtt(
        "00:00:00.000 --> 00:00:01.000\n[Applause]\n\n"
        "00:00:01.000 --> 00:00:02.000\nпет\n\n"
        "00:00:02.000 --> 00:00:03.000\nпет гласа\n\n"
        "00:00:03.000 --> 00:00:04.000\nпет гласа за\n"
    )
    assert [c["text"] for c in cues] == ["пет гласа за"]


def test_vtt_timestamps_without_hours_are_supported():
    cues = I.parse_vtt("00:01.000 --> 00:02.500\ntext\n")
    assert cues[0]["start_ms"] == 1000
    assert cues[0]["end_ms"] == 2500


def test_empty_vtt_produces_no_cues():
    assert I.vtt_to_srt("") == ""
    assert I.parse_vtt("WEBVTT\n\nNOTE nothing here\n") == []


# ---------- instance selection ----------


def test_manual_track_is_preferred_over_auto_for_the_same_language():
    result = I.fetch_captions(
        "abc",
        ("bg",),
        instances=["https://one.invalid"],
        opener=_opener(_meta(TRACK_BG_AUTO, TRACK_BG_MANUAL)),
    )
    assert result["caption_kind"] == I.KIND_MANUAL
    assert result["trust_level"] == "HUMAN_TRANSCRIPT"


def test_auto_track_stays_auto_caption_and_never_upgrades_trust():
    result = I.fetch_captions(
        "abc", ("bg",), instances=["https://one.invalid"], opener=_opener(_meta(TRACK_BG_AUTO))
    )
    assert result["caption_kind"] == I.KIND_AUTO
    assert result["trust_level"] == "AUTO_CAPTION"


def test_unrequested_languages_are_not_used():
    result = I.fetch_captions(
        "abc", ("bg",), instances=["https://one.invalid"], opener=_opener(_meta(TRACK_EN_MANUAL))
    )
    assert result["status"] == "unavailable"
    assert result["warnings"] == ()


def test_first_working_instance_wins_and_failures_are_kept_as_warnings():
    calls = []
    result = I.fetch_captions(
        "abc",
        ("bg",),
        instances=["https://dead.invalid", "https://one.invalid"],
        opener=_opener(_meta(TRACK_BG_AUTO), calls=calls, failing=("dead.invalid",)),
    )
    assert result["instance"] == "https://one.invalid"
    assert any("dead.invalid" in warning for warning in result["warnings"])
    assert any("dead.invalid" in url for url in calls)
    assert result["raw_srt"].startswith("1\n")


def test_total_fallback_failure_is_reported_with_its_reasons_not_swallowed():
    result = I.fetch_captions(
        "abc",
        ("bg",),
        instances=["https://dead.invalid"],
        opener=_opener(_meta(TRACK_BG_AUTO), failing=("dead.invalid",)),
    )
    assert result["status"] == "unavailable"
    assert any("dead.invalid" in warning for warning in result["warnings"])


def test_an_empty_caption_body_is_reported_as_such():
    result = I.fetch_captions(
        "abc",
        ("bg",),
        instances=["https://one.invalid"],
        opener=_opener(_meta(TRACK_BG_AUTO), vtt=""),
    )
    assert result["status"] == "unavailable"
    assert any("empty caption track" in warning for warning in result["warnings"])


def test_instance_count_is_bounded():
    calls = []
    I.fetch_captions(
        "abc",
        ("bg",),
        instances=[f"https://dead{i}.invalid" for i in range(20)],
        opener=_opener(_meta(TRACK_BG_AUTO), calls=calls, failing=("dead",)),
    )
    assert len(calls) <= I.MAX_INSTANCES
