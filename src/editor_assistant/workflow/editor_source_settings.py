"""V1.2-G4: the editor's Sources screen, served from the canonical registry.

This module is a **thin application service**, not a second store. Every read and
every write goes through `sources_registry`, against the same file the collector
reads, resolved exactly the way the collector resolves it (`WB_NEWSROOM_DIR` /
`NEWSROOM_DIR`). There is deliberately no frontend-owned source configuration and
no parallel trusted-domain list: the SPA can only ask for a change, and the
canonical registry is what actually changes (§2).

What this layer adds, and nothing more:

* **editor language** (§4, §12, §13). Registry vocabulary (`kind`, `priority`,
  `effective_status`) is translated into the words the newsroom uses. The raw
  enum is also returned, so the client can filter on it without parsing a label,
  but the editor never has to read it;
* **plain validation errors** (§20). `RegistryError` speaks in schema terms
  ("collector='google_news_rss' requires a query"); §20 requires sentences an
  editor can act on, so each failure is mapped to one here;
* **derived safe defaults** on add (§9). The editor never types a `source_id`, a
  collector or a cadence. They are derived and validated;
* **write safety** (§27). The server is threaded and the registry is a
  read-modify-write JSON file, so a process lock serializes the read/validate/
  write sequence; the atomic file replacement is the existing
  `live_store.atomic_write`.

Deliberately NOT here (§1, §22, §23):

* no RBAC, no source version history, no audit database, no scraping studio;
* no hard delete. `sources_registry.remove_source` exists and the legacy
  Workbench still calls it, but a removed `source_id` disappears from
  `authority_by_domain`, so previously-collected Publications whose publisher was
  that row silently lose their first-party standing on re-read. That is exactly
  the "historical evidence breaks" condition §11 tells us not to allow until it
  is proven safe, so `Изключи` is the only removal in G4;
* no AI credibility scoring. `factual_authority` is the editor's own policy
  claim and is only ever written from an explicit editor action;
* no Research, no Serper, no ranking, no Story/Article mutation.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

from editor_assistant.workflow import blocked_domains, newsroom_refresh, source_health
from editor_assistant.workflow import sources_registry as registry

ROOT = Path(__file__).resolve().parents[3]

#: The HTTP server is threaded and every mutation is a read-modify-write over one
#: JSON file. Serializing the whole sequence is the smallest mechanism that makes
#: "last writer wins" impossible: two concurrent edits can no longer read the
#: same snapshot and each write only their own field.
_WRITE_LOCK = threading.Lock()

#: §12. The canonical registry kinds, in editor language. Every value the backend
#: supports is exposed — no UI-only taxonomy is invented, and there is no "Друг"
#: because the registry has no such kind to map to.
KIND_LABELS = {
    "official": "Официален",
    "media": "Медия",
    "national": "Национална медия",
    "regional": "Регионална медия",
    "aggregator": "Агрегатор",
}

#: §13. The existing registry priority, in words. No numeric score is ever shown.
PRIORITY_LABELS = {
    "high": "Висок",
    "normal": "Нормален",
    "low": "Нисък",
}

#: §6. The help text for `Надежден за факти`. It states what the toggle actually
#: does — the newsroom accepts this publisher as PRIMARY for appropriate
#: first-party claims — and not that everything on the site is true.
AUTHORITY_HELP = (
    "Когато източникът публикува информация от собствената си компетентност, "
    "тя може да се използва като първична фактическа основа."
)

#: §21. Shown once, when factual authority is being turned ON.
AUTHORITY_CONFIRMATION = (
    "Този източник ще може да служи като първична фактическа основа за "
    "информация от собствената му компетентност."
)

MAX_NAME = 120
MAX_URL = 500

#: A URL whose path looks like a feed is collected directly; anything else is
#: monitored through the existing publisher-constrained query mechanism
#: (§17: no bespoke adapter, and no invented feed URL).
_FEED_SUFFIXES = (".xml", ".rss", ".atom", ".rdf")
_FEED_PATH_HINTS = ("/feed", "/rss", "/feeds")


class SourceSettingsError(ValueError):
    """A change the newsroom's registry must refuse, in editor language."""

    def __init__(self, message: str, *, field: str = ""):
        super().__init__(message)
        self.message = message
        self.field = field


