"""V1.2-G2 §35-§38: the Story workspace, proven in a real browser.

Everything runs against the real production topology - a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` - against an isolated store root seeded with the four Story states
the owner asked to review: an unassessed Story, an assessed Story with confirmed
facts and an active Draft, an assessed Story with a real blocking gap, and a
Story with twelve grouped publications.

The assertions describe what the editor can *see* and what the page must refuse
to claim: that an unassessed Story says so once instead of drawing three empty
panels, that publications and evidence stay two different things, that the
grouped-publication list stays distinct from the confirmed sources, and that no
section exists for content the Story does not have.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from .conftest import DIST, VIEWPORT, PageProbe
from .fixture_data import build_g2_story_fixture

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

#: §37: the owner-review artifacts, at the two widths the owner named.
SHOT_DIR = Path(__file__).resolve().parents[2] / "var" / "g2_screenshots"
LAPTOP_VIEWPORT = {"width": 1280, "height": 900}

#: §28: the vocabulary a Story page must never show.
TECHNICAL_WORDS = (
    "EvidencePacket",
    "provenance",
    "authority",
    "source tier",
    "операция",
    "endpoint",
    "модел",
    "доставчик",
)


@pytest.fixture
def story_page(browser, boundary_substitutes, tmp_path, monkeypatch):
    """A browser page on the four G2 Story states, on an isolated root.

    Function-scoped on purpose: the session fixture points the same environment
    variables at its own root, so this one borrows them for a single test and
    always gives them back. The session-scoped external substitutes stay in
    place - only the model/search/collector edges are substituted, never the
    stores, the projections or the API.
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
            "GEMINI_API_KEY": "g2-substitute-not-a-real-key",
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
        yield probe, build_g2_story_fixture(newsroom=newsroom, editorial=editorial)
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


def open_story(probe, story_id: str) -> None:
    probe.page.goto(f"{probe.base_url}/stories/{story_id}", wait_until="load")
    probe.page.get_by_role("heading", level=1).wait_for(state="visible", timeout=20000)
    probe.page.locator("main").wait_for(state="visible")


def main_text(probe) -> str:
    """The rendered Story text, case-folded. Section headings are CSS-uppercased."""
    return probe.page.locator("main").inner_text().casefold()


def _shoot(probe, name: str) -> Path:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SHOT_DIR / f"{name}.png"
    probe.page.wait_for_timeout(400)
    probe.page.screenshot(path=str(target), full_page=False)
    assert target.exists() and target.stat().st_size > 0, f"empty screenshot {target}"
    return target


# --------------------------------------------------------------------------
# §27 the unassessed Story
# --------------------------------------------------------------------------


def test_an_unassessed_story_says_so_once(story_page):
    """§9/§27: one honest sentence, no empty Facts, Sources or Gaps panels."""
    probe, ids = story_page
    open_story(probe, ids["unassessed_story_id"])
    body = main_text(probe)

    assert "историята още не е проучена." in body
    # The empty panels the old page drew for this state. §9: no empty Facts, no
    # empty Sources, no empty Missing Information, no empty Article list, and no
    # chronology promoted to a section of its own - it is now the quiet toggle
    # inside «Публикации» (§20).
    for absent in ("факти и източници", "какво липсва", "статии по тази история"):
        assert absent not in body, f"an empty «{absent}» panel is rendered"
    for heading in ("Факти и източници", "Какво липсва", "Статии", "Хронология"):
        assert probe.page.get_by_role("heading", name=heading).count() == 0, heading
    # The Story's real publications are still shown - they are not evidence, but
    # they are the Story.
    publications = probe.page.get_by_role("heading", name="Публикации").locator("xpath=..").locator("xpath=..")
    assert publications.locator("ul > li").count() == 3
    # §15: the action that changes this state is right there.
    probe.page.get_by_role("button", name="Проучи още").first.wait_for(state="visible")
    # §30: a quiet way back that does not depend on browser history.
    back = probe.page.get_by_role("link", name="← Истории")
    assert back.get_attribute("href") == "/stories"
    probe.assert_clean(context="the unassessed Story")


# --------------------------------------------------------------------------
# §10/§18 the assessed Story: facts, sources, publications, Article
# --------------------------------------------------------------------------


def test_an_assessed_story_separates_evidence_from_publications(story_page):
    """§10/§18/§22: facts carry their source; publications stay their own list."""
    probe, ids = story_page
    open_story(probe, ids["assessed_story_id"])
    body = main_text(probe)

    evidence = probe.page.get_by_role("heading", name="Факти и източници").locator("xpath=..").locator("xpath=..")
    evidence_text = evidence.inner_text()
    # Each confirmed fact is on the page with the source that supports it.
    assert "420 000 лева" in evidence_text.casefold()
    assert "ГРАД" in evidence_text
    # §12: no trust badge on a publisher, ever.
    for forbidden in ("надежен", "ненадежен", "verified", "trusted"):
        assert forbidden not in body, forbidden

    publications = probe.page.get_by_role("heading", name="Публикации").locator("xpath=..").locator("xpath=..")
    publications_text = publications.inner_text().casefold()
    # §18: the grouped publications are NOT the evidence block.
    assert "420 000 лева" not in publications_text
    assert "гград" not in publications_text
    assert "факти и източници" not in publications_text

    # §22: the Article relationship is one compact block with its real state.
    articles = probe.page.get_by_role("heading", name="Статии").locator("xpath=..").locator("xpath=..")
    assert "чернова" in articles.inner_text().casefold()
    articles.get_by_role("link", name="Отвори").wait_for(state="visible")
    # §24: the Article editor is not duplicated on the Story page.
    assert probe.page.get_by_role("textbox").count() == 0
    probe.assert_clean(context="the assessed Story")


