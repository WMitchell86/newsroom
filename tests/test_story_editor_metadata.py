"""Phase A: narrow, independently persisted Story editor metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from editor_assistant.workflow import editor_projections, inbox_store, story_store
from editor_assistant.workflow import story_editor_metadata as metadata


def _canonical_story(dev_item_ids=("item-a", "item-b", "item-c")):
    origin = {
        "item_id": "origin",
        "discovered_at": "2026-09-20T08:00:00Z",
        "published_at": "2026-09-20T07:00:00Z",
    }
    story = story_store.new_story(origin, now="2026-09-20T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    for item_id in dev_item_ids:
        story_store.add_member(
            story,
            {"item_id": item_id},
            relation="NEW_DEVELOPMENT",
            relation_source="deterministic_title",
            now="2026-09-25T08:00:00Z",
        )
    return story


def _seed_story(root, story=None):
    story = story or _canonical_story()
    story_store.write_store({"stories": [story]}, root / "stories.json")
    member_ids = [member["item_id"] for member in story["members"]]
    inbox_store.save_items(
        [
            {
                "item_id": item_id,
                "source_id": "source-a",
                "source_item_id": item_id,
                "title": item_id,
                "url": f"https://example.test/{item_id}",
                "discovered_at": "2026-09-25T08:00:00Z",
                "status": "NEW",
            }
            for item_id in member_ids
        ],
        root / "inbox.jsonl",
    )
    return story


@pytest.fixture
def metadata_root(tmp_path, monkeypatch):
    root = tmp_path / "newsroom"
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    _seed_story(root)
    return root


def test_follow_is_independent_of_review_and_ignore(metadata_root):
    assert metadata.get_story_editor_metadata("s-one", root=metadata_root) == {
        "story_id": "s-one",
        "followed": False,
        "last_reviewed_at": None,
        "reviewed_development_ids": [],
    }
    followed = metadata.set_story_followed(
        "s-one", True, stories_path=metadata_root / "stories.json", root=metadata_root
    )
    assert followed["followed"] is True
    assert followed["last_reviewed_at"] is None
    assert metadata.get_story_editor_metadata("s-one", root=metadata_root) == followed


def test_review_acknowledges_only_observed_developments_and_keeps_follow(metadata_root):
    stories_path = metadata_root / "stories.json"
    _seed_story(metadata_root, _canonical_story(("item-a", "item-b")))
    dev_a = editor_projections.development_id_for("s-one", "item-a")
    dev_b = editor_projections.development_id_for("s-one", "item-b")
    dev_c = editor_projections.development_id_for("s-one", "item-c")
    observed = [dev_a, dev_b]
    store = story_store.read_store(stories_path)
    story = story_store.story_by_id(store, "s-one")
    story_store.add_member(
        story,
        {"item_id": "item-c"},
        relation="NEW_DEVELOPMENT",
        relation_source="deterministic_title",
        now="2026-09-25T09:00:00Z",
    )
    story_store.write_store(store, stories_path)
    metadata.set_story_followed("s-one", True, stories_path=stories_path, root=metadata_root)
    reviewed = metadata.review_story_developments(
        "s-one",
        observed_development_ids=observed,
        stories_path=stories_path,
        inbox_path=metadata_root / "inbox.jsonl",
        now="2026-09-25T10:00:00Z",
        root=metadata_root,
    )

    assert reviewed["followed"] is True
    assert reviewed["last_reviewed_at"] == "2026-09-25T10:00:00Z"
    assert reviewed["reviewed_development_ids"] == sorted([dev_a, dev_b])
    assert dev_c not in reviewed["reviewed_development_ids"]
    stories = story_store.read_store(stories_path)["stories"]
    assert stories[0]["status"] == "SEEN"
    assert {row["status"] for row in inbox_store.read_items(metadata_root / "inbox.jsonl")} == {
        "SEEN"
    }
    assert metadata.get_story_editor_metadata("s-one", root=metadata_root)["followed"] is True


def test_review_restores_ignored_story_without_clearing_follow(metadata_root):
    stories_path = metadata_root / "stories.json"
    inbox_path = metadata_root / "inbox.jsonl"
    story = _canonical_story(("item-a",))
    story["status"] = "IGNORED"
    _seed_story(metadata_root, story)
    metadata.set_story_followed("s-one", True, stories_path=stories_path, root=metadata_root)
    development_id = editor_projections.development_id_for("s-one", "item-a")

    reviewed = metadata.review_story_developments(
        "s-one",
        [development_id],
        stories_path=stories_path,
        inbox_path=inbox_path,
        now="2026-09-25T10:00:00Z",
        root=metadata_root,
    )

    assert (
        story_store.story_by_id(story_store.read_store(stories_path), "s-one")["status"] == "SEEN"
    )
    assert reviewed["followed"] is True


def test_review_validates_observed_set_and_is_atomic_on_corrupt_store(metadata_root):
    _seed_story(metadata_root, _canonical_story(("item-a",)))
    forged = editor_projections.development_id_for("s-one", "forged")
    with pytest.raises(metadata.StoryEditorMetadataError, match="unknown development"):
        metadata.review_story_developments(
            "s-one",
            [forged],
            stories_path=metadata_root / "stories.json",
            inbox_path=metadata_root / "inbox.jsonl",
            root=metadata_root,
        )

    path = metadata.story_editor_metadata_path(root=metadata_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(metadata.StoryEditorMetadataError, match="unreadable"):
        metadata.set_story_followed(
            "s-one", True, stories_path=metadata_root / "stories.json", root=metadata_root
        )
    assert path.read_bytes() == before


def test_store_is_strict_atomic_and_deterministic(metadata_root):
    path = metadata.story_editor_metadata_path(root=metadata_root)
    row = metadata.get_story_editor_metadata("s-one", root=metadata_root)
    metadata.write_story_editor_metadata({"version": 1, "stories": [row]}, root=metadata_root)
    first = path.read_bytes()
    metadata.write_story_editor_metadata({"version": 1, "stories": [row]}, root=metadata_root)
    assert path.read_bytes() == first
    assert json.loads(first) == {"version": 1, "stories": [row]}

    invalid = {**row, "ignored": True}
    with pytest.raises(metadata.StoryEditorMetadataError, match="unknown metadata fields"):
        metadata.validate_story_editor_metadata(invalid)
    with pytest.raises(metadata.StoryEditorMetadataError, match="stories must be a list"):
        metadata.validate_story_editor_store({"version": 1})
    with pytest.raises(metadata.StoryEditorMetadataError, match="ISO-8601"):
        metadata.validate_story_editor_metadata({**row, "last_reviewed_at": "yesterday"})
    with pytest.raises(metadata.StoryEditorMetadataError, match="development id"):
        metadata.validate_story_editor_metadata({**row, "reviewed_development_ids": ["forged"]})


def test_follow_rejects_unknown_story_without_creating_metadata(metadata_root):
    with pytest.raises(metadata.StoryEditorMetadataError, match="unknown canonical story_id"):
        metadata.set_story_followed(
            "s-missing", True, stories_path=metadata_root / "stories.json", root=metadata_root
        )
    assert not metadata.story_editor_metadata_path(root=metadata_root).exists()


def test_review_restores_both_stores_on_metadata_failure(metadata_root, monkeypatch):
    _seed_story(metadata_root, _canonical_story(("item-a",)))
    dev_a = editor_projections.development_id_for("s-one", "item-a")
    metadata.set_story_followed(
        "s-one", True, stories_path=metadata_root / "stories.json", root=metadata_root
    )
    stories_path = metadata_root / "stories.json"
    inbox_path = metadata_root / "inbox.jsonl"
    before_story = stories_path.read_bytes()
    before_inbox = inbox_path.read_bytes()
    before_meta = metadata.story_editor_metadata_path(root=metadata_root).read_bytes()
    real_write = metadata.live_store.atomic_write

    def fail_metadata(path, data):
        if Path(path) == metadata.story_editor_metadata_path(root=metadata_root):
            raise OSError("metadata unavailable")
        return real_write(path, data)

    monkeypatch.setattr(metadata.live_store, "atomic_write", fail_metadata)
    with pytest.raises(OSError, match="metadata unavailable"):
        metadata.review_story_developments(
            "s-one",
            [dev_a],
            stories_path=stories_path,
            inbox_path=inbox_path,
            root=metadata_root,
        )
    assert stories_path.read_bytes() == before_story
    assert inbox_path.read_bytes() == before_inbox
    assert metadata.story_editor_metadata_path(root=metadata_root).read_bytes() == before_meta


def test_metadata_atomic_write_failure_preserves_bytes(metadata_root, monkeypatch):
    row = metadata.get_story_editor_metadata("s-one", root=metadata_root)
    metadata.write_story_editor_metadata({"version": 1, "stories": [row]}, root=metadata_root)
    path = metadata.story_editor_metadata_path(root=metadata_root)
    before = path.read_bytes()

    def fail_write(_path, _data):
        raise OSError("disk full")

    monkeypatch.setattr(metadata.live_store, "atomic_write", fail_write)
    with pytest.raises(OSError, match="disk full"):
        metadata.set_story_followed(
            "s-one", True, stories_path=metadata_root / "stories.json", root=metadata_root
        )
    assert path.read_bytes() == before
    assert list(path.parent.glob("*.tmp")) == []


def test_workbench_newsroom_env_is_honored(tmp_path, monkeypatch):
    newsroom = tmp_path / "workbench-newsroom"
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    assert metadata.story_editor_metadata_path().parent == newsroom
