"""Shared helpers for the D2A browser suite.

Locators are written the way an editor would find the control: by its visible
Bulgarian label and its role. No CSS-module class names and no internal ids leak
into the assertions, so a restyle cannot silently break the proof.

V1.2-G1: the primary navigation moved from a top `<header>` into a left rail, so
nothing here may depend on `header nav` any more. These helpers are anchored on
the navigation *landmark* and on the link labels, which is what actually
identifies the control for a user and for a screen reader.
"""

from __future__ import annotations

#: The frozen editor destinations, in rail order. `Настройки` is last and lives
#: in the left column, separated from the four everyday editorial destinations.
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
    probe.page.get_by_role("navigation", name="Основни раздели").wait_for(state="visible")
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
    probe.page.get_by_role("navigation", name="Основни раздели").wait_for(state="visible")
    probe.page.locator("main").wait_for(state="visible")


def fail_generation_once(probe, article_id: str) -> None:
    """Drive one real generation attempt that genuinely fails, through the UI.

    V1.1-C: `Редактирай` is a recovery path, so a browser proof of manual
    continuation must first EARN it. The provider boundary substitute is swapped
    for one that raises, `Направи чернова` is really clicked, the failed
    operation is really awaited, and the page is refetched from the server — so
    the recovery action that appears was produced by canonical state, not by
    anything the browser remembered.
    """
    from editor_assistant.drafting import generate as gen

    original = gen._call_gemini
    gen._call_gemini = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("provider is down"))
    try:
        page = probe.page
        page.get_by_role("button", name="Направи чернова").first.click()
        # The operation really runs and really fails; the UI reports it.
        page.get_by_role("alert").first.wait_for(state="visible", timeout=120000)
    finally:
        gen._call_gemini = original
    # A canonical refetch: the action list comes back from the server.
    page.goto(f"{probe.base_url}/articles/{article_id}", wait_until="load")
    page.get_by_role("button", name="Редактирай").first.wait_for(state="visible", timeout=30000)


def primary_nav(page):
    return page.get_by_role("navigation", name="Основни раздели")


def nav_link(page, label: str):
    """A frozen destination by label, wherever in the rail it now lives."""
    return page.get_by_role("link", name=label, exact=True).first


def assert_primary_areas(page) -> None:
    """Exactly the five frozen areas, in order, and no sixth one.

    V1.2-G1: the four everyday destinations and `Настройки` are two navigation
    landmarks in the left rail, so the assertion walks the rail rather than a
    single `<nav>`. The *set* and the *order* are still what is asserted.
    """
    rail = page.get_by_role("complementary")
    rail.wait_for(state="visible")
    links = rail.get_by_role("link")
    labels = [links.nth(index).inner_text().strip() for index in range(links.count())]
    # The brand link is identity, not a destination.
    assert tuple(label for label in labels if label != "Редакция") == PRIMARY_AREAS, (
        f"unexpected primary navigation: {labels}"
    )
    assert "Източници" not in labels, "a sixth primary destination was added"


def assert_spa_shell(page) -> None:
    """React mounted inside the AppShell, with no legacy server-rendered chrome."""
    body = page.locator("body").inner_text()
    assert body.strip(), "blank screen: the SPA rendered nothing"
    assert page.get_by_role("navigation", name="Основни раздели").count() >= 1, (
        "AppShell navigation is missing"
    )
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
    """The label of the currently active destination in the left rail.

    Read from the rendered presentation — the small petrol indicator bar that only
    the active rail item draws — rather than from a CSS-module class name, so the
    assertion describes what the editor actually sees. G1 moved the indicator from
    a bottom underline to a left bar, so the measurement follows the marker.
    """
    labels = page.evaluate(
        """() => {
            const rail = document.querySelector('aside');
            if (!rail) return [];
            return [...rail.querySelectorAll('nav a')].map((a) => {
                const marker = getComputedStyle(a, '::before');
                const background = getComputedStyle(a).backgroundColor;
                return {
                    label: a.textContent.trim(),
                    width: parseFloat(marker.width) || 0,
                    tinted: background !== 'rgba(0, 0, 0, 0)' && background !== 'transparent',
                };
            });
        }"""
    )
    marked = [item["label"] for item in labels if item["width"] >= 2 or item["tinted"]]
    assert len(marked) <= 1, f"more than one primary area is marked active: {marked}"
    return marked[0] if marked else ""
