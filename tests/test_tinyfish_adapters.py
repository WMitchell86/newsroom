"""M2S-R3 Part A: TinyFish Search/Fetch adapters (offline; urlopen mocked).

Harness points covered: missing key = capability unavailable, never fabricated
(A2); provider mapping 429->RATE_LIMITED, 402/403/outage->PROVIDER_ERROR (A4);
count normalization / count_param_ignored (A3); DISCOVERY_ONLY snippets (A1);
privacy guard on the outbound surface (A6); fallback routing is narrow and a
blocked target is NEVER forwarded (A5); registered-but-not-default routing
(A8); benchmark helpers (B1/B2).
"""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

from editor_assistant.sources import web_fetch
from editor_assistant.workflow import search

# Search benchmark helpers (Part B); loaded directly from tmp/.
_BENCH_PATH = Path(__file__).resolve().parent.parent / "tmp" / "tinyfish_benchmark.py"
_spec = importlib.util.spec_from_file_location("tinyfish_benchmark", _BENCH_PATH)
BENCH = importlib.util.module_from_spec(_spec)
try:  # the file exists in this checkout; a missing file must not hide adapter failures
    _spec.loader.exec_module(BENCH)
except FileNotFoundError:
    BENCH = None


def _http_error(code, body=b'{"error": {"code": "quota"}}', headers=None):
    return urllib.error.HTTPError(
        "https://api.search.tinyfish.ai", code, "err", headers or {}, io.BytesIO(body)
    )


def _search_payload(n=2, total=None):
    return {
        "results": [
            {
                "position": i + 1,
                "title": f"Резултат {i}",
                "url": f"https://burgas.bg/bg/news/{i}",
                "snippet": f"Откъс {i}",
                "date": "2026-09-16",
                "site_name": "burgas.bg",
                "publisher": "Община Бургас",
            }
            for i in range(n)
        ],
        "total_results": total if total is not None else n,
        "page": 0,
    }


def _fake_urlopen(payload=None, error=None):
    def fake(request, timeout=None):
        if error is not None:
            raise error
        return _FakeOK(payload if callable(payload) else payload or {})

    return fake


class _FakeOK:
    def __init__(self, payload):
        self.status = 200
        self._payload = json.dumps(payload).encode("utf-8")
        self.headers = {}

    def read(self, n=-1):
        return self._payload[:n] if n and n > 0 else self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def patch_urlopen(monkeypatch):
    def _patch(fake):
        monkeypatch.setattr(search.urllib.request, "urlopen", fake)

    return _patch


def _provider(**kwargs):
    return search.TinyFishSearchProvider("k", **kwargs)


# ---------- capability, not fabrication (harness A2/A8) ----------


def test_registered_but_not_in_default_provider_order():
    assert "tinyfish" in search.PROVIDER_CAPABILITIES
    for order in search.PROVIDER_ORDER.values():
        assert "tinyfish" not in order


