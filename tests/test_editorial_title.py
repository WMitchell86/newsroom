"""V1.2-G2.1 §A7 — the editorial headline is not a publisher name.

A publisher is *metadata*. Feeds decorate real headlines with their own brand
and this suite pins the boundary:

    a trailing segment is removed ONLY when structured identity data proves it
    is publisher decoration, and a real newsroom headline such as
    `Бургас - Поморие: затварят пътя` must survive completely untouched.

Every case here is one the slice could plausibly have got wrong - a blind
`rsplit(" - ", 1)` passes the first test and fails the rest.
"""

from __future__ import annotations

import pytest

from editor_assistant.workflow import (
    editor_application as app,
)
from editor_assistant.workflow import (
    editor_article_store as articles,
)
from editor_assistant.workflow import editorial_title as et
from editor_assistant.workflow import (
    inbox_store,
    quick_draft,
    sources_registry,
    story_operations,
    story_store,
)

RAW = "Община Поморие започва ремонта на пристанището - БНР"
CLEAN = "Община Поморие започва ремонта на пристанището"

REGISTRY = [
    {"source_id": "bnr-burgas", "name": "БНР Бургас", "domain": "bnr.bg", "kind": "media"},
    {
        "source_id": "pomorie-municipality",
        "name": "Община Поморие",
        "domain": "pomorie.bg",
        "kind": "official",
    },
    {
        "source_id": "darik-burgas",
        "name": "DarikNews Бургас",
        "domain": "dariknews.bg",
        "kind": "regional",
    },
    {
        "source_id": "chernomorski-far",
        "name": "Черноморски фар",
        "domain": "faragency.bg",
        "kind": "regional",
    },
]


def _identity(publisher_domain, registry=REGISTRY):
    return et.publisher_identity(publisher_domain=publisher_domain, registry_rows=registry)


# --------------------------------------------------------------------------
# the rule itself
# --------------------------------------------------------------------------


def test_removes_a_known_publisher_suffix():
    identity = _identity("bnr.bg")
    assert et.editorial_story_title(RAW, identity=identity) == CLEAN
    # The short brand is matched against the decorated registry name, and the
    # bare domain label is in the set too.
    assert "бнр бургас" in identity and "bnr" in identity


def test_removes_a_municipality_suffix():
    title = "Общината обяви нова чешма в центъра - Община Поморие"
    assert (
        et.editorial_story_title(title, identity=_identity("pomorie.bg"))
        == "Общината обяви нова чешма в центъра"
    )


def test_removes_a_source_domain_variant_when_the_publisher_matches():
    title = "Критичен недостиг на сестри в болниците - dariknews.bg"
    assert (
        et.editorial_story_title(title, identity=_identity("dariknews.bg"))
        == "Критичен недостиг на сестри в болниците"
    )


def test_removes_a_publisher_brand_that_is_not_in_the_registry():
    # A publisher the registry has never heard of still decorates its headline,
    # and its own domain is enough proof.
    title = "Кметът представи стратегия за болницата - BurgasMedia"
    assert (
        et.editorial_story_title(title, identity=_identity("burgasmedia.com"))
        == "Кметът представи стратегия за болницата"
    )


def test_keeps_a_legitimate_hyphenated_headline():
    for title in (
        "Катастрофа на пътя Бургас-Созопол разтрясва региона",
        "Пуснаха линията 12 - 14 след ремонта",
        "Две години по-късно всичко се промени",
    ):
        assert et.editorial_story_title(title, identity=_identity("bnr.bg")) == title


def test_keeps_a_clause_that_merely_contains_a_publisher_name():
    # The owner's counter-example: a real headline whose tail is not decoration.
    title = "Бургас - Поморие: затварят пътя"
    assert et.editorial_story_title(title, identity=_identity("pomorie.bg")) == title


def test_keeps_the_em_dash_inside_a_headline():
    title = "Две призови места за млада надежда на СК „Бушидо“ – Несебър"
    assert et.editorial_story_title(title, identity=_identity("bnr.bg")) == title


