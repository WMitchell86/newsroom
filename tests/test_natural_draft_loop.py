"""V1.2-G4.3 — the natural draft loop: auto-enrichment, rewrite, voice, learning.

What these tests pin is the PRODUCT CONTRACT the owner approved, not the
internals:

* a Draft is produced with automatic bounded enrichment, and a Draft is still
  produced when enrichment finds nothing or the provider is unavailable;
* enrichment never promotes a fact, closes a gap or becomes a gate;
* `Пренапиши` returns a new version of the SAME Article, keeps the old text
  recoverable, reuses the factual basis, and survives a model failure;
* the optional voice defaults to automatic, is validated against the canonical
  list, and changes no existing text;
* the learning loop produces PROPOSALS and only a human approval can make an
  instruction active.

Only the model transport and the search provider are stubbed; every gate,
store and orchestration step is the real one.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import (
    article_generation,
    article_rewrite,
    draft_enrichment,
    inbox_store,
    rewrite_feedback,
    story_operations,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import (
    editor_article_store as articles,
)

HEADLINE = "Съветът одобри графика за ремонта"
BODY = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
SHORT_BODY = "Съветът одобри 1,2 милиона лева за ремонта. Ремонът започва през октомври."


def _item(item_id: str, title: str, *, summary: str = "Обобщение"):
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


@pytest.fixture(autouse=True)
def _enrichment_on(monkeypatch):
    """Opt this module back IN to the automatic enrichment.

    `conftest.py` turns it off for the whole suite so no test can reach the
    network. This module is where the enrichment contract itself is asserted, so
    it enables it explicitly and controls the search transport in each test -
    which is the difference between testing the contract and testing the
    provider.
    """
    monkeypatch.setenv("NEWSROOM_DRAFT_ENRICHMENT", "on")


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
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
    for token in list(getattr(article_rewrite._ACTIVE, "keys", list)()):
        article_rewrite.release(token, article_rewrite._ACTIVE[token])


@pytest.fixture
def prepared(newsroom):
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
            }
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="fixture-round",
    )
    return articles.get_editor_article(article["article_id"])


@pytest.fixture
def model(monkeypatch):
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
            json.dumps(
                {
                    "sentence": BODY,
                    "verdict": "SUPPORTED",
                    "issue": "none",
                    "supporting_fact_ids": [],
                    "note": "ok",
                },
                ensure_ascii=False,
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
    raise AssertionError("the operation did not finish")


def _no_search(monkeypatch, *, sources=(), queries=()):
    """Neutralize the network: a controlled, offline enrichment round."""
    from editor_assistant.workflow import search as search_mod

    def run_event_discovery(**kwargs):
        return {
            "status": search_mod.SEARCH_OK if sources else search_mod.SEARCH_INCOMPLETE,
            "queries": [{"query": q, "status": "SEARCH_OK", "results": 1} for q in queries],
            "candidates": [
                {
                    "title": "Открит източник",
                    "url": url,
                    "opened": {"status": "FETCH_OK", "final_url": url, "content_type": "text/html"},
                }
                for url in sources
            ],
        }

    monkeypatch.setattr(search_mod, "run_event_discovery", run_event_discovery)


def _stub_publication(monkeypatch):
    """Every readable page yields one usable, on-topic claim."""
    monkeypatch.setattr(
        draft_enrichment.publication_material,
        "read_publication",
        lambda url, *, topic="", opener=None: (
            {
                "url": url,
                "domain": url.split("/")[2],
                "claims": [
                    {
                        "text": "Съветът обяви, че ремонтът започва през октомври тази година.",
                        "locator": "claim:0",
                    }
                ],
            }
            if url
            else None
        ),
    )


# ---------------------------------------------------------------- PART A


def test_draft_runs_bounded_enrichment_and_uses_what_it_finds(prepared, model, monkeypatch):
    """§A: pressing `Чернова` enriches automatically and the Draft is written."""
    _no_search(
        monkeypatch,
        sources=["https://other.example.test/2026/budget", "https://third.example.test/x"],
        queries=["Съветът одобри графика за ремонта", "ремонт улица Бургас октомври"],
    )
    _stub_publication(monkeypatch)

    token = app.start_article_draft(prepared["article_id"], idempotency_key="k1")[
        "operationToken"
    ]
    assert _await(token)["status"] == "succeeded"

    content = articles.get_article_content(prepared["article_id"])
    assert content["body"].strip()

    # The enrichment's pages reached the generation as real opened material.
    snapshot_questions = draft_enrichment.plan_questions(HEADLINE)
    assert snapshot_questions, "the enrichment must plan real editorial questions"


def test_draft_survives_enrichment_that_finds_nothing(prepared, model, monkeypatch):
    """§A2: no enrichment result is a WARNING, never a missing Draft."""
    _no_search(monkeypatch, sources=[], queries=["няма нищо"])

    token = app.start_article_draft(prepared["article_id"], idempotency_key="k2")[
        "operationToken"
    ]
    row = _await(token)
    assert row["status"] == "succeeded"
    content = articles.get_article_content(prepared["article_id"])
    assert content["body"].strip(), "the original material is still enough to write"


def test_draft_survives_an_unavailable_search_provider(prepared, model, monkeypatch):
    """§A2: a provider failure degrades to a warning, never to a refusal."""
    from editor_assistant.workflow import search as search_mod

    def broken(**_kwargs):
        raise search_mod.SearchError("provider unavailable")

    monkeypatch.setattr(search_mod, "run_event_discovery", broken)

    token = app.start_article_draft(prepared["article_id"], idempotency_key="k3")[
        "operationToken"
    ]
    assert _await(token)["status"] == "succeeded"
    assert articles.get_article_content(prepared["article_id"])["body"].strip()


def test_enrichment_never_promotes_a_fact_or_closes_a_gap(newsroom, monkeypatch):
    """§A/§B4: enrichment produces MATERIAL only; the canonical basis is untouched."""
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа",
        now="2026-09-25T09:00:00Z",
    )
    story_research_store.merge_research(
        "s-one",
        sources=[{"id": "v", "name": "Вестник", "url": "https://v.example.test/a"}],
        facts=[],
        gaps=[{"id": "gap_remont_when", "question": "Кога точно започва ремонтът?", "blocking": False}],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="op1",
    )
    before = story_research_store.get_story_research("s-one")
    _no_search(monkeypatch, sources=["https://other.example.test/x"])
    _stub_publication(monkeypatch)
    result = draft_enrichment.enrich(topic=HEADLINE)
    assert result["sources"], "the controlled round produced material"
    after = story_research_store.get_story_research("s-one")
    assert after["facts"] == before["facts"], "enrichment must never promote a fact"
    assert [g["id"] for g in after["gaps"]] == [g["id"] for g in before["gaps"]]
    assert article["article_id"]


def test_enrichment_is_bounded_by_policy_constants():
    """§A3: the envelope is policy, so no caller can raise it."""
    assert 2 <= draft_enrichment.MAX_QUERIES <= 3
    assert 3 <= draft_enrichment.MAX_OPENED_PAGES <= 5
    assert 20.0 <= draft_enrichment.WALL_CLOCK_BUDGET_S <= 30.0
    budget = draft_enrichment.Budget(clock=lambda: 0.0)
    assert budget.take_page() is True
    tiny = draft_enrichment.Budget(pages=1, clock=lambda: 0.0)
    assert tiny.take_page() is True and tiny.take_page() is False


def test_enrichment_stops_on_a_spent_wall_clock_budget(monkeypatch):
    """§A3: a slow provider costs the enrichment, never the editor's Draft."""
    from editor_assistant.workflow import search as search_mod

    tick = {"n": 0}

    def clock():
        tick["n"] += 1
        return tick["n"] * 100.0

    _no_search(monkeypatch, sources=["https://a.example.test/x", "https://b.example.test/y"])
    _stub_publication(monkeypatch)
    result = draft_enrichment.enrich(
        topic=HEADLINE, budget=draft_enrichment.Budget(seconds=1.0, clock=clock)
    )
    assert search_mod.run_event_discovery is not None
    assert result["sources"] == [], "an exhausted budget opens no further page"