class SourceNotFound(SourceSettingsError):
    """The named source is not in the registry."""


# ---------- path resolution (§33) ----------


def _newsroom_root():
    """The redirected newsroom root, or `None` for the real one."""
    return os.environ.get("WB_NEWSROOM_DIR") or os.environ.get("NEWSROOM_DIR")




# ---------- path resolution (§33) ----------


def _newsroom_root():
    """The redirected newsroom root, or `None` for the real one."""
    return os.environ.get("WB_NEWSROOM_DIR") or os.environ.get("NEWSROOM_DIR")


def registry_path() -> Path:
    """The canonical registry, resolved exactly like the collector resolves it.

    Deliberately **not** `sources_registry.sources_path()` with no argument: that
    falls back to the repository's real `var/newsroom/sources.json` even when the
    newsroom root is redirected, which is precisely the isolation every test and
    every browser fixture depends on (§33).
    """
    return newsroom_refresh.newsroom_paths(_newsroom_root())["sources"]


def _health_path() -> Path:
    return newsroom_refresh.newsroom_paths(_newsroom_root())["health"]


# ---------- registry vocabulary -> editor language ----------


def _label(value: str, table: dict[str, str], fallback: str) -> str:
    return table.get(value, fallback)


def _health_view(source_id: str) -> dict:
    """§15: a quiet status, never an HTTP error or a collector internal.

    `FAILED` is the only state worth interrupting the editor for, and only as one
    word. `NEVER_RUN` stays empty rather than being rendered as a problem, so a
    freshly added source does not look broken.
    """
    record = source_health.describe(source_id, _health_path())
    status = record.get("last_status") or source_health.NEVER_RUN
    if status == source_health.FAILED:
        return {"status": "problem", "label": "Проблем", "lastSuccessAt": ""}
    if status == source_health.NEVER_RUN:
        return {"status": "unknown", "label": "", "lastSuccessAt": ""}
    return {
        "status": "working",
        "label": "Работи",
        "lastSuccessAt": str(record.get("last_success_at") or ""),
    }


def _address_view(entry: dict) -> str:
    """What the editor recognizes the source by: its feed, or what it watches.

    A direct feed shows its URL; a monitoring query shows the query, because that
    is what is actually being watched. Internal vocabulary (`collector`, `query`)
    is never exposed as its own field.
    """
    if entry.get("url"):
        return str(entry["url"])
    return str(entry.get("query") or "")


def _source_dto(entry: dict) -> dict:
    row = registry.describe(entry)
    return {
        "id": row["source_id"],
        "name": row["name"],
        "kind": row["kind"],
        "kindLabel": _label(row["kind"], KIND_LABELS, "Друг"),
        "domain": row.get("domain") or "",
        "address": _address_view(row),
        # §8. `monitored` is the *effective* status, so a mute whose window has
        # passed reads as monitored again without anything being rewritten.
        "monitored": row["effective_status"] == "active",
        "muteUntil": row.get("muted_until") or "" if row["effective_status"] == "muted" else "",
        # §6. The editor's own policy claim, named in editor language.
        "factualAuthority": bool(row.get("factual_authority")),
        "priority": row["priority"],
        "priorityLabel": _label(row["priority"], PRIORITY_LABELS, "Нормален"),
        "note": row.get("note") or "",
        "health": _health_view(row["source_id"]),
    }