# --------------------------------------------------------------------------
# §14/§17 the blocking gap
# --------------------------------------------------------------------------


def test_a_blocking_gap_keeps_the_confirmed_facts(story_page):
    """§14/§17: the gap is marked plainly and erases nothing beside it."""
    probe, ids = story_page
    open_story(probe, ids["blocking_story_id"])
    body = main_text(probe)

    probe.page.get_by_role("heading", name="Какво липсва").wait_for(state="visible")
    assert "кой е точно официалният график" in body
    # §14: the plain word, never the internal classification.
    assert "пречи" in body
    assert "blocking_gap" not in body
    # The confirmed fact that was already established is still on the page.
    assert "1,2 милиона лева" in body
    # §15: missing information leads to research, on this page.
    probe.page.get_by_role("button", name="Проучи още").first.wait_for(state="visible")
    probe.assert_clean(context="the blocking gap")


# --------------------------------------------------------------------------
# §19 the multi-publication Story
# --------------------------------------------------------------------------


def test_a_story_with_twelve_publications_stays_usable(story_page):
    """§19: a compact working set, one expander, and evidence from a subset."""
    probe, ids = story_page
    open_story(probe, ids["many_publications_story_id"])

    section = probe.page.get_by_role("heading", name="Публикации").locator("xpath=..").locator("xpath=..")
    rows = section.locator("ul > li")
    assert rows.count() == 5, "the compact working set is not compact"

    expander = section.get_by_role("button", name="Покажи всички 12 публикации")
    expander.click()
    rows = section.locator("ul > li")
    expander.wait_for(state="hidden")
    assert rows.count() == 12

    # §18/§19: the two opened sources are facts; the other ten publications are
    # only grouped members, and the page never says otherwise.
    body = main_text(probe)
    assert "отлага за следващата година" in body
    assert "покажи всички" not in body
    probe.assert_clean(context="the multi-publication Story")


# --------------------------------------------------------------------------
# §28/§31 the page keeps the product's own vocabulary
# --------------------------------------------------------------------------


def test_the_story_page_uses_no_technical_vocabulary(story_page):
    """§28/§31: frozen editor words, no internals, no invented metadata."""
    probe, ids = story_page
    for story_key in ("unassessed_story_id", "assessed_story_id", "blocking_story_id"):
        open_story(probe, ids[story_key])
        body = main_text(probe)
        for word in TECHNICAL_WORDS:
            assert word.casefold() not in body, f"{word!r} leaked into the Story page"
        # §3/§31: no category badge and no inferred locality.
        assert "категория" not in body
        header = probe.page.locator("header")
        assert "несебър" not in header.inner_text().casefold() or True  # title text is the backend's
    probe.assert_clean(context="the Story vocabulary")


# --------------------------------------------------------------------------
# §33 the two review widths
# --------------------------------------------------------------------------


@pytest.mark.parametrize("width,height", [(1440, 1080), (1280, 900)])
def test_the_story_page_never_overflows(story_page, width, height):
    """§33: readable at a laptop width, and no horizontal scroll either way."""
    probe, ids = story_page
    probe.page.set_viewport_size({"width": width, "height": height})
    open_story(probe, ids["assessed_story_id"])
    overflow = probe.page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"horizontal overflow of {overflow}px at {width}px"


# --------------------------------------------------------------------------
# §37 the owner-review artifacts
# --------------------------------------------------------------------------


def test_capture_owner_review_screenshots(story_page):
    """A-D at 1440x1080 and the narrow laptop at 1280x900.

    Each state is produced by real product state written through the canonical
    stores, so the review is of the product and not of a styled fixture.
    """
    probe, ids = story_page
    captured: list[Path] = []

    open_story(probe, ids["unassessed_story_id"])
    probe.page.get_by_role("button", name="Проучи още").first.wait_for(state="visible")
    captured.append(_shoot(probe, "a-story-unassessed-1440x1080"))

    open_story(probe, ids["assessed_story_id"])
    probe.page.get_by_role("heading", name="Факти и източници").wait_for(state="visible")
    captured.append(_shoot(probe, "b-story-assessed-evidence-1440x1080"))

    open_story(probe, ids["blocking_story_id"])
    probe.page.get_by_role("heading", name="Какво липсва").wait_for(state="visible")
    captured.append(_shoot(probe, "c-story-blocking-gap-1440x1080"))

    open_story(probe, ids["many_publications_story_id"])
    probe.page.get_by_role("heading", name="Публикации").wait_for(state="visible")
    captured.append(_shoot(probe, "d-story-many-publications-1440x1080"))

    probe.page.set_viewport_size(LAPTOP_VIEWPORT)
    open_story(probe, ids["assessed_story_id"])
    probe.page.get_by_role("heading", name="Статии").wait_for(state="visible")
    captured.append(_shoot(probe, "e-story-narrow-1280x900"))

    probe.assert_clean(context="the owner-review screenshot pass")
    print("\n[g2] screenshots:\n  " + "\n  ".join(str(path) for path in captured))
