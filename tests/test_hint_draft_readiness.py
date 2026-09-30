"""V1.2-G4.21 — what a hint Story can and cannot become. THE KNOWN LIMIT.

This is a capability test, not a defect: it records where the feature stops.

MEASURED. A Story created from an editor's hint cannot be promoted to an
Idea, and therefore can never produce a Draft:

    promote_story_to_idea(...)
    -> WorkbenchError: материалът не може да стане пакет:
       facts must be a non-empty list

A normally collected Story promotes fine, because `promote_story_to_idea`
builds the record body as `full_text or item.body or item.summary or ""`,
the workbench's promote call passes no `full_text`, and the collector
writes a snippet into `summary`. A hint row leaves `summary` empty — the
snippet is DISCOVERY_ONLY and must not be laundered into collected
material — so the body is empty and the packet has no facts.

The obvious fix was to fill `summary` from the opened page, using the
same `parse_article_html` the newsroom uses. That was measured against a
REAL page and does not work:

    fetch_page("https://www.cik.bg/")  -> 35351 bytes
    parse_article_html(...)            -> ArticleParseError:
                                         page has no usable headline + body

`parse_article_html` collects paragraphs from `entry-content` block frames
— it is an extractor for THIS newsroom's own site, not for arbitrary web
pages. There is no generic readability extractor anywhere in
`src/editor_assistant`. A synthetic <h1>+<p> document parses differently
from a real one, so the failure must be measured on a real page; the
synthetic version is what made this look fixable in the first place.

So today a hint gives the editor a LEAD — a real Story, with a real URL,
visible and promotable-looking — and writing from it is blocked. Building
the generic extractor is separate work and is not faked here.
"""

import json

import pytest

from editor_assistant.workflow import editor_hint, inbox_store, story_identity
from editor_assistant.workflow.workbench import state

ARTICLE_HTML = (
    "<html><head><title>ЦИК проверява машините</title></head><body>"
    "<article><h1>ЦИК проверява машините</h1>"
    "<p>Машините ще бъдат разпределени в страната.</p></article></body></html>"
)


def _result():
    r = editor_hint.HintResult(hint="проверка на машините")
    r.opened = [
        {
            "title": "ЦИК проверява машините",
            "url": "https://www.cik.bg/news/machines",
            "bytes": len(ARTICLE_HTML),
            "content_type": "text/html",
        }
    ]
    return r


def test_a_hint_story_is_a_real_visible_story(tmp_path, monkeypatch):
    """What the feature DOES deliver, kept honest so it is not overstated."""
    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    saved = editor_hint.materialise_hint_stories(
        _result(), inbox_path=newsroom / "inbox.jsonl", stories_path=newsroom / "stories.json"
    )
    assert len(saved) == 1
    assert saved[0]["story_id"].startswith("s")


def test_but_it_cannot_yet_be_promoted_to_a_draft(tmp_path, monkeypatch):
    """The known limit, asserted so it cannot be forgotten or assumed away.

    If this starts failing because promotion now succeeds, the blocker was
    genuinely fixed and this test should be replaced by the real thing — an
    end-to-end promotion. It is written as a failure on purpose.
    """
    from editor_assistant.workflow.workbench import state

    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "ed"))
    saved = editor_hint.materialise_hint_stories(
        _result(), inbox_path=newsroom / "inbox.jsonl", stories_path=newsroom / "stories.json"
    )
    with pytest.raises(Exception, match="facts must be a non-empty list"):
        state.promote_story_to_idea(
            saved[0]["story_id"],
            inbox_path=newsroom / "inbox.jsonl",
            stories_path=newsroom / "stories.json",
        )


def _collected_story(tmp_path, monkeypatch, *, url, summary, source_kind):
    """One collected (never-opened) inbox item, promoted to a real Story."""
    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "ed"))
    inbox = newsroom / "inbox.jsonl"
    stories = newsroom / "stories.json"
    item = {
        "item_id": "s1", "source_id": "gn", "source_item_id": "s1",
        "title": "Ремонт на улица", "url": url,
        "published_at": "", "event_at": "", "event_end_at": "",
        "discovered_at": "2026-09-30T10:00:00Z",
        "summary": summary, "source_kind": source_kind, "priority": "normal",
        "publisher_domain": "news.google.com", "publisher_kind": "",
        "factual_authority": False, "status": "NEW",
    }
    inbox_store.save_items([item], inbox)
    store = {"stories": []}
    story_identity.process_item(item, store, {"s1": item})
    stories.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    return store["stories"][0]["story_id"], inbox, stories


def test_a_search_snippet_never_becomes_a_fact(tmp_path, monkeypatch):
    """A DISCOVERY_ONLY summary must not reach the packet.

    The promote bridge used to read `summary` unconditionally, because the
    `candidate.get("body")` rung above it never matched -- `inbox_store.FIELDS`
    has no `body` field -- so a collected Story's RSS snippet fell straight
    through into `build_packet_from_record`, which turns every body sentence
    into a verbatim fact. Measured through that path: one news.google.com item
    produced `fact_count = 2`, with the wrapper URL as the packet's source.

    The selector's first pass ("prefer a material long enough to carry facts")
    was inert for the same reason and is gone.
    """
    story_id, inbox, stories = _collected_story(
        tmp_path, monkeypatch,
        url="https://news.google.com/rss/articles/CBMiK?oc=5",
        summary=(
            "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
            "Жителите на квартала ще пътуват с 10 минути повече до работа."
        ),
        source_kind="google_news_rss",
    )
    with pytest.raises(state.WorkbenchError, match="събрана само от търсене"):
        state.promote_story_to_idea(story_id, inbox_path=inbox, stories_path=stories)


def test_editor_supplied_text_is_still_a_valid_basis(tmp_path, monkeypatch):
    """`full_text` is the editor's own material, so it does not need a hint Story."""
    story_id, inbox, stories = _collected_story(
        tmp_path, monkeypatch,
        url="https://vestnik.example.test/a",
        summary="Кратко парче от търсенето.",
        source_kind="google_news_rss",
    )
    result = state.promote_story_to_idea(
        story_id, inbox_path=inbox, stories_path=stories,
        why_now="има решение", angle="следващата стъпка",
        full_text=(
            "Съветът гласува бюджета за ремонта на улицата. "
            "Работата започва през октомври след приключване на подготовката."
        ),
    )
    assert result["fact_count"] >= 1
