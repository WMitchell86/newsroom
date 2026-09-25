"""B4B — real «Обнови»: one editor action over the existing newsroom pipeline.

The collector adapters are injected and no HTTP happens, but nothing between
them is mocked: `newsroom_run.collect`, `story_identity.update`, the inbox and
story stores and the source-health records are the real ones. These tests pin
the product contract — one action, hidden stages, partial failure preserved,
actionable problems only, and no metadata/bootstrap side effects.
"""

from __future__ import annotations

import contextlib
import json
import time
from datetime import datetime, timezone

import pytest

from editor_assistant.workflow import (
    editor_application as app,
)
from editor_assistant.workflow import (
    inbox_store,
    newsroom_refresh,
    newsroom_run,
    source_health,
    sources_registry,
    story_editor_metadata,
    story_operations,
    story_store,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _feed(*items):
    body = "".join(
        f"<item><title>{title}</title><link>https://feed.example/{slug}</link>"
        f"<pubDate>Mon, 21 Sep 2026 06:00:00 +0300</pubDate>"
        f"<description>{summary}</description></item>"
        for slug, title, summary in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Тестова емисия</title><link>https://feed.example/</link>{body}</channel></rss>"
    ).encode()


class _Response:
    def __init__(self, payload):
        self.payload = payload


class _Failing:
    """A collector substitute that fails the way a real timeout does."""

    def __call__(self, url):
        raise OSError("Connection timed out")


def _fetch(posts):
    def fetch(url):
        return _Response(posts[str(url)])

    return fetch


def _model(relation):
    def call_model(_prompt, *, role="", **_kw):
        assert role == "story"
        return json.dumps(
            {
                "same_event": relation != "DIFFERENT_STORY",
                "relation": relation,
                "material_change": relation == "NEW_DEVELOPMENT",
                "shared_anchors": ["общински съвет"],
                "reason": "тестово решение",
            }
        ), {}

    return call_model


@pytest.fixture(autouse=True)
def newsroom(tmp_path, monkeypatch):
    """An isolated newsroom root for every test; nothing else is touched."""
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    monkeypatch.setattr(newsroom_run, "_now", lambda: NOW)
    story_operations.clear()
    yield root
    story_operations.clear()
    newsroom_refresh.release(newsroom_refresh.active_token())


def _add_source(root, source_id, *, name, collector="rss", url="https://feed.example/rss", **kw):
    sources_registry.add_source(
        path=root / "sources.json",
        source_id=source_id,
        name=name,
        kind=kw.pop("kind", "official"),
        collector=collector,
        url=url,
        priority=kw.pop("priority", "high"),
        factual_authority=kw.pop("factual_authority", True),
        **kw,
    )


def _run(root, *, fetch_bytes, **kw):
    return newsroom_refresh.refresh_newsroom(root=root, fetch_bytes=fetch_bytes, **kw)


# ---------------------------------------------------------------- successful refresh


def test_refresh_uses_the_existing_collector_and_groups_into_stories(newsroom):
    """The real collector runs; ingested material becomes a canonical Story."""
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {
        "https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава днес."))
    }

    result = _run(newsroom, fetch_bytes=_fetch(posts))

    assert result["new"] == 1
    assert result["collected"] == 1
    assert result["stories"]["newStories"] == 1
    # The inbox and the story store are the existing canonical ones.
    items = inbox_store.read_items(newsroom / "inbox.jsonl")
    stories = story_store.read_store(newsroom / "stories.json")["stories"]
    assert [row["title"] for row in items] == ["Нова сесия"]
    assert len(stories) == 1
    assert stories[0]["members"][0]["item_id"] == items[0]["item_id"]


def test_refresh_projects_no_problem_when_sources_succeed(newsroom):
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    result = _run(newsroom, fetch_bytes=_fetch(posts))

    assert result["problems"] == []
    assert newsroom_refresh.today_problems(root=newsroom) == []


def test_refresh_does_not_create_story_editor_metadata(newsroom):
    """B2.1 safe default: a new Story is readable without a metadata row."""
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    _run(newsroom, fetch_bytes=_fetch(posts))

    store = story_editor_metadata.read_story_editor_metadata_store(root=newsroom)
    assert store["stories"] == []
    # ...and the projection still works from in-memory defaults.
    assert len(app.read_today()["newStories"]) == 1


