"""D2A §10-§12: Stories list, Story Workspace and Story interaction smoke.

Topology/browser proof: real React, real API, real canonical stores. Backend
semantics already covered by the Python and Vitest suites are not re-litigated
here; what is proven is that the editor can reach them through a real browser
against the Python-served production bundle.
"""

from __future__ import annotations

from .helpers import (
    STORY_FILTERS,
    assert_spa_shell,
    path_of,
)

#: Row-level management vocabulary that must never appear in the Stories list.
MANAGEMENT_ROW_WORDS = ("Игнорирай", "Спри следването", "Следи", "Прегледай", "Започни статия")


def story_actions(page):
    """The Story action cluster, located by its own accessible name."""
    return page.locator("[aria-label='Действия за историята']")


def open_story(probe, story_id: str) -> None:
    probe.page.goto(f"{probe.base_url}/stories/{story_id}", wait_until="load")
    probe.page.get_by_role("navigation", name="Основни раздели").first.wait_for(
        state="visible"
    )
    probe.page.locator("main").wait_for(state="visible")


# --------------------------------------------------------------------------
# §10 Stories list
# --------------------------------------------------------------------------


def test_stories_list_renders_search_and_four_frozen_filters(page):
    """`/stories`: search box, exactly the four frozen filters, URL query state."""
    probe = page
    probe.page.goto(f"{probe.base_url}/stories", wait_until="load")
    probe.page.get_by_role("heading", name="Истории", level=1).wait_for(state="visible")
    assert_spa_shell(probe.page)

    search = probe.page.get_by_role("searchbox", name="Търсене в истории")
    search.wait_for(state="visible")

    filters = probe.page.get_by_role("navigation", name="Филтри за истории")
    labels = [
        filters.get_by_role("link").nth(index).inner_text().strip()
        for index in range(filters.get_by_role("link").count())
    ]
    assert tuple(labels) == STORY_FILTERS, f"unexpected Story filters: {labels}"

    # Every filter is a real link, so the state is in the URL.
    for label, value in zip(STORY_FILTERS, ("all", "followed", "developments", "ignored")):
        filters.get_by_role("link", name=label, exact=True).click()
        probe.page.wait_for_load_state("load")
        if value == "all":
            assert "filter=" not in probe.page.url
        else:
            assert f"filter={value}" in probe.page.url
    probe.assert_clean(context="Stories list filters")


def test_story_search_filters_the_list_and_keeps_query_in_url(page, spa_runtime):
    """Text search narrows the visible list and is reflected in the URL."""
    probe = page
    probe.page.goto(f"{probe.base_url}/stories", wait_until="load")
    probe.page.get_by_role("heading", name="Истории", level=1).wait_for(state="visible")

    search = probe.page.get_by_role("searchbox", name="Търсене в истории")
    search.fill("Ремонтът")
    search.press("Enter")
    probe.page.wait_for_url("**/stories?q=*")
    assert "q=" in probe.page.url

    # The matching Story is present and the unrelated ones are filtered out.
    probe.page.get_by_role("link", name="Ремонтът започва през октомври").first.wait_for(
        state="visible"
    )
    assert probe.page.get_by_role("link", name="Нова история за преглед").count() == 0, (
        "search did not narrow the list"
    )
    assert (
        probe.page.get_by_role("link", name="Приет е бюджетът за парка в центъра").count() == 0
    ), "search did not narrow the list"
    probe.assert_clean(context="Stories list search")


def test_stories_list_has_no_row_level_management_controls(page, spa_runtime):
    """The list is a reading surface: management stays in the workspace."""
    probe = page
    probe.page.goto(f"{probe.base_url}/stories", wait_until="load")
    probe.page.get_by_role("heading", name="Истории", level=1).wait_for(state="visible")
    body = probe.page.locator("main").inner_text()
    for word in MANAGEMENT_ROW_WORDS:
        assert word not in body, (
            f"row-level management control {word!r} appeared in the Stories list"
        )


def test_story_title_navigates_to_the_workspace(page, spa_runtime):
    """Clicking a title opens the Story Workspace through React Router."""
    probe = page
    probe.page.goto(f"{probe.base_url}/stories", wait_until="load")
    probe.page.get_by_role("heading", name="Истории", level=1).wait_for(state="visible")
    probe.page.get_by_role("link", name="Ремонтът започва през октомври").first.click()
    probe.page.wait_for_url(f"**/stories/{spa_runtime['story_id']}")
    assert path_of(probe.page) == f"/stories/{spa_runtime['story_id']}"
    assert_spa_shell(probe.page)
    probe.assert_clean(context="Stories list -> workspace")


# --------------------------------------------------------------------------
# §11 Story Workspace rendering
# --------------------------------------------------------------------------


