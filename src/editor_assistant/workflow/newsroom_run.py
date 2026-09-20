"""M4A collection runner: SOURCE -> normalized INBOX ITEM, and stop.

One-shot process, no daemon: the operator's cron calls it (identical rule to
`youtube-batch run --cron`). It reads the editor-owned registry and writes the
inbox; it is the only place where a registry entry becomes collected material.

**Not in this milestone** (deliberately): AI angle generation, research, drafting,
story identity (`NEW_DEVELOPMENT` / `DUPLICATE`) and alerts. Those are M4B/M4C/M4D.
An inbox item is a *candidate*, never evidence.

Two hard rules:

* `--dry-run` performs **zero network calls** and prints exactly what a real run
  would do (sources, collectors, estimated network calls);
* **one broken source never stops the run**: its status is reported in the summary
  (`OK` / `FAILED` / `UNSUPPORTED`) and the remaining sources still run.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from editor_assistant.models import SourceDef
from editor_assistant.sources.html_desc import normalize_description
from editor_assistant.sources.rss import PARSER_ID, item_to_dict, parse_datetime, parse_rss_feed
from editor_assistant.workflow import inbox_store, sources_registry

#: Collectors wired in M4A. `youtube` and `web` are declared in the registry (a
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
STATUS_FAILED = "FAILED"
STATUS_UNSUPPORTED = "UNSUPPORTED"
STATUS_PLANNED = "PLANNED"


class CollectionError(RuntimeError):
    """A collector could not produce candidates for a source."""


def _now():
    return datetime.now(timezone.utc)


def _selected_sources(path=None, *, today=None, source_ids=None, limit=None):
    sources = sources_registry.collectable(path, today=today)
    if source_ids:
        wanted = set(source_ids)
        sources = [s for s in sources if s["source_id"] in wanted]
    if limit is not None:
        sources = sources[: max(int(limit), 0)]
    return sources


def plan(path=None, *, today=None, source_ids=None, limit=None):
    """What a run would do, with no network and no side effects."""
    sources = _selected_sources(path, today=today, source_ids=source_ids, limit=limit)
    by_collector = Counter(s["collector"] for s in sources)
    unsupported = [s["source_id"] for s in sources if s["collector"] not in SUPPORTED_COLLECTORS]
    supported = [s for s in sources if s["collector"] in SUPPORTED_COLLECTORS]
    return {
        "sources": sources,
        "by_collector": dict(sorted(by_collector.items())),
        "unsupported": unsupported,
        # One request per source is the honest estimate for both wired collectors
        # (one feed fetch / one query). Nothing is padded to look impressive.
        "estimated_network_calls": len(supported),
    }


# ---------- collector adapters (the only network in M4A) ----------


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

    record = provider.search(entry["query"], count=20)
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
            }
        )
    return out


def _to_inbox_item(entry, candidate, discovered_at):
    """Raw candidate -> the M4A inbox row shape (candidate, never evidence)."""
    return {
        "source_id": entry["source_id"],
        "source_item_id": candidate.get("source_item_id") or candidate.get("url") or "",
        "title": candidate.get("title") or "",
        "url": candidate.get("url") or "",
        "published_at": candidate.get("published_at") or "",
        "discovered_at": discovered_at,
        "summary": candidate.get("snippet") or "",
        "source_kind": entry["kind"],
        "priority": entry["priority"],
        "status": "NEW",
    }


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
):
    """Run the collectors once. `dry_run=True` makes no network call at all."""
    run_plan = plan(path, today=today, source_ids=source_ids, limit=limit)
    started = now()
    results = []
    collected = []

    if not dry_run:
        if fetch_bytes is None:
            from editor_assistant.sources.fetcher import fetch_bytes as _fetch

            fetch_bytes = _fetch
        if news_provider is None:
            from editor_assistant.workflow.search import GoogleNewsRSSProvider

            news_provider = GoogleNewsRSSProvider()

    for entry in run_plan["sources"]:
        entry_result = {
            "source_id": entry["source_id"],
            "collector": entry["collector"],
            "status": STATUS_PLANNED,
            "items": 0,
            "skipped_invalid": 0,
            "reason": "",
        }
        if entry["collector"] not in SUPPORTED_COLLECTORS:
            entry_result["status"] = STATUS_UNSUPPORTED
            entry_result["reason"] = f"collector={entry['collector']} is not wired yet"
            results.append(entry_result)
            continue
        if dry_run:
            results.append(entry_result)
            continue
        try:
            if entry["collector"] == "rss":
                candidates = _collect_rss(entry, fetch_bytes=fetch_bytes, now=now)
            else:
                candidates = _collect_google_news(entry, provider=news_provider, now=now)
        except Exception as exc:  # noqa: BLE001 - one source must never stop the run
            entry_result["status"] = STATUS_FAILED
            entry_result["reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            results.append(entry_result)
            continue

        discovered_at = now().strftime("%Y-%m-%dT%H:%M:%SZ")
        for candidate in candidates:
            item = _to_inbox_item(entry, candidate, discovered_at)
            try:
                inbox_store.validate_item(item)
            except inbox_store.InboxError:
                # A single malformed candidate is counted, never fatal.
                entry_result["skipped_invalid"] += 1
                continue
            collected.append(item)
        entry_result["status"] = STATUS_OK
        entry_result["items"] = len(candidates) - entry_result["skipped_invalid"]
        results.append(entry_result)

    added = {"new": 0, "duplicate": 0}
    if not dry_run and collected:
        added = inbox_store.add_items(collected, store)

    finished = now()
    return {
        "dry_run": dry_run,
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": results,
        "by_collector": run_plan["by_collector"],
        "estimated_network_calls": run_plan["estimated_network_calls"],
        "network_calls": 0 if dry_run else run_plan["estimated_network_calls"],
        "collected": len(collected),
        "new": added["new"],
        "duplicate": added["duplicate"],
        "failed": sum(1 for r in results if r["status"] == STATUS_FAILED),
        "unsupported": sum(1 for r in results if r["status"] == STATUS_UNSUPPORTED),
        "skipped_invalid": sum(r["skipped_invalid"] for r in results),
    }


def render_summary(summary):
    """Human-readable run summary (the operator reads this in the cron output)."""
    lines = []
    mode = "ПРОБЕН (без мрежа)" if summary["dry_run"] else "СЪБИРАНЕ"
    lines.append(
        f"{mode}: {len(summary['sources'])} източника · "
        f"очаквани мрежови заявки: {summary['estimated_network_calls']}"
    )
    for collector, count in summary["by_collector"].items():
        lines.append(f"  · {COLLECTOR_LABELS.get(collector, collector)}: {count}")
    for row in summary["sources"]:
        detail = f"{row['items']} елемента"
        if row["skipped_invalid"]:
            detail += f", {row['skipped_invalid']} пропуснати"
        if row["reason"]:
            detail += f" — {row['reason']}"
        lines.append(f"  {row['source_id']}: {row['status']} ({detail})")
    if summary["dry_run"]:
        lines.append("Нищо не е събрано и нищо не е записано (--dry-run).")
    else:
        lines.append(
            f"Събрани: {summary['collected']} · нови в входящите: {summary['new']} · "
            f"вече известни: {summary['duplicate']} · невалидни: {summary['skipped_invalid']} · "
            f"грешки: {summary['failed']} · неподдържани: {summary['unsupported']}"
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
