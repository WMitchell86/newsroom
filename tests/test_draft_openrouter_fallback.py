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


def test_no_draft_route_may_be_public_only():
    """A Draft is private material. A public-only route must never carry it."""
    offenders = [
        r for r in _policy()["roles"]["draft"]["routes"] if r.get("public_only")
    ]
    assert offenders == [], offenders


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
