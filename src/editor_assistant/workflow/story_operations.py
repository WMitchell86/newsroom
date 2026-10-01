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
#: V1.2-G4.37. There is deliberately NO time-based expiry for a FINISHED
#: operation. `MAX_OPERATIONS` is the memory bound and the only one; a finished
#: row is evicted by count, never by age.
#:
#: Measured: `_prune` used to drop every finished row 900 s after its last
#: update. The registry is mirrored to `var/operations.json` precisely so a
#: lost operation stays visible instead of looking like one nobody asked for
#: (V1.2-G4.6), and `recent()` / `last_for_scope()` read only `_ROWS` - so the
#: durable record survived on disk while the editor-visible index went empty.
#: Two consequences, both observed: the Operations page lost every row 15
#: minutes after the last message, and `quick_draft.availability.lastAttempt`
#: forgot a refusal, so Today offered «Чернова» again with the reason nowhere
#: on screen. That is the exact symptom V1.2-G4.36 was written to remove,
#: reintroduced one step later by the expiry. An operation that reported
#: something remains reportable until it is evicted by count.
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


def _now() -> str:
    """The wall clock, as an ISO-8601 UTC string.

    V1.2-G4.38. The registry already stamped every row with `updated_at`, but
    that value is `time.monotonic()` — a duration since the PROCESS started,
    not a time of day. It orders rows correctly inside one run and is
    meaningless to a person: `1234.5` is not an answer to "when did this
    happen". So it stays, for ordering and eviction, and this is what the
    editor sees.

    The Operations page could not show a time at all before this, and the
    reason was not a missing label: no wall-clock value existed anywhere on
    the row. `var/operations.json` carried a `saved_at`, but that is when the
    FILE was written, which for a batch of operations is the time of the last
    one — reporting it per row would have dated every operation to the same
    moment, which is exactly the kind of confident wrong sentence §6 forbids.
    """
    return datetime.now(timezone.utc).isoformat()


def token_for(story_id, gap_signature, generation=0, key=""):
    seed = f"{story_id}\0{gap_signature}\0{generation}\0{key or ''}"
    return "op_" + hashlib.sha256(seed.encode()).hexdigest()[:24]


#: V1.2-G4.36. The result statuses that mean the command RAN and produced
#: nothing. A worker that returns normally has succeeded as an operation; the
#: command it ran may still have refused. Recording only the registry status made
#: the history state a success for work that produced nothing.
#:
#: Measured on the operator's own desk: one Quick Draft on a collected Story
#: returned `needs_attention`, created no Article, and `var/operations.json`
#: recorded `status: "succeeded"` with an empty `error_code`. Reloading Today then
#: showed «Чернова» again with no trace that anything had been asked for, which is
#: the exact symptom `lastAttempt` was added to remove.
REFUSED_OUTCOMES = frozenset({"needs_attention"})


def _outcome_of(result):
    """`(outcome, code, message)` for a command result, or empty strings.

    Deliberately narrow: only a dict carrying a string `status` reports an
    outcome, and only the command's own editor-safe `reasonCode`/`message` are
    kept. No provider text, no prompt and no internal id crosses into the
    registry, which is read by an editor-facing surface.
    """
    if not isinstance(result, dict):
        return "", "", ""
    status = result.get("status")
    if not isinstance(status, str) or not status:
        return "", "", ""
    return (
        status,
        str(result.get("reasonCode") or "")[:64],
        str(result.get("message") or "")[:240],
    )


def _evict_finished(keep: int) -> None:
    """Drop the oldest FINISHED rows until at most `keep` remain.

    The one bound on the registry. It never drops `pending`/`running` work:
    those rows are what a caller reattaches to, so evicting them would orphan a
    live operation (its `release` no-ops on token inequality while the worker
    keeps running). Insertion order is the recency order for a finished row,
    which is why the oldest finished rows are the only candidates.
    """
    for old_token, item in list(_ROWS.items()):
        if len(_ROWS) <= keep:
            return
        if item["status"] not in {"pending", "running"}:
            _ROWS.pop(old_token, None)


