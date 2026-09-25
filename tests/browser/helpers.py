"""Shared helpers for the D2A browser suite.

Locators are written the way an editor would find the control: by its visible
Bulgarian label and its role. No CSS-module class names and no internal ids leak
into the assertions, so a restyle cannot silently break the proof.
"""

from __future__ import annotations

PRIMARY_AREAS = ("Днес", "Истории", "Статии", "Архив", "Настройки")
STORY_FILTERS = ("Всички", "Следени", "Нови развития", "Игнорирани")
#: Hrefs that exist only in the legacy server-rendered Workbench chrome. If one of
#: them is present on a page, that page was rendered by the backend, not by React.
LEGACY_ONLY_HREFS = ("/inbox", "/models", "/sources", "/cases", "/intake", "/static/style.css")


def path_of(page) -> str:
    """The current path, without origin or query."""
    from urllib.parse import urlsplit

    return urlsplit(page.url).path


def goto(probe, path: str, *, wait_for: str | None = None) -> None:
    """Navigate and wait for the SPA shell, then optionally for a real element."""
    probe.page.goto(f"{probe.base_url}{path}", wait_until="load")
    probe.page.locator("header nav").first.wait_for(state="visible")
    if wait_for:
        probe.page.get_by_text(wait_for, exact=False).first.wait_for(state="visible")


def state_marker(page) -> str:
    """The Article state word shown by the workspace status marker.

    Compared case-insensitively: the frozen design renders the marker in caps via
    CSS, and `inner_text` reports the transformed text.
    """
    marker = page.locator("[class*='statusMarker']").first
    return marker.inner_text().strip().casefold()


def wait_for_state(page, expected: str, *, timeout: int = 120000) -> None:
    """Wait until the canonical state marker really reads `expected`.

    The marker element is already on the page before the transition, so waiting for
    it to be *visible* would pass immediately. This compares the element's rendered
    text, case-insensitively, because the frozen design renders the marker in caps.
    """
    page.wait_for_function(
        "expected => {"
        "  const el = document.querySelector(\"[class*='statusMarker']\");"
        "  return !!el"
        "    && el.innerText.trim().toLowerCase() === expected"
        "    && el.getClientRects().length > 0;"
        "}",
        arg=expected.casefold(),
        timeout=timeout,
    )


def open_article(probe, article_id: str) -> None:
    """Open an Article workspace and wait until its canonical state is rendered."""
    probe.page.goto(f"{probe.base_url}/articles/{article_id}", wait_until="load")
    probe.page.locator("header nav").first.wait_for(state="visible")
    probe.page.locator("main").wait_for(state="visible")


def primary_nav(page):
    return page.get_by_role("navigation", name="Основни раздели")


def nav_link(page, label: str):
    return primary_nav(page).get_by_role("link", name=label, exact=True)


def assert_primary_areas(page) -> None:
    """Exactly the five frozen areas, and no sixth one."""
    links = primary_nav(page).get_by_role("link")
    labels = [links.nth(index).inner_text().strip() for index in range(links.count())]
    assert tuple(labels) == PRIMARY_AREAS, f"unexpected primary navigation: {labels}"


def assert_spa_shell(page) -> None:
    """React mounted inside the AppShell, with no legacy server-rendered chrome."""
    body = page.locator("body").inner_text()
    assert body.strip(), "blank screen: the SPA rendered nothing"
    assert page.locator("header nav").count() >= 1, "AppShell navigation is missing"
    # A server-rendered Workbench page always links its own operator surfaces and
    # stylesheet. Their absence is what proves React owns this route.
    hrefs = page.evaluate(
        "() => [...document.querySelectorAll('[href]')].map(el => el.getAttribute('href'))"
    )
    leaked = sorted({href for href in hrefs if href in LEGACY_ONLY_HREFS})
    assert not leaked, (
        f"legacy Workbench navigation {leaked} is present: this page was rendered "
        "by the server-rendered Workbench, not by the React SPA"
    )


def active_area(page) -> str:
    """The label of the currently active primary navigation item.

    Read from the rendered presentation - the accent-coloured underline bar that
    only the active item draws - rather than from a CSS-module class name, so the
    assertion describes what the editor actually sees.
    """
    labels = page.evaluate(
        """() => {
            const nav = document.querySelector('header nav');
            if (!nav) return [];
            return [...nav.querySelectorAll('a')].map((a) => {
                const after = getComputedStyle(a, '::after');
                return {
                    label: a.textContent.trim(),
                    thickness: parseFloat(after.borderBottomWidth)
                        || parseFloat(after.height) || 0,
                };
            });
        }"""
    )
    marked = [item["label"] for item in labels if item["thickness"] >= 2]
    assert len(marked) <= 1, f"more than one primary area is marked active: {marked}"
    return marked[0] if marked else ""
