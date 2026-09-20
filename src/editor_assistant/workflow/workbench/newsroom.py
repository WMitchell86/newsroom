"""M4A/M4B Workbench service: the editor's source registry and daily inbox.

Thin by design — this module owns **no** validation. Every action delegates to
`workflow/sources_registry.py`, `workflow/blocked_domains.py`,
`workflow/inbox_store.py` and `workflow/newsroom_run.py`, the same functions the
CLI uses, so the UI can never drift from the store contract. Its own jobs are:

* pick the runtime paths (one env knob, like the rest of the Workbench);
* turn a form submission into one service call;
* keep a minimal, append-only audit of what the editor changed;
* shape the daily inbox view (filters, pagination, status/problem counts).

Read-only pages create nothing: opening «Източници» or «Входящи» on an empty
install must not write a file.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import (
    blocked_domains,
    inbox_store,
    newsroom_run,
    source_health,
    sources_registry,
)

ROOT = Path(__file__).resolve().parents[4]

#: The server is threaded and the stores are read-modify-write: serialize edits.
_MUTATION_LOCK = threading.RLock()

INBOX_PAGE_SIZE = 50
INBOX_MAX_PAGE_SIZE = 200


def newsroom_dir():
    """Runtime dir; overridable for tests (never read/write outside it)."""
    return Path(os.environ.get("WB_NEWSROOM_DIR") or (ROOT / "var" / "newsroom"))


def sources_store():
    return newsroom_dir() / "sources.json"


def inbox_store_path():
    return newsroom_dir() / "inbox.jsonl"


def health_store():
    return newsroom_dir() / "source_health.json"


def blocked_store():
    return newsroom_dir() / "blocked_domains.json"


def last_run_store():
    return newsroom_dir() / "last_run.json"


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
    """Registry rows + counts, with the computed display fields the editor reads.

    Adds the operational state M4A.1 requires: source health, whether the source
    is due on its cadence, and whether its domain is blocked.
    """
    today = source_health.sofia_date()
    rows = sources_registry.describe_all(sources_store(), today=today)
    summary = sources_registry.summary(sources_store(), today=today)
    health = source_health.read_health(health_store())
    for row in rows:
        record = health.get(row["source_id"])
        if row["effective_status"] == "active":
            due, _reason = newsroom_run.due_for(row, record, today)
        else:
            due = False
        row["due"] = bool(due)
        row["next_collection"] = sources_registry.next_collection_label(row, due=due, today=today)
        row["health"] = source_health.describe(row["source_id"], health_store())
        row["blocked_reason"] = blocked_domains.blocked_reason(row, path=blocked_store())
    summary["problems"] = sum(
        1
        for row in rows
        if row["health"].get("last_status") == source_health.FAILED or row.get("blocked_reason")
    )
    return {"rows": rows, "summary": summary}


def source_row(source_id):
    for row in sources_view()["rows"]:
        if row["source_id"] == source_id:
            return row
    return None


def blocked_view():
    return {
        "domains": blocked_domains.effective_domains(blocked_store()),
        "default": list(blocked_domains.DEFAULT_BLOCKED),
    }


# ---------- sources (the editor's actions) ----------


def add_source(
    *,
    source_id,
    name,
    kind,
    collector,
    domain="",
    url="",
    query="",
    priority="normal",
    cadence="each_run",
    monitoring_only=False,
    note="",
    calendar=False,
):
    with _MUTATION_LOCK:
        entry = sources_registry.add_source(
            path=sources_store(),
            source_id=source_id,
            name=name,
            kind=kind,
            domain=domain,
            collector=collector,
            url=url,
            query=query,
            priority=priority,
            cadence=cadence,
            factual_authority=not monitoring_only,
            calendar=calendar,
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


def apply_defaults(*, preview=True):
    """Additively apply the default catalogue from the UI (never overwrites)."""
    with _MUTATION_LOCK:
        result = sources_registry.apply_defaults(path=sources_store(), preview=preview)
        if not preview and result["added"]:
            record_action("sources_defaults_applied", ",".join(result["added"]))
        return result


def add_blocked_domain(value):
    with _MUTATION_LOCK:
        result = blocked_domains.add_domain(value, path=blocked_store())
        record_action("domain_blocked", result["domain"])
        return result


def remove_blocked_domain(value):
    with _MUTATION_LOCK:
        result = blocked_domains.remove_domain(value, path=blocked_store())
        record_action("domain_unblocked", result["domain"])
        return result


# ---------- collection ----------


def collection_plan():
    """What a collection run would do right now (no network, no writes)."""
    return newsroom_run.plan(sources_store(), health_path=health_store())


def collect_now(*, dry_run=False, force=False):
    """Run the same one-shot collection service the CLI's cron path calls."""
    return newsroom_run.collect(
        dry_run=dry_run,
        path=sources_store(),
        store=inbox_store_path(),
        health_path=health_store(),
        blocked_path=blocked_store(),
        last_run_path=last_run_store(),
        root=newsroom_dir(),
        force=force,
    )


