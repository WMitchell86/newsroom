"""V1.2-G4.6 — the editor's «Обнови» must finish.

Real failure this pins: `refresh_newsroom` collected 7 new publications and
then spent 12+ minutes in the semantic stage, because Draft-role Gemini is
capped at 5 calls/minute and the router waits out the window before each one.
`stories.json` is written only at the END of that stage, so Today showed a list
15 hours old while the UI reported a finished refresh.

The test counts MODEL CALLS, not seconds: that is the thing the product
controls, and it is the thing that made the run unbounded.
"""

import json

import pytest

from editor_assistant.workflow import grouping_health, newsroom_refresh, story_identity


def _inbox_item(item_id, title, published_at, source_id="src-1"):
    return {
        "item_id": item_id,
        "title": title,
        "published_at": published_at,
        "source_id": source_id,
        "url": f"https://example.com/{item_id}",
    }


def test_budget_stops_the_semantic_stage_before_the_model_is_called():
    """The budget must refuse BEFORE calling, not after."""
    health = grouping_health.GroupingHealth(enabled=True, call_budget=2)
    assert health.spend_call() is True
    assert health.spend_call() is True
    # Third call is refused without the provider being contacted.
    assert health.spend_call() is False
    assert health.calls_spent() == 2


def test_zero_budget_never_calls_the_model():
    health = grouping_health.GroupingHealth(enabled=True, call_budget=0)
    assert health.spend_call() is False
    assert health.calls_spent() == 0


def test_unbounded_is_still_the_default_for_the_cli():
    """CLI/cron callers keep the old behaviour; only the refresh is bounded."""
    health = grouping_health.GroupingHealth(enabled=True)
    for _ in range(50):
        assert health.spend_call() is True


def test_refresh_budget_is_bounded_and_configurable():
    assert isinstance(newsroom_refresh.REFRESH_SEMANTIC_CALL_BUDGET, int)
    assert 0 < newsroom_refresh.REFRESH_SEMANTIC_CALL_BUDGET <= 20


def test_update_bounds_model_calls_and_still_writes_stories(tmp_path):
    """The end of the promise: a bounded run still returns, and still stores."""
    inbox = tmp_path / "inbox.jsonl"
    stories = tmp_path / "stories.json"
    items = [
        _inbox_item(f"it-{i}", f"Crimea report number {i} with a long enough title to anchor",
                    f"2026-09-29T08:{i:02d}:00Z")
        for i in range(6)
    ]
    inbox.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n",
                     encoding="utf-8")
    stories.write_text(json.dumps({"version": 1, "stories": [], "overrides": {}}),
                       encoding="utf-8")

    calls = []

    def call_model(prompt, **kwargs):
        calls.append(prompt)
        return ("DIFFERENT_STORY", {"relation": "DIFFERENT_STORY"})

    story_identity.update(
        inbox=inbox, stories=stories, dry_run=False, semantic=True,
        call_model=call_model, call_budget=2,
    )

    # The run returned, it did not hang trying to classify all six.
    assert len(calls) <= 2, f"budget ignored: {len(calls)} model calls"
    # And the work it DID decide is persisted — a bounded run is not a no-op.
    stored = json.loads(stories.read_text(encoding="utf-8"))
    assert stored["stories"], "a bounded run must still write the stories it grouped"


def test_exhausted_budget_is_reported_as_budget_not_provider_failure(tmp_path):
    """An operator must be able to tell OUR limit from a provider outage."""
    inbox = tmp_path / "inbox.jsonl"
    stories = tmp_path / "stories.json"
    items = [
        _inbox_item(f"it-{i}", f"Crimea report number {i} with a long enough title to anchor",
                    f"2026-09-29T08:{i:02d}:00Z")
        for i in range(4)
    ]
    inbox.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n",
                     encoding="utf-8")
    stories.write_text(json.dumps({"version": 1, "stories": [], "overrides": {}}),
                       encoding="utf-8")

    summary = story_identity.update(
        inbox=inbox, stories=stories, dry_run=True, semantic=True,
        call_model=lambda p, **k: pytest.fail("model must not be called at budget 0"),
        call_budget=0,
    )
    grouping = summary["grouping"]
    assert grouping["semanticDegradedBudgetExhausted"] >= 1, grouping
    assert grouping["status"] == "budget_exhausted", grouping


