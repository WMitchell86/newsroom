"""V1.1-F2B2 §2/§7/§20: the bounded-paid override must not leak.

F2B2 enables paid routes for a single maintenance replay. The safety property
that matters is not "the replay works" but:

    the override exists only inside the replay process, and the newsroom's
    normal policy is `paid_enabled: false` before, during and after.

These tests pin that property, the call cap, and the free-first route order.
They run entirely offline: no provider is contacted, so they assert the
*mechanism* rather than a replay outcome.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from editor_assistant.drafting import model_policy

ROOT = Path(__file__).resolve().parents[1]


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "f2b2", ROOT / "scripts" / "v11f2b2_bounded_paid_healthy_replay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness():
    return _load_harness()


@pytest.fixture(autouse=True)
def clean_policy_env(monkeypatch):
    """No test may inherit a leaked override from another test."""
    monkeypatch.delenv("MODEL_POLICY_PATH", raising=False)
    yield
    os.environ.pop("MODEL_POLICY_PATH", None)


# ------------------------------------------------------------------ §1/§2


def test_normal_runtime_policy_keeps_paid_disabled(harness, tmp_path, monkeypatch):
    """The newsroom's own policy must report paid_enabled False."""
    assert harness.normal_policy_paid_enabled() is False
    assert model_policy.load_policy()["global"]["paid_enabled"] is False


def test_scoped_policy_lives_outside_the_repository(harness, tmp_path):
    scoped = harness.build_scoped_policy(tmp_path / "replay_policy.json", hard_calls_day=220)
    path = tmp_path / "replay_policy.json"
    assert path.exists()
    assert scoped["global"]["paid_enabled"] is True
    # The operator override and the tracked default are never written.
    operator_policy = ROOT / "var" / "model_policy.json"
    before = operator_policy.read_bytes() if operator_policy.exists() else None
    harness.build_scoped_policy(path, hard_calls_day=220)
    after = operator_policy.read_bytes() if operator_policy.exists() else None
    assert before == after, "the operator policy file must not be rewritten"
    default_policy = ROOT / "config" / "model_policy.default.json"
    assert json.loads(default_policy.read_text(encoding="utf-8"))["global"]["paid_enabled"] is False


def test_scoped_override_raises_then_lowers_a_cap(harness, tmp_path, monkeypatch):
    """The scoped policy is process-scoped: it is honoured only while set."""
    path = tmp_path / "replay_policy.json"
    harness.build_scoped_policy(path, hard_calls_day=220)
    assert model_policy.load_policy()["global"]["paid_enabled"] is False

    monkeypatch.setenv("MODEL_POLICY_PATH", str(path))
    scoped = model_policy.load_policy()
    assert scoped["global"]["paid_enabled"] is True
    assert model_policy.role_policy(scoped, "story")["hard_calls_day"] == 220

    monkeypatch.delenv("MODEL_POLICY_PATH")
    assert model_policy.load_policy()["global"]["paid_enabled"] is False


def test_route_order_is_not_reordered_by_the_override(harness, tmp_path):
    """§5: paid is a fallback, never promoted to first choice."""
    scoped = harness.build_scoped_policy(tmp_path / "p.json", hard_calls_day=220)
    normal = model_policy.load_policy()
    assert [r["model"] for r in scoped["roles"]["story"]["routes"]] == [
        r["model"] for r in normal["roles"]["story"]["routes"]
    ]
    free_first = [r for r in scoped["roles"]["story"]["routes"] if r["billing"] != "paid"]
    assert free_first, "at least one free route must precede the paid ones"
    routes = scoped["roles"]["story"]["routes"]
    first_paid = next(i for i, r in enumerate(routes) if r["billing"] == "paid")
    last_free = max(i for i, r in enumerate(routes) if r["billing"] != "paid")
    assert last_free < first_paid, "every free route must be tried before any paid route"


# ---------------------------------------------------------------------- §3/§9


def test_default_cap_is_bounded_and_above_expected_demand(harness):
    assert harness.MAX_SEMANTIC_CALLS == 220
    assert harness.EXPECTED_SEMANTIC_CALLS == 182
    assert harness.MAX_SEMANTIC_CALLS > harness.EXPECTED_SEMANTIC_CALLS
    assert harness.MAX_SEMANTIC_CALLS < 500, "the cap must stay narrow"


def test_cap_exhaustion_is_never_a_merge(harness, monkeypatch):
    """Reaching the cap stops the run; it never becomes a merge.

    The harness raises when the cap is passed, and the production
    `story_relation.classify` turns any exception into `None`, which the
    grouper treats as `REVIEW` + kept separate. That is the §9 requirement:
    a capped run degrades conservatively and is reported, never silently
    continued and never merged. Both halves are asserted here.
    """
    from editor_assistant.drafting import model_router
    from editor_assistant.workflow import story_relation

    def _fake_route(role, prompt, **kwargs):
        raise model_router.RoleUnavailable(
            role,
            "MAINTENANCE_CAP_INSUFFICIENT",
            on_exhausted="conservative",
            trace=[{"event": "SKIPPED", "reason": "replay maintenance cap reached"}],
        )

    monkeypatch.setattr(model_router, "call_role", _fake_route)
    model = harness.ReplayCallModel(cap=2)

    answers = []
    for _ in range(5):
        model.begin("i1", "s1", {})
        # classify() is the real production wrapper: a raise must become None.
        answers.append(story_relation.classify({}, {}, {}, call_model=model))
        model.end()

    assert answers == [None] * 5, "a capped run must never produce a relation"
    summary = model.summary()
    assert summary["capReached"] is True
    # Every capped item is also a degraded item: the cap must not hide the
    # quality loss it causes, which is the whole point of the §8 criterion.
    assert summary["semanticDegraded"] == 5
    assert summary["semanticAnswered"] == 0
    assert summary["paidAnswered"] == 0
    assert summary["budgetFailures"] == 5


# ---------------------------------------------------------------------- §6


def test_corpus_freeze_matches_f1(harness):
    assert harness.CORPUS_FINGERPRINT == "d02f2b9b5a281434"
    assert harness.corpus_fingerprint() == harness.CORPUS_FINGERPRINT


def test_expected_demand_is_the_measured_f1_number(harness):
    """§3/§6: the expected demand is F1's measurement, not a guess."""
    assert harness.EXPECTED_SEMANTIC_CALLS == 182
    assert harness.EXPECTED_SEMANTIC_CALLS < harness.MAX_SEMANTIC_CALLS
