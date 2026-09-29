"""Bounded in-process operation registry for long Story research requests."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

#: V1.2-G4.5. The registry stays stdlib-only apart from this, and must: it is
#: imported BY the Draft layer, so importing that layer back would be circular.
#: `workflow.redaction` is dependency-free for exactly this reason.
from editor_assistant.workflow.redaction import safe_detail

LOG = logging.getLogger(__name__)

MAX_OPERATIONS = 32
TTL_SECONDS = 900
_LOCK = threading.RLock()
_ROWS = OrderedDict()

#: V1.2-G4.5. Workers are daemon threads and `_write_ledger` resolves its path
#: at CALL time, so a worker outliving the code that started it can write with
#: an environment nobody expected - which is how a test run overwrote the
#: operator's real `var/operations.json` with an empty registry.
#:
#: The fix is NOT here. It is a SESSION-SCOPED ledger override in the test
#: fixture, which is never released, so no straggler can reach the live path at
#: any point in the run. A `drain()` helper was tried first and removed: nothing
#: outside its own tests called it, and it could not have covered a worker that
#: started after the last drain anyway.


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
                        error=str(exc)[:240] or type(exc).__name__,
                        # A command that already classified its own stable failure
                        # keeps that code; the caller maps it to editor wording and
                        # never re-reads the raw text. Unclassified failures keep
                        # the exception TYPE as the detail so the envelope never
                        # invents a source/quota cause; `operation_status` maps
                        # the empty code to a neutral technical sentence.
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
#:
#: The path is read at call time and can be overridden (`WB_OPERATIONS_LEDGER_PATH`)
#: for the same reason `MODEL_HEALTH_PATH` can: a test run must never overwrite
#: the operator's own operation history.
_LEDGER_PATH = Path(__file__).resolve().parents[3] / "var" / "operations.json"
_LEDGER_LOCK = threading.RLock()


def ledger_path() -> Path:
    override = os.environ.get("WB_OPERATIONS_LEDGER_PATH")
    return Path(override) if override else _LEDGER_PATH


def _write_ledger() -> None:
    """Mirror the registry to disk. A best-effort mirror: if the disk is
    unwritable the in-process registry stays authoritative and the request that
    triggered this must still succeed - losing history is better than failing a
    Draft because a log file could not be written."""
    with _LEDGER_LOCK:
        try:
            # Snapshot under the registry lock: `run()` updates `_ROWS`
            # concurrently, and serializing a mutating OrderedDict would tear
            # the history this mirror exists to preserve.
            with _LOCK:
                rows = [
                    {
                        "token": token,
                        "story_id": row.get("story_id", ""),
                        "status": row["status"],
                        "error_code": row.get("error_code", ""),
                        "error": row.get("error") or "",
                    }
                    for token, row in _ROWS.items()
                ]
            path = ledger_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "rows": rows,
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError as exc:
            LOG.warning("operation ledger write failed: %s", type(exc).__name__)


def load_ledger() -> int:
    """Restore finished operations from disk at startup.

    Only FINISHED rows are restored, and only as a history. A row that was
    `running` when the process died is restored as `failed`, never as still
    running: the work is provably gone - the thread died with the process - and
    reporting it as in flight forever would be a lie the editor cannot act on.
    """
    try:
        payload = json.loads(ledger_path().read_text(encoding="utf-8"))
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


#: V1.2-G4.5. The registry must not hand the editor a cause it did not observe.
#:
#: The stored `error` is raw exception text. For a CLASSIFIED refusal that text
#: is the editor's own sentence, built from the one reason-message table, and it
#: is worth showing. For an UNCLASSIFIED failure it is whatever the runtime
#: raised, and a probe of this endpoint showed what that means in practice:
#: "openrouter/gemini-3 failed at /home/test/.config/router.json" rendered
#: verbatim on the Operations screen - a provider name and this machine's
#: filesystem path, neither observed nor actionable, presented as the reason.
#:
#: `safe_detail` alone does not fix that, and should not: it removes SECRETS, and
#: a path is not a secret. The fix is the same one G4.5 already applied to the
#: single-operation envelope - an unclassified reason is withheld, not laundered.
#: The raw text stays in the ledger and the logs for whoever is debugging.
#: Shown when a failure carries no reason the system actually observed. It says
#: a technical problem happened and nothing more, because naming a cause here
#: would be inventing one. Silence is not the alternative: `OperationsPage`
#: renders `op.error` only when it is non-empty, so an empty string is a red
#: badge with no cause at all - the exact symptom §G4.6 was written to remove.
#:
#: The wording deliberately matches `editor_application._GENERIC_OPERATION_DEFAULT`
#: (minus its retry hint), and the duplication is forced: that module imports
#: THIS one, so sharing a constant would mean a circular import. Do not "fix"
#: this by importing across - keep the two sentences in step by hand.
_UNOBSERVED_REASON = "Операцията не можа да завърши поради технически проблем."


def _editor_reason(row: dict) -> str:
    if not str(row.get("error_code") or ""):
        return _UNOBSERVED_REASON
    return safe_detail(str(row.get("error") or "")) or _UNOBSERVED_REASON


def last_for_scope(scope, limit=1):
    """The most recent operation for one scope, newest first.

    V1.2-G4.6. Being unavailable is not a reason to be silent. When a Quick
    Draft fails there is nothing to show on the Article - the whole point is
    that the work never happened - so the row itself has to carry the outcome,
    or the editor is left with a button that looks unpressed and an Operations
    page they have to know to visit.
    """
    with _LOCK:
        _prune(time.monotonic())
        found = []
        for token, row in _ROWS.items():
            if row.get("story_id") != scope:
                continue
            found.append(
                {
                    "operationToken": token,
                    "status": row["status"],
                    "errorCode": row.get("error_code", ""),
                    "error": _editor_reason(row),
                    "updated_at": row["updated_at"],
                }
            )
        found.sort(key=lambda item: item["updated_at"], reverse=True)
        return found[:limit]


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
                    "error": _editor_reason(row),
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