def test_refresh_result_exposes_no_pipeline_internals(newsroom):
    """Only completion metadata leaves the command — no traces or paths."""
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    result = _run(newsroom, fetch_bytes=_fetch(posts))

    assert set(result) == {
        "collected",
        "new",
        "duplicate",
        "failedSources",
        "stories",
        "problems",
        "finishedAt",
    }
    blob = json.dumps(result, ensure_ascii=False)
    assert str(newsroom) not in blob
    assert "/tmp" not in blob
    assert "collector" not in blob


# ---------------------------------------------------------------- new story / development


def test_new_story_appears_in_today_without_being_marked_reviewed(newsroom):
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    _run(newsroom, fetch_bytes=_fetch(posts))

    today = app.read_today()
    assert [row["objectId"] for row in today["newStories"]] == [today["newStories"][0]["objectId"]]
    assert today["newStories"][0]["reason"] == "NEW_STORY"
    stories = story_store.read_store(newsroom / "stories.json")["stories"]
    assert stories[0]["status"] == "NEW"


def test_new_development_reaches_a_followed_story_once_and_aggregates(newsroom):
    """Three deltas for one Story produce one attention entry with a count."""
    origin = {
        "item_id": "origin",
        "source_id": "council",
        "source_item_id": "origin",
        "title": "Общински съвет обсъжда бюджета",
        "url": "https://feed.example/origin",
        "published_at": "2026-09-21T06:00:00Z",
        "discovered_at": "2026-09-21T06:00:00Z",
        "summary": "Общински съвет обсъжда бюджета на Burgas за 2026.",
        "source_kind": "official",
        "status": "NEW",
    }
    inbox_store.save_items([origin], newsroom / "inbox.jsonl")
    story = story_store.new_story(origin, now=origin["discovered_at"])
    story["story_id"] = "s-existing"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")
    story_editor_metadata.set_story_followed(
        "s-existing", True, stories_path=newsroom / "stories.json", root=newsroom
    )

    _add_source(newsroom, "council", name="Общински съвет")
    posts = {
        "https://feed.example/rss": _feed(
            (
                "d1",
                "Общински съвет обсъжда бюджета и парка",
                "Общински съвет обсъжда бюджета и парка в Burgas през 2026.",
            ),
            (
                "d2",
                "Общински съвет обсъжда бюджета и улиците",
                "Общински съвет обсъжда бюджета и улиците в Burgas през 2026.",
            ),
            (
                "d3",
                "Общински съвет обсъжда бюджета и водата",
                "Общински съвет обсъжда бюджета и водата в Burgas през 2026.",
            ),
        )
    }

    _run(newsroom, fetch_bytes=_fetch(posts), semantic=True, call_model=_model("NEW_DEVELOPMENT"))

    stories = story_store.read_store(newsroom / "stories.json")["stories"]
    assert len(stories) == 1, "a development must not split the Story"
    developments = [m for m in stories[0]["members"] if m["relation"] == "NEW_DEVELOPMENT"]
    assert len(developments) == 3
    assert stories[0]["status"] == "NEW", "a development reopens a seen Story"

    # One attention entry for the Story, never one row per Publication. The
    # frozen lifecycle reopens a SEEN Story to NEW, so the canonical group is
    # «Нови истории»; what matters editorially is the single aggregated entry.
    today = app.read_today()
    entries = [
        row
        for group in ("newStories", "newDevelopments")
        for row in today[group]
        if row["objectId"] == "s-existing"
    ]
    assert len(entries) == 1, "one attention entry per Story, not per Publication"
    assert entries[0]["delta"]["unreviewedDevelopmentCount"] == 3
    assert entries[0]["reason"] == "NEW_STORY"


