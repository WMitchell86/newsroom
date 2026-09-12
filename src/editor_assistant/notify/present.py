"""M1.5 Step 2 presentation helpers — deterministic cleanup, no LLM, no network.

Every function here derives an editor-facing DISPLAY string from immutable
data (payload snapshot / SourceItem fields). Nothing in this module writes
back: SourceItem, fingerprints, item_state, and outbox identity are untouched
by design (verified by tests/test_present.py).
"""

from __future__ import annotations

import re

# Presentation excerpt cap (payload snapshot keeps its own 500-char body_excerpt).
DISPLAY_EXCERPT_LIMIT = 280
MAX_ATTACHMENTS_SHOWN = 3

# §1 explicit display-name map; unknown ids fall back to the raw source_id.
SOURCE_DISPLAY_NAMES = {
    "burgas-municipal-council": "Общински съвет – Бургас",
    "burgas-municipality-press": "Община Бургас – Пресцентър",
}

# Known Burgas council boilerplate (measured in UX_AUDIT.md over 19/19 items).
# Case-insensitive; longer phrases first so full occurrences are removed whole.
_NOISE_PHRASES = (
    "ВКЛЮЧЕНО В ПРЕДСТОЯЩО ЗАСЕДАНИЕ НА ПОСТОЯННА КОМИСИЯ",
    "ВКЛЮЧЕНО В ПРЕДСТОЯЩО ЗАСЕДАНИЕ",
    "ФАЙЛОВЕ И РЕСУРСИ",
)

# Webmaster/editor credit line, e.g. "zh.gospodinova Пет. | 11.09.2026г. | 16:23ч."
_CREDIT_PATTERN = re.compile(
    r"\b[A-Za-z0-9._-]{2,}\s+Пет\.\s*\|\s*\d{1,2}\.\d{1,2}\.\d{4}г\.\s*\|\s*\d{1,2}:\d{2}ч\."
)

# §2 subject marker ("относно:") — case-insensitive, source text only.
_SUBJECT_PATTERN = re.compile(r"относно\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)

# §7 neutral extension-based attachment labels (no semantic naming).
_EXT_LABELS = {
    "pdf": "PDF",
    "doc": "DOC",
    "docx": "DOCX",
    "xls": "XLS",
    "xlsx": "XLSX",
    "rtf": "RTF",
    "odt": "ODT",
    "zip": "ZIP",
}


def display_source_name(source_id: str) -> str:
    """§1 human-readable source label; unknown ids fall back to source_id."""
    return SOURCE_DISPLAY_NAMES.get(source_id, source_id)


def extract_display_subject(title: str, body_text: str | None) -> str | None:
    """§2 deterministic subject: source text after the first 'относно:' marker.

    Stops at the credit line or a known noise phrase (whichever comes first),
    collapses whitespace, and never invents wording. Falls back to None —
    the caller then uses the original title (§3).
    """
    if not body_text:
        return None
    match = _SUBJECT_PATTERN.search(body_text)
    if not match:
        return None
    rest = match.group(1)
    upper = rest.upper()
    cut = len(rest)
    for phrase in _NOISE_PHRASES:
        idx = upper.find(phrase)
        if idx != -1 and idx < cut:
            cut = idx
    credit = _CREDIT_PATTERN.search(rest)
    if credit and credit.start() < cut:
        cut = credit.start()
    subject = re.sub(r"\s+", " ", rest[:cut]).strip().rstrip(" ,;–—-")
    return subject or None


def clean_body_text(body_text: str | None, *, title: str | None = None) -> str | None:
    """§4 presentation-only boilerplate cleanup. Never mutates stored data.

    Removes: credit line, known noise phrases, and verbatim title repeats
    (exact case-sensitive match — the title comes from the same source).
    """
    if not body_text:
        return None
    text = body_text
    if title:
        text = text.replace(title, " ")
    text = _CREDIT_PATTERN.sub(" ", text)
    for phrase in _NOISE_PHRASES:
        text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    return text


def clean_excerpt(
    body_text: str | None,
    *,
    title: str | None = None,
    limit: int = DISPLAY_EXCERPT_LIMIT,
) -> str | None:
    """§5 clean FIRST, then excerpt to `limit` (never truncate before cleaning)."""
    cleaned = clean_body_text(body_text, title=title)
    if not cleaned:
        return None
    text = re.sub(r"\s+", " ", cleaned).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def attachment_label(url: str) -> str | None:
    """§7 neutral extension label; None when no extension (never guessed)."""
    last = url.rstrip("/").rsplit("/", 1)[-1]
    if "." not in last:
        return None
    ext = last.rsplit(".", 1)[1].lower()
    return _EXT_LABELS.get(ext)


def attachment_summary(links: tuple[str, ...] | list[str]) -> tuple[list[tuple[str, str]], int]:
    """§8/§9 first `MAX_ATTACHMENTS_SHOWN` labeled attachments, order preserved.

    Links without a known extension are skipped from the visible list (they
    cannot be neutrally labeled), never reordered or renamed. Returns
    (visible [(label, url)], hidden_count).
    """
    visible: list[tuple[str, str]] = []
    for link in links:
        label = attachment_label(link)
        if label is not None:
            visible.append((label, link))
        if len(visible) == MAX_ATTACHMENTS_SHOWN:
            break
    hidden = len(links) - len(visible)
    return visible, hidden
