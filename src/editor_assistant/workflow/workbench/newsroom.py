"""M4A Workbench service: the editor's source registry and story inbox.

Thin by design — this module owns **no** validation. Every action delegates to
`workflow/sources_registry.py` / `workflow/inbox_store.py`, the same functions the
CLI uses, so the UI can never drift from the store contract. Its own jobs are:

* pick the runtime paths (one env knob, like the rest of the Workbench);
* turn a form submission into one registry/inbox call;
* keep a minimal, append-only audit of what the editor changed.

Read-only pages create nothing: opening «Източници» on an empty install must not
write a file.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import inbox_store, newsroom_run, sources_registry

ROOT = Path(__file__).resolve().parents[4]

#: The server is threaded and the registry is read-modify-write: serialize edits.
_MUTATION_LOCK = threading.RLock()


def newsroom_dir():
    """Runtime dir; overridable for tests (never read/write outside it)."""
    return Path(os.environ.get("WB_NEWSROOM_DIR") or (ROOT / "var" / "newsroom"))


def sources_store():
    return newsroom_dir() / "sources.json"


def inbox_store_path():
    return newsroom_dir() / "inbox.jsonl"


def audit_path():
    return newsroom_dir() / "newsroom_actions.jsonl"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_action(action, subject):
    """Append-only minimal audit (same shape as the case audit: who/what/when)."""
    row = {"action": action, "subject": subject, "timestamp": _now()}
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def read_actions(limit=None):
    path = audit_path()
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    return rows[-limit:] if limit else rows


# ---------- sources (read) ----------


def sources_view():
    """Registry rows + counts, with the two computed display fields."""
    rows = sources_registry.describe_all(sources_store())
    for row in rows:
        row["next_collection"] = sources_registry.next_collection_label(row)
    return {"rows": rows, "summary": sources_registry.summary(sources_store())}


def source_row(source_id):
    for row in sources_view()["rows"]:
        if row["source_id"] == source_id:
            return row
    return None


# ---------- sources (the editor's actions) ----------


def add_source(
    *,
    source_id,
    name,
    kind,
    collector,
    url="",
    query="",
    priority="normal",
    cadence="each_run",
    monitoring_only=False,
    note="",
):
    with _MUTATION_LOCK:
        entry = sources_registry.add_source(
            path=sources_store(),
            source_id=source_id,
            name=name,
            kind=kind,
            collector=collector,
            url=url,
            query=query,
            priority=priority,
            cadence=cadence,
            factual_authority=not monitoring_only,
            note=note,
        )
        record_action("source_added", entry["source_id"])
        return entry


def update_source(source_id, **changes):
    with _MUTATION_LOCK:
        entry = sources_registry.update_source(source_id, path=sources_store(), **changes)
        record_action("source_updated", source_id)
        return entry


def set_status(source_id, status, *, muted_until=""):
    with _MUTATION_LOCK:
        entry = sources_registry.set_status(
            source_id, status, muted_until=muted_until, path=sources_store()
        )
        record_action(f"source_{status}", source_id)
        return entry


def set_priority(source_id, priority):
    with _MUTATION_LOCK:
        entry = sources_registry.set_priority(source_id, priority, path=sources_store())
        record_action(f"source_priority_{priority}", source_id)
        return entry


def set_authority(source_id, authority):
    with _MUTATION_LOCK:
        entry = sources_registry.set_factual_authority(source_id, authority, path=sources_store())
        record_action("source_authority" if authority else "source_monitoring_only", source_id)
        return entry


def remove_source(source_id):
    with _MUTATION_LOCK:
        entry = sources_registry.remove_source(source_id, path=sources_store())
        record_action("source_removed", source_id)
        return entry


# ---------- collection (read-only view + dry-run preview) ----------


def collection_plan():
    """What a collection run would do right now (no network, no writes)."""
    return newsroom_run.plan(sources_store())


def inbox_view(limit=200):
    return newsroom_run.inbox_view(inbox_store_path(), sources_store(), limit=limit)


def set_inbox_status(item_id, status):
    with _MUTATION_LOCK:
        item = inbox_store.set_status(item_id, status, path=inbox_store_path())
        record_action(f"inbox_{status.lower()}", item_id)
        return item
