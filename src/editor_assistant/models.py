"""M1.1 normalized contract: minimal source + item models (stdlib only).

No AI fields, no scores, no entities/topics/priorities/risk, no persistence IDs.
Missing optional values stay None — never invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceDef:
    """Smallest useful source definition (no registry yet)."""

    source_id: str
    canonical_url: str
    parser: str  # parser identifier, e.g. "rss20"


@dataclass(frozen=True)
class SourceItem:
    """One normalized source item. All values traceable to the fixture."""

    source_id: str
    source_url: str
    item_url: str
    title: str
    published_at: datetime | None
    fetched_at: datetime
    body_text: str | None
    body_links: tuple[str, ...] = ()
    author: str | None = None