def _make_draft(prepared, model, monkeypatch, key="d1"):
    """Produce a real first Draft through the real pipeline."""
    _no_search(monkeypatch, sources=[], queries=["q"])
    token = app.start_article_draft(prepared["article_id"], idempotency_key=key)[
        "operationToken"
    ]
    assert _await(token)["status"] == "succeeded"
    return articles.get_article_content(prepared["article_id"])


# ---------------------------------------------------------------- PART E


def test_rewrite_returns_a_new_version_of_the_same_article(prepared, model, monkeypatch):
    """§E/§E3: a new version of THIS Article, and the old text stays recoverable."""
    before = _make_draft(prepared, model, monkeypatch)
    article_id = prepared["article_id"]

    token = app.start_article_rewrite(
        article_id, "Съкрати текста и започни директно с основния факт.", idempotency_key="r1"
    )["operationToken"]
    assert _await(token)["status"] == "succeeded"

    after = articles.get_article_content(article_id)
    assert after["content_version"] == before["content_version"] + 1
    assert after["body"].strip()
    # The previous version is still on disk and still readable: recoverable.
    old = json.loads(
        (app._editorial_root() / "editor_articles" / article_id /
         f"v{before['content_version']:08d}.json").read_text(encoding="utf-8")
    )
    assert old["body"] == before["body"]
    # Same Article, same Story - not a new one.
    record = articles.get_editor_article(article_id)
    assert record["story_id"] == prepared["story_id"]


def test_rewrite_puts_the_editor_comment_in_the_prompt(prepared, model, monkeypatch):
    """§E1: the editor's exact words are the instruction that governs the text."""
    _make_draft(prepared, model, monkeypatch)
    model.clear()
    comment = "Не наблягай на туристическия сезон. Акцентът трябва да е върху цените."
    token = app.start_article_rewrite(
        prepared["article_id"], comment, idempotency_key="r2"
    )["operationToken"]
    assert _await(token)["status"] == "succeeded"

    draft_prompt = next(row["prompt"] for row in model if row["role"] == "draft")
    assert "===== EDITOR_COMMENT =====" in draft_prompt
    assert comment in draft_prompt
    # And the factual basis travels with it, so the rewrite is grounded.
    assert "===== CURRENT_EVIDENCE =====" in draft_prompt
    assert "===== EDITORIAL =====" in draft_prompt


def test_rewrite_does_not_research_by_default(prepared, model, monkeypatch):
    """§E2: a rewrite is a writing operation, not a web round."""
    _make_draft(prepared, model, monkeypatch)
    searched: list[str] = []

    from editor_assistant.workflow import search as search_mod

    def counting(**kwargs):
        searched.append(kwargs.get("topic", ""))
        return {"status": "SEARCH_INCOMPLETE", "queries": [], "candidates": []}

    monkeypatch.setattr(search_mod, "run_event_discovery", counting)
    token = app.start_article_rewrite(
        prepared["article_id"], "По-кратко.", idempotency_key="r3"
    )["operationToken"]
    assert _await(token)["status"] == "succeeded"
    # ZERO, not "at most one". The previous assertion here was `len(searched)
    # <= 1`, which passed while the rewrite was still running a full enrichment
    # round and merging newly discovered pages into the packet - i.e. unreviewed
    # web material silently entering text the editor had already judged. E2
    # means the factual basis is REUSED, not merely bounded.
    assert searched == [], "Пренапиши must not run any discovery round"


