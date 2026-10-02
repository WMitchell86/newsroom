"""M4D model policy tests — hermetic, no network, no provider key required.

They pin the routing contract the operator now owns:

* the route order in the policy is what actually happens;
* disabled, paid-disabled, privacy-blocked, budget-spent and unhealthy routes are
  skipped with a recorded reason;
* a Gemini failure really falls through to OpenRouter (the old key-presence
  short-circuit never did);
* invalid models stop burning requests, quotas stop for the provider period;
* retries are bounded;
* every role has an explicit safe degradation: story never merges, judge never
  reports a pass, draft never descends to an unqualified free route;
* the usage ledger aggregates calls and never stores prompts.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from editor_assistant.drafting import (
    generate,
    model_catalog,
    model_policy,
    model_prompt_log,
    model_router,
    model_usage,
)
from editor_assistant.workflow import discovery, story_relation


def _route(provider, model, *, billing=None, public_only=None, limit=None, enabled=True):
    route = {"provider": provider, "model": model, "enabled": enabled}
    if billing:
        route["billing"] = billing
    if public_only is not None:
        route["public_only"] = public_only
    if limit:
        route["daily_call_limit"] = limit
    return route


def _policy_with(role, routes, **role_overrides):
    """Tracked defaults with one role's routes replaced (everything else intact)."""
    policy = model_policy.normalize(model_policy.load_defaults())
    policy["roles"][role]["routes"] = routes
    policy["roles"][role].update(role_overrides)
    return model_policy.normalize(policy)


def _http_error(code, body=""):
    return (
        urllib.error.HTTPError("https://example.invalid", code, "err", {}, None)
        if False
        else _FakeHTTPError(code, body)
    )


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body):
        super().__init__("https://example.invalid", code, "err", {}, None)
        self._chernomorie_body = body

    def read(self):  # pragma: no cover - body carried on the exception already
        return (self._chernomorie_body or "").encode()


class _Callers:
    """Recording fake transports for the router."""

    def __init__(self, gemini=None, openrouter=None):
        self.gemini_calls = []
        self.openrouter_calls = []
        self._gemini = gemini
        self._openrouter = openrouter

    def gemini(self, prompt, **kwargs):
        self.gemini_calls.append(kwargs.get("model"))
        if self._gemini is None:
            return "gemini-answer", {"model": kwargs.get("model"), "provider": "gemini"}
        return self._gemini(prompt, **kwargs)

    def openrouter(self, prompt, **kwargs):
        self.openrouter_calls.append(kwargs.get("model"))
        if self._openrouter is None:
            return "openrouter-answer", {"model": kwargs.get("model"), "provider": "openrouter"}
        return self._openrouter(prompt, **kwargs)

    def as_map(self):
        return {"gemini": self.gemini, "openrouter": self.openrouter}


# ---------------------------------------------------------------- config validation


def test_unknown_role_and_invalid_shapes_fail_closed():
    defaults = model_policy.load_defaults()
    broken = json.loads(json.dumps(defaults))
    broken["roles"]["wizard"] = broken["roles"]["judge"]
    with pytest.raises(model_policy.PolicyError):
        model_policy.normalize(broken)

    missing = json.loads(json.dumps(defaults))
    missing["roles"].pop("draft")
    with pytest.raises(model_policy.PolicyError):
        model_policy.normalize(missing)

    bad_billing = json.loads(json.dumps(defaults))
    bad_billing["roles"]["judge"]["routes"][0]["billing"] = "cheapish"
    with pytest.raises(model_policy.PolicyError):
        model_policy.normalize(bad_billing)

    bad_budget = json.loads(json.dumps(defaults))
    bad_budget["roles"]["judge"]["soft_calls_day"] = 500
    bad_budget["roles"]["judge"]["hard_calls_day"] = 10
    with pytest.raises(model_policy.PolicyError):
        model_policy.normalize(bad_budget)


def test_validate_policy_reports_a_broken_policy_instead_of_raising():
    problems = model_policy.validate_policy({"roles": {}})
    assert problems and "roles" in problems[0]


def test_all_roles_have_explicit_degradation_and_budgets():
    policy = model_policy.load_policy()
    assert set(policy["roles"]) == set(model_policy.ROLES)
    for role in model_policy.ROLES:
        raw = policy["roles"][role]
        assert raw["on_exhausted"] in model_policy.ON_EXHAUSTED
        assert raw["hard_calls_day"] > 0
        assert raw["routes"], role


# ---------------------------------------------------------------- routing


def test_route_order_is_authoritative(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "first-model"),
            _route("gemini", "second-model"),
            _route("openrouter", "third/model:free", billing="free"),
        ],
    )
    callers = _Callers()
    text, meta = model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert text == "gemini-answer"
    assert callers.gemini_calls == ["first-model"]
    assert meta["route_index"] == 0 and meta["fallbacks"] == 0


def test_disabled_route_is_skipped(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "off-model", enabled=False),
            _route("gemini", "on-model"),
        ],
    )
    callers = _Callers()
    _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert callers.gemini_calls == ["on-model"]
    assert meta["fallbacks"] == 1  # the disabled route was skipped, not tried
    trace = meta["trace"]
    assert any(row["event"] == "SKIPPED" for row in trace)


def test_privacy_gate_off_allows_free_route_for_private_editorial_payload(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "draft",
        [_route("openrouter", "free/model:free", billing="free", public_only=True)],
    )
    callers = _Callers()
    model_router.call_role("draft", "private editorial", policy=policy, call_map=callers.as_map())
    assert callers.openrouter_calls == ["free/model:free"]
    assert policy["global"]["privacy_gate_enabled"] is False


def test_privacy_gate_status_is_auditable():
    policy = model_policy.load_policy()
    report = model_router.status_report(policy=policy)
    assert report["privacy_gate_enabled"] is False
    assert report["roles"]
    for role in report["roles"]:
        for route in role["routes"]:
            assert "public_only" in route


