"""V1.1-D2 §45-§48: Today fast triage, proven in a real browser.

Everything runs against the real production topology — a real ``npm run build``
output served by the real Python ``ThreadingHTTPServer`` over the real
``/api/v1`` — against an isolated store root. Only the three genuinely external
edges are substituted, by the same session fixture the D2A and D1 suites use.

The assertion this file exists for is a *product* one that no unit test can
make: after one click on ``Чернова`` the editor lands on the Draft, and the
browser never visits the Story workspace or the Preparation screen on the way.
"""

from __future__ import annotations

import os
import threading
from urllib.parse import urlsplit

import pytest

from .conftest import DIST, VIEWPORT, PageProbe

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

HEADLINE = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата"


#: The page every substituted source serves.
#:
#: It is load-bearing, not decorative. The real research executor takes ONE claim
#: per opened page — the first sentence that answers a bootstrap question — and
#: promotes it to a fact only when it is PRIMARY or corroborated by two
#: independent opened domains. So two different hosts serve the SAME sentence, and
#: that sentence names both what happened and who it affects, which is what a real
#: source page about a municipal decision says.
SUBSTITUTED_PAGE = (
    "Ремонтът започва на 1 октомври 2026 г., а жителите на квартала ще пътуват повече, "
    "потвърдиха от информационния център на града."
)

#: Two independent hosts, deliberately NOT `*council*`: the mature angle gate
#: requires assessed editorial angles for council transcripts, and this fixture is
#: a media story, not a council record.
SUBSTITUTED_RESULTS = (
    {
        "rank": 1,
        "title": "Графикът за ремонта е обявен предварително",
        "url": "https://vestnik.example.test/2026/budget-detail",
        "snippet": "Жителите ще се движат по обходен маршрут.",
        "published_at": "",
        "source_name": "vestnik",
    },
    {
        "rank": 2,
        "title": "Общината уточни графика за улицата",
        "url": "https://burgas-news.example.test/2026/repair-plan",
        "snippet": "Работата започва през октомври.",
        "published_at": "",
        "source_name": "burgas-news",
    },
)


def install_d2_research_edges(monkeypatch) -> None:
    """Substitute ONLY the search provider and the page opener.

    Applied on top of the session fixture's model and collector substitutes, so
    the draft model, the real research executor, the real angle gate, the real
    readiness decision and the real stores all stay the product's.

    Called from a test BODY, never from fixture setup: the session-scoped D2A
    substitute is installed at session scope, and a function-scoped patch made
    during setup would be replaced by it.
    """
    from editor_assistant.sources import web_fetch
    from editor_assistant.workflow import search

    class Provider:
        name = "d2_deterministic"

        def search(self, query, count=10, **_kw):
            return {
                "provider": self.name,
                "query": query,
                "requested_count": count,
                "started_at": "2026-09-25T11:00:00Z",
                "status": search.SEARCH_OK,
                "attempt": 1,
                "http_status": 200,
                "retry_after": None,
                "elapsed_ms": 1,
                "results": [dict(row) for row in SUBSTITUTED_RESULTS],
            }

    def fetch_page(url, **_kw):
        return {
            "final_url": url,
            "content_type": "text/html; charset=utf-8",
            "bytes": len(SUBSTITUTED_PAGE),
            "text": SUBSTITUTED_PAGE,
        }

    monkeypatch.setattr(
        search, "provider_chain", lambda capability=search.CAP_WEB, env=None: ([Provider()], [])
    )
    monkeypatch.setattr(web_fetch, "fetch_page", fetch_page)


