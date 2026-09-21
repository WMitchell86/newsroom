"""M4C story identity tests — offline, no network, no model provider.

They pin the rules that matter for the editor's trust:

* publication identity collapses duplicate *discoveries* without touching the raw
  inbox rows;
* the story store is strict, atomic and refuses to look empty when unreadable;
* `uncertain -> separate` (a false split is cheap, a false merge hides news);
* infrastructure failure never merges;
* editor split/merge decisions persist and win over later automatic passes.
"""

from __future__ import annotations

import json

import pytest

from editor_assistant.drafting import generate
from editor_assistant.workflow import (
    blocked_domains,
    cli,
    inbox_store,
    story_identity,
    story_relation,
    story_store,
)
from editor_assistant.workflow import (
    publication_identity as pub,
)


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWSROOM_DIR", str(tmp_path))
    monkeypatch.setenv("NEWSROOM_INBOX_PATH", str(tmp_path / "inbox.jsonl"))
    monkeypatch.setenv("NEWSROOM_STORIES_PATH", str(tmp_path / "stories.json"))
    monkeypatch.setenv("NEWSROOM_BLOCKED_DOMAINS_PATH", str(tmp_path / "blocked.json"))
    return tmp_path


def _item(**over):
    """A valid inbox item; identity is derived from (source_id, source_item_id, url)."""
    base = {
        "source_id": "monitor-a",
        "source_item_id": over.get("url", "https://media.example/a"),
        "title": "Заглавие",
        "url": "https://media.example/a",
        "published_at": "2026-09-20T08:00:00Z",
        "discovered_at": "2026-09-20T08:00:00Z",
        "source_kind": "media",
        "priority": "normal",
        "publisher_domain": "media.example",
        "factual_authority": True,
        "status": "NEW",
    }
    base.update(over)
    if "source_item_id" not in over:
        base["source_item_id"] = base["url"]
    # the same deterministic identity `inbox_store.add_items` would compute
    base.setdefault(
        "item_id",
        inbox_store.item_id_for(base["source_id"], base["source_item_id"], base["url"]),
    )
    return base


def _seed(items):
    return inbox_store.add_items(items)["items"]


def _found(payload, role="story"):
    return json.dumps(payload), {"model": "fake", "role": role}


# ---------------------------------------------------------------- publication identity


def test_same_article_from_two_monitors_shares_one_publication_key():
    one = _item(source_id="monitor-a", title="A", url="https://media.example/news/1")
    two = _item(source_id="monitor-b", title="A (препис)", url="https://media.example/news/1")
    assert pub.publication_key(one) == pub.publication_key(two)
    # The discovery rows stay distinct: provenance is preserved.
    assert inbox_store.item_id_for(
        one["source_id"], one["source_item_id"], one["url"]
    ) != inbox_store.item_id_for(two["source_id"], two["source_item_id"], two["url"])


def test_tracking_params_do_not_create_a_new_publication():
    plain = _item(url="https://media.example/news/1")
    tracked = _item(
        url="https://media.example/news/1?utm_source=fb&utm_campaign=x&fbclid=abc&gclid=1"
    )
    assert pub.publication_key(plain) == pub.publication_key(tracked)


def test_meaningful_query_params_stay_distinct():
    first = _item(url="https://media.example/story?id=11")
    second = _item(url="https://media.example/story?id=12")
    assert pub.publication_key(first) != pub.publication_key(second)
    # Parameter order is not an identity.
    reordered = _item(url="https://media.example/s?a=1&b=2")
    shuffled = _item(url="https://media.example/s?b=2&a=1")
    assert pub.publication_key(reordered) == pub.publication_key(shuffled)


def test_google_news_article_path_identity_is_stable():
    one = _item(
        source_id="monitor-a",
        url="https://news.google.com/rss/articles/CBMi1?hl=bg&gl=BG",
        publisher_domain="bnr.bg",
    )
    two = _item(
        source_id="monitor-b",
        url="https://news.google.com/rss/articles/CBMi1?oc=5",
        publisher_domain="bnr.bg",
    )
    assert pub.publication_key(one) == pub.publication_key(two)
    # A different publisher can never collapse into the same identity.
    other = _item(
        source_id="monitor-b",
        url="https://news.google.com/rss/articles/CBMi1",
        publisher_domain="dariknews.bg",
    )
    assert pub.publication_key(other) != pub.publication_key(one)


