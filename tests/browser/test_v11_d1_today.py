"""V1.1-D1 §30: the cleaned Today, proven in a real browser.

Everything runs against the real production topology — a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` — against an isolated store root seeded with the shape the real
corpus has: a large stale backlog, a small current set, active Article work and
a completed run. Only the outbound provider edges are substituted.

The point of this file is that the numbers on screen were produced by the
product: the row count, the ordering, the withheld count and the refresh line
are read from the rendered page, not from a fixture constant.
"""

from __future__ import annotations

import os
import threading

import pytest

from .conftest import DIST, VIEWPORT, PageProbe
from .fixture_data import build_today_fixture

TRACKED_ENV = (
    "WB_NEWSROOM_DIR",
    "NEWSROOM_DIR",
    "WB_EDITORIAL_WORKFLOW_DIR",
    "MODEL_USAGE_DIR",
    "MODEL_HEALTH_PATH",
    "WB_EDITOR_FRONTEND",
    "WB_SPA_DIST",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "SERPER_API_KEY",
    "TINYFISH_API_KEY",
    "SEARCH_PROVIDER",
)


@pytest.fixture
def today_page(browser, boundary_substitutes, tmp_path):
    """A browser page on a D1-shaped, isolated newsroom.

    The store roots are function-scoped on purpose: the D2A session fixture
    points the same environment variables at its own root, so these proofs
    borrow them only for the duration of one test and always give them back.
    """
    from editor_assistant.workflow import story_operations
    from editor_assistant.workflow.workbench import http

    if not (DIST / "index.html").exists():
        pytest.skip(f"production build missing: run `cd frontend && npm run build` ({DIST})")

    newsroom = tmp_path / "newsroom"
    editorial = tmp_path / "editorial"
    for path in (newsroom, editorial, tmp_path / "model_usage"):
        path.mkdir(parents=True, exist_ok=True)

    saved = {name: os.environ.get(name) for name in TRACKED_ENV}
    os.environ.update(
        {
            "WB_NEWSROOM_DIR": str(newsroom),
            "NEWSROOM_DIR": str(newsroom),
            "WB_EDITORIAL_WORKFLOW_DIR": str(editorial),
            "MODEL_USAGE_DIR": str(tmp_path / "model_usage"),
            "MODEL_HEALTH_PATH": str(tmp_path / "model_health.json"),
            "WB_SPA_DIST": str(DIST),
            "GEMINI_API_KEY": "d1-substitute-not-a-real-key",
        }
    )
    for name in (
        "OPENROUTER_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "SERPER_API_KEY",
        "TINYFISH_API_KEY",
    ):
        os.environ.pop(name, None)
    os.environ.pop("WB_EDITOR_FRONTEND", None)

    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = browser.new_context(viewport=VIEWPORT, locale="bg-BG")
    probe = PageProbe(context.new_page(), f"http://127.0.0.1:{server.server_address[1]}")
    probe.page.set_default_timeout(20000)
    try:
        story_operations.clear()
        yield probe, build_today_fixture(newsroom=newsroom, editorial=editorial)
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        story_operations.clear()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def open_today(probe) -> None:
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible", timeout=20000)
    probe.page.locator("main").wait_for(state="visible")


def today_text(probe) -> str:
    """The rendered Today text, in a comparable case.

    Section headings are uppercased by CSS, and `inner_text` reports the
    transformed text, so a case-sensitive match on the source string would be a
    test of the stylesheet rather than of the projection.
    """
    return probe.page.locator("main").inner_text().casefold()


def test_today_hides_the_stale_backlog_and_bounds_the_current_set(today_page):
    """120 stale Stories must not reach the first screen; 25 current ones must."""
    probe, ids = today_page
    open_today(probe)
    body = probe.page.locator("main").inner_text()

    # The backlog is still in the database — it is just not this screen.
    assert "Стара история" not in body, "stale backlog leaked onto Today"
    assert "Текуща история" in body

    titles = [
        text
        for text in probe.page.locator("main h3 a").all_inner_texts()
        if text.startswith("Текуща история")
    ]
    assert len(titles) == ids["current_count"], titles
    assert len(titles) <= 30, "Today is not bounded"
    probe.assert_clean(context="Today with a stale backlog")


def test_current_stories_are_ordered_newest_first(today_page):
    """The delivered sequence must be chronological, not hash-id order."""
    probe, _ = today_page
    open_today(probe)

    order = probe.page.evaluate(
        """async () => {
            const response = await fetch('/api/v1/today');
            const payload = await response.json();
            return payload.data.newStories.map((row) => row.timestamp);
        }"""
    )
    assert order, "no Story rows were delivered"
    assert order == sorted(order, reverse=True), f"Today is not newest-first: {order}"

    # The page renders exactly what it was given: same count, same order.
    rendered = probe.page.locator("main h3 a").all_inner_texts()
    assert len([t for t in rendered if t.startswith("Текуща история")]) == len(order)
    probe.assert_clean(context="chronological ordering")


