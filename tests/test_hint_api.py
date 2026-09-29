"""V1.2-G4.20 — the «Започни от идея» endpoint.

The search is stubbed in every test here on purpose. Hitting the real chain
from a test would both make the suite depend on the network and, worse, write
real Stories into the live inbox — which is the corpus, not a sandbox. What is
under test here is the wiring: the route, the validation, and the promise that
what the editor is told is what actually happened.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from editor_assistant.workflow import editor_hint
from editor_assistant.workflow import search as search_mod


class _Provider(search_mod.SearchProvider):
    name = "stub"

    def __init__(self, results):
        self._results = results

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        return {
            "provider": self.name,
            "query": query,
            "requested_count": count,
            "started_at": "2026-01-01T00:00:00Z",
            "status": search_mod.SEARCH_OK,
            "attempt": 1,
            "http_status": 200,
            "retry_after": None,
            "elapsed_ms": 1,
            "results": list(self._results),
        }


def _stub(monkeypatch, results, *, opener=None):
    """Force the hint path onto a stub provider and opener."""
    monkeypatch.setattr(
        search_mod, "provider_chain", lambda capability=None, env=None: ([_Provider(results)], [])
    )
    if opener is not None:
        monkeypatch.setattr(editor_hint.web_fetch, "fetch_page", opener)


def _page(url, title="ЦИК", text="body"):
    return {"final_url": url, "content_type": "text/html", "bytes": len(text), "text": text}


def _request(base, path, *, method="GET", body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.fixture
def newsroom_root(tmp_path, monkeypatch):
    """Isolate the newsroom so no test can write into the live corpus.

    This is the same isolation the API suite uses: the hint path writes real
    inbox rows, so a test without it would quietly grow the corpus.
    """
    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    return newsroom


@pytest.fixture
def api_server(newsroom_root):
    from editor_assistant.workflow.workbench import http

    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_hint_that_opens_pages_lands_real_stories(api_server, monkeypatch):
    real = "https://cik.bg/news/2026/machines"
    _stub(
        monkeypatch,
        [{"url": real, "title": "ЦИК", "snippet": "снипет"}],
        opener=lambda url: _page(real),
    )
    status, payload = _request(api_server, "/api/v1/stories/hint", method="POST", body={"hint": "проверка на машините"})
    assert status == 200
    data = payload["data"]
    assert data["openedCount"] == 1
    assert data["opened"][0]["url"] == real
    # The discovery-only snippet must not be handed back as the story's summary.
    assert data["opened"][0].get("summary", "") == ""


def test_a_blank_hint_is_refused_at_the_boundary(api_server, monkeypatch):
    """Measured behaviour: a blank field never reaches the search.

    `_string(required=True)` rejects it first with the generic field message,
    which is the right layer to say "this field is required" — and it means the
    network is never touched for input that was never going to be used.
    """
    _stub(monkeypatch, [], opener=lambda url: _page(url))
    status, payload = _request(api_server, "/api/v1/stories/hint", method="POST", body={"hint": "  "})
    assert status == 400
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_a_hint_too_short_to_search_is_refused_with_its_own_reason(api_server, monkeypatch):
    """Past the boundary the domain rule applies, and keeps its own code.

    An editor who typed "ЦИК" deserves to be told it is too short to search,
    not handed a generic field error — the two are different problems.
    """
    _stub(monkeypatch, [], opener=lambda url: _page(url))
    status, payload = _request(api_server, "/api/v1/stories/hint", method="POST", body={"hint": "ЦИК"})
    assert status == 400
    assert payload["error"]["code"] == "HINT_REJECTED"
    assert "кратка" in payload["error"]["message"]


def test_a_missing_hint_field_is_a_validation_error(api_server):
    status, payload = _request(api_server, "/api/v1/stories/hint", method="POST", body={})
    assert status == 400
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_a_hint_that_finds_nothing_reports_zero_without_inventing(api_server, monkeypatch):
    _stub(monkeypatch, [], opener=lambda url: _page(url))
    status, payload = _request(
        api_server, "/api/v1/stories/hint", method="POST", body={"hint": "тема без резултат"}
    )
    assert status == 200
    data = payload["data"]
    assert data["openedCount"] == 0
    assert data["opened"] == []


def test_a_page_that_cannot_open_is_reported_by_its_real_category(api_server, monkeypatch):
    from editor_assistant.sources import web_fetch

    def opener(url):
        raise web_fetch.WebFetchError("FETCH_TIMEOUT", "connected but no body")

    _stub(monkeypatch, [{"url": "https://example.org/a", "title": "A", "snippet": "..."}], opener=opener)
    status, payload = _request(
        api_server, "/api/v1/stories/hint", method="POST", body={"hint": "проверка на машините"}
    )
    assert status == 200
    data = payload["data"]
    assert data["openedCount"] == 0
    assert data["unopened"][0]["status"] == "FETCH_TIMEOUT"


def test_get_on_the_hint_path_is_405_not_a_misleading_404(api_server):
    status, _payload = _request(api_server, "/api/v1/stories/hint")
    assert status == 405
