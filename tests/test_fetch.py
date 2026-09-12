"""M1.2 fetcher tests: mocked HTTP only — the suite never touches the live net."""

from __future__ import annotations

import io
import urllib.error

import pytest

from editor_assistant.models import SourceDef
from editor_assistant.sources import fetcher as fetcher_mod
from editor_assistant.sources.fetcher import FetchError, fetch_bytes
from editor_assistant.sources.rss import PARSER_ID, parse_rss_feed


class _FakeHeaders:
    def __init__(self, content_type: str = "application/rss+xml"):
        self._ct = content_type

    def get_content_type(self):
        return self._ct


class _FakeResponse:
    def __init__(self, payload: bytes, *, url: str, content_type: str = "application/rss+xml"):
        self._io = io.BytesIO(payload)
        self._url = url
        self._headers = _FakeHeaders(content_type)
        self.status = 200

    def geturl(self):
        return self._url

    @property
    def headers(self):
        return self._headers

    def read(self, n: int = -1):
        return self._io.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


RSS_BYTES = (
    b"<?xml version='1.0'?><rss version='2.0'><channel>"
    b"<item><title>t</title><link>https://example.com/1</link>"
    b"<pubDate>Fri, 11 Sep 2026 08:30:00 +0300</pubDate></item>"
    b"</channel></rss>"
)
SOURCE = SourceDef(source_id="test-src", canonical_url="https://example.com/", parser=PARSER_ID)


def _patch(monkeypatch, response=None, *, error=None):
    def fake_urlopen(request, timeout=None):
        assert timeout is not None
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(fetcher_mod, "urlopen", fake_urlopen)


def test_successful_http_response(monkeypatch):
    _patch(
        monkeypatch,
        _FakeResponse(RSS_BYTES, url="https://example.com/feed.xml"),
    )
    out = fetch_bytes("https://example.com/feed.xml")
    assert out.status == 200 and out.payload == RSS_BYTES
    assert out.content_type == "application/rss+xml"


def test_timeout(monkeypatch):
    _patch(monkeypatch, error=TimeoutError("timed out"))
    with pytest.raises(FetchError, match="fetch failed"):
        fetch_bytes("https://example.com/feed.xml")


def test_http_error(monkeypatch):
    _patch(
        monkeypatch,
        error=urllib.error.HTTPError("https://example.com/x", 404, "NF", None, None),  # type: ignore[arg-type]
    )
    with pytest.raises(FetchError):
        fetch_bytes("https://example.com/x")


def test_empty_response(monkeypatch):
    _patch(monkeypatch, _FakeResponse(b"   ", url="https://example.com/feed.xml"))
    with pytest.raises(FetchError, match="empty"):
        fetch_bytes("https://example.com/feed.xml")


def test_oversized_response(monkeypatch):
    _patch(
        monkeypatch,
        _FakeResponse(b"<rss>" + b"x" * 100, url="https://example.com/feed.xml"),
    )
    with pytest.raises(FetchError, match="exceeds"):
        fetch_bytes("https://example.com/feed.xml", max_bytes=10)


def test_invalid_non_xml_response(monkeypatch):
    _patch(
        monkeypatch,
        _FakeResponse(
            b'{"not": "rss"}',
            url="https://example.com/feed.xml",
            content_type="application/json",
        ),
    )
    with pytest.raises(FetchError):
        fetch_bytes("https://example.com/feed.xml")


def test_parser_receives_raw_bytes_independently(monkeypatch):
    _patch(monkeypatch, _FakeResponse(RSS_BYTES, url="https://example.com/feed.xml"))
    from datetime import datetime, timezone

    out = fetch_bytes("https://example.com/feed.xml")
    items = parse_rss_feed(
        out.payload, source=SOURCE, fetched_at=datetime(2026, 9, 12, tzinfo=timezone.utc)
    )
    assert len(items) == 1 and items[0].title == "t"


def test_redirect_to_unrelated_host_blocked(monkeypatch):
    _patch(monkeypatch, _FakeResponse(RSS_BYTES, url="https://evil.example.net/feed.xml"))
    with pytest.raises(FetchError, match="unrelated host"):
        fetch_bytes("https://example.com/feed.xml")


def test_source_definition_passed_correctly():
    assert SOURCE.parser == PARSER_ID == "rss20"
    assert SOURCE.source_id == "test-src"
