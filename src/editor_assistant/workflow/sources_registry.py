"""Editor-managed source registry (M4A) — the editor owns the sources.

The registry is **configuration, not evidence**: the collection pipeline reads it,
the editor writes it, and nothing in this module fetches, schedules or judges.

Rules
-----
* stdlib only; one canonical write path (`live_store.atomic_write`) so a crash can
  never truncate the store;
* deterministic bytes (`sort_keys=True`), ordered by `source_id`, so the file
  diffs cleanly in review;
* closed enums for `kind` / `collector` / `status` / `priority` / `cadence` — an
  unknown value raises `RegistryError` instead of being stored;
* a mute is **time-boxed**: `status="muted"` requires `muted_until` (a plain UTC
  date). The *effective* status is computed, never rewritten — once the date has
  passed the source is simply active again, so no mute silently becomes forever;
* `factual_authority=False` means "collect it, but never treat it as a factual
  authority" (monitoring only). It is the editor's claim, not a verification
  performed here.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from editor_assistant.workflow import default_sources, live_store

ROOT = Path(__file__).resolve().parents[3]

KINDS = ("official", "media", "national", "regional", "aggregator")
COLLECTORS = ("rss", "google_news_rss", "youtube", "web")
STATUSES = ("active", "disabled", "muted")
PRIORITIES = ("high", "normal", "low")
CADENCES = ("each_run", "daily", "weekly")

#: Display order for the editor (highest first).
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}

_SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: A closed schema: unknown keys are refused, so a typo cannot be stored silently.
FIELDS = (
    "source_id",
    "name",
    "kind",
    "collector",
    "url",
    "query",
    "status",
    "muted_until",
    "priority",
    "cadence",
    "factual_authority",
    "calendar",
    "note",
    "added_at",
    "updated_at",
)

#: Query length limit, matching the public-query privacy guard in `search.py`.
MAX_QUERY_CHARS = 400

#: New-install seed. Now the declarative catalogue (`workflow/default_sources.py`)
#: instead of three hand-written rows: the editor gets a real regional stack, and
#: only the entries the catalogue marks active are seeded (the optionals stay
#: catalogued but disabled). No outlet is invented and no feed URL is guessed —
#: the one `rss` entry is the feed the repository already uses, every other entry
#: is a publisher/locality-constrained monitoring query.
DEFAULT_SEED = default_sources.DEFAULT_ENTRIES


class RegistryError(ValueError):
    """A registry entry or action that must not be stored."""


def sources_path(path=None):
    """Runtime store; overridable for tests (never read/write outside it)."""
    if path is not None:
        return Path(path)
    override = os.environ.get("NEWSROOM_SOURCES_PATH")
    if override:
        return Path(override)
    return ROOT / "var" / "newsroom" / "sources.json"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today(today=None):
    if today is not None:
        return today
    return datetime.now(timezone.utc).date()


# ---------- validation ----------


def _require_enum(name, value, allowed):
    if value not in allowed:
        raise RegistryError(f"{name} must be one of {allowed}, got {value!r}")
    return value


def validate_entry(entry):
    """Return a normalized copy or raise `RegistryError` (never a partial store)."""
    if not isinstance(entry, dict):
        raise RegistryError("a source entry must be an object")
    unknown = sorted(set(entry) - set(FIELDS))
    if unknown:
        raise RegistryError(f"unknown source fields {unknown} (allowed: {list(FIELDS)})")
    source_id = str(entry.get("source_id", "")).strip()
    if not _SLUG_RX.match(source_id):
        raise RegistryError(
            f"source_id must be a lowercase slug (a-z, 0-9, '-'), got {source_id!r}"
        )
    name = str(entry.get("name", "")).strip()
    if not name:
        raise RegistryError(f"{source_id}: name is required")
    kind = _require_enum("kind", entry.get("kind"), KINDS)
    collector = _require_enum("collector", entry.get("collector"), COLLECTORS)
    status = _require_enum("status", entry.get("status", "active"), STATUSES)
    priority = _require_enum("priority", entry.get("priority", "normal"), PRIORITIES)
    cadence = _require_enum("cadence", entry.get("cadence", "each_run"), CADENCES)

    url = str(entry.get("url", "")).strip()
    query = str(entry.get("query", "")).strip()
    if collector in ("rss", "web", "youtube"):
        if not url.startswith(("http://", "https://")):
            raise RegistryError(
                f"{source_id}: collector={collector!r} requires an http(s) url, got {url!r}"
            )
    elif not query:
        raise RegistryError(f"{source_id}: collector='google_news_rss' requires a query")
    if len(query) > MAX_QUERY_CHARS:
        raise RegistryError(
            f"{source_id}: query must be <= {MAX_QUERY_CHARS} chars (public-query guard)"
        )

    muted_until = str(entry.get("muted_until", "")).strip()
    if status == "muted":
        if not _DATE_RX.match(muted_until):
            raise RegistryError(f"{source_id}: status='muted' requires muted_until as YYYY-MM-DD")
        try:
            date.fromisoformat(muted_until)
        except ValueError as exc:
            raise RegistryError(f"{source_id}: muted_until is not a real date: {exc}") from exc
    elif muted_until:
        raise RegistryError(f"{source_id}: muted_until is only meaningful with status='muted'")

    authority = entry.get("factual_authority", False)
    if not isinstance(authority, bool):
        raise RegistryError(f"{source_id}: factual_authority must be true or false")

    calendar = entry.get("calendar", False)
    if not isinstance(calendar, bool):
        raise RegistryError(f"{source_id}: calendar must be true or false")

    return {
        "source_id": source_id,
        "name": name,
        "kind": kind,
        "collector": collector,
        "url": url,
        "query": query,
        "status": status,
        "muted_until": muted_until,
        "priority": priority,
        "cadence": cadence,
        "factual_authority": authority,
        "calendar": calendar,
        "note": str(entry.get("note", "")).strip(),
        "added_at": str(entry.get("added_at") or _now()),
        "updated_at": str(entry.get("updated_at") or _now()),
    }


# ---------- store (read / write) ----------


def read_registry(path=None) -> dict:
    """Return `{source_id: entry}`, ordered by `source_id`. Missing file = empty."""
    store = sources_path(path)
    if not store.exists():
        return {}
    try:
        rows = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistryError(f"source registry is unreadable ({store}): {exc}") from exc
    if not isinstance(rows, list):
        raise RegistryError(f"source registry must be a JSON list of entries ({store})")
    out = {}
    for row in rows:
        entry = validate_entry(row)
        out[entry["source_id"]] = entry
    return {sid: out[sid] for sid in sorted(out)}


def save_registry(entries, path=None):
    """Validate everything, serialize fully, then write atomically."""
    if isinstance(entries, dict):
        entries = list(entries.values())
    normalized = sorted((validate_entry(entry) for entry in entries), key=lambda e: e["source_id"])
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    live_store.atomic_write(sources_path(path), payload)
    return normalized


def add_source(path=None, **entry) -> dict:
    """Add a new source. An existing `source_id` is refused (use the setters)."""
    registry = read_registry(path)
    errors = _collect_errors(entry)
    if errors:
        raise RegistryError("; ".join(errors))
    validated = validate_entry({**entry, "status": entry.get("status", "active")})
    if validated["source_id"] in registry:
        raise RegistryError(
            f"{validated['source_id']} already exists — change it instead of re-adding it"
        )
    registry[validated["source_id"]] = validated
    save_registry(registry, path)
    return validated


def _collect_errors(entry):
    """Field errors as a list (used to report several problems at once in the UI)."""
    try:
        validate_entry(entry)
    except RegistryError as exc:
        return [str(exc)]
    return []


def _update(source_id, path, **changes):
    registry = read_registry(path)
    if source_id not in registry:
        raise RegistryError(f"unknown source_id: {source_id}")
    merged = {**registry[source_id], **changes, "updated_at": _now()}
    validated = validate_entry(merged)
    registry[source_id] = validated
    save_registry(registry, path)
    return validated


def set_status(source_id, status, *, muted_until="", path=None):
    """Set active / disabled / muted. Muting must carry its end date."""
    _require_enum("status", status, STATUSES)
    if status == "muted" and not muted_until:
        raise RegistryError("muting requires an end date (muted_until=YYYY-MM-DD)")
    if status != "muted":
        muted_until = ""
    return _update(source_id, path, status=status, muted_until=muted_until)


def set_priority(source_id, priority, *, path=None):
    _require_enum("priority", priority, PRIORITIES)
    return _update(source_id, path, priority=priority)


def set_cadence(source_id, cadence, *, path=None):
    _require_enum("cadence", cadence, CADENCES)
    return _update(source_id, path, cadence=cadence)


def set_factual_authority(source_id, authority, *, path=None):
    if not isinstance(authority, bool):
        raise RegistryError("factual_authority must be true or false")
    return _update(source_id, path, factual_authority=authority)


#: Fields an editor may change after creation. `source_id` is the key: it is
#: never editable, so evidence and inbox rows keep pointing at the same source.
EDITABLE_FIELDS = ("name", "kind", "collector", "url", "query", "note")


def update_source(source_id, *, path=None, **changes):
    """Change an existing source's editable fields (the UI's "Редактирай")."""
    illegal = sorted(set(changes) - set(EDITABLE_FIELDS))
    if illegal:
        raise RegistryError(
            f"{source_id}: fields not editable: {illegal} (editable: {list(EDITABLE_FIELDS)})"
        )
    if not changes:
        raise RegistryError(f"{source_id}: nothing to change")
    return _update(source_id, path, **changes)


def seed_defaults(*, path=None, dry_run=False):
    """Write the default seed, adding only what is missing.

    Never overwrites an existing entry: once the editor has touched a source,
    its configuration is theirs, and re-running the seed must not undo edits.
    """
    registry = read_registry(path)
    added, skipped = [], []
    for entry in DEFAULT_SEED:
        if entry["source_id"] in registry:
            skipped.append(entry["source_id"])
            continue
        added.append(validate_entry(entry))
    if not dry_run and added:
        for entry in added:
            registry[entry["source_id"]] = entry
        save_registry(registry, path)
    return {"added": [e["source_id"] for e in added], "skipped": skipped}


def apply_defaults(*, path=None, preview=False):
    """Explicitly apply the default catalogue additively (M4A.1).

    The editor-owned store is never silently overwritten:

    * `preview=True` performs **no** write and reports what would change;
    * only missing catalogue IDs are added — an existing entry keeps the editor's
      status, priority, cadence and text verbatim;
    * a disabled source is never re-enabled;
    * repeated applies are idempotent.
    """
    registry = read_registry(path)
    added, present = [], []
    for entry in default_sources.CATALOG:
        source_id = entry["source_id"]
        if source_id in registry:
            present.append(source_id)
            continue
        added.append(validate_entry(entry))
    if not preview and added:
        for entry in added:
            registry[entry["source_id"]] = entry
        save_registry(registry, path)
    return {
        "preview": bool(preview),
        "added": [e["source_id"] for e in added],
        "present": present,
        "optional": list(default_sources.OPTIONAL_IDS),
    }


def remove_source(source_id, *, path=None):
    """Delete a source. Never deletes collected evidence — registry only."""
    registry = read_registry(path)
    if source_id not in registry:
        raise RegistryError(f"unknown source_id: {source_id}")
    removed = registry.pop(source_id)
    save_registry(registry, path)
    return removed


# ---------- views (computed, never stored) ----------


def effective_status(entry, *, today=None):
    """`active` for a window that has passed — the expiry is computed, not written."""
    if entry.get("status") != "muted":
        return entry.get("status")
    until = entry.get("muted_until") or ""
    if not _DATE_RX.match(until):
        # An unreadable window must not silence a source forever.
        return "active"
    return "muted" if date.fromisoformat(until) >= _today(today) else "active"


def describe(entry, *, today=None):
    """Entry + the two computed fields the UI shows."""
    status = effective_status(entry, today=today)
    return {
        **entry,
        "effective_status": status,
        "mute_expired": entry.get("status") == "muted" and status == "active",
    }


def describe_all(path=None, *, today=None):
    return [describe(entry, today=today) for entry in read_registry(path).values()]


def collectable(path=None, *, today=None):
    """Active sources, highest priority first — the collection runner's input."""
    rows = [e for e in describe_all(path, today=today) if e["effective_status"] == "active"]
    return sorted(rows, key=lambda e: (PRIORITY_RANK.get(e["priority"], 9), e["source_id"]))