def start(story_id, gap_signature, work, generation=0, key=""):
    token = token_for(story_id, gap_signature, generation, key)
    now = time.monotonic()
    started_at = _now()
    with _LOCK:
        existing = _ROWS.get(token)
        if existing is not None and existing["status"] == "failed":
            existing.update(
                status="pending",
                result=None,
                error=None,
                error_code="",
                outcome="",
                outcome_code="",
                outcome_message="",
                updated_at=now,
                # V1.2-G4.38: a retry is a NEW attempt, so it is re-stamped. The
                # finished time of the failed run is dropped with it: leaving it
                # would date the retry to the moment the previous one died.
                started_at=started_at,
                finished_at="",
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
                _evict_finished(MAX_OPERATIONS - 1)
            row = {
                "story_id": story_id,
                "status": "pending",
                "result": None,
                "error": None,
                "error_code": "",
                "outcome": "",
                "outcome_code": "",
                "outcome_message": "",
                "updated_at": now,
                # V1.2-G4.38: when it was asked for, and (below) when it stopped.
                "started_at": started_at,
                "finished_at": "",
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
            outcome, outcome_code, outcome_message = _outcome_of(result)
            with _LOCK:
                if token in _ROWS:
                    row["view"] = {"status": "succeeded"}
                    _ROWS[token].update(
                        status="succeeded",
                        result=result,
                        # V1.2-G4.36: the WORK succeeded; what the COMMAND did is
                        # this. Without it a refusal is indistinguishable from a
                        # Draft in the ledger and in the Today row.
                        outcome=outcome,
                        outcome_code=outcome_code,
                        outcome_message=outcome_message,
                        updated_at=time.monotonic(),
                        finished_at=_now(),
                    )
            _write_ledger()
        except Exception as exc:  # noqa: BLE001 - worker must become a sanitized failed operation
            with _LOCK:
                if token in _ROWS:
                    row["view"] = {"status": "failed"}
                    _ROWS[token].update(
                        status="failed",
                        # A raise is not a result: whatever a previous run of this
                        # token reported must not survive into the failure.
                        outcome="",
                        outcome_code="",
                        outcome_message="",
                        error=str(exc)[:240] or type(exc).__name__,
                        # A command that already classified its own stable failure
                        # keeps that code; the caller maps it to editor wording and
                        # never re-reads the raw text. Unclassified failures keep
                        # the exception TYPE as the detail so the envelope never
                        # invents a source/quota cause; `operation_status` maps
                        # the empty code to a neutral technical sentence.
                        error_code=str(getattr(exc, "code", "") or "")[:64],
                        updated_at=time.monotonic(),
                        finished_at=_now(),
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
                        # V1.2-G4.36: the persisted history has to distinguish a
                        # Draft from a refusal, or the ledger is a record of
                        # success for work that produced nothing.
                        "outcome": row.get("outcome", ""),
                        "outcome_code": row.get("outcome_code", ""),
                        "outcome_message": row.get("outcome_message", ""),
                        # V1.2-G4.38: the wall clock survives the restart. Without
                        # it a restored row would be the ONLY row on the page
                        # with no time on it, which reads as "this one is
                        # special" rather than "we lost it".
                        "started_at": row.get("started_at", ""),
                        "finished_at": row.get("finished_at", ""),
                    }
                    for token, row in _ROWS.items()
                ]
            path = ledger_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "rows": rows,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
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
                "outcome": item.get("outcome", ""),
                "outcome_code": item.get("outcome_code", ""),
                "outcome_message": item.get("outcome_message", ""),
                "result": None,
                "error": error,
                "error_code": code,
                "updated_at": time.monotonic(),
                # V1.2-G4.38: restored with the time the work ACTUALLY ran, not
                # with the restart time. Re-stamping it here would date every
                # recovered operation to the moment the server came back.
                "started_at": item.get("started_at", ""),
                "finished_at": item.get("finished_at", ""),
                "view": {"status": status},
            }
            restored += 1
        # V1.2-G4.37: the ledger is now the only history that outlives count
        # eviction, so it is also the one path that could grow `_ROWS` without a
        # bound. History is restored in insertion order, so the eviction drops
        # the oldest, exactly as the in-process bound would have.
        _evict_finished(MAX_OPERATIONS)
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
    # A row that has not failed has no reason to show. Returning the failure
    # sentence for `succeeded` because it carries no error code made four real
    # successes read as "the operation could not finish" — the editor is told
    # the work failed while the result is sitting right there. Silence is the
    # truthful value here; the sentence is a fallback for a FAILURE whose cause
    # was never observed, never a decoration for a row that worked.
    if row.get("status") != "failed":
        return ""
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
                    # V1.2-G4.36: what the COMMAND did, not only that the worker
                    # returned. `status` alone cannot express "ran and refused".
                    "outcome": row.get("outcome", ""),
                    "outcomeCode": row.get("outcome_code", ""),
                    "outcomeMessage": row.get("outcome_message", ""),
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
        rows = []
        for token, row in reversed(_ROWS.items()):
            rows.append(
                {
                    "operationToken": token,
                    "storyId": row.get("story_id", ""),
                    "status": row["status"],
                    "errorCode": row.get("error_code", ""),
                    "error": _editor_reason(row),
                    # V1.2-G4.36: the index that exists so "what happened to the
                    # four I started" has an answer must not answer "succeeded"
                    # for one that refused. The reasons travel with it: a row
                    # that says "did not produce anything" and cannot say why is
                    # the same silence in a new place.
                    "outcome": row.get("outcome", ""),
                    "outcomeCode": row.get("outcome_code", ""),
                    "outcomeMessage": row.get("outcome_message", ""),
                    # V1.2-G4.38: when it was asked for and when it stopped, as
                    # wall-clock UTC. Empty for work still in flight, which is
                    # the truth: there is no finish time for a running job.
                    "startedAt": row.get("started_at", ""),
                    "finishedAt": row.get("finished_at", ""),
                }
            )
        # V1.2-G4.38, review fix. The order used to be insertion order, which is
        # not the same thing once a row can be re-stamped: a RETRY reuses its
        # token and its slot in `_ROWS` but gets a fresh `started_at`, so the
        # newest work on the desk — the retry, the one an editor most wants to
        # see — sorted to the BOTTOM. Measured: `['s-second', 's-first']` where
        # `s-first` was the later of the two.
        #
        # Before this slice the page could not show a time at all, so insertion
        # order was merely imprecise. Now that every row carries an instant, an
        # order that contradicts the timestamps printed beside it is a visible
        # lie, so the list is sorted by the same clock it displays.
        #
        # Sorted on `startedAt` alone, stably: rows written by an older ledger
        # carry no `started_at`, compare equal, and keep their insertion order
        # among themselves rather than being pushed around by a value they do
        # not have.
        rows.sort(key=lambda item: item["startedAt"], reverse=True)
        return rows[:limit]


def get(token):
    with _LOCK:
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
