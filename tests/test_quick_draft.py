"""V1.1-D2 — Today fast triage + Quick Draft.

The product promise under test is one sentence: from Today, one click on
`Чернова` takes an experienced editor to a real Draft, with no intermediate
navigation, and when the canonical path cannot safely succeed it produces one
truthful sentence instead of a bad Draft.

**What is deliberately NOT stubbed.** Every test here runs the real
orchestration, the real research executor, the real `article_readiness`
decision, the real C2 generation pipeline and the real V1.1-C failure marker.
Only the three genuinely external edges are substituted — the search provider,
the page opener and the model transport — exactly as the V1.1-A/B/C suites do.
That is the whole point of the non-negotiable safety rule: Quick Draft must
reuse the canonical machinery, so a test that stubs the machinery would prove
nothing about it.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.sources import web_fetch
from editor_assistant.workflow import (
    article_draft_failure,
    article_generation,
    article_readiness,
    blocked_domains,
    inbox_store,
    quick_draft,
    story_operations,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import (
    editor_article_store as articles,
)
from editor_assistant.workflow import (
    search as search_mod,
)

HEADLINE = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата"
BODY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
SECOND_FACT = "Жителите на квартала ще пътуват с 10 минути повече до работа."
THIRD_FACT = "Следващата сесия на съвета ще обсъди графика за следващата улица."
SOURCE_URL = "https://vestnik.example.test/protokol"
STORY_TITLE = HEADLINE


def _item(item_id: str, title: str):
    return {
        "item_id": item_id,
        "source_id": "vestnik",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://vestnik.example.test/{item_id}",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": "Обобщение",
        "source_kind": "media",
        "status": "NEW",
    }


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
    """An isolated newsroom + editorial root; nothing outside tmp_path is touched."""
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    inbox_store.save_items([_item("origin", STORY_TITLE)], root / "inbox.jsonl")
    story = story_store.new_story(_item("origin", STORY_TITLE), now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    story_operations.clear()
    yield root
    story_operations.clear()
    for key in list(article_generation._ACTIVE):
        article_generation.release(key, article_generation._ACTIVE[key])
    for key in list(quick_draft._ACTIVE):
        quick_draft.release(key, quick_draft._ACTIVE[key])


@pytest.fixture
def api_server(newsroom):
    """The real production HTTP server over the isolated store roots.

    Same `http.serve` the editor uses, so the route, the Idempotency-Key
    handling and the operation registry are all exercised for real.
    """
    from editor_assistant.workflow.workbench import http

    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(base, path, *, method="GET", body=None, headers=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _data(result):
    """The `data` envelope of a `(status, payload)` pair."""
    _, payload = result
    assert "data" in payload, payload
    return payload["data"]


def _await_http(base, token, *, attempts: int = 900):
    """Poll the bounded operation exactly as the editor's client does."""
    for _ in range(attempts):
        result = _request(base, f"/api/v1/operations/{token}")
        assert result[0] == 200, result[1]
        operation = _data(result)
        if operation["status"] in {"succeeded", "failed"}:
            return operation
        time.sleep(0.02)
    raise AssertionError("the operation did not settle")


def _articles_on_disk() -> list[dict]:
    return articles.read_editor_articles()


# ---------------------------------------------------------------- boundaries
# Only the genuinely external edges. Everything between them is the product.


#: The one sentence every substituted page carries.
#:
#: It is not arbitrary. The real research executor extracts exactly ONE claim per
#: opened page (the first sentence answering a bootstrap question), and the claim
#: is only promoted to a fact when it is PRIMARY or corroborated by two
#: independent opened domains. So the substitute gives two different hosts the
#: SAME sentence, and that sentence names both what happened and who it affects -
#: which is what a real source page about a municipal decision actually says.
CONFIRMED_CLAIM = (
    "Ремонтът започва на 1 октомври 2026 г., а жителите на квартала ще пътуват повече, "
    "потвърдиха от общинският съвет на грата."
)