def test_no_usable_url_never_fabricates_an_exact_key():
    assert pub.publication_key({"url": "", "publisher_domain": "x.bg"}) is None
    assert pub.publication_key({"url": "not-a-url", "publisher_domain": "x.bg"}) is None
    assert pub.publication_key({"url": "javascript:alert(1)"}) is None


# ---------------------------------------------------------------- story store


def test_store_is_strict_about_unknown_fields():
    story = story_store.new_story(_item())
    story["confidence"] = 0.9
    with pytest.raises(story_store.StoryStoreError):
        story_store.validate_story(story)

    bad_member = story_store.new_story(_item())
    bad_member["members"][0]["jaccard"] = 0.5
    with pytest.raises(story_store.StoryStoreError):
        story_store.validate_story(bad_member)

    assert "NEW_STORY" not in story_store.RELATIONS  # creating a story is an action


def test_unreadable_store_raises_instead_of_looking_empty(tmp_path):
    path = tmp_path / "stories.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(story_store.StoryStoreError):
        story_store.read_stories(path)
    path.write_text(json.dumps({"version": 1, "stories": [{"story_id": "s1"}]}), encoding="utf-8")
    with pytest.raises(story_store.StoryStoreError):
        story_store.read_stories(path)


def test_save_is_atomic_and_deterministic(tmp_path):
    path = tmp_path / "stories.json"
    story = story_store.new_story(_item())
    story_store.write_store({"stories": [story]}, path)
    first = path.read_text(encoding="utf-8")
    story_store.write_store({"stories": [story]}, path)
    assert path.read_text(encoding="utf-8") == first
    assert json.loads(first)["stories"][0]["story_id"] == story["story_id"]


def test_story_id_is_stable_and_never_derived_from_the_headline():
    item = _item(title="Кратко заглавие")
    key = pub.publication_key(item)
    assert story_store.story_id_for(key) == story_store.story_id_for(key)
    renamed = {**item, "title": "Напълно друго заглавие"}
    assert pub.publication_key(renamed) == key  # title never enters identity
    assert story_store.story_id_for(key) == story_store.story_id_for(pub.publication_key(renamed))


def test_a_missing_store_is_empty_but_not_an_error(tmp_path):
    assert story_store.read_stories(tmp_path / "nope.json") == []


# ---------------------------------------------------------------- exact duplicate / deterministic


def test_exact_duplicate_joins_the_existing_story_without_a_model_call():
    _seed(
        [
            _item(source_id="monitor-a", title="А", url="https://media.example/1"),
            _item(source_id="monitor-b", title="Б", url="https://media.example/1"),
        ]
    )

    def explode(*_a, **_k):
        raise AssertionError("exact publication identity must never call a model")

    summary = story_identity.update(dry_run=False, call_model=explode)
    assert summary["exact_duplicates"] == 1
    assert summary["new_stories"] == 1
    assert summary["semantic_calls"] == 0
    stories = story_store.read_stories()
    assert len(stories) == 1
    assert len(stories[0]["members"]) == 2


def test_source_items_are_preserved_by_story_processing():
    items = _seed(
        [
            _item(source_id="monitor-a", title="А", url="https://media.example/1"),
            _item(source_id="monitor-b", title="Б", url="https://media.example/1"),
        ]
    )
    before = [i["item_id"] for i in inbox_store.read_items()]
    story_identity.update(dry_run=False)
    after = [i["item_id"] for i in inbox_store.read_items()]
    assert before == after
    assert {i["status"] for i in inbox_store.read_items()} == {"NEW"}
    assert len(items) == 2


def test_near_identical_titles_are_merged_deterministically():
    title = "Общинският съвет прие бюджета на Бургас за 2027"
    _seed(
        [
            _item(source_id="monitor-a", title=title, url="https://a.example/1"),
            _item(source_id="monitor-b", title=title, url="https://b.example/1"),
        ]
    )

    def explode(*_a, **_k):
        raise AssertionError("a strong deterministic match must not call a model")

    summary = story_identity.update(dry_run=False, call_model=explode)
    assert summary["deterministic_matches"] == 1
    assert summary["semantic_calls"] == 0
    assert len(story_store.read_stories()) == 1


