"""D2A §15-§23: the complete Article lifecycle through a real browser.

Preparation -> generated Draft -> editing/autosave -> conflict -> Ready ->
Ready->Edit -> Finalize/Archive, plus the lighter manual path. Real React, real
API, real canonical stores, real operation tokens. Only the external model
transport is substituted.
"""

from __future__ import annotations

import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .fixture_data import SLOW_DRAFT_PROVIDER_SECONDS
from .helpers import (
    assert_spa_shell,
    nav_link,
    open_article,
    path_of,
    state_marker,
    wait_for_state,
)

#: Internal Case/Idea vocabulary that must never reach an editor screen (§15).
INTERNAL_WORDS = ("Case", "Идея", "ИдеяCard", "draft_id", "evidence_id", "Доказателства", "Етап")


def open_story(probe, story_id: str) -> None:
    probe.page.goto(f"{probe.base_url}/stories/{story_id}", wait_until="load")
    probe.page.locator("header nav").first.wait_for(state="visible")
    probe.page.locator("main").wait_for(state="visible")


def open_today(probe) -> None:
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible")


def editor_field(page, name: str):
    """A labelled form control, addressed by role so a section heading repeating
    the same words cannot be mistaken for the field itself."""
    return page.get_by_role("textbox", name=name, exact=True)


# --------------------------------------------------------------------------
# §15 Article creation from the Story Workspace
# --------------------------------------------------------------------------


def test_start_article_creates_a_real_preparation_article(page, spa_runtime):
    """`Започни статия`: a real POST, then the browser is on the new Article."""
    probe = page
    story_id = spa_runtime["story_id"]
    before = len(
        probe.page.request.get(f"{probe.base_url}/api/v1/articles?filter=all&query=").json()[
            "data"
        ]["articles"]
    )
    open_story(probe, story_id)
    probe.page.get_by_role("button", name="Започни статия").click()
    probe.page.wait_for_url("**/articles/**", timeout=20000)
    article_id = path_of(probe.page).rsplit("/", 1)[-1]
    open_article(probe, article_id)

    assert state_marker(probe.page) == "подготовка"
    # The Story link points back at the canonical Story this Article belongs to.
    story_link = probe.page.locator(f"main a[href='/stories/{story_id}']").first
    story_link.wait_for(state="visible")
    body = probe.page.locator("main").inner_text()
    for word in INTERNAL_WORDS:
        assert word not in body, f"internal vocabulary {word!r} leaked into the Article view"
    assert_spa_shell(probe.page)

    after = len(
        probe.page.request.get(f"{probe.base_url}/api/v1/articles?filter=all&query=").json()[
            "data"
        ]["articles"]
    )
    assert after == before + 1, "the Article was not really created"
    probe.assert_clean(context="start article")


# --------------------------------------------------------------------------
# §16 Preparation: working title and Editorial Focus
# --------------------------------------------------------------------------


def test_preparation_title_and_focus_updates_are_persisted(page, spa_runtime):
    """Working title and Editorial Focus are edited and confirmed canonically."""
    probe = page
    article_id = spa_runtime["focus_article_id"]
    open_article(probe, article_id)

    # Both controls are real labelled form fields in the Preparation workspace.
    title = editor_field(probe.page, "Работно заглавие")
    focus = editor_field(probe.page, "Редакционен фокус")
    title.wait_for(state="visible")
    focus.wait_for(state="visible")

    new_title = "Ремонтът на улицата тръгна през октомври (проверка)"
    title.fill(new_title)
    title.press("Enter")
    new_focus = "Да обясним решението и последиците за жителите."
    focus.fill(new_focus)
    # The focus is a real form: it is confirmed by submitting it, not by blurring.
    probe.page.get_by_role("button", name="Промени фокуса").click()
    probe.page.wait_for_timeout(800)

    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["content"]["title"] == new_title
    assert detail["editorialFocus"]["text"] == new_focus
    assert detail["editorialFocus"]["confirmedAt"], "the focus was not confirmed canonically"
    probe.assert_clean(context="preparation title and focus")


# --------------------------------------------------------------------------
# §17 generated Draft
# --------------------------------------------------------------------------


def _operation_rows(probe, article_id: str) -> list[dict]:
    """The canonical Article projection, for diagnosing a stuck operation."""
    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    return [
        {
            "state": detail["state"],
            "version": detail["content"]["version"],
            "availableActions": detail["availableActions"],
            "warnings": [w["rule"] for w in detail.get("warnings", [])],
            "preparation": (detail.get("preparation") or {}).get("draftEligible"),
        }
    ]


