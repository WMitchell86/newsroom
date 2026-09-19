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

# M1.5 Step 4 — leading-marker for the conservative `относно: <subject>` case.
# The marker must sit near the very start of the cleaned text (real-data max
# measured marker position across 19 items: 115 chars) so the removable region
# stays clearly anchored at the beginning (§5), never mid-body.
_LEADING_MARKER_RE = re.compile(r"относно\s*:\s*", re.IGNORECASE)
_LEADING_PREFIX_LIMIT = 200

# Punctuation/connectors trimmed from a remainder after a removed prefix.
# The period is safe: it terminates the duplicated subject sentence, never
# the informative remainder (a display line never meaningfully starts with ".").
_TRIM_CHARS = " .,;:–—-»«()[]"

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


def _flex_regex(text: str) -> re.Pattern[str]:
    """§3 comparison-only regex: escaped subject with case-insensitive + flexible
    whitespace. Used ONLY to decide whether leading duplication exists; the
    displayed remainder always keeps the original spelling."""
    escaped = re.escape(text)
    escaped = re.sub(r"\\\s+", r"\\s+", escaped)
    return re.compile(escaped, re.IGNORECASE)


def strip_leading_subject(text: str, subject: str | None) -> str | None:
    """M1.5 Step 4 — remove a strong, deterministic LEADING duplication only.

    Two anchored cases (both at the very start of `text`):
      A) text begins with `subject` (case/whitespace-insensitive match) →
         drop the subject itself;
      B) text begins with an administrative prefix ending in an `относно:`
         marker that is immediately followed by `subject` → drop prefix +
         marker + subject (§5 partial-prefix case).

    Comparison normalization exists for MATCHING ONLY; the returned remainder
    keeps the original source spelling. Nothing is removed from the middle of
    the body, no fuzzy/semantic similarity is used, and text that merely
    shares some words with the subject is preserved (§4). Returns None when
    nothing meaningful remains.
    """
    if not text or not subject:
        return text
    end: int | None = None
    pattern = _flex_regex(subject)
    taken = pattern.match(text)
    if taken:
        end = taken.end()
    else:
        marker = _LEADING_MARKER_RE.search(text)
        if marker and marker.start() <= _LEADING_PREFIX_LIMIT:
            taken = pattern.match(text[marker.end() :])
            if taken:
                end = marker.end() + taken.end()
    if end is None:
        return text
    # lstrip leading punctuation/whitespace of the REMAINDER, then plain
    # whitespace only on the right — a sentence-final '.' is legitimate text.
    remainder = text[end:].lstrip(_TRIM_CHARS).rstrip()
    return remainder or None


def clean_excerpt(
    body_text: str | None,
    *,
    title: str | None = None,
    subject: str | None = None,
    limit: int = DISPLAY_EXCERPT_LIMIT,
) -> str | None:
    """§5/§7 clean FIRST → de-duplicate leading subject → then excerpt to `limit`.

    The length limit is applied only AFTER de-duplication (§7). A fully
    duplicated body yields None (renderer then omits the excerpt cleanly)."""
    cleaned = clean_body_text(body_text, title=title)
    if not cleaned:
        return None
    text = re.sub(r"\s+", " ", cleaned).strip()
    if not text:
        return None
    text = strip_leading_subject(text, subject)
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def attachment_label(url: str) -> str | None:
    """§7 neutral extension label; None when no extension (never guessed).

    Query/fragment are dropped before the extension is read, so a real
    document served as `doklad.pdf?download=1` is still labeled. The extension
    must be in the last path segment: `…/download?file=doc.pdf` stays unlabeled
    rather than guessing from the query.
    """
    path = url.split("?", 1)[0].split("#", 1)[0]
    last = path.rstrip("/").rsplit("/", 1)[-1]
    if "." not in last:
        return None
    ext = last.rsplit(".", 1)[1].lower()
    return _EXT_LABELS.get(ext)


def attachment_summary(links: tuple[str, ...] | list[str]) -> tuple[list[tuple[str, str]], int]:
    """§8/§9 first `MAX_ATTACHMENTS_SHOWN` labeled attachments, order preserved.

    Links without a known extension are skipped from the visible list (they
    cannot be neutrally labeled), never reordered or renamed.

    `hidden` counts only further LABELED attachments. It is rendered as "+N
    още" under "📎 Документи:", so counting unlabeled links (pages, pictures)
    as well would promise the editor documents that do not exist.

    Returns (visible [(label, url)], hidden_count).
    """
    labeled: list[tuple[str, str]] = []
    for link in links:
        label = attachment_label(link)
        if label is not None:
            labeled.append((label, link))
    visible = labeled[:MAX_ATTACHMENTS_SHOWN]
    return visible, len(labeled) - len(visible)