def test_uncertain_titles_stay_separate_by_default():
    _seed(
        [
            _item(
                source_id="monitor-a", title="Пътна обстановка: катастрофа на пътя Бургас — Несебър"
            ),
            _item(
                source_id="monitor-b",
                title="Катастрофа на пътя Бургас — Несебър, трима ранени",
                url="https://b.example/2",
                publisher_domain="b.example",
            ),
        ]
    )
    summary = story_identity.update(dry_run=False, semantic=False)
    assert summary["new_stories"] == 2
    assert summary["needs_review"] == 1  # the second item had a shortlist but no answer
    stories = story_store.read_stories()
    assert len(stories) == 2
    assert any(s["needs_review"] for s in stories)


# ---------------------------------------------------------------- semantic relation


def _shortlist_pair():
    """Two same-event-ish items whose titles are too different for the deterministic test."""
    return _seed(
        [
            _item(
                source_id="monitor-a",
                title="Пътна обстановка: катастрофа на пътя Бургас — Несебър",
                url="https://a.example/1",
            ),
            _item(
                source_id="monitor-b",
                title="Катастрофа на пътя Бургас — Несебър, трима ранени",
                url="https://b.example/2",
                publisher_domain="b.example",
            ),
        ]
    )


def test_semantic_answer_can_join_the_shortlisted_story():
    _shortlist_pair()

    def fake(_prompt, role="story"):
        return _found(
            {
                "same_event": True,
                "relation": "SAME_STORY",
                "material_change": False,
                "shared_anchors": ["Бургас — Несебър"],
                "reason": "същият инцидент",
            },
            role,
        )

    summary = story_identity.update(dry_run=False, call_model=fake)
    assert summary["semantic_matches"] == 1
    assert summary["semantic_calls"] == 1
    assert len(story_store.read_stories()) == 1


def test_invalid_semantic_output_never_merges():
    _shortlist_pair()

    def garbage(_prompt, role="story"):
        return "не е JSON", {"role": role}

    summary = story_identity.update(dry_run=False, call_model=garbage)
    assert summary["semantic_matches"] == 0
    assert summary["semantic_failures"] == 1
    stories = story_store.read_stories()
    assert len(stories) == 2 and stories[1]["needs_review"] is True


def test_contradictory_semantic_output_is_rejected():
    with pytest.raises(story_relation.RelationError):
        story_relation.parse_relation(
            {
                "same_event": True,
                "relation": "DIFFERENT_STORY",
                "material_change": False,
                "shared_anchors": [],
                "reason": "x",
            }
        )
    with pytest.raises(story_relation.RelationError):
        story_relation.parse_relation(
            {
                "same_event": True,
                "relation": "NEW_DEVELOPMENT",
                "material_change": False,
                "shared_anchors": [],
                "reason": "x",
            }
        )
    with pytest.raises(story_relation.RelationError):
        # the model may never smuggle authority or scoring fields through
        story_relation.parse_relation(
            {
                "same_event": True,
                "relation": "SAME_STORY",
                "material_change": False,
                "shared_anchors": [],
                "reason": "x",
                "factual_authority": True,
            }
        )


def test_provider_unavailable_never_merges():
    _shortlist_pair()

    def down(_prompt, role="story"):
        raise RuntimeError("429 rate limited")

    summary = story_identity.update(dry_run=False, call_model=down)
    assert summary["semantic_matches"] == 0
    assert summary["semantic_failures"] == 1
    assert summary["new_stories"] == 2
    stories = story_store.read_stories()
    assert sum(1 for s in stories if s["needs_review"]) == 1  # only the ambiguous item


def test_the_relation_model_never_modifies_publisher_authority():
    _shortlist_pair()

    def fake(_prompt, role="story"):
        return _found(
            {
                "same_event": True,
                "relation": "SAME_STORY",
                "material_change": False,
                "shared_anchors": [],
                "reason": "same",
            },
            role,
        )

    story_identity.update(dry_run=False, call_model=fake)
    for item in inbox_store.read_items():
        assert item["publisher_domain"] in ("a.example", "media.example", "b.example")
        assert isinstance(item["factual_authority"], bool)
        assert item["publisher_kind"] == ""  # an unapproved publisher stays unapproved


