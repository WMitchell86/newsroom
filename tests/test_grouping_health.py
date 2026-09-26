"""V1.1-F2A: Story-grouping health and semantic budget sizing.

F1 proved the dominant cause of Story fragmentation was
`B. SEMANTIC_BUDGET_EXHAUSTION`. These tests pin the two halves of the fix:

* the `story` role budget is sized for **measured** grouping demand, and
* a run in which classification could not be completed is **visible** rather
  than silently producing duplicate Stories.

They also pin the safety property that F2A must not change: a degraded run
still keeps publications separate. A false split stays preferable to a false
merge, and `on_exhausted` stays `conservative`.
"""

from __future__ import annotations

import json

import pytest

from editor_assistant.drafting import model_policy
from editor_assistant.workflow import (
    editor_application as app,
)
from editor_assistant.workflow import (
    grouping_health,
    inbox_store,
    story_identity,
    story_relation,
    story_store,
)

#: Measured demand (V1.1-F1 / F0 replay over the 300-item real corpus).
#: 182 logical story requests for a full 300-publication catch-up;
#: 331 logical requests observed on the worst recorded day.
MEASURED_CATCH_UP_DEMAND = 182
OBSERVED_PEAK_LOGICAL_REQUESTS = 331


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWSROOM_DIR", str(tmp_path))
    monkeypatch.setenv("NEWSROOM_INBOX_PATH", str(tmp_path / "inbox.jsonl"))
    monkeypatch.setenv("NEWSROOM_STORIES_PATH", str(tmp_path / "stories.json"))
    monkeypatch.setenv("NEWSROOM_LAST_RUN_PATH", str(tmp_path / "last_run.json"))
    monkeypatch.setenv("NEWSROOM_METADATA_ROOT", str(tmp_path / "meta"))
    return tmp_path


def _item(**over):
    base = {
        "source_id": "monitor-a",
        "url": "https://media.example/a",
        "title": "Община Бургас прие бюджета за 2026 година",
        "published_at": "2026-09-26T08:00:00Z",
        "discovered_at": "2026-09-26T08:00:00Z",
        "source_kind": "official",
        "priority": "high",
        "publisher_domain": "burgas.bg",
        "factual_authority": True,
        "status": "NEW",
    }
    base.update(over)
    base["source_item_id"] = base["url"]
    base.setdefault(
        "item_id",
        inbox_store.item_id_for(base["source_id"], base["source_item_id"], base["url"]),
    )
    return base


def _seed(items):
    return inbox_store.add_items(items)["items"]


def _answer(relation="SAME_STORY", **over):
    payload = {
        "same_event": relation == "SAME_STORY",
        "relation": relation,
        "material_change": False,
        "shared_anchors": ["бюджет"],
        "reason": "едно събитие",
    }
    payload.update(over)
    return json.dumps(payload), {"model": "fake", "role": "story"}


def _answering_model(_prompt, *, role="draft", **kwargs):
    return _answer()


def _budget_exhausted_model(_prompt, *, role="draft", **kwargs):
    """Raise exactly what the router raises when the role's daily cap is spent."""
    from editor_assistant.drafting.model_router import RoleUnavailable

    raise RoleUnavailable(
        "story",
        "няма достъпен маршрут (липсващ ключ, лимит, изключени платени модели или политика)",
        on_exhausted="conservative",
        trace=[
            {
                "route_index": 0,
                "route": "gemini:gemini-3.8-flash",
                "event": "SKIPPED",
                "reason": "твърд дневен лимит на ролята (story): 100",
            }
        ],
    )


def _no_route_model(_prompt, *, role="draft", **kwargs):
    from editor_assistant.drafting.model_router import RoleUnavailable

    raise RoleUnavailable(
        "story",
        "няма достъпен маршрут (липсващ ключ, лимит, изключени платени модели или политика)",
        on_exhausted="conservative",
        trace=[
            {
                "route_index": 0,
                "route": "gemini:gemini-3.8-flash",
                "event": "SKIPPED",
                "reason": "изчерпан дневен лимит на доставчика (429)",
            }
        ],
    )


def _anchored_pair():
    """Two publications the deterministic stage must NOT merge, but a model should.

    Title overlap here is ~0.43: above the anchor gate (0.34) and above the two
    shared strong tokens, but well below the 0.80 deterministic-merge threshold.
    That is exactly the band the semantic stage exists for.
    """
    first = _item(
        url="https://burgas.bg/one",
        title="Община Бургас прие бюджета за 2026 година",
    )
    second = _item(
        url="https://faragency.bg/two",
        title="Община Бургас гласува бюджета за 2026 година в пленарна сесия",
        source_id="monitor-b",
        publisher_domain="faragency.bg",
        summary="Бюджетът на Община Бургас за 2026 година беше гласуван.",
    )
    return first, second


