"""M3B.1 offline tests: the cron-facing intake run (lock, breaker, pacing).

Nothing here sleeps, opens a socket, runs a model or shells out to yt-dlp.
"""

import json
import os
import random

import pytest

from editor_assistant.workflow import intake_queue as Q
from editor_assistant.workflow import intake_run as R
from editor_assistant.workflow import youtube_policy as P

VID = "dQw4w9WgXcQ"
OTHER = "abcdefghijk"
THIRD = "zyxwvutsrqp"


def _policy(**overrides):
    base = {
        "player_clients": ("only",),
        "fallback_enabled": True,
        "delay_min_s": 7,
        "delay_max_s": 7,
        "nightly_cap": 5,
        "max_attempts": 3,
        "block_cooldown_h": 12,
    }
    base.update(overrides)
    return P.IntakePolicy(**base)


def _result(outcome="NO_PUBLISHABLE_ANGLE", category=None, status="OK", fallback_used=False):
    transcription = {"status": status}
    if category:
        transcription["category"] = category
    if fallback_used:
        transcription["fallback_used"] = True
    if outcome == "TRANSCRIPTION_FAILED":
        transcription.setdefault("reason", "yt-dlp said no")
    return {
        "outcome": outcome,
        "stages": {"transcription": transcription},
        "video": {"video_id": VID},
        "analysis": {"readiness": {"status": "NOT_RUN"}},
    }


def _seed(root, *urls):
    """Queue URLs in the given order (distinct timestamps keep the order stable)."""
    queue = Q.read_queue(root=root)
    for index, url in enumerate(urls):
        Q.add_url(queue, url, now=f"2026-01-01T00:00:{index:02d}Z")
    Q.save_queue(queue, root=root)
    return queue


def _intake(responses):
    """`responses` is one result for every URL, or {url: result} per URL."""
    calls = []
    per_url = isinstance(responses, dict) and "outcome" not in responses

    def fn(url, *, policy, direct_only, jev_shadow_enabled, jev_evaluate_fn):
        calls.append({"url": url, "direct_only": direct_only, "jev": jev_shadow_enabled})
        response = responses[url] if per_url else responses
        if isinstance(response, Exception):
            raise response
        return response

    return fn, calls


def _sleeper():
    slept = []
    return slept, slept.append


# ---------- lock ----------


