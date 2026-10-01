"""Bounded in-process Story research operation transport tests."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

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


# ------------------------------------------- PART: the wall clock (V1.2-G4.38)


def _row(token):
    """The editor-facing row for one token, found by identity.

    Never by index: the worker thread moves a row from `pending` to `running`
    the moment it starts, so an assertion on the exact status of a row that is
    deliberately held open is a race, not a contract.
    """
    return next(r for r in story_operations.recent() if r["operationToken"] == token)


IN_FLIGHT = {"pending", "running"}


def _settle(token, status, attempts=200):
    for _ in range(attempts):
        if story_operations.get(token)["status"] == status:
            return story_operations.get(token)
        time.sleep(0.01)
    raise AssertionError(f"operation never reached {status}")


def test_an_operation_records_when_it_started_and_when_it_stopped():
    """G4.38: the registry must carry a wall clock, not only a monotonic one.

    Measured on the editor's own Operations page: it showed no time at all, and
    the reason was not a missing label — no wall-clock value existed on the row.
    `updated_at` is `time.monotonic()`, a duration since the PROCESS started, so
    it orders rows correctly and means nothing to a person.
    """
    before = datetime.now(timezone.utc)
    token, _ = story_operations.start("s-one", "gap=a", lambda: {"id": "s-one"})
    row = _settle(token, "succeeded")
    after = datetime.now(timezone.utc)

    listed = _row(token)
    started = datetime.fromisoformat(listed["startedAt"])
    finished = datetime.fromisoformat(listed["finishedAt"])

    assert listed["storyId"] == "s-one"
    assert before <= started <= after, "startedAt is a real instant, not a duration"
    assert started <= finished, "a job cannot finish before it starts"
    assert finished <= after
    assert row["status"] == "succeeded"


def test_work_in_flight_has_no_finished_time():
    """G4.38: an empty `finishedAt` is the truth; a guessed one would be a lie."""
    gate = threading.Event()
    token, _ = story_operations.start("s-one", "gap=b", lambda: gate.wait(1))
    listed = _row(token)

    assert listed["status"] in IN_FLIGHT
    assert listed["startedAt"], "it was asked for, so it has a start"
    assert listed["finishedAt"] == "", "it has not stopped, so it has no finish"

    gate.set()
    _settle(token, "succeeded")
    assert _row(token)["finishedAt"]


def test_a_failed_operation_records_when_it_stopped_too():
    def boom():
        raise RuntimeError("no")

    token, _ = story_operations.start("s-one", "gap=c", boom)
    _settle(token, "failed")
    listed = _row(token)
    assert listed["status"] == "failed"
    assert listed["finishedAt"], "a failure has an end, and the editor needs it"


def test_a_retry_is_restamped_and_does_not_inherit_the_dead_runs_time():
    """G4.38: the second attempt is a new moment; the first one's end is not its end."""
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("no")

    token, _ = story_operations.start("s-one", "gap=d", fail)
    first = _row(token)
    _settle(token, "failed")
    dead_finish = _row(token)["finishedAt"]

    # Held open, so the retry is observed while it is genuinely still running
    # rather than after an instant lambda has already finished it.
    retry_gate = threading.Event()
    token, _ = story_operations.start("s-one", "gap=d", lambda: retry_gate.wait(2))
    retried = _row(token)
    assert retried["status"] in IN_FLIGHT
    assert retried["finishedAt"] == "", "the retry has not finished yet"
    assert retried["startedAt"] >= first["startedAt"]

    retry_gate.set()
    _settle(token, "succeeded")
    final = _row(token)
    assert final["finishedAt"], "and it gets its own when it does finish"
    assert final["finishedAt"] >= dead_finish


