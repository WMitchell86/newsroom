"""Cron-friendly YouTube intake run loop (M3B.1).

This is the entry point a scheduler (cron / Task Scheduler) invokes. It is a
**one-shot process, not a daemon**: it wakes, works a bounded number of queue
entries, and exits. Nothing inside the repository schedules anything - the
operator installs the crontab line documented in `RUNBOOK.md`.

The anti-ban guardrails, borrowed from the sibling *ytvault* project:

* **one video at a time, never parallel**;
* a random pause between videos (`delay_min_s`..`delay_max_s`);
* **nightly cap** - a backfill is paced over weeks on purpose;
* **startup jitter** in `--cron` mode, so the job has no fixed signature;
* **lock file** - overlapping runs would double the request rate;
* **circuit breaker** - the first explicit block stops the whole run and writes
  a cooldown, because pushing through a soft block is how it becomes a ban;
* **exponential backoff** per video, then parked (revive with `reset`).

`intake_fn`, `sleeper` and `rng` are seams: the unit suite never sleeps, never
runs a model and never opens a socket.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timedelta, timezone

from editor_assistant.workflow import intake_queue as queue_mod
from editor_assistant.workflow import transcriber as transcriber_mod
from editor_assistant.workflow import youtube_policy as policy_mod
from editor_assistant.workflow.live_store import atomic_write

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2  # circuit breaker tripped, or a cooldown is still active
EXIT_LOCKED = 3  # another run holds the lock

LOCK_NAME = "run.lock"
COOLDOWN_NAME = "cooldown.json"

#: Failure categories that describe the video itself, so retrying is pointless.
PERMANENT_CATEGORIES = (
    transcriber_mod.TRANSCRIPT_EMPTY,
    transcriber_mod.UNSUPPORTED_LANGUAGE,
    transcriber_mod.TRANSCRIPT_UNAVAILABLE,
)

#: System-wide failure fuse: this many failures in a row without a single
#: success means the setup is broken (bad config, dead dependency, blocked at
#: TLS level), so the run aborts instead of burning the whole cap on it.
CONSECUTIVE_FAILURE_FUSE = 5


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_path(root=None):
    return queue_mod.queue_root(root) / LOCK_NAME


def cooldown_path(root=None):
    return queue_mod.queue_root(root) / COOLDOWN_NAME


# ---------------------------------------------------------------- lock


def acquire_lock(*, stale_after_s, root=None, pid=None, clock=None):
    """Take the run lock. A lock older than `stale_after_s` is treated as stale.

    The lock file is created with `O_CREAT | O_EXCL`, so two cron runs starting
    in the same second cannot both win. (A plain `exists()`-then-write check
    races: both processes see "no lock" and both proceed, doubling the request
    rate - the exact thing the lock exists to prevent.)
    """
    path = lock_path(root)
    now = time.time() if clock is None else clock
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": pid or os.getpid(), "started_at": _now()}) + "\n"

    for takeover_attempt in (False, True):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                age = now - path.stat().st_mtime
            except OSError:
                age = 0
            if takeover_attempt or age < stale_after_s:
                return False
            path.unlink(missing_ok=True)  # stale lock: take it over, retry once
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return True
    return False  # pragma: no cover - the loop always returns above


def release_lock(root=None):
    lock_path(root).unlink(missing_ok=True)


# ---------------------------------------------------------------- cooldown


def write_cooldown(reason, *, hours, root=None, now=None):
    moment = queue_mod.parse_timestamp(now) or datetime.now(timezone.utc)
    until = (moment + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "blocked_until": until,
        "reason": (reason or "")[:300],
        "hours": hours,
        "written_at": now or _now(),
    }
    atomic_write(cooldown_path(root), json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    return record


def read_cooldown(root=None):
    path = cooldown_path(root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def active_cooldown(root=None, now=None):
    """The cooldown record if it is still in force, else None."""
    record = read_cooldown(root)
    if not record:
        return None
    until = queue_mod.parse_timestamp(record.get("blocked_until"))
    moment = queue_mod.parse_timestamp(now) or datetime.now(timezone.utc)
    if until is None or until <= moment:
        return None
    return record


# ---------------------------------------------------------------- run


def default_intake(url, *, policy, direct_only, jev_shadow_enabled, jev_evaluate_fn):
    """The production intake call. Kept here so `intake_youtube` stays clean."""
    from editor_assistant.workflow import intake as intake_mod

    return intake_mod.intake_youtube(
        url,
        jev_shadow_enabled=jev_shadow_enabled,
        jev_evaluate_fn=jev_evaluate_fn,
        transcriber_kwargs={"policy": policy, "direct_only": direct_only},
    )


def _classify(result):
    """Intake result -> (kind, category, reason).

    `kind` is one of `done`, `retry`, `permanent`, `breaker`, `invalid`.
    """
    stages = result.get("stages") or {}
    transcription = stages.get("transcription") or {}
    category = transcription.get("category")
    reason = transcription.get("reason") or ""
    outcome = result.get("outcome")

    if outcome == "INVALID_YOUTUBE_URL":
        return "invalid", category, reason
    if outcome == "DISCOVERY_FAILED":
        return "retry", "DISCOVERY_FAILED", (stages.get("discovery") or {}).get("reason") or ""
    if outcome != "TRANSCRIPTION_FAILED":
        return "done", category, reason
    if category == transcriber_mod.TRANSCRIBER_BLOCKED:
        return "breaker", category, reason
    if category in PERMANENT_CATEGORIES:
        return "permanent", category, reason
    # TRANSCRIBER_FALLBACK_FAILED, TRANSCRIPTION_FAILED, TRANSCRIPT_INVALID and
    # anything unknown: worth one more try later, cheap because the transcript
    # (when it exists) is already cached.
    return "retry", category, reason


def run_once(
    *,
    policy=None,
    root=None,
    cap=None,
    cron=False,
    now=None,
    intake_fn=None,
    sleeper=None,
    rng=None,
    jev_shadow_enabled=False,
    jev_evaluate_fn=None,
):
    """Work the due queue entries once. Returns a structured run summary."""
    policy = policy or policy_mod.load_policy()
    sleeper = sleeper if sleeper is not None else time.sleep
    rng = rng if rng is not None else random.Random()
    intake_fn = intake_fn or default_intake
    started_at = now or _now()

    stats = {
        "processed": 0,
        "reused": 0,
        "done": 0,
        "retry": 0,
        "permanent": 0,
        "blocked": 0,
    }
    entries_report = []
    breaker = False
    note = ""
    exit_code = EXIT_OK
    jitter_slept = 0

    if not acquire_lock(stale_after_s=policy.lock_stale_s, root=root):
        return {
            "exit_code": EXIT_LOCKED,
            "note": "another run holds the lock",
            "breaker": False,
            "stats": stats,
            "entries": entries_report,
            "started_at": started_at,
            "jitter_slept_s": 0,
        }

    try:
        cooldown = active_cooldown(root=root, now=now)
        if cooldown:
            return {
                "exit_code": EXIT_BLOCKED,
                "note": f"cooldown active until {cooldown.get('blocked_until')}",
                "cooldown": cooldown,
                "breaker": False,
                "stats": stats,
                "entries": entries_report,
                "started_at": started_at,
                "jitter_slept_s": 0,
            }

        if cron and policy.startup_jitter_max_s > 0:
            jitter_slept = rng.randint(policy.startup_jitter_min_s, policy.startup_jitter_max_s)
            sleeper(jitter_slept)

        queue = queue_mod.read_queue(root)
        cap = policy.nightly_cap if cap is None else max(int(cap), 0)
        due = queue_mod.due_entries(queue, cap, now=now)

        if not due:
            return {
                "exit_code": EXIT_OK,
                "note": "nothing due - the queue is clear",
                "breaker": False,
                "stats": stats,
                "entries": entries_report,
                "started_at": started_at,
                "jitter_slept_s": jitter_slept,
            }

        # Run-level latch: after the first fallback rescue, stop touching
        # YouTube for the rest of the run so a flagged IP is not re-poked.
        direct_only = False
        consecutive_failures = 0

        for index, entry in enumerate(due, start=1):
            key = entry["key"]
            result = intake_fn(
                entry["url"],
                policy=policy,
                direct_only=direct_only,
                jev_shadow_enabled=jev_shadow_enabled,
                jev_evaluate_fn=jev_evaluate_fn,
            )
            stats["processed"] += 1
            stages = result.get("stages") or {}
            transcription = stages.get("transcription") or {}
            if transcription.get("status") == "REUSED":
                stats["reused"] += 1
            if transcription.get("fallback_used"):
                direct_only = True

            kind, category, reason = _classify(result)

            if kind == "done":
                queue_mod.record_success(
                    queue, key, now=now, video_id=(result.get("video") or {}).get("video_id")
                )
                stats["done"] += 1
            elif kind == "invalid":
                queue_mod.record_failure(
                    queue,
                    key,
                    category="INVALID_YOUTUBE_URL",
                    reason=reason,
                    now=now,
                    permanent=True,
                )
                stats["permanent"] += 1
            elif kind == "permanent":
                queue_mod.record_failure(
                    queue, key, category=category, reason=reason, now=now, permanent=True
                )
                stats["permanent"] += 1
            elif kind == "breaker":
                queue_mod.record_failure(
                    queue,
                    key,
                    category=category,
                    reason=reason,
                    now=now,
                    max_attempts=policy.max_attempts,
                    # A block is about the IP, not the video: the entry becomes
                    # due when the cooldown expires, not on the 15-minute rung.
                    delay_seconds=policy.block_cooldown_h * 3600,
                )
                stats["blocked"] += 1
                breaker = True
                cooldown = write_cooldown(
                    reason or category, hours=policy.block_cooldown_h, root=root, now=now
                )
                note = f"circuit breaker: {reason or category}"[:200]
                exit_code = EXIT_BLOCKED
                queue_mod.save_queue(queue, root)
                entries_report.append(_entry_report(entry, kind, category, reason, result))
                break
            else:
                status = queue_mod.record_failure(
                    queue,
                    key,
                    category=category,
                    reason=reason,
                    now=now,
                    max_attempts=policy.max_attempts,
                )
                if status == queue_mod.STATUS_BLOCKED:
                    stats["blocked"] += 1
                else:
                    stats["retry"] += 1

            consecutive_failures = 0 if kind == "done" else consecutive_failures + 1
            queue_mod.save_queue(queue, root)
            entries_report.append(_entry_report(entry, kind, category, reason, result))

            # Fuse: many failures in a row without a single success means the
            # setup is broken system-wide. Aborting beats spending the whole
            # cap proving it.
            if consecutive_failures >= CONSECUTIVE_FAILURE_FUSE and stats["done"] == 0:
                exit_code = EXIT_FAILED
                note = (
                    f"aborted: {consecutive_failures} consecutive failures, 0 done "
                    f"(last: {category})"
                )[:200]
                break

            if index < len(due):
                delay = rng.randint(policy.delay_min_s, policy.delay_max_s)
                sleeper(delay)

        if not note:
            note = (
                f"{stats['processed']} processed, {stats['reused']} reused from cache, "
                f"{stats['retry']} retry, {stats['permanent']} parked"
            )
        return {
            "exit_code": exit_code,
            "note": note,
            "breaker": breaker,
            "stats": stats,
            "entries": entries_report,
            "started_at": started_at,
            "jitter_slept_s": jitter_slept,
        }
    finally:
        release_lock(root)


def _entry_report(entry, kind, category, reason, result):
    stages = result.get("stages") or {}
    return {
        "key": entry.get("key"),
        "video_id": (result.get("video") or {}).get("video_id") or entry.get("video_id"),
        "url": entry.get("url"),
        "kind": kind,
        "outcome": result.get("outcome"),
        "failure_category": category,
        "reason": (reason or "")[:200],
        "transcription_status": (stages.get("transcription") or {}).get("status"),
        "fallback_used": bool((stages.get("transcription") or {}).get("fallback_used")),
        "readiness": ((result.get("analysis") or {}).get("readiness") or {}).get("status"),
    }


def finish_run(result, *, root=None, now=None):
    """Persist one run summary to `runs.jsonl` (append-only operational log)."""
    record = {
        "finished_at": now or _now(),
        "started_at": result.get("started_at"),
        "exit_code": result.get("exit_code"),
        "note": result.get("note"),
        "breaker": bool(result.get("breaker")),
        "stats": result.get("stats"),
        "jitter_slept_s": result.get("jitter_slept_s"),
    }
    queue_mod.append_run(record, root=root)
    return record
