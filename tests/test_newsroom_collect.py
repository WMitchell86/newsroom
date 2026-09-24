"""M4A collection runner tests — offline, every network call is injected.

The runner is the only place where a registry entry becomes collected material, so
these tests pin the two hard rules: `--dry-run` touches nothing, and one broken
source never stops the run. The collector adapters are stubbed; no HTTP happens.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from editor_assistant.workflow import (
    blocked_domains,
    cli,
    inbox_store,
    newsroom_run,
    source_health,
    sources_registry,
)
from editor_assistant.workflow import search as search_mod

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

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
    """Isolated registry + inbox + operational state for every test (env only)."""
    monkeypatch.setenv("NEWSROOM_SOURCES_PATH", str(tmp_path / "sources.json"))
    monkeypatch.setenv("NEWSROOM_INBOX_PATH", str(tmp_path / "inbox.jsonl"))
    monkeypatch.setenv("NEWSROOM_DIR", str(tmp_path))
    # Pin the runner clock: the fixtures are dated 2026-09-21 and the 72 h news
    # window must not rotate them out of range as the real date advances.
    monkeypatch.setattr(newsroom_run, "_now", lambda: NOW)
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


# ---------- M4A.1: blocked domains, cadence, health, bootstrap, lock ----------


def _provider(urls):
    return _FakeProvider(
        [
            {
                "title": f"Новина {index}",
                "url": url,
                "snippet": "описание",
                "published_at": "Mon, 21 Sep 2026 08:00:00 +0300",
                "source_name": "Медия",
            }
            for index, url in enumerate(urls, start=1)
        ]
    )


def test_blocked_domain_is_filtered_before_the_inbox(registry):
    blocked_domains.add_domain("flagman.bg")
    summary = newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=_provider(
            ["https://flagman.bg/1", "https://m.flagman.bg/2", "https://ok.example/3"]
        ),
    )
    by_id = {row["source_id"]: row for row in summary["sources"]}
    assert by_id["news-search"]["blocked_filtered"] == 2
    assert summary["blocked_filtered"] == 2
    urls = {item["url"] for item in inbox_store.read_items(registry / "inbox.jsonl")}
    assert urls == {"https://feed.example/1", "https://feed.example/2", "https://ok.example/3"}


def test_a_blocked_publisher_is_filtered_from_a_google_news_fixture(registry):
    """Google News links are news.google.com redirects, so the publisher domain
    carried on the result itself is what the policy must act on."""
    blocked_domains.add_domain("flagman.bg")
    provider = _FakeProvider(
        [
            {
                "title": "Новина от Флагман",
                "url": "https://news.google.com/rss/articles/CBMi1",
                "snippet": "текст",
                "published_at": "Mon, 21 Sep 2026 08:00:00 +0300",
                "source_name": "Флагман",
                "source_url": "https://www.flagman.bg",
            },
            {
                "title": "Новина от БНР",
                "url": "https://news.google.com/rss/articles/CBMi2",
                "snippet": "текст",
                "published_at": "Mon, 21 Sep 2026 08:00:00 +0300",
                "source_name": "БНР",
                "source_url": "https://bnr.bg",
            },
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
    assert by_id["news-search"]["blocked_filtered"] == 1
    titles = {item["title"] for item in inbox_store.read_items(registry / "inbox.jsonl")}
    assert "Новина от БНР" in titles
    assert "Новина от Флагман" not in titles


def test_a_direct_blocked_source_is_refused_and_never_fetched(stores):
    blocked_domains.add_domain("flagman.bg")
    sources_registry.add_source(
        path=stores / "sources.json",
        source_id="blocked-feed",
        name="Забранена емисия",
        kind="media",
        collector="rss",
        url="https://flagman.bg/rss",
    )

    def explode(_url):
        raise AssertionError("a blocked source must never be fetched")

    summary = newsroom_run.collect(
        dry_run=False,
        path=stores / "sources.json",
        store=stores / "inbox.jsonl",
        fetch_bytes=explode,
    )
    row = summary["sources"][0]
    assert row["status"] == newsroom_run.STATUS_BLOCKED
    assert "забранен" in row["reason"]
    assert (
        not (stores / "inbox.jsonl").exists()
        or inbox_store.read_items(stores / "inbox.jsonl") == []
    )


def test_health_records_ok_and_empty_distinctly(registry):
    newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=_search_hits(),
    )
    assert source_health.describe("council-feed")["last_status"] == "OK"

    empty = _FakeProvider([])
    newsroom_run.collect(
        dry_run=False,
        path=registry / "sources.json",
        store=registry / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=empty,
    )
    record = source_health.describe("news-search")
    assert record["last_status"] == "EMPTY" and record["last_success_at"]


def test_daily_cadence_is_operational_and_force_overrides_it(stores):
    sources_registry.add_source(
        path=stores / "sources.json",
        source_id="daily-feed",
        name="Дневна емисия",
        kind="official",
        collector="rss",
        url="https://feed.example/rss",
        cadence="daily",
    )
    first = newsroom_run.collect(
        dry_run=False,
        path=stores / "sources.json",
        store=stores / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
    )
    assert first["new"] == 2

    plan = newsroom_run.plan(stores / "sources.json")
    assert plan["sources"] == []
    assert plan["excluded"]["cadence"] == ["daily-feed"]

    forced = newsroom_run.plan(stores / "sources.json", force=True)
    assert [s["source_id"] for s in forced["sources"]] == ["daily-feed"]

    again = newsroom_run.collect(
        dry_run=False,
        path=stores / "sources.json",
        store=stores / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
    )
    assert again["new"] == 0 and again["cadence_skipped"] == 1


def test_dry_run_reports_muted_and_disabled_without_a_network_call(registry):
    sources_registry.set_status("news-search", "disabled", path=registry / "sources.json")
    plan = newsroom_run.plan(registry / "sources.json")
    assert plan["excluded"]["disabled"] == ["news-search"]
    assert plan["estimated_network_calls"] == 1


# ---------- M4A.1 correction: publisher authority vs discovery source ----------


def _publisher_registry(stores):
    """An official monitor plus three publishers with different standing."""
    path = stores / "sources.json"
    sources_registry.add_source(
        path=path,
        source_id="official-monitor",
        name="Община Бургас (наблюдение)",
        kind="official",
        domain="burgas.bg",
        collector="google_news_rss",
        query="Община Бургас",
        factual_authority=True,
    )
    sources_registry.add_source(
        path=path,
        source_id="bnr-burgas",
        name="БНР Бургас",
        kind="media",
        domain="bnr.bg",
        collector="google_news_rss",
        query="БНР Бургас",
        factual_authority=True,
        status="disabled",  # only its authority policy matters here
    )
    sources_registry.add_source(
        path=path,
        source_id="darik-burgas",
        name="DarikNews Бургас",
        kind="regional",
        domain="dariknews.bg",
        collector="google_news_rss",
        query="Darik Бургас",
        factual_authority=False,
        status="disabled",
    )
    return path


def _gnews_result(index, publisher_domain):
    return {
        "title": f"Новина {index}",
        "url": f"https://news.google.com/rss/articles/CBMi{index}",
        "snippet": "текст",
        "published_at": "Mon, 21 Sep 2026 08:00:00 +0300",
        "source_name": f"Издател {index}",
        "source_url": f"https://{publisher_domain}",
    }


def test_item_authority_comes_from_the_publisher_not_the_monitoring_source(stores):
    """Acceptance test: an official monitor must not lend its authority to a
    third-party article it merely surfaced."""
    path = _publisher_registry(stores)
    provider = _FakeProvider(
        [
            _gnews_result(1, "bnr.bg"),
            _gnews_result(2, "dariknews.bg"),
            _gnews_result(3, "burgas.bg"),
            _gnews_result(4, "unknown-blog.example"),
        ]
    )
    newsroom_run.collect(
        dry_run=False,
        path=path,
        store=stores / "inbox.jsonl",
        fetch_bytes=_rss_fetcher,
        news_provider=provider,
    )
    items = {
        item["publisher_domain"]: item for item in inbox_store.read_items(stores / "inbox.jsonl")
    }

    # discovered by the official monitor, published by БНР -> БНР's policy (media)
    bnr = items["bnr.bg"]
    assert bnr["source_id"] == "official-monitor"
    assert bnr["source_kind"] == "official"  # how it was found
    assert bnr["publisher_kind"] == "media"  # who published it
    assert bnr["factual_authority"] is True

    # a monitoring-only publisher never inherits the discovery source's authority
    darik = items["dariknews.bg"]
    assert darik["source_kind"] == "official"
    assert darik["publisher_kind"] == "regional"
    assert darik["factual_authority"] is False

    # the configured source's own domain -> official authority eligible
    own = items["burgas.bg"]
    assert own["publisher_kind"] == "official" and own["factual_authority"] is True

    # an unapproved publisher gets no authority
    unknown = items["unknown-blog.example"]
    assert unknown["publisher_kind"] == "" and unknown["factual_authority"] is False


def test_a_shared_publisher_domain_with_conflicting_policy_fails_closed(stores):
    """M4B.1 F5: authority must never be decided by source_id order."""
    path = stores / "sources.json"
    sources_registry.add_source(
        path=path,
        source_id="aaa-publisher",
        name="Издател А",
        kind="official",
        domain="clash.bg",
        collector="google_news_rss",
        query="Издател А",
        factual_authority=True,
    )
    sources_registry.add_source(
        path=path,
        source_id="zzz-publisher",
        name="Издател Б",
        kind="official",
        domain="clash.bg",
        collector="google_news_rss",
        query="Издател Б",
        factual_authority=False,
    )
    with pytest.raises(sources_registry.RegistryError, match="conflicting publisher policy"):
        newsroom_run.authority_by_domain(path)

    # Same domain + same policy is explicitly allowed (the shipped catalogue does
    # this for burgas.bg) and resolves to one authority row.
    sources_registry.set_factual_authority("zzz-publisher", True, path=path)
    by_domain = newsroom_run.authority_by_domain(path)
    assert by_domain["clash.bg"]["factual_authority"] is True

    # A conflicting kind is refused too, even when the authority flag agrees.
    sources_registry.update_source("zzz-publisher", kind="media", path=path)
    with pytest.raises(sources_registry.RegistryError, match="conflicting publisher policy"):
        newsroom_run.authority_by_domain(path)


def test_a_declared_blocked_domain_refuses_an_otherwise_innocent_query(stores):
    """M4B.1 F6: the registry `domain` field is inspected before any network call."""
    blocked_domains.add_domain("flagman.bg")
    entry = {
        "source_id": "sneaky-query",
        "url": "",
        "query": "някаква заявка без име на домейн",
        "domain": "flagman.bg",
    }
    reason = blocked_domains.blocked_reason(entry)
    assert reason and "забранен" in reason

    sources_registry.add_source(
        path=stores / "sources.json",
        source_id="sneaky-query",
        name="Заявка",
        kind="media",
        domain="flagman.bg",
        collector="google_news_rss",
        query="някаква заявка без име на домейн",
    )

    def explode(_url):
        raise AssertionError("a blocked source must never be fetched")

    summary = newsroom_run.collect(
        dry_run=False,
        path=stores / "sources.json",
        store=stores / "inbox.jsonl",
        fetch_bytes=explode,
    )
    assert summary["sources"][0]["status"] == newsroom_run.STATUS_BLOCKED


def test_resolve_authority_is_suffix_aware_and_defaults_to_monitoring_only(stores):
    path = _publisher_registry(stores)
    by_domain = newsroom_run.authority_by_domain(path)
    assert set(by_domain) == {"burgas.bg", "bnr.bg", "dariknews.bg"}

    sub = newsroom_run.resolve_authority({"source_url": "https://news.bnr.bg/x"}, by_domain)
    assert sub["publisher_kind"] == "media" and sub["factual_authority"] is True

    none = newsroom_run.resolve_authority({"url": "https://news.google.com/rss/x"}, by_domain)
    assert none == {
        "publisher_domain": "news.google.com",
        "publisher_kind": "",
        "factual_authority": False,
    }


def test_a_direct_feed_is_its_own_publisher_without_a_domain_field(stores):
    """A direct source's own URL host is the authority key (no extra config)."""
    sources_registry.add_source(
        path=stores / "sources.json",
        source_id="direct-feed",
        name="Директна емисия",
        kind="official",
        collector="rss",
        url="https://feed.example/rss",
        factual_authority=True,
    )
    by_domain = newsroom_run.authority_by_domain(stores / "sources.json")
    assert "feed.example" in by_domain
    resolved = newsroom_run.resolve_authority({"url": "https://feed.example/1"}, by_domain)
    assert resolved["publisher_kind"] == "official" and resolved["factual_authority"] is True