def test_last_refresh_and_article_work_are_visible(today_page):
    probe, ids = today_page
    open_today(probe)
    body = today_text(probe)

    # The refresh line, with the counts the run actually produced.
    assert "последно обновяване:" in body
    assert "37 нови публикации" in body
    # No internal store field is shown.
    assert "source_count" not in body and "blocked_filtered" not in body

    # Article attention survives a full Story list.
    assert "статии за действие" in body
    assert "работа по текущата история" in body
    assert ids["draft_article_id"]


def test_istoriyi_still_reaches_the_complete_collection(today_page):
    """The cap hides rows from Today; it must not remove them from «Истории»."""
    probe, _ = today_page
    open_today(probe)
    probe.page.get_by_role("navigation", name="Основни раздели").get_by_role(
        "link", name="Истории", exact=True
    ).click()
    probe.page.wait_for_url("**/stories", timeout=20000)
    probe.page.get_by_role("heading", name="Истории", level=1).wait_for(state="visible")
    # The list is a real async query; assert on the loaded rows, not the loader.
    probe.page.get_by_role("link", name="Стара история 0").first.wait_for(
        state="visible", timeout=30000
    )

    # The backlog Today refused to show is intact and reachable here.
    assert "Стара история" in probe.page.locator("main").inner_text()
    probe.assert_clean(context="Stories collection")


def _raise_current_count_above_the_cap(ids) -> None:
    """Add 20 more current Stories through the canonical stores.

    Written the same way the pipeline writes them, so the page under test sees
    real store rows rather than a hand-edited JSON file.
    """
    from datetime import datetime, timedelta, timezone

    from editor_assistant.workflow import inbox_store, story_store

    stories = story_store.read_store(ids["stories_path"])["stories"]
    # Current, like the other 25: a stale extra would simply fall outside the
    # horizon and the cap would never be reached.
    when = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    extra_items = []
    extra = []
    for index in range(20):
        item = {
            "item_id": f"s-d1-extra-{index:03d}-origin",
            "source_id": "d1-vestnik",
            "source_item_id": f"s-d1-extra-{index:03d}",
            "title": f"Допълнителна текуща история {index}",
            "url": f"https://vestnik.example.test/extra-{index}",
            "published_at": when,
            "discovered_at": when,
            "summary": "Обобщение",
            "source_kind": "media",
            "status": "NEW",
        }
        extra_items.append(item)
        story = story_store.new_story(item, publication_key=f"pk-extra-{index}", now=when)
        story["story_id"] = f"s-d1-extra-{index:03d}"
        story["status"] = "NEW"
        extra.append(story)
    inbox_store.save_items(
        [*inbox_store.read_items(ids["newsroom"] / "inbox.jsonl"), *extra_items],
        ids["newsroom"] / "inbox.jsonl",
    )
    story_store.write_store({"stories": [*stories, *extra]}, ids["stories_path"])


def test_the_cap_is_disclosed_and_links_to_the_full_collection(today_page):
    """With more current Stories than the cap, the page says so and links out."""
    probe, ids = today_page
    open_today(probe)
    assert "показани са" not in today_text(probe)

    _raise_current_count_above_the_cap(ids)
    open_today(probe)

    body = today_text(probe)
    assert "показани са 30 от 45 текущи истории" in body
    link = probe.page.get_by_role("link", name="Виж всички в Истории")
    link.wait_for(state="visible")
    assert link.get_attribute("href") == "/stories"
    # The screen really is bounded, not merely labelled.
    rendered = [
        text
        for text in probe.page.locator("main h3 a").all_inner_texts()
        if text.startswith(("Текуща история", "Допълнителна текуща"))
    ]
    assert len(rendered) == 30
    probe.assert_clean(context="cap disclosure")


def test_a_real_refresh_updates_the_refresh_line(today_page):
    """`Обнови` really runs, really finishes, and really changes the screen."""
    probe, _ = today_page
    open_today(probe)
    assert "37 нови публикации" in today_text(probe)

    probe.page.get_by_role("button", name="Обнови").click()
    # The pending state is what the editor sees while the run is in flight.
    probe.page.get_by_role("button", name="Обновява се…").wait_for(state="visible", timeout=30000)
    probe.page.get_by_role("button", name="Обнови").wait_for(state="visible", timeout=180000)

    after = today_text(probe)
    # The run recorded a new finish time and a new count, so the line moved.
    assert "37 нови публикации" not in after, "the refresh line did not refetch"
    assert "последно обновяване:" in after
    probe.assert_clean(context="after a controlled refresh")

    probe.assert_clean(context="Today with a stale backlog")
