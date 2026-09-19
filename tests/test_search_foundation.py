"""M2S Track S: search reliability foundation (offline; provider mocked).

Search snippets are DISCOVERY_ONLY; infrastructure failure is never evidence
of absence; missing config is an explicit capability state, never fabricated
results (harness A2-A11).
"""

import json

import pytest

from editor_assistant.sources import web_fetch
from editor_assistant.workflow import search

# Captured at import (before any test swaps it) so the test below can prove the
# autouse fixture restores the real opener.
_REAL_URLOPEN = search.urllib.request.urlopen


@pytest.fixture(autouse=True)
def _isolated_search_state(tmp_path, monkeypatch):
    """Contain this module's global side effects.

    * `search._audit(path=None)` falls back to `SEARCH_RUNS_DIR`, which points
      at the real `var/editorial_workflow/search_runs`: default-path tests used
      to append fixture runs to the real runtime store.
    * `_provider_with` assigns the `urlopen` module global directly (it does not
      use monkeypatch), so a fake provider used to leak into every later test in
      the session. Restore it here.
    """
    runs = tmp_path / "search_runs"
    monkeypatch.setattr(search, "SEARCH_RUNS_DIR", runs)
    real_urlopen = search.urllib.request.urlopen
    yield runs
    search.urllib.request.urlopen = real_urlopen


def _brave_payload(n=2):
    return {
        "web": {
            "results": [
                {
                    "title": f"Резултат {i}",
                    "url": f"https://example.org/bg/news/{i}",
                    "description": f"Описание {i}",
                    "age": "2 days ago",
                    "meta_url": {"hostname": "example.org"},
                }
                for i in range(1, n + 1)
            ]
        }
    }


class _FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.headers = {"Content-Type": "application/json"}

    def read(self, n=-1):
        return self._payload[:n] if n and n > 0 else self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeHTTPError(Exception):
    pass


def _provider_with(payload=None, error=None):
    """BraveSearchProvider with urlopen patched at the module boundary."""

    class Patched(search.BraveSearchProvider):
        def search(self, query, **kwargs):
            return super().search(query, **kwargs)

    provider = Patched("test-key")
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if error is not None:
            raise error
        return _FakeResponse(payload if payload is not None else _brave_payload())

    search.urllib.request.urlopen = fake_urlopen
    provider.calls = calls
    return provider


def test_provider_success_normalizes_results():
    provider = _provider_with(_brave_payload(3))
    record = provider.search("тест заявка")
    assert record["status"] == search.SEARCH_OK
    assert [r["rank"] for r in record["results"]] == [1, 2, 3]
    assert record["results"][0]["url"].startswith("https://example.org/")
    assert record["provider"] == "brave"
    assert record["elapsed_ms"] is not None


def test_missing_api_key_is_capability_unavailable_not_failure():
    provider, status = search.resolve_provider(env={})
    assert provider is None
    assert status == search.SEARCH_CAPABILITY_UNAVAILABLE


def test_429_is_rate_limited_and_bounded():
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        raise search.urllib.error.HTTPError(
            request.full_url, 429, "slow down", {"Retry-After": "0"}, None
        )

    search.urllib.request.urlopen = fake_urlopen
    provider = search.BraveSearchProvider("k")
    record = provider.search("q")
    assert record["status"] == search.RATE_LIMITED
    assert record["retry_after"] == "0"
    assert calls["n"] == search.MAX_PROVIDER_ATTEMPTS  # bounded, no scheduler


def test_500_is_provider_error_not_no_results():
    def fake_urlopen(request, timeout=None):
        raise search.urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)

    search.urllib.request.urlopen = fake_urlopen
    record = search.BraveSearchProvider("k").search("q")
    assert record["status"] == search.SEARCH_PROVIDER_ERROR
    assert record["http_status"] == 500


def test_no_results_is_not_provider_failure():
    provider = _provider_with({"web": {"results": []}})
    record = provider.search("q")
    assert record["status"] == search.NO_RESULTS
    assert record["results"] == []


def test_query_constraints_survive_fallback_evaluation():
    constraints = search.make_constraints(
        description="национални медии", required_domains=("bta.bg",)
    )
    # a municipality candidate does NOT satisfy the national-media constraint
    verdict = search.evaluate_operation(
        constraints, [{"url": "https://burgas.bg/x", "opened": {"status": "FETCH_OK"}}]
    )
    assert verdict["status"] == search.SEARCH_INCOMPLETE
    assert "не се превръща" in verdict["reason"]
    ok = search.evaluate_operation(constraints, [{"url": "https://www.bta.bg/y"}])
    assert ok["status"] == search.SEARCH_COMPLETE


