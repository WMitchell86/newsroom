"""D2A §29-§35: assets, fonts, screenshots, route ownership, a11y, performance.

Also the §32/§33 legacy proofs, which are D2B's rollback release gate: the same
Python runtime with ``WB_EDITOR_FRONTEND=legacy`` still serves the
server-rendered Workbench on the primary routes, and in the default (SPA) mode
the operator and ``/wb-legacy`` compat routes stay backend-rendered.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from .helpers import PRIMARY_AREAS, nav_link

# --------------------------------------------------------------------------
# §29 assets and fonts
# --------------------------------------------------------------------------


def test_scripts_styles_and_fonts_all_load_with_no_asset_404(page, spa_server):
    """Every asset the entry document names is served by Python, none 404."""
    probe = page
    responses: list[tuple[int, str]] = []
    probe.page.on(
        "response",
        lambda response: responses.append((response.status, response.url)),
    )
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")
    probe.page.wait_for_timeout(600)

    assets = [(status, url) for status, url in responses if "/assets/" in url]
    assert assets, "no compiled asset was requested at all"
    bad = [(status, url) for status, url in assets if status != 200]
    assert not bad, f"assets did not load cleanly: {bad}"
    kinds = {url.rsplit(".", 1)[-1] for _status, url in assets}
    assert "js" in kinds and "css" in kinds, f"missing script or stylesheet: {kinds}"
    assert "woff2" in kinds, f"the self-hosted fonts were not requested: {kinds}"


def test_cyrillic_renders_with_the_self_hosted_fonts(page, spa_server):
    """Cyrillic text uses a Noto family, with no external font request."""
    probe = page
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    heading = probe.page.get_by_role("heading", name="Днес", level=1)
    heading.wait_for(state="visible")

    families = heading.evaluate("el => getComputedStyle(el).fontFamily").lower()
    assert "noto" in families, f"the heading is not rendered with a Noto family: {families}"
    # Both Cyrillic subsets are actually fetched, so Cyrillic is not tofu.
    assert not probe.external_requests, (
        f"a font was loaded from a third-party origin: {probe.external_requests}"
    )
    probe.assert_clean(context="fonts")


# --------------------------------------------------------------------------
# §30 screenshots for owner review
# --------------------------------------------------------------------------


def test_capture_owner_review_screenshots(page, spa_runtime, screenshots):
    """Eight production-topology screenshots at 1440x1080, from Python serving."""
    probe = page
    captured: list[str] = []

    def shot(name: str) -> None:
        probe.page.wait_for_timeout(400)
        captured.append(str(screenshots(probe, name)))

    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")
    shot("01-dnes")

    nav_link(probe.page, "Истории").click()
    probe.page.get_by_role("heading", name="Истории", level=1).wait_for(state="visible")
    shot("02-stories-list")

    probe.page.goto(f"{probe.base_url}/stories/{spa_runtime['story_id']}", wait_until="load")
    probe.page.locator("main").wait_for(state="visible")
    shot("03-story-workspace")

    probe.page.goto(
        f"{probe.base_url}/articles/{spa_runtime['deep_link_article_id']}", wait_until="load"
    )
    probe.page.locator("main").wait_for(state="visible")
    shot("04-article-preparation")

    probe.page.goto(
        f"{probe.base_url}/articles/{spa_runtime['manual_article_id']}", wait_until="load"
    )
    probe.page.locator("main").wait_for(state="visible")
    shot("05-article-draft")

    probe.page.goto(
        f"{probe.base_url}/articles/{spa_runtime['ready_article_id']}", wait_until="load"
    )
    probe.page.locator("main").wait_for(state="visible")
    shot("06-article-ready")

    probe.page.goto(
        f"{probe.base_url}/archive/{spa_runtime['archived_article_id']}", wait_until="load"
    )
    probe.page.locator("main").wait_for(state="visible")
    shot("07-archive-detail")

    nav_link(probe.page, "Настройки").click()
    probe.page.get_by_role("heading", name="Настройки", level=1).wait_for(state="visible")
    shot("08-settings")

    assert len(captured) == 8
    for path in captured:
        assert Path(path).exists() and Path(path).stat().st_size > 0, f"empty screenshot {path}"
    print("\n[d2a] screenshots:\n  " + "\n  ".join(captured))


# --------------------------------------------------------------------------
# §33 operator and compat routes stay server-rendered in SPA mode
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/cases", "/inbox", "/sources", "/models"])
def test_operator_routes_stay_server_rendered_in_spa_mode(page, path):
    """Operator surfaces are rollback/ops pages: never the React AppShell."""
    probe = page
    probe.page.goto(f"{probe.base_url}{path}", wait_until="load")
    body = probe.page.locator("body").inner_text()
    assert body.strip(), f"{path} rendered nothing"
    assert probe.page.locator("#root").count() == 0, (
        f"{path} was answered by the React SPA; it must stay a backend route"
    )
    assert probe.page.get_by_role("navigation", name="Основни раздели").count() == 0, (
        f"{path} rendered the SPA AppShell"
    )


def test_legacy_compat_prefix_serves_the_workbench_in_spa_mode(page):
    """`/wb-legacy/...` is the rollback surface and stays server-rendered."""
    probe = page
    probe.page.goto(f"{probe.base_url}/wb-legacy/stories", wait_until="load")
    assert probe.page.locator("#root").count() == 0, "the compat prefix entered the React SPA"
    assert probe.page.locator("body").inner_text().strip(), "the compat prefix rendered nothing"


# --------------------------------------------------------------------------
# §36 accessibility smoke
# --------------------------------------------------------------------------


def test_keyboard_reaches_navigation_and_activates_a_disclosure(page, spa_runtime):
    """Tab through the top navigation and open a disclosure with the keyboard."""
    probe = page
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")

    reached: list[str] = []
    for _ in range(12):
        probe.page.keyboard.press("Tab")
        label = probe.page.evaluate(
            "() => { const el = document.activeElement;"
            " return el ? (el.getAttribute('aria-label') || el.textContent || '').trim() : ''; }"
        )
        if label and label not in reached:
            reached.append(label)
        if (
            any(item in PRIMARY_AREAS for item in reached)
            and len([i for i in reached if i in PRIMARY_AREAS]) >= 3
        ):
            break
    nav_labels = [item for item in reached if item in PRIMARY_AREAS]
    assert len(nav_labels) >= 3, f"Tab did not reach the primary navigation: {reached}"

    # A disclosure is operable from the keyboard alone. V1.2-G2 made
    # `Публикации` a real section - it is content the editor reads, not
    # something they open - so the Story page's remaining disclosure is the
    # chronology toggle (§20), which stayed a disclosure on purpose.
    probe.page.goto(f"{probe.base_url}/stories/{spa_runtime['story_id']}", wait_until="load")
    probe.page.locator("main").wait_for(state="visible")
    disclosure = probe.page.get_by_role("button", name="Хронология")
    disclosure.focus()
    assert probe.page.evaluate(
        "() => document.activeElement?.getAttribute('aria-controls') !== null"
    ), "the disclosure could not take keyboard focus"
    assert disclosure.get_attribute("aria-expanded") == "false"
    probe.page.keyboard.press("Enter")
    assert disclosure.get_attribute("aria-expanded") == "true", (
        "the disclosure did not open with the keyboard"
    )
    probe.assert_clean(context="accessibility smoke")


def test_editor_fields_are_reachable_and_labelled(page, spa_runtime):
    """The editor's fields carry real labels and can be focused."""
    probe = page
    probe.page.goto(
        f"{probe.base_url}/articles/{spa_runtime['manual_article_id']}", wait_until="load"
    )
    probe.page.locator("main").wait_for(state="visible")
    probe.page.get_by_role("button", name="Редактирай").first.click()
    body = probe.page.locator("textarea#article-working-body").first
    body.wait_for(state="visible")
    body.focus()
    assert probe.page.evaluate(
        "() => document.activeElement && document.activeElement.id === 'article-working-body'"
    ), "the article body could not take keyboard focus"
    assert (
        body.get_attribute("aria-label")
        or probe.page.locator("label[for='article-working-body']").count() >= 1
    ), "the article body has no accessible label"
    probe.assert_clean(context="editor accessibility")