@pytest.fixture
def triage_page(browser, boundary_substitutes, tmp_path):
    """A browser page on an isolated newsroom holding one current Story."""
    from editor_assistant.workflow import inbox_store, story_operations, story_store
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
            "GEMINI_API_KEY": "d2-substitute-not-a-real-key",
        }
    )
    for name in (
        "OPENROUTER_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "SERPER_API_KEY",
        "TINYFISH_API_KEY",
    ):
        os.environ.pop(name, None)
    os.environ.pop("WB_EDITOR_FRONTEND", None)

    item = {
        "item_id": "d2-triage-origin",
        "source_id": "vestnik",
        "source_item_id": "d2-triage-origin",
        "title": HEADLINE,
        "url": "https://vestnik.example.test/2026/budget",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": "Обобщение",
        "source_kind": "media",
        "status": "NEW",
    }
    inbox_store.save_items([item], newsroom / "inbox.jsonl")
    story = story_store.new_story(item, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-d2-triage"
    story["status"] = "NEW"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")

    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = browser.new_context(viewport=VIEWPORT, locale="bg-BG")
    probe = PageProbe(context.new_page(), f"http://127.0.0.1:{server.server_address[1]}")
    probe.page.set_default_timeout(20000)
    try:
        story_operations.clear()
        yield probe, newsroom
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
    """Open Today and wait until the real page has rendered it."""
    probe.page.goto(f"{probe.base_url}/", wait_until="load")
    probe.page.get_by_role("heading", name="Днес", level=1).wait_for(state="visible", timeout=20000)
    probe.page.locator("main").wait_for(state="visible")


def _row_for(probe, story_id: str):
    return probe.page.locator(f"[data-quick-draft='{story_id}']").first


def test_one_click_reaches_the_draft_without_any_intermediate_navigation(triage_page, monkeypatch):
    """§45 — the core product promise, proved in a real browser.

    Start on Today with an unassessed Story, click ``Чернова`` once, and the
    editor must end up on ``/articles/{id}`` in the ``Чернова`` state with real
    body text. The browser must NOT have visited the Story or Preparation routes
    on the way: that absence is the assertion.
    """
    from editor_assistant.workflow import editor_article_store as articles
    from editor_assistant.workflow import story_research_store

    install_d2_research_edges(monkeypatch)
    probe, _newsroom = triage_page
    open_today(probe)

    # The row really offers the three triage intents the backend granted.
    _row_for(probe, "s-d2-triage").wait_for(state="visible")
    probe.page.get_by_role("button", name="Игнорирай").first.wait_for(state="visible")
    probe.page.get_by_role("link", name="Прегледай").first.wait_for(state="visible")

    probe.page.get_by_role("button", name="Чернова").first.click()

    # §20: one status, and it is about the editor's request, not our stages.
    probe.page.get_by_role("button", name="Подготвя се чернова…").first.wait_for(
        state="visible", timeout=30000
    )
    for stage in ("Проучване", "Отваряне", "Проверка", "Създаване", "Генериране"):
        assert probe.page.get_by_text(stage, exact=False).count() == 0, stage

    # The Draft workspace is the destination, with real generated text.
    probe.page.wait_for_url("**/articles/**", timeout=180000)
    probe.page.locator("main").wait_for(state="visible")
    article_id = probe.page.url.rstrip("/").rsplit("/", 1)[-1]

    # No intermediate screen was visited on the successful path.
    visited = list(probe.visited_routes)
    assert "/stories/" not in visited, f"the Story workspace was visited: {visited}"
    assert not any(
        "/articles/" in route and route != f"/articles/{article_id}" for route in visited
    ), visited

    content = articles.get_article_content(article_id)
    assert content["body"].strip(), "the Draft must carry real generated text"
    # The Story really was researched by the same canonical path.
    basis = story_research_store.get_story_research("s-d2-triage")
    assert story_research_store.evidence_status_of(basis) == "assessed"
    # Exactly one Article, and it is the one the editor landed on.
    active = [
        row
        for row in articles.read_editor_articles()
        if row["story_id"] == "s-d2-triage" and not row.get("finalized_at")
    ]
    assert [row["article_id"] for row in active] == [article_id]
    probe.assert_clean(context="after a Quick Draft from Today")


def test_an_already_assessed_story_never_calls_research(triage_page):
    """§46 — prove the ABSENCE of unnecessary workflow calls, not a duration.

    An assessed Story with sufficient evidence must take the fast path: one Quick
    Draft intent, one generation, a direct Draft — and no research endpoint or
    research operation anywhere in the request sequence.
    """
    from editor_assistant.workflow import story_research_store

    probe, _newsroom = triage_page
    story_research_store.merge_research(
        "s-d2-triage",
        sources=[{"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/b"}],
        facts=[
            {
                "id": "fact_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-d2-triage"},
        operation_id="fixture-round",
        count_round=True,
    )
    open_today(probe)
    probe.requests.clear()

    probe.page.get_by_role("button", name="Чернова").first.click()
    probe.page.wait_for_url("**/articles/**", timeout=180000)

    urls = [str(call.url) for call in probe.requests]
    assert any(url.endswith("/quick-draft") for url in urls), urls
    # §46: the absence is the point. No research was requested at all.
    assert not any(url.endswith("/research") for url in urls), urls
    assert story_research_store.get_story_research("s-d2-triage")["research_rounds"] == 1
    probe.assert_clean(context="after the assessed fast path")


def test_a_blocked_story_stays_on_today_with_one_concise_reason(triage_page):
    """§47 — an honest stop, with no hidden navigation and no Article."""
    from editor_assistant.workflow import editor_article_store as articles
    from editor_assistant.workflow import story_research_store

    probe, _newsroom = triage_page
    # A canonical blocking gap, with the research cap already spent so the
    # automated path cannot take another speculative round.
    story_research_store.merge_research(
        "s-d2-triage",
        sources=[{"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/b"}],
        facts=[
            {
                "id": "fact_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            }
        ],
        gaps=[
            {
                "id": "gap_when",
                "question": "Кога точно започва ремонтът?",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-d2-triage"},
        operation_id="fixture-round",
        count_round=True,
    )
    basis = story_research_store.get_story_research("s-d2-triage")
    story_research_store.save_story_research({**basis, "research_rounds": 2})
    open_today(probe)

    probe.page.get_by_role("button", name="Чернова").first.click()
    alert = probe.page.get_by_role("alert").first
    alert.wait_for(state="visible", timeout=120000)

    # §23: stay on Today, one sentence, and the way out is still offered.
    assert urlsplit(probe.page.url).path == "/", probe.page.url
    assert probe.page.get_by_text("Има непопълнена информация", exact=False).count() >= 1
    probe.page.get_by_role("link", name="Прегледай").first.wait_for(state="visible")
    # §47: no Article Draft was created at all.
    assert articles.read_editor_articles() == []
    probe.assert_clean(context="after a blocked Quick Draft")


def test_ignore_removes_the_row_and_survives_a_reload(triage_page):
    """§48 — the canonical command, not an optimistic illusion."""
    probe, newsroom = triage_page
    open_today(probe)
    probe.page.get_by_role("button", name="Игнорирай").first.wait_for(state="visible")
    probe.page.get_by_role("button", name="Игнорирай").first.click()

    # The row disappears only after a canonical refetch.
    probe.page.wait_for_function(
        "() => !document.querySelector(\"[data-quick-draft='s-d2-triage']\")",
        timeout=30000,
    )
    # §48: reload the browser. The Story stays absent, because the store really
    # changed — not because the page remembered anything.
    probe.page.reload(wait_until="load")
    probe.page.locator("header nav").first.wait_for(state="visible")
    probe.page.wait_for_function(
        "() => !document.querySelector(\"[data-quick-draft='s-d2-triage']\")",
        timeout=30000,
    )
    # The canonical store really changed, so the absence is not a page artefact.
    from editor_assistant.workflow import story_store

    stored = story_store.read_store(newsroom / "stories.json")["stories"]
    assert {row["story_id"] for row in stored} == {"s-d2-triage"}
    assert next(row for row in stored if row["story_id"] == "s-d2-triage")["status"] == "IGNORED"
    probe.assert_clean(context="after Игнорирай")