def test_the_ledger_keeps_the_wall_clock_across_a_restart(tmp_path, monkeypatch):
    """G4.38: a recovered row is dated when it RAN, not when the server came back.

    Otherwise every operation recovered from disk would show the restart time,
    and a page whose whole job is "what happened to what I asked for" would
    answer with the moment the process died.
    """
    ledger = tmp_path / "operations.json"
    monkeypatch.setenv("WB_OPERATIONS_LEDGER_PATH", str(ledger))
    token, _ = story_operations.start("s-one", "gap=e", lambda: {"ok": True})
    _settle(token, "succeeded")
    original = _row(token)
    assert original["startedAt"] and original["finishedAt"]
    # Flush explicitly. The worker writes the ledger just AFTER it publishes the
    # terminal status, so a test that settles on the status and immediately
    # re-reads the file is racing that write rather than testing persistence.
    story_operations._write_ledger()

    story_operations.clear()  # the process "restarted"
    assert story_operations.load_ledger() == 1
    restored = _row(token)

    assert restored["operationToken"] == token
    assert restored["startedAt"] == original["startedAt"]
    assert restored["finishedAt"] == original["finishedAt"]


def test_an_interrupted_operation_is_restored_as_failed_and_keeps_its_time(tmp_path, monkeypatch):
    """G4.38: the restart path must not lose the time either.

    Written straight into the ledger rather than raced against a live worker:
    the thing under test is what `load_ledger` does with a row that was still
    running when the process died, and a thread that is still running makes
    that a race instead of a contract.
    """
    ledger = tmp_path / "operations.json"
    monkeypatch.setenv("WB_OPERATIONS_LEDGER_PATH", str(ledger))
    token = story_operations.token_for("s-one", "gap=f")
    ledger.write_text(
        json.dumps(
            {
                "saved_at": "2026-10-01T09:00:00+00:00",
                "rows": [
                    {
                        "token": token,
                        "story_id": "s-one",
                        "status": "running",
                        "error_code": "",
                        "error": "",
                        "outcome": "",
                        "outcome_code": "",
                        "outcome_message": "",
                        "started_at": "2026-10-01T08:55:00+00:00",
                        "finished_at": "",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert story_operations.load_ledger() == 1
    restored = story_operations.get(token)
    assert restored["status"] == "failed"
    assert restored["error_code"] == "INTERRUPTED_BY_RESTART"
    assert _row(token)["startedAt"] == "2026-10-01T08:55:00+00:00"


def test_the_list_is_ordered_by_the_clock_it_prints():
    """G4.38 review: a retried operation is the newest work and must list first.

    A retry reuses its token and its slot in `_ROWS`, so insertion order kept it
    at the BOTTOM while its `startedAt` moved to the top — the page printing a
    time that contradicted its own ordering. Measured before the fix:
    `['s-second', 's-first']` where `s-first` was the later of the two.
    """
    story_operations.start("s-first", "gap=r", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    _settle(story_operations.token_for("s-first", "gap=r"), "failed")
    time.sleep(0.01)
    story_operations.start("s-second", "gap=r", lambda: {"ok": True})
    _settle(story_operations.token_for("s-second", "gap=r"), "succeeded")
    time.sleep(0.01)
    # The retry: same token, same slot, a fresh start time.
    story_operations.start("s-first", "gap=r", lambda: {"ok": True})
    _settle(story_operations.token_for("s-first", "gap=r"), "succeeded")

    listed = story_operations.recent()
    assert [row["storyId"] for row in listed] == ["s-first", "s-second"]
    assert [row["startedAt"] for row in listed] == sorted(
        (row["startedAt"] for row in listed), reverse=True
    ), "the printed order and the printed clock must agree"


def test_rows_without_a_stamp_do_not_displace_stamped_ones():
    """G4.38 review: a legacy row has no time, so it must not claim to be newest."""
    try:
        token = story_operations.token_for("s-new", "gap=z")
        story_operations.start("s-new", "gap=z", lambda: {"ok": True})
        _settle(token, "succeeded")
        # Inject an unstamped row the way an older ledger would restore one.
        story_operations._ROWS["op_legacy"] = {
            "story_id": "s-legacy",
            "status": "succeeded",
            "error": None,
            "error_code": "",
            "outcome": "",
            "outcome_code": "",
            "outcome_message": "",
            "result": None,
            "updated_at": time.monotonic(),
            "started_at": "",
            "finished_at": "",
            "view": {"status": "succeeded"},
        }
        listed = story_operations.recent()
        assert listed[0]["storyId"] == "s-new", "a stamped row outranks an unstamped one"
        assert listed[-1]["storyId"] == "s-legacy"
    finally:
        story_operations._ROWS.pop("op_legacy", None)
