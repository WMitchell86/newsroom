"""V1.2-G4.1 §B/§C — Draft is not Ready: two gates, one boundary.

The owner manually tested the product after G3/G4 and could not reliably reach a
Draft. The cause was a single contract: a Story-level `BLOCKING_GAP` refused
`MAKE_DRAFT` **before** the evaluator ever looked at the facts, and the editor was
shown «Има непопълнена информация, която пречи да продължите.» on a Story that had
real, opened, source-backed material.

This module pins the replacement contract:

  * **Gate 1 — can a Draft start?** Focus, and *some* source-backed material.
    Promoted facts, an appropriate PRIMARY, or one really-opened publisher page.
    Open questions do not stop it; they travel with the Draft as warnings.
  * **Gate 2 — can it be Ready?** `article_validation`, unchanged in strength.
    An unresolved blocking gap, an unsupported claim or a conflict stops
    `Отбележи като готова`, and therefore Finalize.

Everything here runs the real pipeline. The only stub is the model transport, so
a passing test means the product can genuinely produce a Draft, not that a
predicate returns a value.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import (
    article_generation,
    article_readiness,
    draft_material,
    inbox_store,
    story_operations,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import (
    editor_application as app,
)
from editor_assistant.workflow import (
    editor_article_store as articles,
)

BODY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
HEADLINE = "Съветът одобри графика за ремонта"
#: The opened page's own words. A realistic length is required, not for
#: realism's sake: the angle gate and the sufficiency check both judge whether
#: the material describes a concrete news event, and a bare headline really is
#: correctly refused as `NO_PUBLISHABLE_ANGLE`.
REAL_SUMMARY = (
    "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата в центъра "
    "на града. Ремонтът ще започне на 1 октомври и ще продължи три месеца, като "
    "движението по улицата ще бъде ограничено. Жителите от квартала ще пътуват "
    "с около 10 минути повече до работата през целия период."
)
SOURCE_URL = "https://vestnik.example.test/2026/budget"
def _item(item_id: str, title: str, *, summary: str = REAL_SUMMARY):
    return {
        "item_id": item_id,
        "source_id": "vestnik",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://vestnik.example.test/{item_id}",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": summary,
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
    origin = _item("origin", HEADLINE)
    inbox_store.save_items([origin], root / "inbox.jsonl")
    story = story_store.new_story(origin, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    story_operations.clear()
    yield root
    story_operations.clear()
    for token in list(getattr(article_generation._ACTIVE, "keys", list)()):
        article_generation.release(token, article_generation._ACTIVE[token])


@pytest.fixture
def prepared(newsroom):
    """An Article the backend itself currently offers MAKE_DRAFT for."""
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(
        article["article_id"], "Да обясним решението и какво променя за хората."
    )
    story_research_store.merge_research(
        "s-one",
        sources=[
            {
                "id": "vestnik",
                "name": "Вестник",
                "url": "https://vestnik.example.test/2026/budget",
            }
        ],
        facts=[
            {
                "id": "fact_money",
                "text": BODY,
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
            {
                "id": "fact_next",
                "text": "Следващата сесия на съвета ще обсъди графика за следващата улица.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 6",
            },
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="fixture-round",
    )
    return articles.get_editor_article(article["article_id"])


@pytest.fixture
def model(monkeypatch):
    """The only stub: the model transport. Readiness, retrieval and gates are real."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    seen: list[dict] = []

    def call(prompt_text, *, api_key, timeout, role="draft", **_kw):
        seen.append({"role": role, "prompt": prompt_text})
        if role == "draft":
            return (
                json.dumps(
                    {
                        "headlines": [HEADLINE],
                        "headline": HEADLINE,
                        "body": BODY + " Това е първата стъпка от по-широк план.",
                    },
                    ensure_ascii=False,
                ),
                {"model": "mock", "provider": "gemini"},
            )
        return (
            "\n".join(
                json.dumps(
                    {
                        "sentence": BODY,
                        "verdict": "SUPPORTED",
                        "issue": "none",
                        "supporting_fact_ids": [],
                        "note": "ok",
                    }
                )
            ),
            {"model": "mock"},
        )

    monkeypatch.setattr(gen, "_call_gemini", call)
    return seen


def _await(token, *, attempts=600):
    for _ in range(attempts):
        row = story_operations.get(token)
        if row and row["status"] in {"succeeded", "failed"}:
            return row
        time.sleep(0.02)
    raise AssertionError("the draft operation did not finish")