def next_collection_label(entry, *, due=True, today=None):
    """What the editor sees in the «Следващо събиране» column.

    Deliberately does NOT invent a clock time: the repo installs no timer, so the
    operator owns the cron times. It reports the cadence, and for a live mute the
    date the source resumes.
    """
    status = effective_status(entry, today=today)
    if status == "disabled":
        return "—"
    if status == "muted":
        until = entry.get("muted_until") or ""
        return f"след {until[8:10]}.{until[5:7]}" if _DATE_RX.match(until) else "—"
    base = {
        "each_run": "при всяко събиране",
        "daily": "всеки ден",
        "weekly": "седмично",
    }.get(entry.get("cadence"), "—")
    # `due=False` is the operational truth once cadence is real: the column shows
    # what the runner will actually do, not just an installed cadence label.
    return base if due else "не е дължимо (днес вече е събрано)"


def summary(path=None, *, today=None):
    """Counts for the Workbench header (never a silent source of truth)."""
    rows = describe_all(path, today=today)
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row["effective_status"]] = counts.get(row["effective_status"], 0) + 1
    return {
        "total": len(rows),
        "active": counts.get("active", 0),
        "disabled": counts.get("disabled", 0),
        "muted": counts.get("muted", 0),
        "monitoring_only": sum(1 for r in rows if not r["factual_authority"]),
    }