def test_bootstrap_lookback_and_cap_for_news():
    now = NOW
    candidates = [
        {"published_at": "2026-09-20T06:00:00Z", "url": "https://x/a"},
        {"published_at": "2026-09-01T06:00:00Z", "url": "https://x/old"},
    ]
    kept, dropped = newsroom_run.select_candidates({}, candidates, bootstrap=True, now=now)
    assert [c["url"] for c in kept] == ["https://x/a"]
    assert dropped == 1

    many = [{"published_at": "2026-09-20T06:00:00Z", "url": f"https://x/{i}"} for i in range(15)]
    kept, dropped = newsroom_run.select_candidates({}, many, bootstrap=True, now=now)
    assert len(kept) == newsroom_run.BOOTSTRAP_MAX_NEWS and dropped == 5

    # not a bootstrap run: only the per-source cap applies
    capped = [
        {"published_at": "2026-09-20T06:00:00Z", "url": f"https://x/{i}"}
        for i in range(newsroom_run.MAX_ITEMS_PER_SOURCE + 8)
    ]
    kept, _ = newsroom_run.select_candidates({}, capped, bootstrap=False, now=now)
    assert len(kept) == newsroom_run.MAX_ITEMS_PER_SOURCE


def test_a_real_event_date_gets_the_event_window_but_a_publication_time_does_not():
    """M4B.1 F2: calendar semantics need a real event date, not published_at."""
    # A future publication time is NOT an event date: with no event_at this is an
    # ordinary news source, so the old ±45-day publication window no longer
    # pretends to understand the event.
    published_only = [
        {"published_at": "2026-10-20T06:00:00Z", "url": "https://x/event"},
        {"published_at": "2026-01-01T06:00:00Z", "url": "https://x/old"},
    ]
    kept, dropped = newsroom_run.select_candidates(
        {"calendar": True}, published_only, bootstrap=True, now=NOW
    )
    assert [c["url"] for c in kept] == ["https://x/event"]
    assert dropped == 1

    # A genuine event date gets the bounded event window, even when the article
    # that announced it is older than the news lookback.
    real_events = [
        {
            "published_at": "2026-06-01T06:00:00Z",
            "event_at": "2026-10-20T06:00:00Z",
            "url": "https://x/future-event",
        },
        {
            "published_at": "2026-06-01T06:00:00Z",
            "event_at": "2026-01-01T06:00:00Z",
            "url": "https://x/past-event",
        },
    ]
    kept, dropped = newsroom_run.select_candidates(
        {"calendar": True}, real_events, bootstrap=True, now=NOW
    )
    assert kept == [real_events[0]] and dropped == 1