def _newsroom(tmp_path, monkeypatch, *, semantic, call_model=None, usable_route):
    """A one-source newsroom whose refresh runs for real, minus the network."""
    from editor_assistant.workflow import newsroom_refresh as nr

    root = tmp_path / "newsroom"
    root.mkdir(parents=True, exist_ok=True)
    from editor_assistant.workflow import sources_registry

    sources_registry.add_source(
        path=root / "sources.json", source_id="src-1", name="Test",
        kind="official", collector="rss", url="https://feed.example/rss",
    )
    (root / "inbox.jsonl").write_text("", encoding="utf-8")
    (root / "stories.json").write_text(
        json.dumps({"version": 1, "stories": [], "overrides": {}}), encoding="utf-8")

    item = {
        "item_id": "it-1",
        "title": "Преследване с 200 км/ч извън град",
        "published_at": "2026-09-29T08:00:00Z",
        "source_id": "src-1",
        "url": "https://example.com/1",
    }
    monkeypatch.setattr(nr.newsroom_run, "collect", lambda **kw: {
        "collected": 1, "new": 1, "duplicate": 0, "failed": 0,
        "finished_at": "2026-09-29T09:10:00Z", "locked": False,
    })
    monkeypatch.setattr(nr.model_router, "role_has_usable_route",
                        lambda role, **kw: usable_route)
    return root, item


def test_refresh_finishes_and_reports_unavailable_when_the_role_is_spent(
    tmp_path, monkeypatch
):
    """The whole failure, end to end: an exhausted story role must not hang.

    Before the fix this run spent one per-minute deferral per classification
    and the editor's Today list stayed frozen for the duration.
    """
    from editor_assistant.workflow import newsroom_refresh

    nr = newsroom_refresh
    root, _item = _newsroom(tmp_path, monkeypatch, semantic=True, usable_route=False)
    # The real collector writes this file; the stand-in above does not, and the
    # merge helpers are documented to leave an unrecorded run unrecorded.
    (root / "last_run.json").write_text(
        json.dumps({"finished_at": "2026-09-29T09:10:00Z", "new": 1}), encoding="utf-8")
    monkeypatch.setattr(nr.story_identity, "update", lambda **kw: {
        "scanned": 1, "new_stories": 1, "needs_review": 0,
        "grouping": {"status": "healthy"}, "semantic_matches": 0, "semantic_failures": 0,
    })

    result = nr.refresh_newsroom(root=root, semantic=True)

    # The run completed and reported what it did.
    assert result["stories"]["newStories"] == 1  # the stub grouped one
    record = json.loads((root / "last_run.json").read_text(encoding="utf-8"))
    block = nr.grouping_health.read_grouping_health(record)
    assert block is not None, record
    assert block[nr.grouping_health.FIELD_STATUS] == "unavailable", block


def test_an_injected_call_model_is_never_vetoed_by_the_quota_gate(
    tmp_path, monkeypatch
):
    """A caller that supplies its own classifier keeps semantic grouping on.

    Otherwise the guard silently changes grouping decisions for every test and
    operator override that passes a callable — a quota check turning into a
    correctness bug.
    """
    from editor_assistant.workflow import newsroom_refresh as nr

    captured = {}

    def fake_update(**kw):
        captured.update(kw)
        return {"scanned": 0, "new_stories": 0, "needs_review": 0,
                "grouping": {"status": "healthy"}}

    root, _item = _newsroom(tmp_path, monkeypatch, semantic=True, usable_route=False)
    monkeypatch.setattr(nr.story_identity, "update", fake_update)

    nr.refresh_newsroom(root=root, semantic=True, call_model=lambda p, **k: None)

    assert captured["semantic"] is True, captured