def _editorial() -> Path:
    return app._editorial_root()




def _editorial() -> Path:
    return app._editorial_root()


def _run(article_id, key):
    started = app.start_article_draft(article_id, idempotency_key=key)
    return started, _await(started["operationToken"])


def _drafts() -> list[dict]:
    path = _editorial() / "live_drafts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _write_basis(newsroom, *, sources, facts, gaps, operation_id):
    """Arrange the canonical Story basis through the real research store."""
    story_research_store.save_story_research(
        {
            "story_id": "s-one",
            "sources": sources,
            "facts": facts,
            "gaps": gaps,
            "assessed_at": "2026-09-25T10:00:00Z",
            "research_rounds": 1,
            "operation_ids": [operation_id],
        }
    )


def _new_article(newsroom, title="Работа за статия"):
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title=title,
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(
        article["article_id"], "Да обясним решението и какво променя за хората."
    )
    return article["article_id"]


OPEN_SOURCE = {"id": "vestnik", "name": "Вестник", "url": SOURCE_URL}
#: §B3 C: the sentences this opened page actually yielded. A single-source
#: Draft is grounded in these, never in a discovery snippet (§B4).
OPENED_CLAIMS = [
    {"text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.", "locator": "claim:0"},
    {"text": "Ремонтът ще започне на 1 октомври и ще продължи три месеца.", "locator": "claim:1"},
    {"text": "Движението по улицата ще бъде ограничено през целия период.", "locator": "claim:2"},
]
SINGLE_SOURCE = {**OPEN_SOURCE, "claims": OPENED_CLAIMS}
OPEN_FACT = {
    "id": "fact_money",
    "text": BODY,
    "sourceId": "vestnik",
    "locator": "Протокол, т. 4",
    "scope": "current",
}
OPEN_GAPS = [
    {"id": "gap_who", "question": "Кой е изпълнителят?", "kind": "unresolved", "blocking": True},
    {"id": "gap_cost", "question": "Каква е стойността?", "kind": "unresolved", "blocking": True},
]


# --------------------------------------------------------------------------
# §B1 — Gate 1: a blocking gap plus usable material means MAKE_DRAFT
# --------------------------------------------------------------------------


