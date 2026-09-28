"""V1.2-G3 §38-§43 — the Article / Draft workspace, proven in a real browser.

Everything runs against the real production topology — a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` — against an isolated store root seeded with the four Article states
the owner asked to review: an eligible Preparation Article, a Preparation
Article whose Story still needs research, a Draft with a realistic Bulgarian
body, and a Ready Article.

These are PRODUCT proofs, not pixel tests. They assert what the editor can do:

  §38  open -> useful Focus already there -> touch nothing -> «Направи чернова»
  §39  click an alternative -> the Focus changes -> one save -> no confirm step
  §40  «Проучи историята» runs the canonical Story command and refetches
  §41  write for a while: one editor, autosave, reload keeps the text
  §42  Draft -> «Отбележи като готова» -> «Финализирай» -> Archive
  §43  the six owner-review screenshots
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from .conftest import DIST, PageProbe
from .fixture_data import build_g3_article_fixture

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

#: §43: the owner-review artifacts, at the two widths the owner named.
SHOT_DIR = Path(__file__).resolve().parents[2] / "var" / "g3_screenshots"
VIEWPORT = {"width": 1440, "height": 1080}
LAPTOP_VIEWPORT = {"width": 1280, "height": 900}

#: §28/§37: vocabulary that must never appear on an Article.
FORBIDDEN_WORDS = ("Публикувай", "Публикува", "Изпрати", "Одобри", "CMS", "Експорт")


@pytest.fixture
def article_desk(browser, boundary_substitutes, tmp_path, monkeypatch):
    """A browser page on the four G3 Article states, on an isolated root.

    Function-scoped on purpose: the session fixture points the same environment
    variables at its own root, so this one borrows them for a single test and
    always gives them back. Only the model/search/collector edges are
    substituted — never the stores, the projections or the API.
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
            "GEMINI_API_KEY": "g3-substitute-not-a-real-key",
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
        yield probe, build_g3_article_fixture(newsroom=newsroom, editorial=editorial)
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


def open_article(probe, article_id: str) -> None:
    probe.page.goto(f"{probe.base_url}/articles/{article_id}", wait_until="load")
    probe.page.get_by_role("heading", level=1).wait_for(state="visible", timeout=30000)
    probe.page.locator("main").wait_for(state="visible")


def article_state(probe, article_id: str) -> str:
    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    return detail["state"]


def shoot(probe, name: str) -> Path:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SHOT_DIR / f"{name}.png"
    probe.page.wait_for_timeout(400)
    probe.page.screenshot(path=str(target), full_page=False)
    assert target.exists() and target.stat().st_size > 0, f"empty screenshot {target}"
    return target


# --------------------------------------------------------------------------
# §38 the preparation fast path — the most important G3 product proof
# --------------------------------------------------------------------------


def test_preparation_reaches_a_draft_without_touching_the_focus(article_desk):
    """§11/§38: the ideal path is DO NOTHING -> «Направи чернова»."""
    probe, ids = article_desk
    open_article(probe, ids["prep_article_id"])

    focus = probe.page.get_by_role("textbox", name="Редакционен фокус")
    focus.wait_for(state="visible")
    # §11: the Focus arrived already filled and already usable.
    assert focus.input_value().strip(), "the Focus is empty on a Preparation Article"
    # §10: no confirmation, no apply, no wizard.
    for absent in ("Потвърди фокуса", "Избери фокус", "Напред", "Стъпка"):
        assert probe.page.get_by_text(absent).count() == 0, absent

    # The editor makes NO Focus interaction at all.
    probe.page.get_by_role("button", name="Направи чернова").click()
    probe.page.get_by_role("heading", name="Чернова").wait_for(state="visible", timeout=60000)

    detail = probe.page.request.get(
        f"{probe.base_url}/api/v1/articles/{ids['prep_article_id']}"
    ).json()["data"]
    assert detail["state"] == "draft"
    assert detail["content"]["body"].strip(), "the fast path produced an empty Draft"
    probe.assert_clean(context="the preparation fast path")


# --------------------------------------------------------------------------
# §39 the alternative Focus
# --------------------------------------------------------------------------


