"""Operational source health + last-run record (M4A.1).

Cadence and health need a small operational state store that is **separate from
the source configuration**: when a source last ran is a fact about a run, not a
setting the editor owns, and mixing the two would make the config file churn on
every collection.

Stored under `var/newsroom/` (env-overridable, git-ignored):

* `source_health.json` — one record per `source_id`:
  `{last_attempt_at, last_success_at, last_status, last_item_count, last_new_count, last_error}`
  with `last_status` in `OK` / `EMPTY` / `FAILED` (`NEVER_RUN` = no record);
* `last_run.json` — the summary of the most recent collection run.

The timezone helpers live here because cadence is defined on the *local* day:
"once a day" means one successful collection per `Europe/Sofia` date, not per UTC
date. `zoneinfo` is stdlib and used when the platform has tzdata; the EU DST rule
is applied manually otherwise, so the result never depends on the machine's clock
configuration.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from editor_assistant.workflow import live_store

ROOT = Path(__file__).resolve().parents[3]

OK = "OK"
EMPTY = "EMPTY"
FAILED = "FAILED"
NEVER_RUN = "NEVER_RUN"
HEALTH_STATUSES = (OK, EMPTY, FAILED, NEVER_RUN)

FIELDS = (
    "last_attempt_at",
    "last_success_at",
    "last_status",
    "last_item_count",
    "last_new_count",
    "last_error",
)


class HealthError(ValueError):
    """A health record that must not be stored."""


def _newsroom_root():
    return Path(os.environ.get("NEWSROOM_DIR") or (ROOT / "var" / "newsroom"))


def health_path(path=None):
    if path is not None:
        return Path(path)
    override = os.environ.get("NEWSROOM_SOURCE_HEALTH_PATH")
    if override:
        return Path(override)
    return _newsroom_root() / "source_health.json"


def last_run_path(path=None):
    if path is not None:
        return Path(path)
    override = os.environ.get("NEWSROOM_LAST_RUN_PATH")
    if override:
        return Path(override)
    return _newsroom_root() / "last_run.json"


def _now(now=None):
    if now is not None:
        return now if isinstance(now, datetime) else parse_timestamp(now)
    return datetime.now(timezone.utc)


def parse_timestamp(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- Europe/Sofia local time (DST-aware, stdlib only) ----------

_LAST_SUNDAY_MARCH_CACHE = {}


def _last_sunday(year, month):
    key = (year, month)
    if key not in _LAST_SUNDAY_MARCH_CACHE:
        day = 31
        while True:
            candidate = date(year, month, day)
            if candidate.weekday() == 6:  # Sunday
                _LAST_SUNDAY_MARCH_CACHE[key] = candidate
                break
            day -= 1
    return _LAST_SUNDAY_MARCH_CACHE[key]


def _manual_sofia_offset(moment_utc):
    """EU DST rule: +03:00 between the last Sundays of March and October."""
    year = moment_utc.year
    start = datetime.combine(_last_sunday(year, 3), datetime.min.time(), tzinfo=timezone.utc)
    start = start + timedelta(hours=1)  # 01:00 UTC switch
    end = datetime.combine(_last_sunday(year, 10), datetime.min.time(), tzinfo=timezone.utc)
    end = end + timedelta(hours=1)
    return timedelta(hours=3) if start <= moment_utc < end else timedelta(hours=2)


def sofia_now(now=None):
    """Timezone-aware Europe/Sofia datetime (tzdata when available, else EU rule)."""
    moment = _now(now).astimezone(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo("Europe/Sofia"))
    except Exception:  # noqa: BLE001 - missing tzdata must not break collection
        return moment + _manual_sofia_offset(moment)


def sofia_date(now=None):
    return sofia_now(now).date()


def sofia_date_of(value):
    """Local date of a stored UTC timestamp; None when unreadable."""
    moment = parse_timestamp(value)
    return sofia_date(moment) if moment else None


# ---------- store ----------


def read_health(path=None):
    store = health_path(path)
    if not store.exists():
        return {}
    try:
        rows = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HealthError(f"състоянието на източниците е нечетимо: {exc}") from exc
    if not isinstance(rows, dict):
        raise HealthError("състоянието на източниците трябва да е JSON обект")
    out = {}
    for source_id, record in rows.items():
        if not isinstance(record, dict):
            raise HealthError(f"{source_id}: записът за състоянието не е обект")
        status = record.get("last_status")
        if status not in HEALTH_STATUSES:
            raise HealthError(f"{source_id}: непознат статус {status!r}")
        unknown = sorted(set(record) - set(FIELDS))
        if unknown:
            raise HealthError(f"{source_id}: непознати полета {unknown}")
        out[str(source_id)] = {
            "last_attempt_at": str(record.get("last_attempt_at") or ""),
            "last_success_at": str(record.get("last_success_at") or ""),
            "last_status": status,
            "last_item_count": int(record.get("last_item_count") or 0),
            "last_new_count": int(record.get("last_new_count") or 0),
            "last_error": str(record.get("last_error") or "")[:300],
        }
    return out


def _save_health(rows, path=None):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    live_store.atomic_write(health_path(path), payload)
    return rows


def record_source(
    source_id,
    *,
    status,
    item_count=0,
    new_count=0,
    error="",
    success=False,
    now=None,
    path=None,
):
    """Upsert one source's health record. `success` sets `last_success_at`.

    `OK` means the collector returned at least one usable item; `EMPTY` means the
    collector worked but produced nothing (a real, visible distinction — an empty
    source must not read as a broken one).
    """
    if status not in (OK, EMPTY, FAILED):
        raise HealthError(f"status must be one of {(OK, EMPTY, FAILED)}, got {status!r}")
    moment = _iso(_now(now))
    rows = read_health(path)
    record = rows.get(source_id) or {
        "last_attempt_at": "",
        "last_success_at": "",
        "last_status": NEVER_RUN,
        "last_item_count": 0,
        "last_new_count": 0,
        "last_error": "",
    }
    record["last_attempt_at"] = moment
    if success:
        record["last_success_at"] = moment
    record["last_status"] = status
    record["last_item_count"] = int(item_count or 0)
    record["last_new_count"] = int(new_count or 0)
    record["last_error"] = str(error or "")[:300]
    rows[source_id] = record
    return _save_health(rows, path)


def describe(source_id, path=None):
    """Health as the editor sees it (NEVER_RUN when there is no record)."""
    record = read_health(path).get(source_id)
    if not record:
        return {"last_status": NEVER_RUN, "last_attempt_at": "", "last_success_at": ""}
    return record


def record_run(summary, *, path=None):
    """Persist the last collection summary (what «Последно събиране» shows)."""
    record = {
        "finished_at": summary.get("finished_at") or "",
        "started_at": summary.get("started_at") or "",
        "collected": int(summary.get("collected") or 0),
        "new": int(summary.get("new") or 0),
        "duplicate": int(summary.get("duplicate") or 0),
        "failed": int(summary.get("failed") or 0),
        "blocked": int(summary.get("blocked") or 0),
        "blocked_filtered": int(summary.get("blocked_filtered") or 0),
        "source_count": len(summary.get("sources") or []),
        "problems": [
            {
                "source_id": row.get("source_id"),
                "status": row.get("status"),
                "reason": row.get("reason"),
            }
            for row in (summary.get("sources") or [])
            if row.get("status") == FAILED
        ],
    }
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    live_store.atomic_write(last_run_path(path), payload)
    return record


def record_run_stories(new_stories, *, path=None):
    """Attach the run's new-Story count to the last-run summary.

    The collection summary is recorded before the identity stage has grouped the
    inbox, so the Story count is the one field that is only known afterwards.
    It is merged into the *existing* single latest-run record rather than
    appended as history: Today needs to say "37 нови публикации, 12 нови
    истории" about the run that actually happened, and a run log would be a
    much larger thing to own and keep correct.

    A run that was never recorded stays unrecorded. This never invents a run.
    """
    record = read_last_run(path)
    if record is None:
        return None
    record["new_stories"] = max(int(new_stories or 0), 0)
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    live_store.atomic_write(last_run_path(path), payload)
    return record


def read_last_run(path=None):
    store = last_run_path(path)
    if not store.exists():
        return None
    try:
        return json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
