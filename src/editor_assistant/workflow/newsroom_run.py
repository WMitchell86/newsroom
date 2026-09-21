"""M4A.1 collection runner: SOURCE -> normalized INBOX ITEM, and stop.

One-shot process, no daemon: the operator's cron calls it (identical rule to
`youtube-batch run --cron`). It reads the editor-owned registry and writes the
inbox; it is the only place where a registry entry becomes collected material.

**Not in this milestone** (deliberately): AI angle generation, research, drafting,
story identity (`NEW_DEVELOPMENT` / `DUPLICATE`), ranking and alerts. Those are
M4B/M4C/M4D. An inbox item is a *candidate*, never evidence.

Hard rules:

* `--dry-run` performs **zero network calls** and prints exactly what a real run
  would do (sources, collectors, cadence, estimated network calls);
* **one broken source never stops the run**: its status is reported in the summary
  (`OK` / `EMPTY` / `FAILED` / `UNSUPPORTED` / `BLOCKED`) and the remaining
  sources still run;
* **cadence is operational**: an `each_run` source is always due, a `daily` source
  only if it has not succeeded on the current `Europe/Sofia` date (weekly: 7 local
  days), and a muted/disabled source is never due;
* **blocked domains** are filtered before an item can reach the inbox, and a
  source whose own URL/query targets a blocked domain is refused;
* **rolling recency**: every run keeps only dated news items from the last 72 h
  (M4B.1 F1) — the bootstrap run additionally caps to the 10 newest, so the older
  results the first run excluded cannot come back as "new" on the second;
* **honest calendar semantics**: a ±45-day event window is applied only when the
  collector genuinely supplies `event_at`/`event_end_at`; otherwise a calendar
  source is treated as ordinary news (an article's publication time is not an
  event date) (M4B.1 F2);
* **one shared lock** so two concurrent runs (cron + the Workbench button) cannot
  interleave writes into the inbox or the health store.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from editor_assistant.models import SourceDef
from editor_assistant.sources.html_desc import normalize_description
from editor_assistant.sources.rss import PARSER_ID, item_to_dict, parse_datetime, parse_rss_feed
from editor_assistant.workflow import blocked_domains, inbox_store, source_health, sources_registry

ROOT = Path(__file__).resolve().parents[3]

#: Collectors wired today. `youtube` and `web` are declared in the registry (a
#: source keeps its collector across slices) but reported as UNSUPPORTED here
#: rather than silently skipped.
SUPPORTED_COLLECTORS = ("rss", "google_news_rss")

COLLECTOR_LABELS = {
    "rss": "RSS емисия",
    "google_news_rss": "търсене в Google News",
    "youtube": "YouTube (още не е включено в събирането)",
    "web": "уеб страница (още не е включено в събирането)",
}

STATUS_OK = "OK"
STATUS_EMPTY = "EMPTY"
STATUS_FAILED = "FAILED"
STATUS_UNSUPPORTED = "UNSUPPORTED"
STATUS_BLOCKED = "BLOCKED"
STATUS_PLANNED = "PLANNED"

#: Safe-bootstrap windows and per-source caps (M4A.1 §3/§9).
NEWS_LOOKBACK_HOURS = 72
CALENDAR_WINDOW_DAYS = 45
BOOTSTRAP_MAX_NEWS = 10
MAX_ITEMS_PER_SOURCE = 20

LOCK_NAME = "collect.lock"
LOCK_STALE_SECONDS = 3600


class CollectionError(RuntimeError):
    """A collector could not produce candidates for a source."""


def newsroom_dir(root=None):
    """Runtime dir; overridable for tests (`NEWSROOM_DIR`)."""
    if root is not None:
        return Path(root)
    override = os.environ.get("NEWSROOM_DIR")
    return Path(override) if override else ROOT / "var" / "newsroom"


def lock_path(root=None):
    return newsroom_dir(root) / LOCK_NAME


# ---------------------------------------------------------------- lock


def acquire_lock(*, root=None, stale_after_s=LOCK_STALE_SECONDS, pid=None, clock=None):
    """Take the collection lock; a stale lock is taken over once (see `intake_run`)."""
    path = lock_path(root)
    now = time.time() if clock is None else clock
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps({"pid": pid or os.getpid(), "started_at": _now().strftime("%Y-%m-%dT%H:%M:%SZ")})
        + "\n"
    )
    for takeover_attempt in (False, True):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                age = now - path.stat().st_mtime
            except OSError:
                age = 0
            if takeover_attempt or age < stale_after_s:
                return False
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return True
    return False  # pragma: no cover - the loop always returns above


def release_lock(root=None):
    lock_path(root).unlink(missing_ok=True)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- planning


def due_for(entry, record, today, *, force=False):
    """(is_due, reason) for one active source, based on real operational state."""
    if force:
        return True, ""
    cadence = entry.get("cadence") or "each_run"
    if cadence == "each_run":
        return True, ""
    last = source_health.sofia_date_of((record or {}).get("last_success_at"))
    if last is None:
        return True, ""
    if cadence == "daily":
        return (last < today), "cadence_skipped"
    if cadence == "weekly":
        return ((today - last).days >= 7), "cadence_skipped"
    return True, ""


def plan(
    path=None,
    *,
    today=None,
    source_ids=None,
    limit=None,
    health_path=None,
    force=False,
    now=None,
):
    """What a run would do, with no network and no side effects.

    `sources` stays the list the runner will actually work (due + selected +
    limited), so callers keep a single source of truth. `excluded` explains who
    was left out and why (`cadence`, `muted`, `disabled`) — the dry-run report the
    operator reads.
    """
    moment = now or _now()
    local_today = today or source_health.sofia_date(moment)
    health = source_health.read_health(health_path)
    all_rows = sources_registry.describe_all(path, today=local_today)
    active = [e for e in all_rows if e["effective_status"] == "active"]
    active.sort(
        key=lambda e: (sources_registry.PRIORITY_RANK.get(e["priority"], 9), e["source_id"])
    )

    excluded = {"cadence": [], "muted": [], "disabled": []}
    due = []
    for entry in all_rows:
        status = entry["effective_status"]
        if status in ("muted", "disabled"):
            excluded[status].append(entry["source_id"])
    for entry in active:
        is_due, _reason = due_for(entry, health.get(entry["source_id"]), local_today, force=force)
        if is_due:
            due.append(entry)
        else:
            excluded["cadence"].append(entry["source_id"])

    if source_ids:
        wanted = set(source_ids)
        due = [s for s in due if s["source_id"] in wanted]
    if limit is not None:
        due = due[: max(int(limit), 0)]

    by_collector = Counter(s["collector"] for s in due)
    supported = [s for s in due if s["collector"] in SUPPORTED_COLLECTORS]
    return {
        "sources": due,
        "by_collector": dict(sorted(by_collector.items())),
        "unsupported": [s["source_id"] for s in due if s["collector"] not in SUPPORTED_COLLECTORS],
        "excluded": excluded,
        "today": local_today.isoformat(),
        "force": bool(force),
        # One request per source is the honest estimate for both wired collectors
        # (one feed fetch / one query). Nothing is padded to look impressive.
        "estimated_network_calls": len(supported),
    }


# ---------------------------------------------------------------- collector adapters


def _collect_rss(entry, *, fetch_bytes, now):
    """One feed fetch + the existing RSS parser. No new schema."""
    response = fetch_bytes(entry["url"])
    source = SourceDef(source_id=entry["source_id"], canonical_url=entry["url"], parser=PARSER_ID)
    items = parse_rss_feed(response.payload, source=source, fetched_at=now())
    return [
        {
            "url": row["item_url"],
            "title": row["title"],
            "snippet": row.get("body_text") or "",
            "published_at": row.get("published_at") or "",
            "source_item_id": row["item_url"],
        }
        for row in (item_to_dict(item) for item in items)
    ]


def _collect_google_news(entry, *, provider, now):
    """One query through the adopted News RSS provider (DISCOVERY_ONLY results)."""
    from editor_assistant.workflow import search as search_mod

    record = provider.search(entry["query"], count=MAX_ITEMS_PER_SOURCE)
    status = record.get("status")
    if status not in (search_mod.SEARCH_OK, search_mod.NO_RESULTS):
        raise CollectionError(
            f"google_news_rss: {status}"
            + (f" ({record.get('error')})" if record.get("error") else "")
        )
    out = []
    for row in record.get("results") or []:
        published = parse_datetime(row.get("published_at"))
        # Google News descriptions are HTML (`<a href=...>…</a><font>Source</font>`).
        # Normalize with the SAME frozen parser the RSS path uses, so the inbox
        # never shows markup (escaped or otherwise) and the text stays readable.
        snippet, _links = normalize_description(
            row.get("snippet") or "", base_url=row.get("url") or ""
        )
        out.append(
            {
                "url": row.get("url") or "",
                "title": row.get("title") or "",
                "snippet": snippet or "",
                "published_at": published.isoformat() if published else "",
                "source_item_id": row.get("url") or row.get("title") or "",
                # Google News wraps the publisher link, so the publisher domain is
                # the only reliable input for the blocked-domain policy.
                "source_url": row.get("source_url") or "",
            }
        )
    return out


# ---------------------------------------------------------------- safe bootstrap


def _published_at(value):
    return source_health.parse_timestamp(value)


def _event_moment(candidate):
    """A **real** event date supplied by the collector, never a publication time."""
    return _published_at(candidate.get("event_at")) or _published_at(candidate.get("event_end_at"))


def _within(moment, floor, horizon):
    # An unreadable date is kept: a source must not be emptied merely because a
    # collector omitted a timestamp.
    return True if moment is None else floor <= moment <= horizon


def select_candidates(entry, candidates, *, bootstrap, now):
    """Apply the recency window, the bootstrap cap and the per-source cap.

    Returns `(kept, dropped)`; order is preserved (newest-first is the feed's /
    provider's order, not ours to invent).

    Two rules, deliberately separate (M4B.1 F1/F2):

    * **news recency runs on every run** — a dated item older than
      `NEWS_LOOKBACK_HOURS` is excluded on run 1 *and* run 2, so a second
      immediate run cannot backfill what the first deliberately dropped;
    * **event window only with a real event date** — a `calendar=True` source uses
      the ±`CALENDAR_WINDOW_DAYS` window only when at least one candidate carries
      `event_at`/`event_end_at`. A calendar whose collector only knows the
      article's publication time is treated as ordinary news (an article's
      `published_at` is not the date the event happens).
    """
    kept = list(candidates)
    calendar_window = None
    if entry.get("calendar") and any(_event_moment(c) is not None for c in kept):
        calendar_window = (
            now - timedelta(days=CALENDAR_WINDOW_DAYS),
            now + timedelta(days=CALENDAR_WINDOW_DAYS),
        )
    if calendar_window is not None:
        floor, horizon = calendar_window
        kept = [c for c in kept if _within(_event_moment(c), floor, horizon)]
    else:
        # News recency is a floor only: a slightly future timestamp (clock skew on
        # the publisher's side) must not make a fresh item disappear.
        news_floor = now - timedelta(hours=NEWS_LOOKBACK_HOURS)
        kept = [
            c
            for c in kept
            if (moment := _published_at(c.get("published_at"))) is None or moment >= news_floor
        ]
    if bootstrap:
        # First successful run of a source: never backfill history with more than
        # the newest few items. Subsequent runs keep the normal per-source cap.
        kept = kept[:BOOTSTRAP_MAX_NEWS]
    dropped = len(candidates) - len(kept)
    kept = kept[:MAX_ITEMS_PER_SOURCE]
    dropped = len(candidates) - len(kept)
    return kept, dropped


def authority_by_domain(path=None, *, today=None):
    """Publisher domain -> registry row: the *real publisher's* authority policy.

    Built from every registry entry's declared `domain` plus the host of its own
    `url` (so a direct feed is its own publisher without any extra configuration).

    **Fail closed on conflict (M4B.1 F5).** Two registry entries for the same
    canonical publisher domain are allowed only when they agree on `kind` and
    `factual_authority`; a differing policy raises `RegistryError` instead of
    letting the alphabetically-first `source_id` decide who has authority.
    """
    out = {}
    for row in sources_registry.describe_all(path, today=today):
        for domain in (row.get("domain") or "", blocked_domains.host_of(row.get("url")) or ""):
            if not domain:
                continue
            known = out.get(domain)
            if known is None:
                out[domain] = row
                continue
            if known["kind"] != row["kind"] or bool(known["factual_authority"]) != bool(
                row["factual_authority"]
            ):
                raise sources_registry.RegistryError(
                    f"conflicting publisher policy for {domain}: "
                    f"{known['source_id']} (kind={known['kind']}, "
                    f"factual_authority={bool(known['factual_authority'])}) vs "
                    f"{row['source_id']} (kind={row['kind']}, "
                    f"factual_authority={bool(row['factual_authority'])}) — "
                    "fix the registry; authority must never be decided by source order"
                )
    return out


def publisher_domain(candidate):
    """The real publisher of one candidate (never the discovery definition).

    Google News results carry the publisher on `source_url` because their `url` is
    an opaque `news.google.com` redirect; a direct feed's item link already lives
    on the publisher's own host.
    """
    return (
        blocked_domains.host_of(candidate.get("source_url"))
        or blocked_domains.host_of(candidate.get("url"))
        or ""
    )


def resolve_authority(candidate, registry_by_domain):
    """Publisher identity + authority for one candidate.

    Strict rule (M4A.1 correction): an item inherits authority from whoever
    **published** it, never from the monitoring definition that surfaced it. An
    unknown or unapproved publisher is monitoring-only — a query that merely
    mentions an institution must not lend that institution's authority to a
    third-party article.
    """
    domain = publisher_domain(candidate)
    match = registry_by_domain.get(domain) if domain else None
    if match is None and domain:
        for known, row in registry_by_domain.items():
            if domain.endswith("." + known):
                match = row
                break
    if match is None:
        return {"publisher_domain": domain, "publisher_kind": "", "factual_authority": False}
    return {
        "publisher_domain": domain,
        "publisher_kind": match["kind"],
        "factual_authority": bool(match["factual_authority"]),
    }


def _to_inbox_item(entry, candidate, discovered_at, authority=None):
    """Raw candidate -> the inbox row shape (candidate, never evidence).

    `source_id`/`source_kind` describe **how the item was discovered**;
    `publisher_domain`/`publisher_kind`/`factual_authority` describe **who
    published it**. The two are deliberately separate fields.
    """
    authority = authority or {
        "publisher_domain": publisher_domain(candidate),
        "publisher_kind": "",
        "factual_authority": False,
    }
    return {
        "source_id": entry["source_id"],
        "source_item_id": candidate.get("source_item_id") or candidate.get("url") or "",
        "title": candidate.get("title") or "",
        "url": candidate.get("url") or "",
        "published_at": candidate.get("published_at") or "",
        # Only a collector that genuinely knows the event date supplies these
        # (M4B.1 F2); they stay empty for every wired collector today.
        "event_at": candidate.get("event_at") or "",
        "event_end_at": candidate.get("event_end_at") or "",
        "discovered_at": discovered_at,
        "summary": candidate.get("snippet") or "",
        "source_kind": entry["kind"],
        "priority": entry["priority"],
        "publisher_domain": authority["publisher_domain"],
        "publisher_kind": authority["publisher_kind"],
        "factual_authority": authority["factual_authority"],
        "status": "NEW",
    }


# ---------------------------------------------------------------- run


def collect(
    *,
    dry_run=True,
    path=None,
    store=None,
    source_ids=None,
    limit=None,
    today=None,
    fetch_bytes=None,
    news_provider=None,
    now=_now,
    force=False,
    health_path=None,
    blocked_path=None,
    last_run_path=None,
    root=None,
    use_lock=True,
):
    """Run the collectors once. `dry_run=True` makes no network call and no write."""
    started = now()
    run_plan = plan(
        path,
        today=today,
        source_ids=source_ids,
        limit=limit,
        health_path=health_path,
        force=force,
        now=started,
    )
    summary_stub = {
        "dry_run": dry_run,
        "locked": False,
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": "",
        "sources": [],
        "by_collector": run_plan["by_collector"],
        "estimated_network_calls": run_plan["estimated_network_calls"],
        "network_calls": 0,
        "collected": 0,
        "new": 0,
        "duplicate": 0,
        "failed": 0,
        "unsupported": 0,
        "skipped_invalid": 0,
        "blocked": 0,
        "blocked_filtered": 0,
        "cadence_skipped": len(run_plan["excluded"]["cadence"]),
        "bootstrap_capped": 0,
        "excluded": run_plan["excluded"],
    }

    if dry_run:
        results = []
        for entry in run_plan["sources"]:
            reason = blocked_domains.blocked_reason(entry, path=blocked_path)
            if reason:
                results.append(_entry_result(entry, STATUS_BLOCKED, reason=reason))
            elif entry["collector"] not in SUPPORTED_COLLECTORS:
                results.append(
                    _entry_result(
                        entry,
                        STATUS_UNSUPPORTED,
                        reason=f"collector={entry['collector']} is not wired yet",
                    )
                )
            else:
                results.append(_entry_result(entry, STATUS_PLANNED))
        summary_stub["sources"] = results
        summary_stub["failed"] = sum(1 for r in results if r["status"] == STATUS_FAILED)
        summary_stub["unsupported"] = sum(1 for r in results if r["status"] == STATUS_UNSUPPORTED)
        summary_stub["blocked"] = sum(1 for r in results if r["status"] == STATUS_BLOCKED)
        summary_stub["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%SZ")
        return summary_stub

    if fetch_bytes is None:
        from editor_assistant.sources.fetcher import fetch_bytes as _fetch

        fetch_bytes = _fetch
    if news_provider is None:
        from editor_assistant.workflow.search import GoogleNewsRSSProvider

        news_provider = GoogleNewsRSSProvider()

    if use_lock and not acquire_lock(root=root):
        summary_stub["locked"] = True
        summary_stub["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%SZ")
        return summary_stub

    try:
        health = source_health.read_health(health_path)
        policy = blocked_domains.effective_domains(blocked_path)
        registry_by_domain = authority_by_domain(path, today=None)
        existing_ids = {item["item_id"] for item in inbox_store.read_items(store)}
        results = []
        collected = []
        new_by_source = Counter()
        blocked_filtered_total = 0
        bootstrap_capped = 0

        for entry in run_plan["sources"]:
            source_id = entry["source_id"]
            entry_result = _entry_result(entry, STATUS_PLANNED)
            refusal = blocked_domains.blocked_reason(entry, path=blocked_path)
            if refusal:
                entry_result["status"] = STATUS_BLOCKED
                entry_result["reason"] = refusal
                results.append(entry_result)
                continue
            if entry["collector"] not in SUPPORTED_COLLECTORS:
                entry_result["status"] = STATUS_UNSUPPORTED
                entry_result["reason"] = f"collector={entry['collector']} is not wired yet"
                results.append(entry_result)
                continue

            try:
                if entry["collector"] == "rss":
                    candidates = _collect_rss(entry, fetch_bytes=fetch_bytes, now=now)
                else:
                    candidates = _collect_google_news(entry, provider=news_provider, now=now)
            except Exception as exc:  # noqa: BLE001 - one source must never stop the run
                reason = f"{type(exc).__name__}: {str(exc)[:200]}"
                entry_result["status"] = STATUS_FAILED
                entry_result["reason"] = reason
                _record_health(
                    source_id,
                    STATUS_FAILED,
                    error=reason,
                    success=False,
                    now=now,
                    health_path=health_path,
                )
                results.append(entry_result)
                continue

            bootstrap = not (health.get(source_id) or {}).get("last_success_at")
            kept, dropped = select_candidates(entry, candidates, bootstrap=bootstrap, now=now())
            bootstrap_capped += dropped if bootstrap else 0

            discovered_at = now().strftime("%Y-%m-%dT%H:%M:%SZ")
            kept_for_inbox = []
            for candidate in kept:
                if policy and (
                    blocked_domains.is_blocked(candidate.get("url"), policy)
                    or blocked_domains.is_blocked(candidate.get("source_url"), policy)
                ):
                    entry_result["blocked_filtered"] += 1
                    blocked_filtered_total += 1
                    continue
                item = _to_inbox_item(
                    entry,
                    candidate,
                    discovered_at,
                    resolve_authority(candidate, registry_by_domain),
                )
                try:
                    normalized = inbox_store.validate_item(item)
                except inbox_store.InboxError:
                    # A single malformed candidate is counted, never fatal.
                    entry_result["skipped_invalid"] += 1
                    continue
                kept_for_inbox.append(normalized)

            for item in kept_for_inbox:
                if item["item_id"] not in existing_ids:
                    new_by_source[source_id] += 1
                    existing_ids.add(item["item_id"])
            collected.extend(kept_for_inbox)
            entry_result["items"] = len(kept_for_inbox)
            entry_result["status"] = STATUS_OK if kept_for_inbox else STATUS_EMPTY
            _record_health(
                source_id,
                entry_result["status"],
                item_count=len(kept_for_inbox),
                new_count=new_by_source[source_id],
                error="",
                success=True,
                now=now,
                health_path=health_path,
            )
            results.append(entry_result)

        added = {"new": 0, "duplicate": 0}
        if collected:
            added = inbox_store.add_items(collected, store)

        finished = now()
        summary = {
            **summary_stub,
            "finished_at": finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": results,
            "collected": len(collected),
            "new": added["new"],
            "duplicate": added["duplicate"],
            "failed": sum(1 for r in results if r["status"] == STATUS_FAILED),
            "unsupported": sum(1 for r in results if r["status"] == STATUS_UNSUPPORTED),
            "blocked": sum(1 for r in results if r["status"] == STATUS_BLOCKED),
            "skipped_invalid": sum(r["skipped_invalid"] for r in results),
            "blocked_filtered": blocked_filtered_total,
            "bootstrap_capped": bootstrap_capped,
        }
        source_health.record_run(summary, path=last_run_path)
        return summary
    finally:
        if use_lock:
            release_lock(root)


def _entry_result(entry, status, *, reason=""):
    return {
        "source_id": entry["source_id"],
        "collector": entry["collector"],
        "status": status,
        "items": 0,
        "skipped_invalid": 0,
        "blocked_filtered": 0,
        "reason": reason,
    }


def _record_health(
    source_id, status, *, item_count=0, new_count=0, error="", success, now, health_path
):
    source_health.record_source(
        source_id,
        status=status,
        item_count=item_count,
        new_count=new_count,
        error=error,
        success=success,
        now=now(),
        path=health_path,
    )


# ---------------------------------------------------------------- reporting


def render_summary(summary):
    """Human-readable run summary (the operator reads this in the cron output)."""
    lines = []
    mode = "ПРОБЕН (без мрежа)" if summary["dry_run"] else "СЪБИРАНЕ"
    if summary.get("locked"):
        lines.append("СЪБИРАНЕТО Е ПРОПУСНАТО: друг процес държи заключването.")
        return "\n".join(lines)
    lines.append(
        f"{mode}: {len(summary['sources'])} източника · "
        f"очаквани мрежови заявки: {summary['estimated_network_calls']}"
    )
    for collector, count in summary["by_collector"].items():
        lines.append(f"  · {COLLECTOR_LABELS.get(collector, collector)}: {count}")
    excluded = summary.get("excluded") or {}
    if any(excluded.get(k) for k in ("cadence", "muted", "disabled")):
        detail = []
        if excluded.get("cadence"):
            detail.append(f"по ритъм: {len(excluded['cadence'])}")
        if excluded.get("muted"):
            detail.append(f"заглушени: {len(excluded['muted'])}")
        if excluded.get("disabled"):
            detail.append(f"изключени: {len(excluded['disabled'])}")
        lines.append("  изключени — " + " · ".join(detail))
    for row in summary["sources"]:
        detail = f"{row['items']} елемента"
        if row["skipped_invalid"]:
            detail += f", {row['skipped_invalid']} пропуснати"
        if row.get("blocked_filtered"):
            detail += f", {row['blocked_filtered']} от забранени домейни"
        if row["reason"]:
            detail += f" — {row['reason']}"
        lines.append(f"  {row['source_id']}: {row['status']} ({detail})")
    if summary["dry_run"]:
        lines.append("Нищо не е събрано и нищо не е записано (--dry-run).")
    else:
        lines.append(
            f"Събрани: {summary['collected']} · нови във входящите: {summary['new']} · "
            f"вече известни: {summary['duplicate']} · невалидни: {summary['skipped_invalid']} · "
            f"грешки: {summary['failed']} · неподдържани: {summary['unsupported']} · "
            f"забранени: {summary.get('blocked', 0)} · "
            f"филтрирани по домейн: {summary.get('blocked_filtered', 0)} · "
            f"пропуснати по ритъм: {summary.get('cadence_skipped', 0)}"
        )
    return "\n".join(lines)


def print_summary(summary):
    print(render_summary(summary))


def inbox_view(store=None, path=None, *, limit=None):
    """Read-only view for the Workbench (`path` = registry, `store` = inbox file)."""
    items = inbox_store.read_items(store)
    counts = inbox_store.counts(store)
    registry = {entry["source_id"]: entry for entry in sources_registry.describe_all(path)}
    for item in items:
        entry = registry.get(item["source_id"]) or {}
        item["source_name"] = entry.get("name") or item["source_id"]
    if limit is not None:
        items = items[: max(int(limit), 0)]
    return {"items": items, "counts": counts}