def test_keeps_a_publisher_name_that_appears_in_the_middle():
    title = "БНР излезе с позиция по бюджета на града"
    assert et.editorial_story_title(title, identity=_identity("bnr.bg")) == title


def test_keeps_a_title_with_no_known_publisher_unchanged():
    title = "Всекидневен разговор за утрешния ден"
    assert et.editorial_story_title(title, identity=set()) == title
    # A trailing segment nobody can attribute stays exactly as collected.
    decorated = "Двери се затвориха за ремонт - новини от Бургас и региона"
    assert et.editorial_story_title(decorated, identity=set()) == decorated


def test_strips_a_chained_publisher_decoration():
    title = "НХА и община обявиха партньорство - Черноморски фар - faragency.bg"
    identity = _identity("faragency.bg")
    assert et.editorial_story_title(title, identity=identity) == "НХА и община обявиха партньорство"


def test_discovery_source_does_not_grant_publisher_identity():
    """M4B.1: the feed that carried an item is never the publisher it names."""
    identity = et.publisher_identity(publisher_domain="www.faragency.bg", registry_rows=REGISTRY)
    # The official feed that discovered it (Община Поморие) is not in the set.
    assert "община поморие" not in identity
    assert "faragency" in identity


# --------------------------------------------------------------------------
# the handoff: Story -> Article
# --------------------------------------------------------------------------


