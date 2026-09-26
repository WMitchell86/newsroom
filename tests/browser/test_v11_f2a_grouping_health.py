"""V1.1-F2A §26: degraded Story grouping, proven in a real browser.

Everything runs against the real production topology — a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` — against an isolated store root. Only the outbound provider edges
are substituted.

Two things are proven that a unit test cannot:

**A. a degraded grouping run is visible.** F1 established that a day in which a
third of the corpus is grouped conservatively looked exactly like a day where
nothing interesting happened. Here the warning must actually render, in editor
language, while every Story stays reachable and Quick Draft keeps working.

**B. a healthy run clears it.** The warning must disappear from canonical
latest-run state after a refresh, with no browser reload — otherwise the signal
is noise the editor learns to ignore.
"""

from __future__ import annotations

import json
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

DEGRADED_GROUPING = {
    "status": "budget_exhausted",
    "lastSuccessfulSemanticClassificationAt": "2026-09-26T07:10:00Z",
    "semanticRequired": 182,
    "semanticAnswered": 79,
    "semanticDegraded": 103,
    "semanticDegradedBudgetExhausted": 103,
    "semanticDegradedUnavailable": 0,
}

HEALTHY_GROUPING = {
    "status": "healthy",
    "lastSuccessfulSemanticClassificationAt": "2026-09-26T09:20:00Z",
    "semanticRequired": 182,
    "semanticAnswered": 182,
    "semanticDegraded": 0,
    "semanticDegradedBudgetExhausted": 0,
    "semanticDegradedUnavailable": 0,
}


@pytest.fixture
def grouped_page(browser, boundary_substitutes, tmp_path):
    if not (DIST / "index.html").exists():
        pytest.skip(f"production build missing: run `cd frontend && npm run build` ({DIST})")

    from editor_assistant.workflow import story_operations
    from editor_assistant.workflow.workbench import http

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
            "GEMINI_API_KEY": "f2a-substitute-not-a-real-key",
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


#: The grouping notice shares `role="status"` with the transient refresh status,
#: so it is addressed by its own class rather than by role alone.
GROUPING_NOTICE = "p[class*='groupingNotice']"


def _set_grouping(newsroom, grouping):
    path = newsroom / "last_run.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["grouping"] = grouping
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def test_degraded_grouping_is_visible_and_editor_safe(grouped_page):
    probe, fixture = grouped_page
    _set_grouping(fixture["newsroom"], DEGRADED_GROUPING)

    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible", timeout=20000)
    probe.page.locator("main").wait_for(state="visible")

    notice = probe.page.locator(GROUPING_NOTICE)
    notice.wait_for(state="visible", timeout=10000)
    # Editor language, and only editor language.
    rendered = notice.inner_text()
    assert "Лимитът за групиране е изчерпан" in rendered
    assert "103" in rendered
    body = probe.page.locator("main").inner_text()
    folded = body.casefold()
    for forbidden in ("gemini", "openrouter", "429", "role_hard_budget", "flash", "quota"):
        assert forbidden not in folded

    # The screen still works: the Story rows are listed and the row actions
    # survive. V1.2-G1 §8 replaced the separate `Нови истории` section heading with
    # the compact attention tabs over one list, so the assertion follows the rows.
    probe.page.locator("[data-story-row]").first.wait_for(state="visible", timeout=10000)
    assert probe.page.locator("main h3 a").count() > 0
    probe.assert_clean(context="Today with a degraded grouping run")


def test_healthy_grouping_is_silent(grouped_page):
    probe, fixture = grouped_page
    _set_grouping(fixture["newsroom"], HEALTHY_GROUPING)

    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible", timeout=20000)
    probe.page.locator("main").wait_for(state="visible")

    # Healthy state consumes no editor attention: no status chrome at all.
    assert probe.page.locator(GROUPING_NOTICE).count() == 0
    body = probe.page.locator("main").inner_text()
    assert "Лимитът за групиране" not in body
    assert "Групирането на истории е ограничено" not in body
    probe.assert_clean(context="Today with healthy grouping")


def test_a_run_without_grouping_health_shows_no_warning(grouped_page):
    """A run that predates F2A is unknown, not unhealthy."""
    probe, fixture = grouped_page
    path = fixture["newsroom"] / "last_run.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("grouping", None)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible", timeout=20000)
    probe.page.locator("main").wait_for(state="visible")

    assert probe.page.locator(GROUPING_NOTICE).count() == 0
    body = probe.page.locator("main").inner_text()
    assert "Лимитът за групиране" not in body
    assert "Групирането на истории е ограничено" not in body
    probe.assert_clean(context="Today with an unknown grouping state")


def test_a_later_healthy_run_clears_the_warning_after_refresh(grouped_page):
    """§26 B: recovery comes from canonical latest-run state, not a reload.

    The warning is first rendered from a degraded run. The store is then updated
    to a healthy run *behind* the already-loaded page, and a single «Обнови»
    click must make the notice disappear. If it required a browser reload the
    editor would be reading a stale signal during exactly the window where it
    matters.
    """
    probe, fixture = grouped_page
    _set_grouping(fixture["newsroom"], DEGRADED_GROUPING)

    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible", timeout=20000)
    probe.page.locator(GROUPING_NOTICE).wait_for(state="visible", timeout=10000)
    assert "Лимитът за групиране е изчерпан" in probe.page.locator(GROUPING_NOTICE).inner_text()

    # The next canonical run is healthy. The page is NOT reloaded.
    _set_grouping(fixture["newsroom"], HEALTHY_GROUPING)

    probe.page.get_by_role("button", name="Обнови").click()
    probe.page.locator(GROUPING_NOTICE).wait_for(state="detached", timeout=30000)

    assert probe.page.get_by_role("heading", name="Днес", level=1).is_visible()
    probe.page.locator("[data-story-row]").first.wait_for(state="visible", timeout=10000)
    probe.assert_clean(context="after a healthy refresh cleared the grouping warning")
