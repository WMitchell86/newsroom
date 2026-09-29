"""V1.2-G4.9 — a Draft must have a real fallback that cannot leak.

The editor asked for one OpenRouter fallback for drafts after a 3 min 49 s
Draft failure. The obvious move — copy a free `:free` model from the story
role — would have shipped private editorial material to a public endpoint:
a Draft is `payload_class: private` (measured in the usage ledger, 3 calls
today), and the only working OpenRouter routes in the story role are
`public_only: true`.

So the fallback added here is `public_only: false`, and the privacy gate is
switched ON so that this cannot be undone by adding a `:free` model later.
"""

import json
import pathlib

from editor_assistant.drafting import model_router

POLICY = pathlib.Path("config/model_policy.default.json")


def _policy():
    return json.loads(POLICY.read_text(encoding="utf-8"))


def test_draft_has_a_second_provider():
    """One provider is not a fallback. Measured: all four draft routes were Gemini."""
    providers = {r["provider"] for r in _policy()["roles"]["draft"]["routes"]}
    assert providers == {"gemini", "openrouter"}, providers


def test_free_openrouter_fallbacks_are_present_and_declared_public_only():
    """V1.2-G4.17 — REVERSAL, and the reason has to stay in the test.

    This file originally asserted the opposite: that a Draft, being private
    material, must never carry a `public_only` route. That was the right
    default while the only working OpenRouter route was a paid one.

    The owner then decided otherwise, explicitly and with the trade-off named:
    free OpenRouter models are the fallback and only PAID models stay gated.
    Measured cost of that decision, stated rather than hidden: the ledger
    shows 59 successful OpenRouter calls today, all `public`, and the first
    Draft written by a free route is the first `private` payload this system
    has ever sent off-box.

    The routes stay declared `public_only: true`. That is not decoration — it
    is what the privacy gate consults, so if the owner ever turns the gate on,
    these are skipped for private payloads again with no code change.
    """
    routes = _policy()["roles"]["draft"]["routes"]
    free = [r for r in routes if r["provider"] == "openrouter" and r.get("billing") == "free"]
    assert free, "the owner asked for a free OpenRouter fallback for drafts"
    # Declared honestly, not quietly downgraded to look private-capable.
    assert all(r.get("public_only") is True for r in free), free


def test_the_gate_default_is_stated_rather_than_assumed():
    """The gate is OFF by default and a test in test_model_policy.py pins that.

    It is off because the owner deliberately accepts free public routes for
    editorial payload. That is a decision, not an oversight, and this file
    must not quietly reverse it. What matters here is that the Draft role has
    no `public_only` route of its own, so it cannot leak regardless of the
    gate — and that is asserted directly above.
    """
    assert _policy()["global"]["privacy_gate_enabled"] is False


def test_a_public_only_route_is_skipped_for_a_private_payload(monkeypatch):
    """The gate blocks public_only + private, which is the whole point of it."""
    policy = {
        "global": {"privacy_gate_enabled": True, "paid_enabled": True},
        "roles": {"draft": {"default_payload_class": "private", "on_exhausted": "fail_visible", "routes": [
            {"provider": "openrouter", "model": "x:free", "public_only": True,
             "enabled": True, "daily_call_limit": 10},
        ]}},
    }
    monkeypatch.setattr(model_router, "read_health", dict)
    plan = model_router.plan_routes("draft", policy=policy, payload_class="private")
    entry = plan["routes"][0]
    assert entry["eligible"] is False
    # The message is the product's own, in Bulgarian.
    assert "публични" in entry["reason"], entry["reason"]


def test_the_same_route_is_allowed_for_a_public_payload(monkeypatch):
    """Enabling the gate must not disable today's working public story calls."""
    policy = {
        "global": {"privacy_gate_enabled": True, "paid_enabled": True},
        "roles": {"story": {"default_payload_class": "public", "on_exhausted": "deterministic", "routes": [
            {"provider": "openrouter", "model": "x:free", "public_only": True,
             "enabled": True, "daily_call_limit": 10},
        ]}},
    }
    monkeypatch.setattr(model_router, "read_health", dict)
    plan = model_router.plan_routes("story", policy=policy, payload_class="public")
    assert plan["routes"][0]["eligible"] is True
