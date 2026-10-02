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
    # V1.2-G4.5: a refresh failure with no classified cause gets the neutral
    # refresh sentence. The previous answer hardcoded `SOURCE_UNAVAILABLE` /
    # "Новините не можаха да се обновят.", which blamed a source for an
    # exception that observed no source problem.
    assert status["error"] == {
        "code": "REFRESH_UNAVAILABLE",
        "message": "Обновяването не можа да завърши поради технически проблем. Опитайте отново.",
        "retryable": True,
    }
    blob = json.dumps(status, ensure_ascii=False)
    assert "gemini" not in blob and "router.json" not in blob
    assert "източник" not in status["error"]["message"], "no invented cause"


def test_the_refresh_guard_is_released_after_a_failed_run(newsroom, monkeypatch):
    _add_source(newsroom, "council", name="Общински съвет")

    def explode(**_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(newsroom_refresh, "refresh_newsroom", explode)
    started = app.start_newsroom_refresh()
    _wait(started["operationToken"])

    assert newsroom_refresh.active_token() == "", "a failed run must not wedge the command"


# --------------------------------------------------------------------------
# V1.2-G4.5 — the console summary must not lie by omission
# --------------------------------------------------------------------------


def test_the_refresh_summary_says_when_story_grouping_silently_failed():
    """The measured failure: a day of unmerged duplicates with a clean-looking log.

    A real run on 2026-09-28 recorded `semanticDegradedUnavailable: 5`,
    `semanticAnswered: 0` and `lastSuccessfulSemanticClassificationAt: null` in
    its JSON, and printed an ordinary summary. Every count looked fine, so nobody
    knew the newsroom could not merge two publishers covering one event. The
    summary is the operator's only view of a cron run, so the verdict belongs in
    it.
    """
    from editor_assistant.workflow.cli import render_refresh_summary

    stories = {
        "new_stories": 8,
        "relations": {"NEW_DEVELOPMENT": 3},
        "deterministic_matches": 0,
        "semantic_matches": 0,
        "exact_duplicates": 0,
        "needs_review": 0,
        "grouping": {
            "status": "unavailable",
            "semanticRequired": 5,
            "semanticAnswered": 0,
            "semanticDegraded": 5,
            "semanticDegradedUnavailable": 5,
            "semanticDegradedBudgetExhausted": 0,
            "lastSuccessfulSemanticClassificationAt": None,
        },
    }
    out = render_refresh_summary(
        {"dry_run": False, "sources": [1] * 9, "new": 12, "failed": 0}, stories, ""
    )

    assert "0/5" in out, out
    assert "ВНИМАНИЕ" in out, out
    assert "5 недостъпен модел" in out, out
    # The strongest statement available, and the one that was missing.
    assert "не е работило нито веднъж" in out, out


def test_a_healthy_grouping_is_reported_without_a_warning():
    """The warning must mean something: silence when nothing degraded."""
    from editor_assistant.workflow.cli import render_refresh_summary

    out = render_refresh_summary(
        {"dry_run": False, "sources": [1] * 9, "new": 12, "failed": 0},
        {
            "new_stories": 8,
            "relations": {},
            "deterministic_matches": 2,
            "semantic_matches": 1,
            "exact_duplicates": 0,
            "needs_review": 0,
            "grouping": {
                "status": "healthy",
                "semanticRequired": 3,
                "semanticAnswered": 3,
                "semanticDegraded": 0,
                "lastSuccessfulSemanticClassificationAt": "2026-09-29T06:00:00Z",
            },
        },
        "",
    )

    assert "3/3" in out, out
    assert "ВНИМАНИЕ" not in out, out
    assert "не е работило нито веднъж" not in out, out


# --------------------------------------------------------------------------
# V1.2-G4.5 — one health verdict, instead of a status nobody reads
# --------------------------------------------------------------------------


def test_doctor_reports_a_role_with_no_usable_route_and_its_consequence(monkeypatch, tmp_path):
    """The check that would have caught the 2026-09-28 outage on its first run.

    Every route of the `story` role was marked EXHAUSTED for a day, so two
    publishers covering one event were never merged. `models status` printed it
    as seven crosses inside a list of checkmarks and nobody looked; the JSON knew
    and nobody opened it. This is one screen, and it exits non-zero so a cron can
    notice without a human reading anything.
    """
    from editor_assistant.drafting import model_router
    from editor_assistant.workflow import cli

    def dead(role, policy, **kw):
        rows = [
            {"model": f"m{i}", "eligible": False, "reason": "маршрутът е EXHAUSTED"}
            for i in range(3)
        ]
        return {"routes": rows, "on_exhausted": "conservative"}

    def alive(role, policy, **kw):
        return {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        }

    monkeypatch.setattr(
        model_router, "plan_routes", lambda role, policy=None, **kw: (
            dead(role, policy) if role == "story" else alive(role, policy)
        )
    )
    monkeypatch.setattr(
        "editor_assistant.drafting.model_policy.load_policy",
        lambda: {"roles": {"story": {}, "draft": {}}},
    )
    from editor_assistant.workflow import source_health

    monkeypatch.setattr(
        source_health, "read_last_run", lambda path=None: {"finished_at": ""}
    )

    report, code = cli.newsroom_doctor()
    assert code == 1, "a dead role must be visible to a cron"
    assert "story" in report
    assert "ПРОБЛЕМ" in report, report
    # The consequence, not just the fact: a role with no route does not fail
    # loudly, it quietly does less.
    assert "слива само при пълна сигурност" in report, report
    # And the single command most likely to fix it.
    assert "newsroom models validate" in report, report


def test_doctor_is_quiet_when_everything_is_healthy(monkeypatch):
    """A warning that always fires is a warning nobody reads."""
    from editor_assistant.drafting import model_policy, model_router
    from editor_assistant.workflow import cli, source_health

    monkeypatch.setattr(
        model_router,
        "plan_routes",
        lambda role, policy=None, **kw: {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        },
    )
    monkeypatch.setattr(model_policy, "load_policy", lambda: {"roles": {"draft": {}}})
    monkeypatch.setattr(
        source_health,
        "read_last_run",
        lambda path=None: {
            "finished_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grouping": {"semanticRequired": 3, "semanticAnswered": 3, "semanticDegraded": 0},
        },
    )

    report, code = cli.newsroom_doctor()
    assert code == 0, report
    assert "ПРОБЛЕМ" not in report, report
    assert "3/3" in report, report


# --------------------------------------------------------------------------
# V1.2-G4.5 — self-repair, and the rule that keeps it honest
# --------------------------------------------------------------------------


def test_repair_does_nothing_while_every_role_can_route(monkeypatch):
    """A repair that runs always is a repair that can mask a real outage.

    The safety rule: a mark is only touched when its role has NO routable path.
    While the system can still work, clearing a mark would let a genuinely spent
    quota be re-tried forever, so this must be a no-op.
    """
    from editor_assistant.drafting import model_catalog, model_policy, model_router
    from editor_assistant.workflow import cli

    monkeypatch.setattr(
        model_router,
        "plan_routes",
        lambda role, policy=None, **kw: {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        },
    )
    monkeypatch.setattr(model_policy, "load_policy", lambda: {"roles": {"draft": {}}})
    monkeypatch.setattr(
        model_catalog,
        "validate_policy_models",
        lambda *a, **kw: pytest.fail("must not contact a provider when nothing is broken"),
    )
    cleared = []
    monkeypatch.setattr(model_router, "clear_route", lambda route: cleared.append(route))

    report, code = cli.newsroom_repair()

    assert code == 0
    assert cleared == [], "a working system must not have its marks cleared"
    assert "нищо не се прави" in report


def test_repair_clears_a_wrong_mark_on_a_role_with_no_route(monkeypatch):
    """The measured outage, undone.

    Every `story` route was marked EXHAUSTED while all seven models were present
    in the provider catalogues. A role with no path at all cannot work, so
    revalidating it and clearing the marks that do not belong is strictly better
    than trying nothing.
    """
    from editor_assistant.drafting import model_catalog, model_policy, model_router
    from editor_assistant.workflow import cli

    def plan_for(role, policy=None, **kw):
        if role == "story":
            return {
                "routes": [{"model": "m1", "eligible": False, "reason": "EXHAUSTED"}],
                "on_exhausted": "conservative",
            }
        return {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        }

    monkeypatch.setattr(model_router, "plan_routes", plan_for)
    monkeypatch.setattr(
        model_policy, "load_policy", lambda: {"roles": {"story": {}, "draft": {}}}
    )
    monkeypatch.setattr(
        model_catalog,
        "validate_policy_models",
        lambda *a, **kw: {
            "rows": [
                {
                    "role": "story",
                    "provider": "gemini",
                    "model": "m1",
                    "status": model_catalog.STATUS_OK,
                    "detail": "наличен",
                }
            ]
        },
    )
    cleared = []
    monkeypatch.setattr(model_router, "clear_route", lambda route: cleared.append(route))

    report, code = cli.newsroom_repair()

    assert code == 0
    assert cleared == [{"provider": "gemini", "model": "m1"}]
    assert "ИЗЧИСТЕНИ" in report


def test_doctor_records_its_verdict_so_status_is_history_not_a_snapshot(monkeypatch, tmp_path):
    """A status recomputed on demand is only as good as remembering to look.

    The record is what lets the product say "healthy for 6 hours" or "last
    checked 40 minutes ago", and it is what makes a regression visible
    afterwards instead of only during the run that caught it.
    """
    from editor_assistant.workflow import cli

    path = tmp_path / "doctor_status.json"
    monkeypatch.setattr(cli, "_record_doctor_status", lambda record: path.write_text(
        __import__("json").dumps(record, ensure_ascii=False), encoding="utf-8"
    ))
    from editor_assistant.drafting import model_policy, model_router
    from editor_assistant.workflow import source_health

    monkeypatch.setattr(
        model_router,
        "plan_routes",
        lambda role, policy=None, **kw: {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        },
    )
    monkeypatch.setattr(model_policy, "load_policy", lambda: {"roles": {"draft": {}}})
    monkeypatch.setattr(
        source_health, "read_last_run", lambda path=None: {"finished_at": ""}
    )
    monkeypatch.setattr(cli, "cron_status", lambda: {"readable": True, "missing": [], "present": ["a"]})

    _report, _code = cli.newsroom_doctor()

    record = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert record["cronMissing"] == []
    assert record["stale"] is True
    assert "ok" in record


def test_doctor_reports_a_missing_cron_job_rather_than_assuming_it(monkeypatch):
    """A crontab lost to a reinstall is the quietest breakage there is.

    The newsroom simply stops updating and every number still looks plausible,
    so the schedule is part of what a health check checks.
    """
    from editor_assistant.workflow import cli

    monkeypatch.setattr(
        cli,
        "cron_status",
        lambda: {"readable": True, "missing": ["newsroom refresh"], "present": []},
    )
    from editor_assistant.drafting import model_policy, model_router
    from editor_assistant.workflow import source_health

    monkeypatch.setattr(
        model_router,
        "plan_routes",
        lambda role, policy=None, **kw: {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        },
    )
    monkeypatch.setattr(model_policy, "load_policy", lambda: {"roles": {"draft": {}}})
    monkeypatch.setattr(
        source_health,
        "read_last_run",
        lambda path=None: {"finished_at": "2026-09-29T06:00:00Z"},
    )
    monkeypatch.setattr(cli, "_record_doctor_status", lambda record: None)

    report, code = cli.newsroom_doctor()

    assert code == 1, "a missing schedule must be visible"
    assert "newsroom refresh" in report
    assert "РАЗПИС" in report


def test_an_unreadable_crontab_is_not_reported_as_missing():
    """Cannot tell is not the same as absent."""
    from editor_assistant.workflow import cli

    class Boom:
        def run(self, *a, **kw):
            raise OSError("crontab not found")

    import subprocess

    monkey = __import__("pytest").MonkeyPatch()
    monkey.setattr(subprocess, "run", Boom().run)
    try:
        result = cli.cron_status()
        assert result["readable"] is False
        assert result["missing"] == []
        assert result["present"] == []
    finally:
        monkey.undo()
def _fake_crontab(text: str):
    """A `subprocess.run` replacement returning `text` as `crontab -l` output."""

    class _Result:
        stdout = text
        stderr = ""
        returncode = 0

    return lambda *args, **kwargs: _Result()


def test_a_missing_log_directory_is_reported_even_when_every_cron_line_is_present(monkeypatch):
    """The silent failure this guards: crontab present, jobs never run.

    `var/` is gitignored, so a fresh checkout has no `var/cron/`. The shell
    opens the crontab's `>> var/cron/x.log` redirect BEFORE running the command,
    so the job dies at the redirect with exit 2 and writes nothing. The old
    check only string-matched the crontab, so `doctor` answered
    "РАЗПИС: на място (4 задачи)" about four jobs that could not run once.

    The assertion is on the DOCTOR's words, not on a helper's return value,
    because the sentence the editor reads is the thing that was wrong.
    """
    from editor_assistant.workflow import cli

    monkeypatch.setattr(
        cli,
        "cron_status",
        lambda: {
            "readable": True,
            "missing": [],
            "present": ["newsroom repair", "newsroom refresh"],
            "logDir": "/home/test/media/var/cron",
            "logDirOk": False,
        },
    )
    from editor_assistant.drafting import model_policy, model_router
    from editor_assistant.workflow import source_health

    monkeypatch.setattr(
        model_router,
        "plan_routes",
        lambda role, policy=None, **kw: {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        },
    )
    monkeypatch.setattr(model_policy, "load_policy", lambda: {"roles": {"draft": {}}})
    monkeypatch.setattr(
        source_health,
        "read_last_run",
        lambda path=None: {"finished_at": "2026-10-01T14:17:08Z"},
    )
    monkeypatch.setattr(cli, "_record_doctor_status", lambda record: None)

    report, code = cli.newsroom_doctor()

    assert code == 1, "a schedule that cannot run must not be reported healthy"
    assert "var/cron" in report
    assert "не е на място" not in report
    assert "на място (" not in report


def test_every_cron_line_creates_its_own_log_directory_before_the_redirect():
    """The `mkdir -p` must come BEFORE `>>`, or it cannot help.

    Ordering is the whole fix: a redirect is opened before the command runs, so
    a `mkdir` after it (or inside the script) is too late. Asserted on the line
    text because that is what the operator pastes into `crontab -e`.
    """
    from editor_assistant.workflow import cli

    for schedule, command, log_name in cli.NEWSROOM_CRONS:
        line = cli.cron_line(schedule, command, log_name)
        mkdir_at = line.index("mkdir -p")
        redirect_at = line.index(">>")
        assert mkdir_at < redirect_at, f"mkdir must precede the redirect: {line}"
        assert line.endswith(f">> {cli.ROOT}/{cli.CRON_LOG_DIR}/{log_name} 2>&1")


def _ok_collect(**kw):
    from editor_assistant.workflow import source_health

    summary = {
        "dry_run": False,
        "locked": False,
        "started_at": "2026-09-20T12:00:00Z",
        "finished_at": "2026-09-20T12:00:01Z",
        "collected": 0,
        "new": 0,
        "duplicate": 0,
        "failed": 0,
        "sources": [],
        "by_collector": {},
        "estimated_network_calls": 0,
        "network_calls": 0,
        "unsupported": 0,
        "skipped_invalid": 0,
        "blocked": 0,
        "blocked_filtered": 0,
        "cadence_skipped": 0,
        "bootstrap_capped": 0,
        "excluded": {},
    }
    # The real `collect` persists the collection summary before stories run;
    # the CLI merge step (`record_run_stories`/`record_run_grouping`) refuses
    # to invent a run, so the double must do the same ordering.
    source_health.record_run(summary)
    return summary


def _story_summary(**over):
    base = {
        "new_stories": 2,
        "relations": {"NEW_DEVELOPMENT": 0},
        "deterministic_matches": 0,
        "semantic_matches": 0,
        "exact_duplicates": 0,
        "needs_review": 0,
        "grouping": {"status": "degraded"},
    }
    base.update(over)
    return base


def test_cli_refresh_records_grouping_and_story_count_on_the_real_last_run(
    newsroom, monkeypatch, capsys
):
    """The open §7 defect: the cron path left `grouping` unrecorded.

    `_run_newsroom_refresh` is what `crontab` calls every hour; a run through
    it must land `new_stories` and `grouping` on the same `last_run.json`
    `refresh_newsroom` writes, so `GET /api/v1/today` stops answering
    `groupingHealth: null` for cron-refreshed runs.
    """
    from types import SimpleNamespace

    from editor_assistant.workflow import cli, newsroom_run, source_health, story_identity

    _add_source(newsroom, "council-feed", name="Съвет")
    monkeypatch.setattr(newsroom_run, "collect", lambda **kw: _ok_collect(**kw))
    monkeypatch.setattr(
        story_identity,
        "update",
        lambda **kw: _story_summary(),
    )

    cli._run_newsroom_refresh(
        SimpleNamespace(dry_run=False, source=None, limit=None, force=False, no_semantic=False)
    )
    capsys.readouterr()

    stored = source_health.read_last_run(newsroom / "last_run.json")
    assert stored["new_stories"] == 2
    assert stored["grouping"] == {"status": "degraded"}


def test_cli_refresh_dry_run_records_nothing(newsroom, monkeypatch, capsys):
    """A preview must not invent a run: no `grouping` block appears from `--dry-run`."""
    from types import SimpleNamespace

    from editor_assistant.workflow import cli, newsroom_run, source_health, story_identity

    _add_source(newsroom, "council-feed", name="Съвет")

    def _dry_collect(**kw):
        # The real `collect(dry_run=True)` writes nothing; the double must match.
        return {
            "dry_run": True,
            "locked": False,
            "started_at": "2026-09-20T12:00:00Z",
            "finished_at": "2026-09-20T12:00:01Z",
            "collected": 0,
            "new": 0,
            "duplicate": 0,
            "failed": 0,
            "sources": [],
        }

    monkeypatch.setattr(newsroom_run, "collect", _dry_collect)
    monkeypatch.setattr(
        story_identity,
        "update",
        lambda **kw: _story_summary(),
    )

    cli._run_newsroom_refresh(
        SimpleNamespace(dry_run=True, source=None, limit=None, force=False, no_semantic=False)
    )
    capsys.readouterr()

    assert source_health.read_last_run(newsroom / "last_run.json") is None


def test_cli_refresh_no_semantic_records_unavailable(newsroom, monkeypatch, capsys):
    """A deliberate `--no-semantic` run says so; it never reports a false `healthy`."""
    from types import SimpleNamespace

    from editor_assistant.workflow import cli, newsroom_run, source_health, story_identity

    _add_source(newsroom, "council-feed", name="Съвет")
    monkeypatch.setattr(newsroom_run, "collect", lambda **kw: _ok_collect(**kw))
    monkeypatch.setattr(
        story_identity,
        "update",
        lambda **kw: _story_summary(new_stories=0, grouping={"status": "healthy"}),
    )

    cli._run_newsroom_refresh(
        SimpleNamespace(dry_run=False, source=None, limit=None, force=False, no_semantic=True)
    )
    capsys.readouterr()

    stored = source_health.read_last_run(newsroom / "last_run.json")
    assert stored["grouping"]["status"] == "unavailable"


def test_cli_refresh_story_failure_leaves_grouping_unknown(newsroom, monkeypatch, capsys):
    """A story-stage failure must not attribute a previous run's health to this one."""
    from types import SimpleNamespace

    from editor_assistant.workflow import cli, newsroom_run, source_health, story_identity

    _add_source(newsroom, "council-feed", name="Съвет")
    monkeypatch.setattr(newsroom_run, "collect", lambda **kw: _ok_collect(**kw))

    def _boom(**kw):
        raise RuntimeError("story store unwritable")

    monkeypatch.setattr(story_identity, "update", _boom)

    cli._run_newsroom_refresh(
        SimpleNamespace(dry_run=False, source=None, limit=None, force=False, no_semantic=False)
    )
    out = capsys.readouterr().out

    assert "истории: RuntimeError" in out
    stored = source_health.read_last_run(newsroom / "last_run.json")
    assert stored is not None and "grouping" not in stored


def test_a_commented_cron_line_is_not_reported_as_present(monkeypatch):
    """A `#`-commented job never runs; the matcher must not claim it is installed.

    Measured failure mode: `cron_status` used `line in out`, so a commented
    line still contained the canonical substring and `doctor` counted a
    disabled job as present. Reproduced before the fix: `"# " + line`
    matched; after the fix it does not.
    """
    from editor_assistant.workflow import cli

    canonical = [cli.cron_line(s, c, l) for s, c, l in cli.NEWSROOM_CRONS]
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        _fake_crontab("# " + canonical[0] + "\n" + "\n".join(canonical[1:])),
    )
    (cli.ROOT / cli.CRON_LOG_DIR).mkdir(parents=True, exist_ok=True)

    status = cli.cron_status()

    assert cli.NEWSROOM_CRONS[0][1] in status["missing"], status
    assert cli.NEWSROOM_CRONS[0][1] not in status["present"], status


