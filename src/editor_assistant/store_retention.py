"""How long the best-effort audit stores keep their rows.

Two append-only JSONL stores record debugging trails and neither was ever
bounded:

* ``model_prompts.jsonl`` — what was sent to each model per attempt;
* ``research_trace.jsonl`` — why each considered research page was kept or
  dropped.

Both hold private editorial text, and both grew on every write. The owner's
decision (2026-10-01, dev mode): **keep two days, and do not care about size
beyond that.** So this module does not design a retention scheme — it applies
one bound to both stores from a single place, because two copies of a
destructive routine is how they drift apart later.

What is deliberately *not* here:

* the usage ledger (``model_usage``) — a cost record, not a debug trail, and
  out of scope;
* rotation into daily files — a full rewrite of a two-day file is small, and
  a second file per day is a second thing to keep correct.

Safety rules, in the order they matter:

1. **A row we cannot interpret is kept.** An unparseable or missing ``at``
   means this module does not know the row's age, and "unknown age" must
   never be quietly deleted (AGENTS.md rule 6, in file form).
2. **A failed prune never breaks the append.** The caller appends first and
   prunes second, and treats a prune failure as a no-op: the audit trail is
   best effort, and the freshly written row must survive.
3. **The rewrite is atomic** (temp file + ``os.replace``), so a reader never
   sees a half-written store, and the temp file is created ``0600`` so the
   replacement keeps the private mode.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: Rows older than this are dropped. Two days is an owner decision, not a
#: measured value.
RETENTION_DAYS = 2

#: How often a *write* may trigger a prune. Without it every append would
#: read and rewrite the whole file; with it the store is bounded to
#: `RETENTION_DAYS` plus at most this interval of slack.
PRUNE_INTERVAL_S = 3600


def _parse_timestamp(value) -> datetime | None:
    """UTC timestamp for a row's ``at``, or ``None`` when it is unreadable."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_dt(now=None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        moment = now
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(float(now), timezone.utc)
    parsed = _parse_timestamp(now)
    if parsed is None:
        raise ValueError(f"retention: unreadable 'now': {now!r}")
    return parsed


def marker_path(path) -> Path:
    """Sidecar whose mtime says when this store was last pruned."""
    return Path(str(path) + ".prune")


def prune(path, *, retention_days=RETENTION_DAYS, now=None) -> int:
    """Drop rows stamped older than `retention_days`; return how many went.

    Any read problem returns 0 rather than raising: this is an audit trail
    and it must never be the reason a generation or a research round fails.
    Rows whose `at` is missing or unparseable are KEPT — see rule 1 in the
    module docstring.
    """
    path = Path(path)
    try:
        if not path.exists():
            return 0
        cutoff = _now_dt(now) - timedelta(days=int(retention_days))
        raw = path.read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError):
        return 0

    kept: list[str] = []
    dropped = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            stamp = _parse_timestamp((json.loads(line) or {}).get("at"))
        except (ValueError, AttributeError, TypeError):
            stamp = None  # unreadable row: keep it, we cannot date it
        if stamp is None or stamp >= cutoff:
            kept.append(line)
        else:
            dropped += 1
    if not dropped:
        return 0

    payload = "".join(line + "\n" for line in kept)
    try:
        _atomic_write_private(path, payload)
    except OSError:
        return 0
    return dropped


def maybe_prune(
    path, *, retention_days=RETENTION_DAYS, now=None, interval_s=PRUNE_INTERVAL_S
) -> int:
    """Prune `path` at most once per `interval_s`; always returns rows dropped.

    The sidecar marker's mtime is the throttle, so a busy store rewrites at
    most once an hour instead of once per row. A store that stops receiving
    writes keeps its rows — nothing is growing, and the next write prunes.
    """
    path = Path(path)
    marker = marker_path(path)
    now_ts = time.time() if now is None else float(_now_dt(now).timestamp())
    try:
        last = marker.stat().st_mtime
    except OSError:
        last = 0.0
    if now_ts - last < interval_s:
        return 0
    dropped = prune(path, retention_days=retention_days, now=now_ts)
    # Touch only after a prune ran: one that failed leaves the marker stale,
    # so the next write tries again instead of waiting another interval.
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        # `os.utime` does NOT create a missing file: it raises FileNotFoundError
        # and leaves nothing behind. Measured here, because the throttle depends
        # on it - without the `touch` the marker never exists, `last` stays 0.0
        # and every single append re-prunes (read + rewrite the whole store).
        marker.touch()
        os.utime(marker, (now_ts, now_ts))
        os.chmod(marker, 0o600)
    except OSError:
        pass
    return dropped


def _atomic_write_private(path: Path, payload: str) -> None:
    """Temp file + `os.replace`, created 0600 so the private mode survives."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    # `mkstemp` is 0600 and `replace` keeps the temp inode's mode — stated
    # here because the guarantee becomes invisible once it holds.
    os.chmod(path, 0o600)
