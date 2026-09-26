"""D2A §7-§9, §24-§28: SPA boot, navigation, deep links, refresh, back/forward.

Everything here runs against the real Python server in the **default** frontend
mode (no ``WB_EDITOR_FRONTEND`` set at all, which is what a normal start does
since the D2B cutover), serving a real ``npm run build`` output. There is no Vite
dev server, no Vite preview and no request interception: the browser talks to the
production topology only.
"""

from __future__ import annotations

from .helpers import (
    active_area,
    assert_primary_areas,
    assert_spa_shell,
    nav_link,
    open_article,
    path_of,
    state_marker,
)

# --------------------------------------------------------------------------
# §7 SPA boot
# --------------------------------------------------------------------------


def test_spa_boot_renders_today_with_exactly_five_areas(page):
    """GET / in Chromium: React mounts, `Днес` is visible, no legacy rail."""
    probe = page
    probe.page.goto(f"{probe.base_url}/", wait_until="load")

    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible", timeout=15000)

    assert_spa_shell(probe.page)
    assert_primary_areas(probe.page)
    assert active_area(probe.page) == "Днес"
    # The root really is the SPA document, not a server-rendered Workbench page.
    assert probe.page.locator("#root").count() == 1
    probe.assert_clean(context="SPA boot on /")


def test_spa_boot_makes_no_external_request(page):
    """Fonts and scripts are self-hosted: no third-party origin is contacted."""
    probe = page
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")
    assert probe.external_requests == [], (
        f"the SPA contacted a third-party origin: {sorted(set(probe.external_requests))}"
    )


# --------------------------------------------------------------------------
# §9 primary navigation, through real clicks
# --------------------------------------------------------------------------


def test_primary_navigation_uses_client_side_routing(page, spa_runtime):
    """Днес -> Истории -> Статии -> Архив -> Настройки, all without a reload."""
    probe = page
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")

    # A marker on `window` survives client-side navigation but dies on a full
    # document load. Its survival is the proof that React Router owned the move.
    probe.page.evaluate("() => { window.__d2aSpaSession = true; }")

    expected = [
        ("Истории", "/stories", "Истории"),
        ("Статии", "/articles", "Статии"),
        ("Архив", "/archive", "Архив"),
        ("Настройки", "/settings", "Настройки"),
        ("Днес", "/", "Днес"),
    ]
    for label, path, heading in expected:
        nav_link(probe.page, label).click()
        probe.page.get_by_role("heading", name=heading, level=1).wait_for(state="visible")
        assert path_of(probe.page) == path, f"«{label}» did not route to {path}"
        assert active_area(probe.page) == label, f"«{label}» is not the active area"
        assert_spa_shell(probe.page)
        assert probe.page.evaluate("() => window.__d2aSpaSession === true"), (
            f"navigating to «{label}» caused a full document reload; "
            "React Router did not own the transition"
        )

    # The five frozen areas are still exactly five after all that navigation.
    assert_primary_areas(probe.page)
    probe.assert_clean(context="primary navigation")


# --------------------------------------------------------------------------
# §24 / §27 deep linking, in a context with no prior session state
# --------------------------------------------------------------------------


def test_deep_link_loads_without_first_visiting_root(fresh_page, spa_runtime):
    """A nested SPA URL opens directly in a brand-new context."""
    probe = fresh_page
    article_id = spa_runtime["deep_link_article_id"]
    path = f"/articles/{article_id}"
    assert probe.page.url == "about:blank", "the context was not fresh"
    open_article(probe, article_id)
    assert state_marker(probe.page) == "подготовка"
    assert path_of(probe.page) == path
    assert_spa_shell(probe.page)
    probe.assert_clean(context=f"deep link {path}")


def test_fresh_pasted_story_url_opens_directly(fresh_page, spa_runtime):
    """§27: a copied Story URL pasted into a fresh context opens directly."""
    probe = fresh_page
    path = f"/stories/{spa_runtime['story_id']}"
    probe.page.goto(f"{probe.base_url}{path}", wait_until="load")
    probe.page.get_by_role("navigation", name="Основни раздели").first.wait_for(
        state="visible"
    )
    assert path_of(probe.page) == path
    assert_spa_shell(probe.page)
    probe.assert_clean(context="pasted story deep link")


# --------------------------------------------------------------------------
# §25 refresh on nested routes
# --------------------------------------------------------------------------