def list_sources() -> dict:
    """The whole registry for the editor, plus the counts the header states."""
    try:
        rows = [_source_dto(entry) for entry in registry.describe_all(registry_path())]
    except registry.RegistryError as exc:
        raise _translate_registry_error(exc) from exc
    rows.sort(key=lambda row: (registry.PRIORITY_RANK.get(row["priority"], 9), row["name"]))
    return {
        "sources": rows,
        "summary": {
            "total": len(rows),
            "monitored": sum(1 for row in rows if row["monitored"]),
            "notMonitored": sum(1 for row in rows if not row["monitored"]),
            # §32: a count of rows the newsroom accepts as first-party, not a
            # score and not a ranking.
            "factualAuthority": sum(1 for row in rows if row["factualAuthority"]),
            "problems": sum(1 for row in rows if row["health"]["status"] == "problem"),
        },
    }



# ---------- validation, in editor language (§20) ----------


#: A Cyrillic name still has to become the registry's lowercase ASCII slug, so it
#: is transliterated rather than dropped. The editor never types an id (§9).
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y",
    "ю": "yu", "я": "ya",
}


def _slugify(name: str) -> str:
    """A stable, readable `source_id` derived from a Bulgarian name."""
    out = []
    for char in name.lower().strip():
        if char in _CYRILLIC:
            out.append(_CYRILLIC[char])
        elif char.isascii() and char.isalnum():
            out.append(char)
        else:
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")[:64]
    # The registry pattern needs two characters, and a name that transliterates
    # to nothing usable still needs a valid, deterministic id.
    if len(slug) < 2:
        slug = f"iztochnik-{hashlib.sha256(name.strip().encode('utf-8')).hexdigest()[:10]}"
    return slug