def substitute_research_network(monkeypatch, *, results: bool = True) -> list[str]:
    """Substitute ONLY the two external edges of the real research executor.

    The search *provider* and the page *opener* are where a real deployment
    leaves the process. The executor, the bootstrap question planner, the
    sufficiency assessment, the corroboration rule, the fact and gap projection,
    the canonical research store and the whole application layer stay the
    product's - which is what makes §33 worth asserting at all.

    Returns the list of URLs the executor actually opened, so a test can assert
    that a real research round really happened.
    """
    opened: list[str] = []
    pages = {
        "https://source-a.example.test/a": CONFIRMED_CLAIM,
        "https://source-b.example.test/b": CONFIRMED_CLAIM,
        "https://source-c.example.test/c": CONFIRMED_CLAIM,
    }

    class Provider:
        name = "fake"

        def search(self, query):
            if not results:
                return {"provider": "fake", "query": query, "status": "NO_RESULTS", "results": []}
            return {
                "provider": "fake",
                "query": query,
                "status": "SEARCH_OK",
                "results": [
                    {"rank": index + 1, "title": f"Източник {index}", "url": url, "snippet": "s"}
                    for index, url in enumerate(pages)
                ],
            }

    def fetch_page(url, **_kwargs):
        opened.append(url)
        text = pages.get(url, CONFIRMED_CLAIM)
        return {
            "url": url,
            "final_url": url,
            "status": 200,
            "content_type": "text/html; charset=utf-8",
            "bytes": len(text),
            "text": text,
        }

    monkeypatch.setattr(
        search_mod, "provider_chain", lambda capability=None, env=None: ([Provider()], [])
    )
    monkeypatch.setattr(web_fetch, "fetch_page", fetch_page)
    _SUBSTITUTE_PROVIDER[0] = Provider()
    _SUBSTITUTE_OPENER[0] = fetch_page
    return opened


def install_working_model(monkeypatch) -> None:
    """The only success stub on the generation side: the model transport.

    Every gate between the command and this call — readiness, the evidence
    packet, the angle gate, the factual and originality audits — is real.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def call(prompt_text, *, api_key, timeout, role="draft", **_kw):
        if role == "draft":
            return (
                json.dumps(
                    {
                        "headlines": [HEADLINE],
                        "headline": HEADLINE,
                        "body": BODY + " Първа стъпка.",
                    },
                    ensure_ascii=False,
                ),
                {"model": "mock", "provider": "gemini"},
            )
        return (
            json.dumps(
                {
                    "sentence": BODY,
                    "verdict": "SUPPORTED",
                    "issue": "none",
                    "supporting_fact_ids": [],
                    "note": "ok",
                }
            ),
            {"model": "mock"},
        )

    monkeypatch.setattr(gen, "_call_gemini", call)


@pytest.fixture
def working_model(monkeypatch):
    install_working_model(monkeypatch)


def break_draft_provider(monkeypatch) -> list[str]:
    """Fail only the DRAFT model role — the real generation boundary."""
    entered: list[str] = []
    install_working_model(monkeypatch)
    working = gen._call_gemini

    def call(prompt_text, *, api_key, timeout, role="draft", **kwargs):
        if role == "draft":
            entered.append(role)
            raise RuntimeError("provider transport is down")
        return working(prompt_text, api_key=api_key, timeout=timeout, role=role, **kwargs)

    monkeypatch.setattr(gen, "_call_gemini", call)
    return entered


def research_round(newsroom, *, facts=None, gaps=None, blocking=True, sources=None):
    """Persist one canonical research outcome, exactly as the executor does."""
    return story_research_store.merge_research(
        "s-one",
        sources=sources
        if sources is not None
        else [{"id": "vestnik", "name": "Вестник", "url": SOURCE_URL}],
        facts=facts
        if facts is not None
        else [
            {"id": "fact_money", "text": BODY, "sourceId": "vestnik", "locator": "т. 4"},
            {"id": "fact_people", "text": SECOND_FACT, "sourceId": "vestnik", "locator": "т. 5"},
            {"id": "fact_next", "text": THIRD_FACT, "sourceId": "vestnik", "locator": "т. 6"},
        ],
        gaps=gaps
        if gaps is not None
        else (
            [
                {
                    "id": "gap_when",
                    "question": "Кога започва?",
                    "kind": "unresolved",
                    "blocking": blocking,
                }
            ]
            if blocking
            else []
        ),
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="fixture-round",
        # Exactly as the real executor persists a completed round: the cap is
        # enforced against this counter, so a fixture that left it at 0 would
        # silently grant the Story extra research it never had.
        count_round=True,
        replace_gaps=True,
    )


def make_sufficient(newsroom):
    """An assessed Story whose evidence genuinely satisfies the real gates."""
    research_round(newsroom, gaps=[])
    return app.read_story("s-one")


def await_operation(token: str) -> dict:
    """Wait for one bounded operation to settle, the way the editor's poll does."""
    for _ in range(900):
        row = story_operations.get(token)
        if row and row["status"] in {"succeeded", "failed"}:
            return row
        time.sleep(0.02)
    raise AssertionError("the operation did not finish")