def test_make_draft_produces_a_read_only_draft_body(page, spa_runtime):
    """Направи чернова -> Черновата се създава… -> Чернова, rendered read-only."""
    probe = page
    article_id = spa_runtime["preparation_article_id"]
    open_article(probe, article_id)

    probe.page.get_by_role("button", name="Направи чернова").click()
    probe.page.get_by_text("Черновата се създава…").wait_for(state="visible", timeout=10000)
    # The real operation runs; the canonical state becomes Чернова.
    try:
        wait_for_state(probe.page, "чернова", timeout=60000)
    except PlaywrightTimeoutError:
        # Surface the canonical operation outcome and any product error message,
        # instead of leaving a bare locator timeout.
        alerts = probe.page.get_by_role("alert").all_inner_texts()
        raise AssertionError(
            "the Draft operation did not complete. "
            f"article={_operation_rows(probe, article_id)} alerts={alerts} "
            f"console={probe.console_errors}"
        ) from None
    assert state_marker(probe.page) == "чернова", "the Article did not reach Чернова"

    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["state"] == "draft"
    assert detail["content"]["body"].strip(), "the generated Draft has no body"
    # The Draft body renders read-only: the editor is not active.
    assert probe.page.locator("textarea#article-working-body").count() == 0
    probe.page.get_by_role("button", name="Редактирай").first.wait_for(state="visible")
    probe.assert_clean(context="make draft")


# --------------------------------------------------------------------------
# D2B: the Draft polling budget, proven in a real browser
# --------------------------------------------------------------------------


def test_a_slow_draft_operation_still_succeeds_in_the_ui(page, spa_runtime):
    """D2B: a generation longer than the old 2s budget reaches Чернова anyway.

    The substituted provider in `fixture_data` deliberately takes
    ``SLOW_DRAFT_PROVIDER_SECONDS`` (~4s). Under the old 8 x 250ms budget the
    editor would have reported «Черновата още не е готова» while the backend
    operation was still correctly running. This test fails if the hardened budget
    is ever reverted, and it asserts that no failure wording was ever shown.
    """
    probe = page
    article_id = spa_runtime["slow_draft_article_id"]
    open_article(probe, article_id)

    started = time.monotonic()
    probe.page.get_by_role("button", name="Направи чернова").click()
    probe.page.get_by_text("Черновата се създава…").wait_for(state="visible", timeout=10000)
    try:
        wait_for_state(probe.page, "чернова", timeout=60000)
    except PlaywrightTimeoutError:
        alerts = probe.page.get_by_role("alert").all_inner_texts()
        raise AssertionError(
            "the slow Draft operation did not complete. "
            f"article={_operation_rows(probe, article_id)} alerts={alerts} "
            f"console={probe.console_errors}"
        ) from None
    elapsed = time.monotonic() - started

    # The operation really did outlast the old two-second window.
    assert elapsed >= SLOW_DRAFT_PROVIDER_SECONDS, (
        f"the draft completed in {elapsed:.1f}s, which is faster than the substituted "
        f"provider takes ({SLOW_DRAFT_PROVIDER_SECONDS}s): the slow-path proof did not run"
    )

    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["state"] == "draft"
    assert detail["content"]["body"].strip(), "the generated Draft has no body"

    # No premature-failure wording was ever shown, and nothing claimed failure.
    body = probe.page.locator("main").inner_text()
    for wording in ("още не е готова", "все още се създава. Опитайте", "не можа да бъде създадена"):
        assert wording not in body, f"the UI reported {wording!r} for a slow Draft"
    probe.assert_clean(context="slow draft generation")


# --------------------------------------------------------------------------
# §18 editing and autosave
# --------------------------------------------------------------------------


def open_draft_editor(probe, article_id: str) -> None:
    """Open a Draft workspace and activate the real editor with `Редактирай`."""
    open_article(probe, article_id)
    edit = probe.page.get_by_role("button", name="Редактирай")
    if edit.count() == 0:
        return
    edit.first.click()
    probe.page.locator("textarea#article-working-body").first.wait_for(state="visible")