def test_browser_refresh_on_nested_routes(page, spa_runtime):
    """Python -> index.html, React -> API, resource renders. No 404, no loop."""
    probe = page
    cases = [
        f"/stories/{spa_runtime['story_id']}",
        f"/articles/{spa_runtime['deep_link_article_id']}",
        f"/archive/{spa_runtime['archived_article_id']}",
    ]
    for path in cases:
        probe.page.goto(f"{probe.base_url}{path}", wait_until="load")
        probe.page.get_by_role("navigation", name="Основни раздели").first.wait_for(
        state="visible"
    )
        probe.page.locator("main").wait_for(state="visible")

        probe.reset()
        # A real browser reload, not a client-side re-render.
        probe.page.reload(wait_until="load")
        probe.page.get_by_role("navigation", name="Основни раздели").first.wait_for(
        state="visible"
    )
        probe.page.locator("main").wait_for(state="visible")

        assert_spa_shell(probe.page)
        assert path_of(probe.page) == path
        assert probe.page.locator("#root").count() == 1, "refresh did not return the SPA"
        probe.assert_clean(context=f"refresh on {path}")


# --------------------------------------------------------------------------
# §26 back / forward
# --------------------------------------------------------------------------


def test_back_and_forward_walk_the_spa_history(fresh_page, spa_runtime):
    """Днес -> Story -> related Article -> Back -> Back -> Stories -> Forward."""
    probe = fresh_page
    story_id = spa_runtime["story_id"]

    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")

    nav_link(probe.page, "Истории").click()
    probe.page.get_by_role("heading", name="Истории", level=1).wait_for(state="visible")
    probe.page.wait_for_url("**/stories")
    assert path_of(probe.page) == "/stories"

    # Into the Story Workspace, by clicking its title.
    probe.page.get_by_role("link", name="Ремонтът започва през октомври").first.click()
    probe.page.wait_for_url(f"**/stories/{story_id}")
    assert path_of(probe.page) == f"/stories/{story_id}"
    assert_spa_shell(probe.page)

    # Into a related Article, through the workspace's own link.
    probe.page.get_by_role("link", name="Свързана статия за навигация").first.click()
    probe.page.wait_for_url("**/articles/**")
    article_path = path_of(probe.page)
    assert_spa_shell(probe.page)

    probe.reset()
    probe.page.go_back()
    probe.page.wait_for_url(f"**/stories/{story_id}")
    assert path_of(probe.page) == f"/stories/{story_id}"
    assert_spa_shell(probe.page)

    probe.page.go_back()
    probe.page.wait_for_url("**/stories")
    assert path_of(probe.page) == "/stories"
    assert_spa_shell(probe.page)

    probe.page.go_forward()
    probe.page.wait_for_url(f"**/stories/{story_id}")
    assert path_of(probe.page) == f"/stories/{story_id}"
    assert_spa_shell(probe.page)
    assert probe.page.locator("#root").count() == 1, "forward broke the AppShell"
    probe.assert_clean(context="back/forward")
    assert article_path.startswith("/articles/")


# --------------------------------------------------------------------------
# §28 unknown routes
# --------------------------------------------------------------------------


def test_unsupported_route_is_a_real_server_404(page):
    """An arbitrary unsupported URL must not be answered with the SPA."""
    probe = page
    response = probe.page.goto(f"{probe.base_url}/not-a-real-route", wait_until="load")
    assert response is not None, "the server answered nothing at all"
    assert response.status == 404, (
        f"an unknown route answered {response.status}; it must be a real 404, never 200 index.html"
    )
    assert probe.page.locator("#root").count() == 0, "the SPA was served for an unknown route"


def test_structural_route_with_unknown_id_loads_the_spa(fresh_page):
    """An approved shape with an unknown id: SPA loads, React shows its own state."""
    probe = fresh_page
    response = probe.page.goto(f"{probe.base_url}/stories/s-does-not-exist", wait_until="load")
    assert response is not None and response.status == 200
    probe.page.get_by_role("navigation", name="Основни раздели").first.wait_for(
        state="visible"
    )
    # The API answers 404 and the workspace renders its own not-found state.
    probe.page.get_by_role("heading", name="Съдържанието не можа да се зареди").wait_for(
        state="visible"
    )
    assert_spa_shell(probe.page)
    probe.assert_clean(context="unknown story id", allow_api_404=True)


def test_api_and_health_are_never_swallowed_by_the_spa(page):
    """Route ownership rehearsal: API stays JSON, health stays backend (§34)."""
    probe = page
    api = probe.page.request.get(f"{probe.base_url}/api/v1/today")
    assert api.status == 200
    assert api.headers.get("content-type", "").startswith("application/json")
    assert '<div id="root">' not in api.text()

    health = probe.page.request.get(f"{probe.base_url}/healthz")
    assert health.status == 200 and health.text().strip() == "OK"