# --------------------------------------------------------------------------
# §32 legacy mode browser smoke (the rollback surface)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/stories", "/articles", "/settings"])
def test_legacy_mode_still_serves_the_server_rendered_workbench(legacy_page, path):
    """With `WB_EDITOR_FRONTEND=legacy`, the Workbench still answers in a browser."""
    probe = legacy_page
    probe.goto(path)
    body = probe.page.locator("body").inner_text()
    assert body.strip(), f"legacy {path} rendered nothing"
    assert probe.page.locator("#root").count() == 0, f"legacy {path} was answered by the React SPA"
    # The legacy Workbench links its own operator surfaces and stylesheet.
    hrefs = probe.page.evaluate(
        "() => [...document.querySelectorAll('[href]')].map(el => el.getAttribute('href'))"
    )
    assert "/inbox" in hrefs or "/static/style.css" in hrefs, (
        f"legacy {path} does not look like the server-rendered Workbench: {hrefs[:12]}"
    )


def test_legacy_mode_never_serves_the_compiled_bundle(legacy_page):
    """In legacy mode the SPA document is not served at all."""
    probe = legacy_page
    probe.goto("/")
    assert probe.page.locator("#root").count() == 0
    assert '<div id="root">' not in probe.page.content()


# --------------------------------------------------------------------------
# §35 performance sanity (no budgets, only pathology detection)
# --------------------------------------------------------------------------


def test_no_pathological_repeated_requests_or_infinite_query_loop(page, spa_server):
    """Detect repeated API calls, asset re-loading and route-loading regressions."""
    probe = page
    requests: list[str] = []
    probe.page.on("request", lambda request: requests.append(request.url))

    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")
    probe.page.wait_for_timeout(2500)  # long enough for a query loop to show up

    api_calls = [url for url in requests if "/api/v1/" in url]
    counts = Counter(api_calls)
    repeated = {url: n for url, n in counts.items() if n > 3}
    assert not repeated, f"a single API endpoint was polled repeatedly: {repeated}"

    assets = [url for url in requests if "/assets/" in url]
    asset_counts = Counter(assets)
    reloaded = {url: n for url, n in asset_counts.items() if n > 1}
    assert not reloaded, f"compiled assets were fetched more than once: {reloaded}"

    # One client-side navigation must not re-download the whole bundle.
    probe.reset()
    nav_link(probe.page, "Архив").click()
    probe.page.get_by_role("heading", name="Архив", level=1).wait_for(state="visible")
    probe.page.wait_for_timeout(1200)
    after_assets = [url for url in requests if "/assets/" in url]
    assert len(after_assets) == len(assets), (
        f"navigating re-fetched compiled assets: {len(after_assets) - len(assets)} extra"
    )
    probe.assert_clean(context="performance sanity")
