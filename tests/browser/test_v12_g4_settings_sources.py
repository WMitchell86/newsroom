"""V1.2-G4 §29-§34 — `Настройки → Източници`, proven in a real browser.

Everything runs against the real production topology — a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` — against an **isolated** registry seeded with the sources the owner
actually has. The repository's real ``var/newsroom`` and ``var/editorial_workflow``
are hashed before the first test and after the last one by the session-scoped
autouse fixture in ``conftest.py``: any changed byte fails the run (§33).

These are PRODUCT proofs:

  §29  Настройки → Източници → a source is visible → disable → reload → still off
       → re-enable
  §30  Надежден за факти OFF → enable → confirmation → reload → ON, and the
       **backend** registry is what changed
  §31  + Добави източник → save → row appears → reload → persists
  §32  the negative proofs: no AI trust score, no Serper, no Article/Story
       mutation, no publishing vocabulary, no hard delete
  §34  the five owner-review screenshots
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from .conftest import DIST, PageProbe
from .fixture_data import build_g4_sources_fixture

TRACKED_ENV = (
    "WB_NEWSROOM_DIR",
    "NEWSROOM_DIR",
    "WB_EDITORIAL_WORKFLOW_DIR",
    "MODEL_USAGE_DIR",
    "MODEL_HEALTH_PATH",
    "WB_EDITOR_FRONTEND",
    "WB_SPA_DIST",
    "NEWSROOM_SOURCES_PATH",
    "NEWSROOM_SOURCE_HEALTH_PATH",
)

#: §34: the owner-review artifacts, at the two widths the owner named.
SHOT_DIR = Path(__file__).resolve().parents[2] / "var" / "g4_screenshots"
VIEWPORT = {"width": 1440, "height": 1080}
LAPTOP_VIEWPORT = {"width": 1280, "height": 900}

#: §32: vocabulary this slice must never introduce.
PUBLISHING_WORDS = ("Публикувай", "Публикува", "Изпрати", "Одобри", "CMS", "Експорт")
#: §22: no AI credibility scoring, anywhere on the screen.
AI_TRUST_WORDS = ("Надежност", "доверие", "рейтинг", "Оценка", "Trust", "score")


@pytest.fixture
def sources_desk(browser, tmp_path, monkeypatch):
    """A browser page on `Настройки → Източники`, on an isolated registry.

    Function-scoped: the session fixture points the same environment variables at
    its own root, so this borrows them for one test and always gives them back.
    Only the model/search/collector edges are substituted — never the registry,
    the projections or the API.
    """
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
            # The registry itself is pinned too, so the settings service can
            # never fall back to the repository's real file (§33).
            "NEWSROOM_SOURCES_PATH": str(newsroom / "sources.json"),
            "NEWSROOM_SOURCE_HEALTH_PATH": str(newsroom / "source_health.json"),
        }
    )
    os.environ.pop("WB_EDITOR_FRONTEND", None)

    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = browser.new_context(viewport=VIEWPORT, locale="bg-BG")
    probe = PageProbe(context.new_page(), f"http://127.0.0.1:{server.server_address[1]}")
    probe.page.set_default_timeout(30000)
    try:
        yield probe, build_g4_sources_fixture(newsroom=newsroom, editorial=editorial)
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def open_sources(probe) -> None:
    """`Настройки → Източници`, reached the way an editor reaches it."""
    probe.page.goto(f"{probe.base_url}/settings", wait_until="load")
    probe.page.get_by_role("link", name="Източници").click()
    probe.page.get_by_role("heading", level=1, name="Източници").wait_for(state="visible")
    probe.page.get_by_role("table").wait_for(state="visible")


def stored_row(registry_path: Path, source_id: str) -> dict:
    """The canonical registry on disk — the only thing that counts as proof."""
    rows = {row["source_id"]: row for row in json.loads(registry_path.read_text(encoding="utf-8"))}
    assert source_id in rows, f"{source_id} vanished from the canonical registry"
    return rows[source_id]


def row_named(probe, name: str):
    """The table row whose name cell reads exactly `name`."""
    return probe.page.get_by_role("row").filter(has=probe.page.get_by_text(name, exact=True))


def shoot(probe, name: str) -> Path:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SHOT_DIR / f"{name}.png"
    probe.page.wait_for_timeout(350)
    probe.page.screenshot(path=str(target), full_page=False)
    assert target.exists() and target.stat().st_size > 0, f"empty screenshot {target}"
    return target



def wait_switch(probe, label: str, state: str, *, timeout: int = 20000) -> None:
    """Wait until the named switch really reads `state`.

    The switch is on screen before the click, so waiting for it to be *visible*
    would pass immediately — the attribute has to be compared. The label travels
    as a Playwright argument rather than being interpolated into the script, so no
    editor-visible string is ever concatenated into JavaScript.
    """
    probe.page.wait_for_function(
        """([label, state]) => {
              const target = Array.from(
                document.querySelectorAll('[role="switch"]'),
              ).find((el) => el.getAttribute('aria-label') === label);
              return !!target
                && target.getAttribute('aria-checked') === state
                && target.getClientRects().length > 0;
           }""",
        arg=[label, state],
        timeout=timeout,
    )


# --------------------------------------------------------------------------
# §29 basic management
# --------------------------------------------------------------------------


def test_the_editor_can_read_the_registry_and_understand_what_is_watched(sources_desk):
    """§4/§5/§12/§13: the five questions an editor opens this screen to answer."""
    probe, _ = sources_desk
    open_sources(probe)

    body = probe.page.locator("main").inner_text()
    # "Какви източници следим?" — the real regional stack is really listed.
    for expected in (
        "Община Бургас", "Община Поморие", "Община Несебър", "Община Созопол",
        "Община Царево", "ОДМВР Бургас", "БНР Бургас", "БТА — област Бургас",
    ):
        assert expected in body, f"{expected} is not on the Sources screen"
    # §12/§13: editor language, never the stored enum.
    assert "Официален" in body and "Медия" in body and "Регионална медия" in body
    assert "Висок" in body and "Нормален" in body and "Нисък" in body
    for internal in ("official", "google_news_rss", "factual_authority", "source_id"):
        assert internal not in body, f"registry vocabulary leaked: {internal}"

    # §19: three rows share burgas.bg and all three survive.
    assert probe.page.get_by_text("burgas.bg", exact=True).count() == 3
    # §15: a real FAILED record is one quiet word, and the HTTP text stays behind.
    assert probe.page.get_by_text("Проблем", exact=True).count() == 1
    for leaked in ("503", "HTTPError", "bs.gov.bg/"):
        assert leaked not in body, f"collector internal leaked: {leaked}"

    probe.assert_clean(context="reading the registry")


def test_disable_survives_a_reload_and_can_be_undone(sources_desk):
    """§29: disable -> reload -> still disabled -> re-enable."""
    probe, paths = sources_desk
    open_sources(probe)

    toggle = row_named(probe, "Община Несебър").get_by_role("switch", name="Следи се: Община Несебър")
    assert toggle.get_attribute("aria-checked") == "true"
    toggle.click()
    wait_switch(probe, "Следи се: Община Несебър", "false")

    # The canonical registry changed, not just React state.
    assert stored_row(paths["registry"], "nessebar-municipality")["status"] == "disabled"

    # §29: a full reload, from the URL, still shows it disabled.
    probe.page.reload(wait_until="load")
    probe.page.get_by_role("table").wait_for(state="visible")
    after = row_named(probe, "Община Несебър").get_by_role("switch", name="Следи се: Община Несебър")
    assert after.get_attribute("aria-checked") == "false"

    # §8: the row is still listed. Disabling is not removal.
    assert row_named(probe, "Община Несебър").count() == 1

    after.click()
    wait_switch(probe, "Следи се: Община Несебър", "true")
    assert stored_row(paths["registry"], "nessebar-municipality")["status"] == "active"
    probe.assert_clean(context="disabling and re-enabling")


# --------------------------------------------------------------------------
# §30 factual authority
# --------------------------------------------------------------------------


def test_granting_factual_authority_asks_once_and_persists_in_the_backend(sources_desk):
    """§6/§7/§30: the claim-appropriateness policy, and its one confirmation."""
    probe, paths = sources_desk
    open_sources(probe)

    toggle = row_named(probe, "DarikNews Бургас").get_by_role(
        "switch", name="Надежден за факти: DarikNews Бургас"
    )
    assert toggle.get_attribute("aria-checked") == "false"
    toggle.click()

    # §21: exactly one confirmation, carrying the §21 sentence.
    dialog = probe.page.get_by_role("alertdialog")
    dialog.wait_for(state="visible")
    assert "първична фактическа основа" in dialog.inner_text()
    assert dialog.get_by_role("button", name="Потвърди").count() == 1
    assert dialog.get_by_role("button", name="Отказ").count() == 1
    # Nothing was written while the question was open.
    assert stored_row(paths["registry"], "darik-burgas")["factual_authority"] is False

    dialog.get_by_role("button", name="Потвърди").click()
    dialog.wait_for(state="hidden")

    # §30: the BACKEND registry changed.
    assert stored_row(paths["registry"], "darik-burgas")["factual_authority"] is True

    # §30: and it is still ON after a reload.
    probe.page.reload(wait_until="load")
    probe.page.get_by_role("table").wait_for(state="visible")
    wait_switch(probe, "Надежден за факти: DarikNews Бургас", "true")
    probe.assert_clean(context="granting factual authority")


def test_revoking_factual_authority_asks_nothing(sources_desk):
    """§21: the confirmation is one-directional — losing a permission is instant."""
    probe, paths = sources_desk
    open_sources(probe)

    toggle = row_named(probe, "Община Бургас").get_by_role(
        "switch", name="Надежден за факти: Община Бургас"
    )
    assert toggle.get_attribute("aria-checked") == "true"
    toggle.click()
    wait_switch(probe, "Надежден за факти: Община Бургас", "false")

    assert probe.page.get_by_role("alertdialog").count() == 0
    assert stored_row(paths["registry"], "burgas-municipality")["factual_authority"] is False
    probe.assert_clean(context="revoking factual authority")



# --------------------------------------------------------------------------
# §31 add a source
# --------------------------------------------------------------------------


def test_adding_a_source_persists_and_needs_no_collection(sources_desk):
    """§9/§31: six fields in, one row out, and it survives a reload."""
    probe, paths = sources_desk
    open_sources(probe)

    probe.page.get_by_role("button", name="+ Добави източник").click()
    probe.page.get_by_role("heading", name="Нов източник").wait_for(state="visible")

    # §9: exactly the six editor-facing fields, and no internal registry field.
    sheet = probe.page.locator("main")
    for label in ("Име", "URL / домейн", "Тип", "Приоритет"):
        assert sheet.get_by_label(label, exact=True).count() == 1, label
    for internal in ("source_id", "collector", "cadence", "factual_authority", "status"):
        assert internal not in sheet.inner_text(), internal

    sheet.get_by_label("Име", exact=True).fill("Пътна полиция")
    sheet.get_by_label("URL / домейн", exact=True).fill("kat.bg")
    sheet.get_by_label("Тип", exact=True).select_option("official")
    sheet.get_by_role("button", name="Добави източник", exact=True).click()

    probe.page.get_by_role("heading", name="Нов източник").wait_for(state="hidden")
    # §31: the row appears, with a derived id the editor never typed.
    row_named(probe, "Пътна полиция").wait_for(state="visible")
    stored = stored_row(paths["registry"], "patna-politsiya")
    assert stored["name"] == "Пътна полиция"
    assert stored["domain"] == "kat.bg"
    assert stored["kind"] == "official"
    assert stored["status"] == "active"

    # §31: and it persists across a reload.
    probe.page.reload(wait_until="load")
    probe.page.get_by_role("table").wait_for(state="visible")
    row_named(probe, "Пътна полиция").wait_for(state="visible")

    # §31: no collection was needed for any of this.
    assert not [url for url in probe.external_requests if "kat.bg" in url]
    probe.assert_clean(context="adding a source")


# --------------------------------------------------------------------------
# §10 the inline editor
# --------------------------------------------------------------------------


def test_editing_a_source_changes_only_what_the_editor_chose(sources_desk):
    """§10: a small inline editor over one canonical row."""
    probe, paths = sources_desk
    open_sources(probe)

    row_named(probe, "Община Царево").get_by_role("button", name="Редактирай").click()
    probe.page.get_by_role("heading", name="Община Царево").wait_for(state="visible")

    sheet = probe.page.locator("main")
    sheet.get_by_label("Приоритет", exact=True).select_option("high")
    sheet.get_by_role("button", name="Запиши").click()
    probe.page.get_by_role("heading", name="Община Царево").wait_for(state="hidden")

    stored = stored_row(paths["registry"], "tsarevo-municipality")
    assert stored["priority"] == "high"
    # §10: the identity and the untouched policy are exactly as before.
    assert stored["source_id"] == "tsarevo-municipality"
    assert stored["domain"] == "tsarevo.bg"
    assert stored["factual_authority"] is True


# --------------------------------------------------------------------------
# §32 the negative proofs
# --------------------------------------------------------------------------


def test_the_screen_carries_no_ai_trust_score_and_no_publishing_vocabulary(sources_desk):
    """§22/§32: an editorial policy decision, not a model's opinion."""
    probe, _ = sources_desk
    open_sources(probe)
    body = probe.page.locator("body").inner_text()

    for word in AI_TRUST_WORDS:
        assert word not in body, f"§22: AI trust vocabulary on the screen: {word}"
    for word in PUBLISHING_WORDS:
        assert word not in body, f"§32: publishing vocabulary on the screen: {word}"