def test_editor_autosaves_and_survives_a_python_served_reload(page, spa_runtime):
    """Редактирай -> edit -> debounce -> autosave -> Запазено -> reload -> persisted."""
    probe = page
    article_id = spa_runtime["manual_article_id"]
    open_draft_editor(probe, article_id)

    body = probe.page.locator("textarea#article-working-body").first
    title = probe.page.locator("input#article-working-title").first
    body.wait_for(state="visible")

    # The autosave request is observed on the wire, so the proof does not depend
    # on catching a transient label.
    saves: list[str] = []
    probe.page.on(
        "request",
        lambda request: (
            saves.append(request.url)
            if request.method == "PUT" and request.url.endswith("/content")
            else None
        ),
    )

    new_body = "Града получиха средства за обновяване на парка. Работата започна през октомври."
    new_title = "Ръчно написана чернова за парка (редакция)"
    body.fill(new_body)
    # Typing one character at a time keeps the debounce honest: the timer must be
    # reset on every change, and only the final state may be saved.
    for index in range(1, len(new_title) + 1):
        title.fill(new_title[:index])
        probe.page.wait_for_timeout(25)
    # Settle on the exact final value, so a mid-typing snapshot is never the
    # canonical saved title.
    title.fill(new_title)
    probe.page.get_by_text("Запазено", exact=True).first.wait_for(state="visible", timeout=30000)
    assert saves, "no autosave request reached the server"

    # No Save button exists anywhere: autosave is the only persistence path.
    assert probe.page.get_by_role("button", name="Запази").count() == 0

    # Reload through the Python route, then confirm the canonical content.
    probe.page.reload(wait_until="load")
    probe.page.locator("header nav").first.wait_for(state="visible")
    probe.page.locator("main").wait_for(state="visible")
    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["content"]["body"] == new_body
    assert detail["content"]["title"] == new_title
    probe.assert_clean(context="autosave + reload")


# --------------------------------------------------------------------------
# §19 conflict, from two independent client snapshots
# --------------------------------------------------------------------------


def test_conflict_is_shown_and_never_silently_overwritten(browser, spa_server, spa_runtime):
    """Client A and B hold version N; A saves; B must see a conflict, not a loss."""
    from .conftest import VIEWPORT, PageProbe

    article_id = spa_runtime["manual_article_id"]
    probe_a = PageProbe(browser.new_page(viewport=VIEWPORT, locale="bg-BG"), spa_server)
    probe_b = PageProbe(browser.new_page(viewport=VIEWPORT, locale="bg-BG"), spa_server)
    try:
        for probe in (probe_a, probe_b):
            open_draft_editor(probe, article_id)

        # A edits and its autosave lands first.
        body_a = probe_a.page.locator("textarea#article-working-body").first
        body_a.fill("Версия от клиент А: паркът ще бъде обновен през октомври.")
        probe_a.page.get_by_text("Запазено", exact=True).wait_for(state="visible", timeout=20000)
        detail = probe_a.page.request.get(
            f"{probe_a.base_url}/api/v1/articles/{article_id}"
        ).json()["data"]
        version_after_a = detail["content"]["version"]

        # B still holds the older version and now tries to save over it.
        body_b = probe_b.page.locator("textarea#article-working-body").first
        local_b = "Версия от клиент Б: паркът остава затворен до края на месеца."
        body_b.fill(local_b)
        probe_b.page.wait_for_timeout(2500)

        # B is told, explicitly, and its own text is retained.
        conflict = probe_b.page.get_by_role("alert").filter(has_text="променена в друга сесия")
        conflict.wait_for(state="visible", timeout=20000)
        assert "Локалните промени са запазени." in conflict.inner_text()
        assert body_b.input_value() == local_b, "B lost its local text on conflict"

        # Two explicit resolution choices, and no third silent path.
        assert probe_b.page.get_by_role("button", name="Използвай моите промени").count() == 1
        assert probe_b.page.get_by_role("button", name="Зареди запазената версия").count() == 1

        # Exercise one resolution path: B keeps its own text.
        probe_b.page.get_by_role("button", name="Използвай моите промени").click()
        probe_b.page.get_by_text("Запазено", exact=True).wait_for(state="visible", timeout=20000)

        final = probe_b.page.request.get(f"{probe_b.base_url}/api/v1/articles/{article_id}").json()[
            "data"
        ]
        assert final["content"]["version"] > version_after_a
        assert final["content"]["body"] == local_b
        probe_b.assert_only_conflict_noise(context="conflict resolution")
    finally:
        probe_a.page.context.close()
        probe_b.page.context.close()


# --------------------------------------------------------------------------
# §20 Ready, §21 Ready -> Edit
# --------------------------------------------------------------------------


