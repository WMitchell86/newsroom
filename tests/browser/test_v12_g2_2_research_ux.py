"""V1.2-G2.2 §14-§17: research UX, provider refusal and the original link.

Everything runs against the real production topology - a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` - on an isolated store root. Only the three outbound edges are
substituted, and for this proof the *research* edge is deliberately shaped to
the two real conditions the owner hit:

* a round that takes materially longer than the old ~2 second client budget;
* a search provider that is genuinely not available.

Neither substitutes an API response, and neither touches the stores, the
projections or the evidence rules.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from .conftest import DIST, VIEWPORT, PageProbe
from .fixture_data import (
    build_g2_story_fixture,
    reset_research_boundary,
    set_research_boundary,
)

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

#: §14: the controlled research duration. The old Research budget was 8 x 250ms
#: ~= 2 seconds, so a round that is still working after this many seconds is
#: exactly the case the editor saw as a failure.
LONG_RESEARCH_SECONDS = 5.0


@pytest.fixture
def research_page(browser, boundary_substitutes, tmp_path):
    """A browser page on an isolated root, with a shaped research boundary."""
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
            "GEMINI_API_KEY": "g22-substitute-not-a-real-key",
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
    probe.page.set_default_timeout(30000)
    try:
        story_operations.clear()
        ids = build_g2_story_fixture(newsroom=newsroom, editorial=editorial)
        yield probe, ids, editorial
    finally:
        reset_research_boundary()
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
    probe.page.get_by_role("heading", level=1).wait_for(state="visible", timeout=30000)
    probe.page.locator("main").wait_for(state="visible")


def main_text(probe) -> str:
    return probe.page.locator("main").inner_text().casefold()


def research_rounds(editorial: Path, story_id: str) -> int:
    from editor_assistant.workflow import story_research_store

    return story_research_store.get_story_research(story_id, root=editorial)["research_rounds"]


# --------------------------------------------------------------------------
# §14 a long research round must not look failed
# --------------------------------------------------------------------------


def test_a_research_longer_than_the_old_two_second_budget_never_looks_failed(research_page):
    probe, ids, editorial = research_page
    story_id = ids["unassessed_story_id"]
    set_research_boundary(latency=LONG_RESEARCH_SECONDS)
    open_story(probe, story_id)
    assert research_rounds(editorial, story_id) == 0
    url_before = probe.page.url

    probe.page.get_by_role("button", name="Проучи още").first.click()
    pending = probe.page.get_by_role("button", name="Проучва се…")
    pending.wait_for(state="visible", timeout=10000)

    # The round is now demonstrably longer than the old ~2s budget. Sample it
    # across that window: the UI must stay in the pending state the whole time
    # and must never claim the research failed.
    for _ in range(5):
        probe.page.wait_for_timeout(700)
        assert probe.page.get_by_role("button", name="Проучва се…").count() == 1, (
            "the pending state was replaced before the operation finished"
        )
        assert not probe.page.get_by_text("Проучването все още не е готово").count()
        assert not probe.page.get_by_text("Опитайте отново").count()

    # Completion: the Story updates by itself, with no reload and no navigation.
    probe.page.get_by_role("button", name="Проучи още").first.wait_for(state="visible", timeout=40000)
    assert probe.page.url == url_before
    assert "историята още не е проучена." not in main_text(probe)

    # §14: ONE backend operation. The canonical round counter is the durable
    # proof, and exactly one research request was issued.
    assert research_rounds(editorial, story_id) == 1
    research_calls = [
        request
        for request in probe.requests
        if request.method == "POST" and "/research" in request.url
    ]
    assert len(research_calls) == 1, f"more than one research operation: {research_calls}"
    probe.assert_clean(context="a long research round")


# --------------------------------------------------------------------------
# §15 a genuine provider failure is not missing evidence
# --------------------------------------------------------------------------


def test_an_unavailable_provider_is_operational_never_missing_evidence(research_page):
    probe, ids, editorial = research_page
    story_id = ids["unassessed_story_id"]
    # The page is projected while research is genuinely possible, so the action
    # is honestly offered...
    open_story(probe, story_id)
    probe.page.get_by_role("button", name="Проучи още").first.wait_for(state="visible")
    rounds_before = research_rounds(editorial, story_id)

    # ...and then the search provider is gone before the editor clicks. This is
    # the real race (another session, a provider key expiring, an outage) and it
    # is exactly where the editor used to be told a source was missing.
    set_research_boundary(outage="unavailable")
    probe.page.get_by_role("button", name="Проучи още").first.click()
    probe.page.get_by_role("alert").wait_for(state="visible", timeout=20000)

    body = main_text(probe)
    assert "автоматичното проучване временно не е налично." in body
    # §3: never an evidence statement, and no provider internals.
    for forbidden in (
        "не е намерен отворен източник",
        "няма отворен източник",
        "историята трябва първо",
        "429",
        "доставчик",
        "модел",
        "route",
    ):
        assert forbidden not in body, f"an operational refusal claimed {forbidden!r}"
    # §15: the existing evidence state is completely unchanged.
    assert research_rounds(editorial, story_id) == rounds_before
    # The 503 IS the product refusing correctly, exactly as the existing 409
    # conflict proof allows. Nothing else may be wrong.
    probe.assert_refusal_clean(context="an unavailable provider", status="503")


def test_research_is_not_offered_at_all_when_no_provider_exists(research_page):
    # §3, first half: with no search route the product does not offer research
    # at all, so there is nothing for the editor to be misled by.
    probe, ids, _editorial = research_page
    set_research_boundary(outage="unavailable")
    open_story(probe, ids["unassessed_story_id"])

    assert probe.page.get_by_role("button", name="Проучи още").count() == 0
    body = main_text(probe)
    for forbidden in ("не е намерен отворен източник", "историята трябва първо"):
        assert forbidden not in body
    probe.assert_clean(context="a Story with no available research provider")


def test_a_spent_round_budget_says_quota_precisely(research_page):
    from editor_assistant.workflow import readiness, story_research_store

    probe, ids, editorial = research_page
    story_id = ids["blocking_story_id"]
    open_story(probe, story_id)
    probe.page.get_by_role("button", name="Проучи още").first.wait_for(state="visible")
    gaps_before = story_research_store.get_story_research(story_id, root=editorial)["gaps"]

    # §3: quota wording is used only where the backend KNOWS the budget is the
    # cause, so the proof spends the real canonical counter rather than faking a
    # reason - after the page was projected, exactly as a second session would.
    for index in range(readiness.MAX_RESEARCH_ROUNDS + 1):
        current = story_research_store.get_story_research(story_id, root=editorial)
        story_research_store.merge_research(
            story_id,
            sources=current["sources"],
            facts=current["facts"],
            gaps=current["gaps"],
            assessed_at=current.get("assessed_at"),
            canonical_story={"story_id": story_id},
            operation_id=f"g22-quota-{index}",
            count_round=True,
            root=editorial,
        )

    probe.page.get_by_role("button", name="Проучи още").first.click()
    probe.page.get_by_role("alert").wait_for(state="visible", timeout=20000)

    body = main_text(probe)
    assert "достигнат е лимитът за автоматично проучване на тази история." in body
    # The refusal itself must not claim anything about evidence or expose the
    # transport status. `отворен източник` remains legitimate page vocabulary
    # for a genuinely confirmed source, so only the false claims are forbidden.
    alert_text = probe.page.get_by_role("alert").inner_text().casefold()
    for forbidden in ("отворен източник", "източник", "429"):
        assert forbidden not in alert_text, f"the refusal claimed {forbidden!r}"
    assert not alert_text.startswith("http")
    # §15: the assessed basis is exactly as it was.
    after = story_research_store.get_story_research(story_id, root=editorial)
    assert after["gaps"] == gaps_before
    probe.assert_refusal_clean(context="a spent research budget", status="429")


# --------------------------------------------------------------------------
# §9/§17 the original collected article is one click away
# --------------------------------------------------------------------------


def test_the_original_publication_is_one_external_link_away(research_page):
    probe, ids, _editorial = research_page
    open_story(probe, ids["assessed_story_id"])

    original = probe.page.locator("[data-story-original]")
    original.wait_for(state="visible", timeout=20000)
    assert "отвори оригинала" in original.inner_text().casefold()
    assert original.get_attribute("target") == "_blank"
    assert "noreferrer" in (original.get_attribute("rel") or "")
    # §9: the URL is the one the projection published, not a reconstruction.
    assert original.get_attribute("href").startswith("https://")

    # §10: every publication is reachable too, and neither link claims status.
    section = probe.page.get_by_role("heading", name="Публикации").locator("xpath=../..")
    links = section.get_by_role("link", name="Отвори")
    assert links.count() >= 1
    for index in range(links.count()):
        link = links.nth(index)
        assert link.get_attribute("target") == "_blank"
        assert "noreferrer" in (link.get_attribute("rel") or "")
    section_text = section.inner_text().casefold()
    for forbidden in ("надежден", "потвърден източник", "проверен"):
        assert forbidden not in section_text
    probe.assert_clean(context="the original publication link")
