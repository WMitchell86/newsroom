"""YouTube intake operational queue (M3B.1 Part F, hardened).

Distinct from `intake_store.registry.json` on purpose:

* the **registry** is evidence - content-addressed raw transcripts and their
  version history. Losing it means losing provenance.
* the **queue** is operational state - which URL still needs work, how many
  attempts it has had, when it is allowed to be retried. It can be deleted at
  any time without losing a single transcript.

Keeping them apart is what lets the nightly run be interrupted, resumed and
throttled without ever touching the transcript corpus.

Retry policy mirrors the sibling *ytvault* project: a failed video is retried on
an exponential ladder (15m -> 1h -> 6h -> 24h) and parked as `blocked` after
`max_attempts`. Videos that can never succeed (`no_captions`, `unavailable`,
`invalid_url`) are parked immediately - retrying a dead video is just extra
requests aimed at an IP that may already be flagged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from editor_assistant.workflow import intake_store
from editor_assistant.workflow import youtube as youtube_mod
from editor_assistant.workflow import youtube_policy as policy_mod
from editor_assistant.workflow.live_store import atomic_write

STATUS_PENDING = "pending"
STATUS_RETRY = "retry"
STATUS_DONE = "done"
STATUS_BLOCKED = "blocked"  # retry budget exhausted (revive with `reset`)
STATUS_NO_CAPTIONS = "no_captions"  # the video genuinely has no usable track
STATUS_UNAVAILABLE = "unavailable"  # removed / private / region-locked
STATUS_INVALID_URL = "invalid_url"

#: Statuses that are never picked up again without an explicit `reset`.
TERMINAL_STATUSES = (
    STATUS_DONE,
    STATUS_BLOCKED,
    STATUS_NO_CAPTIONS,
    STATUS_UNAVAILABLE,
    STATUS_INVALID_URL,
)

#: Statuses that carry retry bookkeeping.
RETRYABLE_STATUSES = (STATUS_PENDING, STATUS_RETRY)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def queue_root(root=None):
    """Same runtime root as the transcript registry (one root, not two).

    Overridable so tests never write outside their tmp dir.
    """
    return Path(intake_store.intake_root(root))


def queue_path(root=None):
    return queue_root(root) / "queue.json"


def runs_path(root=None):
    return queue_root(root) / "runs.jsonl"


def read_queue(root=None):
    path = queue_path(root)
    if not path.exists():
        return {"entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"entries": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {"entries": {}}
    return data


def save_queue(queue, root=None):
    """Atomic queue write (temp file + os.replace + fsync)."""
    path = queue_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        json.dumps(queue, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
    )


def _key_for(url, video_id=None):
    if video_id:
        return video_id
    digest = hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:12]
    return f"url:{digest}"


def add_url(queue, url, *, now=None, metadata_fn=None):
    """Queue one URL. Equivalent URL forms deduplicate by video id.

    An unparseable URL is still recorded (so the operator sees it) but parked as
    `invalid_url`; it never becomes an intake request.
    """
    now = now or _now()
    raw = (url or "").strip()
    try:
        source = youtube_mod.identify(raw, metadata=metadata_fn(raw) if metadata_fn else None)
    except youtube_mod.YouTubeSourceError as exc:
        key = _key_for(raw)
        existing = queue["entries"].get(key)
        entry = existing or {
            "key": key,
            "url": raw,
            "video_id": None,
            "status": STATUS_INVALID_URL,
            "attempts": 0,
            "added_at": now,
        }
        entry.update(
            {"status": STATUS_INVALID_URL, "last_error": str(exc)[:300], "updated_at": now}
        )
        queue["entries"][key] = entry
        return entry, existing is None

    key = _key_for(raw, source.video_id)
    entry = queue["entries"].get(key)
    if entry is None:
        entry = {
            "key": key,
            "url": raw,
            "canonical_url": source.canonical_url,
            "video_id": source.video_id,
            "status": STATUS_PENDING,
            "attempts": 0,
            "next_attempt_at": None,
            "added_at": now,
            "updated_at": now,
            "last_error": None,
        }
        queue["entries"][key] = entry
        return entry, True
    # Already known: an explicit re-add of a parked entry revives it.
    if entry.get("status") in (STATUS_BLOCKED, STATUS_UNAVAILABLE, STATUS_INVALID_URL):
        entry.update(
            {
                "status": STATUS_PENDING,
                "attempts": 0,
                "next_attempt_at": None,
                "last_error": None,
                "updated_at": now,
            }
        )
        return entry, True
    return entry, False


def due_entries(queue, cap, *, now=None):
    """Entries that may be worked on, oldest first (deterministic order)."""
    moment = parse_timestamp(now) or datetime.now(timezone.utc)
    due = []
    for entry in (queue.get("entries") or {}).values():
        status = entry.get("status")
        if status not in RETRYABLE_STATUSES:
            continue
        if status == STATUS_RETRY:
            ready = parse_timestamp(entry.get("next_attempt_at"))
            if ready is not None and ready > moment:
                continue
        due.append(entry)
    due.sort(
        key=lambda e: (e.get("next_attempt_at") or e.get("added_at") or "", e.get("key") or "")
    )
    return due[: max(int(cap or 0), 0)]


def record_success(queue, key, *, now=None, video_id=None):
    now = now or _now()
    entry = queue["entries"].get(key)
    if entry is None:
        return None
    entry.update(
        {
            "status": STATUS_DONE,
            "next_attempt_at": None,
            "last_error": None,
            "updated_at": now,
            "completed_at": now,
        }
    )
    if video_id:
        entry["video_id"] = video_id
    return entry


def record_failure(
    queue,
    key,
    *,
    category,
    reason="",
    now=None,
    max_attempts=None,
    permanent=False,
    delay_seconds=None,
):
    """Backoff bookkeeping. Returns the resulting status.

    `delay_seconds` overrides the backoff ladder - used for a circuit breaker,
    where the video should become due when the *IP* cooldown expires rather than
    on the 15-minute rung.
    """
    now = now or _now()
    max_attempts = policy_mod.DEFAULTS["max_attempts"] if max_attempts is None else max_attempts
    entry = queue["entries"].get(key)
    if entry is None:
        return None
    attempts = int(entry.get("attempts") or 0) + 1
    entry["attempts"] = attempts
    entry["failure_category"] = category
    entry["last_error"] = (reason or "")[:300]
    entry["updated_at"] = now

    if permanent:
        # Every permanent category must be named here: an unmapped one would
        # silently park as `blocked`, which mistranslates "invalid URL" into a
        # retryable-looking state. The default stays `blocked` on purpose - it
        # is the safe parking state for an unknown permanent failure.
        entry["status"] = {
            "TRANSCRIPT_EMPTY": STATUS_NO_CAPTIONS,
            "UNSUPPORTED_LANGUAGE": STATUS_NO_CAPTIONS,
            "TRANSCRIPT_UNAVAILABLE": STATUS_UNAVAILABLE,
            "INVALID_YOUTUBE_URL": STATUS_INVALID_URL,
        }.get(category, STATUS_BLOCKED)
        entry["next_attempt_at"] = None
        return entry["status"]

    if attempts >= max_attempts:
        entry["status"] = STATUS_BLOCKED
        entry["next_attempt_at"] = None
        return STATUS_BLOCKED

    delay = policy_mod.backoff_seconds(attempts) if delay_seconds is None else int(delay_seconds)
    moment = parse_timestamp(now) or datetime.now(timezone.utc)
    entry["status"] = STATUS_RETRY
    entry["next_attempt_at"] = (moment + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return STATUS_RETRY


def reset(queue, *, include_no_captions=False, now=None):
    """Revive parked entries: blocked/retry (and optionally no_captions) -> pending."""
    now = now or _now()
    revive = [STATUS_BLOCKED, STATUS_RETRY] + ([STATUS_NO_CAPTIONS] if include_no_captions else [])
    revived = []
    for entry in (queue.get("entries") or {}).values():
        if entry.get("status") in revive:
            entry.update(
                {
                    "status": STATUS_PENDING,
                    "attempts": 0,
                    "next_attempt_at": None,
                    "last_error": None,
                    "updated_at": now,
                }
            )
            revived.append(entry.get("key"))
    return revived


def summarize(queue):
    counts = {status: 0 for status in TERMINAL_STATUSES}
    counts[STATUS_PENDING] = 0
    counts[STATUS_RETRY] = 0
    for entry in (queue.get("entries") or {}).values():
        status = entry.get("status")
        if status in counts:
            counts[status] += 1
    counts["total"] = sum(count for status, count in counts.items() if status != "total")
    return counts


def append_run(record, root=None):
    """Append one run summary (append-only operational log)."""
    path = runs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def recent_runs(root=None, limit=5):
    path = runs_path(root)
    if not path.exists():
        return []
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