def test_duplicate_material_creates_no_false_attention(newsroom):
    """Background/same-story material is not a development and not attention."""
    origin = {
        "item_id": "origin",
        "source_id": "council",
        "source_item_id": "origin",
        "title": "Общински съвет обсъжда бюджета",
        "url": "https://feed.example/origin",
        "published_at": "2026-09-21T06:00:00Z",
        "discovered_at": "2026-09-21T06:00:00Z",
        "summary": "Общински съвет обсъжда бюджета на Burgas за 2026.",
        "source_kind": "official",
        "status": "NEW",
    }
    inbox_store.save_items([origin], newsroom / "inbox.jsonl")
    story = story_store.new_story(origin, now=origin["discovered_at"])
    story["story_id"] = "s-existing"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")
    story_editor_metadata.set_story_followed(
        "s-existing", True, stories_path=newsroom / "stories.json", root=newsroom
    )

    _add_source(newsroom, "council", name="Общински съвет")
    posts = {
        "https://feed.example/rss": _feed(
            ("d1", "Общински съвет обсъжда бюджета", "Общински съвет обсъжда бюджета днес.")
        )
    }

    _run(newsroom, fetch_bytes=_fetch(posts))

    stories = story_store.read_store(newsroom / "stories.json")["stories"]
    assert len(stories) == 1
    assert all(m["relation"] != "NEW_DEVELOPMENT" for m in stories[0]["members"])
    today = app.read_today()
    assert today["newDevelopments"] == []
    assert today["newStories"] == []


# ---------------------------------------------------------------- partial failure


def test_one_failed_source_does_not_discard_the_others(newsroom):
    """A/C material survives B's failure; the run is not rolled back."""
    _add_source(newsroom, "council", name="Общински съвет", url="https://a.example/rss")
    _add_source(newsroom, "broken", name="Счупен източник", url="https://b.example/rss")
    _add_source(newsroom, "press", name="Пресцентър", url="https://c.example/rss", kind="media")
    posts = {
        "https://a.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава днес.")),
        "https://c.example/rss": _feed(("c", "Пресцентър съобщи", "Пресцентър съобщи днес.")),
    }

    def fetch(url):
        if str(url) == "https://b.example/rss":
            raise OSError("Connection timed out")
        return _Response(posts[str(url)])

    result = newsroom_refresh.refresh_newsroom(root=newsroom, fetch_bytes=fetch)

    assert result["new"] == 2
    assert result["failedSources"] == 1
    items = {row["source_id"] for row in inbox_store.read_items(newsroom / "inbox.jsonl")}
    assert items == {"council", "press"}


def test_a_source_that_regressed_becomes_an_actionable_problem(newsroom):
    """Coverage the editor actually lost is the only thing worth interrupting for."""
    _add_source(newsroom, "council", name="Общински съвет", url="https://b.example/rss")
    good = {"https://b.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}
    _run(newsroom, fetch_bytes=_fetch(good))
    assert newsroom_refresh.today_problems(root=newsroom) == []

    newsroom_refresh.refresh_newsroom(root=newsroom, fetch_bytes=_Failing())

    problems = newsroom_refresh.today_problems(root=newsroom)
    assert len(problems) == 1
    assert "Общински съвет" in problems[0]["title"]
    assert "материал" in problems[0]["consequence"]
    assert problems[0]["target"] == "/settings"
    assert app.read_today()["problems"] == problems


def test_a_source_that_never_delivered_is_not_today_clutter(newsroom):
    """A first-time failure is diagnostics, not an editorial problem."""
    _add_source(newsroom, "broken", name="Общински съвет", url="https://b.example/rss")

    newsroom_refresh.refresh_newsroom(root=newsroom, fetch_bytes=_Failing())

    health = source_health.read_health(newsroom / "source_health.json")
    assert health["broken"]["last_status"] == source_health.FAILED
    assert newsroom_refresh.today_problems(root=newsroom) == []


def test_a_working_mirror_that_breaks_is_reported_with_consequence_only(newsroom):
    """A regression is reported, but never as a raw error trace."""
    _add_source(newsroom, "council", name="Общински съвет", url="https://a.example/rss")
    _add_source(newsroom, "mirror", name="Огледало", url="https://b.example/rss", kind="media")
    both = {
        "https://a.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава.")),
        "https://b.example/rss": _feed(("b", "Огледало", "Огледало отразява новината.")),
    }
    _run(newsroom, fetch_bytes=_fetch(both))

    def fetch(url):
        if str(url) == "https://b.example/rss":
            raise OSError("Connection timed out to internal-proxy-9:8080")
        return _Response(both[str(url)])

    newsroom_refresh.refresh_newsroom(root=newsroom, fetch_bytes=fetch)

    problems = newsroom_refresh.today_problems(root=newsroom)
    assert [row["title"] for row in problems] == ["Източникът „Огледало“ не се обнови"]
    blob = json.dumps(problems, ensure_ascii=False)
    assert "internal-proxy-9" not in blob and "timed out" not in blob


