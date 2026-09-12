"""M1.4A notification payload + local renderer — deterministic, no network.

Payload snapshots immutable editor-facing fields at enqueue time so later
source changes cannot rewrite an older queued version's notification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from editor_assistant.models import SourceItem
from editor_assistant.notify.present import (
    attachment_summary,
    clean_excerpt,
    display_source_name,
    extract_display_subject,
)

BODY_EXCERPT_LIMIT = 500

_SOFIA_TZ = ZoneInfo("Europe/Sofia")


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
    """§11 editor-facing alert. Plain text only; deterministic; display-only.

    Every editor-facing field is derived at render time from the immutable
    payload snapshot (see notify.present). Stored source data, fingerprints,
    and outbox identity are never modified by rendering.
    """
    marker = _EVENT_MARKERS.get(payload.event_type, payload.event_type)
    label = source_label or display_source_name(payload.source_id)
    subject = extract_display_subject(payload.title, payload.body_excerpt)
    headline = subject or payload.title
    lines: list[str] = [f"{marker} {label}", "", headline]
    published_bg = format_published_bg_display(payload.published_at)
    if published_bg:
        lines += ["", f"🕒 {published_bg}"]
    excerpt = clean_excerpt(payload.body_excerpt, title=payload.title)
    if excerpt:
        lines += ["", excerpt]
    visible, hidden = attachment_summary(payload.body_links)
    if visible:
        lines += ["", "📎 Документи:"]
        for att_label, att_url in visible:
            lines.append(f"• {att_label} — {att_url}")
        if hidden > 0:
            lines.append(f"+{hidden} още")
    lines += ["", "🔗 Източник:", payload.item_url]
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


def format_published_bg_display(published_at: datetime | str | None) -> str | None:
    """§6 display-only BG local time (Europe/Sofia): `дд.мм.гггг, чч:мм`.

    Never mutates or replaces the stored value; None renders as None so the
    line is omitted cleanly. Naive datetimes are rejected (project-wide rule).
    """
    if published_at is None:
        return None
    if isinstance(published_at, str):
        published_at = datetime.fromisoformat(published_at)
    if published_at.tzinfo is None:
        raise ValueError("published_at must be timezone-aware for display formatting")
    return published_at.astimezone(_SOFIA_TZ).strftime("%d.%m.%Y, %H:%M")


# Kept for backwards compatibility with the M1.4A name (UTC, %Z suffix).
def format_published_bg(published_at: datetime | None) -> str | None:
    return format_published_bg_display(published_at)


# §11 markers (plain text; no Telegram parse mode).
_EVENT_MARKERS = {"NEW": "🆕", "UPDATED": "🔄"}