def test_the_focus_is_edited_directly_and_saved_in_one_step(article_desk):
    """V1.2-G4.3 §C: no alternative chips; the editable field IS the interaction.

    The previous contract offered two or three deterministic variants and this
    test proved one click replaced AND saved one. A real review found the
    variants were templates that could sit on any story in the desk, so they are
    gone: zero alternatives is the approved outcome.

    What is preserved here is the part that still matters - the editor types a
    Focus, leaving the field saves it through the one canonical write, there is
    no Confirm or Apply, and the Draft then works.
    """
    probe, ids = article_desk
    article_id = ids["prep_article_id"]
    open_article(probe, article_id)

    focus = probe.page.get_by_role("textbox", name="Редакционен фокус")
    focus.wait_for(state="visible")
    original = focus.input_value()

    # §C3: no generic alternative chip is rendered at all.
    assert probe.page.locator("button[data-focus-alternative]").count() == 0, (
        "the deterministic alternatives are gone; no chip may be rendered"
    )
    assert probe.page.locator("[data-focus-own]").count() == 0

    writes: list[str] = []
    probe.page.on(
        "request",
        lambda request: (
            writes.append(request.url)
            if request.method == "PUT" and request.url.endswith("/focus")
            else None
        ),
    )

    edited = "Показваме само готовото по ремонта и връзката му с пътищата."
    focus.fill(edited)
    focus.blur()

    probe.page.wait_for_timeout(600)
    assert focus.input_value().strip() == edited, "the edited Focus was not kept"
    assert edited != original
    # Leaving the field is the save. There is no second confirmation step.
    assert len(writes) == 1, f"the Focus took {len(writes)} saves, expected exactly 1"
    for absent in ("Потвърди", "Приложи"):
        assert probe.page.get_by_role("button", name=absent).count() == 0, absent

    probe.page.get_by_role("button", name="Направи чернова").click()
    probe.page.get_by_role("heading", name="Чернова").wait_for(state="visible", timeout=60000)
    assert article_state(probe, article_id) == "draft"
    probe.assert_clean(context="the edited Focus")


# --------------------------------------------------------------------------
# §40 research from the Article
# --------------------------------------------------------------------------


def test_research_from_the_article_runs_the_canonical_story_command(article_desk):
    """§21/§22/§24/§40: the same canonical research command, and no generic wording.

    The research edge is put into its operational-outage shape — an existing,
    sanctioned substitute for this suite. Two reasons, both deliberate:

      * §22 needs a real refusal to prove the closed message set. An outage is
        the honest one: the capability is unavailable, which is NOT a statement
        about the evidence, and the generic «Проучването не можа да завърши» must
        not come back.
      * the substituted search provider never records a real search-run ledger,
        so the repository's runtime stores stay byte-identical (§48).
    """
    from .fixture_data import reset_research_boundary, set_research_boundary

    probe, ids = article_desk
    article_id = ids["research_article_id"]
    open_article(probe, article_id)

    action = probe.page.get_by_role("button", name="Проучи историята")
    action.wait_for(state="visible")
    # §24: a readiness blocker is not a generation failure. No draft button, and
    # no manual-continuation escape hatch that was not earned.
    assert probe.page.get_by_role("button", name="Направи чернова").count() == 0
    assert probe.page.get_by_role("button", name="Редактирай").count() == 0

    requests: list[str] = []
    probe.page.on(
        "request",
        lambda request: (
            requests.append(f"{request.method} {request.url}")
            if request.method == "POST" and request.url.endswith("/research")
            else None
        ),
    )
    set_research_boundary(outage="unavailable")
    try:
        action.click()
        # §21: while the round runs, the page says the round is running.
        probe.page.wait_for_timeout(4000)
    finally:
        reset_research_boundary()

    assert any(url.endswith("/research") for url in requests), "no canonical research command was issued"
    body = probe.page.locator("main").inner_text()
    # §22: the generic sentence must be gone, and the refusal must be named.
    assert "Проучването не можа да завърши" not in body
    probe.assert_refusal_clean(context="research from the Article", status="503")


