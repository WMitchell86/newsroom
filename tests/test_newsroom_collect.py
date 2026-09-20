"""M4A collection runner tests — offline, every network call is injected.

The runner is the only place where a registry entry becomes collected material, so
these tests pin the two hard rules: `--dry-run` touches nothing, and one broken
source never stops the run. The collector adapters are stubbed; no HTTP happens.
"""

from __future__ import annotations

import pytest

from editor_assistant.workflow import cli, inbox_store, newsroom_run, sources_registry
from editor_assistant.workflow import search as search_mod

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Тестова емисия</title><link>https://feed.example/</link>
<item><title>Първа новина</title><link>https://feed.example/1</link>
<pubDate>Mon, 21 Sep 2026 06:00:00 +0300</pubDate><description>Описание на първата.</description></item>
<item><title>Втора новина</title><link>https://feed.example/2</link>
<pubDate>Mon, 21 Sep 2026 07:00:00 +0300</pubDate><description>Описание на втората.</description></item>
</channel></rss>
"""


class _Response:
    def __init__(self, payload):
        self.payload = payload


class _FakeProvider:
    def __init__(self, results, status=None):
        self.results = results
        self.status = status or (search_mod.SEARCH_OK if results else search_mod.NO_RESULTS)
        self.queries = []

    def search(self, query, *, count=10, **_kw):
        self.queries.append(query)
        return {"status": self.status, "results": self.results, "query": query}


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    """Isolated registry + inbox for every test (env is the only knob)."""
    monkeypatch.setenv("NEWSROOM_SOURCES_PATH", str(tmp_path / "sources.json"))
    monkeypatch.setenv("NEWSROOM_INBOX_PATH", str(tmp_path / "inbox.jsonl"))
    return tmp_path


@pytest.fixture
def registry(stores):
    sources_registry.add_source(
        path=stores / "sources.json",
        source_id="council-feed",
        name="Общински съвет",
        kind="official",
        collector="rss",
        url="https://feed.example/rss",
        priority="high",
        factual_authority=True,
    )
    sources_registry.add_source(
        path=stores / "sources.json",
        source_id="news-search",
        name="Търсене на новини",
        kind="aggregator",
        collector="google_news_rss",
        query="Бургас",
    )
    return stores


def _rss_fetcher(url):
    assert url == "https://feed.example/rss"
    return _Response(RSS_FEED.encode("utf-8"))


def _search_hits():
    return _FakeProvider(
        [
            {
                "title": "Намерена новина",
                "url": "https://media.example/story",
                "snippet": "Кратко описание",
                "published_at": "Mon, 21 Sep 2026 08:00:00 +0300",
                "source_name": "Медия",
            }
        ]
    )


def test_dry_run_makes_no_network_call_and_writes_nothing(registry, capsys):
    def explode(_url):
        raise AssertionError("dry-run must not fetch anything")

    summary = newsroom_run.collect(
        dry_run=True,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=explode,
    )
    assert summary["estimated_network_calls"] == 2  # one request per wired source
    assert summary["network_calls"] == 0
    assert summary["collected"] == 0 and summary["new"] == 0
    assert [row["status"] for row in summary["sources"]] == ["PLANNED", "PLANNED"]
    assert not (registry / "inbox.jsonl").exists()

    newsroom_run.print_summary(summary)
    out = capsys.readouterr().out
    assert "ПРОБЕН (без мрежа)" in out and "council-feed" in out


def test_collect_normalizes_items_and_dedupes_on_a_second_run(registry):
    summary = newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=_search_hits(),
    )
    assert summary["failed"] == 0
    assert summary["new"] == 3  # 2 feed items + 1 search hit
    assert summary["duplicate"] == 0

    items = inbox_store.read_items(registry / "inbox.jsonl")
    first = items[0]
    assert first["title"] and first["source_id"] in ("council-feed", "news-search")
    assert first["status"] == "NEW"
    assert first["source_kind"] and first["discovered_at"]

    again = newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=_search_hits(),
    )
    assert again["new"] == 0 and again["duplicate"] == 3
    assert len(inbox_store.read_items(registry / "inbox.jsonl")) == 3


def test_one_broken_source_never_stops_the_run(registry):
    def half_broken(url):
        raise OSError("feed is down")

    summary = newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=half_broken,
        news_provider=_search_hits(),
    )
    by_id = {row["source_id"]: row for row in summary["sources"]}
    assert by_id["council-feed"]["status"] == "FAILED"
    assert "OSError" in by_id["council-feed"]["reason"]
    assert by_id["news-search"]["status"] == "OK"
    assert summary["failed"] == 1
    # the healthy source still landed its item
    assert len(inbox_store.read_items(registry / "inbox.jsonl")) == 1


def test_a_search_provider_error_is_a_source_failure_not_a_silent_empty(registry):
    provider = _FakeProvider([], status=search_mod.SEARCH_PROVIDER_ERROR)
    summary = newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=provider,
    )
    by_id = {row["source_id"]: row for row in summary["sources"]}
    assert by_id["news-search"]["status"] == "FAILED"
    assert search_mod.SEARCH_PROVIDER_ERROR in by_id["news-search"]["reason"]


def test_unsupported_collector_is_reported_never_silently_skipped(stores):
    sources_registry.add_source(
        path=stores / "sources.json",
        source_id="youtube-chan",
        name="YouTube канал",
        kind="media",
        collector="youtube",
        url="https://www.youtube.com/@example",
    )
    summary = newsroom_run.collect(
        dry_run=True, path=stores / "sources.json", store=stores / "inbox.jsonl"
    )
    row = summary["sources"][0]
    assert row["status"] == "UNSUPPORTED" and "youtube" in row["reason"]
    assert summary["unsupported"] == 1
    assert summary["estimated_network_calls"] == 0


def test_a_malformed_candidate_is_counted_not_fatal(registry):
    provider = _FakeProvider(
        [
            {"title": "Без валиден адрес", "url": "", "snippet": ""},
            {"title": "Валидна", "url": "https://media.example/ok", "snippet": ""},
        ]
    )
    summary = newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=provider,
    )
    by_id = {row["source_id"]: row for row in summary["sources"]}
    assert by_id["news-search"]["items"] == 1
    assert by_id["news-search"]["skipped_invalid"] == 1
    assert summary["skipped_invalid"] == 1


def test_html_in_a_search_snippet_is_normalized_not_shown_as_markup(registry):
    """Google News descriptions are HTML; the inbox shows readable text."""
    provider = _FakeProvider(
        [
            {
                "title": "Новина",
                "url": "https://media.example/a",
                "snippet": '<a href="https://media.example/a">Новина</a>&nbsp;&nbsp;<font color="#6f6f6f">Медия</font>',
                "published_at": "Mon, 21 Sep 2026 08:00:00 +0300",
                "source_name": "Медия",
            }
        ]
    )
    newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=provider,
    )
    item = next(
        i
        for i in inbox_store.read_items(registry / "inbox.jsonl")
        if i["source_id"] == "news-search"
    )
    assert "<" not in item["summary"] and "&nbsp;" not in item["summary"]
    assert "Новина" in item["summary"] and "Медия" in item["summary"]


def test_disabled_and_muted_sources_are_not_collected(registry):
    sources_registry.set_status("news-search", "disabled", path=registry / "sources.json")
    plan = newsroom_run.plan(registry / "sources.json")
    assert [s["source_id"] for s in plan["sources"]] == ["council-feed"]

    sources_registry.set_status(
        "council-feed", "muted", muted_until="2026-12-31", path=registry / "sources.json"
    )
    assert newsroom_run.plan(registry / "sources.json")["sources"] == []


def test_source_selection_and_limit_are_honoured(registry):
    plan = newsroom_run.plan(registry / "sources.json", source_ids=["news-search"])
    assert [s["source_id"] for s in plan["sources"]] == ["news-search"]
    assert newsroom_run.plan(registry / "sources.json", limit=1)["sources"]
    assert len(newsroom_run.plan(registry / "sources.json", limit=1)["sources"]) == 1


def test_cli_dry_run_needs_no_network(registry, capsys):
    cli.main(["newsroom", "collect", "--dry-run"])
    out = capsys.readouterr().out
    assert "ПРОБЕН (без мрежа)" in out
    assert "council-feed" in out and "news-search" in out
    assert not (registry / "inbox.jsonl").exists()


def test_cli_exit_code_surfaces_a_partial_failure(registry, monkeypatch, capsys):
    """A partial failure exits non-zero so cron mail surfaces it."""
    monkeypatch.setattr(newsroom_run, "collect", lambda **_k: _summary_with_failures())
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["newsroom", "collect"])
    assert exit_info.value.code == 1
    assert "council-feed" in capsys.readouterr().out


def _summary_with_failures():
    return {
        "dry_run": False,
        "sources": [
            {
                "source_id": "council-feed",
                "collector": "rss",
                "status": "FAILED",
                "items": 0,
                "skipped_invalid": 0,
                "reason": "OSError: network down",
            }
        ],
        "by_collector": {"rss": 1},
        "estimated_network_calls": 1,
        "network_calls": 1,
        "collected": 0,
        "new": 0,
        "duplicate": 0,
        "failed": 1,
        "unsupported": 0,
        "skipped_invalid": 0,
    }