def test_the_classifier_only_sees_the_shortlisted_story():
    calls = []
    _seed(
        [
            # an old unrelated story: must never be sent to the model
            _item(
                source_id="monitor-a",
                title="Откриха незаконен строеж край Созопол",
                url="https://a.example/old",
            ),
            _item(
                source_id="monitor-b",
                title="Пътна обстановка: катастрофа на пътя Бургас — Несебър",
                url="https://b.example/1",
                publisher_domain="b.example",
            ),
            _item(
                source_id="monitor-c",
                title="Катастрофа на пътя Бургас — Несебър, трима ранени",
                url="https://c.example/2",
                publisher_domain="c.example",
            ),
        ]
    )

    def fake(prompt, role="story"):
        calls.append(prompt)
        return _found(
            {
                "same_event": False,
                "relation": "DIFFERENT_STORY",
                "material_change": False,
                "shared_anchors": [],
                "reason": "различни",
            },
            role,
        )

    story_identity.update(dry_run=False, call_model=fake)
    assert calls, "the ambiguous pair must reach the semantic step"
    assert all("Созопол" not in prompt for prompt in calls)


def test_the_prompt_carries_no_article_bodies_and_at_most_three_publications():
    stories = []
    for index in range(5):
        stories.append(
            _item(
                source_id=f"monitor-{index}",
                title=f"Катастрофа на пътя Бургас — Несебър, вариант {index}",
                url=f"https://m{index}.example/{index}",
                publisher_domain=f"m{index}.example",
                summary="К" * 5000,
            )
        )
    _seed(stories)
    story_identity.update(dry_run=False, semantic=False)
    store = story_store.read_stories()
    target = store[0]
    context = story_relation.build_context(
        _item(url="https://new.example/x", title="Катастрофа на пътя Бургас — Несебър"),
        target,
        {i["item_id"]: i for i in inbox_store.read_items()},
    )
    assert len(context["publications"]) <= story_relation.MAX_CONTEXT_PUBLICATIONS
    assert all(
        len(p["summary"]) <= story_relation.MAX_SUMMARY_CHARS for p in context["publications"]
    )


def test_relation_output_has_no_scoring_or_authority_surface():
    answer = story_relation.parse_relation(
        {
            "same_event": True,
            "relation": "RELATED_BACKGROUND",
            "material_change": False,
            "shared_anchors": ["a"],
            "reason": "context",
        }
    )
    assert set(answer) == {
        "same_event",
        "relation",
        "material_change",
        "shared_anchors",
        "reason",
    }


# ---------------------------------------------------------------- lifecycle


def _one_story_with_status(status):
    _seed([_item(source_id="monitor-a", title="А", url="https://a.example/1")])
    story_identity.update(dry_run=False)
    story_id = story_store.read_stories()[0]["story_id"]
    if status != "NEW":
        story_identity.set_story_status(story_id, status)
    return story_id


def test_same_story_does_not_reopen_a_seen_story():
    story_id = _one_story_with_status("SEEN")
    _seed([_item(source_id="monitor-b", title="Б", url="https://a.example/1")])
    story_identity.update(dry_run=False)
    assert story_store.read_stories()[0]["story_id"] == story_id
    assert story_store.read_stories()[0]["status"] == "SEEN"
    # the story-level status propagates to the raw material view
    assert {i["status"] for i in inbox_store.read_items()} == {"SEEN"}


def test_related_background_does_not_reopen_a_seen_story():
    story_id = _one_story_with_status("SEEN")
    _shortlist_pair()
    story_identity.update(dry_run=False, semantic=False)
    story = story_store.story_by_id(story_store.read_store(), story_id)
    story_store.add_member(
        story,
        inbox_store.read_items()[0],
        relation="RELATED_BACKGROUND",
        relation_source=story_store.SOURCE_SEMANTIC,
    )
    assert story["status"] == "SEEN"
    assert story["representative_item_id"] != ""  # context never becomes the headline


def test_new_development_reopens_a_seen_story():
    story_id = _one_story_with_status("SEEN")
    store = story_store.read_store()
    story = story_store.story_by_id(store, story_id)
    item = _item(source_id="monitor-c", title="Ново развитие", url="https://c.example/3")
    story_store.add_member(
        story,
        item,
        relation="NEW_DEVELOPMENT",
        relation_source=story_store.SOURCE_SEMANTIC,
    )
    assert story["status"] == "NEW"
    assert story["representative_item_id"] == inbox_store.item_id_for(
        item["source_id"], item["source_item_id"], item["url"]
    )


def test_an_ignored_story_stays_ignored():
    story_id = _one_story_with_status("IGNORED")
    _seed([_item(source_id="monitor-b", title="Б", url="https://a.example/1")])
    story_identity.update(dry_run=False)
    store = story_store.read_store()
    assert story_store.story_by_id(store, story_id)["status"] == "IGNORED"
    assert {i["status"] for i in inbox_store.read_items()} == {"IGNORED"}