def test_no_search_provider_and_no_article_or_story_is_touched(sources_desk):
    """§23/§32: no Serper, and no editorial state is mutated by Settings."""
    probe, _paths = sources_desk
    editorial = Path(os.environ["WB_EDITORIAL_WORKFLOW_DIR"])
    before_editorial = sorted(p.name for p in editorial.iterdir()) if editorial.exists() else []

    open_sources(probe)
    row_named(probe, "Община Несебър").get_by_role("switch", name="Следи се: Община Несебър").click()
    wait_switch(probe, "Следи се: Община Несебър", "false")

    # §23: not one search provider was called from this screen.
    assert not probe.external_requests, f"§23: outbound requests: {probe.external_requests}"
    for url in probe.requests:
        path = getattr(url, "url", "")
        assert "/api/v1/today/refresh" not in path, "§23: a collection run was triggered"

    # §32: only the registry moved. No story, article or research file appeared.
    after_editorial = sorted(p.name for p in editorial.iterdir()) if editorial.exists() else []
    assert after_editorial == before_editorial
    newsroom_files = {p.name for p in Path(os.environ["WB_NEWSROOM_DIR"]).iterdir()}
    assert newsroom_files == {"sources.json", "source_health.json"}, newsroom_files
    probe.assert_clean(context="the negative proofs")