def _route_research_edges(monkeypatch) -> None:
    """Hand the substituted provider and opener to the canonical research call.

    `research_story` already accepts `provider` and `page_opener` - the same two
    seams the ordinary «Проучи още» command exposes. Routing them here changes no
    product behaviour: Quick Draft still calls the one `research_story`, and the
    test simply substitutes the two edges that live outside the process.
    """
    real = app.research_story

    def routed(story_id, *, provider=None, page_opener=None, now=None):
        return real(
            story_id,
            provider=provider or _SUBSTITUTE_PROVIDER[0],
            page_opener=page_opener or _SUBSTITUTE_OPENER[0],
            now=now,
        )

    monkeypatch.setattr(app, "research_story", routed)


#: Filled in by :func:`substitute_research_network`.
_SUBSTITUTE_PROVIDER: list = [None]
_SUBSTITUTE_OPENER: list = [None]


def run_quick(story_id: str = "s-one", key: str = "click-1") -> dict:
    """Start the real Quick Draft operation and wait for it to settle."""
    return await_operation(app.start_quick_draft(story_id, idempotency_key=key)["operationToken"])


def _rows(name: str) -> list[dict]:
    path = Path(app._editorial_root()) / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def articles_for(story_id: str = "s-one") -> list[dict]:
    return [row for row in articles.read_editor_articles() if row["story_id"] == story_id]


def all_articles() -> list[dict]:
    return articles.read_editor_articles()


# ------------------------------------------------------------------ §33
# UNASSESSED HAPPY PATH — the whole product promise, end to end


def test_unassessed_story_researches_then_produces_exactly_one_draft(
    newsroom, monkeypatch, working_model
):
    """§33 — one click on an unassessed Story produces a real Draft.

    The full canonical sequence runs for real: the V1.1-A first research round,
    Article creation, the quick Focus, the V1.1-B readiness decision and the C2
    generation pipeline. Only the two research network edges and the model
    transport are substituted.
    """
    opened = substitute_research_network(monkeypatch)
    _route_research_edges(monkeypatch)

    row = run_quick()

    assert row["status"] == "succeeded", row
    assert opened, "the real research executor must have opened a real page"
    created = articles_for()
    assert len(created) == 1
    assert row["result"] == {
        "status": quick_draft.DRAFT_CREATED,
        "articleId": created[0]["article_id"],
    }
    # One Story, one Article, one research basis, one generation — and every
    # write landed in the same canonical stores the ordinary path uses.
    assert len(story_store.read_store(newsroom / "stories.json")["stories"]) == 1
    assert len(created) == 1
    basis = story_research_store.get_story_research("s-one")
    assert basis["research_rounds"] == 1
    assert story_research_store.evidence_status_of(basis) == story_research_store.EVIDENCE_ASSESSED
    article_id = created[0]["article_id"]
    # The C2 pipeline really ran: an internal Case and a published body.
    assert _rows("cases.jsonl"), "the C2 pipeline must have produced a real Case"
    assert articles.get_editor_article(article_id)["internal_refs"]["case_id"]
    assert articles.get_article_content(article_id)["body"].strip()
    assert app.read_article(article_id)["state"] == "draft"


# ------------------------------------------------------------------ §35
# ALREADY ASSESSED — the cheapest path, and it must stay cheap


def test_an_already_assessed_story_is_not_researched_again(newsroom, monkeypatch, working_model):
    """§35 — sufficient evidence means no second research round, ever."""
    make_sufficient(newsroom)

    def explode(*_args, **_kwargs):
        raise AssertionError("Quick Draft must not research an already sufficient Story")

    monkeypatch.setattr(app, "research_story", explode)
    before = len(_rows("cases.jsonl"))

    row = run_quick(key="fast-path")

    assert row["status"] == "succeeded", row
    assert row["result"]["status"] == quick_draft.DRAFT_CREATED
    # One research round was already on the basis; the quick path added none.
    assert story_research_store.get_story_research("s-one")["research_rounds"] == 1
    assert len(articles_for()) == 1
    assert len(_rows("cases.jsonl")) == before + 1, "exactly one generation"


# ------------------------------------------------------------------ §36
# EXISTING PREPARATION ARTICLE


