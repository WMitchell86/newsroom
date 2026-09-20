"""M4A Workbench tests: «Източници» + «Входящи» (offline, env-isolated).

Every test runs against a temp `var/newsroom` via `WB_NEWSROOM_DIR`, so the real
registry and inbox are never touched. HTTP tests bind to 127.0.0.1 only.

What matters here: the editor can manage sources from the page, a refusal is a
readable Bulgarian message (never a 500 and never a silent store change), and the
UI delegates to the same registry functions the CLI uses.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from editor_assistant.workflow import inbox_store, sources_registry
from editor_assistant.workflow.workbench import http, newsroom


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # pragma: no cover - trivial
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get(url):
    return _OPENER.open(url, timeout=5)


def _post(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as err:
        return err


@pytest.fixture(autouse=True)
def newsroom_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(tmp_path / "newsroom"))
    return tmp_path / "newsroom"


@pytest.fixture
def seeded(newsroom_dir):
    sources_registry.add_source(
        path=newsroom.sources_store(),
        source_id="council-feed",
        name="Общински съвет Бургас",
        kind="official",
        collector="rss",
        url="https://feed.example/rss",
        priority="high",
        factual_authority=True,
    )
    sources_registry.add_source(
        path=newsroom.sources_store(),
        source_id="news-search",
        name="Търсене Бургас",
        kind="aggregator",
        collector="google_news_rss",
        query="Бургас",
        factual_authority=False,
    )
    inbox_store.add_items(
        [
            {
                "source_id": "council-feed",
                "title": "Общинският съвет прие бюджета",
                "url": "https://feed.example/budget",
                "discovered_at": "2026-09-20T07:00:00Z",
                "source_kind": "official",
                "priority": "high",
            }
        ],
        path=newsroom.inbox_store_path(),
    )
    return newsroom_dir


@pytest.fixture
def server(seeded):
    httpd = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------- sources page ----------


def test_sources_page_lists_the_registry_with_bulgarian_labels(server):
    html = _get(f"{server}/sources").read().decode("utf-8")
    assert "Източници" in html
    assert "Общински съвет Бургас" in html and "council-feed" in html
    assert "Официален" in html and "Активен" in html and "Висок" in html
    assert "само наблюдение" in html  # the monitoring-only source is flagged
    assert "при всяко събиране" in html  # next-collection column
    assert "Добави източник" in html
    # the nav links the new pages
    assert 'href="/inbox"' in html and 'href="/sources"' in html


def test_sources_page_on_an_empty_install_writes_nothing(newsroom_dir):
    httpd = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        body = _get(f"{base}/sources").read().decode("utf-8")
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert "Още няма източници" in body
    assert not newsroom_dir.exists()


def test_add_source_from_the_page(server):
    resp = _post(
        f"{server}/sources",
        {
            "action": "add",
            "source_id": "bnr-burgas",
            "name": "БНР Бургас",
            "kind": "media",
            "collector": "rss",
            "url": "https://bnr.bg/burgas/rss",
            "priority": "normal",
            "cadence": "daily",
            "note": "",
        },
    )
    assert resp.code in (302, 303)
    assert "message" in resp.headers["Location"]
    entry = sources_registry.read_registry(newsroom.sources_store())["bnr-burgas"]
    assert entry["kind"] == "media" and entry["cadence"] == "daily"
    last = newsroom.read_actions()[-1]
    assert last["action"] == "source_added" and last["subject"] == "bnr-burgas"


def test_a_refused_add_shows_a_message_and_changes_nothing(server):
    before = newsroom.sources_store().read_text(encoding="utf-8")
    resp = _post(
        f"{server}/sources",
        {
            "action": "add",
            "source_id": "Bad Id",
            "name": "Лош",
            "kind": "media",
            "collector": "rss",
            "url": "https://x.example/rss",
        },
    )
    body = resp.read().decode("utf-8")
    assert resp.code == 400
    assert "lowercase slug" in body  # the refusal is shown, not a traceback
    assert "Лош" in body  # the typed values are echoed back
    assert newsroom.sources_store().read_text(encoding="utf-8") == before


def test_disable_enable_mute_priority_and_authority(server):
    assert _post(f"{server}/sources", {"action": "disable", "source_id": "news-search"}).code in (
        302,
        303,
    )
    assert sources_registry.read_registry(newsroom.sources_store())["news-search"]["status"] == (
        "disabled"
    )

    _post(f"{server}/sources", {"action": "enable", "source_id": "news-search"})
    assert sources_registry.read_registry(newsroom.sources_store())["news-search"]["status"] == (
        "active"
    )

    _post(
        f"{server}/sources",
        {"action": "mute", "source_id": "news-search", "muted_until": "2026-09-25"},
    )
    muted = sources_registry.read_registry(newsroom.sources_store())["news-search"]
    assert muted["status"] == "muted" and muted["muted_until"] == "2026-09-25"

    _post(f"{server}/sources", {"action": "unmute", "source_id": "news-search"})
    unmuted = sources_registry.read_registry(newsroom.sources_store())["news-search"]
    assert unmuted["status"] == "active" and unmuted["muted_until"] == ""

    _post(f"{server}/sources", {"action": "priority", "source_id": "news-search", "value": "high"})
    assert (
        sources_registry.read_registry(newsroom.sources_store())["news-search"]["priority"]
        == "high"
    )

    _post(f"{server}/sources", {"action": "authority", "source_id": "news-search"})
    assert (
        sources_registry.read_registry(newsroom.sources_store())["news-search"]["factual_authority"]
        is True
    )
    _post(f"{server}/sources", {"action": "monitoring_only", "source_id": "news-search"})
    assert (
        sources_registry.read_registry(newsroom.sources_store())["news-search"]["factual_authority"]
        is False
    )


def test_mute_without_a_date_is_refused_with_a_message(server):
    resp = _post(
        f"{server}/sources",
        {"action": "mute", "source_id": "council-feed", "muted_until": ""},
    )
    assert resp.code == 400
    assert "muted_until" in resp.read().decode("utf-8")
    assert (
        sources_registry.read_registry(newsroom.sources_store())["council-feed"]["status"]
        == "active"
    )


def test_edit_and_remove_from_the_page(server):
    _post(
        f"{server}/sources",
        {"action": "edit", "source_id": "council-feed", "name": "Общински съвет (ново име)"},
    )
    entry = sources_registry.read_registry(newsroom.sources_store())["council-feed"]
    assert entry["name"] == "Общински съвет (ново име)"
    assert entry["url"] == "https://feed.example/rss"  # untouched fields stay

    _post(f"{server}/sources", {"action": "remove", "source_id": "news-search"})
    assert "news-search" not in sources_registry.read_registry(newsroom.sources_store())


def test_unknown_action_is_refused(server):
    resp = _post(f"{server}/sources", {"action": "explode", "source_id": "council-feed"})
    assert resp.code == 400
    assert "непознато действие" in resp.read().decode("utf-8")


# ---------- inbox page ----------


def test_inbox_page_shows_collected_items(server):
    body = _get(f"{server}/inbox").read().decode("utf-8")
    assert "Входящи" in body
    assert "Общинският съвет прие бюджета" in body
    assert "Общински съвет Бургас" in body  # source name, not only the id
    assert "Нов" in body
    assert "не доказателства" in body  # the candidate-not-evidence reminder


def test_inbox_status_actions(server):
    item_id = inbox_store.read_items(newsroom.inbox_store_path())[0]["item_id"]
    resp = _post(f"{server}/inbox", {"action": "status", "item_id": item_id, "status": "IGNORED"})
    assert resp.code in (302, 303)
    assert inbox_store.read_items(newsroom.inbox_store_path())[0]["status"] == "IGNORED"
    assert newsroom.read_actions()[-1]["action"] == "inbox_ignored"

    body = _get(f"{server}/inbox").read().decode("utf-8")
    assert "Игнориран" in body


def test_unknown_inbox_item_is_refused(server):
    resp = _post(f"{server}/inbox", {"action": "status", "item_id": "nope", "status": "SEEN"})
    assert resp.code == 400
    assert "unknown item_id" in resp.read().decode("utf-8")


def test_collection_plan_view_makes_no_network_call(seeded):
    plan = newsroom.collection_plan()
    assert [s["source_id"] for s in plan["sources"]] == ["council-feed", "news-search"]
    assert plan["estimated_network_calls"] == 2