def test_snippet_only_candidate_cannot_be_opened_result():
    """Snippets carry DISCOVERY_ONLY authority in operation candidates."""
    provider = _provider_with(_brave_payload(1))
    operation = search.run_search_operation(
        topic="тема",
        constraints=search.make_constraints(description="описание"),
        provider=provider,
        page_opener=lambda url: (_ for _ in ()).throw(
            web_fetch.WebFetchError(web_fetch.FETCH_HTTP_ERROR, "403", status=403)
        ),
        audit_path=None,
    )
    candidate = operation["candidates"][0]
    assert candidate["snippet_authority"] == "DISCOVERY_ONLY"
    assert candidate["opened"]["status"] == web_fetch.FETCH_HTTP_ERROR
    assert operation["status"] == search.SEARCH_COMPLETE  # discovery happened


def test_page_fetch_success_and_oversize_rejection(tmp_path):
    class Resp:
        status = 200
        data = b"<html>ok</html>"

        def __init__(self, data=None):
            self.headers = {"Content-Type": "text/html; charset=utf-8"}
            if data is not None:
                self.data = data

        def read(self, n=-1):
            return self.data if n < 0 or n > len(self.data) else self.data[:n]

        def geturl(self):
            return "https://example.org/final"

    record = web_fetch.fetch_page(
        "https://example.org/page", opener=lambda req, timeout=None: Resp()
    )
    assert record["status"] == 200
    assert record["final_url"] == "https://example.org/final"
    assert "<html>" in record["text"]

    big = Resp(b"x" * (web_fetch.MAX_BYTES + 10))
    with pytest.raises(web_fetch.WebFetchError) as exc:
        web_fetch.fetch_page("https://example.org/big", opener=lambda req, timeout=None: big)
    assert exc.value.category == web_fetch.FETCH_TOO_LARGE


def test_hermetic_resolver_maps_public_fixture_hosts_offline():
    """A2: public fixture hostnames resolve deterministically without real DNS."""
    infos = web_fetch.socket.getaddrinfo("example.org", None)
    assert infos and infos[0][4][0] == "93.184.216.34"
    web_fetch.guard_target("https://example.org/page")  # public: must not raise


def test_unresolvable_host_fails_closed():
    """A2: the guard stays fail-closed for hosts outside the test map."""
    with pytest.raises(web_fetch.WebFetchError) as exc:
        web_fetch.guard_target("https://does-not-resolve.invalid/x")
    assert exc.value.category == web_fetch.FETCH_BLOCKED_TARGET


def test_private_and_local_targets_rejected():
    for bad in (
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://10.0.0.1/x",
        "http://169.254.169.254/meta",
        "file:///etc/passwd",
        "ftp://example.org/x",
    ):
        with pytest.raises(web_fetch.WebFetchError) as exc:
            web_fetch.guard_target(bad)
        assert exc.value.category == web_fetch.FETCH_BLOCKED_TARGET


def test_operation_without_provider_reports_capability(tmp_path, monkeypatch):
    """Empty chain = explicit capability state; audited, never fabricated."""
    monkeypatch.setattr(
        search,
        "provider_chain",
        lambda capability="WEB", env=None: ([], ["serper:no-key", "brave:no-key"]),
    )
    audit = tmp_path / "runs.jsonl"
    operation = search.run_search_operation(
        topic="тема",
        constraints=search.make_constraints(description="описание"),
        provider=None,
        env={"BRAVE_SEARCH_API_KEY": "supersecret-brave", "SERPER_API_KEY": "supersecret-serper"},
        audit_path=audit,
    )
    assert operation["status"] == search.SEARCH_INCOMPLETE
    assert operation["failure"] == search.SEARCH_CAPABILITY_UNAVAILABLE
    assert operation["providers_unavailable"] == ["serper:no-key", "brave:no-key"]
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    recorded = json.loads(lines[0])
    assert recorded["failure"] == search.SEARCH_CAPABILITY_UNAVAILABLE
    dumped = json.dumps(recorded)
    assert "supersecret" not in dumped  # no credential values in the audit


def test_planner_caps_queries_and_is_gap_driven():
    queries = search.plan_queries(
        topic="Събитие X",
        missing_dimensions=("admission", "event_schedule"),
        research_questions=("Има ли вход?",),
    )
    assert 1 <= len(queries) <= 3
    assert all("Събитие X" in q for q in queries)


# ---------- M2S-R2: capability-based provider stack ----------


def test_provider_chain_news_defaults_keyless(monkeypatch):
    """NEWS chain without keys: RSS first, serper/brave explicitly unavailable."""
    chain, unavailable = search.provider_chain(capability=search.CAP_NEWS, env={})
    names = [p.name for p in chain]
    assert names[0] == "google_news_rss"
    assert "serper:no-key" in unavailable and "brave:no-key" in unavailable
    if search._load_ddgs() is not None:
        assert "ddgs" in names