def test_an_existing_preparation_article_is_reused_and_never_duplicated(
    newsroom, monkeypatch, working_model
):
    """§36 — reuse, keep the editor's confirmed Focus, generate once."""
    make_sufficient(newsroom)
    existing = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        editorial_focus="Да обясним решението и какво променя за жителите.",
        now="2026-09-25T09:00:00Z",
    )
    article_id = existing["article_id"]
    articles.update_editor_focus(article_id, "Да обясним решението и какво променя за жителите.")

    row = run_quick(key="reuse")

    assert row["status"] == "succeeded", row
    assert row["result"] == {
        "status": quick_draft.DRAFT_CREATED,
        "articleId": article_id,
    }
    assert [record["article_id"] for record in articles_for()] == [article_id]
    # §14: a confirmed editor Focus is preserved byte-for-byte.
    stored = articles.get_editor_article(article_id)
    assert stored["editorial_focus"] == "Да обясним решението и какво променя за жителите."
    assert app.read_article(article_id)["state"] == "draft"


def test_an_unconfirmed_focus_receives_the_quick_straight_news_focus(
    newsroom, monkeypatch, working_model
):
    """§36/§13 — the quick Focus only fills the gap the editor left."""
    make_sufficient(newsroom)
    existing = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        now="2026-09-25T09:00:00Z",
    )
    article_id = existing["article_id"]
    assert articles.get_editor_article(article_id)["focus_confirmed_at"] is None

    row = run_quick(key="quick-focus")

    assert row["status"] == "succeeded", row
    focus = articles.get_editor_article(article_id)["editorial_focus"]
    assert focus == quick_draft.default_focus(STORY_TITLE)
    # §42: Story-specific, confirmed, and NOT the old V1 generic placeholder.
    assert STORY_TITLE in focus
    assert articles.get_editor_article(article_id)["focus_confirmed_at"]
    assert "Да разкажем какво се е променило" not in focus
    assert app.read_article(article_id)["state"] == "draft"


# ------------------------------------------------------------------ §37
# EXISTING DRAFT / READY — never regenerate


def test_an_existing_draft_is_returned_without_regenerating(newsroom, monkeypatch, working_model):
    """§37 — a unique existing Draft is the destination; nothing is regenerated."""
    make_sufficient(newsroom)
    created = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        editorial_focus="Да обясним решението и какво променя за жителите.",
        now="2026-09-25T09:00:00Z",
    )
    article_id = created["article_id"]
    articles.update_editor_focus(article_id, "Да обясним решението и както променя за жителите.")
    started = app.start_article_draft(article_id, idempotency_key="first-real-draft")
    await_operation(started["operationToken"])
    assert app.read_article(article_id)["state"] == "draft"
    cases_before = len(_rows("cases.jsonl"))

    def explode(*_args, **_kwargs):
        raise AssertionError("an existing Draft must never be regenerated")

    monkeypatch.setattr(app, "_run_draft_generation", explode)
    row = run_quick(key="already-drafted")

    assert row["status"] == "succeeded", row
    assert row["result"] == {
        "status": quick_draft.EXISTING_ARTICLE,
        "articleId": article_id,
    }
    assert len(articles_for()) == 1
    assert len(_rows("cases.jsonl")) == cases_before


# ------------------------------------------------------------------ §34
# GAP PATH — an honest stop, and nothing left behind


def test_research_that_finds_nothing_stops_without_creating_an_article(
    newsroom, monkeypatch, working_model
):
    """§34/§10 — an insufficient Story leaves no empty Preparation Article."""
    substitute_research_network(monkeypatch, results=False)
    _route_research_edges(monkeypatch)

    def explode(*_args, **_kwargs):
        raise AssertionError("no generation may be attempted without sufficient evidence")

    monkeypatch.setattr(app, "_run_draft_generation", explode)
    row = run_quick(key="blocked")

    assert row["status"] == "succeeded", row
    result = row["result"]
    assert result["status"] == quick_draft.NEEDS_ATTENTION
    assert result["storyId"] == "s-one"
    assert result["reasonCode"] in article_readiness.RESEARCH_REMEDY_CODES
    assert result["message"]
    assert "articleId" not in result, "no Article may exist for an insufficient Story"
    # §10: the preferred ordering is evidence first, Article second.
    assert articles_for() == []
    assert not _rows("cases.jsonl"), "no generation provider call may happen"


