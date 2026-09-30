"""A URL is a transcript when the word is in it, not when the letters are.

V1.2-G4.36. Both call sites used `"transcript" in url.lower()`. Measured
consequence, before this file existed:

  https://example.bg/transcriptome-study  -> matched, so a biology article was
                                            treated as a council transcript.

The two sites were not equally affected, and that is why both are fixed here:

  - `angles.needs_angle_review` adds a review gate. Fail-closed, so harmless in
    effect — but every false gate teaches the editor to distrust a real one.
  - the promote bridge sets `source_type`, and `_transcript_trust` reads
    `source_type` to grant AUTO_CAPTION trust. A mislabel there ELEVATES trust.

The shared helper lives in `angles` so the two cannot drift into disagreeing
about what a transcript is.
"""

import pytest

from editor_assistant.workflow import angles


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.bg/transcriptome-study", False),
        ("https://example.bg/news-today", False),
        ("https://vestnik.example.test/council/transcript-12", True),
        ("https://vestnik.example.test/protokol-transcript", True),
        # `съвет` is a COUNCIL cue, not a transcript token. `url_is_transcript`
        # deliberately does not match it; `needs_angle_review` does, separately.
        # Asserting it here was my error, not the code's.
        ("https://vestnik.example.test/съвет-протокол", False),
        ("", False),
    ],
)
def test_url_is_transcript_matches_whole_tokens(url, expected):
    assert angles.url_is_transcript(url) is expected


@pytest.mark.parametrize(
    "packet,expected",
    [
        # The false positive this file exists for.
        (
            {"source_type": "opened_publication", "source_url": "https://example.bg/transcriptome-study"},
            False,
        ),
        ({"source_type": "opened_publication", "source_url": "https://example.bg/news-today"}, False),
        # A declared type is a fact about the material, whatever the URL says.
        ({"source_type": "council_transcript", "source_url": "https://x.bg/a"}, True),
        ({"source_type": "transcript", "source_url": ""}, True),
        # A real transcript URL still trips the gate.
        (
            {"source_type": "opened_publication", "source_url": "https://x.bg/council/transcript-12"},
            True,
        ),
        ({"source_type": "opened_publication", "source_url": "https://x.bg/съвет"}, True),
        # The editor-text attribution must never look like a transcript.
        ({"source_type": "opened_publication", "source_url": "workbench://story/s-abc"}, False),
    ],
)
def test_needs_angle_review_uses_type_equality_and_url_tokens(packet, expected):
    assert angles.needs_angle_review(packet) is expected


def test_the_transliteration_gap_is_unchanged_not_closed():
    """A recorded limitation, not a fix.

    A publisher slug like `obshtinski-svet` does not match, and did not match
    before this change either: the old test looked for the Cyrillic `съвет`
    anywhere in the string, which a transliterated slug never contained. Recording
    it here so nobody reads the token change as having closed it.
    """
    assert angles.url_is_transcript("https://x.bg/obshtinski-svet") is False
