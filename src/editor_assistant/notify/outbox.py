"""M1.4A durable outbox — same SQLite file, same transaction as item_state.

Placed in notify/ but imports the destination constant lazily to avoid a
store<->outbox import cycle (store owns the transaction, outbox the table).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from editor_assistant.notify.render import (
    NotificationPayload,
    payload_from_json,
    payload_to_json,
)

_OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_outbox (
    id           INTEGER PRIMARY KEY,
    destination  TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    item_url     TEXT NOT NULL,
    version_no   INTEGER NOT NULL,
    event_type   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    delivered_at TEXT NULL,
    UNIQUE (destination, source_id, item_url, version_no)
)
"""


@dataclass(frozen=True)
class OutboxRow:
    id: int
    destination: str
    source_id: str
    item_url: str
    version_no: int
    event_type: str
    content_hash: str
    payload: NotificationPayload
    created_at: str
    delivered_at: str | None

    @property
    def pending(self) -> bool:
        return self.delivered_at is None


def init_outbox(conn: sqlite3.Connection) -> None:
    """Create the outbox table inside the caller's transaction/connection."""
    conn.execute(_OUTBOX_SCHEMA)


def enqueue_notification(
    conn: sqlite3.Connection,
    *,
    destination: str,
    source_id: str,
    item_url: str,
    version_no: int,
    event_type: str,
    content_hash: str,
    payload: NotificationPayload,
    created_at_iso: str,
) -> int | None:
    """Insert one intent; same (destination, source, url, version) → keep first.

    Returns the row id, or None if this version was already queued.
    """
    cursor = conn.execute(
        "INSERT OR IGNORE INTO notification_outbox "
        "(destination, source_id, item_url, version_no, event_type,"
        " content_hash, payload_json, created_at, delivered_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (
            destination,
            source_id,
            item_url,
            version_no,
            event_type,
            content_hash,
            payload_to_json(payload),
            created_at_iso,
        ),
    )
    if cursor.lastrowid:
        return cursor.lastrowid
    row = conn.execute(
        "SELECT id FROM notification_outbox WHERE destination = ? AND source_id = ?"
        " AND item_url = ? AND version_no = ?",
        (destination, source_id, item_url, version_no),
    ).fetchone()
    return row[0] if row else None


def _row_to_outbox(row: tuple) -> OutboxRow:
    return OutboxRow(
        id=row[0],
        destination=row[1],
        source_id=row[2],
        item_url=row[3],
        version_no=row[4],
        event_type=row[5],
        content_hash=row[6],
        payload=payload_from_json(row[7]),
        created_at=row[8],
        delivered_at=row[9],
    )


def list_pending(db_path: str | Path, *, destination: str | None = None) -> list[OutboxRow]:
    from editor_assistant.state.store import TELEGRAM_TEST_DESTINATION

    destination = destination or TELEGRAM_TEST_DESTINATION
    with sqlite3.connect(db_path) as conn:
        conn.execute(_OUTBOX_SCHEMA)
        rows = conn.execute(
            "SELECT id, destination, source_id, item_url, version_no, event_type,"
            " content_hash, payload_json, created_at, delivered_at"
            " FROM notification_outbox WHERE destination = ? AND delivered_at IS NULL"
            " ORDER BY id",
            (destination,),
        ).fetchall()
    return [_row_to_outbox(r) for r in rows]


def count_all(db_path: str | Path) -> tuple[int, int, int]:
    """Return (all, pending, sent) for the default destination."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(_OUTBOX_SCHEMA)
        all_n = conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM notification_outbox WHERE delivered_at IS NULL"
        ).fetchone()[0]
    return all_n, pending, all_n - pending


def mark_delivered(db_path: str | Path, outbox_id: int, delivered_at: datetime) -> None:
    from editor_assistant.state.fingerprint import StateError

    if not isinstance(delivered_at, datetime) or delivered_at.tzinfo is None:
        raise StateError("delivered_at must be a timezone-aware datetime")
    with sqlite3.connect(db_path) as conn:
        conn.execute(_OUTBOX_SCHEMA)
        with conn:
            cursor = conn.execute(
                "UPDATE notification_outbox SET delivered_at = ? WHERE id = ?",
                (delivered_at.isoformat(), outbox_id),
            )
            if cursor.rowcount == 0:
                raise StateError(f"unknown outbox id: {outbox_id}")
