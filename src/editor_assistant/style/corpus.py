"""M2.1 ArticleRecord contract + deterministic normalization (stdlib only).

Frozen Radar untouched: this module does not import sources/rss.py,
state/*, notify/*, poll.py. Missing values stay explicit None — never
invented. Published wording preserved verbatim (only whitespace
collapsed).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

SOURCE_TYPE = "chernomorie_archive"

_WS_RE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str | None:
    """Collapse whitespace runs to single spaces and strip ends."""
    if not isinstance(text, str):
        return None
    collapsed = _WS_RE.sub(" ", text).strip()
    return collapsed or None


def _norm_key(text: str | None) -> str:
    """Normalized key for duplicate matching (case/whitespace-insensitive)."""
    if text is None:
        return ""
    return _WS_RE.sub(" ", text).strip().lower()


def make_article_id(url: str, published_at: str | None, headline: str | None) -> str:
    """Deterministic 16-hex-char id from (url, published_at, headline)."""
    canonical = json.dumps(
        {
            "url": (url or "").strip(),
            "published_at": published_at or "",
            "headline": _norm_key(headline),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


def body_hash(body: str | None) -> str | None:
    """SHA-256 over whitespace-normalized body; None stays None."""
    if body is None:
        return None
    normalized = _WS_RE.sub(" ", body).strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArticleRecord:
    """One cleaned archive article. All fields traceable to source HTML."""

    article_id: str
    url: str
    published_at: str | None = None
    author: str | None = None
    category: str | None = None
    headline: str | None = None
    subheadline: str | None = None
    lead: str | None = None
    body: str | None = None
    quotes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    source_type: str = SOURCE_TYPE


@dataclass(frozen=True)
class FailureRecord:
    """Quarantined parse failure — evidence preserved, never dropped."""

    url: str
    failure_type: str
    failure_detail: str
    observed_at: str


@dataclass(frozen=True)
class CorpusManifest:
    total_articles: int
    date_min: str | None
    date_max: str | None
    category_counts: dict[str, int] = field(default_factory=dict)
    author_counts: dict[str, int] = field(default_factory=dict)
    missing_author: int = 0
    missing_date: int = 0
    missing_body: int = 0
    duplicate_count: int = 0
    parse_failure_count: int = 0
    median_body_length: int = 0


def article_to_dict(record: ArticleRecord) -> dict[str, object]:
    from dataclasses import asdict

    data = asdict(record)
    data["quotes"] = list(record.quotes)
    data["tags"] = list(record.tags)
    return data


def article_from_dict(data: dict[str, object]) -> ArticleRecord:
    payload = dict(data)
    payload["quotes"] = tuple(payload.get("quotes") or ())
    payload["tags"] = tuple(payload.get("tags") or ())
    return ArticleRecord(**payload)  # type: ignore[arg-type]


def manifest_to_dict(manifest: CorpusManifest) -> dict[str, object]:
    from dataclasses import asdict

    return asdict(manifest)


def find_duplicates(records: list[ArticleRecord]) -> dict[str, list[list[str]]]:
    """Inspect 3 duplicate signals; record groups, destroy nothing."""
    by_url: dict[str, list[str]] = {}
    by_headline_date: dict[str, list[str]] = {}
    by_body: dict[str, list[str]] = {}
    for record in records:
        by_url.setdefault((record.url or "").strip(), []).append(record.article_id)
        key = _norm_key(record.headline) + "|" + (record.published_at or "").strip()
        by_headline_date.setdefault(key, []).append(record.article_id)
        digest = body_hash(record.body)
        if digest is not None:
            by_body.setdefault(digest, []).append(record.article_id)
    return {
        "by_url": [sorted(g) for g in by_url.values() if len(g) > 1],
        "by_headline_date": [sorted(g) for g in by_headline_date.values() if len(g) > 1],
        "by_body_hash": [sorted(g) for g in by_body.values() if len(g) > 1],
    }


def build_manifest(
    records: list[ArticleRecord],
    *,
    failures: list[FailureRecord] | None = None,
) -> CorpusManifest:
    """Reproducible manifest: same records -> same manifest."""
    from statistics import median

    failures = failures or []
    dates = sorted(r.published_at for r in records if r.published_at)
    category_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    for record in records:
        if record.category:
            category_counts[record.category] = category_counts.get(record.category, 0) + 1
        if record.author:
            author_counts[record.author] = author_counts.get(record.author, 0) + 1
    dup_groups = find_duplicates(records)
    dup_ids: set[str] = set()
    for groups in dup_groups.values():
        for group in groups:
            dup_ids.update(sorted(group)[1:])
    lengths = sorted(len(record.body or "") for record in records)
    return CorpusManifest(
        total_articles=len(records),
        date_min=dates[0] if dates else None,
        date_max=dates[-1] if dates else None,
        category_counts=dict(sorted(category_counts.items())),
        author_counts=dict(sorted(author_counts.items())),
        missing_author=sum(1 for r in records if not r.author),
        missing_date=sum(1 for r in records if not r.published_at),
        missing_body=sum(1 for r in records if not r.body),
        duplicate_count=len(dup_ids),
        parse_failure_count=len(failures),
        median_body_length=int(median(lengths)) if lengths else 0,
    )