def test_paid_route_is_skipped_when_paid_is_disabled(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with("draft", [_route("openrouter", "paid/model", billing="paid")])
    callers = _Callers()
    with pytest.raises(model_router.RoleUnavailable) as exc:
        model_router.call_role("draft", "p", policy=policy, call_map=callers.as_map())
    assert callers.openrouter_calls == []
    assert exc.value.on_exhausted == policy["roles"]["draft"]["on_exhausted"]
    assert "платените модели са изключени" in json.dumps(exc.value.trace, ensure_ascii=False)


def test_paid_route_runs_when_the_operator_enables_paid(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with("draft", [_route("openrouter", "paid/model", billing="paid")])
    policy["global"]["paid_enabled"] = True
    policy = model_policy.normalize(policy)
    callers = _Callers()
    text, meta = model_router.call_role("draft", "p", policy=policy, call_map=callers.as_map())
    assert text == "openrouter-answer"
    assert callers.openrouter_calls == ["paid/model"]
    assert meta["route_index"] == 0


def test_true_cross_provider_fallback_gemini_to_openrouter(monkeypatch):
    """The old code returned early on GEMINI_API_KEY, so this never happened.

    The backup route is free OpenRouter, so under the A2 invariant it is
    public-only and the payload class is public (transcript/public entailment).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "dry-model"),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def exhausted(_prompt, **_kwargs):
        raise _FakeHTTPError(429, "You exceeded your current quota, please check your plan")

    callers = _Callers(gemini=exhausted)
    text, meta = model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert callers.gemini_calls == ["dry-model"]
    assert callers.openrouter_calls == ["backup/model:free"]
    assert text == "openrouter-answer"
    assert meta["fallbacks"] == 1


def test_invalid_model_marks_the_route_unhealthy_until_the_policy_changes(monkeypatch):
    """A 400 that *names* a missing model is permanent; the route is not retried."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "removed-model"),
            _route("openrouter", "working/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def gone(_prompt, **_kwargs):
        # The wording the provider actually uses for a model it does not serve.
        # `invalid model id` (the old fixture) is NOT a marker the classifier
        # recognises on purpose: a bare 400 is a malformed REQUEST, and treating
        # it as a removed model is what once parked the only working Draft route
        # as INVALID until the policy changed (V1.2-G4.2 §12/§14).
        raise _FakeHTTPError(
            400, '{"error": {"message": "models/removed-model is not found for API version v1beta"}}'
        )

    callers = _Callers(gemini=gone)
    model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert callers.gemini_calls == ["removed-model"]

    # Second call with the SAME policy hash must not burn another request.
    _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert callers.gemini_calls == ["removed-model"]
    assert meta["route_index"] == 1

    # A policy change (explicit revalidation surface) clears the stale mark.
    changed = model_policy.normalize(json.loads(json.dumps(policy)))
    changed["roles"]["judge"]["soft_calls_day"] = policy["roles"]["judge"]["soft_calls_day"] + 1
    changed = model_policy.normalize(changed)
    callers2 = _Callers()
    model_router.call_role("judge", "p", policy=changed, call_map=callers2.as_map())
    assert callers2.gemini_calls == ["removed-model"]


def test_a_bare_400_is_retryable_and_never_a_removed_model(monkeypatch):
    """The counterpart of the test above: a 400 with no model-missing marker.

    Gemini answers 400 for a malformed request (an unsupported generation
    parameter, an output budget below its own thinking budget). Reading that as
    "this model does not exist" parked the only working Draft route as INVALID
    until the policy changed, which made the primary product action look
    permanently broken while the model answered fine.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "healthy-model"),
            _route("openrouter", "working/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def malformed(_prompt, **_kwargs):
        raise _FakeHTTPError(400, '{"error": {"message": "Invalid JSON payload received"}}')

    callers = _Callers(gemini=malformed)
    _text, meta = model_router.call_role(
        "judge", "p", policy=policy, call_map=callers.as_map(), sleep=lambda _s: None
    )
    # Retried within the route (bounded), then the next route answered.
    assert callers.gemini_calls == ["healthy-model", "healthy-model"]
    assert meta["route_index"] == 1
    # The route is NOT marked INVALID: the policy's route order still stands.
    assert model_router.read_health().get("gemini:healthy-model") is None


def test_an_ambiguous_quota_429_does_not_buy_a_day_long_mark(monkeypatch):
    """`You exceeded your current quota` names no window, so the router may not claim one.

    Measured 2026-09-28: this exact wording was read as a daily exhaustion and
    four working Draft routes were marked EXHAUSTED until the next provider
    reset (~14 h). The category is now QUOTA_AMBIGUOUS, the health mark is the
    short RATE_LIMITED window, and the route stays usable after it.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "throttled"),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def throttled(_prompt, **_kwargs):
        raise _FakeHTTPError(
            429,
            '{"error": {"message": "You exceeded your current quota, please check your plan"}}',
        )

    callers = _Callers(gemini=throttled)
    _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    # One attempt on the throttled route, then the fallback answered.
    assert callers.gemini_calls == ["throttled"]
    assert meta["route_index"] == 1

    health = model_router.read_health()["gemini:throttled"]
    assert health["status"] == model_router.STATUS_RATE_LIMITED
    assert health["status"] != model_router.STATUS_EXHAUSTED
    assert health["until"], "a short window must be stated"
    # ...and the window is minutes, not the next provider midnight.
    assert health["until"] < model_router._iso(
        model_router._utc_now() + timedelta(minutes=5)
    )


def test_an_explicit_daily_quota_429_still_marks_the_route_for_the_period(monkeypatch):
    """The ambiguous rule must not weaken the real daily signal."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "spent"),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def spent(_prompt, **_kwargs):
        raise _FakeHTTPError(429, '{"error": {"status": "per day limit exceeded (RPD)"}}')

    callers = _Callers(gemini=spent)
    model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    health = model_router.read_health()["gemini:spent"]
    assert health["status"] == model_router.STATUS_EXHAUSTED


def test_provider_reset_metadata_wins_over_ambiguous_quota_wording(monkeypatch):
    """`retryDelay` in the body is the provider stating its own short reset."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "brief"),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def brief(_prompt, **_kwargs):
        raise _FakeHTTPError(
            429,
            '{"error": {"message": "quota", "details": [{"retryDelay": "12s"}]}}',
        )

    callers = _Callers(gemini=brief)
    _text, meta = model_router.call_role(
        "judge", "p", policy=policy, call_map=callers.as_map(), sleep=lambda _s: None
    )
    # A stated short reset is worth the bounded RATE_LIMITED retry, then the
    # next route answers.
    assert callers.gemini_calls == ["brief", "brief"]
    assert meta["route_index"] == 1
    # The provider's own retry metadata means the route is throttled briefly,
    # never parked until the next reset.
    assert model_router.read_health()["gemini:brief"]["status"] == model_router.STATUS_RATE_LIMITED


def test_quota_exhaustion_skips_the_route_for_the_provider_period(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "quota-model"),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def quota(_prompt, **_kwargs):
        raise _FakeHTTPError(429, '{"error": {"status": "QUOTA_EXHAUSTED"}} per day')

    callers = _Callers(gemini=quota)
    model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert callers.gemini_calls == ["quota-model"]  # exhausted once, not twice
    assert model_router.read_health()["gemini:quota-model"]["status"] == "EXHAUSTED"


def test_payment_required_is_not_retried_blindly(monkeypatch):
    """OpenRouter answers 402 when the account has no credits: retrying is pointless."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    policy = _policy_with(
        "draft",
        [
            _route("openrouter", "paid/a", billing="paid"),
            _route("openrouter", "paid/b", billing="paid"),
        ],
    )
    policy["global"]["paid_enabled"] = True
    policy = model_policy.normalize(policy)
    calls = []

    def no_credits(_prompt, **kwargs):
        calls.append(kwargs.get("model"))
        raise _FakeHTTPError(402, "Insufficient credits")

    callers = _Callers(openrouter=no_credits)
    with pytest.raises(model_router.RoleUnavailable):
        model_router.call_role(
            "draft", "p", policy=policy, call_map=callers.as_map(), sleep=lambda _s: None
        )
    assert calls == ["paid/a", "paid/b"]  # each route once, no retry loop
    health = model_router.read_health()
    assert health["openrouter:paid/a"]["status"] == "INVALID"
    assert model_usage.daily_summary()["payment_failures"] == 2


def test_transient_failure_retries_are_bounded(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "flaky"),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )
    attempts = {"n": 0}

    def flaky(_prompt, **_kwargs):
        attempts["n"] += 1
        raise _FakeHTTPError(503, "service unavailable")

    callers = _Callers(gemini=flaky)
    _text, meta = model_router.call_role(
        "judge", "p", policy=policy, call_map=callers.as_map(), sleep=lambda _s: None
    )
    assert attempts["n"] == policy["global"]["max_transient_attempts"]
    assert meta["route_index"] == 1


def test_empty_output_retries_once_then_continues(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "story",
        [
            _route("gemini", "silent"),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
    )
    calls = {"n": 0}

    def silent(_prompt, **_kwargs):
        calls["n"] += 1
        return "", {"provider": "gemini"}

    callers = _Callers(gemini=silent)
    text, meta = model_router.call_role(
        "story", "p", policy=policy, call_map=callers.as_map(), sleep=lambda _s: None
    )
    assert calls["n"] == 2
    assert text == "openrouter-answer" and meta["route_index"] == 1


def test_privacy_gate_blocks_public_only_routes_for_private_material(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    policy = _policy_with(
        "draft",
        [
            _route("openrouter", "free/model:free", billing="free", public_only=True),
            _route("openrouter", "paid/model", billing="paid"),
        ],
    )
    policy["global"]["paid_enabled"] = True
    policy["global"]["privacy_gate_enabled"] = True
    policy = model_policy.normalize(policy)
    callers = _Callers()
    _text, meta = model_router.call_role("draft", "p", policy=policy, call_map=callers.as_map())
    assert callers.openrouter_calls == ["paid/model"]
    assert "само за публични" in json.dumps(meta["trace"], ensure_ascii=False)

    # An explicitly public payload may use the free route.
    callers2 = _Callers()
    model_router.call_role(
        "draft", "p", policy=policy, payload_class="public", call_map=callers2.as_map()
    )
    assert callers2.openrouter_calls == ["free/model:free"]


def test_soft_budget_warns_and_continues_hard_budget_stops_the_role(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    # soft 1 = warn after the first call; hard 3 = the third call is the last one.
    policy = _policy_with("judge", [_route("gemini", "one")], soft_calls_day=1, hard_calls_day=3)
    first = _Callers()
    _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=first.as_map())
    assert meta["soft_budget_exceeded"] is False
    for _ in range(2):
        _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=first.as_map())
    assert meta["soft_budget_exceeded"] is True  # soft warns, the call still runs
    assert first.gemini_calls == ["one", "one", "one"]

    callers = _Callers()
    with pytest.raises(model_router.RoleUnavailable):
        model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert callers.gemini_calls == []


def test_per_model_daily_limit_is_respected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "limited", limit=1),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )
    first = _Callers()
    _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=first.as_map())
    assert first.gemini_calls == ["limited"] and meta["route_index"] == 0

    second = _Callers()
    _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=second.as_map())
    assert second.gemini_calls == [] and meta["route_index"] == 1


# ---------------------------------------------------------------- degradation


def test_story_role_degrades_conservatively_without_merging(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    policy = _policy_with("story", [_route("gemini", "will-fail")])

    def boom(_prompt, **_kwargs):
        raise _FakeHTTPError(429, "current quota exceeded")

    with pytest.raises(model_router.RoleUnavailable) as exc:
        model_router.call_role("story", "p", policy=policy, call_map=_Callers(gemini=boom).as_map())
    assert exc.value.on_exhausted == "conservative"

    # story_relation turns any provider failure into "no answer" -> no merge.
    assert (
        story_relation.classify({"item_id": "i1"}, {"members": []}, {}, call_model=_raiser) is None
    )


def _raiser(*_args, **_kwargs):
    raise model_router.RoleUnavailable("story", "no route", on_exhausted="conservative")


def test_judge_unavailable_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(
        generate,
        "call_model",
        lambda *a, **k: (_ for _ in ()).throw(model_router.RoleUnavailable("judge", "no route")),
    )
    packet = {"facts": [{"id": "f1", "text": "Факт."}]}
    with pytest.raises(model_router.RoleUnavailable):
        generate.verify_claims_semantic(packet, "Изречение.")
    # The optional judge helper degrades to None (never "entailed").
    assert discovery.judge_fact_with_model("Факт.", ["Факт."], api_key="k") is None


def test_draft_free_fallback_is_allowed_but_paid_is_still_gated():
    """V1.2-G4.17 — the owner's split: free yes, paid no.

    Reversed from `test_draft_never_falls_back_to_a_free_unqualified_route`,
    which asserted the opposite until the owner decided that free OpenRouter
    models may back Drafts while paid ones stay off by default. The `fail_visible`
    half of that original assertion is kept: exhausting the role must still be
    visible to the editor rather than silently producing nothing.
    """
    policy = model_policy.load_policy()
    free_or = [
        r["model"]
        for r in policy["roles"]["draft"]["routes"]
        if r["provider"] == "openrouter" and r["billing"] == "free"
    ]
    assert free_or, "the owner asked for a free OpenRouter fallback for drafts"
    assert policy["global"]["paid_enabled"] is False, "paid routes stay gated"
    assert policy["roles"]["draft"]["on_exhausted"] == "fail_visible"


def test_every_role_has_a_free_substitute():
    """A role whose only fallbacks are PAID has no fallback at all.

    This was a real gap: `angle` went straight from the Gemini routes to two
    `billing: paid` OpenRouter models. With `paid_enabled: false` a paid route
    is skipped, so once the Gemini per-model daily limits were spent the role had
    NOTHING eligible left and quietly degraded — the exact `on_exhausted:
    degraded` case the contract exists for.

    OpenRouter is the PROVIDER, not a billing class: it also serves models that
    are genuinely free, and those are proven working (the ledger shows
    nemotron-3-ultra-550b:free answering 50/56 calls today). So the fix is a
    free route in the chain, not loosening the paid gate.

    Ordering is deliberately NOT asserted. A gated paid route is a skip that
    `continue`s to the next route, so a free route placed after it is still
    reached — `draft` ships that way and works. Asserting the order would pin a
    detail the router does not depend on.
    """
    policy = model_policy.load_policy()

    for role in model_policy.ROLES:
        billings = [r.get("billing") for r in policy["roles"][role]["routes"]]
        assert "free" in billings, f"{role}: no free substitute in {billings}"


def test_the_angle_free_substitute_survives_gemini_being_spent(monkeypatch):
    """The scenario above, asserted on the router rather than on the JSON.

    Spending the Gemini daily limits must leave `angle` a FREE eligible route,
    not an empty list. Pinned because the JSON assertion alone would still pass
    if a later edit reordered the routes or the free model were removed.

    Only the GEMINI keys are cleared, and that is deliberate. The browser
    conftest leaves `GEMINI_API_KEY` in `os.environ` without cleanup, so a
    scenario test that keeps it silently depends on test order — it passed alone
    and failed after `tests/browser/` (reproduced). `OPENROUTER_API_KEY` must
    stay: a route with no key is skipped with "липсва …KEY", so clearing it
    would skip the free substitutes too and the test would assert nothing about
    the fallback at all.
    """
    for name in ("GEMINI_API_KEY", "GEMINI_DRAFT_MODELS", "GEMINI_ANGLE_MODELS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used-for-a-real-call")
    policy = model_policy.load_policy()
    monkeypatch.setattr(
        model_router.model_usage, "model_calls_today", lambda provider, model, day=None: 999
    )

    plan = model_router.plan_routes("angle", policy=policy, payload_class="public")
    eligible = [r for r in plan["routes"] if r.get("eligible")]

    assert eligible, (
        "angle must still have a route once Gemini is spent; reasons were: "
        + "; ".join(f"{r['model']}={r['reason']}" for r in plan["routes"] if r.get("reason"))
    )
    assert all(
        r.get("billing") == "free" for r in eligible
    ), f"angle fell back to something that is not free: {[r['billing'] for r in eligible]}"


def test_angle_and_story_roles_never_ride_the_judge_pool():
    policy = model_policy.load_policy()
    judge_models = {r["model"] for r in policy["roles"]["judge"]["routes"]}
    angle_models = {r["model"] for r in policy["roles"]["angle"]["routes"]}
    story_models = {r["model"] for r in policy["roles"]["story"]["routes"]}
    assert "gemini-3.8-flash" in angle_models  # quality-sensitive, strong bucket first
    assert not angle_models <= judge_models
    assert "gemini-3.8-flash" in story_models


def test_angle_proposal_and_assessment_call_the_angle_role(monkeypatch):
    seen = []

    def fake_call_model(prompt, **kwargs):
        seen.append(kwargs.get("role"))
        return json.dumps({"angles": []}), {"model": "m"}

    monkeypatch.setattr(generate, "call_model", fake_call_model)
    facts = [{"fact_id": "f1", "text": "Факт.", "risk_flags": []}]
    discovery.propose_angles(facts)
    assert seen == ["angle"]

    seen.clear()
    monkeypatch.setattr(
        discovery,
        "_angles_mod",
        type(
            "X",
            (),
            {
                "CRITERIA": discovery._angles_mod.CRITERIA,
                "VIABLE": discovery._angles_mod.VIABLE,
                "NEEDS_RESEARCH": discovery._angles_mod.NEEDS_RESEARCH,
                "NOT_VIABLE": discovery._angles_mod.NOT_VIABLE,
            },
        ),
    )
    discovery._model_assess({"title": "t", "new_proposition": "p", "reason": "r"}, facts)
    assert seen == ["angle"]


def test_fact_extraction_uses_the_extract_role(monkeypatch):
    seen = []

    def fake_call_model(prompt, **kwargs):
        seen.append(kwargs.get("role"))
        return json.dumps({"facts": []}), {"model": "m"}

    monkeypatch.setattr(generate, "call_model", fake_call_model)
    discovery._extract_facts_for_topic(
        {"label": "t", "segment_ids": ["s1"], "text": "Текст."}, doc=None
    )
    assert seen == ["extract"]


# ---------------------------------------------------------------- ledger


def test_usage_ledger_aggregates_and_never_stores_prompts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    secret = "СЕКРЕТЕН НЕПУБЛИКУВАН ТЕКСТ"
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "bad"),
            _route("openrouter", "good/model:free", billing="free"),
        ],
        default_payload_class="public",
    )
    callers = _Callers(gemini=lambda *_a, **_k: (_ for _ in ()).throw(_FakeHTTPError(503, "")))
    model_router.call_role(
        "judge", secret, policy=policy, call_map=callers.as_map(), sleep=lambda _s: None
    )
    raw = (model_usage.usage_dir() / f"{model_usage.sofia_day()}.json").read_text(encoding="utf-8")
    assert secret not in raw
    assert "prompt" not in raw.lower()
    day = json.loads(raw)
    assert set(day["calls"][0]) == {
        "at",
        "request_id",
        "role",
        "provider",
        "model",
        "route_index",
        "status",
        "category",
        "provider_attempts",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "fallbacks",
        "payload_class",
    }
    summary = model_usage.daily_summary()
    assert summary["calls"] == 2
    assert summary["successes"] == 1 and summary["failures"] == 1
    # PART B: one call_role() invocation = ONE logical request, even though it
    # wrote a FAILED row (2 provider attempts) and an OK row (1 attempt).
    assert summary["role_calls"]["judge"] == 1
    assert summary["requests"] == 1
    assert summary["model_calls"] == {
        "gemini:bad": 2,  # bounded transient retries are real provider attempts
        "openrouter:good/model:free": 1,
    }
    # And the same request counted once no matter how many rows it wrote.
    assert model_usage.role_calls_today("judge") == 1


def test_status_report_lists_every_role_and_route():
    report = model_router.status_report()
    assert [role["role"] for role in report["roles"]] == list(model_policy.ROLES)
    assert report["usage"]["calls"] == 0
    assert all("eligible" in route for role in report["roles"] for route in role["routes"])


def test_paid_cost_is_estimated_from_reported_tokens(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    policy = _policy_with("draft", [_route("openrouter", "openai/gpt-5.6-luna", billing="paid")])
    policy["global"]["paid_enabled"] = True
    policy = model_policy.normalize(policy)

    def priced(_prompt, **_kwargs):
        return "ok", {
            "provider": "openrouter",
            "model": "openai/gpt-5.6-luna",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
        }

    callers = _Callers(openrouter=priced)
    _text, meta = model_router.call_role("draft", "p", policy=policy, call_map=callers.as_map())
    assert meta["cost_usd"] == pytest.approx(0.20, abs=1e-6)
    assert model_usage.paid_cost_today() == pytest.approx(0.20, abs=1e-6)


# ---------------------------------------------------------------- operator edits + validation


def test_operator_reorder_and_toggle_persist_as_a_diff():
    policy = model_policy.load_policy()
    original_first = policy["roles"]["draft"]["routes"][0]["model"]
    model_policy.reorder_route(policy, "draft", 0, direction="down")
    model_policy.set_route_enabled(policy, "draft", 0, False)
    model_policy.set_global(policy, paid_enabled=True)
    path = model_policy.save_policy(policy)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "judge" not in payload["roles"], "untouched roles must keep following the defaults"
    back = model_policy.load_policy()
    assert back["global"]["paid_enabled"] is True
    assert back["roles"]["draft"]["routes"][0]["model"] != original_first
    assert back["roles"]["judge"]["routes"] == policy["roles"]["judge"]["routes"]
    assert len(back["roles"]["draft"]["routes"]) == len(policy["roles"]["draft"]["routes"])


def test_operator_edits_are_reported_when_they_are_impossible():
    policy = model_policy.load_policy()
    with pytest.raises(model_policy.PolicyError):
        model_policy.reorder_route(policy, "draft", 0, direction="up")
    with pytest.raises(model_policy.PolicyError):
        model_policy.remove_route(policy, "draft", 99)
    with pytest.raises(model_policy.PolicyError):
        model_policy.set_global(policy, unknown_setting=1)


def test_shipped_defaults_carry_no_stale_invalid_model_ids():
    raw = model_policy.DEFAULT_POLICY_PATH.read_text(encoding="utf-8")
    # The id that shipped before M4D does not exist in the live OpenRouter catalog.
    assert 'google/gemma-4-31b"' not in raw
    assert "google/gemma-4-31b-it:free" in raw
    defaults = model_policy.load_defaults()
    for role in defaults["roles"].values():
        for route in role["routes"]:
            if route["provider"] == "openrouter" and route.get("billing") == "free":
                assert route["model"].endswith(":free"), route["model"]
                assert route["public_only"] is True


def test_validate_flags_an_id_missing_from_the_live_catalog():
    policy = _policy_with(
        "judge",
        [
            _route("openrouter", "ghost/model:free", billing="free", public_only=True),
            _route("openrouter", "openai/gpt-5.6-luna", billing="paid"),
        ],
    )
    catalog = {
        "openai/gpt-5.6-luna": {
            "free": False,
            "prompt": 2e-7,
            "completion": 1.2e-6,
            "context": 100,
        },
    }
    report = model_catalog.validate_policy_models(
        policy, gemini_key="", openrouter_key="", catalog=catalog
    )
    statuses = {(row["model"]): row["status"] for row in report["rows"]}
    assert statuses["ghost/model:free"] == model_catalog.STATUS_INVALID
    assert statuses["openai/gpt-5.6-luna"] == model_catalog.STATUS_OK
    assert report["invalid"]
    rendered = model_catalog.render_validation(report)
    assert "НЕВАЛИДЕН" in rendered
    # No prompt/article text is ever part of a validation report.
    assert "prompt_text" not in json.dumps(report)


def test_validate_flags_a_free_label_on_a_paid_catalog_model():
    policy = _policy_with(
        "judge", [_route("openrouter", "actually/paid", billing="free", public_only=True)]
    )
    catalog = {"actually/paid": {"free": False, "prompt": 1e-6, "completion": 2e-6, "context": 10}}
    report = model_catalog.validate_policy_models(
        policy, gemini_key="", openrouter_key="", catalog=catalog
    )
    assert report["mismatches"] and report["mismatches"][0]["model"] == "actually/paid"


def test_validate_marks_gemini_rows_unchecked_without_a_key():
    policy = _policy_with("judge", [_route("gemini", "gemini-3.8-flash")])
    report = model_catalog.validate_policy_models(
        policy, gemini_key="", openrouter_key="", catalog={}
    )
    assert report["rows"][0]["status"] == model_catalog.STATUS_UNCHECKED
    assert "GEMINI_API_KEY" in report["rows"][0]["detail"] or report["gemini_error"]


def test_legacy_env_pool_override_still_works(monkeypatch):
    monkeypatch.setenv("GEMINI_JUDGE_MODELS", "gemini-3.1-flash-lite,gemini-2.5-flash-lite")
    policy = model_policy.load_policy()
    models = [r["model"] for r in policy["roles"]["judge"]["routes"] if r["provider"] == "gemini"]
    assert models == ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
    assert policy["roles"]["judge"]["routes"][-1]["provider"] == "openrouter"


def test_call_model_still_routes_through_the_policy(monkeypatch):
    """The legacy entry point keeps working: first eligible route, role respected."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen = {}

    def fake_gemini(prompt, *, api_key, timeout, role="draft", **kwargs):
        seen.update({"role": role, "model": kwargs.get("model")})
        return "ok", {"provider": "gemini"}

    monkeypatch.setattr(generate, "_call_gemini", fake_gemini)
    text, meta = generate.call_model("p", role="story")
    assert text == "ok"
    assert seen["role"] == "story"
    assert seen["model"] == model_policy.load_policy()["roles"]["story"]["routes"][0]["model"]
    assert meta["on_exhausted"] == "conservative"


def test_fetch_gemini_models_sends_the_key_as_a_header_never_in_the_url(monkeypatch):
    """M4F F6: URLs leak into logs/proxies — the key must never enter one."""
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(
                {
                    "models": [
                        {
                            "name": "models/gemini-test",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["key"] = req.get_header("X-goog-api-key")
        return _Resp()

    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fake_urlopen)
    assert model_catalog.fetch_gemini_models("k-secret") == ["gemini-test"]
    assert "?key=" not in seen["url"] and "k-secret" not in seen["url"]
    assert seen["key"] == "k-secret"


# ---------------------------------------------------------------- pre-frontend gate (PART A)


def test_openrouter_route_never_gets_an_implicit_billing_class():
    """A1: billing omitted on an OpenRouter route is a refusal, never `free`."""
    policy = model_policy.normalize(model_policy.load_defaults())
    with pytest.raises(model_policy.PolicyError, match="billing"):
        model_policy.add_route(
            policy, "draft", {"provider": "openrouter", "model": "openai/gpt-5.6-luna"}
        )
    # The same hole in a raw policy file fails closed at load time.
    broken = json.loads(json.dumps(model_policy.load_defaults()))
    broken["roles"]["draft"]["routes"].append({"provider": "openrouter", "model": "mystery/model"})
    with pytest.raises(model_policy.PolicyError):
        model_policy.normalize(broken)
    # operator_declared is not an OpenRouter billing class either.
    with pytest.raises(model_policy.PolicyError, match="free или paid"):
        model_policy.add_route(
            policy,
            "draft",
            {
                "provider": "openrouter",
                "model": "mystery/model",
                "billing": "operator_declared",
            },
        )


def test_adding_the_paid_luna_model_without_billing_is_refused():
    """A6: the exact review example — `openai/gpt-5.6-luna` without billing."""
    policy = model_policy.normalize(model_policy.load_defaults())
    with pytest.raises(model_policy.PolicyError):
        model_policy.add_route(
            policy, "draft", {"provider": "openrouter", "model": "openai/gpt-5.6-luna"}
        )


def test_free_openrouter_route_cannot_declare_public_only_false():
    """A2: policy files declaring free + public_only=false are rejected."""
    broken = json.loads(json.dumps(model_policy.load_defaults()))
    broken["roles"]["judge"]["routes"].append(
        {
            "provider": "openrouter",
            "model": "free/model:free",
            "billing": "free",
            "public_only": False,
        }
    )
    with pytest.raises(model_policy.PolicyError, match="public_only"):
        model_policy.normalize(broken)
    # The valid combination (free, public-only by default) still loads.
    policy = model_policy.normalize(model_policy.load_defaults())
    model_policy.add_route(
        policy, "draft", {"provider": "openrouter", "model": "free/model:free", "billing": "free"}
    )
    added = policy["roles"]["draft"]["routes"][-1]
    assert added["billing"] == "free" and added["public_only"] is True


def test_known_billing_is_empty_for_undeclared_models():
    """A3: an id nobody declared is NOT free."""
    policy = model_policy.load_policy()
    assert model_policy.known_billing(policy, "never/seen-model") == ""
    assert model_policy.known_billing(policy, "openai/gpt-5.6-luna") == "paid"
    assert model_policy.known_billing(policy, "qwen/qwen3.8-27b:free") == "free"


def test_unknown_explicit_model_cannot_bypass_paid_gating(monkeypatch):
    """A3/A6: unknown explicit id fails paid-safe BEFORE any transport call."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    callers = _Callers()
    policy = _policy_with("story", [_route("gemini", "unused")])

    with pytest.raises(model_router.RoleUnavailable):
        model_router.call_role(
            "story",
            "p",
            policy=policy,
            model="brand/new-model",
            payload_class="private",
            call_map=callers.as_map(),
        )
    assert callers.openrouter_calls == [] and callers.gemini_calls == []

    # The same id runs once the operator explicitly enables paid models.
    paid_on = json.loads(json.dumps(policy))
    paid_on["global"]["paid_enabled"] = True
    paid_on = model_policy.normalize(paid_on)
    text, meta = model_router.call_role(
        "story",
        "p",
        policy=paid_on,
        model="brand/new-model",
        payload_class="private",
        call_map=callers.as_map(),
    )
    assert text == "openrouter-answer" and meta["route_index"] == 0


def test_free_route_added_as_free_cannot_receive_a_private_payload(monkeypatch):
    """A2/A6: free OpenRouter stays public-only even through the add path."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    policy = _policy_with("draft", [_route("gemini", "unused")])
    policy["global"]["privacy_gate_enabled"] = True
    model_policy.add_route(
        policy, "draft", {"provider": "openrouter", "model": "free/model:free", "billing": "free"}
    )
    callers = _Callers()
    with pytest.raises(model_router.RoleUnavailable) as exc:
        model_router.call_role("draft", "p", policy=policy, call_map=callers.as_map())
    assert callers.openrouter_calls == []  # private draft payload refused
    assert "само за публични" in json.dumps(exc.value.trace, ensure_ascii=False)
    # The very same route serves a public payload.
    model_router.call_role(
        "draft", "p", policy=policy, payload_class="public", call_map=callers.as_map()
    )
    assert callers.openrouter_calls == ["free/model:free"]


def test_cached_catalog_validation_contradicting_free_refuses_the_add():
    """A5: a cached validation that saw the model as paid refuses `free`."""
    report = {
        "rows": [
            {
                "provider": "openrouter",
                "model": "sneaky/paid-model",
                "observed_free": False,
                "observed_price_usd_per_mtok": [0.2, 1.2],
            }
        ]
    }
    refusal = model_catalog.cached_billing_contradiction(report, "sneaky/paid-model", "free")
    assert refusal and "платен" in refusal and "validate" in refusal
    # Declaring it PAID is fine, and an unrelated/unknown model is not blocked.
    assert model_catalog.cached_billing_contradiction(report, "sneaky/paid-model", "paid") == ""
    assert model_catalog.cached_billing_contradiction(report, "fresh/model:free", "free") == ""
    assert model_catalog.cached_billing_contradiction(None, "sneaky/paid-model", "free") == ""


# ---------------------------------------------------------------- payload classes (PART H)


def test_payload_class_is_declared_at_every_production_call_site(monkeypatch):
    """H: known-public transcript calls are `public` at the call site; the
    unpublished-draft semantic judge is explicitly `private`. No whole role
    flips — each caller classifies its own input."""
    seen = []

    def capture(prompt, **kwargs):
        role = kwargs.get("role")
        seen.append((role, kwargs.get("payload_class")))
        if role == "extract":
            return json.dumps({"facts": []}), {"model": "m"}
        if role == "angle":
            return json.dumps({"angles": []}), {"model": "m"}
        return '{"entailed": true, "reason": "x"}', {"model": "m"}

    monkeypatch.setattr(generate, "call_model", capture)

    discovery._extract_facts_for_topic(
        {"label": "t", "segment_ids": ["s1"], "text": "Текст."}, doc=None
    )
    assert seen[-1] == ("extract", "public")  # public transcript material

    discovery.judge_fact_with_model("Факт.", ["Факт."], api_key="k")
    assert seen[-1] == ("judge", "public")  # entailment over public material

    facts = [{"fact_id": "f1", "text": "Факт.", "risk_flags": []}]
    discovery.propose_angles(facts)
    assert seen[-1] == ("angle", "public")

    discovery._model_assess({"title": "t", "new_proposition": "p", "reason": "r"}, facts)
    assert seen[-1] == ("angle", "public")

    generate.verify_claims_semantic({"facts": [{"id": "f1", "text": "Факт."}]}, "Изречение.")
    assert seen[-1] == ("judge", "private")  # unpublished draft stays private


def test_a_public_transcript_call_reaches_the_named_free_route_but_a_private_one_cannot(
    monkeypatch,
):
    """H: the point of classifying transcript calls public — they may fall
    through to the named free OpenRouter route; private payloads may not."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    policy = _policy_with("judge", [_route("openrouter", "vendor/transcript:free", billing="free")])
    policy["global"]["privacy_gate_enabled"] = True
    public_callers = _Callers()
    text, _meta = model_router.call_role(
        "judge", "p", policy=policy, payload_class="public", call_map=public_callers.as_map()
    )
    assert text == "openrouter-answer"
    assert public_callers.openrouter_calls == ["vendor/transcript:free"]

    private_callers = _Callers()
    with pytest.raises(model_router.RoleUnavailable):
        model_router.call_role(
            "judge",
            "p",
            policy=policy,
            payload_class="private",
            call_map=private_callers.as_map(),
        )
    assert private_callers.openrouter_calls == []


# ---------------------------------------------------------------- accounting (PART B)


def test_b7_disabled_route_then_success_counts_one_request_zero_one_attempts(monkeypatch):
    """Exact B7 reproduction: route0 disabled, route1 succeeds.

    Expected: 1 logical role request, 0 provider attempts on route0, 1 on
    route1 — a skip must never consume a model quota or a role budget.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "disabled-model", enabled=False),
            _route("openrouter", "backup/model:free", billing="free"),
        ],
        default_payload_class="public",
    )
    callers = _Callers()
    text, meta = model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())
    assert text == "openrouter-answer" and meta["route_index"] == 1
    assert model_usage.role_calls_today("judge") == 1
    assert model_usage.model_calls_today("gemini", "disabled-model") == 0
    assert model_usage.model_calls_today("openrouter", "backup/model:free") == 1
    summary = model_usage.daily_summary()
    assert summary["requests"] == 1 and summary["role_calls"]["judge"] == 1


def test_b7_transient_retry_is_two_attempts_but_one_request(monkeypatch):
    """route0 429-transient then success -> attempts=2, role requests=1."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    policy = _policy_with("judge", [_route("gemini", "flaky-once")])
    calls = {"n": 0}

    def flaky(_prompt, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _FakeHTTPError(429, "Too Many Requests")
        return "gemini-answer", {"model": "flaky-once", "provider": "gemini"}

    callers = _Callers(gemini=flaky)
    text, meta = model_router.call_role(
        "judge", "p", policy=policy, call_map=callers.as_map(), sleep=lambda _s: None
    )
    assert text == "gemini-answer" and meta["route_index"] == 0
    assert model_usage.model_calls_today("gemini", "flaky-once") == 2  # attempts
    assert model_usage.role_calls_today("judge") == 1  # logical requests
    summary = model_usage.daily_summary()
    assert summary["requests"] == 1
    assert summary["model_calls"] == {"gemini:flaky-once": 2}


def test_old_ledger_rows_stay_readable_without_rewriting(monkeypatch, tmp_path):
    """B6: legacy rows (no request_id/provider_attempts) keep working."""
    legacy = {
        "version": 1,
        "day": model_usage.sofia_day(),
        "updated_at": "2026-09-21T10:00:00Z",
        "calls": [
            {
                "at": "2026-09-21T09:00:00Z",
                "role": "judge",
                "provider": "gemini",
                "model": "m1",
                "status": "SKIPPED",
            },
            {
                "at": "2026-09-21T09:00:01Z",
                "role": "judge",
                "provider": "gemini",
                "model": "m1",
                "status": "OK",
            },
            {
                "at": "2026-09-21T09:00:02Z",
                "role": "judge",
                "provider": "openrouter",
                "model": "m2",
                "status": "FAILED",
            },
        ],
        "by_role": {},
        "by_model": {},
        "paid_cost_usd": 0.0,
    }
    path = model_usage.usage_dir() / f"{model_usage.sofia_day()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")
    summary = model_usage.daily_summary()
    # old OK/FAILED = 1 attempt each, old SKIPPED = 0
    assert summary["model_calls"] == {"gemini:m1": 1, "openrouter:m2": 1}
    # old OK/FAILED rows each count as one logical request, skips never do
    assert model_usage.role_calls_today("judge") == 2


# ---------------------------------------------------------------- paid soft budget (PART C)


def test_paid_soft_budget_warning_is_visible_and_never_blocks(monkeypatch):
    """PART C: `paid_soft_exceeded` warns in CLI + page, routing continues."""
    from editor_assistant.workflow import cli as cli_mod

    policy = model_policy.load_policy()
    budget = policy["global"]["soft_paid_budget_usd_day"]
    assert budget > 0
    assert model_router.status_report()["paid_soft_exceeded"] is False

    model_usage.record(
        {
            "role": "draft",
            "provider": "openrouter",
            "model": "openai/gpt-5.6-luna",
            "status": model_usage.STATUS_OK,
            "cost_usd": budget + 0.5,
        }
    )
    report = model_router.status_report()
    assert report["paid_soft_exceeded"] is True
    rendered = cli_mod.render_models_status(report)
    assert "ПРЕВИШЕН СОФТ БЮДЖЕТ" in rendered
    # Non-blocking: paid routing still works because paid_enabled is explicit.
    # The tracked default draft role has Gemini routes only, so this assertion
    # supplies the paid OpenRouter route it is about, explicitly — rather than
    # depending on a legacy env knob that can no longer add a route.
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    paid_on = _policy_with("draft", [_route("openrouter", "openai/gpt-5.6-luna", billing="paid")])
    paid_on["global"]["paid_enabled"] = True
    paid_on = model_policy.normalize(paid_on)
    text, _meta = model_router.call_role("draft", "p", policy=paid_on, call_map=_Callers().as_map())
    assert text == "openrouter-answer"


# --------------------------------------------------------------------------
# V1.2-G4.5 — the per-MINUTE dimension, which is the one that actually binds
# --------------------------------------------------------------------------

DRAFT_FLASH = ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash")


def _minute_reasons(route, *, recent_minute=0):
    """The real `_skip_reasons`, with the minute counter pinned to a number.

    Written against the production function so the test cannot drift from it,
    and stubbing only the one measurement the scenario is about.
    """
    policy = {"global": {"paid_enabled": False}, "roles": {}}
    with mock.patch.object(
        model_usage, "model_calls_last_minute", return_value=recent_minute
    ), mock.patch.object(
        model_usage, "model_calls_today", return_value=0
    ), mock.patch.object(
        model_router, "_keys_available", return_value={"gemini": "k", "openrouter": ""}
    ):
        return model_router._skip_reasons(
            route,
            "draft",
            payload_class="public",
            policy=policy,
            policy_hash="",
            role_calls=0,
            hard=None,
            now=datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc),
        )


def test_the_measured_rpm_limits_match_the_project_they_were_read_from():
    """The minute budget is a measured number, and the SHAPE is the point.

    Read from this project's own AI Studio rate-limit page on 2026-09-28, the
    same screen and the same day as `GEMINI_DAILY_LIMITS`: RPM 5 against RPD 20
    for the draft models. The ceiling that actually stops a Draft is therefore a
    minute long, while the only guard this code had was a day long.
    """
    for model in DRAFT_FLASH:
        assert model_policy.GEMINI_RPM_LIMITS[model] == 5, model
        assert model_policy.GEMINI_DAILY_LIMITS[model] == 20, model
    assert model_policy.GEMINI_RPM_LIMITS["gemini-3.5-flash-lite"] == 15
    assert model_policy.GEMINI_DAILY_LIMITS["gemini-3.5-flash-lite"] == 500


def test_a_spent_minute_skips_the_route_before_it_costs_a_round_trip():
    """Under the ceiling the route is offered; at it, it is skipped silently.

    Learning the ceiling from a 429 means paying for the call and then writing a
    failure into the route's health for something entirely predictable. The skip
    costs nothing, and it must name the MINUTE - reporting a minute as a day is
    the mistake that keeps a working model offline.
    """
    route = {
        "provider": "gemini",
        "model": "gemini-3.7-flash",
        "enabled": True,
        "billing": "operator_declared",
        "daily_call_limit": 20,
    }
    assert _minute_reasons(route, recent_minute=0) == []
    assert _minute_reasons(route, recent_minute=4) == []

    reasons = _minute_reasons(route, recent_minute=5)
    assert any("минутен лимит" in reason for reason in reasons), reasons
    assert not any("дневен лимит" in reason for reason in reasons), reasons


def test_a_model_with_no_measured_minute_is_not_guessed_one():
    """Absent from the table means unguarded, not unlimited and not invented."""
    route = {
        "provider": "gemini",
        "model": "some-unmeasured-model",
        "enabled": True,
        "billing": "operator_declared",
    }
    assert "some-unmeasured-model" not in model_policy.GEMINI_RPM_LIMITS
    assert _minute_reasons(route, recent_minute=10_000) == []


def test_a_spent_minute_never_writes_a_lasting_health_mark():
    """Five per minute must not take a working route offline for a day.

    This is the failure AGENTS.md rule 2 records, one dimension down. The skip
    category is therefore excluded from every set that produces a lasting mark.
    """
    assert model_router.RPM_LIMIT_REACHED not in model_router._UNHEALTHY_FOR_THE_PERIOD
    assert model_router.RPM_LIMIT_REACHED not in model_router._UNHEALTHY_UNTIL_POLICY_CHANGES
    # And the invariant those two sets exist to express: a provider-exhausted
    # classification is the ONLY thing that takes a route offline until the
    # provider's own reset.
    assert model_router._UNHEALTHY_FOR_THE_PERIOD == {model_router.QUOTA_EXHAUSTED}


def test_the_minute_counter_reads_a_rolling_window_not_a_calendar_minute():
    """A call 59 seconds old counts; one 61 seconds old does not."""
    now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    for offset, model in ((-59, "gemini-3.7-flash"), (-61, "gemini-3.7-flash"), (-5, "gemini-3.6-flash")):
        model_usage.record(
            {
                "provider": "gemini",
                "model": model,
                "at": (now + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    assert model_usage.model_calls_last_minute("gemini", "gemini-3.7-flash", now=now) == 1
    assert model_usage.model_calls_last_minute("gemini", "gemini-3.6-flash", now=now) == 1


def test_a_skipped_route_spends_no_quota():
    """A minute skip is a diagnostic row, and a skip is not an attempt."""
    model_usage.record(
        {
            "provider": "gemini",
            "model": "gemini-3.7-flash",
            "status": "SKIPPED",
            "provider_attempts": 0,
        }
    )
    now = datetime.now(timezone.utc)
    assert model_usage.model_calls_last_minute("gemini", "gemini-3.7-flash", now=now) == 0


def test_a_spent_minute_routes_to_the_next_model_instead_of_calling(monkeypatch):
    """End to end: the ceiling decides the ROUTE, it does not just annotate one.

    This is the behaviour the measured limits exist to produce. The first model
    is over its five-per-minute ceiling, so the router must fall through to the
    second and never spend a call that the project would refuse. The trace has to
    say which dimension stopped it, so an operator reading a later failure is
    not left guessing between a minute and a day.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    policy = _policy_with(
        "judge",
        [
            _route("gemini", "gemini-3.7-flash"),
            _route("gemini", "gemini-3.6-flash"),
        ],
    )
    spent = "gemini-3.7-flash"

    def spent_minute_only(_provider, model, now=None):
        return 5 if model == spent else 0

    with mock.patch.object(
        model_usage, "model_calls_last_minute", side_effect=spent_minute_only
    ):
        callers = _Callers()
        _text, meta = model_router.call_role("judge", "p", policy=policy, call_map=callers.as_map())

    assert callers.gemini_calls == ["gemini-3.6-flash"], "the spent route must not be called"
    skipped = [row for row in meta["trace"] if row["event"] == "SKIPPED"]
    assert skipped, meta["trace"]
    assert "минутен лимит" in skipped[0]["reason"], skipped[0]
    assert model_router._skip_category([skipped[0]["reason"]]) == model_router.RPM_LIMIT_REACHED


def test_the_prompt_log_records_what_was_sent_per_attempt(monkeypatch, tmp_path):
    """What was SENT, per attempt - including the ones that failed.

    The editor's two questions are "what exactly did you ask?" and "which model
    answered?", and the usage ledger can answer neither by design. Asserted on
    the fallback chain because that is the case worth keeping: a request that
    tried Gemini and then fell back must leave a row for EVERY attempt, so the
    reason the expected model was not used stays visible after the fact.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("MODEL_PROMPT_LOG", str(tmp_path / "prompts.jsonl"))
    secret = "НЕПУБЛИКУВАН ИЗТОЧНИК ТЕКСТ"
    policy = _policy_with(
        "draft",
        [
            _route("gemini", "gemini-3.8-flash"),
            _route("openrouter", "good/model:free", billing="free"),
        ],
        default_payload_class="public",
    )

    def gemini_503(*_a, **_k):
        raise _FakeHTTPError(503, "")

    def ok(*_a, **_k):
        return ("чернова", {"provider": "openrouter", "usage": {}})

    model_router.call_role(
        "draft",
        secret,
        policy=policy,
        call_map=_Callers(gemini=gemini_503, openrouter=ok).as_map(),
        sleep=lambda _s: None,
    )

    rows = model_prompt_log.read_sent_prompts()
    models = [r["model"] for r in rows]
    assert "gemini-3.8-flash" in models, models
    assert models[-1] == "good/model:free", "the answering model is the LAST row"
    assert all(r["prompt"] == secret for r in rows)
    assert all(r["request_id"] for r in rows), "one logical request, one id"
    assert len({r["request_id"] for r in rows}) == 1


def test_the_prompt_log_never_reaches_the_usage_ledger(monkeypatch, tmp_path):
    """The ledger's contract holds: no prompt text, not even a field name.

    `test_usage_ledger_aggregates_and_never_stores_prompts` freezes the ledger;
    this proves the NEW store did not quietly become a back door into it.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("MODEL_USAGE_DIR", str(tmp_path / "usage"))
    monkeypatch.setenv("MODEL_PROMPT_LOG", str(tmp_path / "prompts.jsonl"))
    secret = "ТАЙНА НЕПУБЛИКУВАНА МАТЕРИАЛ"
    policy = _policy_with(
        "draft", [_route("openrouter", "m:free", billing="free")], default_payload_class="public"
    )

    model_router.call_role(
        "draft",
        secret,
        policy=policy,
        call_map=_Callers(
            openrouter=lambda *_a, **_k: ("ok", {"provider": "openrouter"})
        ).as_map(),
        sleep=lambda _s: None,
    )

    ledger = (tmp_path / "usage" / f"{model_usage.sofia_day()}.json").read_text(encoding="utf-8")
    assert secret not in ledger
    assert "prompt" not in ledger.lower()
    # ...and it IS in the private store, so the feature is not a no-op.
    assert secret in (tmp_path / "prompts.jsonl").read_text(encoding="utf-8")


def test_the_prompt_log_file_is_private(monkeypatch, tmp_path):
    """Unpublished editorial text must not land world-readable.

    `open("a")` applies the umask, which is 0022 on this host - so a plain
    append would create the file 0644 and expose every draft prompt to any
    local user. Asserted on the mode, not on the intent.

    `MODEL_PROMPT_LOG` is cleared first because the autouse isolation fixture
    sets it, and it takes precedence over `root`. Left in place, `root=` would be
    silently ignored and the test would assert on a file nobody wrote - which is
    exactly how it failed before this line existed.
    """
    monkeypatch.delenv("MODEL_PROMPT_LOG", raising=False)
    model_prompt_log.record_sent_prompt(
        role="draft", provider="gemini", model="m", prompt_text="x", root=tmp_path
    )
    path = tmp_path / "editorial_workflow" / model_prompt_log.FILENAME
    assert path.exists()
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_reading_the_prompt_log_tolerates_a_missing_file_and_bad_lines(monkeypatch, tmp_path):
    """An inspection command must never crash on its own store."""
    monkeypatch.delenv("MODEL_PROMPT_LOG", raising=False)
    assert model_prompt_log.read_sent_prompts(root=tmp_path) == []

    path = tmp_path / "editorial_workflow" / model_prompt_log.FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"role": "draft", "prompt": "ok"}\nnot json at all\n\n', encoding="utf-8")
    rows = model_prompt_log.read_sent_prompts(root=tmp_path)
    assert [r["prompt"] for r in rows] == ["ok"]