def test_mark_ready_then_reopen_returns_to_draft(page, spa_runtime):
    """Отбележи като готова -> Готова (read-only) -> Редактирай -> Чернова."""
    probe = page
    article_id = spa_runtime["manual_article_id"]
    open_article(probe, article_id)

    ready = probe.page.get_by_role("button", name="Отбележи като готова")
    ready.click()
    wait_for_state(probe.page, "готова")
    assert state_marker(probe.page) == "готова", "the Article did not reach Готова"
    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["state"] == "ready"
    # The Ready workspace is read-only: no editable field is present.
    assert probe.page.locator("textarea#article-working-body").count() == 0
    # Финализирай is offered, per the backend projection.
    assert probe.page.get_by_role("button", name="Финализирай").count() == 1

    # §21: Редактирай from Готова returns the same Article to Чернова.
    probe.page.get_by_role("button", name="Редактирай").click()
    wait_for_state(probe.page, "чернова", timeout=60000)
    assert state_marker(probe.page) == "чернова", "Редактирай did not return the Article to Чернова"
    after = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert after["state"] == "draft"
    assert after["id"] == article_id, "the Article id changed across the transition"
    assert after["content"]["body"], "the content was lost across Редактирай"
    # The Ready checkpoint is no longer represented as current.
    assert after["readiness"]["isCurrent"] is False
    probe.assert_clean(context="ready and reopen")


# --------------------------------------------------------------------------
# §22 Finalize / Archive
# --------------------------------------------------------------------------


def test_finalize_navigates_to_archive_and_leaves_the_active_lists(page, spa_runtime):
    """Финализирай -> /archive/{id}: read-only, gone from Статии, present in Архив."""
    probe = page
    article_id = spa_runtime["lifecycle_article_id"]
    story_id = "s-d2a-clean"
    open_article(probe, article_id)

    # Preparation -> Редактирай -> a manual body, so the Article can be reviewed.
    probe.page.get_by_role("button", name="Редактирай").click()
    body = probe.page.locator("textarea#article-working-body").first
    body.wait_for(state="visible")
    body.fill("Града получиха средства за обновяване на централния парк.")
    probe.page.get_by_text("Запазено", exact=True).first.wait_for(state="visible", timeout=30000)
    wait_for_state(probe.page, "чернова", timeout=60000)

    # Отбележи като готова, then Финализирай.
    probe.page.get_by_role("button", name="Отбележи като готова").click()
    wait_for_state(probe.page, "готова")
    assert probe.page.get_by_role("button", name="Финализирай").count() == 1
    # Finalization is not publishing: no publish control exists anywhere.
    assert probe.page.get_by_role("button", name="Публикувай").count() == 0

    probe.page.get_by_role("button", name="Финализирай").click()
    probe.page.wait_for_url(f"**/archive/{article_id}", timeout=60000)
    assert path_of(probe.page) == f"/archive/{article_id}"
    assert_spa_shell(probe.page)

    # The archived content is read-only.
    assert probe.page.locator("textarea#article-working-body").count() == 0
    archive_text = probe.page.locator("main").inner_text()
    assert "Града получиха средства" in archive_text, "the finalized text is not rendered"

    # Story traceability survives: the archived Article still links its Story.
    assert probe.page.locator(f"main a[href='/stories/{story_id}']").count() >= 1

    # Gone from the active Articles list, present in the Archive.
    active = probe.page.request.get(f"{probe.base_url}/api/v1/articles?filter=all&query=").json()[
        "data"
    ]["articles"]
    assert article_id not in [row["id"] for row in active], (
        "the finalized Article is still in the active Articles list"
    )
    archived = probe.page.request.get(f"{probe.base_url}/api/v1/archive").json()["data"]["articles"]
    assert article_id in [row["id"] for row in archived], "the Article is not in the Archive"

    # The Archive list itself shows it.
    nav_link(probe.page, "Архив").click()
    probe.page.get_by_role("heading", name="Архив", level=1).wait_for(state="visible")
    probe.page.get_by_role(
        "link", name="Обновяването на парка започва през октомври"
    ).first.wait_for(state="visible")
    probe.assert_clean(context="finalize and archive")


# --------------------------------------------------------------------------
# §23 the lighter manual path
# --------------------------------------------------------------------------


def test_manual_continuation_reaches_draft_in_the_browser(page, spa_runtime):
    """Preparation -> Редактирай -> manual body -> Чернова, with no generation."""
    probe = page
    article_id = spa_runtime["manual_article_id"]
    open_article(probe, article_id)
    assert state_marker(probe.page) == "чернова", "the seeded manual Draft is not a Чернова"

    probe.page.get_by_role("button", name="Редактирай").click()
    body = probe.page.locator("textarea#article-working-body").first
    body.wait_for(state="visible")
    manual = "Града получиха средства за обновяване на парка. Работата е в ход."
    body.fill(manual)
    probe.page.get_by_text("Запазено", exact=True).first.wait_for(state="visible", timeout=30000)
    detail = probe.page.request.get(f"{probe.base_url}/api/v1/articles/{article_id}").json()["data"]
    assert detail["state"] == "draft"
    assert detail["content"]["body"] == manual
    # No generated lineage was invented for the manual path.
    assert detail.get("generatedContentVersion") in (None, 0)
    probe.assert_clean(context="manual continuation")