def test_story_workspace_renders_every_frozen_area(page, spa_runtime):
    """Title, context, development, facts, missing info, articles, disclosures."""
    probe = page
    open_story(probe, spa_runtime["story_id"])
    main = probe.page.locator("main")

    # Title and current context.
    probe.page.get_by_role("heading", name="Ремонтът започва през октомври", level=1).wait_for(
        state="visible"
    )
    main.get_by_text("Общинският съвет одобри 1,2 милиона лева").first.wait_for(state="visible")

    # New development, facts/sources and missing information.
    main.get_by_role("heading", name="Ново развитие", level=2).wait_for(state="visible")
    main.get_by_role("heading", name="Факти и източници", level=2).first.wait_for(state="visible")
    main.get_by_role("heading", name="Какво липсва", level=2).first.wait_for(state="visible")
    main.get_by_text("Кога точно започва ремонтът?").first.wait_for(state="visible")

    # Related Articles.
    main.get_by_role("heading", name="Статии по тази история", level=2).wait_for(state="visible")
    main.get_by_role("link", name="Свързана статия за навигация").first.wait_for(state="visible")
    assert_spa_shell(probe.page)
    probe.assert_clean(context="Story Workspace rendering")


def test_story_disclosures_open_and_close_in_the_browser(page, spa_runtime):
    """Collapsible Publications and chronology are operable disclosure controls."""
    probe = page
    open_story(probe, spa_runtime["story_id"])

    for label in ("Публикации", "Хронология"):
        button = probe.page.get_by_role("button", name=label)
        button.wait_for(state="visible")
        assert button.get_attribute("aria-expanded") == "false", f"{label} started expanded"
        button.click()
        assert button.get_attribute("aria-expanded") == "true", f"{label} did not expand"
        button.click()
        assert button.get_attribute("aria-expanded") == "false", f"{label} did not collapse"
    probe.assert_clean(context="Story disclosures")


def test_story_actions_match_the_backend_available_actions(page, spa_runtime):
    """Only the actions the projection offers are rendered (§11).

    The buttons live in more than one cluster by design: the Story actions sit
    together, while `Проучи още` belongs to the Missing Information section. The
    contract asserted here is page-level - nothing is offered that the projection
    does not, and nothing offered is missing.
    """
    probe = page
    open_story(probe, spa_runtime["story_id"])
    detail = probe.page.request.get(
        f"{probe.base_url}/api/v1/stories/{spa_runtime['story_id']}"
    ).json()["data"]
    offered = set(detail["availableActions"])
    for label, action in (
        ("Прегледай", "REVIEW"),
        ("Следи", "FOLLOW"),
        ("Спри следването", "UNFOLLOW"),
        ("Игнорирай", "IGNORE"),
        ("Проучи още", "RESEARCH_MORE"),
        ("Започни статия", "START_ARTICLE"),
    ):
        visible = probe.page.get_by_role("button", name=label).count() > 0
        assert visible == (action in offered), (
            f"«{label}» visibility {visible} does not match "
            f"{'offered' if action in offered else 'not offered'} by the projection"
        )


# --------------------------------------------------------------------------
# §12 Story interaction smoke
# --------------------------------------------------------------------------


def test_story_follow_and_unfollow_change_canonical_state(page, spa_runtime):
    """`Следи` then `Спри следването`, with the canonical projection updating."""
    probe = page
    story_id = spa_runtime["story_new_id"]
    open_story(probe, story_id)
    actions = story_actions(probe.page)

    # The fixture already followed this Story, so start by unfollowing it.
    actions.get_by_role("button", name="Спри следването").click()
    probe.page.get_by_role("button", name="Следи").wait_for(state="visible")
    assert probe.page.get_by_text("Следена: не").first.is_visible()

    actions.get_by_role("button", name="Следи").click()
    probe.page.get_by_role("button", name="Спри следването").wait_for(state="visible")
    assert probe.page.get_by_text("Следена: да").first.is_visible()
    probe.assert_clean(context="follow/unfollow")


def test_story_review_marks_the_development_as_seen(page, spa_runtime):
    """`Прегледай` on an unreviewed Story updates the canonical projection."""
    probe = page
    story_id = spa_runtime["story_new_id"]
    open_story(probe, story_id)
    probe.page.get_by_role("button", name="Прегледай").click()
    probe.page.get_by_text("Прегледана: да").first.wait_for(state="visible")
    probe.assert_clean(context="review")


def test_story_ignore_moves_it_out_of_the_active_surfaces(page, spa_runtime):
    """`Игнорирай` and the canonical ignored state, in the browser."""
    probe = page
    story_id = spa_runtime["story_ignored_id"]
    open_story(probe, story_id)
    body = probe.page.locator("main").inner_text()
    assert "Игнорирана" in body, "the ignored Story is not marked as such"

    # An ignored Story offers neither ignoring again nor starting an Article.
    actions = story_actions(probe.page)
    assert actions.get_by_role("button", name="Игнорирай").count() == 0
    assert actions.get_by_role("button", name="Започни статия").count() == 0
    probe.assert_clean(context="ignored Story")