def test_a_persisting_blocking_gap_reports_the_real_blocker(newsroom, monkeypatch, working_model):
    """§9/§34 — research completing is not the same as evidence being sufficient.

    The Story is already assessed, and its single allowed research round is
    exhausted, so the basis keeps its blocking gap. The command must report that
    exact gap and stop — it must not spend a second speculative round trying to
    fix it, and it must not produce a low-quality Draft.
    """
    research_round(
        newsroom,
        gaps=[
            {
                "id": "gap_when",
                "question": "Кога точно започва ремонтът?",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
    )
    basis = story_research_store.get_story_research("s-one")
    story_research_store.save_story_research(
        {**basis, "research_rounds": 2, "operation_ids": [*basis["operation_ids"], "op-extra"]}
    )

    def explode(*_args, **_kwargs):
        raise AssertionError("an exhausted basis must not be researched again")

    monkeypatch.setattr(app, "research_story", explode)

    def explode_generation(*_args, **_kwargs):
        raise AssertionError("a blocking gap must stop before generation")

    monkeypatch.setattr(app, "_run_draft_generation", explode_generation)
    row = run_quick(key="gap")

    assert row["status"] == "succeeded", row
    assert row["result"]["status"] == quick_draft.NEEDS_ATTENTION
    # The exact reason, not a generic excuse: the readiness code that names the
    # blocking gap is the one the editor and the API both receive.
    assert row["result"]["reasonCode"] == article_readiness.BLOCKING_GAP
    assert (
        row["result"]["message"]
        == article_readiness.REASON_MESSAGES[article_readiness.BLOCKING_GAP]
    )
    assert articles_for() == []
    assert not _rows("cases.jsonl")


# ------------------------------------------------------------------ §38
# MULTIPLE ACTIVE ARTICLES — never guess


def test_two_active_articles_stop_with_an_editor_safe_ambiguity(
    newsroom, monkeypatch, working_model
):
    """§38 — a supported canonical feature is not a reason to pick one silently."""
    make_sufficient(newsroom)
    for index in range(2):
        articles.create_editor_article(
            story_id="s-one",
            stories_path=newsroom / "stories.json",
            working_title=f"Работа {index}",
            editorial_focus="Да обясним решението и какво променя за жителите.",
            now=f"2026-09-25T09:0{index}:00Z",
            idempotency_key=f"ambiguous-{index}",
        )
    before = [(row["article_id"], row["editorial_focus"]) for row in articles_for()]

    def explode(*_args, **_kwargs):
        raise AssertionError("Quick Draft must not guess between two Articles")

    monkeypatch.setattr(app, "_run_draft_generation", explode)
    row = run_quick(key="ambiguous")

    assert row["status"] == "succeeded", row
    assert row["result"]["status"] == quick_draft.NEEDS_ATTENTION
    assert row["result"]["reasonCode"] == quick_draft.MULTIPLE_ACTIVE_ARTICLES
    assert "повече от една активна статия" in row["result"]["message"]
    # Nothing was created, and no existing content or Focus was touched.
    assert [(r["article_id"], r["editorial_focus"]) for r in articles_for()] == before
    assert not _rows("cases.jsonl")


# ------------------------------------------------------------------ §40
# PROVIDER FAILURE — V1.1-C's marker, not a second failure mechanism


def test_a_generation_failure_keeps_the_article_and_earns_manual_continuation(
    newsroom, monkeypatch
):
    """§40/§18 — the real V1.1-C recovery surface, reached through Quick Draft."""
    make_sufficient(newsroom)
    entered = break_draft_provider(monkeypatch)

    row = run_quick(key="provider-down")

    assert entered, "the real generation path must have called the provider"
    assert row["status"] == "succeeded", row
    result = row["result"]
    assert result["status"] == quick_draft.NEEDS_ATTENTION
    assert result["reasonCode"] == quick_draft.DRAFT_GENERATION_FAILED
    article_id = result["articleId"]
    # The Preparation Article survives, carrying V1.1-C's durable marker.
    stored = articles.get_editor_article(article_id)
    failure = stored["draft_generation_failure"]
    assert failure is not None
    assert failure["reason_code"] == article_draft_failure.PROVIDER_UNAVAILABLE
    assert failure["basis_digest"] and failure["failed_at"]
    projection = app.read_article(article_id)
    assert projection["state"] == "preparation"
    assert "EDIT" in projection["availableActions"]
    # §10 of V1.1-C: the retry stays available next to the recovery path.
    assert "MAKE_DRAFT" in projection["availableActions"]
    assert not _rows("cases.jsonl"), "a failed generation publishes nothing"


# ------------------------------------------------------------------ §41
# NO SAFETY BYPASS — automation never overrides a result


def test_an_ignored_story_is_refused_by_the_command(newsroom, monkeypatch, working_model):
    """§41 — the ignored Story is refused before any work is scheduled."""
    story = story_store.read_store(newsroom / "stories.json")["stories"][0]
    story["status"] = "IGNORED"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")

    def explode(*_args, **_kwargs):
        raise AssertionError("an ignored Story must never be orchestrated")

    monkeypatch.setattr(app, "_run_quick_draft", explode)
    with pytest.raises(app.EditorInvalidTransition):
        app.start_quick_draft("s-one", idempotency_key="ignored")
    assert articles_for() == []


def test_a_story_that_becomes_ignored_mid_flight_stops_without_an_article(
    newsroom, monkeypatch, working_model
):
    """§41 — the guard is re-checked in the worker, not only at the API edge."""
    make_sufficient(newsroom)
    story = story_store.read_store(newsroom / "stories.json")["stories"][0]
    story["status"] = "IGNORED"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")

    # The command edge already refuses an ignored Story, so the worker's own
    # re-check is driven directly: this is the guard for the window between
    # accepting the click and the worker reading canonical state.
    result = app._run_quick_draft("s-one")

    assert result["status"] == quick_draft.NEEDS_ATTENTION
    assert result["reasonCode"] == quick_draft.STORY_IGNORED
    assert articles_for() == []


def test_a_blocked_source_stops_the_orchestration(newsroom, monkeypatch, working_model):
    """§41 — a deterministic safety guard is never overridden by automation."""
    research_round(
        newsroom,
        sources=[{"id": "vestnik", "name": "Вестник", "url": SOURCE_URL}],
        gaps=[],
    )
    # Arrange the canonical basis so the ONLY usable opened source is one the
    # safety guard rejects. The store accepts the row; the guard stops the Draft.
    blocked_url = "https://flagman.bg/x"
    assert blocked_domains.is_blocked(blocked_url), "the fixture must use a really blocked host"
    story_research_store.save_story_research(
        {
            "story_id": "s-one",
            "sources": [{"id": "vestnik", "name": "Вестник", "url": blocked_url}],
            "facts": [{"id": "fact_money", "text": BODY, "sourceId": "vestnik", "locator": "т. 4"}],
            "gaps": [],
            "assessed_at": "2026-09-25T08:45:00Z",
            "research_rounds": 1,
            "operation_ids": ["op-blocked"],
        }
    )

    def explode(*_args, **_kwargs):
        raise AssertionError("a safety guard must stop before generation")

    monkeypatch.setattr(app, "_run_draft_generation", explode)
    row = run_quick(key="blocked-source")

    assert row["result"]["status"] == quick_draft.NEEDS_ATTENTION
    assert row["result"]["reasonCode"] == article_readiness.SAFETY_BLOCKED
    assert articles_for() == []
    assert not _rows("cases.jsonl")


def test_an_invalid_story_lineage_is_refused(newsroom, monkeypatch, working_model):
    """§41 — a Story that cannot be read is a refusal, not an invitation."""
    make_sufficient(newsroom)
    story_store.write_store({"stories": []}, newsroom / "stories.json")

    def explode(*_args, **_kwargs):
        raise AssertionError("a missing Story must never be orchestrated")

    monkeypatch.setattr(app, "_run_quick_draft", explode)
    with pytest.raises(app.EditorNotFound):
        app.start_quick_draft("s-one", idempotency_key="no-story")
    assert articles_for() == []


def test_an_exhausted_research_cap_does_not_trigger_more_research(
    newsroom, monkeypatch, working_model
):
    """§8 — the existing round cap still binds the automated path."""
    research_round(newsroom, gaps=[], blocking=False)
    basis = story_research_store.get_story_research("s-one")
    story_research_store.save_story_research(
        {
            **basis,
            "gaps": [
                {"id": "gap_when", "question": "Кога?", "kind": "unresolved", "blocking": True}
            ],
            "research_rounds": 2,
        }
    )

    def explode(*_args, **_kwargs):
        raise AssertionError("the research cap must stop the automated round")

    monkeypatch.setattr(app, "research_story", explode)
    row = run_quick(key="cap-exhausted")

    assert row["result"]["status"] == quick_draft.NEEDS_ATTENTION
    assert story_research_store.get_story_research("s-one")["research_rounds"] == 2
    assert articles_for() == []


# ------------------------------------------------------------------ §12/§39
# IDEMPOTENCY — one click, one research round, one Article, one generation


def test_a_repeated_request_addresses_the_same_operation(newsroom, monkeypatch, working_model):
    """§12/§39 — the same Idempotency-Key never repeats the work."""
    make_sufficient(newsroom)
    first = app.start_quick_draft("s-one", idempotency_key="same-key")
    second = app.start_quick_draft("s-one", idempotency_key="same-key")

    assert first["operationToken"] == second["operationToken"]
    row = await_operation(first["operationToken"])

    assert row["status"] == "succeeded", row
    assert len(articles_for()) == 1
    assert len(_rows("cases.jsonl")) == 1, "exactly one generation attempt"
    assert story_research_store.get_story_research("s-one")["research_rounds"] == 1


def test_concurrent_identical_requests_share_one_operation(newsroom, monkeypatch, working_model):
    """§39 — two threads racing the same click produce one Article, one Draft."""
    make_sufficient(newsroom)
    tokens: list[str] = []
    errors: list[Exception] = []

    def fire():
        try:
            tokens.append(app.start_quick_draft("s-one", idempotency_key="race")["operationToken"])
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=fire) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert len(set(tokens)) == 1, f"a race must not mint several operations: {tokens}"
    await_operation(tokens[0])
    assert len(articles_for()) == 1
    assert len(_rows("cases.jsonl")) == 1


def test_a_second_click_while_the_work_runs_reattaches(newsroom, monkeypatch, working_model):
    """§29 — no duplicate hidden work, and the same token comes back."""
    make_sufficient(newsroom)
    first = app.start_quick_draft("s-one", idempotency_key="click-a")
    second = app.start_quick_draft("s-one", idempotency_key="click-b")

    assert first["operationToken"] == second["operationToken"]
    row = await_operation(first["operationToken"])
    assert row["result"]["status"] == quick_draft.DRAFT_CREATED
    assert len(articles_for()) == 1
    assert len(_rows("cases.jsonl")) == 1


def test_a_missing_idempotency_key_is_refused(newsroom, working_model):
    """§12 — the key is required, because without it retries are not safe."""
    make_sufficient(newsroom)
    with pytest.raises(app.EditorApplicationError):
        app.start_quick_draft("s-one", idempotency_key="   ")
    assert articles_for() == []


# ------------------------------------------------------------------ §42
# FOCUS


def test_the_default_focus_is_story_specific_and_costs_no_model_call():
    """§13/§42 — deterministic, Story-specific, and no provider is involved."""
    first = quick_draft.default_focus(STORY_TITLE)
    second = quick_draft.default_focus(STORY_TITLE)
    other = quick_draft.default_focus("Друг ремонт на друга улица")

    assert first == second, "the default Focus must be deterministic"
    assert first != other
    assert STORY_TITLE in first
    assert "Друг ремонт" not in first
    # 1-3 sentences, and it represents a straight-news intent explicitly.
    assert first.count(".") <= 2
    assert "информационна новина" in first
    # §13: never the old generic V1 placeholder.
    assert "Да разкажем какво се е променило" not in first
    # No source suffix garbage when the canonical title is already clean.
    assert "Вестник" not in first


def test_the_default_focus_collapses_whitespace_and_bounds_its_length():
    """A Story title is data; a Focus must not be a place for data to sprawl."""
    focus = quick_draft.default_focus("  Заглавие  с\nмного   интервали  ")
    assert "  " not in focus
    assert "\n" not in focus
    long_title = "а" * 400
    assert len(quick_draft.default_focus(long_title)) < len(long_title) + 200


def test_no_focus_is_written_without_a_clean_story_title(newsroom, monkeypatch, working_model):
    """An empty subject is not a reason to write a vague Focus."""
    assert quick_draft.default_focus("") == ""


# ------------------------------------------------------------------ §4/§43
# THE TODAY DTO — the backend is the authority


def _today_rows(newsroom) -> list[dict]:
    return [*app.read_today()["newDevelopments"], *app.read_today()["newStories"]]


def _row_for(newsroom, story_id: str = "s-one") -> dict:
    return next(row for row in _today_rows(newsroom) if row["objectId"] == story_id)


def test_today_offers_all_three_triage_intents_for_a_current_story(newsroom):
    """§3/§43 — `Игнорирай`, `Прегледай`, `Чернова`, decided by the backend."""
    story = story_store.read_store(newsroom / "stories.json")["stories"][0]
    story["status"] = "NEW"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")

    row = _row_for(newsroom)

    assert row["nextAction"] == "REVIEW", "Прегледай keeps its existing semantics"
    assert "REVIEW" in row["availableActions"]
    assert "IGNORE" in row["availableActions"]
    # §4: an unassessed Story is still offered, because the quick path researches
    # it. Refusing the button here would push the decision back onto the editor.
    assert "QUICK_DRAFT" in row["availableActions"]
    assert row["quickDraft"] == {
        "available": True,
        "label": "Чернова",
        "articleId": None,
        "reasonCode": None,
    }


def test_today_withholds_quick_draft_for_an_ambiguous_story(newsroom):
    """§4 — the backend refuses the button when it could not choose an Article."""
    story = story_store.read_store(newsroom / "stories.json")["stories"][0]
    story["status"] = "NEW"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")
    for index in range(2):
        articles.create_editor_article(
            story_id="s-one",
            stories_path=newsroom / "stories.json",
            working_title=f"Работа {index}",
            now=f"2026-09-25T09:0{index}:00Z",
            idempotency_key=f"row-ambiguous-{index}",
        )

    row = _row_for(newsroom)

    assert "QUICK_DRAFT" not in row["availableActions"]
    assert row["quickDraft"]["available"] is False
    assert row["quickDraft"]["reasonCode"] == quick_draft.MULTIPLE_ACTIVE_ARTICLES


def test_today_offers_open_draft_when_a_draft_already_exists(newsroom):
    """§22 — when a unique Draft exists the row says «Отвори чернова»."""
    story = story_store.read_store(newsroom / "stories.json")["stories"][0]
    story["status"] = "NEW"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")
    created = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        editorial_focus="Да обясним решението и както променя.",
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(created["article_id"], "Да обясним решението и както променя.")
    articles.save_article_content(
        created["article_id"], expected_version=0, title="Работа за статия", body="Готово тяло."
    )

    row = _row_for(newsroom)

    assert row["quickDraft"]["available"] is True
    assert row["quickDraft"]["label"] == quick_draft.LABEL_OPEN_DRAFT
    assert row["quickDraft"]["articleId"] == created["article_id"]


def test_today_keeps_article_internals_out_of_the_story_row(newsroom):
    """§43 — Today carries the minimum, not the Article's internals."""
    story = story_store.read_store(newsroom / "stories.json")["stories"][0]
    story["status"] = "NEW"
    story_store.write_store({"stories": [story]}, newsroom / "stories.json")

    serialized = json.dumps(_row_for(newsroom), ensure_ascii=False)

    for forbidden in ("evidenceId", "caseId", "internal_refs", "content", "model", "provider"):
        assert forbidden not in serialized


def test_reading_today_never_writes_to_any_store(newsroom):
    """D1's invariant still holds with the triage projection added on top."""
    watched = {
        path: path.read_bytes()
        for path in (
            newsroom / "stories.json",
            newsroom / "inbox.jsonl",
            Path(app._editorial_root()) / "editor_articles.jsonl",
        )
        if path.exists()
    }
    app.read_today()
    assert all(path.read_bytes() == before for path, before in watched.items())


# ------------------------------------------------------------------ §5
# THE API CONTRACT — one route, one token, a required key


def test_the_quick_draft_route_requires_an_idempotency_key(api_server):
    """§12 — without a key a retry is not safe, so the route refuses it."""
    status, payload = _request(api_server, "/api/v1/stories/s-one/quick-draft", method="POST")
    assert status == 400
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    # A malformed key is refused the same way, before any work is scheduled.
    status, _ = _request(
        api_server,
        "/api/v1/stories/s-one/quick-draft",
        method="POST",
        headers={"Idempotency-Key": "bad key with spaces"},
    )
    assert status == 400
    assert _articles_on_disk() == []


def test_the_quick_draft_route_answers_202_with_one_operation_token(
    api_server, monkeypatch, working_model
):
    """§5/§6 — the browser expresses one intent and gets one bounded operation."""
    substitute_research_network(monkeypatch)
    _route_research_edges(monkeypatch)

    result = _request(
        api_server,
        "/api/v1/stories/s-one/quick-draft",
        method="POST",
        headers={"Idempotency-Key": "http-click"},
    )
    assert result[0] == 202, result[1]
    token = _data(result)["operationToken"]
    assert token.startswith("op_")

    operation = _await_http(api_server, token)
    assert operation["status"] == "succeeded", operation
    result = operation["result"]
    assert result["status"] == quick_draft.DRAFT_CREATED
    # §19: the result crosses the API without a single internal identifier.
    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in ("case", "evidence_id", "model", "provider", "search", "operationToken"):
        assert forbidden not in serialized.lower()


def test_a_repeated_http_post_returns_the_same_operation(api_server, monkeypatch, working_model):
    """§39 — a double click over HTTP addresses one operation, not two."""
    substitute_research_network(monkeypatch)
    _route_research_edges(monkeypatch)
    headers = {"Idempotency-Key": "double-click"}

    first = _request(
        api_server, "/api/v1/stories/s-one/quick-draft", method="POST", headers=headers
    )
    second = _request(
        api_server, "/api/v1/stories/s-one/quick-draft", method="POST", headers=headers
    )
    assert first[0] == second[0] == 202
    assert _data(first)["operationToken"] == _data(second)["operationToken"]

    _await_http(api_server, _data(first)["operationToken"])
    assert len(articles_for()) == 1
    assert len(_rows("cases.jsonl")) == 1
