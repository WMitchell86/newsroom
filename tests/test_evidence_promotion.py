"""V1.2-G2.3 §36: evidence promotion on the real research path.

These drive `execute_story_research` end to end with substituted outbound
edges, so the whole funnel is exercised: open -> extract -> quality-filter ->
promote -> persist. The safety rule is the V1.1-A rule, unchanged.
"""

from __future__ import annotations

import pytest

from editor_assistant.workflow import claim_equivalence as ce
from editor_assistant.workflow import claim_quality as cq
from editor_assistant.workflow import (
    inbox_store,
    search as search_mod,
    story_research,
    story_research_store,
    story_store,
)
from editor_assistant.sources import web_fetch

HEADLINE = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата"
#: §11 — the exact navigation chrome G2.1 promoted as its single "fact".
CHROME = cq.KNOWN_CHROME


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    item = {
        "item_id": "origin",
        "source_id": "vestnik",
        "source_item_id": "origin",
        "title": HEADLINE,
        "url": "https://vestnik.example.test/a",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": "",
        "source_kind": "media",
        "status": "NEW",
    }
    inbox_store.save_items([item], root / "inbox.jsonl")
    story = story_store.new_story(item, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    return root


def _run(newsroom, monkeypatch, pages, *, authority=None):
    """Run one research round over `pages`: {host: text}."""
    editorial = newsroom.parent / "editorial"

    class _Provider:
        name = "g23"

        def search(self, query, count=10, **_kw):
            return {
                "provider": self.name,
                "query": query,
                "requested_count": count,
                "started_at": "2026-09-25T11:00:00Z",
                "status": search_mod.SEARCH_OK,
                "attempt": 1,
                "http_status": 200,
                "retry_after": None,
                "elapsed_ms": 1,
                "results": [
                    {
                        "rank": index + 1,
                        "title": HEADLINE,
                        "url": f"https://{host}/article",
                        "snippet": "Общинският съвет одобри средствата.",
                        "published_at": "",
                        "source_name": host,
                    }
                    for index, host in enumerate(pages)
                ],
            }

    monkeypatch.setattr(
        search_mod, "provider_chain", lambda capability=None, env=None: ([_Provider()], [])
    )

    def _open(url, **_kw):
        host = url.split("/")[2]
        return {
            "final_url": url,
            "content_type": "text/html; charset=utf-8",
            "bytes": len(pages[host]),
            "text": pages[host],
        }

    monkeypatch.setattr(web_fetch, "fetch_page", _open)
    story_research.execute_story_research(
        "s-one",
        topic=HEADLINE,
        root=editorial,
        canonical_story={"story_id": "s-one"},
        page_opener=_open,
        story_title=HEADLINE,
        authority_resolver=authority if authority is not None else dict,
    )
    return story_research_store.get_story_research("s-one", root=editorial)


# ---------------------------------------------------------------------------
# §11 navigation chrome can never be a fact
# ---------------------------------------------------------------------------


def test_navigation_chrome_is_never_promoted(newsroom, monkeypatch):
    basis = _run(newsroom, monkeypatch, {"menu-site": CHROME})
    assert basis["facts"] == []
    assert CHROME not in " ".join(fact["text"] for fact in basis["facts"])


def test_chrome_alongside_a_real_claim_does_not_poison_it(newsroom, monkeypatch):
    # The real risk: a page that is mostly menu, with one real sentence. The
    # menu must not be promoted, and the real sentence still may be.
    text = f"{CHROME} Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
    basis = _run(newsroom, monkeypatch, {"menu-site": text})
    for fact in basis["facts"]:
        assert CHROME not in fact["text"]


# ---------------------------------------------------------------------------
# §2/§16 semantic corroboration
# ---------------------------------------------------------------------------


def test_one_publisher_alone_never_produces_a_fact(newsroom, monkeypatch):
    basis = _run(
        newsroom,
        monkeypatch,
        {
            "only-site": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
            "Ремонтът започна през октомври 2026 година."
        },
    )
    assert basis["facts"] == []


def test_two_independent_publishers_with_the_same_wording_corroborate(newsroom, monkeypatch):
    # The pre-G2.3 behaviour, preserved exactly.
    text = "Ремонтът на улицата започна през октомври 2026 година."
    basis = _run(newsroom, monkeypatch, {"site-a": text, "site-b": text})
    assert len(basis["facts"]) == 2
    assert all(gap["kind"] == "conflict" for gap in basis["gaps"])


def test_two_urls_on_the_same_publisher_are_one_source(newsroom, monkeypatch):
    # §8: a subdomain and its parent are the same publisher.
    text = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
    basis = _run(newsroom, monkeypatch, {"site-a": text, "site-a": text})
    assert basis["facts"] == []


def test_a_paraphrase_from_an_independent_publisher_can_corroborate(
    newsroom, monkeypatch
):
    # §2: the whole point of the slice. Two publishers, one proposition,
    # different wording. The semantic step is the only thing that can see it.
    monkeypatch.setattr(
        ce, "_default_semantic", lambda a, b: ce.SAME_FACT
    )
    basis = _run(
        newsroom,
        monkeypatch,
        {
            "site-a": "Ремонтът на улицата започна през октомври 2026 година.",
            "site-b": "Подновяването на улицата е започнало през октомври 2026 г.",
        },
    )
    assert len(basis["facts"]) == 2


def test_without_a_model_the_paraphrase_grants_nothing(newsroom, monkeypatch):
    # §29: PRIMARY sources must still work when the semantic route is dead, and
    # a paraphrase must NOT be promoted by a fallback.
    def _dead(*_args, **_kwargs):
        raise RuntimeError("no route")

    monkeypatch.setattr(ce, "_default_semantic", _dead)
    basis = _run(
        newsroom,
        monkeypatch,
        {
            "site-a": "Ремонтът на улицата започна през октомври 2026 година.",
            "site-b": "Подновяването на улицата е започнало през октомври 2026 г.",
        },
    )
    assert basis["facts"] == []


# ---------------------------------------------------------------------------
# §21 a conflict is never corroboration
# ---------------------------------------------------------------------------


def test_conflicting_quantities_do_not_corroborate_and_surface_a_question(
    newsroom, monkeypatch
):
    monkeypatch.setattr(ce, "_default_semantic", lambda a, b: ce.SAME_FACT)
    basis = _run(
        newsroom,
        monkeypatch,
        {
            "site-a": "При катастрофата на пътя пострадаха 3 души.",
            "site-b": "При катастрофата на пътя пострадаха 4 души.",
        },
    )
    assert basis["facts"] == []
    conflicts = [gap for gap in basis["gaps"] if gap["kind"] == "conflict"]
    assert conflicts, "a contradiction must be shown, not absorbed"
    # §23: the question is the real disagreement, in plain language.
    assert "3 души" in conflicts[0]["question"] and "4 души" in conflicts[0]["question"]


def test_a_conflict_is_detected_even_when_a_model_would_agree(newsroom, monkeypatch):
    # §5: a model may never talk a hard contradiction into agreement.
    monkeypatch.setattr(ce, "_default_semantic", lambda a, b: ce.SAME_FACT)
    basis = _run(
        newsroom,
        monkeypatch,
        {
            "site-a": "Ремонтът на улицата започна през октомври.",
            "site-b": "Ремонтът на улицата започна през ноември.",
        },
    )
    assert basis["facts"] == []


def test_a_decision_claim_is_not_corroborated_by_two_media_outlets(newsroom, monkeypatch):
    # §15 and the pre-existing M2S council guard: "the council approved X" needs
    # an official protocol/decision record, never two media articles however
    # well they agree. G2.3 makes the extractor strong enough to SEE these
    # claims, so it must be explicit that they are still not promotable.
    monkeypatch.setattr(ce, "_default_semantic", lambda a, b: ce.SAME_FACT)
    text = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
    basis = _run(newsroom, monkeypatch, {"site-a": text, "site-b": text})
    assert basis["facts"] == []
    # ...and the round still completes with a truthful reason, rather than
    # aborting on a ResearchError after pages had already been opened.
    assert basis["evidence_status"] == story_research_store.EVIDENCE_ASSESSED
    assert basis["gaps"]


# ---------------------------------------------------------------------------
# §1-A / §15 authoritative sources still work alone
# ---------------------------------------------------------------------------


def test_an_authoritative_source_promotes_its_own_claim(newsroom, monkeypatch):
    policy = {
        "official-muni.example.test": {
            "name": "Община Созопол",
            "kind": "official",
            "factual_authority": True,
        }
    }
    basis = _run(
        newsroom,
        monkeypatch,
        {"official-muni.example.test": "Общинският съвет одобри 1,2 милиона лева за ремонта."},
        authority=lambda: policy,
    )
    # The one path a decision claim may take: the official record itself.
    assert len(basis["facts"]) == 1
    assert basis["facts"][0]["text"].startswith("Общинският съвет одобри")


# ---------------------------------------------------------------------------
# §9 several candidate claims per page
# ---------------------------------------------------------------------------


def test_several_claims_are_taken_from_one_page(newsroom, monkeypatch):
    policy = {
        "official-muni.example.test": {
            "name": "Община Созопол",
            "kind": "official",
            "factual_authority": True,
        }
    }
    text = (
        "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
        "Ремонтът започна през октомври 2026 година. "
        "Кметът на града заяви, че работите вървят по график. "
        f"{CHROME}"
    )
    basis = _run(
        newsroom,
        monkeypatch,
        {"official-muni.example.test": text},
        authority=lambda: policy,
    )
    texts = [fact["text"] for fact in basis["facts"]]
    assert len(texts) >= 3, f"expected several claims, got {texts}"
    assert CHROME not in " ".join(texts)


# ---------------------------------------------------------------------------
# §30 the semantic stage is bounded
# ---------------------------------------------------------------------------


def test_comparisons_stay_bounded_per_round(newsroom, monkeypatch):
    calls = []

    def _counting(a, b):
        calls.append((a, b))
        return ce.UNCERTAIN

    monkeypatch.setattr(ce, "_default_semantic", _counting)
    pages = {
        f"site-{index}": " ".join(
            f"При катастрофата на пътя пострадаха {index + 1} души."
            f" Ремонтът започна през октомври 2026 година."
            f" Жителите ще пътуват с 10 минути повече до работата."
            f" В училището започнаха работите по новата ограда."
            for index in range(3)
        )
        for index in range(6)
    }
    _run(newsroom, monkeypatch, pages)
    assert len(calls) <= story_research.MAX_SEMANTIC_COMPARISONS, (
        f"the semantic stage must stay bounded, made {len(calls)} model calls"
    )
