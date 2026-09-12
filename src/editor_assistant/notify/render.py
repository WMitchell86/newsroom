"""M1.4A notification payload + local renderer — deterministic, no network.

Payload snapshots immutable editor-facing fields at enqueue time so later
source changes cannot rewrite an older queued version's notification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from editor_assistant.models import SourceItem

BODY_EXCERPT_LIMIT = 500


@dataclass(frozen=True)
class NotificationPayload:
    event_type: str  # "NEW" | "UPDATED"
    source_id: str
    item_url: str
    title: str
    published_at: str | None  # ISO-8601 or None (explicit missing)
    version_no: int
    body_excerpt: str | None
    body_links: tuple[str, ...] = ()


def excerpt_body(body_text: str | None, limit: int = BODY_EXCERPT_LIMIT) -> str | None:
    """First N characters (Python slicing = code-point safe), stripped."""
    if body_text is None:
        return None
    text = body_text.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_payload(item: SourceItem, *, event_type: str, version_no: int) -> NotificationPayload:
    if event_type not in ("NEW", "UPDATED"):
        raise ValueError(f"unsupported event_type: {event_type!r}")
    published = item.published_at.isoformat() if item.published_at else None
    return NotificationPayload(
        event_type=event_type,
        source_id=item.source_id,
        item_url=item.item_url,
        title=item.title,
        published_at=published,
        version_no=version_no,
        body_excerpt=excerpt_body(item.body_text),
        body_links=tuple(item.body_links),
    )


def render_message(payload: NotificationPayload, *, source_label: str | None = None) -> str:
    """Plain-text editor-facing alert. Deterministic; normalized data only."""
    label = source_label or payload.source_id
    lines = [f"[{payload.event_type}] {label}", "", payload.title, ""]
    if payload.published_at:
        lines.append(f"Публикувано: {payload.published_at}")
        lines.append("")
    if payload.body_excerpt:
        lines.append(payload.body_excerpt)
        lines.append("")
    lines.append("Източник:")
    lines.append(payload.item_url)
    for link in payload.body_links:
        lines.append("")
        lines.append("Документ:")
        lines.append(link)
    return "\n".join(lines).strip() + "\n"


def payload_to_json(payload: NotificationPayload) -> str:
    import json

    data = asdict(payload)
    data["body_links"] = list(payload.body_links)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_from_json(raw: str) -> NotificationPayload:
    import json

    data = json.loads(raw)
    data["body_links"] = tuple(data.get("body_links") or ())
    return NotificationPayload(**data)


def format_published_bg(published_at: datetime | None) -> str | None:
    if published_at is None:
        return None
    return published_at.strftime("%d.%m.%Y %H:%M %Z").strip() or None
