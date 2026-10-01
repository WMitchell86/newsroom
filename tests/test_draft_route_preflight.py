"""V1.2-G4.8 — «Направи чернова» must fail in seconds, not minutes.

Measured 2026-09-29 10:17→10:21: the editor pressed the button, walked away,
came back, and found it still active with nothing ready. The operation took
3 min 49 s to fail, because all four Draft routes are Gemini on one key
sharing one daily quota: they die together, and the router discovers it one
60-second timeout at a time.

The four routes are NOT four independent fallbacks. That is the fact these
tests exist to keep visible.

**V1.2-G4.38 — why the fixtures below were rewritten.** These tests used to
describe routes as `{"provider": ..., "model": ..., "eligible": True}`, and
`role_has_usable_route` read `eligible` straight off the raw policy route. No
route the product ships carries that key (the real keys are `billing`,
`daily_call_limit`, `enabled`, `model`, `provider`, `public_only`), so against a
real policy every route was skipped and the function answered "cannot judge" for
every role, always — while the tests stayed green because they pinned a shape
that does not exist. The guard was therefore dead in production and alive only
in here. `_route()` now builds the shipped shape, and
`test_the_shipped_policy_is_judgeable` loads the real policy so this cannot come
back as a fiction again.
"""

import pytest

from editor_assistant.drafting import model_policy, model_router
from editor_assistant.workflow import editor_application as app


def _route(provider="gemini", model="m1", **extra):
    """One route in the shape `config/model_policy.default.json` actually uses.

    Deliberately no `eligible` key: eligibility is computed by `plan_routes`,
    never declared by the file.
    """
    route = {"provider": provider, "model": model, "enabled": True, "billing": "free"}
    route.update(extra)
    return route


def _policy(routes, *, on_exhausted="fail_visible", payload_class="public"):
    """A complete, normalised role policy — the keys `call_role` requires."""
    return {
        "global": {"paid_enabled": True, "privacy_gate_enabled": True},
        "roles": {
            "draft": {
                "default_payload_class": payload_class,
                "on_exhausted": on_exhausted,
                "soft_calls_day": 0,
                "hard_calls_day": 0,
                "routes": routes,
            }
        },
    }


@pytest.fixture(autouse=True)
def _both_providers_configured(monkeypatch):
    """A configured desk.

    `_skip_reasons` marks a route ineligible when its provider key is missing,
    which is correct in production and would make every test here measure the
    test machine's `.env` instead of the routing logic.
    """
    monkeypatch.setattr(
        model_router,
        "_keys_available",
        lambda *a, **k: {"gemini": True, "openrouter": True},
    )


def test_tri_state_distinguishes_no_routes_from_all_routes_dead():
    """'We have no routes to judge' is not 'all your routes are dead'.

    The first version answered False for both and refused every Draft in any
    environment without a full route table — 13 tests broke on it.
    """
    policy = _policy([])
    assert model_router.role_has_usable_route("draft", policy=policy) is None

    # A route with no health record has never failed, so it is worth calling.
    policy = _policy([_route()])
    assert model_router.role_has_usable_route("draft", policy=policy) is True


def test_all_routes_exhausted_is_an_explicit_false(monkeypatch):
    monkeypatch.setattr(
        model_router,
        "read_health",
        lambda: {
            "gemini:m1": {"status": "EXHAUSTED", "until": "2099-01-01T00:00:00Z"},
            "gemini:m2": {"status": "EXHAUSTED", "until": "2099-01-01T00:00:00Z"},
        },
    )
    policy = _policy([_route(model="m1"), _route(model="m2")])
    assert model_router.role_has_usable_route("draft", policy=policy) is False


def test_an_expired_window_makes_the_route_worth_calling_again(monkeypatch):
    """A 429's reset moment passing is what a daily quota looks like tomorrow."""
    monkeypatch.setattr(
        model_router,
        "read_health",
        lambda: {"gemini:m1": {"status": "EXHAUSTED", "until": "2000-01-01T00:00:00Z"}},
    )
    policy = _policy([_route(model="m1")])
    assert model_router.role_has_usable_route("draft", policy=policy) is True


def test_a_disabled_paid_gate_does_not_hide_a_free_route(monkeypatch):
    """The old broad rule skipped EVERY non-Gemini route when paid was off.

    That is the opposite of the point: with paid models disabled, a free
    OpenRouter route is precisely what should be called. `call_role` never had
    that rule — it applies the narrow `billing == "paid"` gate — so the guard
    must not have it either.
    """
    policy = _policy([_route(provider="openrouter", model="qwen/qwen3.8-27b:free")])
    policy["global"]["paid_enabled"] = False
    assert model_router.role_has_usable_route("draft", policy=policy) is True


def test_the_shipped_policy_is_judgeable():
    """The regression this whole file was blind to.

    Read the policy the product actually ships and require a JUDGEABLE answer.
    `None` means "cannot judge", which both callers treat as permission to
    proceed — so a `None` here is the guardrail being absent, not a quiet
    success. Measured 2026-10-01 on the operator's desk: three Draft routes were
    EXHAUSTED, `plan_routes` could say so, and `role_has_usable_route` still
    answered `None` for every role.

    The assertion is `is not None` and not a literal `True`/`False`, because
    which of the two is correct depends on the machine's quota at that moment —
    and both are honest answers. Answering nothing is not.
    """
    for role in sorted(model_policy.load_policy().get("roles") or {}):
        assert model_router.role_has_usable_route(role) is not None, (
            f"{role} came back unjudgeable against the shipped policy"
        )


def test_draft_preflight_refuses_immediately_when_nothing_is_callable(monkeypatch):
    """The refusal must be raised, and it must name the real cause."""
    monkeypatch.setattr(model_router, "role_has_usable_route", lambda *a, **k: False)
    monkeypatch.setattr(
        model_router,
        "exhausted_routes_for",
        lambda *a, **k: [
            {"route": "gemini:gemini-3.7-flash", "status": "EXHAUSTED", "until": "x"},
        ],
    )
    with pytest.raises(app.EditorApplicationError) as excinfo:
        app._draft_route_preflight()
    text = str(excinfo.value)
    assert "DRAFT_ROUTE_UNAVAILABLE" in text or "Няма достъпен модел" in text
    assert "gemini-3.7-flash" in text, text


def test_draft_preflight_does_not_refuse_when_it_cannot_judge(monkeypatch):
    """`None` is not an outage. Refusing here would invent one."""
    monkeypatch.setattr(model_router, "role_has_usable_route", lambda *a, **k: None)
    app._draft_route_preflight()  # must not raise


def test_draft_preflight_passes_through_when_a_route_is_usable(monkeypatch):
    monkeypatch.setattr(model_router, "role_has_usable_route", lambda *a, **k: True)
    app._draft_route_preflight()  # must not raise
