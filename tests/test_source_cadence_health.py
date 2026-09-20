"""M4A.1 operational-state tests: source health + real cadence (offline).

Cadence must be operational, not a UI label, and health must distinguish "nothing
new" from "the collector is broken". Both are computed on the Europe/Sofia day.
"""

from __future__ import annotations

from datetime import date

import pytest

from editor_assistant.workflow import newsroom_run, source_health


@pytest.fixture(autouse=True)
def newsroom_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWSROOM_DIR", str(tmp_path / "newsroom"))
    return tmp_path / "newsroom"


def _entry(cadence):
    return {"source_id": "s", "cadence": cadence, "effective_status": "active"}


def test_sofia_date_crosses_midnight_even_in_winter():
    # 22:30 UTC in summer is 01:30 the next day in Sofia (UTC+3).
    assert source_health.sofia_date("2026-09-20T22:30:00Z") == date(2026, 9, 21)
    # 22:30 UTC in winter is 00:30 the next day in Sofia (UTC+2).
    assert source_health.sofia_date("2026-01-15T22:30:00Z") == date(2026, 1, 16)
    # 20:00 UTC in summer is still 23:00 the same day.
    assert source_health.sofia_date("2026-09-20T20:00:00Z") == date(2026, 9, 20)


def test_each_run_is_always_due_and_unknown_state_is_due():
    assert newsroom_run.due_for(_entry("each_run"), None, date(2026, 9, 20))[0] is True
    assert newsroom_run.due_for(_entry("daily"), None, date(2026, 9, 20))[0] is True


def test_daily_is_due_once_per_local_day():
    record = {"last_success_at": "2026-09-20T20:00:00Z"}  # Sofia 23:00 on the 20th
    assert newsroom_run.due_for(_entry("daily"), record, date(2026, 9, 20))[0] is False
    assert newsroom_run.due_for(_entry("daily"), record, date(2026, 9, 21))[0] is True


def test_daily_failed_attempt_does_not_mark_the_day_done():
    # only a SUCCESS sets last_success_at; a failure record must stay due
    record = {"last_attempt_at": "2026-09-20T08:00:00Z", "last_success_at": ""}
    assert newsroom_run.due_for(_entry("daily"), record, date(2026, 9, 20))[0] is True


def test_weekly_needs_seven_local_days():
    record = {"last_success_at": "2026-09-14T06:00:00Z"}
    assert newsroom_run.due_for(_entry("weekly"), record, date(2026, 9, 18))[0] is False
    assert newsroom_run.due_for(_entry("weekly"), record, date(2026, 9, 21))[0] is True


def test_force_overrides_cadence():
    record = {"last_success_at": "2026-09-20T20:00:00Z"}
    assert newsroom_run.due_for(_entry("daily"), record, date(2026, 9, 20), force=True)[0] is True


def test_health_records_ok_empty_and_failed_distinctly():
    assert source_health.describe("s")["last_status"] == source_health.NEVER_RUN

    source_health.record_source("s", status="OK", item_count=3, new_count=2, success=True)
    ok = source_health.describe("s")
    assert ok["last_status"] == "OK"
    assert ok["last_item_count"] == 3 and ok["last_new_count"] == 2
    assert ok["last_success_at"]

    source_health.record_source("s", status="FAILED", error="OSError: down", success=False)
    failed = source_health.describe("s")
    assert failed["last_status"] == "FAILED"
    assert failed["last_success_at"] == ok["last_success_at"]  # the success is preserved
    assert "down" in failed["last_error"]


def test_health_rejects_an_unknown_status():
    with pytest.raises(source_health.HealthError):
        source_health.record_source("s", status="BROKEN", success=True)


def test_last_run_is_recorded_and_readable():
    assert source_health.read_last_run() is None
    record = source_health.record_run(
        {
            "finished_at": "2026-09-20T07:00:00Z",
            "collected": 5,
            "new": 3,
            "duplicate": 2,
            "failed": 1,
            "sources": [{"source_id": "s", "status": "FAILED", "reason": "boom"}],
        }
    )
    assert record["new"] == 3
    stored = source_health.read_last_run()
    assert stored["new"] == 3 and stored["failed"] == 1
    assert stored["problems"][0]["source_id"] == "s"