def test_cron_status_reports_a_missing_log_directory_as_not_ok(monkeypatch, tmp_path):
    """`logDirOk` is measured, never assumed."""
    from editor_assistant.workflow import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path / "no-such-checkout")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        _fake_crontab("\n".join(cli.cron_line(s, c, l) for s, c, l in cli.NEWSROOM_CRONS)),
    )

    status = cli.cron_status()

    assert status["missing"] == [], "the crontab lines themselves are present"
    assert status["logDirOk"] is False, "the directory they log into is not"


def test_cron_status_is_ok_once_the_log_directory_exists(monkeypatch, tmp_path):
    from editor_assistant.workflow import cli

    root = tmp_path / "checkout"
    (root / cli.CRON_LOG_DIR).mkdir(parents=True)
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        _fake_crontab("\n".join(cli.cron_line(s, c, l) for s, c, l in cli.NEWSROOM_CRONS)),
    )

    status = cli.cron_status()

    assert status["logDirOk"] is True
    assert status["missing"] == []
    assert len(status["present"]) == len(cli.NEWSROOM_CRONS)


def test_the_installed_crontab_line_is_what_cron_status_looks_for(monkeypatch):
    """The drift trap from 849b455, closed for the log-directory prefix too.

    Editing the crontab without editing `NEWSROOM_CRONS` is what once made the
    doctor report a missing job about a desk that was collecting fine. The
    `mkdir -p` prefix is part of the matched line, so it has the same exposure
    and the same guard.
    """
    from editor_assistant.workflow import cli

    installed = "\n".join(cli.cron_line(s, c, l) for s, c, l in cli.NEWSROOM_CRONS)
    monkeypatch.setattr(cli.subprocess, "run", _fake_crontab(installed))

    status = cli.cron_status()

    assert status["missing"] == []


def test_a_stale_crontab_without_the_mkdir_prefix_is_reported_as_missing(monkeypatch):
    """The OLD line shape must no longer satisfy the check.

    This is the whole point: the four lines installed before this fix are
    broken on a fresh checkout, so if they still matched, the fix would be
    invisible and the next reinstall would silently reintroduce it.
    """
    from editor_assistant.workflow import cli

    old_style = "\n".join(
        f"{s} {cli.CRON_ENTRY} {c} >> {cli.ROOT}/{cli.CRON_LOG_DIR}/{l} 2>&1"
        for s, c, l in cli.NEWSROOM_CRONS
    )
    monkeypatch.setattr(cli.subprocess, "run", _fake_crontab(old_style))

    status = cli.cron_status()

    assert status["missing"], "the pre-fix crontab must not pass as installed"