def _unique_source_id(base: str, taken) -> str:
    """§20: a duplicate id/domain configuration is refused by construction."""
    candidate, suffix = base, 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _clean_text(value, field: str, label: str, *, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SourceSettingsError(f"{label} трябва да е текст.", field=field)
    text = value.strip()
    if len(text) > maximum:
        raise SourceSettingsError(f"{label} е твърде дълго.", field=field)
    return text


def _require_name(value) -> str:
    name = _clean_text(value, "name", "Името", maximum=MAX_NAME)
    if not name:
        raise SourceSettingsError("Дайте име на източника.", field="name")
    return name


def _require_kind(value) -> str:
    kind = _clean_text(value, "kind", "Типът", maximum=40)
    if kind not in KIND_LABELS:
        raise SourceSettingsError("Изберете тип на източника.", field="kind")
    return kind


def _require_priority(value) -> str:
    priority = _clean_text(value, "priority", "Приоритетът", maximum=20)
    if priority not in PRIORITY_LABELS:
        raise SourceSettingsError("Изберете приоритет.", field="priority")
    return priority


def _require_flag(value, field: str, label: str) -> bool:
    """A strict boolean.

    A missing or loosely-typed value is refused rather than coerced: this is an
    editorial policy claim, so "absent" must never silently mean "yes" (§22).
    """
    if not isinstance(value, bool):
        raise SourceSettingsError(f"{label} трябва да е включен или изключен.", field=field)
    return value


def _resolve_address(raw: str, name: str) -> tuple[str, str, str]:
    """`(collector, url, query)` for a typed address, with safe defaults.

    A feed-looking http(s) URL is collected directly. A bare host, or an http(s)
    URL that is a page rather than a feed, is monitored through the existing
    publisher-constrained query mechanism built from the name — the same
    mechanism 33 of the 35 shipped rows use. No feed URL is ever guessed and no
    bespoke adapter is implied (§17).
    """
    text = raw.strip()
    if not text:
        return "google_news_rss", "", name
    if "://" in text:
        parts = urlsplit(text)
        if parts.scheme.lower() not in ("http", "https"):
            raise SourceSettingsError(
                "Адресът трябва да започне с http:// или https://.", field="address"
            )
        if not parts.hostname:
            raise SourceSettingsError("Адресът не е пълен.", field="address")
        path = parts.path.lower()
        looks_like_feed = path.endswith(_FEED_SUFFIXES) or any(
            hint in path for hint in _FEED_PATH_HINTS
        )
        if looks_like_feed:
            return "rss", text, ""
        return "google_news_rss", "", name
    try:
        blocked_domains.canonical_host(text)
    except blocked_domains.BlockedDomainError as exc:
        raise SourceSettingsError(f"Домейнът не е разпознат: {exc}", field="address") from exc
    return "google_news_rss", "", name


def _domain_for(address: str) -> str:
    """The declared publisher domain, when the typed address carries one."""
    if not address:
        return ""
    candidate = address if "://" in address else f"https://{address}"
    try:
        return blocked_domains.canonical_host(candidate)
    except blocked_domains.BlockedDomainError:
        # A feed URL with a path is a valid source but declares no bare domain.
        # The collector still treats the feed as its own publisher via its URL.
        return ""


def _translate_registry_error(exc: registry.RegistryError) -> SourceSettingsError:
    """A schema sentence becomes one an editor can act on (§20)."""
    text = str(exc)
    if "already exists" in text:
        return SourceSettingsError("Този източник вече е добавен.", field="name")
    if "name is required" in text:
        return SourceSettingsError("Дайте име на източника.", field="name")
    if "requires an http(s) url" in text or "requires a query" in text:
        return SourceSettingsError("Посочете адрес или име за търсене.", field="address")
    if "unknown source_id" in text:
        return SourceNotFound("Източникът не е намерен.", field="id")
    if "muted_until" in text:
        return SourceSettingsError(
            "Източникът е изключен временно до посочената дата.", field="id"
        )
    if "unknown source fields" in text or "fields not editable" in text:
        return SourceSettingsError("Тези полета не могат да се променят.", field="id")
    if "priority" in text:
        return SourceSettingsError("Изберете приоритет.", field="priority")
    if "domain is not a plain host" in text:
        return SourceSettingsError("Домейнът не е разпознат.", field="address")
    if "kind" in text or "collector" in text:
        return SourceSettingsError("Изберете тип на източника.", field="kind")
    if "factual_authority" in text:
        return SourceSettingsError(
            "Надеждността трябва да е включена или изключена.", field="factualAuthority"
        )
    if "source_id" in text:
        return SourceSettingsError(
            "Името не води до валиден адрес на източника.", field="name"
        )
    return SourceSettingsError("Промяната не може да се запише. Проверете данните.")


# ---------- mutations ----------


def _mutate(fn, *args, **kwargs):
    """Run one registry mutation under the process write lock (§27).

    The lock spans read → validate → write, so two concurrent editor actions can
    never read the same snapshot and lose one of the two changes. Durability is
    the existing `live_store.atomic_write` inside the registry's own setters.
    """
    with _WRITE_LOCK:
        try:
            return fn(registry_path(), *args, **kwargs)
        except registry.RegistryError as exc:
            raise _translate_registry_error(exc) from exc


def _require_existing(path, source_id: str) -> dict:
    """The row must exist; a missing id is a 404-shaped refusal, not a write."""
    current = registry.read_registry(path)
    if source_id not in current:
        raise SourceNotFound("Източникът не е намерен.", field="id")
    return current[source_id]


def add_source(*, name, address, kind, monitored, factual_authority, priority) -> dict:
    """`+ Добави източник` (§9). The editor types six things; the rest is derived.

    `source_id`, `collector`, `cadence` and the timestamps are all derived here,
    so the form never asks for a field the registry merely happens to store.
    """
    clean_name = _require_name(name)
    clean_kind = _require_kind(kind)
    clean_priority = _require_priority(priority)
    clean_address = _clean_text(address, "address", "Адресът", maximum=MAX_URL)
    monitored_flag = _require_flag(monitored, "monitored", "Следи се")
    authority_flag = _require_flag(factual_authority, "factualAuthority", "Надежден за факти")
    collector, url, query = _resolve_address(clean_address, clean_name)

    def run(path):
        existing = registry.read_registry(path)
        source_id = _unique_source_id(_slugify(clean_name), existing)
        return registry.add_source(
            path,
            source_id=source_id,
            name=clean_name,
            kind=clean_kind,
            domain=_domain_for(clean_address),
            collector=collector,
            url=url,
            query=query,
            status="active" if monitored_flag else "disabled",
            priority=clean_priority,
            factual_authority=authority_flag,
        )

    return _source_dto(_mutate(run))


def set_monitored(source_id: str, monitored: bool) -> dict:
    """`Следи се` (§8). This is the registry's own active/disabled status.

    Disabling stops normal collection through the existing collector behaviour
    and changes nothing else: the row stays in the registry, and no Publication,
    inbox item or Article is touched, so the source remains historically
    identifiable (§8, §32).
    """
    if not isinstance(monitored, bool):
        raise SourceSettingsError("Следи се трябва да е включен или изключен.", field="monitored")

    def run(path):
        _require_existing(path, source_id)
        return registry.set_status(source_id, "active" if monitored else "disabled", path=path)

    return _source_dto(_mutate(run))


def set_factual_authority(source_id: str, factual_authority: bool) -> dict:
    """`Надежден за факти` (§6, §7).

    This is the newsroom's own claim-appropriateness policy: the publisher is
    accepted as PRIMARY for information from its own competence. It does not say
    everything on that site is true, and ordinary media keeps needing
    corroboration. Only an explicit editor value reaches the registry — no
    default, no inference, and no model input (§22).
    """
    if not isinstance(factual_authority, bool):
        raise SourceSettingsError(
            "Надежден за факти трябва да е включен или изключен.", field="factualAuthority"
        )

    def run(path):
        _require_existing(path, source_id)
        return registry.set_factual_authority(source_id, factual_authority, path=path)

    return _source_dto(_mutate(run))


def set_priority(source_id: str, priority: str) -> dict:
    """`Приоритет` (§13). The existing registry value, exposed in words only."""
    clean = _require_priority(priority)

    def run(path):
        _require_existing(path, source_id)
        return registry.set_priority(source_id, clean, path=path)

    return _source_dto(_mutate(run))


def rename_source(source_id: str, name: str) -> dict:
    """A display-name change. `source_id` is never editable, so history is safe."""

    def run(path):
        _require_existing(path, source_id)
        return registry.update_source(source_id, path=path, name=_require_name(name))

    return _source_dto(_mutate(run))


#: §10. The fields a row may be changed on after creation. `source_id` is the key
#: and is never editable, so existing evidence and inbox rows keep pointing at
#: the same source; the address belongs to the collector, so it is derived on add
#: and never edited independently either.
EDITABLE_FIELDS = ("name", "monitored", "factualAuthority", "priority")


def update_source(source_id: str, changes: dict) -> dict:
    """`Редактирай` (§10) — a small inline editor over one canonical row.

    Each field is applied through the registry's own setter rather than a merged
    rewrite, so every one keeps the registry's validation and its `updated_at`
    stamp, and no other field can be reached by passing an extra key.
    """
    unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
    if unknown:
        raise SourceSettingsError("Тези полета не могат да се променят.", field="id")
    if not changes:
        raise SourceSettingsError("Няма какво да се промени.", field="id")
    if "name" in changes:
        result = rename_source(source_id, _require_name(changes["name"]))
    else:
        result = _read_one(source_id)
    if "priority" in changes:
        result = set_priority(source_id, changes["priority"])
    if "factualAuthority" in changes:
        result = set_factual_authority(
            source_id,
            _require_flag(changes["factualAuthority"], "factualAuthority", "Надежден за факти"),
        )
    if "monitored" in changes:
        result = set_monitored(
            source_id, _require_flag(changes["monitored"], "monitored", "Следи се")
        )
    return result


def _read_one(source_id: str) -> dict:
    """The current DTO for one row, without mutating anything."""
    path = registry_path()
    _require_existing(path, source_id)
    return _source_dto(registry.read_registry(path)[source_id])