def test_the_test_suite_never_writes_the_operator_prompt_store(monkeypatch, tmp_path):
    """The autouse fixture must redirect the prompt store, not just the ledger.

    Regression guard for a real accident: the fixture isolated
    `MODEL_USAGE_DIR` / `MODEL_HEALTH_PATH` / `MODEL_POLICY_PATH` but not the new
    `MODEL_PROMPT_LOG`, so one full suite run appended ~328 rows / 3 MB of test
    prompts into the operator's own store. Nothing reads that file
    automatically, so nothing failed - it would only have surfaced as the editor
    opening `newsroom models prompts` to a wall of fixture text.
    """
    from editor_assistant.drafting import model_prompt_log as module

    monkeypatch.setenv("MODEL_PROMPT_LOG", str(tmp_path / "isolated.jsonl"))
    monkeypatch.setenv("MODEL_USAGE_DIR", str(tmp_path / "usage"))

    module.record_sent_prompt(
        role="draft", provider="gemini", model="m", prompt_text="тестово"
    )

    assert (tmp_path / "isolated.jsonl").exists(), "the write went to the override"
    real = module.ROOT / "var" / "editorial_workflow" / module.FILENAME
    if real.exists():
        assert "тестово" not in real.read_text(encoding="utf-8"), (
            "test text reached the operator's own prompt store"
        )