def last_run():
    return source_health.read_last_run(last_run_store())


# ---------- inbox (M4B daily view) ----------


def _inbox_problems():
    """Sources whose last collection failed (or that are refused by policy)."""
    rows = sources_view()["rows"]
    out = []
    for row in rows:
        if row["health"].get("last_status") == source_health.FAILED:
            out.append(
                {
                    "source_id": row["source_id"],
                    "name": row["name"],
                    "status": source_health.FAILED,
                    "detail": row["health"].get("last_error") or "грешка при последното събиране",
                }
            )
        elif row.get("blocked_reason"):
            out.append(
                {
                    "source_id": row["source_id"],
                    "name": row["name"],
                    "status": newsroom_run.STATUS_BLOCKED,
                    "detail": row["blocked_reason"],
                }
            )
    return out


def inbox_view(
    *,
    status=None,
    source_id=None,
    kind=None,
    priority=None,
    date=None,
    authority=None,
    page=1,
    page_size=INBOX_PAGE_SIZE,
):
    """Filtered, paged inbox. The default the editor lands on is `NEW` (M4B §B4)."""
    view = newsroom_run.inbox_view(inbox_store_path(), sources_store())
    items = view["items"]
    registry = {row["source_id"]: row for row in sources_registry.describe_all(sources_store())}

    def _match(item):
        if status and status != "all" and item["status"] != status:
            return False
        # Filters describe the item itself: `source_id`/`kind` = how it was
        # discovered, `authority` = who published it (never inherited).
        if source_id and item["source_id"] != source_id:
            return False
        if kind and item["source_kind"] != kind:
            return False
        if priority and item["priority"] != priority:
            return False
        if date and not (item["published_at"] or item["discovered_at"]).startswith(date):
            return False
        if authority == "official":
            return item.get("publisher_kind") == "official"
        if authority == "authority":
            return bool(item.get("factual_authority"))
        if authority == "monitoring":
            return not item.get("factual_authority")
        return True

    filtered = [item for item in items if _match(item)]
    try:
        page = max(int(page), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(min(int(page_size), INBOX_MAX_PAGE_SIZE), 1)
    except (TypeError, ValueError):
        page_size = INBOX_PAGE_SIZE
    total = len(filtered)
    page_count = max((total + page_size - 1) // page_size, 1)
    page = min(page, page_count)
    start = (page - 1) * page_size
    window = filtered[start : start + page_size]

    return {
        "items": window,
        "counts": view["counts"],
        "problems": _inbox_problems(),
        "last_run": last_run(),
        "total": total,
        "page": page,
        "page_count": page_count,
        "page_size": page_size,
        "filters": {
            "status": status or "all",
            "source_id": source_id or "",
            "kind": kind or "",
            "priority": priority or "",
            "date": date or "",
            "authority": authority or "",
        },
        "source_options": sorted(
            ({"source_id": sid, "name": row["name"]} for sid, row in registry.items()),
            key=lambda r: r["name"],
        ),
    }


def set_inbox_status(item_id, status):
    with _MUTATION_LOCK:
        item = inbox_store.set_status(item_id, status, path=inbox_store_path())
        record_action(f"inbox_{status.lower()}", item_id)
        return item
