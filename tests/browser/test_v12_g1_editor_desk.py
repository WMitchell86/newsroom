"""V1.2-G1 §32-§34: the editor desk, proven in a real browser.

Everything runs against the real production topology - a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` - against an isolated store root seeded with a realistic desk: ten
current Stories with differing publisher counts, one assessed blocking gap, one
active Article and a completed run. Only the outbound provider edges are
substituted.

The assertions here describe what the editor can actually *do* on the first
screen, and what the screen must refuse to claim. In particular §30 asks for
proof that a non-backed category control changes no Story data, and that the
frontend never invents generic trust language for a precise evidence blocker.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from .conftest import DIST, VIEWPORT, PageProbe
from .fixture_data import build_g1_desk_fixture, install_g1_research_edges

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

#: §33: the review artifacts, and the four required states.
SHOT_DIR = Path(__file__).resolve().parents[2] / "var" / "g1_screenshots"
LAPTOP_VIEWPORT = {"width": 1280, "height": 900}

#: How long the substituted draft provider takes. Long enough that the pending
#: state is a real, observable phase rather than a race the test happened to win.
SLOW_DRAFT_SECONDS = 6.0


@pytest.fixture
def desk_page(browser, boundary_substitutes, tmp_path, monkeypatch):
    """A browser page on a G1-shaped, isolated newsroom.

    Function-scoped on purpose: the session fixture points the same environment
    variables at its own root, so this fixture borrows them for one test and
    always gives them back.

    The draft provider is slowed here so §33's pending screenshot captures a
    genuinely in-flight Quick Draft. The substitution wraps the session-scoped
    one rather than replacing it, so every other boundary stays as that fixture
    installed it.
    """
    import time

    from editor_assistant.drafting import generate as gen
    from editor_assistant.workflow import story_operations
    from editor_assistant.workflow.workbench import http

    if not (DIST / "index.html").exists():
        pytest.skip(f"production build missing: run `cd frontend && npm run build` ({DIST})")

    original_provider = gen._call_gemini

    def slow_draft(prompt_text, *, api_key="", timeout=0, role="draft", **kwargs):
        if role == "draft":
            time.sleep(SLOW_DRAFT_SECONDS)
        return original_provider(prompt_text, api_key=api_key, timeout=timeout, role=role, **kwargs)

    monkeypatch.setattr(gen, "_call_gemini", slow_draft)

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
            "GEMINI_API_KEY": "g1-substitute-not-a-real-key",
        }
    )
    for name in ("OPENROUTER_API_KEY", "BRAVE_SEARCH_API_KEY", "SERPER_API_KEY", "TINYFISH_API_KEY"):
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
        yield probe, build_g1_desk_fixture(newsroom=newsroom, editorial=editorial)
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
    probe.page.locator("[data-story-row]").first.wait_for(state="visible", timeout=20000)


def main_text(probe) -> str:
    """The rendered Today text, case-folded.

    Section headings are uppercased by CSS and `inner_text` reports the
    transformed text, so a case-sensitive match on a source string would be a
    test of the stylesheet rather than of the projection.
    """
    return probe.page.locator("main").inner_text().casefold()


def story_titles(probe) -> list[str]:
    return probe.page.locator("[data-story-row] h3 a").all_inner_texts()


# --------------------------------------------------------------------------
# §32 the structure
# --------------------------------------------------------------------------


def test_the_desk_has_the_rail_header_and_wire_rows(desk_page):
    """§1/§3/§4: left rail, header, toolbar, and a list of rows - not cards."""
    probe, ids = desk_page
    open_today(probe)

    # The rail is a real landmark and holds the frozen destinations.
    rail = probe.page.get_by_role("complementary")
    rail.wait_for(state="visible")
    labels = [rail.get_by_role("link").nth(i).inner_text().strip() for i in range(rail.get_by_role("link").count())]
    assert tuple(label for label in labels if label != "Редакция") == (
        "Днес", "Истории", "Статии", "Архив", "Настройки",
    ), labels
    assert "Източници" not in labels, "a sixth primary destination appeared"

    # The header states the screen, its currency, and one obvious action.
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")
    body = main_text(probe)
    assert "нови публикации и развития" in body
    assert "последно обновяване:" in body
    assert "24 нови публикации" in body
    probe.page.get_by_role("button", name="Обнови").wait_for(state="visible")

    # Ten real rows, each a wire row separated by a divider rather than a card.
    rows = probe.page.locator("[data-story-row]")
    assert rows.count() == ids["story_count"]
    assert probe.page.get_by_label("Търсене в днешните истории").is_visible()
    assert probe.page.get_by_label("Сортирай").is_visible()
    probe.assert_clean(context="the editor desk structure")


def test_settings_sits_at_the_bottom_of_the_left_column(desk_page):
    """§24: Settings is the fifth frozen destination and stays in the left rail."""
    probe, _ = desk_page
    open_today(probe)

    settings = probe.page.get_by_role("link", name="Настройки", exact=True)
    settings.wait_for(state="visible")
    box = settings.bounding_box()
    rail = probe.page.get_by_role("complementary").bounding_box()
    assert box is not None and rail is not None
    # Horizontally inside the rail, and below the four everyday destinations.
    assert box["x"] >= rail["x"] and box["x"] + box["width"] <= rail["x"] + rail["width"] + 1

    editorial = probe.page.get_by_role("link", name="Архив", exact=True).bounding_box()
    assert box["y"] > editorial["y"], "Настройки is not below the editorial destinations"
    probe.assert_clean(context="Settings placement")


def test_search_filters_the_loaded_rows(desk_page):
    """§6: obvious search, scoped to what Today actually holds."""
    probe, _ = desk_page
    open_today(probe)
    assert len(story_titles(probe)) == 10

    field = probe.page.get_by_label("Търсене в днешните истории")
    field.fill("музей")

    probe.page.wait_for_function(
        "() => document.querySelectorAll('[data-story-row]').length === 1"
    )
    assert "музей" in story_titles(probe)[0]
    # Clearing really restores the set.
    field.fill("")
    probe.page.wait_for_function(
        "() => document.querySelectorAll('[data-story-row]').length === 10"
    )
    probe.assert_clean(context="Today search")


def test_sorting_by_publisher_count_reorders_and_default_restores(desk_page):
    """§9/§10/§11: obvious sorting, view-only, no reload and no mutation."""
    probe, _ = desk_page
    open_today(probe)
    # A marker on `window` dies with the document: if sorting reloaded the page it
    # would be gone, which is exactly what a view preference must never do.
    probe.page.evaluate("() => { window.__g1 = 'alive'; }")
    chronological = story_titles(probe)

    probe.page.get_by_label("Сортирай").select_option("publishers")
    probe.page.wait_for_timeout(300)
    by_publishers = story_titles(probe)

    assert by_publishers != chronological, "the sort did not reorder anything"
    # The five-publisher Story (БНР и пет независими медии) now leads.
    assert "БНР" in by_publishers[0], by_publishers
    # §11: still the same document, and no navigation happened.
    assert probe.page.evaluate("() => window.__g1") == "alive"
    assert urlsplit(probe.page.url).path == "/"

    probe.page.get_by_label("Сортирай").select_option("newest")
    probe.page.wait_for_timeout(300)
    assert story_titles(probe) == chronological, "the default order was not restored"
    probe.assert_clean(context="Today sorting")


# --------------------------------------------------------------------------
# §5 the categories: prepared space, no manufactured data
# --------------------------------------------------------------------------


def test_the_category_rail_changes_no_story_data(desk_page):
    """§5/§30: the taxonomy is visible, inert, and changes nothing.

    This is the assertion that matters most for the owner review. A category
    control that looked live but filtered nothing would be the exact failure the
    brief warns about, so the row set is compared before and after.
    """
    probe, _ = desk_page
    open_today(probe)
    before = story_titles(probe)

    # `Всички` is the one real state.
    assert probe.page.get_by_text("Всички", exact=True).count() >= 1
    # The future labels are present but genuinely disabled, with an accessible
    # reason and no fabricated counts.
    for label in ("Общество", "Спорт", "Инфраструктура"):
        control = probe.page.get_by_role("button", name=label, exact=True)
        control.wait_for(state="attached")
        assert not control.is_enabled(), f"{label} is actionable without category data"
    assert "Категоризацията предстои" in probe.page.get_by_role("complementary").inner_text()

    # Clicking one must not move a single row.
    probe.page.get_by_role("button", name="Спорт", exact=True).click(force=True)
    probe.page.wait_for_timeout(300)
    assert story_titles(probe) == before, "a non-backed category filter changed the data"
    probe.assert_clean(context="the prepared category rail")


# --------------------------------------------------------------------------
# §16-§21 the evidence warning: precise, and never a trust claim
# --------------------------------------------------------------------------


def test_a_blocked_draft_shows_the_real_reason_not_a_trust_claim(desk_page, monkeypatch):
    """§18-§21: the actual blocker, and `Прегледай` still offered.

    The fixture's Story carries a real assessed blocking gap, and the research
    round cap is spent, so the automated path genuinely cannot take another
    speculative round. The sentence the editor sees must be the backend's own
    evidence wording — not a judgement about the publisher, and not a generic
    "we need a reliable source".
    """
    from editor_assistant.workflow import story_research_store

    install_g1_research_edges(monkeypatch)
    probe, ids = desk_page
    open_today(probe)

    # The cap is a canonical part of the Story's research basis, written the way
    # the pipeline writes it.
    basis = story_research_store.get_story_research(ids["blocking_story_id"])
    story_research_store.save_story_research({**basis, "research_rounds": 2})

    row = probe.page.locator(f"[data-story-row='{ids['blocking_story_id']}']")
    row.wait_for(state="visible")
    row.get_by_role("button", name="Чернова").click()

    alert = probe.page.get_by_role("alert").first
    alert.wait_for(state="visible", timeout=120000)
    text = alert.inner_text()
    # §19: the sentence is the backend's own. This Story's assessed basis still
    # carries a blocking gap, so the honest stop is the blocking-gap wording — the
    # editor is told the *information* is incomplete, not that a publisher is
    # suspect.
    assert "непопълнена информация" in text.casefold(), text
    # §18: the frontend must not substitute a reputation judgement.
    for forbidden in ("надежден", "Надежден", "Ненадежден", "Trusted", "Verified"):
        assert forbidden not in text, text
    # §19: the way out is still there, in the same action region.
    row.get_by_role("link", name="Прегледай").wait_for(state="visible")
    assert urlsplit(probe.page.url).path == "/", probe.page.url
    probe.assert_clean(context="an evidence blocker")


# --------------------------------------------------------------------------
# §26 nothing existing regressed
# --------------------------------------------------------------------------


def test_the_proven_d1_d2_behaviour_survives(desk_page):
    """§26: cap, refresh line, Article tier, and the Quick Draft hierarchy."""
    probe, _ = desk_page
    open_today(probe)
    body = main_text(probe)

    # D1 refresh context, in the newsroom's own timezone and never raw UTC.
    assert "последно обновяване:" in body
    assert "24 нови публикации" in body
    # §27: the Article tier is present but below the Stories.
    assert "статии за действие" in body
    assert "работа по бюджета на градините" in body
    # §16: exactly the three triage intents, with `Чернова` the forward one.
    first = probe.page.locator("[data-story-row]").first
    assert first.get_by_role("button", name="Игнорирай").is_visible()
    assert first.get_by_role("link", name="Прегледай").is_visible()
    assert first.get_by_role("button", name="Чернова").is_visible()
    probe.assert_clean(context="preserved D1/D2 behaviour")


def test_a_quick_draft_still_reaches_the_draft(desk_page, monkeypatch):
    """§26: the D2 fast path is untouched by the visual rewrite.

    The substituted research edges are installed here, in the test body, because
    the session-scoped substitute is installed at session scope and would
    otherwise be replaced.
    """
    install_g1_research_edges(monkeypatch)
    probe, _ = desk_page
    open_today(probe)
    # A Story with no active Article and an unassessed basis: the canonical path
    # researches it, confirms facts, and really creates a Draft.
    row = probe.page.locator("[data-story-row='s-g1-05']")
    row.get_by_role("button", name="Чернова").click()

    probe.page.wait_for_url("**/articles/**", timeout=180000)
    probe.page.locator("main").wait_for(state="visible")
    # The editor landed on the Article, not on an intermediate Story screen.
    assert "articles" in urlsplit(probe.page.url).path
    probe.assert_clean(context="Quick Draft reaching the Draft")


# --------------------------------------------------------------------------
# §33 the visual review artifacts
# --------------------------------------------------------------------------


def _shoot(probe, name: str) -> Path:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SHOT_DIR / f"{name}.png"
    probe.page.wait_for_timeout(400)
    probe.page.screenshot(path=str(target), full_page=False)
    assert target.exists() and target.stat().st_size > 0, f"empty screenshot {target}"
    return target


def test_capture_owner_review_screenshots(desk_page, monkeypatch):
    """A. normal, B. pending, C. blocker, D. narrow laptop - at two widths.

    These four states are the review itself, so each one is produced by real
    product state rather than by styling a fixture: the pending row is a real
    Quick Draft in flight, and the blocker is a real assessed gap.
    """
    from editor_assistant.workflow import story_research_store

    install_g1_research_edges(monkeypatch)
    probe, ids = desk_page
    captured: list[Path] = []

    open_today(probe)

    # A. the ordinary desk: ten rows, and the row the owner asked to see.
    captured.append(_shoot(probe, "a-today-1440x1080"))

    # B. one row genuinely preparing a draft. Clicking a Story whose evidence
    #    path runs the substituted provider, which is deliberately slow.
    pending_row = probe.page.locator("[data-story-row='s-g1-05']")
    pending_row.get_by_role("button", name="Чернова").click()
    probe.page.get_by_role("button", name="Подготвя се чернова…").wait_for(
        state="visible", timeout=30000
    )
    captured.append(_shoot(probe, "b-today-quick-draft-pending-1440x1080"))
    # §17: one status sentence and no stage vocabulary.
    pending_text = probe.page.get_by_role("button", name="Подготвя се чернова…").inner_text()
    assert "подготвя се чернова" in pending_text.casefold(), pending_text
    # Let the real operation finish so the fixture is left clean.
    probe.page.wait_for_url("**/articles/**", timeout=180000)

    # C. the precise evidence blocker on its own row. The research cap is spent
    #    first, so the honest stop is the evidence wording and not a retry.
    open_today(probe)
    basis = story_research_store.get_story_research(ids["blocking_story_id"])
    story_research_store.save_story_research({**basis, "research_rounds": 2})
    probe.page.reload(wait_until="load")
    probe.page.locator("[data-story-row]").first.wait_for(state="visible", timeout=20000)
    blocking = probe.page.locator(f"[data-story-row='{ids['blocking_story_id']}']")
    blocking.get_by_role("button", name="Чернова").click()
    probe.page.get_by_role("alert").first.wait_for(state="visible", timeout=180000)
    captured.append(_shoot(probe, "c-today-evidence-blocker-1440x1080"))

    # D. a common laptop width, to judge density and wrapping.
    probe.page.set_viewport_size(LAPTOP_VIEWPORT)
    probe.page.wait_for_timeout(400)
    captured.append(_shoot(probe, "d-today-narrow-laptop-1280x900"))

    # No horizontal overflow at either width: a desk that scrolls sideways is not
    # a desk an editor can work at.
    for width in (1440, LAPTOP_VIEWPORT["width"]):
        probe.page.set_viewport_size({"width": width, "height": 1080})
        probe.page.wait_for_timeout(200)
        overflow = probe.page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"horizontal overflow of {overflow}px at {width}px"

    probe.assert_clean(context="the owner-review screenshot pass")
    print("\n[g1] screenshots:\n  " + "\n  ".join(str(path) for path in captured))