# ------------------------------------------------------------------ §19 budget


def test_story_budget_exceeds_measured_catch_up_demand_with_margin():
    policy = model_policy.load_policy()
    story = model_policy.role_policy(policy, "story")
    hard = int(story["hard_calls_day"])
    soft = int(story["soft_calls_day"])
    assert hard > MEASURED_CATCH_UP_DEMAND, "hard budget must cover a full catch-up"
    assert hard > OBSERVED_PEAK_LOGICAL_REQUESTS, "hard budget must cover the worst observed day"
    assert soft < hard, "soft must warn before the hard cap stops classification"
    assert hard < 10_000, "hard must stay finite"


def test_soft_budget_does_not_warn_during_normal_refresh():
    story = model_policy.role_policy(model_policy.load_policy(), "story")
    # A normal incremental day is a small fraction of the measured catch-up.
    normal_refresh_demand = 40
    assert normal_refresh_demand < int(story["soft_calls_day"])
    assert normal_refresh_demand < int(story["hard_calls_day"])


def test_paid_routes_remain_disabled():
    policy = model_policy.load_policy()
    assert policy["global"]["paid_enabled"] is False


def test_on_exhausted_stays_conservative():
    story = model_policy.role_policy(model_policy.load_policy(), "story")
    assert story["on_exhausted"] == "conservative"


# ------------------------------------------------- §20 healthy / §24 no semantic


def test_healthy_run_reports_healthy_and_no_degradation():
    first, second = _anchored_pair()
    _seed([first, second])
    summary = story_identity.update(dry_run=False, call_model=_answering_model)
    grouping = summary["grouping"]
    assert grouping[grouping_health.FIELD_REQUIRED] == 1
    assert grouping[grouping_health.FIELD_ANSWERED] == 1
    assert grouping[grouping_health.FIELD_STATUS] == grouping_health.GROUPING_HEALTHY
    assert grouping[grouping_health.FIELD_DEGRADED] == 0
    assert grouping[grouping_health.FIELD_LAST_SUCCESS] is not None


def test_run_without_semantic_need_is_healthy_not_unavailable():
    """§24: a run that never needed the model must not be reported as broken."""
    _seed([_item(url="https://burgas.bg/only")])
    summary = story_identity.update(dry_run=False)
    grouping = summary["grouping"]
    assert grouping[grouping_health.FIELD_REQUIRED] == 0
    assert grouping[grouping_health.FIELD_STATUS] == grouping_health.GROUPING_HEALTHY


# ------------------------------------------------------- §21 internal hard cap


def test_internal_budget_exhaustion_is_reported_and_never_merges():
    first, second = _anchored_pair()
    _seed([first])
    story_identity.update(dry_run=False, call_model=_answering_model)
    _seed([second])
    summary = story_identity.update(dry_run=False, call_model=_budget_exhausted_model)
    grouping = summary["grouping"]
    assert grouping[grouping_health.FIELD_STATUS] == grouping_health.GROUPING_BUDGET_EXHAUSTED
    assert grouping[grouping_health.FIELD_DEGRADED] > 0
    assert grouping[grouping_health.FIELD_DEGRADED_BUDGET] > 0
    # The conservative fallback is unchanged: no forced merge.
    assert summary["semantic_matches"] == 0
    assert summary["needs_review"] >= 1
    assert summary["semantic_failures"] >= 1


# ---------------------------------------------------- §22 provider unavailable


def test_provider_outage_is_unavailable_not_budget_exhausted():
    first, second = _anchored_pair()
    _seed([first])
    story_identity.update(dry_run=False, call_model=_answering_model)
    _seed([second])
    summary = story_identity.update(dry_run=False, call_model=_no_route_model)
    grouping = summary["grouping"]
    assert grouping[grouping_health.FIELD_STATUS] == grouping_health.GROUPING_UNAVAILABLE
    assert grouping[grouping_health.FIELD_DEGRADED_UNAVAILABLE] > 0
    assert grouping[grouping_health.FIELD_DEGRADED_BUDGET] == 0


# ------------------------------------------------------------- §23 mixed run


def test_mixed_run_keeps_last_success_and_counts_both_sides():
    """The actual 2026-09-25 shape: some answered, then the budget ran out."""
    health = grouping_health.GroupingHealth()
    health.required_semantic()
    health.answered(at="2026-09-25T10:00:00Z")
    health.required_semantic()
    health.failed(story_relation.FAILURE_BUDGET)
    summary = health.summary()
    assert summary[grouping_health.FIELD_STATUS] == grouping_health.GROUPING_BUDGET_EXHAUSTED
    assert summary[grouping_health.FIELD_ANSWERED] == 1
    assert summary[grouping_health.FIELD_DEGRADED] == 1
    assert summary[grouping_health.FIELD_LAST_SUCCESS] == "2026-09-25T10:00:00Z"


