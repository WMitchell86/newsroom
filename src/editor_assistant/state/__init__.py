"""M1.3+M1.4A state package: fingerprint + SQLite store + outbox (stdlib only)."""

from editor_assistant.state.fingerprint import (
    StateError,
    canonical_payload,
    fingerprint_item,
)
from editor_assistant.state.store import (
    DEFAULT_DB_PATH,
    ItemStatus,
    StateResult,
    init_db,
    process_items,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "ItemStatus",
    "StateError",
    "StateResult",
    "canonical_payload",
    "fingerprint_item",
    "init_db",
    "process_items",
]
