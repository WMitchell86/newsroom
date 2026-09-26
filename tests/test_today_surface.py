"""V1.1-D1: Today is a bounded, chronological, current attention surface.

Three product decisions are asserted here, and each of them is a decision the
old implementation got wrong against real data:

* **ordering** follows the canonical change timestamp, not a relation
  (`latest_development.changed_at`) that is empty for every Story in the corpus;
* **horizon** is calendar-based in `Europe/Sofia`, so untouched backlog retires
  on its own without anybody marking it reviewed;
* **cap** bounds the first screen, and the withheld count is reported rather
  than silently dropped.

Plus the two operational facts the editor can now see: when the newsroom was
last refreshed, and that the projection no longer re-reads every store once per
Story.

Nothing here writes to the repository's real runtime stores: every fixture is
built under `tmp_path` through the canonical stores.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from editor_assistant.workflow import (
    editor_article_store,
    editor_queries,
    inbox_store,
    source_health,
    story_editor_metadata,
    story_store,
)

#: A fixed editorial "now": Wednesday 2026-09-23, 10:00 in the newsroom.
NOW = datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc)  # 10:00 Europe/Sofia


def _development_id(story_id: str, item_id: str) -> str:
    seed = f"{story_id}\0{item_id}".encode()
    return "dev_" + hashlib.sha256(seed).hexdigest()[:15]


def _item(item_id: str, *, title: str = "Материал", discovered_at: str) -> dict:
    return {
        "item_id": item_id,
        "source_id": "source-a",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://example.test/{item_id}",
        "published_at": discovered_at,
        "discovered_at": discovered_at,
        "summary": f"Обобщение за {title}",
        "source_kind": "media",
        "status": "NEW",
    }


def _story(story_id: str, *, changed_at: str, status: str = "NEW", developments=()) -> dict:
    """A canonical Story with one ORIGIN member and optional developments."""
    origin = _item(f"{story_id}-origin", title=f"Заглавие {story_id}", discovered_at=changed_at)
    story = story_store.new_story(origin, publication_key=f"pk-{story_id}", now=changed_at)
    story["story_id"] = story_id
    for index, development in enumerate(developments):
        member = _item(
            f"{story_id}-dev-{index}",
            title=f"Развитие {index}",
            discovered_at=development,
        )
        story_store.add_member(
            story,
            member,
            relation="NEW_DEVELOPMENT",
            relation_source="semantic",
            publication_key=f"pk-{story_id}-dev-{index}",
            now=development,
        )
    # The identity stage recomputes the derived timestamps after every change;
    # the fixture must do the same or it would assert against a Story shape the
    # real pipeline never produces.
    story_store.refresh_times(
        story,
        {
            member["item_id"]: _item(member["item_id"], discovered_at=member["added_at"])
            for member in story["members"]
        },
        now=changed_at,
    )
    story["status"] = status
    return story


def _seed(tmp_path, stories, *, follow=(), article_story=None):
    """Write a complete, valid newsroom fixture and return its paths."""
    newsroom = tmp_path / "newsroom"
    newsroom.mkdir(parents=True, exist_ok=True)
    stories_path = newsroom / "stories.json"
    inbox_path = newsroom / "inbox.jsonl"
    rows = []
    for story in stories:
        for member in story["members"]:
            rows.append(
                _item(
                    member["item_id"],
                    title=f"Заглавие {story['story_id']}",
                    discovered_at=member["added_at"],
                )
            )
    inbox_store.save_items(rows, inbox_path)
    story_store.write_store({"stories": list(stories)}, stories_path)
    for story_id in follow:
        story_editor_metadata.set_story_followed(
            story_id, True, stories_path=stories_path, root=newsroom
        )
    article = None
    if article_story is not None:
        article = editor_article_store.create_editor_article(
            story_id=article_story,
            stories_path=stories_path,
            working_title="Работа",
            now="2026-09-23T06:00:00Z",
            root=tmp_path / "editorial",
        )
    return {
        "root": tmp_path,
        "newsroom": newsroom,
        "stories": stories_path,
        "inbox": inbox_path,
        "article": article,
    }


def _hundred_stories(count: int):
    """`count` current Stories, newest first, with ids that do not track time.

    The id suffix is deliberately scrambled against the timestamp, so any
    ordering that silently falls back to `story_id` produces a different (and
    obviously wrong) sequence than chronological order.
    """
    stories = []
    for index in range(count):
        stories.append(
            _story(
                f"s-{(index * 7919) % count:04d}",
                changed_at=(
                    datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc) - timedelta(minutes=index)
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
    return stories


def _today(paths, *, now=NOW, story_cap=editor_queries.TODAY_STORY_CAP):
    return editor_queries.read_today(
        stories_path=paths["stories"],
        inbox_path=paths["inbox"],
        metadata_root=paths["newsroom"],
        article_root=paths["root"] / "editorial",
        now=now,
        story_cap=story_cap,
    )


# --------------------------------------------------------------------------
# §24 ordering
# --------------------------------------------------------------------------


def test_ordering_follows_the_canonical_timestamp_not_the_story_id(tmp_path):
    """Deliberately non-monotonic ids: id order and time order disagree.

    The old sort key was `latest_development.changed_at`, empty for every Story
    here because no member is classified `NEW_DEVELOPMENT`, so it silently
    became `story_id DESC` — a reverse sort on a SHA-derived hex string.
    """
    stories = [
        _story("s-zzz-oldest", changed_at="2026-09-23T05:00:00Z"),
        _story("s-aaa-newest", changed_at="2026-09-23T09:00:00Z"),
        _story("s-mmm-middle", changed_at="2026-09-23T07:00:00Z"),
    ]
    result = _today(_seed(tmp_path, stories), now=NOW)

    assert [row["id"] for row in result["stories"]] == [
        "s-aaa-newest",
        "s-mmm-middle",
        "s-zzz-oldest",
    ]
    # The rendered date and the sort key are the same chronology by
    # construction: both come from `latestChangeAt`.
    stamps = [row["latestChangeAt"] for row in result["stories"]]
    assert stamps == sorted(stamps, reverse=True)


def test_ordering_is_stable_on_an_exact_timestamp_tie(tmp_path):
    """Equal timestamps keep ascending id order — total, reproducible."""
    stories = [
        _story("s-ccc", changed_at="2026-09-23T08:00:00Z"),
        _story("s-aaa", changed_at="2026-09-23T08:00:00Z"),
        _story("s-bbb", changed_at="2026-09-23T08:00:00Z"),
    ]
    first = [row["id"] for row in _today(_seed(tmp_path, stories), now=NOW)["stories"]]
    second = [row["id"] for row in _today(_seed(tmp_path, stories), now=NOW)["stories"]]

    assert first == ["s-aaa", "s-bbb", "s-ccc"]
    assert second == first  # repeat reads cannot reshuffle the page


def test_ordering_works_when_no_story_has_a_new_development(tmp_path):
    """The real corpus has `NEW_DEVELOPMENT = 0`; ordering must still be correct.

    `latestChangeAt` falls back to `last_seen_at`, so a Story with no
    development still has a real chronology to be ordered on.
    """
    stories = [
        _story("s-one", changed_at="2026-09-22T08:00:00Z"),
        _story("s-two", changed_at="2026-09-23T08:00:00Z"),
    ]
    for story in stories:
        story["latest_material_change_at"] = ""  # no material change recorded
    result = _today(_seed(tmp_path, stories), now=NOW)

    assert [row["id"] for row in result["stories"]] == ["s-two", "s-one"]
    assert [row["latestChangeAt"] for row in result["stories"]] == [
        "2026-09-23T08:00:00Z",
        "2026-09-22T08:00:00Z",
    ]


def test_a_story_with_a_real_development_keeps_its_own_chronology(tmp_path):
    stories = [
        _story("s-newer", changed_at="2026-09-23T09:00:00Z"),
        _story("s-older", changed_at="2026-09-23T06:00:00Z", developments=["2026-09-23T06:30:00Z"]),
    ]
    result = _today(_seed(tmp_path, stories), now=NOW)

    ordered = {row["id"]: row for row in result["stories"]}
    assert ordered["s-older"]["unreviewedDevelopmentCount"] == 1
    # The development is the latest material change, so it is the chronology.
    assert ordered["s-older"]["latestChangeAt"] == "2026-09-23T06:30:00Z"
    assert [row["id"] for row in result["stories"]] == ["s-newer", "s-older"]


# --------------------------------------------------------------------------
# §25 horizon
# --------------------------------------------------------------------------


def test_horizon_keeps_today_and_the_previous_calendar_day(tmp_path):
    stories = [
        _story("s-today", changed_at="2026-09-23T06:00:00Z"),  # 09:00 local
        _story("s-yesterday", changed_at="2026-09-22T20:00:00Z"),  # 23:00 local
        _story("s-two-days-ago", changed_at="2026-09-21T20:00:00Z"),
    ]
    paths = _seed(tmp_path, stories)
    result = _today(paths, now=NOW)

    assert [row["id"] for row in result["stories"]] == ["s-today", "s-yesterday"]
    # Excluded by derivation, not by being marked read: the stored status is
    # still NEW and no store byte changed.
    stored = story_store.read_store(paths["stories"])
    assert {row["story_id"]: row["status"] for row in stored["stories"]}["s-two-days-ago"] == "NEW"


def test_horizon_is_calendar_based_not_a_rolling_window(tmp_path):
    """A 10:00 editor still sees yesterday evening; a 24-hour window would not.

    22:00 local on 2026-09-22 is 29 hours before `NOW`, so a rolling 24-hour
    window would drop it. Editorial work is calendar-based, so it stays.
    """
    stories = [_story("s-last-night", changed_at="2026-09-22T19:00:00Z")]  # 22:00 local
    result = _today(_seed(tmp_path, stories), now=NOW)

    assert [row["id"] for row in result["stories"]] == ["s-last-night"]


def test_horizon_survives_the_midnight_boundary(tmp_path):
    """00:30 local on the 23rd: 23:50 on the 22nd stays, 23:50 on the 21st goes."""
    just_after_midnight = datetime(2026, 9, 22, 21, 30, tzinfo=timezone.utc)  # 00:30 local
    stories = [
        _story("s-late-yesterday", changed_at="2026-09-22T20:50:00Z"),  # 23:50 on the 22nd
        _story("s-too-old", changed_at="2026-09-21T20:50:00Z"),  # 23:50 on the 21st
    ]
    result = _today(_seed(tmp_path, stories), now=just_after_midnight)

    assert [row["id"] for row in result["stories"]] == ["s-late-yesterday"]


def test_horizon_uses_newsroom_local_time_not_utc(tmp_path):
    """01:10 local on the 23rd is still the 22nd in UTC, and still counts.

    The boundary is a newsroom calendar date, so a timestamp must be converted
    before it is compared. Comparing raw UTC dates would wrongly hide it.
    """
    stories = [
        _story("s-just-after-midnight-local", changed_at="2026-09-22T22:10:00Z"),  # 01:10 local
        _story("s-just-before", changed_at="2026-09-21T20:50:00Z"),  # 23:50 on the 21st
    ]
    result = _today(_seed(tmp_path, stories), now=NOW)

    assert [row["id"] for row in result["stories"]] == ["s-just-after-midnight-local"]


def test_an_unreviewed_development_survives_the_horizon(tmp_path):
    """An explicit current reason outlives the horizon — it is not a timestamp.

    The editor has not looked at something that arrived, so dropping it by age
    would hide real work.
    """
    stories = [
        _story(
            "s-old-but-unreviewed",
            changed_at="2026-09-10T08:00:00Z",
            developments=["2026-09-10T09:00:00Z"],
        )
    ]
    result = _today(_seed(tmp_path, stories), now=NOW)

    assert [row["id"] for row in result["stories"]] == ["s-old-but-unreviewed"]
    assert result["stories"][0]["unreviewedDevelopmentCount"] == 1


def test_a_reviewed_development_does_not_rescue_an_old_story(tmp_path):
    """The exception is review state, so reviewing it lets the Story retire.

    This is what stops an old Story surviving forever: the reason to stay has to
    be a real unreviewed development, not merely `status == NEW`.
    """
    stories = [
        _story("s-old", changed_at="2026-09-10T08:00:00Z", developments=["2026-09-10T09:00:00Z"])
    ]
    paths = _seed(tmp_path, stories)
    story_editor_metadata.write_story_editor_metadata(
        {
            "version": 1,
            "stories": [
                {
                    "story_id": "s-old",
                    "followed": True,
                    "last_reviewed_at": "2026-09-11T08:00:00Z",
                    "reviewed_development_ids": [_development_id("s-old", "s-old-dev-0")],
                }
            ],
        },
        root=paths["newsroom"],
    )

    result = _today(paths, now=NOW)
    assert result["stories"] == []
    assert result["storyAttentionTotal"] == 0


def test_article_attention_is_not_subject_to_the_story_horizon(tmp_path):
    """Article work is bounded on its own terms and never competes for the cap."""
    stories = [_story("s-old", changed_at="2026-09-10T08:00:00Z")]
    paths = _seed(tmp_path, stories, article_story="s-old")
    result = editor_queries.read_today(
        stories_path=paths["stories"],
        inbox_path=paths["inbox"],
        metadata_root=paths["newsroom"],
        article_root=paths["root"] / "editorial",
        article_next_actions={paths["article"]["article_id"]: "SELECT_FOCUS"},
        now=NOW,
    )

    # The Story is out of the horizon, so the Article is the only row — and it
    # is still there.
    assert result["stories"] == []
    assert [entry["article"]["id"] for entry in result["articles"]] == [
        paths["article"]["article_id"]
    ]


# --------------------------------------------------------------------------
# §26 cap
# --------------------------------------------------------------------------


def test_cap_bounds_the_first_screen_and_reports_the_withheld_count(tmp_path):
    result = _today(_seed(tmp_path, _hundred_stories(100)), now=NOW, story_cap=30)

    assert result["storyAttentionTotal"] == 100
    assert len(result["stories"]) == 30


def test_cap_keeps_the_newest_candidates(tmp_path):
    result = _today(_seed(tmp_path, _hundred_stories(100)), now=NOW, story_cap=30)
    stamps = [row["latestChangeAt"] for row in result["stories"]]

    assert stamps == sorted(stamps, reverse=True)
    assert stamps[0] == "2026-09-23T06:00:00Z"  # the newest Story survived
    # The oldest 70 are exactly the ones withheld.
    assert stamps[-1] == "2026-09-23T05:31:00Z"


def test_cap_never_displaces_active_article_work(tmp_path):
    """A full Story list must not push an in-progress Article off Today."""
    stories = _hundred_stories(100)
    paths = _seed(tmp_path, stories, article_story=stories[0]["story_id"])
    result = editor_queries.read_today(
        stories_path=paths["stories"],
        inbox_path=paths["inbox"],
        metadata_root=paths["newsroom"],
        article_root=paths["root"] / "editorial",
        article_next_actions={paths["article"]["article_id"]: "SELECT_FOCUS"},
        now=NOW,
        story_cap=30,
    )

    assert len(result["stories"]) == 30
    assert [entry["article"]["id"] for entry in result["articles"]] == [
        paths["article"]["article_id"]
    ]


def test_no_cap_notice_when_everything_qualifies(tmp_path):
    result = _today(_seed(tmp_path, _hundred_stories(5)), now=NOW, story_cap=30)

    assert result["storyAttentionTotal"] == 5
    assert len(result["stories"]) == 5


@pytest.mark.parametrize("cap", [0, 1, 30])
def test_cap_never_exceeds_the_configured_bound(tmp_path, cap):
    result = _today(_seed(tmp_path, _hundred_stories(50)), now=NOW, story_cap=cap)

    assert len(result["stories"]) <= cap
    assert result["storyAttentionTotal"] == 50


# --------------------------------------------------------------------------
# §27 last refresh projection
# --------------------------------------------------------------------------


def _write_last_run(newsroom, payload) -> None:
    (newsroom / "last_run.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_last_refresh_maps_only_the_editor_facing_fields(tmp_path, monkeypatch):
    from editor_assistant.workflow import editor_application as app

    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    _write_last_run(
        newsroom,
        {
            "finished_at": "2026-09-23T06:32:51Z",
            "started_at": "2026-09-23T06:32:35Z",
            "new": 37,
            "failed": 2,
            "collected": 157,
            "duplicate": 120,
            "blocked": 3,
            "blocked_filtered": 4,
            "source_count": 31,
            "problems": [{"source_id": "x", "status": "FAILED", "reason": "timeout"}],
            "new_stories": 12,
        },
    )
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))

    last_refresh = app._today_last_refresh()

    assert last_refresh == {
        "finishedAt": "2026-09-23T06:32:51Z",
        "newPublications": 37,
        "newStories": 12,
        "failedSources": 2,
    }
    # Operational internals stay in the store: the editor's first screen never
    # receives source ids, blocked counts or raw failure reasons.
    serialized = json.dumps(last_refresh)
    for leaked in ("source_count", "blocked", "duplicate", "problems", "timeout", "source_id"):
        assert leaked not in serialized


def test_last_refresh_reports_an_unpersisted_story_count_as_absent(tmp_path, monkeypatch):
    """`null`, not `0`: a run that predates the field has made no claim about it."""
    from editor_assistant.workflow import editor_application as app

    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    _write_last_run(newsroom, {"finished_at": "2026-09-23T06:32:51Z", "new": 5, "failed": 0})
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))

    assert app._today_last_refresh()["newStories"] is None


def test_never_run_is_null_rather_than_a_placeholder(tmp_path, monkeypatch):
    from editor_assistant.workflow import editor_application as app

    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))

    assert app._today_last_refresh() is None


def test_story_count_is_merged_into_the_single_last_run_record(tmp_path):
    """The one persisted field, written into the existing summary — not a log."""
    paths = tmp_path / "run"
    paths.mkdir()
    source_health.record_run(
        {
            "finished_at": "2026-09-23T06:32:51Z",
            "started_at": "2026-09-23T06:32:35Z",
            "new": 37,
            "failed": 0,
            "sources": [],
        },
        path=paths / "last_run.json",
    )
    stored = source_health.record_run_stories(12, path=paths / "last_run.json")

    assert stored["new_stories"] == 12
    assert stored["new"] == 37  # the collection summary survives the merge
    assert source_health.read_last_run(paths / "last_run.json")["new_stories"] == 12


def test_merging_story_count_never_invents_a_run(tmp_path):
    paths = tmp_path / "run"
    paths.mkdir()

    assert source_health.record_run_stories(12, path=paths / "last_run.json") is None
    assert source_health.read_last_run(paths / "last_run.json") is None


# --------------------------------------------------------------------------
# §28 store read count (structural, not a wall-clock benchmark)
# --------------------------------------------------------------------------


def _count_store_reads(paths, *, story_cap=editor_queries.TODAY_STORY_CAP):
    """Count canonical store reads for one Today projection.

    Each call installs its own patches and removes them again, so a second
    measurement in the same test can never wrap an already-wrapped reader and
    silently double every count.
    """
    counts = {"story_store": 0, "inbox": 0, "metadata": 0, "articles": 0}
    targets = {
        "story_store": (story_store, "read_store"),
        "inbox": (inbox_store, "read_items"),
        "metadata": (story_editor_metadata, "read_story_editor_metadata_store"),
        "articles": (editor_article_store, "read_editor_articles"),
    }
    originals = {name: getattr(module, attribute) for name, (module, attribute) in targets.items()}

    def counted(name, original):
        def reader(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)

        return reader

    for name, (module, attribute) in targets.items():
        module.__dict__[attribute] = counted(name, originals[name])
    try:
        _today(paths, story_cap=story_cap)
    finally:
        for name, (module, attribute) in targets.items():
            module.__dict__[attribute] = originals[name]
    return counts


def test_each_canonical_store_is_read_once_regardless_of_story_count(tmp_path):
    """10 Stories and 1000 Stories must cost the same number of reads.

    This asserts the complexity *shape*, not a timing. The old implementation
    re-read every store once per Story (259 / 259 / 259 / 281 calls on 253
    Stories); an invariance over corpus size catches that regression directly,
    where a brittle absolute benchmark would only catch it on one machine.
    """
    few = _count_store_reads(_seed(tmp_path / "few", _hundred_stories(10)))
    many = _count_store_reads(_seed(tmp_path / "many", _hundred_stories(1000)))

    assert few == many, f"store reads scale with corpus size: {few} vs {many}"
    for name, count in few.items():
        assert count <= 2, f"{name} was read {count} times, not a bounded constant"


def test_store_reads_do_not_track_the_number_of_returned_rows(tmp_path):
    """The cap lowers the row count; it must not lower the read count.

    If reads tracked rows rather than stores, a smaller page would look faster
    for the wrong reason, and the cap would mask a regression.
    """
    stories = _hundred_stories(40)
    capped = _count_store_reads(_seed(tmp_path / "a", stories), story_cap=5)
    uncapped = _count_store_reads(_seed(tmp_path / "b", stories), story_cap=30)

    assert capped == uncapped


def test_only_article_content_reads_scale_with_articles(tmp_path):
    """The residual per-Article cost is content, not a corpus re-scan.

    Every Article owns its own current-content file, and readiness genuinely
    depends on that exact version, so one content read per Article is real work.
    What must never happen is that Article count dragging the *Story* and inbox
    stores along with it: 1 Article and 20 Articles must scan the corpus once
    each, not twenty times.
    """
    one = _seed(tmp_path / "one", _hundred_stories(50), article_story="s-0000")
    many = _seed(tmp_path / "many", _hundred_stories(50), article_story="s-0000")
    for index in range(19):
        editor_article_store.create_editor_article(
            story_id="s-0000",
            stories_path=many["stories"],
            working_title=f"Още работа {index}",
            now="2026-09-23T06:00:00Z",
            root=many["root"] / "editorial",
            idempotency_key=f"d1-extra-{index}",
        )

    few = _count_store_reads(one)
    lots = _count_store_reads(many)

    # The Story store and the inbox are read once per projection either way.
    assert few["story_store"] == lots["story_store"] <= 2
    assert few["inbox"] == lots["inbox"] <= 2
    # The Article index grows only with the Articles, never with the Stories.
    assert lots["articles"] > few["articles"]
    assert lots["story_store"] == few["story_store"], "Article count re-scans the corpus"


# --------------------------------------------------------------------------
# §19 the Stories database itself is not rewritten to hide backlog
# --------------------------------------------------------------------------


def test_deriving_today_never_writes_to_any_store(tmp_path):
    stories = _hundred_stories(40) + [_story("s-ancient", changed_at="2026-08-01T08:00:00Z")]
    paths = _seed(tmp_path, stories)
    watched = {
        candidate: candidate.read_bytes()
        for candidate in (
            paths["stories"],
            paths["inbox"],
            story_editor_metadata.story_editor_metadata_path(root=paths["newsroom"]),
        )
        if candidate.exists()
    }

    _today(paths, now=NOW, story_cap=30)

    assert all(candidate.read_bytes() == before for candidate, before in watched.items())
    # The excluded backlog is still on disk, still NEW, and still reachable
    # under «Истории». D1 derives the first screen; it does not edit history.
    stored = story_store.read_store(paths["stories"])["stories"]
    assert {row["story_id"]: row["status"] for row in stored}["s-ancient"] == "NEW"
    assert len(stored) == 41
