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

import pytest

from editor_assistant.drafting import (
    generate,
    model_catalog,
    model_policy,
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
        raise _FakeHTTPError(400, "invalid model id")

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


def test_draft_never_falls_back_to_a_free_unqualified_route():
    policy = model_policy.load_policy()
    free_or = [
        r["model"]
        for r in policy["roles"]["draft"]["routes"]
        if r["provider"] == "openrouter" and r["billing"] != "paid"
    ]
    assert free_or == [], "draft must not reach an unqualified free OpenRouter route"
    assert policy["roles"]["draft"]["on_exhausted"] == "fail_visible"


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
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    paid_on = model_policy.load_policy()
    paid_on["global"]["paid_enabled"] = True
    paid_on = model_policy.normalize(paid_on)
    text, _meta = model_router.call_role("draft", "p", policy=paid_on, call_map=_Callers().as_map())
    assert text == "openrouter-answer"
