"""M4A Workbench tests: «Източници» + «Входящи» (offline, env-isolated).

Every test runs against a temp `var/newsroom` via `WB_NEWSROOM_DIR`, so the real
registry and inbox are never touched. HTTP tests bind to 127.0.0.1 only.

What matters here: the editor can manage sources from the page, a refusal is a
readable Bulgarian message (never a 500 and never a silent store change), and the
UI delegates to the same registry functions the CLI uses.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from editor_assistant.workflow import (
    blocked_domains,
    inbox_store,
    newsroom_run,
    source_health,
    sources_registry,
)
from editor_assistant.workflow import story_store as story_store_mod
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
    # M4C renamed the editor-facing raw view «Публикации»; route and store are unchanged.
    body = _get(f"{server}/inbox").read().decode("utf-8")
    assert "Публикации" in body
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

    body = _get(f"{server}/inbox?status=IGNORED").read().decode("utf-8")
    assert "Игнориран" in body


def test_unknown_inbox_item_is_refused(server):
    resp = _post(f"{server}/inbox", {"action": "status", "item_id": "nope", "status": "SEEN"})
    assert resp.code == 400
    assert "unknown item_id" in resp.read().decode("utf-8")


def test_collection_plan_view_makes_no_network_call(seeded):
    plan = newsroom.collection_plan()
    assert [s["source_id"] for s in plan["sources"]] == ["council-feed", "news-search"]
    assert plan["estimated_network_calls"] == 2


# ---------- M4A.1: health, blocked domains, defaults ----------


def test_sources_page_shows_health_and_blocked_domains(server):
    body = _get(f"{server}/sources").read().decode("utf-8")
    assert "Здраве" in body
    assert "Още не е събирано" in body  # health never fabricates a success
    assert "Забранени домейни" in body
    assert "flagman.bg" in body  # the default policy is visible


def test_blocked_domain_add_and_remove_from_the_page(server):
    resp = _post(f"{server}/sources", {"action": "domain_add", "domain": "noise.example"})
    assert resp.code in (302, 303)
    assert "noise.example" in blocked_domains.read_domains(newsroom.blocked_store())

    resp = _post(f"{server}/sources", {"action": "domain_remove", "domain": "noise.example"})
    assert resp.code in (302, 303)
    assert "noise.example" not in blocked_domains.read_domains(newsroom.blocked_store())


def test_a_bad_blocked_domain_is_refused_readably(server):
    resp = _post(f"{server}/sources", {"action": "domain_add", "domain": "https://x.bg/2026/09/a"})
    assert resp.code == 400
    assert "само домейн" in resp.read().decode("utf-8")


def test_defaults_preview_writes_nothing_and_apply_is_additive(server):
    before = newsroom.sources_store().read_text(encoding="utf-8")
    resp = _post(f"{server}/sources", {"action": "defaults_preview"})
    assert resp.code in (302, 303)
    assert newsroom.sources_store().read_text(encoding="utf-8") == before

    _post(f"{server}/sources", {"action": "defaults_apply"})
    from editor_assistant.workflow import default_sources as D

    registry = sources_registry.read_registry(newsroom.sources_store())
    assert set(D.required_ids()) <= set(registry)
    # the editor's own entries were preserved (only missing defaults are added)
    assert registry["council-feed"]["name"] == "Общински съвет Бургас"
    assert "news-search" in registry


# ---------- M4B: daily inbox UX ----------


def test_inbox_defaults_to_new_and_filters(server):
    inbox_store.add_items(
        [
            {
                "source_id": "news-search",
                "title": "Игнорирана новина",
                "url": "https://media.example/ignored",
                "discovered_at": "2026-09-20T09:00:00Z",
                "source_kind": "aggregator",
                "priority": "normal",
                "status": "IGNORED",
            },
            {
                "source_id": "news-search",
                "title": "Прегледана новина",
                "url": "https://media.example/seen",
                "discovered_at": "2026-09-20T08:00:00Z",
                "source_kind": "aggregator",
                "priority": "normal",
                "status": "SEEN",
            },
        ],
        path=newsroom.inbox_store_path(),
    )
    default = _get(f"{server}/inbox").read().decode("utf-8")
    assert "Общинският съвет прие бюджета" in default  # the NEW item
    assert "Игнорирана новина" not in default  # default view is NEW only
    # "Днес" is a real Europe/Sofia day and lifetime totals are labelled separately
    # (M4B.1 F3); these fixtures were collected on 2026-09-20, not today.
    assert "Днес (" in default and "Непрегледани общо:" in default

    all_items = _get(f"{server}/inbox?status=all").read().decode("utf-8")
    assert "Игнорирана новина" in all_items and "Прегледана новина" in all_items

    by_source = _get(f"{server}/inbox?status=all&source=news-search").read().decode("utf-8")
    assert "Игнорирана новина" in by_source
    assert "Общинският съвет прие бюджета" not in by_source


def test_today_counts_use_the_sofia_arrival_day(server):
    """ "Днес" counts arrival on the local day, never lifetime totals (F3)."""
    from datetime import datetime, timezone

    arrived = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inbox_store.add_items(
        [
            {
                "source_id": "news-search",
                "title": "Днешна новина",
                "url": "https://media.example/today",
                "discovered_at": arrived,
                "source_kind": "aggregator",
                "priority": "normal",
            },
            {
                "source_id": "news-search",
                "title": "Стара новина",
                "url": "https://media.example/old",
                "discovered_at": "2020-01-01T08:00:00Z",
                "source_kind": "aggregator",
                "priority": "normal",
            },
        ],
        path=newsroom.inbox_store_path(),
    )
    counts = inbox_store.today_counts(newsroom.inbox_store_path())
    assert counts["by_status"]["NEW"] >= 1
    # the 2020 row exists but is outside the local day window
    assert counts["total"] < inbox_store.counts(newsroom.inbox_store_path())["total"]
    page = _get(f"{server}/inbox").read().decode("utf-8")
    assert "Днес (" in page and counts["date"] in page
    assert "Непрегледани общо:" in page


# ---------- M4C: stories page ----------


PAIR_TITLE = "Катастрофа на пътя Бургас — Несебър, трима ранени"


def _add_pair():
    """Two publishers reporting the same event with an identical title.

    The title is deliberately unrelated to the seeded fixture item, so this pair
    never needs a semantic call (the deterministic test is enough).
    """
    inbox_store.add_items(
        [
            {
                "source_id": "news-search",
                "title": PAIR_TITLE,
                "url": "https://media.example/crash",
                "published_at": "2026-09-20T08:00:00Z",
                "discovered_at": "2026-09-20T08:00:00Z",
                "source_kind": "aggregator",
                "priority": "normal",
                "publisher_domain": "bta.bg",
                "status": "NEW",
            },
            {
                "source_id": "council-feed",
                "title": PAIR_TITLE,
                "url": "https://bnr.bg/crash",
                "published_at": "2026-09-20T08:05:00Z",
                "discovered_at": "2026-09-20T08:05:00Z",
                "source_kind": "official",
                "priority": "high",
                "publisher_domain": "bnr.bg",
                "status": "NEW",
            },
        ],
        path=newsroom.inbox_store_path(),
    )


def _pair_story(path=None):
    store = story_store_mod.read_store(path or newsroom.stories_store())
    return next(s for s in store["stories"] if len(s["members"]) == 2)


def test_stories_page_groups_materials_and_shows_honest_counts(server):
    _add_pair()
    resp = _post(f"{server}/stories", {"action": "update"})
    assert resp.code in (302, 303)
    page = _get(f"{server}/stories").read().decode("utf-8")
    assert "Истории" in page
    assert PAIR_TITLE in page
    # two discoveries, two unique publications, two publishers — counted apart
    assert "2 издателя" in page and "2 публикации" in page and "2 откривания" in page
    assert "bta.bg" in page and "bnr.bg" in page
    # the raw materials view is still one click away
    assert 'href="/inbox"' in page
    assert len(_pair_story()["members"]) == 2


def test_story_detail_shows_chronology_and_publications(server):
    _add_pair()
    _post(f"{server}/stories", {"action": "update"})
    detail = _get(f"{server}/stories/{_pair_story()['story_id']}").read().decode("utf-8")
    assert "Хронология" in detail and "Публикации" in detail
    assert "Откривания" in detail
    assert "bta.bg" in detail and "bnr.bg" in detail
    assert "0.4" not in detail and "jaccard" not in detail.lower()


def test_editor_can_split_a_material_out_of_a_story(server):
    _add_pair()
    _post(f"{server}/stories", {"action": "update"})
    story_id = _pair_story()["story_id"]
    before = len(story_store_mod.read_stories(newsroom.stories_store()))
    view = newsroom.story_view(story_id)
    resp = _post(
        f"{server}/stories",
        {"action": "split", "story": story_id, "item": view["timeline"][1]["item_id"]},
    )
    assert resp.code in (302, 303)
    assert "/stories/" in resp.headers["Location"]
    # one story gained: the split material is its own story again
    assert len(story_store_mod.read_stories(newsroom.stories_store())) == before + 1
    store = story_store_mod.read_store(newsroom.stories_store())
    assert store["overrides"][-1]["action"] == "SPLIT"


def test_editor_can_merge_a_false_split(server):
    _add_pair()
    _post(f"{server}/stories", {"action": "update"})
    first = _pair_story()
    before = len(story_store_mod.read_stories(newsroom.stories_store()))
    # split, then merge back — exactly the editor's recovery path
    view = newsroom.story_view(first["story_id"])
    split = newsroom.split_story_item(first["story_id"], view["timeline"][1]["item_id"])
    assert len(story_store_mod.read_stories(newsroom.stories_store())) == before + 1
    resp = _post(
        f"{server}/stories",
        {"action": "merge", "target": first["story_id"], "source": split["to_story"]},
    )
    assert resp.code in (302, 303)
    assert len(story_store_mod.read_stories(newsroom.stories_store())) == before
    assert len(_pair_story()["members"]) == 2
    store = story_store_mod.read_store(newsroom.stories_store())
    assert store["overrides"][-1]["action"] == "MERGE"


def test_story_status_actions_work_from_the_page(server):
    _add_pair()
    _post(f"{server}/stories", {"action": "update"})
    story_id = _pair_story()["story_id"]
    resp = _post(f"{server}/stories", {"action": "status", "story": story_id, "status": "SEEN"})
    assert resp.code in (302, 303)
    store = story_store_mod.read_store(newsroom.stories_store())
    assert story_store_mod.story_by_id(store, story_id)["status"] == "SEEN"
    items = inbox_store.read_items(newsroom.inbox_store_path())
    assert {i["status"] for i in items if i["source_id"] == "news-search"} == {"SEEN"}


def test_story_update_preview_writes_nothing(server):
    _add_pair()
    resp = _post(f"{server}/stories", {"action": "update_preview"})
    assert resp.code in (302, 303)
    assert "Пробен преглед" in urllib.parse.unquote_plus(resp.headers["Location"])
    assert story_store_mod.read_stories(newsroom.stories_store()) == []


def test_inbox_collect_now_delegates_to_the_shared_service(server, monkeypatch):
    captured = {}

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return {
            "dry_run": False,
            "locked": False,
            "sources": [],
            "estimated_network_calls": 2,
            "new": 4,
            "duplicate": 1,
            "failed": 0,
            "blocked_filtered": 0,
        }

    monkeypatch.setattr(newsroom_run, "collect", fake_collect)
    resp = _post(f"{server}/inbox", {"action": "collect"})
    assert resp.code in (302, 303)
    assert str(captured["path"]).endswith("sources.json")
    assert str(captured["store"]).endswith("inbox.jsonl")
    assert str(captured["health_path"]).endswith("source_health.json")
    assert str(captured["root"]) == str(newsroom.newsroom_dir())
    assert captured["dry_run"] is False
    assert "Събрани 4" in urllib.parse.unquote_plus(resp.headers["Location"])


def test_inbox_collect_preview_asks_the_shared_service_for_a_dry_run(server, monkeypatch):
    captured = {}

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return {
            "dry_run": True,
            "locked": False,
            "sources": [],
            "estimated_network_calls": 2,
        }

    monkeypatch.setattr(newsroom_run, "collect", fake_collect)
    resp = _post(f"{server}/inbox", {"action": "collect_preview"})
    assert resp.code in (302, 303)
    assert captured["dry_run"] is True
    assert "Пробен преглед" in urllib.parse.unquote_plus(resp.headers["Location"])


def test_inbox_shows_source_problems_and_last_run(seeded):
    source_health.record_source(
        "news-search",
        status="FAILED",
        error="Google News: RATE_LIMITED",
        success=False,
        path=newsroom.health_store(),
    )
    source_health.record_run(
        {"finished_at": "2026-09-20T07:00:00Z", "new": 3, "failed": 1},
        path=newsroom.last_run_store(),
    )
    view = newsroom.inbox_view(status="NEW")
    assert view["last_run"]["new"] == 3
    assert any(p["source_id"] == "news-search" for p in view["problems"])
    body = http.html_mod.render_inbox(view)
    assert "Източници с проблем" in body and "RATE_LIMITED" in body


def test_inbox_authority_filter_uses_the_publisher_not_the_discovery_source(seeded):
    """An item found by an official source's monitor is filtered by its publisher."""
    inbox_store.add_items(
        [
            {
                "source_id": "council-feed",  # official, but the publisher is a blog
                "title": "Блог публикация",
                "url": "https://unknown-blog.example/a",
                "discovered_at": "2026-09-20T09:00:00Z",
                "source_kind": "official",
                "priority": "high",
                "publisher_domain": "unknown-blog.example",
                "publisher_kind": "",
                "factual_authority": False,
            },
            {
                "source_id": "news-search",
                "title": "Общинско съобщение",
                "url": "https://news.google.com/rss/articles/x",
                "discovered_at": "2026-09-20T10:00:00Z",
                "source_kind": "aggregator",
                "priority": "normal",
                "publisher_domain": "burgas.bg",
                "publisher_kind": "official",
                "factual_authority": True,
            },
        ],
        path=newsroom.inbox_store_path(),
    )
    official = newsroom.inbox_view(status="all", authority="official")
    titles = {item["title"] for item in official["items"]}
    assert titles == {"Общинско съобщение"}

    monitoring = newsroom.inbox_view(status="all", authority="monitoring")
    monitor_titles = {item["title"] for item in monitoring["items"]}
    assert "Блог публикация" in monitor_titles
    assert "Общинско съобщение" not in monitor_titles

    body = http.html_mod.render_inbox(newsroom.inbox_view(status="all"))
    assert "издател: burgas.bg" in body and "без авторитет" in body


