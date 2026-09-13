"""M1.6 manual poll cycle — one explicit operator-triggered ingestion run.

Pipeline (existing components only, no duplication):

    LIVE_FEED_URL -> fetch_bytes -> parse_rss_feed
    -> process_items(destination="telegram-test")
    -> operator report -> STOP

Read-only externally except local SQLite state/outbox. Never calls
Telegram/WordPress/webhooks/email. No loop, daemon, scheduler, send flag.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.sources.fetcher import FetchError, fetch_bytes
from editor_assistant.sources.live import BURGAS_MUNICIPAL_COUNCIL, LIVE_FEED_URL
from editor_assistant.sources.rss import SourceParseError, parse_rss_feed
from editor_assistant.state.fingerprint import StateError
from editor_assistant.state.store import (
    DEFAULT_DB_PATH,
    TELEGRAM_TEST_DESTINATION,
    ItemStatus,
    process_items,
)

_EMPTY_FEED_MARKER = "contains no <item>"

STATUS_OK = "OK"
STATUS_ERROR = "ERROR"


@dataclass(frozen=True)
class PollReport:
    source_id: str
    feed_url: str
    fetched: int
    parsed: int
    new_count: int
    updated_count: int
    unchanged_count: int
    new_outbox_intents: int
    pending_total: int
    status: str
    error: str | None = None
    new_items: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    updated_items: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _pending_total(db_path: str | Path) -> int:
    from editor_assistant.notify.outbox import list_pending

    return len(list_pending(db_path, destination=TELEGRAM_TEST_DESTINATION))


def _parse_or_empty(payload: bytes, *, observed_at: datetime) -> list:
    """Parse RSS; a valid-but-empty channel maps to [] (OK, not failure)."""
    try:
        return parse_rss_feed(payload, source=BURGAS_MUNICIPAL_COUNCIL, fetched_at=observed_at)
    except SourceParseError as exc:
        if _EMPTY_FEED_MARKER in str(exc):
            return []
        raise


def poll_once(*, db_path=DEFAULT_DB_PATH, feed_url=LIVE_FEED_URL, observed_at=None):
    """Execute one ingestion cycle. Raises on failure (never silent empty)."""
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise StateError("observed_at must be a timezone-aware datetime")
    fetched = fetch_bytes(feed_url)
    items = _parse_or_empty(fetched.payload, observed_at=observed)
    results = process_items(items, observed, db_path=db_path, destination="telegram-test")
    by_url = {item.item_url: item for item in items}
    new_l = tuple(
        (by_url[r.item_url].title, r.item_url) for r in results if r.status == ItemStatus.NEW
    )
    upd_l = tuple(
        (by_url[r.item_url].title, r.item_url) for r in results if r.status == ItemStatus.UPDATED
    )
    n_new = len(new_l)
    n_upd = len(upd_l)
    n_same = sum(1 for r in results if r.status == ItemStatus.UNCHANGED)
    pending = _pending_total(db_path)
    return PollReport(
        BURGAS_MUNICIPAL_COUNCIL.source_id,
        feed_url,
        len(items),
        len(items),
        n_new,
        n_upd,
        n_same,
        n_new + n_upd,
        pending,
        STATUS_OK,
        None,
        new_l,
        upd_l,
    )


def format_report(report):
    lines = [
        f"source: {report.source_id}",
        f"feed_url: {report.feed_url}",
        f"fetched: {report.fetched}",
        f"parsed: {report.parsed}",
        f"NEW: {report.new_count}",
        f"UPDATED: {report.updated_count}",
        f"UNCHANGED: {report.unchanged_count}",
        f"new_outbox_intents: {report.new_outbox_intents}",
        f"pending_total: {report.pending_total}",
    ]
    if report.new_items:
        lines.append("NEW:")
        for title, url in report.new_items:
            lines += [f"- {title}", f"  {url}"]
    if report.updated_items:
        lines.append("UPDATED:")
        for title, url in report.updated_items:
            lines += [f"- {title}", f"  {url}"]
    lines.append(f"status: {report.status}")
    if report.error:
        lines.append("error: " + report.error)
    return "\n".join(lines)


def _safe_error_message(exc):
    if isinstance(exc, FetchError):
        return f"fetch failed: {exc}"
    if isinstance(exc, SourceParseError):
        return f"parse failed: {exc}"
    if isinstance(exc, StateError):
        return f"state failed: {exc}"
    if isinstance(exc, sqlite3.Error):
        return f"database failed: {exc}"
    if isinstance(exc, OSError):
        return f"storage failed: {exc}"
    return f"poll failed: {type(exc).__name__}"


def _parse_args(argv):
    p = argparse.ArgumentParser(description="M1.6 manual poll")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--feed-url", default=LIVE_FEED_URL)
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        report = poll_once(db_path=args.db, feed_url=args.feed_url)
    except Exception as exc:  # noqa: BLE001 -- operator failure contract
        print(
            format_report(
                PollReport(
                    BURGAS_MUNICIPAL_COUNCIL.source_id,
                    args.feed_url,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    STATUS_ERROR,
                    _safe_error_message(exc),
                )
            )
        )
        return 1
    print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
