"""M1.1 RSS 2.0 fixture parser — deterministic, stdlib only, no network.

Rules: extract only what the fixture contains; normalize whitespace
deterministically; timezone-aware datetimes; fail clearly on invalid input.
"""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from editor_assistant.models import SourceDef, SourceItem

PARSER_ID = "rss20"

_WS_RE = re.compile(r"\s+")


class SourceParseError(ValueError):
    """Raised when fixture bytes are structurally invalid or unusable."""


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip ends."""
    return _WS_RE.sub(" ", text).strip()


def parse_datetime(raw: str | None) -> datetime | None:
    """Parse RFC-2822 pubDate into a tz-aware datetime; None stays None.

    No timezone is ever inferred: a present-but-naive pubDate is a source
    defect and raises SourceParseError (not UTC, not Europe/Sofia, not local).
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError) as exc:
        raise SourceParseError(f"unparseable pubDate: {raw!r}") from exc
    if parsed.tzinfo is None:
        raise SourceParseError(f"pubDate without timezone: {raw!r}")
    return parsed


def _required_text(element: ET.Element, tag: str, *, what: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None or not child.text.strip():
        raise SourceParseError(f"{what} is missing required <{tag}>")
    return normalize_whitespace(child.text)


def _optional_text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None or not child.text.strip():
        return None
    return normalize_whitespace(child.text)


def parse_rss_item(item: ET.Element, *, source: SourceDef, fetched_at: datetime) -> SourceItem:
    """Parse one <item> element into a SourceItem. Missing optionals stay None."""
    title = _required_text(item, "title", what="RSS item")
    link = _required_text(item, "link", what="RSS item")
    published_at = parse_datetime(_optional_text(item, "pubDate"))
    body_text = _optional_text(item, "description")
    author = _optional_text(item, "author")
    if fetched_at.tzinfo is None:
        raise SourceParseError("fetched_at must be timezone-aware")
    return SourceItem(
        source_id=source.source_id,
        source_url=source.canonical_url,
        item_url=link,
        title=title,
        published_at=published_at,
        fetched_at=fetched_at,
        body_text=body_text,
        author=author,
    )


def parse_rss_feed(
    payload: bytes | str, *, source: SourceDef, fetched_at: datetime
) -> list[SourceItem]:
    """Parse a full RSS 2.0 document into SourceItems in document order."""
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = payload
    if not raw.strip():
        raise SourceParseError("empty RSS payload")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SourceParseError(f"malformed XML: {exc}") from exc
    channel = root.find("channel") if root.tag != "channel" else root
    if channel is None:
        raise SourceParseError("RSS document has no <channel>")
    items = channel.findall("item")
    if not items:
        raise SourceParseError("RSS channel contains no <item>")
    return [parse_rss_item(it, source=source, fetched_at=fetched_at) for it in items]


def item_to_dict(item: SourceItem) -> dict[str, str | None]:
    """Local deterministic rendering: every normalized field, inspectable JSON."""
    return {
        "source_id": item.source_id,
        "source_url": item.source_url,
        "item_url": item.item_url,
        "title": item.title,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "fetched_at": item.fetched_at.isoformat(),
        "body_text": item.body_text,
        "author": item.author,
    }