def test_story_status_propagates_to_member_items():
    story_id = _one_story_with_status("SEEN")
    assert {i["status"] for i in inbox_store.read_items()} == {"SEEN"}
    result = story_identity.set_story_status(story_id, "NEW")
    assert result["status"] == "NEW"
    # reopening a story does not rewrite the material statuses
    assert {i["status"] for i in inbox_store.read_items()} == {"SEEN"}


# ---------------------------------------------------------------- editor corrections


def test_editor_split_persists_and_blocks_a_later_remerge():
    _seed(
        [
            _item(source_id="monitor-a", title="А", url="https://a.example/1"),
            _item(source_id="monitor-b", title="Б", url="https://a.example/1"),
        ]
    )
    story_identity.update(dry_run=False)
    story = story_store.read_stories()[0]
    other = [m for m in story["members"]][1]
    result = story_identity.split_item(story["story_id"], other["item_id"])
    assert result["to_story"] != result["from_story"]
    store = story_store.read_store()
    assert len(store["stories"]) == 2
    assert store["overrides"][-1]["action"] == "SPLIT"
    assert story_store.is_editor_locked(store, other["item_id"]) is True
    # the split is not undone by a later incremental pass
    story_identity.update(dry_run=False)
    assert len(story_store.read_stories()) == 2


def test_editor_merge_moves_members_and_records_an_override():
    _seed(
        [
            _item(source_id="monitor-a", title="А", url="https://a.example/1"),
            _item(
                source_id="monitor-b",
                title="Б",
                url="https://b.example/2",
                publisher_domain="b.example",
            ),
        ]
    )
    story_identity.update(dry_run=False, semantic=False)
    store = story_store.read_store()
    target, source = store["stories"][0], store["stories"][1]
    result = story_identity.merge_stories(target["story_id"], source["story_id"])
    assert result["members"] == 2
    store = story_store.read_store()
    assert len(store["stories"]) == 1
    assert store["overrides"][-1]["action"] == "MERGE"
    assert story_store.story_by_id(store, source["story_id"]) is None


def test_rebuild_refuses_to_discard_editor_corrections():
    _seed(
        [
            _item(source_id="monitor-a", title="А", url="https://a.example/1"),
            _item(source_id="monitor-b", title="Б", url="https://a.example/1"),
        ]
    )
    story_identity.update(dry_run=False)
    story = story_store.read_stories()[0]
    story_identity.split_item(story["story_id"], story["members"][1]["item_id"])
    before = len(story_store.read_stories())
    result = story_identity.rebuild(preview=False)
    assert result["refused"] is True
    assert "editor correction" in result["reason"]
    assert len(story_store.read_stories()) == before  # nothing was overwritten


def test_rebuild_preview_writes_nothing():
    _seed([_item(source_id="monitor-a", title="А", url="https://a.example/1")])
    result = story_identity.rebuild(preview=True, semantic=False)
    assert result["stories"] == 1
    assert story_store.read_stories() == []


def test_a_story_with_a_single_origin_cannot_be_split():
    _seed([_item(source_id="monitor-a", title="А", url="https://a.example/1")])
    story_identity.update(dry_run=False)
    story = story_store.read_stories()[0]
    with pytest.raises(story_store.StoryStoreError):
        story_store.split_member(
            story,
            story["members"][0]["item_id"],
            items_by_id={},
        )


# ---------------------------------------------------------------- blocked publishers (PART 17)


def test_a_blocked_publisher_never_creates_a_story_but_its_row_survives():
    _seed(
        [
            _item(
                source_id="monitor-a",
                title="Флагман: новина",
                url="https://flagman.bg/1",
                publisher_domain="flagman.bg",
            ),
            _item(
                source_id="monitor-b",
                title="БНР: новина",
                url="https://bnr.bg/1",
                publisher_domain="bnr.bg",
            ),
        ]
    )
    summary = story_identity.update(dry_run=False)
    assert summary["blocked_publisher"] == 1
    assert len(story_store.read_stories()) == 1
    # the raw rows are untouched (audit) — only grouping is refused
    urls = {i["url"] for i in inbox_store.read_items()}
    assert urls == {"https://flagman.bg/1", "https://bnr.bg/1"}
    assert "flagman.bg" in blocked_domains.effective_domains()


# ---------------------------------------------------------------- counts (PART 15)


