"""D2A browser harness: deterministic isolated fixture + external boundary substitutes.

TEST-ONLY. This module lets the Playwright suite drive the REAL production
topology (real ``npm run build`` output, real Python ``ThreadingHTTPServer``, real
``/api/v1``) without touching the repository's normal runtime stores and without
depending on live network or live providers.

Two responsibilities, and nothing else:

1. :func:`build_fixture` seeds an isolated newsroom/editorial/runtime root through
   the *canonical* stores and services (``inbox_store``, ``story_store``,
   ``story_research_store``, ``editor_article_store``, ``editor_application``), so
   every file on disk is a valid, contract-shaped store row. Nothing is
   hand-written to make a screen appear.

2. :func:`install_boundary_substitutes` replaces ONLY the three genuinely external
   edges, where production code reaches outside the process:

   * the model transport (``generate._call_gemini`` / ``_call_openrouter``),
   * the search *provider* + page *opener* (``search`` / ``web_fetch``),
   * the newsroom *collector* byte fetcher and the semantic grouping model
     (``fetcher`` / ``story_relation`` / ``newsroom_run``).

   Everything between those edges stays real: the operation registry, the real
   worker threads, the readiness and orchestration layer, the stores, the
   projections and the whole HTTP surface.

The substitution happens by monkeypatching module attributes in the test process
that also hosts the server. It is not a product test mode: no frontend code, no
``if E2E_TEST`` branch, nothing exposed in the SPA, and no change to the product
source tree.
"""

from __future__ import annotations

import json
from pathlib import Path

# --------------------------------------------------------------------------
# deterministic editorial material
# --------------------------------------------------------------------------

HEADLINE = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата"
FACT_MONEY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
FACT_PEOPLE = "Жителите на квартала ще пътуват с 10 минути повече до работата."
GAP_BLOCKING = "Кога точно започва ремонтът?"
GAP_SOFT = "Ще има ли компенсация за жителите по време на строителството?"

#: Body the generated-Draft substitute produces. It is composed only from the two
#: seeded facts, so the real C4 evidence/readiness engine sees supported claims.
SUPPORTED_BODY = (
    "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
    "Жителите на квартала ще пътуват с 10 минути повече до работата."
)

#: The complete Story's single fact, and the body derived from it. Articles on
#: that Story use this so the real validation engine has matching evidence.
CLEAN_FACT = "Общинският съвет одобри 400 000 лева за обновяване на централния парк."
CLEAN_BODY = "Града получиха средства за обновяване на централния парк."

#: D2B: how long the substituted draft provider takes. Deliberately longer than
#: the ~2-second client polling budget D2A found insufficient, so the browser
#: generation proof only passes while the hardened budget is in place. A real
#: external provider is routinely this slow or slower.
SLOW_DRAFT_PROVIDER_SECONDS = 4.0

SOURCE_ROW = {"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/2026/budget"}


def _item(
    item_id: str, title: str, *, source_id: str = "vestnik", discovered_at: str, summary: str = ""
):
    return {
        "item_id": item_id,
        "source_id": source_id,
        "source_item_id": item_id,
        "title": title,
        "url": f"https://{source_id}.example.test/{item_id}",
        "published_at": discovered_at,
        "discovered_at": discovered_at,
        "summary": summary or f"Обобщение: {title}",
        "source_kind": "media",
        "status": "NEW",
    }


# --------------------------------------------------------------------------
# fixture construction
# --------------------------------------------------------------------------


def _new_article(
    *, stories_path, editorial, story_id: str, key: str, title: str, focus: str, now: str
) -> str:
    """One Preparation Article with a confirmed focus, via the canonical store."""
    from editor_assistant.workflow import editor_article_store as articles

    article = articles.create_editor_article(
        story_id=story_id,
        stories_path=stories_path,
        working_title=title,
        now=now,
        root=editorial,
        idempotency_key=key,
    )
    articles.update_editor_focus(article["article_id"], focus, now=now, root=editorial)
    return article["article_id"]