# ------------------------------------------------------------- Today surface


def _write_last_run(tmp_path, grouping):
    """Write a latest-run record at the path the application will actually read.

    The path is passed explicitly to `source_health` rather than relied upon
    through the environment: the browser suite sets `NEWSROOM_DIR` process-wide,
    so an env-derived path is not hermetic against a full-suite run.
    """
    from editor_assistant.workflow import source_health

    path = tmp_path / "last_run.json"
    source_health.record_run(
        {
            "finished_at": "2026-09-26T09:00:00Z",
            "started_at": "2026-09-26T08:59:00Z",
            "collected": 40,
            "new": 12,
            "duplicate": 3,
            "failed": 0,
            "sources": [],
        },
        path=path,
    )
    if grouping is not None:
        source_health.record_run_grouping(grouping, path=path)
    return path


def test_today_exposes_grouping_health_when_degraded(tmp_path, monkeypatch):
    path = _write_last_run(
        tmp_path,
        {
            "status": "budget_exhausted",
            "lastSuccessfulSemanticClassificationAt": "2026-09-26T08:55:00Z",
            "semanticRequired": 40,
            "semanticAnswered": 12,
            "semanticDegraded": 28,
        },
    )
    monkeypatch.setenv("NEWSROOM_LAST_RUN_PATH", str(path))
    health = app._today_grouping_health()
    assert health is not None
    assert health["status"] == "budget_exhausted"
    assert health["semanticDegraded"] == 28


def test_today_stays_quiet_for_healthy_and_unknown(tmp_path, monkeypatch):
    path = _write_last_run(
        tmp_path, {"status": "healthy", "semanticRequired": 5, "semanticDegraded": 0}
    )
    monkeypatch.setenv("NEWSROOM_LAST_RUN_PATH", str(path))
    assert grouping_health.is_healthy({"grouping": {"status": "healthy"}}) is True
    # A run that predates this field is unknown, not unhealthy: no warning.
    assert grouping_health.is_healthy({"finished_at": "x"}) is True
    assert app._today_grouping_health()["status"] == grouping_health.GROUPING_HEALTHY
    # Now remove the grouping block: the reader must report unknown, not healthy.
    from editor_assistant.workflow import source_health

    record = source_health.read_last_run(path)
    record.pop("grouping", None)
    path.write_text(json.dumps(record), encoding="utf-8")
    assert app._today_grouping_health() is None
    assert grouping_health.is_healthy(source_health.read_last_run(path)) is True


def test_grouping_health_never_carries_provider_vocabulary(tmp_path, monkeypatch):
    """Editor-facing DTOs must not leak route ids, models or HTTP categories."""
    path = _write_last_run(
        tmp_path,
        {
            "status": "budget_exhausted",
            "lastSuccessfulSemanticClassificationAt": None,
            "semanticRequired": 3,
            "semanticAnswered": 0,
            "semanticDegraded": 3,
        },
    )
    monkeypatch.setenv("NEWSROOM_LAST_RUN_PATH", str(path))
    rendered = json.dumps(app._today_grouping_health()).lower()
    for forbidden in ("gemini", "openrouter", "429", "role_hard_budget", "flash", "route"):
        assert forbidden not in rendered


# ------------------------------------------------------------ safety unchanged


def test_observability_never_changes_a_merge_decision():
    """A recorder that raises must not be able to alter grouping."""
    first, second = _anchored_pair()
    _seed([first])
    story_identity.update(dry_run=False, call_model=_answering_model)
    _seed([second])

    class Exploding:
        def required_semantic(self):
            raise RuntimeError("boom")

        def answered(self, *, at=None):
            raise RuntimeError("boom")

        def failed(self, reason):
            raise RuntimeError("boom")

        def failure_reporter(self):
            return None

        def summary(self):
            return {}

    plan = story_identity.build_plan(call_model=_answering_model, health=Exploding())
    # The model still merged, i.e. reporting never suppressed a legitimate merge.
    assert sum(1 for row in plan["outcomes"] if row.get("action") == "SEMANTIC") == 1


def test_story_store_is_untouched_by_degraded_runs():
    first, second = _anchored_pair()
    _seed([first])
    story_identity.update(dry_run=False, call_model=_answering_model)
    _seed([second])
    story_identity.update(dry_run=False, call_model=_budget_exhausted_model)
    stories = story_store.read_stories()
    assert len(stories) == 2, "a degraded run keeps publications separate"