def test_undated_candidates_never_empty_a_source():
    undated = [{"url": f"https://x/{i}"} for i in range(3)]
    kept, dropped = newsroom_run.select_candidates({}, undated, bootstrap=True, now=NOW)
    assert kept == undated and dropped == 0


def test_rolling_recency_applies_on_every_run():
    """M4B.1 F1: run 2 must not backfill what run 1 deliberately excluded."""
    recent = [
        {"published_at": "2026-09-20T06:00:00Z", "url": f"https://x/new/{i}"} for i in range(10)
    ]
    old = [{"published_at": "2026-09-10T06:00:00Z", "url": f"https://x/old/{i}"} for i in range(10)]
    candidates = recent + old

    first, _ = newsroom_run.select_candidates({}, candidates, bootstrap=True, now=NOW)
    assert [c["url"] for c in first] == [c["url"] for c in recent]

    second, _ = newsroom_run.select_candidates({}, candidates, bootstrap=False, now=NOW)
    assert [c["url"] for c in second] == [c["url"] for c in recent]  # no old backfill


def test_a_second_concurrent_run_is_locked_out(registry):
    assert newsroom_run.acquire_lock() is True
    try:
        summary = newsroom_run.collect(
            dry_run=False,
            path=registry / "sources.json",
            store=registry / "inbox.jsonl",
            fetch_bytes=_rss_fetcher,
        )
    finally:
        newsroom_run.release_lock()
    assert summary["locked"] is True and summary["collected"] == 0
    assert not (registry / "inbox.jsonl").exists()


def test_dry_run_never_writes_health_or_last_run(registry):
    newsroom_run.collect(
        dry_run=True, path=registry / "sources.json", store=registry / "inbox.jsonl"
    )
    assert source_health.read_health() == {}
    assert source_health.read_last_run() is None
