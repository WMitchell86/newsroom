"""M1.2.1 tests: deterministic HTML description normalization (stdlib only)."""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from editor_assistant.models import SourceDef
from editor_assistant.sources.html_desc import normalize_description
from editor_assistant.sources.rss import PARSER_ID, item_to_dict, parse_rss_feed

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "rss_description_html.xml"
SOURCE = SourceDef(
    source_id="test-council-html",
    canonical_url="https://example.com/council",
    parser=PARSER_ID,
)
FETCHED_AT = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
ITEM_URL = "https://example.com/council/node/3637"


def _parse_one():
    (item,) = parse_rss_feed(FIXTURE.read_bytes(), source=SOURCE, fetched_at=FETCHED_AT)
    return item


def test_plain_text_description_unchanged():
    text, links = normalize_description("Община Бургас организира почистване.", base_url=ITEM_URL)
    assert text == "Община Бургас организира почистване."
    assert links == ()


def test_nested_html_becomes_readable_text():
    item = _parse_one()
    assert item.body_text is not None
    assert "<" not in item.body_text and ">" not in item.body_text
    assert "Докладна записка 18838" in item.body_text
    assert "Първи абзац с текст. Втори абзац" in item.body_text  # blocks stay separated


def test_whitespace_normalization_deterministic():
    a, _ = normalize_description("<p>Първи   абзац.</p>\n<p>Втори\tабзац.</p>", base_url=ITEM_URL)
    b, _ = normalize_description("<p>Първи абзац.</p><p>Втори абзац.</p>", base_url=ITEM_URL)
    assert a == b == "Първи абзац. Втори абзац."


def test_anchor_text_remains_in_body():
    item = _parse_one()
    assert "документ PDF" in (item.body_text or "")
    assert "приложение" in (item.body_text or "")


def test_absolute_href_extracted():
    item = _parse_one()
    assert "https://example.com/files/18838_sayt.pdf" in item.body_links


def test_relative_href_resolves_against_item_url():
    item = _parse_one()
    assert "https://example.com/files/annex.pdf" in item.body_links


def test_duplicate_links_emitted_once_and_ordered():
    item = _parse_one()
    assert item.body_links == (
        "https://example.com/files/18838_sayt.pdf",
        "https://example.com/files/annex.pdf",
    )


def test_link_order_deterministic():
    first = _parse_one().body_links
    second = _parse_one().body_links
    assert first == second and list(first) == sorted(first, key=list(first).index)


def test_missing_description_gives_none_and_empty_links():
    payload = (
        b"<rss><channel>"
        b"<item><title>t</title><link>https://example.com/1</link>"
        b"<pubDate>Fri, 11 Sep 2026 08:30:00 +0300</pubDate></item>"
        b"</channel></rss>"
    )
    (item,) = parse_rss_feed(payload, source=SOURCE, fetched_at=FETCHED_AT)
    assert item.body_text is None
    assert item.body_links == ()


def test_html_entities_decoded():
    text, _ = normalize_description("<p>a&amp;b&nbsp;c</p>", base_url=ITEM_URL)
    assert text == "a&b c"


def test_script_style_text_excluded():
    text, _ = normalize_description(
        "<p>видимо</p><script>evil()==1</script><style>.x{color:red}</style>",
        base_url=ITEM_URL,
    )
    assert text == "видимо"


def test_self_closing_script_does_not_suppress_later_text():
    """A self-closed <script/> has no end tag, so it must not open a skip region.

    Regression: it used to leave the skip depth permanently raised, silently
    dropping every remaining text chunk in the description.
    """
    text, _ = normalize_description(
        "<p>Преди</p><script/>ВАЖЕН ТЕКСТ<p>Край</p>", base_url=ITEM_URL
    )
    assert "ВАЖЕН ТЕКСТ" in text
    assert "Край" in text


def test_self_closing_style_does_not_suppress_later_text():
    text, _ = normalize_description("<p>Преди</p><style/>ВАЖЕН ТЕКСТ", base_url=ITEM_URL)
    assert "ВАЖЕН ТЕКСТ" in text


def test_repeated_parsing_equivalent():
    assert item_to_dict(_parse_one()) == item_to_dict(_parse_one())


def test_raw_inner_html_recovered_from_element():
    """ElementTree .text drops inner tags — parser must still see anchors."""
    root = ET.fromstring(
        "<item><description>see <a href='https://example.com/d.pdf'>doc</a></description></item>"
    )
    from editor_assistant.sources.rss import _raw_optional_text

    raw = _raw_optional_text(root, "description")
    assert raw is not None and "<a" in raw
    text, links = normalize_description(raw, base_url=ITEM_URL)
    assert text == "see doc"
    assert links == ("https://example.com/d.pdf",)