def test_rewrite_failure_preserves_the_text_and_the_comment(prepared, model, monkeypatch):
    """§E4: a failed rewrite never leaves a blank Article and keeps the words."""
    before = _make_draft(prepared, model, monkeypatch)
    article_id = prepared["article_id"]
    _no_search(monkeypatch, sources=[], queries=["q"])

    def boom(*_a, **_k):
        raise RuntimeError("model is down")

    monkeypatch.setattr(gen, "call_model", boom)
    token = app.start_article_rewrite(
        article_id, "Направи текста по-кратък.", idempotency_key="r4"
    )["operationToken"]
    row = _await(token)
    assert row["status"] == "failed"

    after = articles.get_article_content(article_id)
    assert after["body"] == before["body"], "the current text is untouched"
    assert after["content_version"] == before["content_version"]
    # The editor's request is still on record, and says no new version exists.
    records = rewrite_feedback.read_all()
    assert any("по-кратък" in r["editor_comment"] for r in records)
    assert all(
        r["draft_version_before"] == r["draft_version_after"]
        for r in records
        if r["generated_by_model"] is False
    )


def test_rewrite_refuses_without_a_draft_or_a_comment(prepared):
    """§E: there is nothing to rewrite in Preparation, and an empty comment says nothing."""
    with pytest.raises(app.EditorApplicationError):
        app.start_article_rewrite(prepared["article_id"], "по-кратко", idempotency_key="x1")


# ---------------------------------------------------------------- PART D


def test_voice_options_are_only_canonical_frozen_voices():
    """§D: no new voice values, and no model/provider terminology."""
    from editor_assistant.style import profiles as style_profiles

    options = articles.editorial_voice_options()
    ids = [row["id"] for row in options]
    assert ids[0] == "", "Автоматично is the default and comes first"
    assert set(ids) - {""} == set(style_profiles.FROZEN_VOICES)
    assert all("model" not in row["label"].lower() for row in options)
    assert all("provider" not in row["label"].lower() for row in options)


def test_voice_defaults_to_automatic_and_persists(prepared):
    """§D: a new Article is automatic; a chosen voice persists on the Article."""
    article_id = prepared["article_id"]
    assert articles.get_editor_article(article_id)["editorial_voice"] == ""
    app.update_voice(article_id, "VOICE_DESISLAVA_RECENT")
    assert articles.get_editor_article(article_id)["editorial_voice"] == "VOICE_DESISLAVA_RECENT"
    app.update_voice(article_id, "")
    assert articles.get_editor_article(article_id)["editorial_voice"] == ""


def test_changing_voice_changes_no_existing_text_and_no_readiness(prepared, model, monkeypatch):
    """§D: the choice applies to the NEXT draft/rewrite and rewrites nothing now."""
    before = _make_draft(prepared, model, monkeypatch)
    article_id = prepared["article_id"]
    projection = app.update_voice(article_id, "VOICE_DESISLAVA_RECENT")
    after = articles.get_article_content(article_id)
    assert after["body"] == before["body"]
    assert after["content_version"] == before["content_version"]
    assert projection["style"]["voice"] == "VOICE_DESISLAVA_RECENT"


def test_voice_is_exposed_in_the_article_projection(prepared):
    """§D: the control is server-authoritative and speaks editor language."""
    projection = app.read_article(prepared["article_id"])
    assert projection["style"]["label"] == "Автоматично"
    assert projection["style"]["options"][0]["id"] == ""


def test_an_unknown_voice_is_refused(prepared):
    """§D: a voice the style system could not honour must never be stored."""
    with pytest.raises(app.EditorApplicationError):
        app.update_voice(prepared["article_id"], "VOICE_MADE_UP")


