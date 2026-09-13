"""M2.1 corpus store — JSONL only (inspectable), stdlib only."""

from __future__ import annotations

import json
from pathlib import Path

from editor_assistant.style.corpus import (
    ArticleRecord,
    CorpusManifest,
    FailureRecord,
    article_from_dict,
    article_to_dict,
    build_manifest,
    manifest_to_dict,
)
from editor_assistant.style.extract import ArticleParseError, parse_article_html

FAILURE_TYPES = ("EMPTY", "MALFORMED", "MISSING_CONTENT", "ENCODING")


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def import_pages(
    pages: list[tuple[str, str | bytes]],
    *,
    observed_at: str | None = None,
) -> tuple[list[ArticleRecord], list[FailureRecord]]:
    """Import (url, html) pairs; failures quarantined, never raised."""
    seen_at = observed_at or _utc_now_iso()
    records: list[ArticleRecord] = []
    failures: list[FailureRecord] = []
    for url, html in pages:
        try:
            records.append(parse_article_html(html, url=url))
        except ArticleParseError as exc:
            failures.append(
                FailureRecord(
                    url=url or "",
                    failure_type="MISSING_CONTENT",
                    failure_detail=str(exc),
                    observed_at=seen_at,
                )
            )
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            failures.append(
                FailureRecord(
                    url=url or "",
                    failure_type="MALFORMED",
                    failure_detail=f"{type(exc).__name__}: {exc}",
                    observed_at=seen_at,
                )
            )
    return records, failures


def write_jsonl(records: list[ArticleRecord], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(article_to_dict(record), ensure_ascii=False) + "\n")
    return out


def read_jsonl(path: str | Path) -> list[ArticleRecord]:
    out: list[ArticleRecord] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(article_from_dict(json.loads(line)))
    return out


def build_and_write_manifest(
    records: list[ArticleRecord],
    failures: list[FailureRecord],
    path: str | Path,
) -> CorpusManifest:
    manifest = build_manifest(records, failures=failures)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest_to_dict(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
