"""Canonical live-evidence store (one writer, one schema).

Before M3C (automatic research enrichment) every producer of
`live_evidence.jsonl` must go through this module. The CLI and the Workbench
used to keep private read-modify-write copies; that is a reliability seam, not
an architecture. Rules (harness M3A A3):

* exact same JSON schema as before: one object per line, keyed by `evidence_id`;
* deterministic ordering (`evidence_id`) and deterministic bytes
  (`sort_keys=True`, `ensure_ascii=False`);
* atomic same-directory temp file + `os.replace`;
* no editorial logic here - this is a file-store seam only;
* caller-selectable path (tests and the Workbench pass their own).

Reading tolerates a missing file (empty store). A serialization failure raises
BEFORE the store is touched, so a bad row can never truncate existing evidence.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: Default runtime path; callers with an overridable root pass `path=` instead.
LIVE_EVIDENCE_PATH = ROOT / "var" / "editorial_workflow" / "live_evidence.jsonl"


def read_live_evidence(path=None):
    """Return `{evidence_id: row}` in insertion order of the file."""
    store = Path(path) if path is not None else LIVE_EVIDENCE_PATH
    if not store.exists():
        return {}
    rows = {}
    for line in store.open(encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            rows[row["evidence_id"]] = row
    return rows


def save_live_evidence_row(row, path=None):
    """Upsert one row by `evidence_id` and rewrite the store atomically."""
    store = Path(path) if path is not None else LIVE_EVIDENCE_PATH
    rows = read_live_evidence(store)
    rows[row["evidence_id"]] = row
    # Serialize fully before touching the file: a bad row must not truncate.
    lines = [
        json.dumps(r, ensure_ascii=False, sort_keys=True)
        for r in sorted(rows.values(), key=lambda r: r["evidence_id"])
    ]
    payload = "\n".join(lines) + "\n"
    _atomic_write(store, payload)


def _atomic_write(path, data):
    """Same-directory temp file + os.replace (no partial writes)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