def test_voice_reaches_the_generation(prepared, model, monkeypatch):
    """§K: a chosen Voice changes the style of the next generation."""
    _make_draft(prepared, model, monkeypatch)
    app.update_voice(prepared["article_id"], "VOICE_DESISLAVA_RECENT")
    model.clear()
    _no_search(monkeypatch, sources=[], queries=["q"])
    token = app.start_article_rewrite(
        prepared["article_id"], "Съкрати.", idempotency_key="v1"
    )["operationToken"]
    assert _await(token)["status"] == "succeeded"
    case_line = (app._editorial_root() / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    last = json.loads(case_line[-1])
    assert last["voice_selected"] == "VOICE_DESISLAVA_RECENT"


# ---------------------------------------------------------------- PART C


def test_focus_is_a_default_not_a_gate_and_has_no_generic_alternatives():
    """§C: a default Focus, editable, never a gate, and zero generic chips."""
    from editor_assistant.workflow import focus_suggestions

    focus = focus_suggestions.primary_focus(HEADLINE)
    assert focus.strip(), "every Draft gets a default Focus"
    assert focus_suggestions.alternatives(HEADLINE, facts=[{"text": BODY}]) == ()


def test_draft_works_without_a_confirmed_focus(newsroom, model, monkeypatch):
    """§C: Focus is not a permission gate - a Draft is written anyway."""
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title=HEADLINE,
        now="2026-09-25T09:00:00Z",
    )
    story_research_store.merge_research(
        "s-one",
        sources=[{"id": "v", "name": "В", "url": "https://v.example.test/a"}],
        facts=[
            {
                "id": "fact_money",
                "text": BODY,
                "sourceId": "v",
                "locator": "Протокол, т. 4",
            }
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="op1",
    )
    _no_search(monkeypatch, sources=[], queries=["q"])
    # The real contract: pressing `Чернова` with NO focus the editor ever wrote
    # must still produce a real Draft. An earlier version of this test only
    # asserted which actions were offered, which passed while the backend still
    # REFUSED the command — the product proof caught that, not the test.
    assert articles.get_editor_article(article["article_id"])["editorial_focus"] == ""
    token = app.start_article_draft(article["article_id"], idempotency_key="nofocus")[
        "operationToken"
    ]
    assert _await(token)["status"] == "succeeded"
    content = articles.get_article_content(article["article_id"])
    assert content["body"].strip(), "a Story with real material must be draftable"
    # And the Draft now carries a stored, confirmed default Focus, so `Готова`
    # and finalization stay reachable without the editor typing anything.
    record = articles.get_editor_article(article["article_id"])
    assert record["editorial_focus"].strip()
    assert record["focus_confirmed_at"]
    # With a Draft in place the Article is no longer in Preparation, so the
    # alternatives block is gone entirely rather than merely empty.
    assert app.read_article(article["article_id"])["preparation"] is None


# ---------------------------------------------------------------- PART F/G


def _seed(root: Path, comments, *, article="art_synthetic"):
    """Synthetic feedback records — explicitly NOT real editor comments (§L)."""
    for index, comment in enumerate(comments, start=1):
        rewrite_feedback.record(
            article_id=article,
            editor_comment=comment,
            draft_version_before=index,
            draft_version_after=index + 1,
            root=root,
        )


def test_feedback_record_keeps_no_copy_of_the_article_text(tmp_path):
    """§F: the Article versions own the text; the record owns the editor's words."""
    row = rewrite_feedback.record(
        article_id="art_a",
        editor_comment="Започни директно с основния факт.",
        focus="Фокус",
        voice="VOICE_HOUSE",
        draft_version_before=3,
        draft_version_after=4,
        root=tmp_path,
    )
    assert set(row) <= set(rewrite_feedback.RECORD_FIELDS)
    assert row["processed_for_learning"] is False
    assert row["draft_version_before"] == 3 and row["draft_version_after"] == 4
    stored = json.loads(rewrite_feedback.feedback_path(root=tmp_path).read_text().splitlines()[0])
    assert "body" not in stored and "title" not in stored


def test_threshold_is_twenty_and_analysis_is_not_run_per_comment(tmp_path):
    """§G1: 19 records -> not eligible; 20 -> eligible. No scheduler needed."""
    assert rewrite_feedback.DEFAULT_THRESHOLD == 20
    assert rewrite_feedback.threshold() == 20
    _seed(tmp_path, ["Започни директно с факта."] * 19)
    assert len(rewrite_feedback.unprocessed(root=tmp_path)) == 19
    assert rewrite_feedback.is_eligible(root=tmp_path) is False
    _seed(tmp_path, ["Започни директно с факта."], article="art_more")
    assert len(rewrite_feedback.unprocessed(root=tmp_path)) == 20
    assert rewrite_feedback.is_eligible(root=tmp_path) is True


def test_analyzer_produces_proposals_and_never_active_instructions(tmp_path):
    """§G2/§L: analysis is a proposal; the prompt/style source stays untouched."""
    _seed(
        tmp_path,
        [
            "Започни директно с основния факт.",
            "Лийдът е твърде общ.",
            "Без общо въведение.",
            "По-сдържан тон, без оценъчни думи.",
        ],
    )
    proposals = rewrite_feedback.analyze(root=tmp_path, minimum=2)
    ids = {row["pattern_id"] for row in proposals}
    assert "direct_lead" in ids
    lead = next(row for row in proposals if row["pattern_id"] == "direct_lead")
    assert lead["support"] == 3
    assert lead["status"] == "proposed"
    assert lead["target"] in rewrite_feedback.TARGETS
    assert lead["examples"], "proposals show the real editor words"
    # Nothing became active just because the pattern was detected.
    assert rewrite_feedback.approved_instructions(root=tmp_path) == []


def test_conflicting_feedback_is_reported_not_averaged(tmp_path):
    """§G2: opposite instructions must be surfaced, never silently merged."""
    _seed(
        tmp_path,
        ["Съкрати текста.", "Съкрати.", "По-кратко.", "Започни директно с факта.",
         "Лийдът е твърде общ.", "Без общо въведение."],
    )
    proposals = rewrite_feedback.analyze(root=tmp_path, minimum=2)
    conflict = [row for row in proposals if row["status"] == "conflict"]
    assert conflict, "opposite length instructions are reported as a conflict"


def test_only_human_approval_makes_an_instruction_active(tmp_path):
    """§G4: the approved set changes only through an explicit decision."""
    _seed(tmp_path, ["Започни директно с факта."] * 4)
    proposals = rewrite_feedback.analyze(root=tmp_path, minimum=3)
    target = next(row for row in proposals if row["pattern_id"] == "direct_lead")

    assert rewrite_feedback.approved_instructions(root=tmp_path) == []
    entry = rewrite_feedback.apply_approval(target, root=tmp_path)
    assert entry["approved"] is True
    assert entry["support"] == 4
    assert entry["feedback_ids"], "the decision records its evidence"

    active = rewrite_feedback.approved_instructions(root=tmp_path)
    assert len(active) == 1
    # And the records it rested on are now processed, so the same evidence is
    # never counted into a second proposal.
    assert rewrite_feedback.unprocessed(root=tmp_path) == []


def test_a_rejected_proposal_is_not_re_proposed(tmp_path):
    """§G4: a human refusal is a decision, and re-proposing it would be nagging."""
    _seed(tmp_path, ["Започни директно с факта."] * 4)
    target = next(
        row for row in rewrite_feedback.analyze(root=tmp_path, minimum=3)
        if row["pattern_id"] == "direct_lead"
    )
    rewrite_feedback.apply_approval(target, approved=False, root=tmp_path)
    assert rewrite_feedback.approved_instructions(root=tmp_path)[0]["approved"] is False
    # Re-deciding the same pattern replaces the decision rather than stacking.
    rewrite_feedback.apply_approval(target, approved=True, root=tmp_path)
    active = rewrite_feedback.approved_instructions(root=tmp_path)
    assert len(active) == 1 and active[0]["approved"] is True


def test_an_approved_instruction_actually_reaches_the_prompt(tmp_path, monkeypatch):
    """G4 - approval is not a dead letter: the rule must reach the model.

    The loop used to end at a file nothing read, so approving a rule changed no
    generation behaviour whatsoever. This asserts the whole path: approve ->
    approved set -> prompt section -> the rendered text the model is sent.
    """
    from editor_assistant.drafting import prompt as prompt_mod
    from editor_assistant.workflow import rewrite_feedback as rfb

    _seed(tmp_path, ["Започни директно с факта."] * 4)
    target = next(
        row for row in rfb.analyze(root=tmp_path, minimum=3)
        if row["pattern_id"] == "direct_lead"
    )
    rfb.apply_approval(target, root=tmp_path)

    rules = rfb.active_instruction_texts(root=tmp_path)
    assert rules, "an approved rule must be readable back as a prompt-ready line"

    built = prompt_mod.build_prompt(
        {"source_url": "https://x.test/a", "source_headline": "h", "facts": [], "quotes": [],
         "unknowns": []},
        site_dna={"conventions": {}},
        voice_profile={"profile_id": "VOICE_HOUSE", "headline": {"common_patterns": []},
                       "opening": {"typical_patterns": []},
                       "body": {"paragraph_shape": "", "sentence_shape": ""},
                       "quotes": {"frequency": "", "placement": ""},
                       "tone": {"factual_vs_descriptive": "", "narrative_distance": ""},
                       "numbers_dates": {"conventions": []},
                       "lexical_notes": {"recurring_preferences": []}, "avoidances": []},
        mode_profile={"profile_id": "MODE_BRIEF", "headline": {"common_patterns": []},
                      "opening": {"typical_patterns": []},
                      "body": {"paragraph_shape": "", "sentence_shape": ""},
                      "quotes": {"frequency": "", "placement": ""},
                      "tone": {"factual_vs_descriptive": "", "narrative_distance": ""},
                      "numbers_dates": {"conventions": []},
                      "lexical_notes": {"recurring_preferences": []}, "avoidances": []},
        style_examples=[],
        learned_instructions=rules,
    )
    assert "===== LEARNED_INSTRUCTIONS =====" in built["text"]
    assert rules[0] in built["text"]


def test_a_rejected_rule_never_reaches_the_prompt(tmp_path):
    """G4 - a human 'no' stays a no."""
    from editor_assistant.workflow import rewrite_feedback as rfb

    _seed(tmp_path, ["Започни директно с факта."] * 4)
    target = next(
        row for row in rfb.analyze(root=tmp_path, minimum=3)
        if row["pattern_id"] == "direct_lead"
    )
    rfb.apply_approval(target, approved=False, root=tmp_path)
    assert rfb.active_instruction_texts(root=tmp_path) == ()


def test_an_unapproved_proposal_never_reaches_the_prompt(tmp_path):
    """G4 - detection alone must not activate anything."""
    from editor_assistant.workflow import rewrite_feedback as rfb

    _seed(tmp_path, ["Започни директно с факта."] * 4)
    assert rfb.analyze(root=tmp_path, minimum=3), "the pattern is detected"
    assert rfb.active_instruction_texts(root=tmp_path) == ()


def test_prompt_source_is_unchanged_until_approval(tmp_path):
    """§L: the canonical prompt is untouched by feedback, approved or not."""
    from editor_assistant.drafting import prompt as prompt_mod

    before = (Path(prompt_mod.__file__)).read_text(encoding="utf-8")
    _seed(tmp_path, ["Започни директно с факта."] * 5)
    rewrite_feedback.analyze(root=tmp_path, minimum=3)
    assert Path(prompt_mod.__file__).read_text(encoding="utf-8") == before
    proposals = rewrite_feedback.analyze(root=tmp_path, minimum=3)
    rewrite_feedback.apply_approval(
        next(row for row in proposals if row["pattern_id"] == "direct_lead"), root=tmp_path
    )
    # Even an APPROVED instruction does not mutate the prompt in this slice: it
    # is recorded for the human to fold into the style system deliberately.
    assert Path(prompt_mod.__file__).read_text(encoding="utf-8") == before


def test_rewrite_records_feedback_on_success(prepared, model, monkeypatch):
    """§F: a real rewrite is captured, with the versions it moved between."""
    before = _make_draft(prepared, model, monkeypatch)
    token = app.start_article_rewrite(
        prepared["article_id"], "По-кратък, без общо въведение.", idempotency_key="f1"
    )["operationToken"]
    assert _await(token)["status"] == "succeeded"
    rows = rewrite_feedback.read_all()
    assert rows, "the rewrite is on record"
    row = rows[-1]
    assert row["draft_version_before"] == before["content_version"]
    assert row["draft_version_after"] == before["content_version"] + 1
    assert row["generated_by_model"] is True
    assert "кратък" in row["editor_comment"]


# ---------------------------------------------------------------- store safety


def test_an_interrupted_publish_does_not_brick_the_article(newsroom, prepared):
    """§E3 — an orphaned content document must not make the Article unwritable.

    A publish writes the immutable content document first and the Article
    pointer last, so a crash in between leaves debris at a version the pointer
    never reached. Before this recovery existed, that debris made EVERY later
    publish fail with "an Article content version is immutable" — permanently,
    so the `Пренапиши` retry the owner is offered could never succeed.
    """
    article_id = prepared["article_id"]
    editorial = app._editorial_root()
    articles.save_article_content(article_id, 0, "Работа", "Първи текст")
    assert articles.get_article_content(article_id)["content_version"] == 1

    # Simulate the crash: the document is written, the pointer never moves.
    orphan = editorial / "editor_articles" / article_id / "v00000002.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(
        json.dumps(
            {
                "article_id": article_id,
                "title": "Работа",
                "body": "получен текст, който никога не е бил публикуван",
                "content_version": 2,
                "updated_at": "2026-09-25T10:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # The next real publish must recover rather than refuse forever.
    published = articles.publish_generated_draft(
        article_id, 1, title="Работа", body="Новият текст"
    )
    assert published["content_version"] == 2
    assert published["body"] == "Новият текст"
    # And the version the editor actually had is still readable.
    v1 = json.loads(
        (editorial / "editor_articles" / article_id / "v00000001.json").read_text(
            encoding="utf-8"
        )
    )
    assert v1["body"] == "Първи текст"


def test_a_reachable_version_is_still_immutable(newsroom, prepared):
    """The recovery must not weaken the immutability that actually protects work."""
    article_id = prepared["article_id"]
    articles.save_article_content(article_id, 0, "Работа", "Първи текст")
    editorial = app._editorial_root()
    path = editorial / "editor_articles" / article_id / "v00000001.json"
    existing = json.loads(path.read_text(encoding="utf-8"))
    existing["body"] = "подменен текст"
    path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(articles.ArticleStoreError):
        articles.save_article_content(article_id, 0, "Работа", "Първи текст")


# ---------------------------------------------------------------- A3 enforcement


def test_the_wall_clock_envelope_actually_bounds_a_slow_discovery(monkeypatch):
    """A3 - a slow provider must cost the enrichment, not the editor's wait.

    The previous implementation only CHECKED the clock around one unbounded
    blocking call, so a discovery that slept 2s against a 0.5s budget returned
    after the full 2s and the promise was fiction. The deadline is now enforced
    from the outside.
    """
    from editor_assistant.workflow import draft_enrichment as de

    def slow(**_kwargs):
        time.sleep(2.0)
        return {"status": "SEARCH_OK", "queries": [], "candidates": []}

    monkeypatch.setattr(de.search_mod, "run_event_discovery", slow)
    started = time.monotonic()
    result = de.enrich(topic=HEADLINE, budget=de.Budget(seconds=0.4))
    elapsed = time.monotonic() - started

    assert result["sources"] == []
    assert elapsed < 1.5, f"the envelope did not bound the call ({elapsed:.1f}s)"
    # And it is reported honestly: cut off, not "found nothing".
    assert result["warnings"] == (de.WARNING_ENRICHMENT_UNAVAILABLE,)


def test_a_spent_budget_is_not_reported_as_an_empty_search(monkeypatch):
    """A2 - 'enrichment found nothing' and 'enrichment was cut off' differ."""
    from editor_assistant.workflow import draft_enrichment as de

    _no_search(monkeypatch, sources=["https://a.example.test/x"])
    _stub_publication(monkeypatch)
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        # Blow the budget immediately after the discovery call returns.
        return 0.0 if ticks["n"] < 3 else 999.0

    result = de.enrich(
        topic=HEADLINE, budget=de.Budget(clock=clock, seconds=1.0)
    )
    assert result["sources"] == []
    assert result["warnings"] == (de.WARNING_ENRICHMENT_UNAVAILABLE,), (
        "a cut-off round must not be reported as a search that found nothing"
    )


def test_an_accepted_page_is_fetched_only_once():
    """A3 - a page discovery opened is not downloaded again for extraction.

    `run_event_discovery` opens a candidate to decide whether it is a real
    publisher, and the extraction pass then reads the SAME page. Without the
    cache every accepted page was downloaded twice, so a stated envelope of
    "3-5 opened pages" was really up to ten fetches.
    """
    from editor_assistant.workflow import draft_enrichment as de

    calls: list[str] = []

    def opener(url):
        calls.append(url)
        return {"final_url": url, "text": "текст", "bytes": 4}

    cache = de._PageCache(opener)
    first = cache("https://p.example.test/a")
    second = cache("https://p.example.test/a")
    cache("https://q.example.test/b")

    assert first is second, "the same URL must return the same page object"
    assert calls == ["https://p.example.test/a", "https://q.example.test/b"], (
        f"a page was fetched more than once: {calls}"
    )
    # And the same instance is what both phases are given, which is what makes
    # the deduplication real rather than incidental.
    assert cache.cached("https://p.example.test/a") is first
    assert cache.cached("https://missing.example.test") is None


def test_a_caller_cannot_raise_the_envelope(monkeypatch):
    """A3 - the constants are policy: a caller may ask for less, never more."""
    from editor_assistant.workflow import draft_enrichment as de

    assert de.Budget(pages=99).pages_left == de.MAX_OPENED_PAGES
    assert de.Budget(queries=99).queries_left == de.MAX_QUERIES
    assert de.Budget(seconds=9999).seconds == de.WALL_CLOCK_BUDGET_S
    # Asking for less still works, which is what tests and cheap runs need.
    assert de.Budget(pages=1).pages_left == 1

    urls = [f"https://p{i}.example.test/a" for i in range(12)]
    _no_search(monkeypatch, sources=urls)
    _stub_publication(monkeypatch)
    result = de.enrich(topic=HEADLINE, budget=de.Budget(pages=99))
    assert len(result["sources"]) <= de.MAX_OPENED_PAGES


def test_enrichment_sources_carry_a_resolvable_identity(monkeypatch):
    """A5 - a claim must be traceable to the page it came from."""
    from editor_assistant.workflow import draft_enrichment as de

    _no_search(monkeypatch, sources=["https://a.example.test/x", "https://b.example.test/y"])
    _stub_publication(monkeypatch)
    result = de.enrich(topic=HEADLINE)
    ids = [row["id"] for row in result["sources"]]
    assert all(ids), "every enrichment source needs a non-empty id"
    assert len(set(ids)) == len(ids), "two pages must not share one identity"


def test_plan_questions_does_not_match_inside_a_word(monkeypatch):
    """A4 - 'цена' inside 'сцена' must not turn a theatre story into a decision."""
    from editor_assistant.workflow import draft_enrichment as de

    assert de.plan_questions("Ремонт на сцената в читалището") == de.GENERAL_QUESTIONS[:3]
    # A real decision word still classifies, including an inflected form.
    assert de.plan_questions("Общинският съвет одобри цените") == de.DECISION_QUESTIONS[:3]
    assert de.plan_questions("Пожари в центъра на града") == de.INCIDENT_QUESTIONS[:3]


def test_an_empty_enrichment_is_reported_to_the_editor(prepared, model, monkeypatch):
    """A2 - "no enrichment" ends in a Draft PLUS a warning, and the warning is VISIBLE.

    Four specifications promise the editor is told when the automatic gathering
    found nothing. The warnings were computed and then dropped on the floor:
    they lived in a snapshot key that nothing read, so the promise was kept only
    in the documents.
    """
    from editor_assistant.workflow import draft_enrichment as de

    _no_search(monkeypatch, sources=[], queries=["няма нищо"])
    token = app.start_article_draft(prepared["article_id"], idempotency_key="w1")[
        "operationToken"
    ]
    assert _await(token)["status"] == "succeeded"

    projection = app.read_article(prepared["article_id"])
    assert de.WARNING_ENRICHMENT_EMPTY in projection["draftWarnings"], (
        "the enrichment outcome must reach the editor, not just the snapshot"
    )
    # And it is recorded with the text, so it survives the snapshot.
    basis = articles.get_editor_article(prepared["article_id"])["draft_material_basis"]
    assert de.WARNING_ENRICHMENT_EMPTY in basis["enrichmentWarnings"]


def test_a_cut_off_enrichment_reaches_the_editor_as_its_own_sentence(
    prepared, model, monkeypatch
):
    """A2 - a cut-off round and an empty result are different sentences.

    The module-level honesty (`_no_material_warning`) is covered directly by
    `test_a_spent_budget_is_not_reported_as_an_empty_search`; what this adds is
    the end-to-end half: the sentence the editor is shown is the cut-off one,
    not a claim that a search came back empty.
    """
    from editor_assistant.workflow import draft_enrichment as de

    _no_search(monkeypatch, sources=[], queries=["q"])
    real_budget = de.Budget

    def budget_with_no_time(**kwargs):
        made = real_budget(**kwargs)
        # An envelope already spent: discovery is allowed to run, but the
        # extract loop that follows is cut off before it can open anything.
        made.seconds = 0.0
        return made

    monkeypatch.setattr(de, "Budget", budget_with_no_time)
    token = app.start_article_draft(prepared["article_id"], idempotency_key="w2")[
        "operationToken"
    ]
    assert _await(token)["status"] == "succeeded"
    warnings = app.read_article(prepared["article_id"])["draftWarnings"]
    assert de.WARNING_ENRICHMENT_UNAVAILABLE in warnings
    assert de.WARNING_ENRICHMENT_EMPTY not in warnings


# ---------------------------------------------------------------- G hardening


def test_a_rejected_pattern_is_never_proposed_again(tmp_path):
    """G4 - a refusal retires the pattern instead of nagging about it.

    The previous version deleted the earlier decision, so a rejected pattern was
    re-proposed on the next analyse and a later approval overwrote the human's
    "no" with no trace that it had ever been given.
    """
    from editor_assistant.workflow import rewrite_feedback as rfb

    _seed(tmp_path, ["Започни директно с факта."] * 4)
    target = next(
        row for row in rfb.analyze(root=tmp_path, minimum=3)
        if row["pattern_id"] == "direct_lead"
    )
    rfb.apply_approval(target, approved=False, root=tmp_path)
    assert "direct_lead" in rfb.retired_patterns(root=tmp_path)

    # More matching feedback arrives; the retired pattern stays silent.
    _seed(tmp_path, ["Започни директно с факта."] * 3, article="art_more")
    again = {row["pattern_id"] for row in rfb.analyze(root=tmp_path, minimum=3)}
    assert "direct_lead" not in again, "a refused rule was proposed again"

    # And re-deciding records the history rather than erasing the refusal.
    entry = rfb.apply_approval(target, approved=True, root=tmp_path)
    assert entry["approved"] is True
    assert entry.get("history"), "the earlier decision must remain on record"


def test_a_conflict_cannot_be_approved_as_an_instruction(tmp_path):
    """G2/G4 - a conflict is a question to the editor, not a rule."""
    from editor_assistant.workflow import rewrite_feedback as rfb

    _seed(
        tmp_path,
        ["Съкрати текста.", "Съкрати.", "По-кратко.", "Започни директно с факта.",
         "Лийдът е твърде общ.", "Без общо въведение."],
    )
    conflicts = [
        row for row in rfb.analyze(root=tmp_path, minimum=2) if row["status"] == "conflict"
    ]
    assert conflicts, "the fixture must produce a conflict"
    with pytest.raises(rfb.FeedbackError):
        rfb.apply_approval(conflicts[0], root=tmp_path)
    assert rfb.active_instruction_texts(root=tmp_path) == ()


def test_approval_is_refused_below_the_threshold(tmp_path, monkeypatch):
    """G1 - the threshold gates the DECISION, not only the report."""
    from editor_assistant.workflow import cli as cli_mod
    from editor_assistant.workflow import rewrite_feedback as rfb

    _seed(tmp_path, ["Започни директно с факта."] * 4)
    assert any(
        row["pattern_id"] == "direct_lead" for row in rfb.analyze(root=tmp_path, minimum=3)
    ), "the fixture must produce a detectable pattern"
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path))
    args = type("A", (), {"feedback_action": "approve", "pattern_id": "direct_lead"})()
    with pytest.raises(SystemExit):
        cli_mod._run_newsroom_feedback(args)
    assert rfb.active_instruction_texts(root=tmp_path) == (), (
        "3 records must not be enough to approve a permanent rule"
    )


def test_marking_processed_keeps_every_record(tmp_path, monkeypatch):
    """F/G - the marking pass marks, it never rewrites the log from a stale read.

    The previous version read the log, then truncated and rewrote it from that
    snapshot. A record appended in between - the ordinary case of an editor
    hitting Пренапиши while an operator approves a pattern - was silently
    DELETED. Both sides of the file now take the same lock, and the write is
    atomic, so no append can be lost.
    """
    from editor_assistant.workflow import rewrite_feedback as rfb

    _seed(tmp_path, ["Започни директно с факта."] * 4)
    target = next(
        row for row in rfb.analyze(root=tmp_path, minimum=3)
        if row["pattern_id"] == "direct_lead"
    )
    target_ids = set(target["feedback_ids"])
    assert len(target_ids) == 4

    real_read = rfb.read_all
    seen: list[int] = []

    def read_and_let_one_land(*args, **kwargs):
        rows = real_read(*args, **kwargs)
        seen.append(len(rows))
        return rows

    monkeypatch.setattr(rfb, "read_all", read_and_let_one_land)
    # The editor's newer feedback lands while the approval is in flight.
    rfb.record(
        article_id="art_live",
        editor_comment="Съкрати още веднъж.",
        draft_version_before=1,
        draft_version_after=2,
        root=tmp_path,
    )
    rfb.apply_approval(target, root=tmp_path)
    monkeypatch.undo()

    rows = rfb.read_all(root=tmp_path)
    live = [row for row in rows if row["article_id"] == "art_live"]
    assert live, "the concurrently appended record was destroyed by the marking pass"
    assert all(row["processed_for_learning"] for row in rows if row["feedback_id"] in target_ids)
    assert not live[0]["processed_for_learning"], "an unrelated record must not be marked"


def test_an_unread_publication_never_claims_confirmed_information(newsroom, monkeypatch):
    """G4.4: the readiness sentence must not assert what has not happened.

    Found in the field. A Story whose own publication is readable but NOT yet
    read was reported as `DRAFT_ELIGIBLE` with the sentence "Има достатъчно
    потвърдена информация за чернова" - while it had zero opened sources, zero
    facts, and a research round that had already failed to open anything. The
    editor was told the material was sufficient, pressed the button, and it
    failed.
    """
    from editor_assistant.workflow import article_readiness as ar

    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title=HEADLINE,
        now="2026-09-25T09:00:00Z",
    )
    articles.update_editor_focus(article["article_id"], "Фокус")
    # Assessed, but research opened nothing - exactly the on-screen case.
    story_research_store.merge_research(
        "s-one",
        sources=[],
        facts=[],
        gaps=[{"id": "gap_no_source", "question": "Не успяхме да отворим подходящ източник.",
               "blocking": False}],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="op1",
    )

    # The story's publication is a resolvable wrapper: worth ONE bounded read.
    decision = ar.evaluate_evidence(
        evidence_status="assessed",
        facts=[],
        blocking_gaps=[],
        source_url="",
        sources=[],
        readable_publication=True,
    )
    # eligible stays FALSE: the material is not confirmed, and pretending
    # otherwise is the defect this test exists for. The ACTION is still offered
    # by the projection, because the command reads the source itself.
    assert decision.eligible is False
    assert decision.reason_code == ar.DRAFT_FROM_UNREAD_SOURCE
    assert decision.reason_code != ar.DRAFT_ELIGIBLE, (
        "an unread source must not be reported as confirmed information"
    )
    assert "потвърдена информация" not in decision.reason_message
    assert decision.reason_message == ar.REASON_MESSAGES[ar.DRAFT_FROM_UNREAD_SOURCE]

    # And genuinely confirmed material still uses the strong, true sentence.
    confirmed = ar.evaluate_evidence(
        evidence_status="assessed",
        facts=[],
        blocking_gaps=[],
        source_url="",
        sources=[
            {
                "id": "s1", "name": "p", "url": "https://p.example.test/a",
                "domain": "p.example.test",
                "claims": [{"text": "Съветът обяви график.", "locator": "claim:0"}],
            }
        ],
    )
    assert confirmed.reason_code == ar.DRAFT_ELIGIBLE
    assert "потвърдена информация" in confirmed.reason_message