# --------------------------------------------------------------------------
# §41 writing
# --------------------------------------------------------------------------


def test_the_writing_desk_holds_a_real_session(article_desk):
    """§5/§6/§13/§14/§41: one editor, autosave, and a reload that keeps the text."""
    probe, ids = article_desk
    article_id = ids["draft_article_id"]
    open_article(probe, article_id)

    # §5/§6: the evidence rail is present here, and the writing column is the
    # dominant element. The rail is support, not a second page.
    rail = probe.page.get_by_role("heading", name="Факти и източници")
    rail.wait_for(state="visible")
    # V1.2-G4.3: the Draft is editable the moment it opens. There is no
    # `Редактирай` gate in front of the editor's own text.
    body = probe.page.locator("textarea#article-working-body").first
    body.wait_for(state="visible")
    assert probe.page.get_by_role("button", name="Редактирай").count() == 0
    # §13: exactly one body control, and the labelled one is the real one.
    assert probe.page.locator("textarea#article-working-body").count() == 1
    assert probe.page.locator("label[for='article-working-body']").count() >= 1

    # A readable measure and generous writing space, measured in the real page.
    metrics = body.evaluate(
        "el => { const r = el.getBoundingClientRect();"
        " const cs = getComputedStyle(el);"
        " return { width: r.width, height: r.height, line: parseFloat(cs.lineHeight) }; }"
    )
    assert 520 <= metrics["width"] <= 1000, f"writing measure is {metrics['width']}px"
    assert metrics["height"] >= 400, f"writing surface is only {metrics['height']}px tall"
    assert metrics["line"] >= 24, f"line height is only {metrics['line']}px"

    new_text = (
        "Общинският съвет одобри 1,2 милиона лева за ремонта на булевард „Свобода“ в централната "
        "част на града. Решението е прието на заседание в сряда и предвижда работата да започне през "
        "октомври, когато туристическият сезон вече е приключил.\n\n"
        "Средствата са разпределени за три позиции: укрепване на каменната настилка, смяна на "
        "амфората на носа и полагане на нова облицовка на пешеходната част. За инвестицията е "
        "предвиден срок от осем месеца, като първият месец е за подготовка на терена и временна "
        "организация на движението.\n\n"
        "„Много хора ни пишеха за състоянието на булеварда — и имат основание. Това е едно от "
        "най-посещаваните места в града, а настилката е от десетилетия“, заяви зам.-кметът по "
        "градоустройство и строителство след заседанието.\n\n"
        "Община Бургас уточни, че движението по булеварда няма да бъде спирано изцяло. Ще се работи "
        "на участък, а преминаването на автомобилите ще се осъществява в едното платно. Жителите "
        "от квартала посрещнаха решението с противоречиви реакции.\n\n"
        "Ремонтът е част от по-широка програма за обновяване на пешеходните зони в центъра. Общината "
        "обещава да публикува подробен график с дати по етапи след подписването на договора."
    )
    saves: list[str] = []
    probe.page.on(
        "request",
        lambda request: (
            saves.append(request.url)
            if request.method == "PUT" and request.url.endswith("/content")
            else None
        ),
    )
    body.fill(new_text)
    probe.page.get_by_text("Запазено", exact=True).first.wait_for(state="visible", timeout=30000)
    assert saves, "no autosave request reached the server"

    # §41: a browser reload keeps the text.
    probe.page.reload(wait_until="load")
    probe.page.get_by_role("heading", level=1).wait_for(state="visible", timeout=30000)
    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["content"]["body"].strip() == new_text.strip(), "the reload lost the saved text"

    # §19: collapsing the rail gives the writing surface the full width back.
    open_article(probe, article_id)
    # V1.2-G4.3: a Draft is already editable - no `Редактирай` gate.
    probe.page.locator("textarea#article-working-body").first.wait_for(state="visible")
    open_width = probe.page.locator("textarea#article-working-body").first.evaluate(
        "el => el.getBoundingClientRect().width"
    )
    probe.page.get_by_role("button", name="Скрий източниците").click()
    closed_width = probe.page.locator("textarea#article-working-body").first.evaluate(
        "el => el.getBoundingClientRect().width"
    )
    assert closed_width > open_width, f"collapsing the rail did not widen writing ({open_width} -> {closed_width})"
    probe.assert_clean(context="the writing session")


