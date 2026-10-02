"""What was actually SENT to a model, kept apart from the usage ledger.

There are two records of a model call and they answer different questions:

* `var/model_usage/<day>.json` — the ledger. How much, to which model, with what
  outcome. **It never stores prompt text**, and that is a deliberate contract,
  not an oversight: it is an operational file that gets aggregated, diffed and
  read while investigating a provider failure, and an unpublished draft prompt
  is private editorial material (AGENTS.md rules 1 and 6).
  `tests/test_model_policy.py::test_usage_ledger_aggregates_and_never_stores_
  prompts` freezes it.

* this module — the prompt log. The exact text handed to one specific model on
  one specific attempt, so an editor can answer "what did you actually ask the
  model?" after a bad draft, and "which model wrote this?".

Why the router and not the caller. `_trim_for_model` runs INSIDE
`generate._call_gemini`, so a prompt logged by `live.py` (before the call) would
be the pre-trim text — which is not what the provider received whenever the
30 000-char safety valve fires. Logging at the transport boundary is the only
place where "logged" and "sent" are the same string.

Deliberately separate file, deliberately `0600`. The prompt can contain the
unpublished source text, so this store gets the same permissions as the other
private editorial stores (`cases.jsonl`, `live_evidence.jsonl`) rather than the
world-readable default an `open("a")` would produce.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from editor_assistant import store_retention

ROOT = Path(__file__).resolve().parents[3]

#: The ledger's promise is scoped to the ledger; this file is a different store.
FILENAME = "model_prompts.jsonl"


def prompt_log_path(root=None) -> Path:
    """Where the sent-prompt log lives.

    `MODEL_PROMPT_LOG` wins and is the unambiguous override (tests use it).
    `root` is the `var/` directory, matching `model_usage.usage_dir()`'s shape,
    so `root=tmp_path` yields `tmp_path/editorial_workflow/model_prompts.jsonl` -
    NOT `tmp_path/model_prompts.jsonl`. Stated here because getting it wrong
    silently writes to a different place than the caller expects, which is how
    a test ends up asserting on a file that was never created.
    """
    override = os.environ.get("MODEL_PROMPT_LOG")
    if override:
        return Path(override)
    base = Path(root) if root is not None else ROOT / "var"
    return base / "editorial_workflow" / FILENAME


def record_sent_prompt(
    *,
    role,
    provider,
    model,
    prompt_text,
    request_id="",
    route_index=None,
    payload_class="",
    outcome="",
    attempt=1,
    sent_chars=None,
    root=None,
):
    """Append one attempt's prompt. Best effort — logging must never fail a call.

    Called once per REAL transport execution, so a request that walked four
    routes leaves four rows: three of them are exactly the "why did it not
    use the good model" evidence an editor asks for after the fact. A route
    retried under `attempts_allowed` logs once per execution, so a request
    with `attempts_allowed == 2` that fails twice leaves two rows.

    `outcome` is the attempt's own verdict (`SENT`, `FAILED:<category>`);
    `sent_chars` is the length the transport reported receiving (`None`
    when the transport never answered — e.g. it raised before trimming —
    in which case the stored text is what was handed to it). A generation
    must not fail because its own audit trail had a bad day.

    Returns the record, or `None` when it could not be written.
    """
    text = prompt_text if isinstance(prompt_text, str) else str(prompt_text or "")
    row = {
        "at": _utc_now(),
        "request_id": str(request_id or ""),
        "role": str(role or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "route_index": route_index,
        "attempt": int(attempt or 1),
        "payload_class": str(payload_class or ""),
        "outcome": str(outcome or ""),
        "chars": len(text),
        "sent_chars": sent_chars if sent_chars is None else int(sent_chars),
        "prompt": text,
    }
    try:
        return _write(row, root)
    except Exception:  # noqa: BLE001 - the audit trail must never fail a generation
        # Deliberately broader than an OSError catch: this runs on the hot path
        # of every model attempt, and a broken logger (bad path type, an
        # unserialisable row, a patched-out helper) must not take the editor's
        # draft down with it. The docstring promises best effort; this is where
        # that promise is kept.
        return None


def _write(row: dict, root=None):
    """The actual append; ordinary IO failure is handled by the caller."""
    path = prompt_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with restrictive permissions from the start: `open("a")` would
    # apply the umask (0022 -> world-readable) to private editorial text.
    # Fail CLOSED: if the pre-existing file cannot be brought to 0600, the
    # row is not written anywhere else (no world-readable copy, no silent
    # downgrade). Measured: `os.chmod` raising after `os.open` used to leave
    # the row appended at the file's prior mode.
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        os.close(fd)
        raise
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Retention (owner decision: two days, dev mode) runs AFTER the append and
    # is itself best effort — if the rewrite fails the row above is already on
    # disk, and swallowing here is what keeps `_write` from reporting a loss
    # that did not happen.
    try:
        store_retention.maybe_prune(path)
    except Exception:  # noqa: BLE001 - a prune must never undo the append
        pass
    return row


def read_sent_prompts(*, role=None, model=None, request_id=None, limit=None, root=None):
    """Read the log back. Unreadable lines are skipped, never fatal."""
    path = prompt_log_path(root)
    if not path.exists():
        return []
    out = []
    try:
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if role and row.get("role") != role:
                continue
            if model and row.get("model") != model:
                continue
            if request_id and row.get("request_id") != request_id:
                continue
            out.append(row)
    except OSError:
        return []
    return out[-limit:] if limit else out


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")