# ---------- AI models page (M4D) ----------
#
# The page is operator configuration: it must show every role and route, never
# echo a key, and every control must go through the same policy helpers the CLI
# uses (so the UI cannot drift from the store contract).


def test_models_page_lists_roles_routes_and_never_echoes_a_key(server, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key-value")
    html = _get(f"{server}/models").read().decode("utf-8")
    assert "AI модели" in html
    assert "Идентичност на история" in html and "Финален текст" in html
    assert "gemini-3.8-flash" in html
    assert "openai/gpt-5.6-luna" in html
    assert "собствена квота" in html  # operator-declared Gemini quota
    assert "само публични публикации" in html  # privacy flag is visible
    assert "super-secret-key-value" not in html
    assert "наличен" in html  # the page reports key presence instead


def test_models_page_writes_only_a_policy_diff(server, newsroom_dir):
    """Reordering/enabling through the UI persists without freezing other defaults."""
    from editor_assistant.drafting import model_policy as policy_mod

    resp = _post(
        f"{server}/models", {"action": "toggle", "role": "draft", "index": "0", "enabled": "0"}
    )
    assert resp.status == 303
    policy = policy_mod.load_policy()
    assert policy["roles"]["draft"]["routes"][0]["enabled"] is False
    payload = json.loads(policy_mod.policy_path().read_text(encoding="utf-8"))
    assert "judge" not in payload["roles"]
    assert set(payload["roles"]) == {"draft"}

    resp = _post(
        f"{server}/models", {"action": "move", "role": "draft", "index": "0", "direction": "down"}
    )
    assert resp.status == 303
    moved = policy_mod.load_policy()["roles"]["draft"]["routes"]
    assert moved[0]["model"] != policy["roles"]["draft"]["routes"][0]["model"]


def test_models_page_refuses_an_impossible_edit_with_a_message(server):
    resp = _post(f"{server}/models", {"action": "remove", "role": "draft", "index": "99"})
    assert resp.status == 400
    body = resp.read().decode("utf-8")
    assert "AI модели" in body and "маршрут" in body

    resp = _post(f"{server}/models", {"action": "add", "role": "draft", "provider": "gemini"})
    assert resp.status == 400
    assert "provider и model" in resp.read().decode("utf-8")


def test_models_toggle_fails_closed_when_the_policy_read_fails(server, newsroom_dir, monkeypatch):
    """M4F P3: an unreadable policy must never be guessed into an *enable*.

    The old flip path fell back to `enabled=1` on a read error — a fail-open
    money switch. Now the toggle refuses, changes nothing, and says so.
    """
    from editor_assistant.drafting import model_policy as policy_mod
    from editor_assistant.workflow.workbench import newsroom as nr

    before = policy_mod.load_policy()["roles"]["draft"]["routes"][0]["enabled"]

    def boom():
        raise OSError("policy store unreadable")

    monkeypatch.setattr(nr, "models_view", boom)
    resp = _post(f"{server}/models", {"op": "toggle", "role": "draft", "index": "0"})
    assert resp.status == 400
    assert "нищо не е променено" in resp.read().decode("utf-8")
    assert policy_mod.load_policy()["roles"]["draft"]["routes"][0]["enabled"] == before

    resp = _post(f"{server}/models", {"action": "nonsense"})
    assert resp.status == 400


def test_models_page_validate_stores_the_catalog_report(server, monkeypatch):
    """Validation runs only on the explicit action and is shown on the page."""
    from editor_assistant.drafting import model_catalog

    called = {"n": 0}

    def fake_validate(*_args, **_kwargs):
        called["n"] += 1
        return {
            "gemini_catalog": None,
            "openrouter_catalog": 24,
            "gemini_error": "липсва GEMINI_API_KEY",
            "openrouter_error": "",
            "rows": [
                {
                    "role": "story",
                    "index": 0,
                    "provider": "openrouter",
                    "model": "ghost/model:free",
                    "status": model_catalog.STATUS_INVALID,
                    "detail": "моделът липсва в текущия OpenRouter каталог",
                }
            ],
            "invalid": [{"model": "ghost/model:free"}],
            "mismatches": [],
            "unchecked": [],
        }

    monkeypatch.setattr(model_catalog, "validate_policy_models", fake_validate)
    resp = _post(f"{server}/models", {"action": "validate"})
    assert resp.status == 303
    assert called["n"] == 1
    html = _get(f"{server}/models").read().decode("utf-8")
    assert "Последна проверка в живите каталози" in html
    assert "ghost/model:free" in html and "НЕВАЛИДЕН" in html


def test_models_page_shows_global_paid_state(server):
    from editor_assistant.drafting import model_policy as policy_mod

    resp = _post(f"{server}/models", {"action": "global", "soft_paid_budget_usd_day": "1.25"})
    assert resp.status == 303
    assert policy_mod.load_policy()["global"]["soft_paid_budget_usd_day"] == 1.25
    html = _get(f"{server}/models").read().decode("utf-8")
    assert "1.25" in html


# ---------- pre-frontend gate: add-route billing/privacy safety (A) + soft paid (C) ----------


def test_models_add_openrouter_requires_an_explicit_billing_choice(server):
    """A1/A6: no billing in the form -> 400, nothing stored, no free default."""
    from editor_assistant.drafting import model_policy as policy_mod

    before = len(policy_mod.load_policy()["roles"]["draft"]["routes"])
    resp = _post(
        f"{server}/models",
        {
            "action": "add",
            "role": "draft",
            "provider": "openrouter",
            "model": "openai/gpt-5.6-luna",
        },
    )
    assert resp.status == 400
    body = resp.read().decode("utf-8")
    assert "Безплатен или Платен" in body
    after = policy_mod.load_policy()
    assert len(after["roles"]["draft"]["routes"]) == before
    assert after["global"]["paid_enabled"] is False


def test_models_add_free_openrouter_is_stored_public_only(server):
    """A2: billing=free forces public_only=true; the checkbox cannot weaken it."""
    from editor_assistant.drafting import model_policy as policy_mod

    resp = _post(
        f"{server}/models",
        {
            "action": "add",
            "role": "judge",
            "provider": "openrouter",
            "model": "vendor/new-free:free",
            "billing": "free",
            # deliberately NO public_only checkbox — the service must force it
        },
    )
    assert resp.status == 303
    route = next(
        r
        for r in policy_mod.load_policy()["roles"]["judge"]["routes"]
        if r["model"] == "vendor/new-free:free"
    )
    assert route["billing"] == "free" and route["public_only"] is True


def test_models_add_gemini_uses_operator_declared_with_known_rpd(server):
    """A4: Gemini additions never ask paid/free and inherit the local RPD."""
    from editor_assistant.drafting import model_policy as policy_mod

    resp = _post(
        f"{server}/models",
        {
            "action": "add",
            "role": "draft",
            "provider": "gemini",
            "model": "gemini-3.7-flash",
            "billing": "free",  # ignored for Gemini: the operator's own quota
        },
    )
    assert resp.status == 303
    route = next(
        r
        for r in policy_mod.load_policy()["roles"]["draft"]["routes"]
        if r["model"] == "gemini-3.7-flash" and r["provider"] == "gemini"
    )
    assert route["billing"] == "operator_declared"
    assert route["daily_call_limit"] == policy_mod.GEMINI_DAILY_LIMITS["gemini-3.7-flash"]


def test_models_add_refuses_free_when_the_cached_validation_saw_paid(server, newsroom_dir):
    """A5: a contradicting cached catalog validation refuses the edit (no network)."""
    from editor_assistant.drafting import model_policy as policy_mod

    newsroom_dir.mkdir(parents=True, exist_ok=True)
    (newsroom_dir / "model_validation.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "provider": "openrouter",
                        "model": "looks-free-but-paid",
                        "observed_free": False,
                        "observed_price_usd_per_mtok": [0.2, 1.2],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    before = len(policy_mod.load_policy()["roles"]["judge"]["routes"])
    resp = _post(
        f"{server}/models",
        {
            "action": "add",
            "role": "judge",
            "provider": "openrouter",
            "model": "looks-free-but-paid",
            "billing": "free",
        },
    )
    assert resp.status == 400
    body = resp.read().decode("utf-8")
    assert "платен" in body and "validate" in body
    assert len(policy_mod.load_policy()["roles"]["judge"]["routes"]) == before


def test_models_page_renders_the_explicit_billing_choice(server):
    """A4: the add form shows Безплатен/Платен with no blank default."""
    html = _get(f"{server}/models").read().decode("utf-8")
    assert 'name="billing"' in html
    assert "Безплатен (OpenRouter)" in html and "Платен (OpenRouter)" in html
    assert "Собствена квота (Gemini)" in html


def test_models_page_warns_when_the_paid_soft_budget_is_exceeded(server):
    """PART C: visible, non-blocking warning on the operator page."""
    from editor_assistant.drafting import model_policy as policy_mod
    from editor_assistant.drafting import model_usage

    budget = policy_mod.load_policy()["global"]["soft_paid_budget_usd_day"]
    html = _get(f"{server}/models").read().decode("utf-8")
    assert "ПРЕВИШЕН" not in html
    model_usage.record(
        {
            "role": "draft",
            "provider": "openrouter",
            "model": "openai/gpt-5.6-luna",
            "status": model_usage.STATUS_OK,
            "cost_usd": budget + 0.25,
        }
    )
    html = _get(f"{server}/models").read().decode("utf-8")
    assert "Платеният софт бюджет" in html and "не блокада" in html