def test_provider_chain_pins_single_provider(monkeypatch):
    """SEARCH_PROVIDER pins one provider; missing key is an explicit outcome."""
    chain, unavailable = search.provider_chain(
        capability=search.CAP_WEB, env={"SEARCH_PROVIDER": "serper"}
    )
    assert chain == []
    assert unavailable == ["serper:no-key"]


def test_provider_chain_unknown_capability_raises():
    with pytest.raises(search.SearchError):
        search.provider_chain(capability="TELEPATHY", env={})


def _offline_page_opener(url):
    """Hermetic stand-in: candidate opening must never touch the network (A2)."""
    raise web_fetch.WebFetchError(
        web_fetch.FETCH_HTTP_ERROR, f"offline test opener: {url}", status=503
    )


def test_operation_falls_back_along_the_chain(monkeypatch):
    """A failing provider is skipped; its status stays visible in the audit."""

    class Fail(search.SearchProvider):
        name = "fail"

        def search(self, query, **kw):
            rec = self._empty(query, 5)
            rec["status"] = search.SEARCH_PROVIDER_ERROR
            return rec

    class Ok(search.SearchProvider):
        name = "ok"

        def search(self, query, **kw):
            rec = self._empty(query, 5)
            rec["status"] = search.SEARCH_OK
            rec["results"] = [
                {"rank": 1, "title": "t", "url": "https://example.org/x", "snippet": "s"}
            ]
            return rec

    monkeypatch.setattr(
        search, "provider_chain", lambda capability="WEB", env=None: ([Fail(), Ok()], [])
    )
    operation = search.run_search_operation(
        topic="тема",
        constraints=search.make_constraints(description="описание"),
        provider=None,
        page_opener=_offline_page_opener,
        audit_path=None,
    )
    assert [q["provider"] for q in operation["queries"]] == ["fail", "ok"]
    assert operation["chain_fallbacks"] == ["fail:SEARCH_PROVIDER_ERROR"]
    assert operation["candidates"][0]["url"] == "https://example.org/x"
    assert operation["status"] == search.SEARCH_COMPLETE


def test_operation_survives_provider_raising_searcherror(monkeypatch):
    """A provider that cannot even run (package missing) never kills the chain."""

    class Broken(search.SearchProvider):
        name = "broken"

        def search(self, query, **kw):
            raise search.SearchError("ddgs package is not installed")

    class Ok(search.SearchProvider):
        name = "ok"

        def search(self, query, **kw):
            rec = self._empty(query, 5)
            rec["status"] = search.SEARCH_OK
            rec["results"] = [
                {"rank": 1, "title": "t", "url": "https://example.org/y", "snippet": "s"}
            ]
            return rec

    monkeypatch.setattr(
        search, "provider_chain", lambda capability="WEB", env=None: ([Broken(), Ok()], [])
    )
    operation = search.run_search_operation(
        topic="тема",
        constraints=search.make_constraints(description="описание"),
        page_opener=_offline_page_opener,
        audit_path=None,
    )
    assert operation["chain_fallbacks"] == ["broken:SEARCH_CAPABILITY_UNAVAILABLE"]
    assert operation["status"] == search.SEARCH_COMPLETE