def _item(item_id, title, *, source_id="bnr-burgas", publisher_domain="bnr.bg"):
    return {
        "item_id": item_id,
        "source_id": source_id,
        "source_item_id": item_id,
        "title": title,
        "url": "https://news.google.com/rss/articles/abc",
        "publisher_domain": publisher_domain,
        "publisher_kind": "media",
        "published_at": "2026-09-26T08:00:00Z",
        "discovered_at": "2026-09-26T08:00:00Z",
        "summary": "Обобщение",
        "source_kind": "media",
        "status": "NEW",
    }


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    sources_registry.add_source(
        path=root / "sources.json",
        source_id="bnr-burgas",
        name="БНР Бургас",
        kind="media",
        collector="rss",
        url="https://bnr.bg/feed",
        priority="high",
        factual_authority=True,
        domain="bnr.bg",
    )
    origin = _item("origin", RAW)
    inbox_store.save_items([origin], root / "inbox.jsonl")
    story = story_store.new_story(origin, now="2026-09-26T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    story_operations.clear()
    yield root
    story_operations.clear()
    for key in list(quick_draft._ACTIVE):
        quick_draft.release(key, quick_draft._ACTIVE[key])


def test_story_display_title_is_clean_but_the_publication_title_is_not(newsroom):
    detail = app.read_story("s-one")
    # §A5: the editor reads the clean headline.
    assert detail["title"] == CLEAN
    # §A2: the grouped publication keeps the exact collected string.
    assert detail["publications"][0]["title"] == RAW
    # ... and so does the stored source material itself.
    stored = inbox_store.read_items(newsroom / "inbox.jsonl")[0]
    assert stored["title"] == RAW


def test_an_article_started_from_the_story_gets_the_clean_title(newsroom):
    article = app.start_article("s-one", idempotency_key="g21-title-1")
    record = articles.get_editor_article(article["id"])
    assert record["working_title"] == CLEAN


def test_quick_draft_creates_its_article_with_the_same_clean_title(newsroom):
    article_id = app._create_quick_article("s-one", app._story("s-one"))
    assert article_id is not None
    assert articles.get_editor_article(article_id)["working_title"] == CLEAN


def test_an_existing_article_title_is_never_rewritten(newsroom):
    """§A6: only new Articles get the clean prefill."""
    article = app.start_article("s-one", idempotency_key="g21-title-2")
    articles.update_article_title(
        article["id"], 0, "Собствено заглавие на редактора", root=newsroom.parent / "editorial"
    )
    detail = app.read_story("s-one")
    related = next(row for row in detail["relatedArticles"] if row["id"] == article["id"])
    assert related["title"] == "Собствено заглавие на редактора"
    # Re-reading the Story never touches a stored Article title.
    assert articles.get_editor_article(article["id"])["working_title"] == (
        "Собствено заглавие на редактора"
    )


def test_the_research_query_uses_the_clean_title(newsroom):
    """§A5: the topic research searches for is the editorial title."""
    story = app._story("s-one")
    context = app._research_bootstrap_context(story, app._story_items())
    assert context["title"] == CLEAN
    assert " - БНР" not in context["title"]


def test_a_broken_registry_leaves_titles_exactly_as_collected(newsroom, monkeypatch):
    """A missing registry must never invent a title change."""
    (newsroom / "sources.json").unlink()
    et.clear_registry_cache()
    assert app.read_story("s-one")["title"] == RAW
    # A later read with a restored registry cleans the very same Story.
    sources_registry.add_source(
        path=newsroom / "sources.json",
        source_id="bnr-burgas",
        name="БНР Бургас",
        kind="media",
        collector="rss",
        url="https://bnr.bg/feed",
        priority="high",
        factual_authority=True,
        domain="bnr.bg",
    )
    assert app.read_story("s-one")["title"] == CLEAN


# --------------------------------------------------------------------------
# §C — the real product proof, end to end
# --------------------------------------------------------------------------


def test_c_the_real_handoff_has_no_source_suffix_anywhere(newsroom):
    """Every surface the editor and the workflow see, on one real Story."""
    # 1. The Publication keeps the exact collected headline — source material.
    detail = app.read_story("s-one")
    assert detail["publications"][0]["title"] == (
        "Община Поморие започва ремонта на пристанището - БНР"
    )
    # 2. The Story the editor reads carries the headline only.
    assert detail["title"] == "Община Поморие започва ремонта на пристанището"
    # 3. A manually started Article inherits the clean title.
    manual = app.start_article("s-one", idempotency_key="g21-proof-manual")
    assert articles.get_editor_article(manual["id"])["working_title"] == detail["title"]
    # 4. A Quick Draft Article gets exactly the same title.
    quick_id = app._create_quick_article("s-one", app._story("s-one"))
    assert articles.get_editor_article(quick_id)["working_title"] == detail["title"]
    # 5. The research topic that will be searched for is clean too.
    context = app._research_bootstrap_context(app._story("s-one"), app._story_items())
    assert context["title"] == detail["title"]
    # ... and no surface anywhere still ends in the publisher.
    for value in (detail["title"], context["title"]):
        assert " - БНР" not in value


def test_grouping_still_reads_the_raw_stored_title(newsroom):
    """§A2/A5: cleaning is presentation, never a store rewrite.

    The Story card used by grouping and the JEV replay keeps the raw collected
    headline. Grouping compares real source text, so silently rewriting the
    value it reads would change identity semantics to fix a display problem.
    """
    from editor_assistant.workflow import story_identity

    cards = story_identity.story_cards(
        inbox=app._paths()["inbox"], stories=app._paths()["stories"]
    )["stories"]
    card = next(row for row in cards if row["story_id"] == "s-one")
    assert card["title"] == RAW


def test_today_row_title_matches_the_story_it_opens(newsroom, monkeypatch):
    """§A4: one rule, so a Today row and its Story never disagree."""
    from editor_assistant.workflow import quick_draft as quick_mod

    monkeypatch.setattr(
        quick_mod,
        "availability",
        lambda **kwargs: {
            "available": False,
            "label": "Чернова",
            "articleId": None,
            "reasonCode": None,
        },
    )
    story = app._story("s-one")
    story["status"] = "NEW"
    story["latest_material_change_at"] = "2026-09-26T08:00:00Z"
    store = story_store.read_store(newsroom / "stories.json")
    store["stories"] = [story]
    story_store.write_store(store, newsroom / "stories.json")
    # Force Today attention regardless of the editorial clock.
    monkeypatch.setattr(
        "editor_assistant.workflow.editor_queries.story_is_within_horizon",
        lambda story, *, horizon_start: True,
    )
    today = app.read_today()
    row = next(item for item in today["newStories"] if item["objectId"] == "s-one")
    assert row["title"] == app.read_story("s-one")["title"] == CLEAN
