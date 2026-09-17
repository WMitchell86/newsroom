"""M2S Track S: search reliability foundation (offline; provider mocked).

Search snippets are DISCOVERY_ONLY; infrastructure failure is never evidence
of absence; missing config is an explicit capability state, never fabricated
results (harness A2-A11).
"""

import json

import pytest

from editor_assistant.sources import web_fetch
from editor_assistant.workflow import search


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
        self._payload = json.dumps(payload).encode()
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


def test_operation_without_provider_reports_capability(tmp_path):
    audit = tmp_path / "runs.jsonl"
    operation = search.run_search_operation(
        topic="тема",
        constraints=search.make_constraints(description="описание"),
        provider=None,
        env={},
        audit_path=audit,
    )
    assert operation["status"] == search.SEARCH_INCOMPLETE
    assert operation["failure"] == search.SEARCH_CAPABILITY_UNAVAILABLE
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    recorded = json.loads(lines[0])
    assert recorded["failure"] == search.SEARCH_CAPABILITY_UNAVAILABLE
    assert "key" not in json.dumps(recorded).lower()  # no secrets in audit


def test_planner_caps_queries_and_is_gap_driven():
    queries = search.plan_queries(
        topic="Събитие X",
        missing_dimensions=("admission", "event_schedule"),
        research_questions=("Има ли вход?",),
    )
    assert 1 <= len(queries) <= 3
    assert all("Събитие X" in q for q in queries)