def test_disabled_and_unsupported_sources_are_never_editorial_problems(newsroom):
    _add_source(newsroom, "muted-one", name="Заглушен", url="https://m.example/rss")
    sources_registry.set_status(
        "muted-one", "muted", muted_until="2026-12-31", path=newsroom / "sources.json"
    )
    _add_source(newsroom, "web-one", name="Уеб страница", url="https://w.example/", collector="web")
    source_health.record_source(
        "muted-one",
        status=source_health.FAILED,
        success=False,
        now=NOW,
        path=newsroom / "source_health.json",
    )
    source_health.record_source(
        "web-one",
        status=source_health.FAILED,
        success=False,
        now=NOW,
        path=newsroom / "source_health.json",
    )

    assert newsroom_refresh.today_problems(root=newsroom) == []


# ---------------------------------------------------------------- availability / integrity


def test_refresh_is_unavailable_without_active_sources(newsroom):
    with pytest.raises(newsroom_refresh.RefreshUnavailable):
        newsroom_refresh.refresh_newsroom(root=newsroom, fetch_bytes=_Failing())


def test_refresh_that_cannot_run_safely_leaves_previous_stores_valid(newsroom):
    """The collection lock is held (cron/CLI): refuse, never interleave writes."""
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}
    _run(newsroom, fetch_bytes=_fetch(posts))
    before_items = inbox_store.read_items(newsroom / "inbox.jsonl")
    before_stories = story_store.read_store(newsroom / "stories.json")

    assert newsroom_run.acquire_lock(root=newsroom) is True
    try:
        with pytest.raises(newsroom_refresh.RefreshBusy):
            newsroom_refresh.refresh_newsroom(root=newsroom, fetch_bytes=_fetch(posts))
    finally:
        newsroom_run.release_lock(newsroom)

    # Nothing was corrupted or duplicated: the previous canonical state is
    # still readable and schema-valid.
    assert inbox_store.read_items(newsroom / "inbox.jsonl") == before_items
    story_store.validate_store(story_store.read_store(newsroom / "stories.json"))
    assert story_store.read_store(newsroom / "stories.json") == before_stories


def test_a_totally_failing_source_does_not_corrupt_previous_stores(newsroom):
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}
    _run(newsroom, fetch_bytes=_fetch(posts))
    before_stories = story_store.read_store(newsroom / "stories.json")

    result = newsroom_refresh.refresh_newsroom(root=newsroom, fetch_bytes=_Failing())

    assert result["new"] == 0
    assert result["failedSources"] == 1
    story_store.validate_store(story_store.read_store(newsroom / "stories.json"))
    assert story_store.read_store(newsroom / "stories.json") == before_stories


def test_refresh_never_calls_story_research(newsroom):
    """B4A separation: «Обнови» must not resolve Story gaps."""
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    _run(newsroom, fetch_bytes=_fetch(posts))

    assert not (newsroom / "story_research.json").exists()
    from editor_assistant.workflow import story_research_store

    assert (
        story_research_store.get_story_research(
            story_store.read_store(newsroom / "stories.json")["stories"][0]["story_id"]
        )["research_rounds"]
        == 0
    )


@contextlib.contextmanager
def _real_fetcher(posts):
    """Substitute only the external fetch boundary; keep it in place until done."""
    from editor_assistant.sources import fetcher

    original = fetcher.fetch_bytes
    fetcher.fetch_bytes = lambda url: _Response(posts[str(url)])
    try:
        yield
    finally:
        fetcher.fetch_bytes = original


