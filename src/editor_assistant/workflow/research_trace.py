"""Why a research page did or did not reach the draft model (V1.2-G4.20).

`story_research.json` records what SURVIVED: the promoted sources, their claims,
and the fact ids. It says nothing about the pages that were dropped, and the
research loop has five separate `continue` points where a page disappears
without a recorded reason (aggregator host, blocked domain, duplicate
publication, no usable prose, claim gate). So the honest question an editor asks
after a thin draft - "did it look anywhere else, and what happened there?" -
has no answer in the product at all.

That is the same shape of defect as the prompt log: a real decision happened and
nothing recorded it. The difference is where the answer lives.

Deliberately a SEPARATE store, for the same reason `model_prompt_log` is:
`story_research_store._row()` validates a CLOSED field set (`req <= set(v) <=
req | optional`). Adding a trace field to the research row would break that
contract, and the row is the canonical assessment the editor reads.

One row per page the round CONSIDERED, kept whether it was kept or dropped, so
the answer is a list with both outcomes rather than a count of survivors. Dropped
pages store the url/host and the reason and NOT the page text: the value of this
store is "what happened", and keeping whole scraped pages would duplicate the
private evidence stores at a size nobody asked for.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from editor_assistant import store_retention

ROOT = Path(__file__).resolve().parents[3]

FILENAME = "research_trace.jsonl"

#: Every way a considered page can end. Named so the reader sees a CAUSE and not
#: a silent absence, and so a new drop point cannot be added without picking one.
KEPT = "KEPT"
SKIPPED_NON_PUBLISHER = "SKIPPED_NON_PUBLISHER"
SKIPPED_BLOCKED = "SKIPPED_BLOCKED"
SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
SKIPPED_NO_PROSE = "SKIPPED_NO_PROSE"
SKIPPED_CLAIM_GATE = "SKIPPED_CLAIM_GATE"
OPEN_FAILED = "OPEN_FAILED"
NOT_ATTEMPTED = "NOT_ATTEMPTED"

OUTCOMES = (
    KEPT,
    SKIPPED_NON_PUBLISHER,
    SKIPPED_BLOCKED,
    SKIPPED_DUPLICATE,
    SKIPPED_NO_PROSE,
    SKIPPED_CLAIM_GATE,
    OPEN_FAILED,
    NOT_ATTEMPTED,
)


def trace_path(root=None) -> Path:
    """Where the research trace lives (`RESEARCH_TRACE_PATH` overrides it)."""
    override = os.environ.get("RESEARCH_TRACE_PATH")
    if override:
        return Path(override)
    base = Path(root) if root is not None else ROOT / "var"
    return base / "editorial_workflow" / FILENAME


def record_page(
    *,
    story_id,
    url,
    outcome,
    reason="",
    host="",
    final_url="",
    source_id="",
    fact_ids=(),
    claim_count=0,
    dropped_by_gate=0,
    root=None,
):
    """Append one considered page. Best effort — never fail a research round."""
    if outcome not in OUTCOMES:
        outcome = NOT_ATTEMPTED
    row = {
        "at": _utc_now(),
        "story_id": str(story_id or ""),
        "url": str(url or ""),
        "final_url": str(final_url or ""),
        "host": str(host or ""),
        "outcome": outcome,
        "reason": str(reason or ""),
        "source_id": str(source_id or ""),
        "fact_ids": [str(x) for x in (fact_ids or [])],
        "claim_count": int(claim_count or 0),
        "dropped_by_gate": int(dropped_by_gate or 0),
    }
    try:
        return _write(row, root)
    except Exception:  # noqa: BLE001 - an audit trail must never fail research
        return None


def record_round(
    *,
    story_id,
    topic="",
    questions=(),
    considered=0,
    kept=0,
    facts=0,
    dropped_by_gate=0,
    operation_id="",
    root=None,
):
    """The round's summary, so a list of pages can be read without arithmetic."""
    row = {
        "at": _utc_now(),
        "story_id": str(story_id or ""),
        "outcome": "ROUND",
        "topic": str(topic or ""),
        "questions": [str(q) for q in (questions or [])],
        "considered": int(considered or 0),
        "kept": int(kept or 0),
        "facts": int(facts or 0),
        "dropped_by_gate": int(dropped_by_gate or 0),
        "operation_id": str(operation_id or ""),
    }
    try:
        return _write(row, root)
    except Exception:  # noqa: BLE001
        return None


def read_trace(*, story_id=None, outcome=None, limit=None, root=None):
    """Read the trace back; unreadable lines are skipped, never fatal."""
    path = trace_path(root)
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
            if story_id and row.get("story_id") != story_id:
                continue
            if outcome and row.get("outcome") != outcome:
                continue
            out.append(row)
    except OSError:
        return []
    return out[-limit:] if limit else out


def _write(row: dict, root=None):
    """The actual append; ordinary IO failure is handled by the caller."""
    path = trace_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 0600 like the other editorial stores: a url plus its verdict is still a
    # record of what the newsroom was reading. Fail CLOSED like the prompt
    # log: if the file cannot be brought to 0600, the row is not written
    # anywhere else.
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        os.close(fd)
        raise
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Retention (owner decision: two days, dev mode) runs AFTER the append and
    # is best effort: a failed rewrite leaves the row above on disk, and this
    # trail must never be what fails a research round.
    try:
        store_retention.maybe_prune(path)
    except Exception:  # noqa: BLE001 - a prune must never undo the append
        pass
    return row


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")