def test_a_prompt_log_failure_never_breaks_the_model_call(monkeypatch, tmp_path):
    """Logging is best effort. A generation must not fail over its audit trail.

    The failure is injected at `_write` (the real IO helper) rather than at
    `record_sent_prompt`, because patching the public function replaces the very
    guard this test is about: it would pass for the wrong reason, and it would
    keep passing if someone later deleted the try/except entirely.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("MODEL_PROMPT_LOG", str(tmp_path / "prompts.jsonl"))

    def boom(*_args, **_kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(model_prompt_log, "_write", boom)
    policy = _policy_with(
        "draft", [_route("openrouter", "m:free", billing="free")], default_payload_class="public"
    )

    text, meta = model_router.call_role(
        "draft",
        "prompt",
        policy=policy,
        call_map=_Callers(
            openrouter=lambda *_a, **_k: ("ok", {"provider": "openrouter"})
        ).as_map(),
        sleep=lambda _s: None,
    )

    assert text == "ok", "the call must still return its answer"
    assert meta.get("model") == "m:free"
    assert model_prompt_log.read_sent_prompts(root=tmp_path) == []


def test_a_retried_attempt_logs_once_per_execution_not_once_per_retry(monkeypatch, tmp_path):
    """`attempts_allowed == 2` that fails twice leaves two rows, not one or three.

    Non-vacuity guard for the per-execution granularity: a `finally`-placed
    log plus a `continue` would double-log the retried attempt (three rows);
    a log only on terminal return would drop the retried attempt (one row).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("MODEL_PROMPT_LOG", str(tmp_path / "prompts.jsonl"))
    policy = _policy_with(
        "draft",
        [_route("openrouter", "m:free", billing="free")],
        default_payload_class="public",
        **{"global": {"max_transient_attempts": 2, "max_rate_limited_attempts": 0}},
    )

    calls = {"n": 0}

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _FakeHTTPError(500, "")
        return ("ok", {"provider": "openrouter"})

    text, _meta = model_router.call_role(
        "draft",
        "prompt",
        policy=policy,
        call_map=_Callers(openrouter=flaky).as_map(),
        sleep=lambda _s: None,
    )

    assert text == "ok"
    assert calls["n"] == 2, "the transport really executed twice"
    rows = model_prompt_log.read_sent_prompts()
    assert [r["attempt"] for r in rows] == [1, 2], rows
    assert rows[0]["outcome"].startswith("FAILED:"), rows
    assert rows[-1]["outcome"] == "SENT", rows


