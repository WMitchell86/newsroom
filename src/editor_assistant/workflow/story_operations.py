"""Bounded in-process operation registry for long Story research requests."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

MAX_OPERATIONS = 32
TTL_SECONDS = 900
_LOCK = threading.RLock()
_ROWS = OrderedDict()


class BusyError(RuntimeError):
    """All operation slots are occupied by active work."""


def token_for(story_id, gap_signature, generation=0, key=""):
    seed = f"{story_id}\0{gap_signature}\0{generation}\0{key or ''}"
    return "op_" + hashlib.sha256(seed.encode()).hexdigest()[:24]


def _prune(now):
    for token, row in list(_ROWS.items()):
        if now - row["updated_at"] > TTL_SECONDS and row["status"] not in {"pending", "running"}:
            _ROWS.pop(token, None)


def start(story_id, gap_signature, work, generation=0, key=""):
    token = token_for(story_id, gap_signature, generation, key)
    now = time.monotonic()
    with _LOCK:
        _prune(now)
        existing = _ROWS.get(token)
        if existing is not None and existing["status"] == "failed":
            existing.update(
                status="pending", result=None, error=None, error_code="", updated_at=now
            )
            existing["view"] = {"status": "pending"}
            row = existing
        else:
            if existing is not None:
                return token, dict(existing["view"])
            if len(_ROWS) >= MAX_OPERATIONS:
                active = [
                    token
                    for token, item in _ROWS.items()
                    if item["status"] in {"pending", "running"}
                ]
                if len(active) >= MAX_OPERATIONS:
                    raise BusyError("операциите са заети")
                for old_token, item in list(_ROWS.items()):
                    if item["status"] not in {"pending", "running"}:
                        _ROWS.pop(old_token, None)
                        if len(_ROWS) < MAX_OPERATIONS:
                            break
            row = {
                "story_id": story_id,
                "status": "pending",
                "result": None,
                "error": None,
                "error_code": "",
                "updated_at": now,
                "view": {"status": "pending"},
            }
            _ROWS[token] = row

    def run():
        with _LOCK:
            row = _ROWS.get(token)
            if row is None:
                return
            row["view"] = {"status": "running"}
            row["status"] = "running"
            row["updated_at"] = time.monotonic()
        try:
            result = work()
            with _LOCK:
                if token in _ROWS:
                    row["view"] = {"status": "succeeded"}
                    _ROWS[token].update(
                        status="succeeded", result=result, updated_at=time.monotonic()
                    )
            _write_ledger()
        except Exception as exc:  # noqa: BLE001 - worker must become a sanitized failed operation
            with _LOCK:
                if token in _ROWS:
                    row["view"] = {"status": "failed"}
                    _ROWS[token].update(
                        status="failed",
                        error=str(exc)[:240] or "Source unavailable",
                        # A command that already classified its own stable failure
                        # keeps that code; the caller maps it to editor wording and
                        # never re-reads the raw text.
                        error_code=str(getattr(exc, "code", "") or "")[:64],
                        updated_at=time.monotonic(),
                    )
            _write_ledger()

    _write_ledger()
    threading.Thread(target=run, name=f"story-research-{token}", daemon=True).start()
    return token, {"status": "pending"}


#: V1.2-G4.6. The registry used to live only in memory, so every restart erased
#: it: a Draft the editor had requested would be running, the process would be
#: restarted, and the operation would vanish with no record that it had ever
#: existed. The editor's side of that is silence - the button went back to
#: "Чернова" as if nothing had been asked for. Persisting the row is what makes
#: a lost operation visible instead of invisible.
_LEDGER_PATH = Path(__file__).resolve().parents[3] / "var" / "operations.json"
_LEDGER_LOCK = threading.RLock()


def _write_ledger() -> None:
    """Mirror the registry to disk. A best-effort mirror: if the disk is
    unwritable the in-process registry stays authoritative and the request that
    triggered this must still succeed - losing history is better than failing a
    Draft because a log file could not be written."""
    with _LEDGER_LOCK:
        try:
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "rows": [
                    {
                        "token": token,
                        "story_id": row.get("story_id", ""),
                        "status": row["status"],
                        "error_code": row.get("error_code", ""),
                        "error": row.get("error") or "",
                    }
                    for token, row in _ROWS.items()
                ],
            }
            _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
            _LEDGER_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass


def load_ledger() -> int:
    """Restore finished operations from disk at startup.

    Only FINISHED rows are restored, and only as a history. A row that was
    `running` when the process died is restored as `failed`, never as still
    running: the work is provably gone - the thread died with the process - and
    reporting it as in flight forever would be a lie the editor cannot act on.
    """
    try:
        payload = json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    rows = payload.get("rows") or []
    with _LOCK:
        restored = 0
        for item in rows:
            token = item.get("token")
            if not token or token in _ROWS:
                continue
            status = item.get("status") or "failed"
            interrupted = status in {"pending", "running"}
            if interrupted:
                status = "failed"
            error = item.get("error") or ""
            code = item.get("error_code") or ""
            if interrupted and not error:
                # The work provably died with the process. Saying so is the whole
                # point of persisting the row: silence is what made a lost Draft
                # look like one that was never asked for.
                error = "Операцията беше прекъсната при рестарт на сървъра."
                code = "INTERRUPTED_BY_RESTART"
            _ROWS[token] = {
                "story_id": item.get("story_id", ""),
                "status": status,
                "result": None,
                "error": error,
                "error_code": code,
                "updated_at": time.monotonic(),
                "view": {"status": status},
            }
            restored += 1
        return restored


def recent(limit=40):
    """Every operation this process knows about, newest first.

    V1.2-G4.6. The single-operation endpoint answers "how did THAT one go",
    which is useless when the editor cannot remember which tokens they have -
    and there is no list to look at. Asking for four drafts and getting four
    202s means four opaque handles, so the only way to find out what happened
    to them was to keep them all in a terminal. This is the missing index.
    """
    with _LOCK:
        _prune(time.monotonic())
        rows = []
        for token, row in reversed(_ROWS.items()):
            rows.append(
                {
                    "operationToken": token,
                    "storyId": row.get("story_id", ""),
                    "status": row["status"],
                    "errorCode": row.get("error_code", ""),
                    "error": row.get("error") or "",
                }
            )
        return rows[:limit]


def get(token):
    with _LOCK:
        _prune(time.monotonic())
        row = _ROWS.get(token)
        if row is None:
            return None
        return {
            "status": row["status"],
            "result": row["result"],
            "error": row["error"],
            "error_code": row.get("error_code", ""),
            "story_id": row["story_id"],
        }


def clear():
    with _LOCK:
        _ROWS.clear()