def _release_refresh_lock(newsroom_refresh) -> None:
    """Leave no collection lock behind between fixture builds."""
    token = newsroom_refresh.active_token()
    if token:
        newsroom_refresh.release(token)


def build_fixture(*, newsroom: Path, editorial: Path) -> dict:
    """Seed every required Story/Article state into an isolated store root.

    The caller has already pointed the ``WB_*`` environment variables at
    ``newsroom``/``editorial``. Returns the ids the browser suite navigates to.
    """
    from editor_assistant.workflow import editor_application as app
    from editor_assistant.workflow import editor_article_store as articles
    from editor_assistant.workflow import (
        inbox_store,
        newsroom_refresh,
        sources_registry,
        story_operations,
        story_research_store,
        story_store,
    )
    from editor_assistant.workflow import story_editor_metadata as metadata

    newsroom.mkdir(parents=True, exist_ok=True)
    editorial.mkdir(parents=True, exist_ok=True)
    stories_path = newsroom / "stories.json"
    inbox_path = newsroom / "inbox.jsonl"

    _release_refresh_lock(newsroom_refresh)

    # ---- canonical raw material --------------------------------------------
    main_origin = _item("d2a-main-origin", HEADLINE, discovered_at="2026-09-25T08:00:00Z")
    main_dev = _item(
        "d2a-main-dev", "Ремонтът започва през октомври", discovered_at="2026-09-25T09:00:00Z"
    )
    ignored_origin = _item(
        "d2a-ignored-origin",
        "Информация без редакционно значение",
        source_id="dneshnie",
        discovered_at="2026-09-25T08:30:00Z",
    )
    new_origin = _item(
        "d2a-new-origin", "Нова история за преглед", discovered_at="2026-09-25T10:00:00Z"
    )
    # A separate, complete Story: its basis has no blocking gap, so an Article on
    # it can legitimately reach the Ready checkpoint and the Archive. The
    # representative Story keeps its blocking gap on purpose - that is what makes
    # «Проучи още» available in the browser.
    clean_origin = _item(
        "d2a-clean-origin",
        "Приет е бюджетът за парка в центъра",
        source_id="vestnik",
        discovered_at="2026-09-25T07:00:00Z",
    )
    inbox_store.save_items(
        [main_origin, main_dev, ignored_origin, new_origin, clean_origin], inbox_path
    )

    # ---- Stories ------------------------------------------------------------
    # Representative Story: followed, with an unreviewed development, facts and
    # sources, one blocking gap and one soft gap.
    main = story_store.new_story(main_origin, now="2026-09-25T08:00:00Z")
    main["story_id"] = "s-d2a-main"
    main["status"] = "SEEN"
    story_store.add_member(
        main,
        main_dev,
        relation="NEW_DEVELOPMENT",
        relation_source="deterministic",
        now="2026-09-25T09:00:00Z",
    )
    main["status"] = "SEEN"

    ignored = story_store.new_story(ignored_origin, now="2026-09-25T08:30:00Z")
    ignored["story_id"] = "s-d2a-ignored"
    ignored["status"] = "IGNORED"

    fresh = story_store.new_story(new_origin, now="2026-09-25T10:00:00Z")
    fresh["story_id"] = "s-d2a-new"
    fresh["status"] = "NEW"

    clean = story_store.new_story(clean_origin, now="2026-09-25T07:00:00Z")
    clean["story_id"] = "s-d2a-clean"
    clean["status"] = "SEEN"

    story_store.write_store({"stories": [main, ignored, fresh, clean]}, stories_path)

    metadata.set_story_followed("s-d2a-main", True, stories_path=stories_path, root=newsroom)
    metadata.set_story_followed("s-d2a-new", True, stories_path=stories_path, root=newsroom)
    # Record the representative Story as reviewed *before* the browser session, so
    # `Прегледай` is exercised on a different Story than the workspace assertions.
    metadata.review_story_developments(
        "s-d2a-main",
        [],
        stories_path=stories_path,
        inbox_path=inbox_path,
        now="2026-09-25T09:30:00Z",
        root=newsroom,
    )

    story_research_store.merge_research(
        "s-d2a-main",
        sources=[SOURCE_ROW],
        facts=[
            {
                "id": "fact_money",
                "text": FACT_MONEY,
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": FACT_PEOPLE,
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
        ],
        gaps=[
            {"id": "gap_when", "question": GAP_BLOCKING, "blocking": True},
            {"id": "gap_comp", "question": GAP_SOFT, "blocking": False},
        ],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-d2a-main"},
        operation_id="d2a-seed",
    )
    story_research_store.merge_research(
        "s-d2a-ignored",
        sources=[{"id": "dneshnie", "name": "Днешни", "url": "https://dneshnie.example.test/a"}],
        facts=[],
        gaps=[{"id": "gap_ignored", "question": GAP_SOFT, "blocking": False}],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-d2a-ignored"},
        operation_id="d2a-seed-ignored",
    )

    story_research_store.merge_research(
        "s-d2a-clean",
        sources=[
            {"id": "bta", "name": "БТА", "url": "https://bta.example.test/park"},
            {"id": "gradona", "name": "Градона", "url": "https://gradona.example.test/park"},
        ],
        facts=[
            {
                "id": "fact_park",
                "text": CLEAN_FACT,
                "sourceId": "bta",
                "locator": "Решение 118",
            },
            {
                "id": "fact_park_term",
                "text": "Срокът за изпълнение е краят на октомври тази година.",
                "sourceId": "gradona",
                "locator": "Репортаж, т. 2",
            },
            {
                # A reader-value depth fact. The real readiness engine classifies a
                # bare announcement as RESEARCH_MORE and would refuse to draft, so
                # the fixture must carry the same depth a real assessed Story has.
                "id": "fact_park_who",
                "text": "Жителите от централния квартал ще имат нов детски кът и осветление.",
                "sourceId": "gradona",
                "locator": "Репортаж, т. 3",
            },
        ],
        gaps=[],
        assessed_at="2026-09-25T07:30:00Z",
        canonical_story={"story_id": "s-d2a-clean"},
        operation_id="d2a-seed-clean",
    )

    ids = {
        "newsroom": newsroom,
        "editorial": editorial,
        "stories_path": stories_path,
        "inbox_path": inbox_path,
        "story_id": "s-d2a-main",
        "story_ignored_id": "s-d2a-ignored",
        "story_new_id": "s-d2a-new",
    }

    # ---- Articles -----------------------------------------------------------
    # Every mutable Article gets its own row, so no browser test can be broken by
    # another one having already advanced the same Article. The mutable Articles
    # live on the complete Story: its research basis has no blocking gap, so
    # «Направи чернова» is legitimately offered and the real generation
    # orchestration can run. The representative Story keeps its blocking gap on
    # purpose: that is what makes «Проучи още» available.
    preparation = _new_article(
        stories_path=stories_path,
        editorial=editorial,
        story_id="s-d2a-clean",
        key="d2a-preparation",
        title="Ремонтът на улицата тръгна през октомври",
        focus="Да обясним решението на съвета и какво значи то за жителите.",
        now="2026-09-25T09:00:00Z",
    )
    ids["preparation_article_id"] = preparation

    # D2B: a dedicated Preparation Article for the slow-generation proof, so the
    # §17 draft test above keeps its own row and the two can never interfere.
    slow_draft = _new_article(
        stories_path=stories_path,
        editorial=editorial,
        story_id="s-d2a-clean",
        key="d2a-slow-draft",
        title="Бавно създадена чернова за проверка на изчакването",
        focus="Да се покаже, че бавното създаване не се обявява за провал.",
        now="2026-09-25T09:01:00Z",
    )
    ids["slow_draft_article_id"] = slow_draft

    # A second Preparation Article, so the §16 title/focus proof never consumes
    # the row the §17 generation proof needs.
    focus_only = _new_article(
        stories_path=stories_path,
        editorial=editorial,
        story_id="s-d2a-clean",
        key="d2a-focus",
        title="Работно заглавие за проверка",
        focus="Първоначално потвърден фокус.",
        now="2026-09-25T09:02:00Z",
    )
    ids["focus_article_id"] = focus_only

    # A third Preparation Article, used by the §22 finalization proof, which needs
    # to reach Готова through the browser itself.
    lifecycle = _new_article(
        stories_path=stories_path,
        editorial=editorial,
        story_id="s-d2a-clean",
        key="d2a-lifecycle",
        title="Обновяването на парка започва през октомври",
        focus="Да разкажем срока и защо е важен за жителите.",
        now="2026-09-25T09:03:00Z",
    )
    ids["lifecycle_article_id"] = lifecycle

    # Manual Draft: Preparation -> Редактирай -> manual body (the light path, §23).
    # The body is composed from the complete Story's own fact, so the real C4
    # evidence engine sees supported claims and `Чернова` is a truthful state.
    manual = articles.create_editor_article(
        story_id="s-d2a-clean",
        stories_path=stories_path,
        working_title="Ръчно написана чернова за парка",
        now="2026-09-25T09:05:00Z",
        root=editorial,
        idempotency_key="d2a-manual",
    )
    articles.update_editor_focus(
        manual["article_id"],
        "Да разкажем какво предстои за парка в центъра.",
        now="2026-09-25T09:06:00Z",
        root=editorial,
    )
    articles.save_article_content(
        manual["article_id"],
        0,
        "Ръчно написана чернова за парка",
        CLEAN_BODY,
        now="2026-09-25T09:07:00Z",
        root=editorial,
    )
    # A fourth Preparation Article for the deep-link and refresh proofs, so those
    # never depend on an Article another test has already advanced.
    deep_link = _new_article(
        stories_path=stories_path,
        editorial=editorial,
        story_id="s-d2a-clean",
        key="d2a-deeplink",
        title="Материал за директен адрес",
        focus="Да проверим директното отваряне на адрес.",
        now="2026-09-25T09:04:00Z",
    )
    ids["deep_link_article_id"] = deep_link

    # A fourth manual Draft, kept for the back/forward proof so the Article a
    # navigation test follows is never renamed by an editing test.
    related = _new_article(
        stories_path=stories_path,
        editorial=editorial,
        story_id="s-d2a-main",
        key="d2a-related",
        title="Свързана статия за навигация",
        focus="Да разкажем връзката с историята.",
        now="2026-09-25T09:08:00Z",
    )
    articles.save_article_content(
        related,
        0,
        "Свързана статия за навигация",
        CLEAN_BODY,
        now="2026-09-25T09:09:00Z",
        root=editorial,
    )
    ids["related_article_id"] = related

    # V1.1-C: a fresh Preparation Article on the complete Story, kept purely for
    # the manual-continuation proof. It must start in Preparation, because the
    # recovery editor is offered only after a genuine generation failure, and it
    # must be eligible, so the failure can really happen at the provider.
    continuation = _new_article(
        stories_path=stories_path,
        editorial=editorial,
        story_id="s-d2a-clean",
        key="d2a-continuation",
        title="Обновяването на парка — ръчно продължение",
        focus="Да разкажем какво предстои за парка в центъра.",
        now="2026-09-25T09:11:00Z",
    )
    ids["continuation_article_id"] = continuation

    ids["manual_article_id"] = manual["article_id"]

    # Finalized Archive Article: the read-only archived surface (§22, §24, §25).
    # It lives on the complete Story, whose basis has no blocking gap, so the
    # real readiness engine and the real finalization digest check both pass.
    archived = articles.create_editor_article(
        story_id="s-d2a-clean",
        stories_path=stories_path,
        working_title="Приет бюджет за обновяване на парка",
        now="2026-09-25T09:10:00Z",
        root=editorial,
        idempotency_key="d2a-archived",
    )
    articles.update_editor_focus(
        archived["article_id"],
        "Да документираме приетото решение за парка.",
        now="2026-09-25T09:11:00Z",
        root=editorial,
    )
    articles.save_article_content(
        archived["article_id"],
        0,
        "Приет бюджет за обновяване на парка",
        CLEAN_BODY,
        now="2026-09-25T09:12:00Z",
        root=editorial,
    )
    # Readiness and finalization go through the real application commands, so the
    # C4 validation engine and the C5 digest re-check both really execute.
    app.mark_article_ready(archived["article_id"], 1)
    app.finalize_article(archived["article_id"], 1, idempotency_key="d2a-archive")
    ids["archived_article_id"] = archived["article_id"]

    # A Ready Article: a real `Готова` checkpoint, for the Ready workspace, the
    # Ready -> Edit transition and the §20/§21 assertions.
    ready = articles.create_editor_article(
        story_id="s-d2a-clean",
        stories_path=stories_path,
        working_title="Кога ще започне обновяването на парка",
        now="2026-09-25T09:20:00Z",
        root=editorial,
        idempotency_key="d2a-ready",
    )
    articles.update_editor_focus(
        ready["article_id"],
        "Да отговорим на въпроса със сроковете.",
        now="2026-09-25T09:21:00Z",
        root=editorial,
    )
    articles.save_article_content(
        ready["article_id"],
        0,
        "Кога ще започне обновяването на парка",
        CLEAN_BODY,
        now="2026-09-25T09:22:00Z",
        root=editorial,
    )
    app.mark_article_ready(ready["article_id"], 1)
    ids["ready_article_id"] = ready["article_id"]

    story_operations.clear()

    # One active RSS source, so the real «Обнови» capability check passes. The
    # collector's bytes are substituted at the fetch boundary; the parser, dedup,
    # ingestion, identity grouping and health records are the real ones.
    sources_registry.add_source(
        path=newsroom / "sources.json",
        source_id="d2a-vestnik",
        name="Д2А тестов емисион",
        kind="official",
        collector="rss",
        url="https://vestnik.example.test/rss.xml",
        priority="high",
        factual_authority=True,
    )

    return ids


# --------------------------------------------------------------------------
# V1.1-D1 fixture: a Today screen with real shape
# --------------------------------------------------------------------------


def build_today_fixture(*, newsroom: Path, editorial: Path) -> dict:
    """Seed the D1 shape: a large stale backlog, a small current set, work.

    This exists because the *interesting* Today is the one the real corpus
    produced: far more `NEW` Stories than an editor can act on, almost all of
    them days old. A fixture with three tidy current Stories cannot show
    whether the horizon, the cap or the ordering actually work.

    Timestamps are derived from the real clock, not hard-coded, because the
    horizon is defined against the current `Europe/Sofia` date. A hard-coded
    fixture date would silently stop testing anything the day after it was
    written.
    """
    from datetime import datetime, timedelta, timezone

    from editor_assistant.workflow import editor_article_store as articles
    from editor_assistant.workflow import (
        inbox_store,
        newsroom_refresh,
        sources_registry,
        story_operations,
        story_store,
    )

    newsroom.mkdir(parents=True, exist_ok=True)
    editorial.mkdir(parents=True, exist_ok=True)
    stories_path = newsroom / "stories.json"
    inbox_path = newsroom / "inbox.jsonl"
    _release_refresh_lock(newsroom_refresh)

    now = datetime.now(timezone.utc)

    def stamp(**delta) -> str:
        return (now - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")

    STALE = 120  # untouched backlog, far outside the horizon
    CURRENT = 25  # what an editor can actually scan

    items = []
    stories = []

    def add(story_id: str, when: str, title: str) -> None:
        item = _item(f"{story_id}-origin", title, discovered_at=when)
        items.append(item)
        story = story_store.new_story(item, publication_key=f"pk-{story_id}", now=when)
        story["story_id"] = story_id
        story["status"] = "NEW"
        stories.append(story)

    for index in range(STALE):
        add(f"s-d1-stale-{index:03d}", stamp(days=9 + index // 20), f"Стара история {index}")

    for index in range(CURRENT):
        # Ids are scrambled against time on purpose, so a page that ordered by
        # id would look obviously wrong in the rendered sequence.
        suffix = f"{(index * 613) % CURRENT:03d}"
        add(f"s-d1-now-{suffix}", stamp(minutes=25 * index), f"Текуща история {suffix}")

    inbox_store.save_items(items, inbox_path)
    story_store.write_store({"stories": stories}, stories_path)

    # A Draft Article on a current Story, so Article attention is present and
    # the proof can show that Story volume does not displace it.
    draft = articles.create_editor_article(
        story_id="s-d1-now-000",
        stories_path=stories_path,
        working_title="Работа по текущата история",
        now=stamp(minutes=5),
        root=editorial,
        idempotency_key="d1-draft",
    )
    articles.update_editor_focus(
        draft["article_id"],
        "Да разкажем какво предстои по темата.",
        now=stamp(minutes=4),
        root=editorial,
    )
    articles.save_article_content(
        draft["article_id"],
        0,
        "Работа по текущата история",
        CLEAN_BODY,
        now=stamp(minutes=3),
        root=editorial,
    )

    story_operations.clear()

    sources_registry.add_source(
        path=newsroom / "sources.json",
        source_id="d1-vestnik",
        name="Д1 тестов емисион",
        kind="official",
        collector="rss",
        url="https://vestnik.example.test/rss.xml",
        priority="high",
        factual_authority=True,
    )

    # A completed run, so the refresh line has something true to say.
    from editor_assistant.workflow import source_health

    source_health.record_run(
        {
            "finished_at": stamp(hours=2),
            "started_at": stamp(hours=2, minutes=1),
            "collected": 157,
            "new": 37,
            "duplicate": 120,
            "failed": 0,
            "blocked": 0,
            "blocked_filtered": 0,
            "sources": [{"source_id": "d1-vestnik", "status": "OK"}],
        },
        path=newsroom / "last_run.json",
    )
    source_health.record_run_stories(12, path=newsroom / "last_run.json")

    return {
        "newsroom": newsroom,
        "editorial": editorial,
        "stories_path": stories_path,
        "draft_article_id": draft["article_id"],
        "stale_count": STALE,
        "current_count": CURRENT,
    }


# --------------------------------------------------------------------------
# external boundary substitutes
# --------------------------------------------------------------------------


def install_boundary_substitutes(monkeypatch) -> None:
    """Substitute only the three outbound edges. Everything between stays real."""
    import time

    from editor_assistant.drafting import generate as gen
    from editor_assistant.sources import fetcher, web_fetch
    from editor_assistant.workflow import newsroom_run, search

    # -- 1. model transport: the only outbound call for drafting, the semantic
    #       story grouping and the claim judge. `generate.call_model` routes
    #       through the real role policy/router, which then reaches this seam.
    #
    # D2B: the *draft* role deliberately takes longer than the old 2-second client
    # polling budget. A real external provider does, and that is exactly the
    # condition the previous budget mishandled: the operation was still correctly
    # running while the UI already declared the Draft lost. The substitute models
    # that realistic latency, so this suite fails if the fix is ever reverted.
    def fake_call_gemini(prompt_text, *, api_key="", timeout=0, role="draft", **_kw):
        if role == "draft":
            time.sleep(SLOW_DRAFT_PROVIDER_SECONDS)
        return _model_answer(role), {"model": "d2a-substitute", "provider": "substitute"}

    def fake_call_openrouter(prompt_text, *, api_key="", timeout=0, model="", **_kw):
        time.sleep(SLOW_DRAFT_PROVIDER_SECONDS)
        return _model_answer("draft"), {"model": "d2a-substitute"}

    monkeypatch.setattr(gen, "_call_gemini", fake_call_gemini)
    monkeypatch.setattr(gen, "_call_openrouter", fake_call_openrouter)

    # -- 2. search provider + page opener, for «Проучи още».
    class _DeterministicProvider:
        name = "d2a_deterministic"

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
                "results": [
                    {
                        "rank": 1,
                        "title": "Общинският съвет обсъди бюджета за ремонта",
                        "url": "https://vestnik.example.test/2026/budget-detail",
                        "snippet": "Решението беше гласувано на заседание.",
                        "published_at": "",
                        "source_name": "vestnik",
                    }
                ],
            }

    monkeypatch.setattr(
        search,
        "provider_chain",
        lambda capability=search.CAP_WEB, env=None: ([_DeterministicProvider()], []),
    )

    def fake_fetch_page(url, **_kw):
        text = (
            "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
            "Жителите на квартала ще пътуват с 10 минути повече до работата. "
            "Ремонтът започва през октомври, след като приключат подготвителните работи."
        )
        return {
            "final_url": url,
            "content_type": "text/html; charset=utf-8",
            "bytes": len(text),
            "text": text,
        }

    monkeypatch.setattr(web_fetch, "fetch_page", fake_fetch_page)

    # -- 3. newsroom collector bytes, for «Обнови». The real RSS parser, dedup,
    #       inbox ingestion, identity grouping and health records all still run.
    def fake_fetch_bytes(url):
        from editor_assistant.sources.fetcher import FetchedResponse

        return FetchedResponse(
            final_url=url,
            status=200,
            content_type="application/rss+xml",
            payload=_deterministic_feed(),
        )

    monkeypatch.setattr(fetcher, "fetch_bytes", fake_fetch_bytes)

    # The collector clock is pinned so a refresh is reproducible and its
    # recency window never depends on the wall clock.
    monkeypatch.setattr(newsroom_run, "_now", _fixed_now)


def _fixed_now():
    from datetime import datetime, timezone

    return datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _model_answer(role: str) -> str:
    """The minimal well-formed payload each model role expects."""
    if role == "story":
        return json.dumps(
            {
                "same_event": True,
                "relation": "NEW_DEVELOPMENT",
                "material_change": True,
                "shared_anchors": ["общински съвет", "ремонт"],
                "reason": "d2a deterministic grouping",
            },
            ensure_ascii=False,
        )
    if role in {"judge", "verify", "claim"}:
        return json.dumps(
            {
                "sentence": CLEAN_BODY,
                "verdict": "SUPPORTED",
                "issue": "none",
                "supporting_fact_ids": ["fact_money", "fact_people"],
                "note": "d2a deterministic judgement",
            },
            ensure_ascii=False,
        )
    # The draft role: the frozen contract expects a JSON object with a headline
    # and a body composed from the seeded evidence.
    return json.dumps(
        {"headline": HEADLINE, "headlines": [HEADLINE], "body": CLEAN_BODY},
        ensure_ascii=False,
    )


def _deterministic_feed() -> bytes:
    """A minimal, valid RSS payload for the newsroom collector substitute."""
    items = [
        ("d2a-refresh-a", "Съветът обсъди ремонта на улицата"),
        ("d2a-refresh-b", "Жителите питат за срока на ремонта"),
    ]
    body = "".join(
        f"<item><title>{title}</title>"
        f"<link>https://vestnik.example.test/{slug}</link>"
        f"<pubDate>Fri, 25 Sep 2026 11:30:00 +0300</pubDate>"
        f"<description>Материал от източника за обновяването на новините.</description>"
        f"</item>"
        for slug, title in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Тестова емисия</title><link>https://vestnik.example.test/</link>"
        f"{body}</channel></rss>"
    ).encode()