def test_missing_key_is_explicit_unavailable(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    chain, unavailable = search.provider_chain(search.CAP_WEB, env={"SEARCH_PROVIDER": "tinyfish"})
    assert chain == []
    assert unavailable == ["tinyfish:unavailable"]
    assert search.tinyfish_search_provider(env={}) is None
    assert search.tinyfish_fetch_provider(env={}) is None


def test_pin_with_key_builds_single_provider_chain():
    chain, unavailable = search.provider_chain(
        search.CAP_NEWS, env={"SEARCH_PROVIDER": "tinyfish", "TINYFISH_API_KEY": "k"}
    )
    assert [p.name for p in chain] == ["tinyfish"]
    assert chain[0].domain_type == "news"
    assert unavailable == []


def test_empty_api_key_rejected():
    with pytest.raises(search.SearchError):
        search.TinyFishSearchProvider("  ")
    with pytest.raises(search.SearchError):
        search.TinyFishFetchProvider("")
    with pytest.raises(search.SearchError):
        search.TinyFishSearchProvider("k", domain_type="blogs")


# ---------- request shape and normalization (harness A3) ----------


def test_search_success_normalizes_and_respects_count(patch_urlopen):
    seen = {}

    def fake(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.headers)
        return _FakeOK(_search_payload(5))

    patch_urlopen(fake)
    record = _provider().search("Община Бургас бюджет 2026", count=3)
    assert record["status"] == search.SEARCH_OK
    assert len(record["results"]) == 3  # client-side count, provider has no param
    assert record["count_param_ignored"] is True
    assert record["results"][0]["rank"] == 1
    assert record["results"][0]["url"].startswith("https://burgas.bg")
    assert record["results"][0]["source_name"] == "burgas.bg"
    assert "x-api-key" in {k.lower() for k in seen["headers"]}  # urllib normalizes case
    assert "location=BG" in seen["url"] and "language=bg" in seen["url"]
    assert "domain_type=web" in seen["url"]
    assert "page=0" in seen["url"]
    assert record["results"][0]["snippet"]


def test_locale_news_and_domain_type_mapping(patch_urlopen):
    seen = {}

    def fake(request, timeout=None):
        seen["url"] = request.full_url
        return _FakeOK(_search_payload(0))

    patch_urlopen(fake)
    rec = search.TinyFishSearchProvider("k", domain_type="news").search(
        "новина", country="US", search_language="EN"
    )
    assert rec["status"] == search.NO_RESULTS
    assert "location=US" in seen["url"] and "language=EN" in seen["url"]
    assert "domain_type=news" in seen["url"]


def test_freshness_maps_to_recency_minutes(patch_urlopen):
    seen = {}

    def fake(request, timeout=None):
        seen["url"] = request.full_url
        return _FakeOK(_search_payload(1))

    patch_urlopen(fake)
    _provider().search("q", freshness="pw")
    assert "recency_minutes=10080" in seen["url"]


def test_include_exclude_domains_serialized(patch_urlopen):
    seen = {}

    def fake(request, timeout=None):
        seen["url"] = request.full_url
        return _FakeOK(_search_payload(0))

    patch_urlopen(fake)
    _provider().search(
        "q", include_domains=["burgas.bg", "government.bg"], exclude_domains=["facebook.com"]
    )
    assert "include_domains=burgas.bg%2Cgovernment.bg" in seen["url"]
    assert "exclude_domains=facebook.com" in seen["url"]


# ---------- failure mapping (harness A4) ----------


def test_429_is_rate_limited_never_no_results(patch_urlopen, monkeypatch):
    monkeypatch.setattr(search.time, "sleep", lambda s: None)
    patch_urlopen(_fake_urlopen(error=_http_error(429, headers={"Retry-After": "0"})))
    record = _provider().search("q")
    assert record["status"] == search.RATE_LIMITED
    assert record["retry_after"] == "0"
    assert record["http_status"] == 429


def test_402_and_403_are_provider_error(patch_urlopen):
    for code in (402, 403):
        patch_urlopen(_fake_urlopen(error=_http_error(code)))
        record = _provider().search("q")
        assert record["status"] == search.SEARCH_PROVIDER_ERROR
        assert record["error_code"] == "quota"
        assert record["http_status"] == code


def test_outage_is_provider_error_not_no_results(patch_urlopen):
    def fake(request, timeout=None):
        raise OSError("connection refused")

    patch_urlopen(fake)
    record = _provider().search("q")
    assert record["status"] == search.SEARCH_PROVIDER_ERROR


def test_malformed_json_is_provider_error(patch_urlopen):
    def broken(request, timeout=None):
        raise json.JSONDecodeError("x", "y", 1)

    patch_urlopen(broken)
    record = _provider().search("q")
    assert record["status"] == search.SEARCH_PROVIDER_ERROR


# ---------- privacy guard (harness A6) ----------


def test_guard_rejects_transcript_material():
    with pytest.raises(search.PrivacyGuardError):
        search.guard_public_query("00:04:09 [музика] някакъв текст")
    with pytest.raises(search.PrivacyGuardError):
        search.guard_public_query("тук има субтитри към видеото")
    long = "дума " * 90
    with pytest.raises(search.PrivacyGuardError):
        search.guard_public_query(long)


def test_guard_allows_public_phrase_and_guards_purpose(patch_urlopen):
    assert search.guard_public_query("Община Бургас бюджет") == "Община Бургас бюджет"
    seen = {}

    def fake(request, timeout=None):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeOK(
            {"results": [{"url": "https://burgas.bg/report.pdf", "title": "Отчет", "text": "бюджет"}],
             "errors": []}
        )

    patch_urlopen(fake)
    fetcher = search.TinyFishFetchProvider("k")
    fetcher.fetch("https://burgas.bg/report.pdf", purpose="проверка на бюджетен отчет")
    assert seen["body"]["purpose"] == "проверка на бюджетен отчет"


def test_fetch_rejects_transcript_purpose_before_any_network_call():
    fetcher = search.TinyFishFetchProvider("k")
    with pytest.raises(search.PrivacyGuardError):
        fetcher.fetch("https://burgas.bg/x", purpose="00:12:33 " + "дума " * 100)


# ---------- fetch adapter + fallback routing (harness A5) ----------


def test_fetch_success_matches_local_record_shape(patch_urlopen):
    payload = {
        "results": [
            {
                "url": "https://burgas.bg/report.pdf",
                "title": "Отчет",
                "text": "а" * 400,
                "language": "bg",
                "published_date": "2026-09-01",
                "status": "ok",
            }
        ],
        "errors": [],
    }
    seen = {}

    def fake(request, timeout=None):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeOK(payload)

    patch_urlopen(fake)
    page = search.TinyFishFetchProvider("k").fetch("https://burgas.bg/report.pdf")
    assert page["url"] == "https://burgas.bg/report.pdf"
    assert page["bytes"] >= 400
    assert page["extractor"] == "tinyfish_fetch"
    assert seen["body"]["format"] == "markdown"
    assert seen["body"]["urls"] == ["https://burgas.bg/report.pdf"]


def test_fetch_batch_limit_and_errors_are_explicit(patch_urlopen):
    fetcher = search.TinyFishFetchProvider("k")
    with pytest.raises(search.SearchError):
        fetcher.fetch_many([f"https://a.bg/{i}" for i in range(11)])
    with pytest.raises(search.SearchError):
        fetcher.fetch_many([])

    def fake(request, timeout=None):
        return _FakeOK({"results": [], "errors": [{"url": "https://example.com/x", "error": "timeout"}]})

    patch_urlopen(fake)
    with pytest.raises(web_fetch.WebFetchError) as excinfo:
        fetcher.fetch("https://example.com/page")
    assert excinfo.value.category == web_fetch.FETCH_TIMEOUT


def test_fallback_triggers_only_after_near_empty_local_failure(patch_urlopen):
    def local_ok(url):
        return {"url": url, "status": 200, "text": "Дълъг достатъчен текст " * 20}

    called = {"fetch": False}

    def fake(request, timeout=None):
        called["fetch"] = True
        return _FakeOK(
            {
                "results": [
                    {"url": "https://burgas.bg/x", "title": "t", "text": "бюджет Бургас " * 30}
                ],
                "errors": [],
            }
        )

    patch_urlopen(fake)
    out = search.fetch_with_fallback(
        "https://burgas.bg/x", local_opener=local_ok, fallback=search.TinyFishFetchProvider("k")
    )
    assert out["source"] == "local" and out["fallback_attempted"] is False
    assert not called["fetch"]


def test_fallback_runs_for_http_error_and_parse_empty(patch_urlopen):
    def local_http_error(url):
        raise web_fetch.WebFetchError(web_fetch.FETCH_HTTP_ERROR, "503", status=503)

    def local_empty(url):
        return {"url": url, "status": 200, "text": "Малко."}

    for opener in (local_http_error, local_empty):
        calls: list = []

        def fake(request, timeout=None, calls=calls):  # bind per iteration (B023)
            calls.append(request.full_url)
            return _FakeOK(
                {
                    "results": [{"url": calls[0], "title": "t", "text": "бюджет " * 60}],
                    "errors": [],
                }
            )

        patch_urlopen(fake)
        out = search.fetch_with_fallback(
            "https://burgas.bg/x",
            local_opener=opener,
            fallback=search.TinyFishFetchProvider("k"),
        )
        assert out["fallback_attempted"] is True
        assert out["source"] == "tinyfish_fetch"
        assert out["opened"]["text"]
        assert out["failure_category"] is None


def test_no_fallback_configured_is_explicit_not_failure(patch_urlopen):
    def local_http_error(url):
        raise web_fetch.WebFetchError(web_fetch.FETCH_TIMEOUT, "timeout")

    def never(request, timeout=None):
        raise AssertionError("no fallback fetcher configured - no request expected")

    patch_urlopen(never)
    out = search.fetch_with_fallback("https://burgas.bg/x", local_opener=local_http_error, env={})
    assert out["fallback_attempted"] is False
    assert out["opened"] is None
    assert out["failure_category"] == search.SOURCE_FETCH_FAILED
    assert "TINYFISH_API_KEY" in out["reason"]


def test_blocked_target_never_forwarded(patch_urlopen):
    def local_blocked(url):
        raise web_fetch.WebFetchError(web_fetch.FETCH_BLOCKED_TARGET, "private")

    def never(request, timeout=None):
        raise AssertionError("blocked target must never be forwarded")

    patch_urlopen(never)
    out = search.fetch_with_fallback(
        "http://127.0.0.1:9/x",
        local_opener=local_blocked,
        fallback=search.TinyFishFetchProvider("k"),
    )
    assert out["fallback_attempted"] is False
    assert out["opened"] is None
    assert out["failure_category"] == search.SOURCE_ACCESS_BLOCKED
    assert "never forwarded" in out["reason"]


def test_fallback_failure_maps_to_source_taxonomy(patch_urlopen):
    def local_http_error(url):
        raise web_fetch.WebFetchError(web_fetch.FETCH_HTTP_ERROR, "403")

    def fake(request, timeout=None):
        raise web_fetch.WebFetchError(web_fetch.FETCH_HTTP_ERROR, "HTTP 403", status=403)

    patch_urlopen(fake)
    out = search.fetch_with_fallback(
        "https://burgas.bg/x",
        local_opener=local_http_error,
        fallback=search.TinyFishFetchProvider("k"),
    )
    assert out["fallback_attempted"] is True
    assert out["opened"] is None
    assert out["failure_category"] == search.SOURCE_FETCH_FAILED


# ---------- benchmark helpers (Part B, B1/B2) ----------


def test_benchmark_helpers_shape_and_derivation():
    if BENCH is None:  # pragma: no cover
        pytest.skip("benchmark module not loadable")
    cells = BENCH.derive_cells(_search_payload(2), 7, count_param_ignored=True)
    assert cells["results_total"] == 2
    assert cells["results_used"] == 2
    assert cells["count_param_ignored"] is True
    assert cells["top3_domains"] == ["burgas.bg", "burgas.bg"]
    assert cells["official_domain_share"].startswith("burgas.bg 2/2")
    dup = BENCH.derive_cells({"results": [{"url": "https://a.bg/1", "title": "x"}] * 7}, 7)
    assert dup["dup_ratio"] == "6/7"
    empty = BENCH.derive_cells({"results": []}, 7)
    assert empty["results_total"] == 0 and empty["results_used"] == 0



