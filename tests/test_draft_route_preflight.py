"""V1.2-G4.8 — «Направи чернова» must fail in seconds, not minutes.

Measured 2026-09-29 10:17→10:21: the editor pressed the button, walked away,
came back, and found it still active with nothing ready. The operation took
3 min 49 s to fail, because all four Draft routes are Gemini on one key
sharing one daily quota: they die together, and the router discovers it one
60-second timeout at a time.

The four routes are NOT four independent fallbacks. That is the fact these
tests exist to keep visible.
"""

import pytest

from editor_assistant.drafting import model_router
from editor_assistant.workflow import editor_application as app


def test_tri_state_distinguishes_no_routes_from_all_routes_dead(monkeypatch):
    """'We have no routes to judge' is not 'all your routes are dead'.

    The first version answered False for both and refused every Draft in any
    environment without a full route table — 13 tests broke on it.
    """
    monkeypatch.setattr(model_router, "read_health", dict)
    policy = {"roles": {"draft": {"routes": []}}}
    assert model_router.role_has_usable_route("draft", policy=policy) is None

    policy = {"roles": {"draft": {"routes": [
        {"provider": "gemini", "model": "m1", "eligible": True}]}}}
    # A route with no health record has never failed, so it is worth calling.
    assert model_router.role_has_usable_route("draft", policy=policy) is True


def test_all_routes_exhausted_is_an_explicit_false(monkeypatch):
    monkeypatch.setattr(model_router, "read_health", lambda: {
        "gemini:m1": {"status": "EXHAUSTED", "until": "2099-01-01T00:00:00Z"},
        "gemini:m2": {"status": "EXHAUSTED", "until": "2099-01-01T00:00:00Z"},
    })
    policy = {"roles": {"draft": {"routes": [
        {"provider": "gemini", "model": "m1", "eligible": True},
        {"provider": "gemini", "model": "m2", "eligible": True}]}}}
    assert model_router.role_has_usable_route("draft", policy=policy) is False


def test_an_expired_window_makes_the_route_worth_calling_again(monkeypatch):
    """A 429's reset moment passing is what a daily quota looks like tomorrow."""
    monkeypatch.setattr(model_router, "read_health", lambda: {
        "gemini:m1": {"status": "EXHAUSTED", "until": "2000-01-01T00:00:00Z"},
    })
    policy = {"roles": {"draft": {"routes": [
        {"provider": "gemini", "model": "m1", "eligible": True}]}}}
    assert model_router.role_has_usable_route("draft", policy=policy) is True


def test_draft_preflight_refuses_immediately_when_nothing_is_callable(monkeypatch):
    """The refusal must be raised, and it must name the real cause."""
    monkeypatch.setattr(model_router, "role_has_usable_route", lambda *a, **k: False)
    monkeypatch.setattr(model_router, "exhausted_routes_for", lambda *a, **k: [
        {"route": "gemini:gemini-3.7-flash", "status": "EXHAUSTED", "until": "x"},
    ])
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
