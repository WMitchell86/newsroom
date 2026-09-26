"""D2A §13-§14: real «Проучи още» and real «Обнови» through the browser UI.

Only the genuinely external edges are substituted (the search provider/page
opener and the collector's byte fetcher). Everything the editor can observe is
real: the operation registry and its token, the real worker threads, the real
research store and its projection, the real collector/ingestion/grouping
pipeline and the real Today projection.
"""

from __future__ import annotations

import time

from .helpers import assert_spa_shell, path_of

#: Internal pipeline vocabulary that must never surface on an editor screen.
#: Only genuinely internal terms belong here: the frozen editor vocabulary
#: (including «Проучване» and «Проучи още») is correct product language.
INTERNAL_WORDS = (
    "research_runs",
    "SEARCH_COMPLETE",
    "Идея",
    "Доказателства",
    "Case",
    "Етап",
    "draft_id",
)


def open_story(probe, story_id: str) -> None:
    probe.page.goto(f"{probe.base_url}/stories/{story_id}", wait_until="load")
    probe.page.get_by_role("navigation", name="Основни раздели").first.wait_for(
        state="visible"
    )
    probe.page.locator("main").wait_for(state="visible")


def open_today(probe) -> None:
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")


def _wait_until(probe, predicate, *, timeout: float = 90.0, interval: float = 0.25):
    """Poll the canonical API, not the DOM, so we assert the server's answer."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


# --------------------------------------------------------------------------
# §13 Story research
# --------------------------------------------------------------------------


def test_research_more_completes_and_refreshes_the_same_story(page, spa_runtime):
    """Проучи още -> Проучва се… -> the operation completes -> the Story refreshes."""
    probe = page
    story_id = spa_runtime["story_id"]
    open_story(probe, story_id)

    before = probe.page.request.get(f"{probe.base_url}/api/v1/stories/{story_id}").json()["data"]
    rounds_before = before["missingInformation"]["items"]

    button = probe.page.get_by_role("button", name="Проучи още")
    button.wait_for(state="visible")
    button.click()

    # The pending wording is asserted while the real operation is still running.
    pending = probe.page.get_by_role("button", name="Проучва се…")
    pending.wait_for(state="visible", timeout=10000)

    # The research rounds advance only when the real operation really finished.
    def rounds_advanced():
        detail = probe.page.request.get(f"{probe.base_url}/api/v1/stories/{story_id}").json()[
            "data"
        ]
        return detail if detail["missingInformation"] != rounds_before else None

    settled = _wait_until(probe, rounds_advanced)
    assert settled is not None, "the research operation never changed the canonical Story"

    # The same Story, refreshed in place: no navigation, no Research page.
    assert path_of(probe.page) == f"/stories/{story_id}"
    body = probe.page.locator("main").inner_text()
    for word in INTERNAL_WORDS:
        assert word not in body, f"internal vocabulary {word!r} leaked into the Story view"
    assert "/research" not in body
    assert_spa_shell(probe.page)
    probe.assert_clean(context="research more")


def test_research_never_navigates_to_a_job_or_research_page(page, spa_runtime):
    """The editor stays on the Story; there is no Research surface to leak into."""
    probe = page
    story_id = spa_runtime["story_id"]
    open_story(probe, story_id)
    probe.page.get_by_role("button", name="Проучи още").click()
    probe.page.wait_for_timeout(3000)
    assert path_of(probe.page) == f"/stories/{story_id}"
    probe.assert_clean(context="research navigation")


# --------------------------------------------------------------------------
# §14 «Обнови»
# --------------------------------------------------------------------------


def test_today_refresh_runs_the_real_pipeline_and_updates_today(page, spa_runtime):
    """Обнови -> Обновява се… -> Today is refreshed, with no pipeline stages shown."""
    probe = page
    open_today(probe)

    refresh = probe.page.get_by_role("button", name="Обнови")
    refresh.wait_for(state="visible")
    refresh.click()

    # The pending wording and the preserved content are asserted while running.
    probe.page.get_by_role("button", name="Обновява се…").wait_for(state="visible", timeout=10000)
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")

    # The real collection run finishes: the button returns to its idle wording.
    probe.page.get_by_role("button", name="Обнови").wait_for(state="visible", timeout=120000)

    body = probe.page.locator("main").inner_text()
    for word in ("Етап", "Източник:", "collector", "RSS", "health"):
        assert word not in body, f"internal pipeline stage {word!r} appeared on Today"
    assert_spa_shell(probe.page)
    probe.assert_clean(context="Today refresh")
