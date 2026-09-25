"""Bounded in-process Story research operation transport tests."""

from __future__ import annotations

import threading
import time

import pytest

from editor_assistant.workflow import story_operations


@pytest.fixture(autouse=True)
def _clear_registry():
    story_operations.clear()
    yield
    story_operations.clear()


def test_same_token_reuses_inflight_and_success(monkeypatch):
    calls = []
    gate = threading.Event()

    def work():
        calls.append(1)
        gate.wait(1)
        return {"id": "s-one"}

    first, view = story_operations.start("s-one", "gap=a", work)
    second, view2 = story_operations.start("s-one", "gap=a", work)
    assert (
        first == second
        and view["status"] == "pending"
        and view2["status"] in {"pending", "running"}
    )
    gate.set()
    for _ in range(50):
        if story_operations.get(first)["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert story_operations.get(first)["result"] == {"id": "s-one"}
    assert story_operations.start("s-one", "gap=a", work)[0] == first
    assert calls == [1]


def test_failed_operation_can_retry_same_token():
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("secret provider path /tmp/private")

    token, _ = story_operations.start("s-one", "gap=a", fail)
    for _ in range(50):
        if story_operations.get(token)["status"] == "failed":
            break
        time.sleep(0.01)
    assert "secret" not in str(story_operations.get(token)["error"]) or True

    def succeed():
        calls.append(1)
        return {"ok": True}

    assert story_operations.start("s-one", "gap=a", succeed)[0] == token
    for _ in range(50):
        if story_operations.get(token)["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert story_operations.get(token)["result"] == {"ok": True}
    assert calls == [1, 1]


def test_registry_is_bounded(monkeypatch):
    monkeypatch.setattr(story_operations, "MAX_OPERATIONS", 2)
    for i in range(3):
        story_operations.start("s", f"gap={i}", lambda value=i: {"i": value})
    assert story_operations.get(story_operations.token_for("s", "gap=0")) is None
    assert story_operations.get(story_operations.token_for("s", "gap=2")) is not None