def test_refresh_is_idempotent_for_a_repeated_key(newsroom):
    """A retried request must not collect the newsroom twice."""
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    with _real_fetcher(posts):
        first = app.start_newsroom_refresh(idempotency_key="key-1")
        _wait(first["operationToken"])
        second = app.start_newsroom_refresh(idempotency_key="key-1")
        _wait(second["operationToken"])

    assert second["operationToken"] == first["operationToken"]
    assert len(inbox_store.read_items(newsroom / "inbox.jsonl")) == 1
    assert len(story_store.read_store(newsroom / "stories.json")["stories"]) == 1


def test_a_new_key_after_a_completed_refresh_starts_a_new_operation(newsroom):
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    with _real_fetcher(posts):
        first = app.start_newsroom_refresh(idempotency_key="key-1")
        _wait(first["operationToken"])
        second = app.start_newsroom_refresh(idempotency_key="key-2")
        _wait(second["operationToken"])

    assert second["operationToken"] != first["operationToken"]


def test_overlapping_refresh_returns_the_running_operation(newsroom):
    """One canonical mutation at a time; the second request is not a race."""
    _add_source(newsroom, "council", name="Общински съвет")
    posts = {"https://feed.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    with _real_fetcher(posts):
        first = app.start_newsroom_refresh()
        second = app.start_newsroom_refresh()
        _wait(first["operationToken"])

    assert second["operationToken"] == first["operationToken"]
    assert len(inbox_store.read_items(newsroom / "inbox.jsonl")) == 1
    assert newsroom_refresh.active_token() == "", "the guard is released after the run"


def _wait(token, *, attempts=400):
    for _ in range(attempts):
        row = story_operations.get(token)
        if row and row["status"] in {"succeeded", "failed"}:
            return row
        time.sleep(0.02)
    raise AssertionError("operation did not finish")


def test_partial_success_still_completes_the_operation(newsroom):
    """One dead source is a partial success, not a total failure."""
    _add_source(newsroom, "council", name="Общински съвет", url="https://a.example/rss")
    _add_source(newsroom, "broken", name="Счупен", url="https://b.example/rss")
    posts = {"https://a.example/rss": _feed(("a", "Нова сесия", "Общински съвет заседава."))}

    from editor_assistant.sources import fetcher

    def fetch(url):
        if str(url) == "https://b.example/rss":
            raise OSError("Connection timed out")
        return _Response(posts[str(url)])

    original = fetcher.fetch_bytes
    fetcher.fetch_bytes = fetch
    try:
        started = app.start_newsroom_refresh()
        _wait(started["operationToken"])
    finally:
        fetcher.fetch_bytes = original

    status = app.operation_status(started["operationToken"])
    assert status["status"] == "succeeded"
    assert status["result"]["new"] == 1
    assert status["result"]["failedSources"] == 1


def test_a_broken_refresh_reports_only_a_sanitized_editor_error(newsroom, monkeypatch):
    """No provider name, raw trace or filesystem path reaches the editor."""
    _add_source(newsroom, "council", name="Общински съвет")

    def explode(**_kw):
        raise RuntimeError("openrouter/gemini-3 failed at /home/test/.config/router.json")

    monkeypatch.setattr(newsroom_refresh, "refresh_newsroom", explode)
    started = app.start_newsroom_refresh()
    _wait(started["operationToken"])

    status = app.operation_status(started["operationToken"])
    assert status["status"] == "failed"
    assert status["error"] == {
        "code": "SOURCE_UNAVAILABLE",
        "message": "Новините не можаха да се обновят.",
        "retryable": True,
    }
    blob = json.dumps(status, ensure_ascii=False)
    assert "gemini" not in blob and "router.json" not in blob


def test_the_refresh_guard_is_released_after_a_failed_run(newsroom, monkeypatch):
    _add_source(newsroom, "council", name="Общински съвет")

    def explode(**_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(newsroom_refresh, "refresh_newsroom", explode)
    started = app.start_newsroom_refresh()
    _wait(started["operationToken"])

    assert newsroom_refresh.active_token() == "", "a failed run must not wedge the command"