def test_a_trimmed_gemini_prompt_logs_what_was_sent(monkeypatch, tmp_path):
    """The row answers "what was sent", not "what was assembled".

    Regression for the pre-trim logging bug: `_trim_for_model` runs inside
    `_call_gemini`, so a 72k-char prompt arrives at the provider trimmed to
    ~30k. The row must carry the transport-reported `sent_chars`, and the
    stored text must be the trimmed text — not the 42k chars the provider
    never saw. Mutate `sent_chars` handling and this fails.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("MODEL_PROMPT_LOG", str(tmp_path / "prompts.jsonl"))
    policy = _policy_with(
        "draft",
        [_route("gemini", "gemini-3.8-flash")],
        default_payload_class="public",
    )

    full = (
        "===== TASK =====\nDo the thing.\n===== STYLE_EXAMPLES =====\n"
        + "пример ".join(["x"] * 9000)
        + "\n===== OUTPUT =====\n{json}"
    )
    assert len(full) > 30000, "the test only means something past the trim valve"
    trimmed = generate._trim_for_model(full)
    assert len(trimmed) < len(full)

    def gemini_trim(prompt_text, **_kw):
        sent = generate._trim_for_model(prompt_text)
        return ("ok", {"provider": "gemini", "prompt_chars": len(sent), "_sent": sent})

    model_router.call_role(
        "draft",
        full,
        policy=policy,
        call_map=_Callers(gemini=gemini_trim).as_map(),
        sleep=lambda _s: None,
    )

    rows = model_prompt_log.read_sent_prompts()
    assert len(rows) == 1, rows
    assert rows[0]["outcome"] == "SENT", rows
    assert rows[0]["sent_chars"] == len(trimmed), rows
    assert rows[0]["chars"] == len(full), rows


def test_a_chmod_failure_writes_no_world_readable_row(monkeypatch, tmp_path):
    """Fail CLOSED: if 0600 cannot be enforced, nothing world-readable remains.

    The guard is sabotaged at `os.fchmod` (the enforcement point), not at
    `record_sent_prompt`: patching the public function would pass for the
    wrong reason. After the fix the row is absent; before it, the row sat on
    disk at the file's prior mode.
    """
    monkeypatch.delenv("MODEL_PROMPT_LOG", raising=False)

    def deny(_fd, _mode):
        raise OSError("chmod denied")

    monkeypatch.setattr(__import__("os"), "fchmod", deny)
    row = model_prompt_log.record_sent_prompt(
        role="draft", provider="gemini", model="m", prompt_text="x", root=tmp_path
    )

    assert row is None, "best effort: the call reports the loss, it does not raise"
    path = tmp_path / "editorial_workflow" / model_prompt_log.FILENAME
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# V1.2-G4.22: an empty answer must say WHY it was empty.
#
# Measured: qwen/qwen3.8-27b:free, real 12 630-char draft prompt,
# max_tokens 16384 -> `finish_reason: "length"` with zero content chunks.
# The caller reported a bare `EMPTY_OUTPUT`, which reads the same for a model
# with nothing to say, a refusal, and an answer the ceiling cut off.
# ---------------------------------------------------------------------------


def _sse(*frames: str) -> bytes:
    return ("\n".join(f"data: {f}" for f in frames) + "\ndata: [DONE]\n").encode("utf-8")


def _call_with_body(generate, body: bytes):
    """Call `_call_openrouter` against a canned SSE body. No network, no key."""
    import io
    import urllib.request

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.close()
            return False

    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *_a, **_k: _Resp(body)
    try:
        return generate._call_openrouter("prompt", api_key="k", timeout=5, model="m:free")
    finally:
        urllib.request.urlopen = real


def test_the_openrouter_transport_reports_the_providers_own_stop_reason():
    """`finish_reason` must survive the stream parse, not be dropped on the floor."""
    from editor_assistant.drafting import generate

    body = _sse('{"choices":[{"delta":{},"finish_reason":"length"}]}')
    text, meta = _call_with_body(generate, body)

    assert text == "", "no content chunk, so no text - that is the failure being traced"
    assert meta["finish_reason"] == "length", meta
    assert meta["provider"] == "openrouter"


def test_a_normal_openrouter_answer_still_returns_its_text():
    """The added bookkeeping must not cost a working model its answer."""
    from editor_assistant.drafting import generate

    body = _sse(
        '{"choices":[{"delta":{"content":"Здравейте"},"finish_reason":null}]}',
        '{"choices":[{"delta":{"content":" от Бургас"},"finish_reason":"stop"}]}',
    )
    text, meta = _call_with_body(generate, body)

    assert text == "Здравейте от Бургас", text
    assert meta["finish_reason"] == "stop", meta


def test_the_logged_outcome_names_the_token_limit_rather_than_a_bare_empty():
    """The regression, pinned: `finish_reason: length` must be visible in the log.

    Before this the row read `FAILED:EMPTY_OUTPUT` and the operator had to guess
    between a dead model, a quota wall and an answer the ceiling cut off.
    """
    from editor_assistant.drafting import model_router

    assert (
        model_router.empty_output_outcome({"finish_reason": "length"})
        == "FAILED:EMPTY_OUTPUT:TRUNCATED_BY_TOKEN_LIMIT"
    )
    # No stop reason at all: say exactly that, never imply a cause we did not see.
    assert model_router.empty_output_outcome({}) == "FAILED:EMPTY_OUTPUT:no_stop_reason"
    assert model_router.empty_output_outcome(None) == "FAILED:EMPTY_OUTPUT:no_stop_reason"
    # A stop reason we have no sentence for is still reported, not swallowed.
    assert (
        model_router.empty_output_outcome({"finish_reason": "content_filter"})
        == "FAILED:EMPTY_OUTPUT:stop=content_filter"
    )
    # The bare code remains a PREFIX: anything matching on `FAILED:EMPTY_OUTPUT`
    # keeps working, because the cause was added, not substituted.
    for meta in ({"finish_reason": "length"}, {}, {"finish_reason": "stop"}):
        assert model_router.empty_output_outcome(meta).startswith("FAILED:EMPTY_OUTPUT")


def _page(outcome, host="a.test", **extra):
    row = {"at": "2026-10-02T05:29:00Z", "outcome": outcome, "host": host,
           "url": f"https://{host}/x", "story_id": "s-one"}
    row.update(extra)
    return row


def _round(considered, kept, facts, dropped=0, questions=()):
    return {"at": "2026-10-02T05:30:00Z", "outcome": "ROUND", "story_id": "s-one",
            "considered": considered, "kept": kept, "facts": facts,
            "dropped_by_gate": dropped, "questions": list(questions)}


def test_reasoning_is_counted_but_never_returned_as_the_answer():
    """The parser used to DROP `delta.reasoning`, so a model mid-thought looked
    identical to a model with nothing to say. Counted now; NEVER returned."""
    from editor_assistant.drafting import generate

    body = _sse(
        '{"choices":[{"delta":{"reasoning":"мисъл едно "},"finish_reason":null}]}',
        '{"choices":[{"delta":{"reasoning":"мисъл две"},"finish_reason":null}]}',
        '{"choices":[{"delta":{"content":"Бургас, "},"finish_reason":null}]}',
        '{"choices":[{"delta":{"content":"велосипеди."},"finish_reason":"stop"}]}',
        '{"usage":{"prompt_tokens":423,"completion_tokens":3956},"choices":[]}',
    )
    text, meta = _call_with_body(generate, body)

    assert text == "Бургас, велосипеди.", text
    assert "мисъл" not in text, "chain-of-thought must never reach the draft store"
    assert meta["reasoning_chars"] == len("мисъл едно ") + len("мисъл две"), meta
    assert meta["completion_tokens"] == 3956, meta
    assert meta["prompt_chars"] == 423, meta


def test_reasoning_content_is_the_other_spelling_and_also_counted():
    from editor_assistant.drafting import generate

    body = _sse('{"choices":[{"delta":{"reasoning_content":"abc"},"finish_reason":null}]}')
    _text, meta = _call_with_body(generate, body)
    assert meta["reasoning_chars"] == 3, meta


def test_a_model_that_only_thinks_is_named_not_called_silent():
    """The regression: an empty answer that spent its whole budget reasoning."""
    from editor_assistant.drafting import model_router

    spent = model_router.empty_output_outcome(
        {"finish_reason": "length", "reasoning_chars": 70036}
    )
    assert spent == "FAILED:EMPTY_OUTPUT:TRUNCATED_BY_TOKEN_LIMIT", spent
    thinking = model_router.empty_output_outcome(
        {"finish_reason": "", "reasoning_chars": 70036}
    )
    assert thinking == "FAILED:EMPTY_OUTPUT:SPENT_BUDGET_ON_REASONING", thinking
    # A genuinely silent model (no reasoning, no stop reason) is still its own case.
    assert (
        model_router.empty_output_outcome({"finish_reason": "", "reasoning_chars": 0})
        == "FAILED:EMPTY_OUTPUT:no_stop_reason"
    )


def test_openrouter_has_its_own_explicit_token_ceiling():
    """A MEASURED NEGATIVE RESULT, pinned so nobody re-raises it blind.

    Raising the ceiling to 32768 was tried against a reasoning model on a real
    2 858-char draft prompt: it spent the FULL 32 768-token budget on reasoning
    (101 417 chars) and still returned zero content, in 292 s. A bigger budget
    bought more silence and more latency, so the ceiling stays at 8192.
    """
    from editor_assistant.drafting import generate

    assert generate.OPENROUTER_MAX_TOKENS == 8192, generate.OPENROUTER_MAX_TOKENS

    sent = {}
    import io
    import urllib.request

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.close()
            return False

    def _capture(req, *_a, **_k):
        sent.update(json.loads(req.data.decode("utf-8")))
        return _Resp(b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n')

    real = urllib.request.urlopen
    urllib.request.urlopen = _capture
    try:
        generate._call_openrouter("p", api_key="k", timeout=5, model="m:free")
    finally:
        urllib.request.urlopen = real
    assert sent["max_tokens"] == generate.OPENROUTER_MAX_TOKENS, sent["max_tokens"]


def test_the_operator_output_explains_a_reasoning_budget_failure():
    from editor_assistant.workflow import cli

    text = cli.readable_outcome("FAILED:EMPTY_OUTPUT:SPENT_BUDGET_ON_REASONING")
    assert "размишление" in text, text
    # The advice must name the exact knob, so the operator can act without
    # reading the source: an unnamed "raise the limit" is what produced the
    # wrong fix in the first place.
    assert "OPENROUTER_MAX_TOKENS" in cli.next_step("FAILED:EMPTY_OUTPUT:SPENT_BUDGET_ON_REASONING")


def test_the_research_summary_reports_what_was_actually_gathered():
    """The achievement, not the activity. Measured need: a round can consider
    many pages, keep some, and still gather nothing."""
    from editor_assistant.workflow import cli

    rows = [
        _round(considered=40, kept=4, facts=0, dropped=30,
               questions=["Кой е замесен?"]),
        _page("KEPT", "a.test"), _page("KEPT", "a.test"),
        _page("KEPT", "b.test"), _page("KEPT", "c.test"),
        _page("SKIPPED_CLAIM_GATE", "d.test"), _page("OPEN_FAILED", "e.test"),
    ]
    summary = cli.summarise_research(rows, story_id="s-one")
    out = "\n".join(cli.render_research_summary(summary))

    assert summary["pagesConsidered"] == 6, summary
    assert summary["pagesKept"] == 4, summary
    assert summary["facts"] == 0, summary
    # Zero facts with six pages kept is the exact case that reads as "busy" and
    # delivered nothing, so it must be stated in words, not left to arithmetic.
    assert "НУЛА" in out, out
    assert "40" not in out.split("Разгледани")[0], "activity must not lead the report"
    assert "Кой е замесен?" in out, out


def test_kept_pages_that_brought_no_fact_are_called_out():
    """The quiet failure: `kept` reading as `useful`."""
    from editor_assistant.workflow import cli

    rows = [
        _round(considered=3, kept=2, facts=1),
        # No fact_ids and no claim_count: kept, but bought nothing.
        _page("KEPT", "a.test"), _page("KEPT", "b.test"),
        _page("KEPT", "c.test", fact_ids=["f1"], claim_count=1),
    ]
    summary = cli.summarise_research(rows)
    out = "\n".join(cli.render_research_summary(summary))

    assert summary["keptWithoutFacts"] == 2, summary
    assert "без нито един факт" in out, out


def test_one_publisher_supplying_everything_is_flagged():
    """Corroboration is the point; a single host cannot corroborate itself."""
    from editor_assistant.workflow import cli

    rows = [_round(considered=5, kept=3, facts=3),
            _page("KEPT", "only.test"), _page("KEPT", "only.test"),
            _page("KEPT", "only.test", fact_ids=["f1"], claim_count=1)]
    summary = cli.summarise_research(rows)
    out = "\n".join(cli.render_research_summary(summary))
    assert " един източник" in out, out

    # Two hosts, no warning: the guard must not cry wolf on a healthy round.
    rows2 = rows + [_page("KEPT", "second.test")]
    out2 = "\n".join(cli.render_research_summary(cli.summarise_research(rows2)))
    assert " един източник" not in out2, out2


def test_every_drop_reason_is_translated_and_unknowns_pass_through():
    """A code with no sentence must not be smoothed into a friendlier guess."""
    from editor_assistant.workflow import cli

    assert "не е новинарски издател" in cli.readable_research_outcome("SKIPPED_NON_PUBLISHER")
    assert "не се отвори" in cli.readable_research_outcome("OPEN_FAILED")
    assert "запазена" in cli.readable_research_outcome("KEPT")
    assert cli.readable_research_outcome("SOMETHING_NEW") == "SOMETHING_NEW"
    assert cli.readable_research_outcome("") == "—"


def test_the_summary_lists_pages_only_when_asked():
    from editor_assistant.workflow import cli

    rows = [_round(considered=1, kept=1, facts=1), _page("KEPT", "a.test")]
    summary = cli.summarise_research(rows)
    assert "Всяка разгледана страница" not in "\n".join(cli.render_research_summary(summary))
    assert "Всяка разгледана страница" in "\n".join(
        cli.render_research_summary(summary, pages=[r for r in rows if r["outcome"] != "ROUND"])
    )


def test_the_operator_output_names_the_cause_and_the_next_step():
    """A human must be able to read the cause without opening the JSON."""
    from editor_assistant.workflow import cli

    text = cli.readable_outcome("FAILED:EMPTY_OUTPUT:TRUNCATED_BY_TOKEN_LIMIT")
    assert "TRUNCATED" not in text, "the raw token must not leak into the sentence"
    assert "токени" in text, text
    # The advice must NOT tell the operator to raise the ceiling: measured,
    # raising max_tokens made this failure worse (238s, zero characters).
    step = cli.next_step("FAILED:EMPTY_OUTPUT:TRUNCATED_BY_TOKEN_LIMIT")
    assert "Намали" in step or "смени маршрута" in step, step

    assert "квотата" in cli.readable_outcome("FAILED:QUOTA_EXHAUSTED")
    assert "успешно" in cli.readable_outcome("SENT")

    # An unmapped code degrades to the raw value, never to a friendlier guess.
    assert cli.readable_outcome("FAILED:SOMETHING_NEW") == "провален — SOMETHING_NEW"
    assert cli.readable_outcome("") == "няма отчетен резултат (редът е от стара версия без поле outcome)"

    # Two wording bugs found by printing every code, not by reading the table:
    # `no_stop_reason` must not be dressed up as a cause the provider gave,
    # and the `stop=` prefix must appear once, not twice.
    assert "no_stop_reason" not in cli.readable_outcome("FAILED:EMPTY_OUTPUT:no_stop_reason")
    filtered = cli.readable_outcome("FAILED:EMPTY_OUTPUT:stop=content_filter")
    assert filtered.count("stop=") == 1, filtered
    assert "content_filter" in filtered, filtered


def test_the_prompts_command_shows_a_verdict_on_every_row(monkeypatch, capsys, tmp_path):
    """The regression a human hits first: a line with no verdict at all.

    Before this, `_print_sent_prompts` printed no outcome, so a failed row and a
    successful row looked identical on screen.
    """
    from editor_assistant.drafting import model_prompt_log
    from editor_assistant.workflow import cli

    monkeypatch.setenv("MODEL_PROMPT_LOG", str(tmp_path / "model_prompts.jsonl"))
    (tmp_path / "model_prompts.jsonl").write_text(
        json.dumps(
            {
                "at": "2026-10-02T05:32:07Z",
                "request_id": "r1",
                "role": "draft",
                "provider": "openrouter",
                "model": "qwen/qwen3.8-27b:free",
                "route_index": 5,
                "attempt": 1,
                "chars": 12630,
                "sent_chars": 12630,
                "payload_class": "private",
                "prompt": "текст",
                "outcome": "FAILED:EMPTY_OUTPUT:TRUNCATED_BY_TOKEN_LIMIT",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    class _Args:
        role = model = request_id = limit = None
        json = False
        no_text = True

    cli._print_sent_prompts(_Args())
    out = capsys.readouterr().out
    assert "резултат" in out, out
    assert "токени" in out, out
    assert "какво следва" in out, out
