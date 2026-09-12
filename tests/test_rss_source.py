"""M1.1 tests: one saved RSS fixture -> normalized SourceItems, no network."""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest

from editor_assistant.models import SourceDef
from editor_assistant.sources.rss import (
    PARSER_ID,
    SourceParseError,
    item_to_dict,
    parse_datetime,
    parse_rss_feed,
)

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "rss_burgas_municipality.xml"
SOURCE = SourceDef(
    source_id="burgas-municipality-press",
    canonical_url="https://www.burgas.bg/press",
    parser=PARSER_ID,
)
FETCHED_AT = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)

EXPECTED_TITLE = "Временна организация на движението по ул. „Александровска“ в събота"
EXPECTED_URL = "https://www.burgas.bg/press/2026/09/traffic-aleksandrovska"
EXPECTED_PUBLISHED = "2026-09-11T08:30:00+03:00"
EXPECTED_BODY = (
    "Община Бургас уведомява, че на 12 септември 2026 г. "
    "от 08:00 до 17:00 ч. ще бъде въведена временна организация "
    "на движението по ул. „Александровска“ поради ремонтни дейности."
)


def _parse() -> list:
    return parse_rss_feed(FIXTURE.read_bytes(), source=SOURCE, fetched_at=FETCHED_AT)


def test_valid_fixture_parses_successfully():
    items = _parse()
    assert len(items) == 2
    assert all(item.source_id == SOURCE.source_id for item in items)
    assert all(item.source_url == SOURCE.canonical_url for item in items)


def test_expected_title_extracted():
    assert _parse()[0].title == EXPECTED_TITLE


def test_expected_url_extracted():
    assert _parse()[0].item_url == EXPECTED_URL


def test_expected_timestamp_parsed_with_timezone():
    published = _parse()[0].published_at
    assert published is not None and published.tzinfo is not None
    assert published.isoformat() == EXPECTED_PUBLISHED


def test_body_text_normalized_deterministically():
    first = _parse()[0].body_text
    second = parse_rss_feed(
        FIXTURE.read_text(encoding="utf-8"), source=SOURCE, fetched_at=FETCHED_AT
    )[0].body_text
    assert first == EXPECTED_BODY
    assert second == EXPECTED_BODY  # bytes vs str input, same output


def test_missing_optional_value_stays_missing():
    minimal = _parse()[1]
    assert minimal.author is None
    assert minimal.body_text == "Община Бургас организира почистване на плажната ивица."


def test_malformed_fixture_fails_predictably():
    with pytest.raises(SourceParseError):
        parse_rss_feed(b"<rss><channel><item>", source=SOURCE, fetched_at=FETCHED_AT)
    with pytest.raises(SourceParseError):
        parse_rss_feed(b"   ", source=SOURCE, fetched_at=FETCHED_AT)
    with pytest.raises(SourceParseError):
        parse_rss_feed(
            b"<rss><channel><item><title>x</title></item></channel></rss>",
            source=SOURCE,
            fetched_at=FETCHED_AT,
        )  # missing <link>


def test_repeated_parsing_produces_equivalent_output():
    assert [item_to_dict(i) for i in _parse()] == [item_to_dict(i) for i in _parse()]


def test_pubdate_timezone_matrix():
    # (1) tz-aware +0300 parses and preserves the zone.
    aware = parse_datetime("Fri, 11 Sep 2026 08:30:00 +0300")
    assert aware is not None and aware.isoformat() == "2026-09-11T08:30:00+03:00"
    # (2) missing pubDate remains None — never invented.
    assert parse_datetime(None) is None
    assert parse_datetime("   ") is None
    # (3) naive pubDate fails predictably — no UTC/Sofia/local guess.
    with pytest.raises(SourceParseError):
        parse_datetime("Fri, 11 Sep 2026 08:30:00")
    # (4) malformed pubDate fails predictably.
    with pytest.raises(SourceParseError):
        parse_datetime("not a date at all")


def test_no_network_usage_in_sources_package():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "editor_assistant"
    forbidden = ("socket", "requests", "httpx", "urllib", "aiohttp")
    hits = [
        f"{p.name}: {line.strip()}"
        for p in sorted((src / "sources").glob("*.py"))
        for line in p.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith(("#", '"', "'"))
        for word in forbidden
        if word in line.lower()
    ]
    assert hits == [], f"network usage found: {hits}"
