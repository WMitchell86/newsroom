"""M1.3+M1.4A SQLite state — stdlib sqlite3 only, no ORM, current-state only.

Identity: (source_id, item_url). No deletion/tombstone semantics.
No historical version tables. One transaction per process_items batch,
covering both item_state and the notification_outbox (M1.4A).
"""

from __future__ import annotations

import enum
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from editor_assistant.models import SourceItem
from editor_assistant.state.fingerprint import StateError, fingerprint_item

TELEGRAM_TEST_DESTINATION = "telegram-test"

DEFAULT_DB_PATH = Path("var/editor_assistant.sqlite3")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS item_state (
    source_id    TEXT NOT NULL,
    item_url     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version_no   INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    PRIMARY KEY (source_id, item_url)
)
"""


class ItemStatus(enum.Enum):
    NEW = "NEW"
    UNCHANGED = "UNCHANGED"
    UPDATED = "UPDATED"


@dataclass(frozen=True)
class StateResult:
    status: ItemStatus
    source_id: str
    item_url: str
    version_no: int
    content_hash: str


def _require_aware(value: datetime, *, what: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise StateError(f"{what} must be a timezone-aware datetime")
    return value.isoformat()


def init_db(path: str | Path = DEFAULT_DB_PATH) -> Path:
    """Explicit, idempotent DB init. Never drops state. Creates parent dirs."""
    db_path = Path(path)
    if db_path.parent != Path(".") and str(db_path.parent):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_SCHEMA)
        conn.commit()
    return db_path


def process_items(
    items: list[SourceItem],
    observed_at: datetime,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    destination: str = TELEGRAM_TEST_DESTINATION,
) -> list[StateResult]:
    """Process a batch in one transaction; results preserve input order.

    NEW/UPDATED transitions enqueue a durable outbox intent atomically in the
    same transaction (no state-without-notification window). UNCHANGED enqueues
    nothing. Reprocessing an unchanged item never duplicates an intent
    (UNIQUE + INSERT OR IGNORE defensive layer).
    """
    observed_iso = _require_aware(observed_at, what="observed_at")
    fingerprints = [fingerprint_item(item) for item in items]  # fail before touching DB
    results: list[StateResult] = []
    with sqlite3.connect(db_path) as conn:
        conn.execute(_SCHEMA)  # init-on-first-use, idempotent, keeps state
        from editor_assistant.notify.outbox import init_outbox

        init_outbox(conn)
        try:
            with conn:  # single transaction: commit on success, rollback on error
                for item, digest in zip(items, fingerprints, strict=True):
                    row = conn.execute(
                        "SELECT content_hash, version_no, first_seen_at "
                        "FROM item_state WHERE source_id = ? AND item_url = ?",
                        (item.source_id, item.item_url),
                    ).fetchone()
                    if row is None:
                        conn.execute(
                            "INSERT INTO item_state "
                            "(source_id, item_url, content_hash, version_no,"
                            " first_seen_at, last_seen_at)"
                            " VALUES (?, ?, ?, 1, ?, ?)",
                            (item.source_id, item.item_url, digest, observed_iso, observed_iso),
                        )
                        _enqueue(conn, item, digest, 1, "NEW", destination, observed_iso)
                        results.append(
                            StateResult(ItemStatus.NEW, item.source_id, item.item_url, 1, digest)
                        )
                    elif row[0] == digest:
                        conn.execute(
                            "UPDATE item_state SET last_seen_at = ? "
                            "WHERE source_id = ? AND item_url = ?",
                            (observed_iso, item.source_id, item.item_url),
                        )
                        results.append(
                            StateResult(
                                ItemStatus.UNCHANGED, item.source_id, item.item_url, row[1], digest
                            )
                        )
                    else:
                        conn.execute(
                            "UPDATE item_state SET content_hash = ?, version_no = version_no + 1,"
                            " last_seen_at = ? WHERE source_id = ? AND item_url = ?",
                            (digest, observed_iso, item.source_id, item.item_url),
                        )
                        updated = conn.execute(
                            "SELECT version_no FROM item_state "
                            "WHERE source_id = ? AND item_url = ?",
                            (item.source_id, item.item_url),
                        ).fetchone()
                        _enqueue(
                            conn, item, digest, updated[0], "UPDATED", destination, observed_iso
                        )
                        results.append(
                            StateResult(
                                ItemStatus.UPDATED,
                                item.source_id,
                                item.item_url,
                                updated[0],
                                digest,
                            )
                        )
        except sqlite3.Error as exc:
            raise StateError(f"batch storage failed, rolled back: {exc}") from exc
    return results


def _enqueue(
    conn: sqlite3.Connection,
    item: SourceItem,
    digest: str,
    version_no: int,
    event_type: str,
    destination: str,
    observed_iso: str,
) -> None:
    from editor_assistant.notify.outbox import enqueue_notification
    from editor_assistant.notify.render import build_payload

    payload = build_payload(item, event_type=event_type, version_no=version_no)
    enqueue_notification(
        conn,
        destination=destination,
        source_id=item.source_id,
        item_url=item.item_url,
        version_no=version_no,
        event_type=event_type,
        content_hash=digest,
        payload=payload,
        created_at_iso=observed_iso,
    )