def test_counts_separate_discoveries_publications_and_publishers():
    title = "Общинският съвет прие бюджета на Бургас за 2027"
    _seed(
        [
            _item(
                source_id="monitor-a",
                title=title,
                url="https://news.google.com/rss/articles/CBMiX",
                publisher_domain="bta.bg",
            ),
            _item(
                source_id="monitor-b",
                title=title,
                url="https://news.google.com/rss/articles/CBMiX",
                publisher_domain="bta.bg",
            ),
            _item(
                source_id="monitor-c",
                title=title,
                url="https://news.google.com/rss/articles/CBMiX",
                publisher_domain="bta.bg",
            ),
            _item(
                source_id="monitor-d",
                title=title,
                url="https://bnr.bg/1",
                publisher_domain="bnr.bg",
            ),
        ]
    )
    story_identity.update(dry_run=False)
    cards = story_identity.story_cards()["stories"]
    assert len(cards) == 1
    metrics = cards[0]["metrics"]
    assert metrics["discovery_count"] == 4
    assert metrics["publication_count"] == 2  # three discoveries are one publication
    assert metrics["publisher_count"] == 2
    assert cards[0]["publishers"] == ["bnr.bg", "bta.bg"]


def test_the_editor_list_never_exposes_internal_ids_as_text():
    _seed([_item(source_id="monitor-a", title="Заглавие", url="https://a.example/1")])
    story_identity.update(dry_run=False)
    card = story_identity.story_cards()["stories"][0]
    assert card["title"] == "Заглавие"
    assert "confidence" not in card and "jaccard" not in card


# ---------------------------------------------------------------- CLI


def test_cli_stories_update_dry_run_writes_nothing(capsys):
    _seed([_item(source_id="monitor-a", title="Заглавие", url="https://a.example/1")])
    cli.main(["newsroom", "stories", "update", "--dry-run", "--no-semantic"])
    out = capsys.readouterr().out
    assert "ПРОБЕН ПРЕГЛЕД" in out and "нови истории: 1" in out
    assert story_store.read_stories() == []


def test_cli_refresh_summarizes_collection_and_stories(monkeypatch, capsys):
    _seed([_item(source_id="monitor-a", title="Заглавие", url="https://a.example/1")])

    def fake_collect(**_kwargs):
        return {
            "dry_run": True,
            "locked": False,
            "sources": [{"source_id": "x"}],
            "estimated_network_calls": 1,
            "new": 3,
            "failed": 0,
        }

    from editor_assistant.workflow import newsroom_run

    monkeypatch.setattr(newsroom_run, "collect", fake_collect)
    cli.main(["newsroom", "refresh", "--dry-run"])
    out = capsys.readouterr().out
    assert "източници: 1" in out
    assert "нови материали: 3" in out
    assert "нови истории: 1" in out
    assert "грешки: 0" in out


# ---------------------------------------------------------------- model role (PART 25)


def test_story_role_has_its_own_pool_and_never_the_judge_pool():
    assert generate.STORY_MODEL_POOL  # defaults to the draft pool, never empty
    assert generate.STORY_MODEL_POOL != generate.JUDGE_MODEL_POOL
    assert set(generate._gemini_pool("story")) <= set(generate.STORY_MODEL_POOL)
    # the judge role keeps the Lite pool: the story role must not have moved it
    assert set(generate._gemini_pool("judge")) <= set(generate.JUDGE_MODEL_POOL)
    assert generate._gemini_pool("story") != generate._gemini_pool("judge")


def test_openrouter_story_model_does_not_leak_into_the_draft_role(monkeypatch):
    monkeypatch.setenv("OPENROUTER_STORY_MODEL", "deepseek/deepseek-v4-flash-0731:free")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    calls = {}

    def fake_call(prompt, *, api_key, timeout, model):
        calls["model"] = model
        return "{}", {"model": model}

    monkeypatch.setattr(generate, "_call_openrouter", fake_call)
    generate.call_model("hello", role="draft")
    drafted = calls["model"]
    generate.call_model("hello", role="story")
    assert calls["model"] == "deepseek/deepseek-v4-flash-0731:free"
    assert drafted != calls["model"]


def test_story_calls_reuse_the_gemini_env_pool_when_configured(monkeypatch):
    monkeypatch.setattr(generate, "STORY_MODEL_POOL", ["story-a", "story-b"])
    assert generate._gemini_pool("story") == ["story-a", "story-b"]
    assert generate._gemini_pool("draft") != ["story-a", "story-b"]
