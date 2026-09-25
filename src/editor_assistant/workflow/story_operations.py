"""Bounded in-process operation registry for long Story research requests."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict

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

    threading.Thread(target=run, name=f"story-research-{token}", daemon=True).start()
    return token, {"status": "pending"}


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