# --------------------------------------------------------------------------
# §42 Ready -> Finalize
# --------------------------------------------------------------------------


def test_ready_to_finalize_never_speaks_of_publishing(article_desk):
    """§25/§26/§27/§42: the editorial decisions, and the Archive."""
    probe, ids = article_desk
    article_id = ids["ready_article_id"]
    open_article(probe, article_id)

    probe.page.get_by_text("Готова").first.wait_for(state="visible")
    # §26: calm, and exactly one forward action.
    assert probe.page.get_by_role("button", name="Финализирай").count() == 1
    assert probe.page.get_by_role("button", name="Редактирай").count() == 1
    assert probe.page.get_by_role("button", name="Отбележи като готова").count() == 0
    body = probe.page.locator("main").inner_text()
    for forbidden in FORBIDDEN_WORDS:
        assert forbidden not in body, forbidden

    probe.page.get_by_role("button", name="Финализирай").click()
    # §27: the Article leaves the active workspace and lands in the Archive.
    # The real `/archive/:articleId` view is what renders here, so the proof
    # reads the real finalized page rather than a stand-in.
    archived = probe.page.get_by_text("Статията е финализирана в редакционната система.")
    archived.wait_for(state="visible", timeout=30000)
    assert "/archive/" in probe.page.url
    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["state"] is None, "a finalized Article is still an active state"
    assert detail["isFinalized"] is True
    # §28: finalized is not published, and the Archive offers no publishing.
    archive_text = probe.page.locator("main").inner_text()
    for forbidden in FORBIDDEN_WORDS:
        assert forbidden not in archive_text, forbidden
    probe.assert_clean(context="finalize")


# --------------------------------------------------------------------------
# §43 the owner-review screenshots
# --------------------------------------------------------------------------


def test_capture_owner_review_screenshots(article_desk):
    """§43: six artifacts with realistic Bulgarian content, no lorem ipsum."""
    probe, ids = article_desk

    # a. Preparation
    open_article(probe, ids["prep_article_id"])
    probe.page.get_by_role("button", name="Направи чернова").wait_for(state="visible")
    shoot(probe, "a-article-preparation-1440x1080")

    # b/c. the Draft, plain and with the evidence rail
    open_article(probe, ids["draft_article_id"])
    # V1.2-G4.3: a Draft is already editable - no `Редактирай` gate.
    probe.page.locator("textarea#article-working-body").first.wait_for(state="visible")
    shoot(probe, "b-article-draft-1440x1080")
    shoot(probe, "c-article-draft-evidence-open-1440x1080")

    # d. a Draft that carries a REAL warning beside the decision it affects.
    #    The warning is raised by the production C4 validation engine about this
    #    real text; the fixture never fabricates a warning row.
    open_article(probe, ids["warning_article_id"])
    warning_heading = probe.page.get_by_role("heading", name="Какво да прегледаш")
    warning_heading.wait_for(state="visible")
    # The point of this artifact is the warning, so it is scrolled into view
    # rather than left just below the fold of an otherwise-identical screen.
    warning_heading.evaluate("el => el.scrollIntoView({ block: \"center\" })")
    shoot(probe, "d-article-draft-warning-1440x1080")

    # e. Ready
    open_article(probe, ids["ready_article_id"])
    probe.page.get_by_text("Готова").first.wait_for(state="visible")
    shoot(probe, "e-article-ready-1440x1080")

    # f. the narrow laptop width
    probe.page.set_viewport_size(LAPTOP_VIEWPORT)
    open_article(probe, ids["draft_article_id"])
    # V1.2-G4.3: a Draft is already editable - no `Редактирай` gate.
    probe.page.locator("textarea#article-working-body").first.wait_for(state="visible")
    shoot(probe, "f-article-draft-1280x900")
    # §33: no horizontal overflow at the narrow width.
    overflow = probe.page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"the page overflows horizontally by {overflow}px at 1280"
    probe.assert_clean(context="the owner-review screenshots")