def test_a_held_lock_prevents_overlapping_runs(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    assert R.acquire_lock(stale_after_s=3600, root=tmp_path) is True
    intake, calls = _intake(_result())
    result = R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert result["exit_code"] == R.EXIT_LOCKED
    assert result["stats"]["processed"] == 0
    assert calls == []
    R.release_lock(root=tmp_path)


def test_a_stale_lock_is_taken_over(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    lock = R.lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("stale", encoding="utf-8")
    long_ago = os.path.getmtime(lock) - 10 * 3600
    os.utime(lock, (long_ago, long_ago))

    intake, calls = _intake(_result())
    result = R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert result["exit_code"] == R.EXIT_OK
    assert len(calls) == 1


def test_the_lock_is_always_released(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(_result("TRANSCRIPTION_FAILED", category="TRANSCRIBER_BLOCKED"))
    R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert not R.lock_path(tmp_path).exists()


# ---------- cooldown / circuit breaker ----------


def test_an_active_cooldown_blocks_the_run_before_any_request(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    R.write_cooldown("429", hours=1, root=tmp_path, now="2099-01-01T00:00:00Z")
    intake, calls = _intake(_result())
    result = R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert result["exit_code"] == R.EXIT_BLOCKED
    assert calls == []


def test_an_expired_cooldown_lets_the_run_proceed(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    R.write_cooldown("429", hours=1, root=tmp_path, now="2020-01-01T00:00:00Z")
    assert R.active_cooldown(root=tmp_path) is None
    intake, calls = _intake(_result())
    result = R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert result["exit_code"] == R.EXIT_OK
    assert len(calls) == 1


def test_the_breaker_stops_the_run_and_writes_a_cooldown(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}", f"https://youtu.be/{OTHER}")
    blocked = _result("TRANSCRIPTION_FAILED", category="TRANSCRIBER_BLOCKED")
    intake, calls = _intake(blocked)
    slept, sleep = _sleeper()
    result = R.run_once(
        policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=sleep, rng=random.Random(1)
    )
    assert result["exit_code"] == R.EXIT_BLOCKED
    assert result["breaker"] is True
    assert len(calls) == 1  # nothing else was attempted
    assert slept == []  # and no pacing pause was taken either
    cooldown = R.read_cooldown(root=tmp_path)
    assert cooldown and cooldown["reason"] and cooldown["blocked_until"] > cooldown["written_at"]


def test_a_fallback_failure_does_not_trip_the_breaker(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}", f"https://youtu.be/{OTHER}")
    responses = {
        f"https://youtu.be/{VID}": _result(
            "TRANSCRIPTION_FAILED", category="TRANSCRIBER_FALLBACK_FAILED"
        ),
        f"https://youtu.be/{OTHER}": _result("DRAFT_READY"),
    }
    intake, calls = _intake(responses)
    result = R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert result["exit_code"] == R.EXIT_OK
    assert result["breaker"] is False
    assert len(calls) == 2
    assert R.read_cooldown(root=tmp_path) is None
    assert result["stats"]["retry"] == 1 and result["stats"]["done"] == 1


def test_a_rescue_latches_the_rest_of_the_run_off_youtube(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}", f"https://youtu.be/{OTHER}")
    responses = {
        f"https://youtu.be/{VID}": _result("DRAFT_READY", fallback_used=True),
        f"https://youtu.be/{OTHER}": _result("DRAFT_READY"),
    }
    intake, calls = _intake(responses)
    R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert [call["direct_only"] for call in calls] == [False, True]


# ---------- pacing ----------


def test_cron_mode_sleeps_a_random_startup_jitter(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(_result())
    slept, sleep = _sleeper()
    result = R.run_once(
        policy=_policy(startup_jitter_min_s=600, startup_jitter_max_s=600),
        root=tmp_path,
        cron=True,
        intake_fn=intake,
        sleeper=sleep,
    )
    assert slept == [600]
    assert result["jitter_slept_s"] == 600


def test_no_jitter_without_cron(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(_result())
    slept, sleep = _sleeper()
    R.run_once(
        policy=_policy(startup_jitter_min_s=600, startup_jitter_max_s=600),
        root=tmp_path,
        intake_fn=intake,
        sleeper=sleep,
    )
    assert slept == []


def test_a_pause_is_taken_between_entries_but_never_after_the_last(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}", f"https://youtu.be/{OTHER}")
    intake, _ = _intake(_result())
    slept, sleep = _sleeper()
    R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=sleep)
    assert slept == [7]


def test_the_nightly_cap_bounds_the_run(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}", f"https://youtu.be/{OTHER}")
    intake, calls = _intake(_result())
    result = R.run_once(
        policy=_policy(), root=tmp_path, cap=1, intake_fn=intake, sleeper=lambda s: None
    )
    assert len(calls) == 1
    assert result["stats"]["processed"] == 1


# ---------- bookkeeping ----------


def test_a_clean_queue_reports_nothing_due(tmp_path):
    result = R.run_once(policy=_policy(), root=tmp_path, sleeper=lambda s: None)
    assert result["exit_code"] == R.EXIT_OK
    assert "nothing due" in result["note"]
    assert not Q.queue_path(tmp_path).exists()


def test_outcomes_are_written_back_to_the_queue(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}", f"https://youtu.be/{OTHER}")
    responses = {
        f"https://youtu.be/{VID}": _result("DRAFT_READY"),
        f"https://youtu.be/{OTHER}": _result("TRANSCRIPTION_FAILED", category="TRANSCRIPT_EMPTY"),
    }
    intake, _ = _intake(responses)
    R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    entries = Q.read_queue(root=tmp_path)["entries"]
    assert entries[VID]["status"] == Q.STATUS_DONE
    assert entries[OTHER]["status"] == Q.STATUS_NO_CAPTIONS


def test_repeat_retries_exhaust_the_budget_and_park(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(_result("TRANSCRIPTION_FAILED", category="TRANSCRIPTION_FAILED"))
    for _ in range(3):
        R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
        # clear any backoff so the next attempt is due immediately
        queue = Q.read_queue(root=tmp_path)
        queue["entries"][VID]["next_attempt_at"] = None
        Q.save_queue(queue, root=tmp_path)
    assert Q.read_queue(root=tmp_path)["entries"][VID]["status"] == Q.STATUS_BLOCKED


def test_cache_reuse_is_reported_separately(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(_result("NO_PUBLISHABLE_ANGLE", status="REUSED"))
    result = R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert result["stats"]["reused"] == 1
    assert result["entries"][0]["transcription_status"] == "REUSED"


def test_an_interrupted_run_leaves_no_success_behind(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(RuntimeError("killed by operator"))
    with pytest.raises(RuntimeError):
        R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert not R.lock_path(tmp_path).exists()
    assert Q.read_queue(root=tmp_path)["entries"][VID]["status"] == Q.STATUS_PENDING


def test_jev_shadow_is_off_unless_explicitly_requested(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, calls = _intake(_result())
    R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    assert calls[0]["jev"] is False


def test_the_breaker_defers_the_entry_to_the_cooldown_window(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(_result("TRANSCRIPTION_FAILED", category="TRANSCRIBER_BLOCKED"))
    R.run_once(
        policy=_policy(block_cooldown_h=12),
        root=tmp_path,
        intake_fn=intake,
        sleeper=lambda s: None,
        now="2026-01-01T00:00:00Z",
    )
    entry = Q.read_queue(root=tmp_path)["entries"][VID]
    assert entry["next_attempt_at"] == "2026-01-01T12:00:00Z"


def test_a_systemic_failure_aborts_the_run_instead_of_burning_the_cap(tmp_path):
    """Many failures in a row with zero successes = the setup is broken."""
    _seed(
        tmp_path,
        "https://youtu.be/" + VID,
        "https://youtu.be/" + OTHER,
        "https://youtu.be/" + THIRD,
    )
    failing = _result("TRANSCRIPTION_FAILED", category="TRANSCRIPTION_FAILED")
    intake, calls = _intake(failing)
    slept, sleep = _sleeper()
    result = R.run_once(
        policy=_policy(nightly_cap=10, delay_min_s=1, delay_max_s=1),
        root=tmp_path,
        intake_fn=intake,
        sleeper=sleep,
    )
    assert len(calls) == 3  # only three entries existed, and all three were tried
    assert result["exit_code"] == R.EXIT_OK

    # Now with more entries queued than the fuse tolerates:
    for index in range(6):
        _seed(tmp_path, f"https://youtu.be/{index:011d}")
    intake, calls = _intake(failing)
    slept, sleep = _sleeper()
    result = R.run_once(
        policy=_policy(nightly_cap=20, max_attempts=99),
        root=tmp_path,
        intake_fn=intake,
        sleeper=sleep,
    )
    assert result["exit_code"] == R.EXIT_FAILED
    assert "consecutive failures" in result["note"]
    assert len(calls) == R.CONSECUTIVE_FAILURE_FUSE
    assert len(slept) == R.CONSECUTIVE_FAILURE_FUSE - 1  # no pause after aborting


def test_finish_run_appends_a_summary(tmp_path):
    _seed(tmp_path, f"https://youtu.be/{VID}")
    intake, _ = _intake(_result())
    result = R.run_once(policy=_policy(), root=tmp_path, intake_fn=intake, sleeper=lambda s: None)
    record = R.finish_run(result, root=tmp_path, now="2026-01-02T00:00:00Z")
    written = json.loads(Q.runs_path(tmp_path).read_text(encoding="utf-8").strip())
    assert written["note"] == record["note"]
    assert written["exit_code"] == R.EXIT_OK