def test_a_blocking_gap_plus_usable_facts_produces_a_real_draft(newsroom, model):
    """The owner's exact screen, end to end, through the real pipeline.

    Not a predicate result: a real Article, a real command, a real model call and
    a real non-empty Bulgarian body.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[OPEN_SOURCE],
        facts=[OPEN_FACT],
        gaps=OPEN_GAPS,
        operation_id="gap-and-facts",
    )

    before = app.read_article(article_id)
    assert before["preparation"]["draftEligible"] is True
    assert before["preparation"]["draftReadiness"]["code"] == "DRAFT_ELIGIBLE"
    assert "MAKE_DRAFT" in before["availableActions"]
    assert before["nextAction"]["action"] == "MAKE_DRAFT"
    # The real questions are still on screen — visible, not blocking.
    assert [gap["question"] for gap in before["preparation"]["blockingGaps"]] == [
        "Кой е изпълнителят?",
        "Каква е стойността?",
    ]

    _started, outcome = _run(article_id, "gap-ok")
    assert outcome["status"] == "succeeded", outcome
    assert _drafts(), "a real immutable generated Draft was written"

    after = app.read_article(article_id)
    assert after["state"] == "draft"
    assert after["content"]["body"].strip(), "the Draft has real editorial text"
    assert after["content"]["version"] == 1


# --------------------------------------------------------------------------
# §B3 C — the single-source attributed fallback
# --------------------------------------------------------------------------


def test_one_opened_ordinary_publisher_allows_an_attributed_draft(newsroom, model):
    """§B3 C: one real opened page is enough to START, with attribution required.

    No promoted fact exists — the corroboration gate declined it — but the page
    really was opened, so the editor may begin. The decision carries the
    single-source basis and the warning, and the gate's own `PROMOTED` path is
    explicitly not what produced it.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[SINGLE_SOURCE],
        facts=[],
        gaps=[
            {
                "id": "gap_corr",
                "question": "Нужен е още независим източник за потвърждение.",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
        operation_id="one-source",
    )

    snapshot = app._draft_snapshot(article_id)
    decision = article_readiness.evaluate(snapshot)
    assert decision.eligible is True
    assert decision.draft_basis == draft_material.SINGLE_SOURCE
    assert decision.attribution_required is True
    assert draft_material.WARNING_SINGLE_SOURCE in decision.draft_warnings
    assert "MAKE_DRAFT" in app.read_article(article_id)["availableActions"]

    _started, outcome = _run(article_id, "one-source")
    assert outcome["status"] == "succeeded", outcome
    after = app.read_article(article_id)
    assert after["state"] == "draft"
    assert after["content"]["body"].strip()


def test_a_primary_official_source_needs_no_second_publisher(newsroom, model, monkeypatch):
    """§B3 B and Proof 3: an official PRIMARY is enough on its own.

    G4's `Надежден за факти` remains the only authority in the product — this
    resolves the opened page through the same registry and nothing else, so there
    is no artificial second-source requirement and no new trust system.
    """
    import json as _json

    registry = newsroom / "sources.json"
    registry.write_text(
        _json.dumps(
            [
                {
                    "source_id": "burgas-municipality",
                    "name": "Община Бургас",
                    "kind": "official",
                    "domain": "burgas.bg",
                    "collector": "google_news_rss",
                    "query": "Община Бургас",
                    "url": "",
                    "status": "active",
                    "muted_until": "",
                    "priority": "normal",
                    "cadence": "each_run",
                    "factual_authority": True,
                    "calendar": False,
                    "note": "",
                    "added_at": "2026-09-21T17:00:00Z",
                    "updated_at": "2026-09-21T17:00:00Z",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[
            {
                "id": "obshina",
                "name": "Община Бургас",
                "url": "https://burgas.bg/novini/repair",
            }
        ],
        facts=[],
        gaps=[
            {
                "id": "gap_when",
                "question": "Кога точно започва ремонтът?",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
        operation_id="primary-only",
    )

    snapshot = app._draft_snapshot(article_id)
    decision = article_readiness.evaluate(snapshot)
    assert decision.eligible is True
    assert decision.draft_basis == draft_material.PRIMARY
    # A PRIMARY establishes its own first-party facts: no attribution caveat and
    # no artificial requirement for a second publisher.
    assert decision.attribution_required is False
    assert draft_material.WARNING_SINGLE_SOURCE not in decision.draft_warnings


# --------------------------------------------------------------------------
# §B4 / §B6 — what is still refused
# --------------------------------------------------------------------------


def test_a_snippet_only_basis_is_refused(newsroom, model):
    """§B4: a discovery snippet can never reach a Draft.

    A snippet was never opened, so it is not source-backed material. The Story has
    an item and a summary but no opened publication at all.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[],
        facts=[],
        gaps=[
            {
                "id": "gap_none",
                "question": "Не успяхме да отворим подходящ източник.",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
        operation_id="snippet-only",
    )

    decision = article_readiness.evaluate(app._draft_snapshot(article_id))
    assert decision.eligible is False
    assert decision.reason_code == "NO_DRAFT_MATERIAL"
    assert decision.is_researchable is True
    with pytest.raises(app.EditorDraftNotReady) as refusal:
        app.start_article_draft(article_id, idempotency_key="snippet-only")
    assert refusal.value.code == "NO_DRAFT_MATERIAL"
    assert model == [], "nothing may be generated from a snippet"


def test_an_unresolved_aggregator_wrapper_is_refused(newsroom, model):
    """§B4: an unresolved wrapper is not a publisher either.

    `news.google.com` is a redirect surface, not a publication. It reuses the
    already-measured publisher test, so this cannot drift from §E1.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[
            {
                "id": "wrapper",
                "name": "Google News",
                "url": "https://news.google.com/rss/articles/CBMi?oc=5",
            }
        ],
        facts=[],
        gaps=[
            {
                "id": "gap_none",
                "question": "Нужен е още независим източник за потвърждение.",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
        operation_id="wrapper-only",
    )

    decision = article_readiness.evaluate(app._draft_snapshot(article_id))
    assert decision.eligible is False
    assert decision.reason_code == "NO_DRAFT_MATERIAL"
    assert draft_material.is_opened_publisher_source({"domain": "news.google.com"}) is False
    with pytest.raises(app.EditorDraftNotReady) as refusal:
        app.start_article_draft(article_id, idempotency_key="wrapper-only")
    assert refusal.value.code == "NO_DRAFT_MATERIAL"
    assert model == []


def test_a_known_conflict_still_refuses_the_draft(newsroom, model):
    """§C2: a detected contradiction is never something to write around.

    This is the one gap kind that is NOT demoted to a warning, because two opened
    sources disagreeing about the same proposition is an editorial obstacle rather
    than a missing detail.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[OPEN_SOURCE],
        facts=[],
        gaps=[
            {
                "id": "gap_conflict",
                "question": "Източниците се разминават за датата на събитието.",
                "kind": "conflict",
                "blocking": False,
            }
        ],
        operation_id="conflict",
    )

    decision = article_readiness.evaluate(app._draft_snapshot(article_id))
    assert decision.eligible is False
    assert decision.reason_code == "NO_DRAFT_MATERIAL"


# --------------------------------------------------------------------------
# §C — Gate 2: the safety boundary is preserved
# --------------------------------------------------------------------------


def test_a_single_source_draft_carries_its_warning_and_cannot_be_marked_ready(
    newsroom, model
):
    """Proof 4: the Draft exists, is editable, and Ready stays closed.

    This is the whole point of splitting the gates. The single-source Draft is
    real, visible and editable; what it cannot do is be declared finished, because
    one unconfirmed source is not a finished article.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[SINGLE_SOURCE],
        facts=[],
        gaps=[
            {
                "id": "gap_corr",
                "question": "Нужен е още независим източник за потвърждение.",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
        operation_id="one-source-ready",
    )
    _started, outcome = _run(article_id, "one-source-ready")
    assert outcome["status"] == "succeeded", outcome

    draft = app.read_article(article_id)
    assert draft["state"] == "draft"
    assert draft["content"]["body"].strip()
    # §B3: the warning the single-source Draft must always carry, recomputed
    # from the canonical basis on every read rather than stored on the Article.
    assert draft_material.WARNING_SINGLE_SOURCE in draft["draftWarnings"]
    assert draft["missingInformation"]["openedSources"], "the opened page is visible"
    assert draft["missingInformation"]["openedSources"][0]["url"] == SOURCE_URL
    # §C2: `Готова` is not offered while a blocking gap is open.
    assert "MARK_READY" not in draft["availableActions"]
    assert draft["nextAction"]["action"] != "MARK_READY"
    # §C3: the editor can keep working on it.
    assert "EDIT" in draft["availableActions"]


def test_research_after_a_draft_never_overwrites_the_editor_text(newsroom, model):
    """§C3: new facts refresh the evidence, never the body.

    The Draft is written, the editor types their own sentence over it, and a
    further research round lands new material. The text must survive exactly.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[OPEN_SOURCE],
        facts=[OPEN_FACT],
        gaps=[],
        operation_id="before-research",
    )
    _started, outcome = _run(article_id, "before-research")
    assert outcome["status"] == "succeeded", outcome
    generated = app.read_article(article_id)
    assert generated["content"]["body"].strip()

    edited = app.save_content(
        article_id,
        1,
        generated["content"]["title"],
        "Редакторски текст, който не бива да бъде презаписан.",
    )
    assert edited["content"]["body"] == "Редакторски текст, който не бива да бъде презаписан."

    # A real further research round adds material to the same Story.
    story_research_store.merge_research(
        "s-one",
        sources=[OPEN_SOURCE],
        facts=[
            {
                "id": "fact_new",
                "text": "Ремонтът продължава до края на годината.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 9",
                "scope": "current",
            }
        ],
        gaps=[
            {
                "id": "gap_new",
                "question": "Кой е изпълнителят?",
                "kind": "unresolved",
                "blocking": True,
            }
        ],
        assessed_at="2026-09-25T12:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="later-round",
    )

    after = app.read_article(article_id)
    assert after["content"]["body"] == "Редакторски текст, който не бива да бъде презаписан."
    assert after["content"]["version"] == 2
    # The evidence rail did refresh: the new question is visible on the Story
    # the Draft belongs to, and the Draft's own body is untouched.
    assert [
        gap["question"]
        for gap in app.read_story("s-one")["missingInformation"]["items"]
    ] == ["Кой е изпълнителят?"]
    # And Ready is still withheld, because the new question is unresolved.
    assert "MARK_READY" not in after["availableActions"]


def test_a_clean_draft_with_resolved_gaps_can_be_marked_ready(newsroom, model):
    """§C1: Ready remains reachable once the safety conditions are met.

    The gates are not "Ready is now impossible" — a Draft with no open question
    and supported text still becomes `Готова` through the unchanged editor action.
    """
    article_id = _new_article(newsroom)
    _write_basis(
        newsroom,
        sources=[OPEN_SOURCE],
        facts=[OPEN_FACT],
        gaps=[],
        operation_id="clean",
    )
    _started, outcome = _run(article_id, "clean")
    assert outcome["status"] == "succeeded", outcome
    draft = app.read_article(article_id)
    assert "MARK_READY" in draft["availableActions"], draft["availableActions"]
    assert draft["nextAction"]["action"] == "MARK_READY"

    ready = app.mark_article_ready(article_id, 1)
    assert ready["readiness"]["readyAt"], "the readiness checkpoint is recorded"
    assert ready["state"] == "ready"


def test_opened_page_claims_survive_the_corroboration_gate(newsroom, model):
    """§B3 C: the page's own words are kept even when no fact is promoted.

    This is what makes the attributed Draft possible at all. The claims are NOT
    facts — the canonical basis still reports zero promoted facts — but they are
    real text read off a real opened page, with their own locators, and they are
    what the Draft is written from instead of a discovery snippet (§B4).
    """
    from editor_assistant.workflow import story_research_store

    story_research_store.save_story_research(
        {
            "story_id": "s-one",
            "sources": [
                {
                    "id": "vestnik",
                    "name": "Вестник",
                    "url": SOURCE_URL,
                    "claims": [
                        {"text": "Ремонтът започна на 25 септември.", "locator": "claim:0"},
                        {"text": "Жителите ще пътуват с 10 минути повече.", "locator": "claim:1"},
                    ],
                }
            ],
            "facts": [],
            "gaps": [
                {
                    "id": "gap_corr",
                    "question": "Нужен е още независим източник за потвърждение.",
                    "kind": "unresolved",
                    "blocking": True,
                }
            ],
            "assessed_at": "2026-09-25T10:00:00Z",
            "research_rounds": 1,
            "operation_ids": ["claims-round"],
        }
    )
    row = story_research_store.get_story_research("s-one")
    assert row["facts"] == [], "nothing is promoted to a confirmed fact"
    assert [claim["text"] for claim in row["sources"][0]["claims"]] == [
        "Ремонтът започна на 25 септември.",
        "Жителите ще пътуват с 10 минути повече.",
    ]

    article_id = _new_article(newsroom)
    projection = app.read_article(article_id)
    opened = projection["missingInformation"]["openedSources"]
    assert opened[0]["claims"], "the editor can see what the page yielded"
    snapshot = app._draft_snapshot(article_id)
    packet = article_generation.build_packet(snapshot, "EV-CLAIMS")
    assert len(packet["facts"]) == 2
    assert packet["source_url"] == SOURCE_URL
    assert all(ref["source_id"] == "vestnik" for fact in packet["facts"] for ref in fact["source_refs"])


def test_an_opened_page_with_no_extractable_text_is_still_refused(newsroom, model):
    """§B6: a page that opened but yielded no sentence is not material.

    `NO_PUBLISHABLE_ANGLE` and an empty claim list are the same honest answer:
    there is nothing on the page to write from, so the Draft stays blocked rather
    than falling back to the discovery snippet.
    """
    from editor_assistant.workflow import story_research_store

    story_research_store.save_story_research(
        {
            "story_id": "s-one",
            "sources": [{"id": "vestnik", "name": "Вестник", "url": SOURCE_URL}],
            "facts": [],
            "gaps": [
                {
                    "id": "gap_none",
                    "question": "Намерени са източници, но информацията още не е достатъчна.",
                    "kind": "unresolved",
                    "blocking": True,
                }
            ],
            "assessed_at": "2026-09-25T10:00:00Z",
            "research_rounds": 1,
            "operation_ids": ["no-claims"],
        }
    )
    article_id = _new_article(newsroom)
    snapshot = app._draft_snapshot(article_id)
    decision = article_readiness.evaluate(snapshot)
    # The opened page still makes the basis single-source eligible...
    assert decision.eligible is True
    # ...but there is nothing on it to ground a Draft in, so generation refuses
    # honestly instead of reaching for the snippet.
    with pytest.raises(article_generation.DraftRefused) as refusal:
        article_generation.build_packet(snapshot, "EV-EMPTY")
    assert refusal.value.code == "NO_DRAFT_MATERIAL"
    assert model == []