def test_there_is_no_hard_delete_anywhere_on_the_screen(sources_desk):
    """§11: `Изключи` is the removal; no destructive action is offered."""
    probe, paths = sources_desk
    open_sources(probe)

    body = probe.page.locator("body").inner_text()
    for destructive in ("Премахни", "Изтрий", "Удалери"):
        assert destructive not in body, destructive
    assert probe.page.get_by_role("button", name="+ Добави източник").count() == 1

    # And the API refuses one too, rather than silently removing the row.
    response = probe.page.request.delete(
        f"{probe.base_url}/api/v1/settings/sources/nessebar-municipality"
    )
    assert response.status == 405
    assert "nessebar-municipality" in stored_row(
        paths["registry"], "nessebar-municipality"
    )["source_id"]


# --------------------------------------------------------------------------
# §34 the owner-review screenshots
# --------------------------------------------------------------------------


def test_capture_owner_review_screenshots(sources_desk):
    """The five artifacts the owner asked to see, with realistic source names."""
    probe, _ = sources_desk

    # a) the list
    open_sources(probe)
    shoot(probe, "a-settings-sources-1440x1080")

    # b) the inline editor, open on a real source
    row_named(probe, "Община Бургас").get_by_role("button", name="Редактирай").click()
    probe.page.get_by_role("heading", name="Община Бургас").wait_for(state="visible")
    shoot(probe, "b-settings-source-edit-1440x1080")
    probe.page.get_by_role("button", name="Отказ").click()

    # c) the add form
    probe.page.get_by_role("button", name="+ Добави източник").click()
    probe.page.get_by_role("heading", name="Нов източник").wait_for(state="visible")
    shoot(probe, "c-settings-add-source-1440x1080")
    probe.page.get_by_role("button", name="Отказ").click()

    # d) the authority confirmation
    row_named(probe, "DarikNews Бургас").get_by_role(
        "switch", name="Надежден за факти: DarikNews Бургас"
    ).click()
    probe.page.get_by_role("alertdialog").wait_for(state="visible")
    shoot(probe, "d-settings-authority-confirmation-1440x1080")
    probe.page.get_by_role("alertdialog").get_by_role("button", name="Отказ").click()

    # e) the same list at the laptop width
    probe.page.set_viewport_size(LAPTOP_VIEWPORT)
    probe.page.get_by_role("table").wait_for(state="visible")
    shoot(probe, "e-settings-sources-1280x900")

    probe.assert_clean(context="the owner-review screenshots")

    probe.assert_clean(context="editing a source")


def test_cancelling_the_confirmation_leaves_the_registry_untouched(sources_desk):
    """§21: `Отказ` really means no."""
    probe, paths = sources_desk
    before = paths["registry"].read_bytes()
    open_sources(probe)

    row_named(probe, "DarikNews Бургас").get_by_role(
        "switch", name="Надежден за факти: DarikNews Бургас"
    ).click()
    probe.page.get_by_role("alertdialog").get_by_role("button", name="Отказ").click()
    probe.page.get_by_role("alertdialog").wait_for(state="hidden")

    assert paths["registry"].read_bytes() == before
    probe.assert_clean(context="cancelling the authority confirmation")