def _rss_feed(n=2):
    items = "".join(
        f"<item><title>Новина {i}</title><link>https://example.org/n/{i}</link>"
        f"<description>Описание {i}</description>"
        f"<pubDate>Tue, 1 Sep 2026 10:0{i}:00 GMT</pubDate>"
        # real Google News RSS shape: &amp;-escaped attr value (note: &quot; in an
        # attribute value is invalid XML and must never appear on the wire)
        f'<source url="https://example.org/r?via=1&amp;x={i}">Пример</source></item>'
        for i in range(1, n + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Google News</title>{items}</channel></rss>"
    ).encode()


def test_fetch_page_encodes_non_ascii_url():
    """Regression: Cyrillic URLs (.bg publishers) must not crash urllib (IRI->URI)."""
    seen = {}

    def fake_opener(request, timeout=None):
        seen["url"] = request.full_url

        class _R:
            status = 200

            def __init__(self):
                self.headers = {"Content-Type": "text/html; charset=utf-8"}

            def read(self, n=-1):
                return b"<html>ok</html>"

            def geturl(self):
                return request.full_url

        return _R()

    page = web_fetch.fetch_page("https://example.org/новини/бургас", opener=fake_opener)
    assert seen["url"].isascii(), seen["url"]
    assert "%D0%BD" in seen["url"]  # encoded Cyrillic
    assert page["status"] == 200


def test_rss_provider_parses_feed(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        return _FakeResponse(_rss_feed(2))

    monkeypatch.setattr(search.urllib.request, "urlopen", fake_urlopen)
    record = search.GoogleNewsRSSProvider().search("Бургас тест")
    assert record["status"] == search.SEARCH_OK
    assert "news.google.com/rss/search" in seen["url"]
    assert record["results"][0]["title"] == "Новина 1"
    assert record["results"][0]["url"] == "https://example.org/n/1"
    assert record["results"][0]["source_name"] == "Пример"


def test_rss_provider_empty_feed_is_no_results_not_error(monkeypatch):
    monkeypatch.setattr(
        search.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(_rss_feed(0))
    )
    record = search.GoogleNewsRSSProvider().search("q")
    assert record["status"] == search.NO_RESULTS


def test_rss_provider_http_error_is_provider_error(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise search.urllib.error.HTTPError(request.full_url, 503, "down", {}, None)

    monkeypatch.setattr(search.urllib.request, "urlopen", fake_urlopen)
    record = search.GoogleNewsRSSProvider().search("q")
    assert record["status"] == search.SEARCH_PROVIDER_ERROR
    assert record["http_status"] == 503


def test_wikipedia_provider_normalizes(monkeypatch):
    payload = {
        "query": {
            "search": [
                {
                    "title": "Бургас",
                    "snippet": "<span>град в България</span>",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ]
        }
    }
    monkeypatch.setattr(
        search.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(payload)
    )
    record = search.WikipediaBackgroundProvider().search("Бургас")
    assert record["status"] == search.SEARCH_OK
    assert (
        record["results"][0]["url"]
        == "https://bg.wikipedia.org/wiki/%D0%91%D1%83%D1%80%D0%B3%D0%B0%D1%81"
    )
    assert "<span>" not in record["results"][0]["snippet"]
    assert record["results"][0]["source_name"] == "bg.wikipedia.org"


def test_serper_provider_sends_key_and_normalizes(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["api_key"] = request.get_header("X-api-key")
        seen["body"] = request.data.decode("utf-8")
        return _FakeResponse(
            {"organic": [{"title": "t", "link": "https://example.org/a", "snippet": "s"}]}
        )

    monkeypatch.setattr(search.urllib.request, "urlopen", fake_urlopen)
    record = search.SerperProvider("sk-test").search("Бургас")
    assert record["status"] == search.SEARCH_OK
    assert seen["api_key"] == "sk-test"
    import json as _json

    assert _json.loads(seen["body"])["q"] == "Бургас"
    assert record["results"][0]["url"] == "https://example.org/a"


def test_serper_provider_requires_key():
    with pytest.raises(search.SearchError):
        search.SerperProvider("  ")


def test_ddgs_provider_requires_package():
    with pytest.raises(search.SearchError):
        search.DDGSProvider(ddgs_factory=lambda: None)


def test_ddgs_provider_normalizes():
    class FakeDDGS:
        def __init__(self, *args, **kwargs):
            pass

        def text(self, query, region=None, max_results=None):
            assert region == "bg-bg"
            return [
                {"title": "t", "href": "https://example.org/d", "body": "b", "date": ""},
                {"title": "bad", "href": "", "body": "", "date": ""},
            ]

    record = search.DDGSProvider(ddgs_factory=lambda: FakeDDGS).search("Бургас")
    assert record["status"] == search.SEARCH_OK
    assert len(record["results"]) == 2
    assert record["results"][0]["url"] == "https://example.org/d"


def test_ddgs_provider_runtime_error_is_provider_error():
    class ExplodingDDGS:
        def __init__(self, *args, **kwargs):
            pass

        def text(self, *a, **kw):
            raise RuntimeError("backend gone")

    record = search.DDGSProvider(ddgs_factory=lambda: ExplodingDDGS).search("q")
    assert record["status"] == search.SEARCH_PROVIDER_ERROR
    assert record["error"] == "RuntimeError"


def test_resolve_provider_still_supports_new_names():
    provider, status = search.resolve_provider(env={"SEARCH_PROVIDER": "google_news_rss"})
    assert status == search.SEARCH_OK and provider.name == "google_news_rss"
    provider, status = search.resolve_provider(env={"SEARCH_PROVIDER": "wikipedia"})
    assert status == search.SEARCH_OK and provider.name == "wikipedia"
    provider, status = search.resolve_provider(env={"SEARCH_PROVIDER": "serper"})
    assert provider is None and status == search.SEARCH_CAPABILITY_UNAVAILABLE
    with pytest.raises(search.SearchError):
        search.resolve_provider(env={"SEARCH_PROVIDER": "altavista"})


def test_global_urlopen_is_restored_after_provider_tests():
    """The autouse fixture must undo `_provider_with`'s direct global swap.

    Otherwise every later test in the session runs against a fake opener that
    never touches the network.
    """
    assert search.urllib.request.urlopen is _REAL_URLOPEN
