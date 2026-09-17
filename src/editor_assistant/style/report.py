"""M2.1B extended manifest + QA sample builder — stdlib only, offline.

- build_extended_manifest: M2.1 manifest fields + M2.1B stratification
  stats (time bands, author classes, multi-category membership).
  article_count and category_membership_count are reported separately.
- check_record: automated QA checks (headline/date/body presence,
  start/end integrity, nav pollution, Bulgarian characters, URL).
- build_qa_sample: deterministic stratified 30-item sample + 10 spot
  checks (seeded; bands and author classes stratified, ties by url).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from editor_assistant.style.corpus import (
    ArticleRecord,
    CorpusManifest,
    FailureRecord,
    author_class,
    author_class_counts,
    band_for_date,
    build_manifest,
    manifest_to_dict,
)

NAV_POLLUTION_MARKERS = ("Още новини", "Тагове", "Реклама")


def build_extended_manifest(
    records: list[ArticleRecord],
    failures: list[FailureRecord] | None = None,
) -> dict[str, object]:
    """M2.1 manifest + M2.1B stratification block (deterministic)."""
    manifest: CorpusManifest = build_manifest(records, failures=failures)
    base = manifest_to_dict(manifest)
    bands: dict[str, int] = {}
    for record in records:
        band = band_for_date(record.published_date) or "unk"
        bands[band] = bands.get(band, 0) + 1
    multi = sum(1 for r in records if len(r.categories) > 1)
    memberships = sum(len(r.categories) for r in records)
    return {
        **base,
        "article_count": len(records),
        "category_membership_count": memberships,
        "multi_category_count": multi,
        "band_counts": dict(sorted(bands.items())),
        "author_class_counts": author_class_counts(records),
        "parse_failure_types": _failure_type_counts(failures or []),
    }


def _failure_type_counts(failures: list[FailureRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for failure in failures:
        counts[failure.failure_type] = counts.get(failure.failure_type, 0) + 1
    return dict(sorted(counts.items()))


def _starts_clean(body: str) -> bool:
    text = body.strip()
    return bool(text) and not text[0].islower()


def _ends_clean(body: str) -> bool:
    text = body.strip()
    if not text:
        return False
    return text[-1] in '.!?\u2026")\u201d' or text[-1].isalnum()


def _has_bulgarian(text: str) -> bool:
    return any("\u0430" <= ch <= "\u044f" for ch in text)


def check_record(record: ArticleRecord) -> dict[str, object]:
    """Automated QA checks on one record (no network, deterministic)."""
    body = record.body or ""
    checks: dict[str, object] = {
        "headline_present": bool((record.headline or "").strip()),
        "date_present": bool(record.published_date),
        "author_present": bool((record.author or "").strip()),
        "body_present": bool(body.strip()),
        "body_starts_clean": _starts_clean(body),
        "body_ends_clean": _ends_clean(body),
        "no_nav_pollution": not any(marker in body for marker in NAV_POLLUTION_MARKERS),
        "bulgarian_chars_ok": _has_bulgarian(body),
        "url_valid": (record.url or "").startswith("https://chernomorie-bg.com/post/"),
        "no_placeholder_gaps": "\u2588" not in body,
    }
    critical_keys = (
        "headline_present",
        "date_present",
        "body_present",
        "body_starts_clean",
        "body_ends_clean",
        "no_nav_pollution",
        "url_valid",
    )
    checks["critical_errors"] = sum(1 for key in critical_keys if not checks[key])
    return checks


def build_qa_sample(
    records: list[ArticleRecord],
    *,
    size: int = 30,
    spot_size: int = 10,
    seed: int = 20260913,
) -> dict[str, object]:
    """Deterministic stratified QA sample: 30 + spot checks.

    Strata: time band x author class (house/named/unknown); seeded
    shuffle inside strata, round-robin across strata, ties by URL.
    Every row carries automated check_record() results.
    """
    strata: dict[tuple[str, str], list[ArticleRecord]] = {}
    for record in sorted(records, key=lambda r: r.url):
        band = band_for_date(record.published_date) or "unk"
        strata.setdefault((band, author_class(record.author)), []).append(record)
    rng = random.Random(seed)
    for key in sorted(strata):
        rng.shuffle(strata[key])
    ordered: list[ArticleRecord] = []
    keys = sorted(strata)
    cursors = {key: 0 for key in keys}
    while len(ordered) < len(records):
        progressed = False
        for key in keys:
            group = strata[key]
            if cursors[key] < len(group):
                ordered.append(group[cursors[key]])
                cursors[key] += 1
                progressed = True
        if not progressed:
            break
    sample = ordered[: min(size, len(ordered))]
    qa_rows = [
        {
            "article_id": r.article_id,
            "url": r.url,
            "headline": r.headline,
            "author": r.author,
            "published_date": r.published_date,
            "category": r.category,
            "band": band_for_date(r.published_date) or "unk",
            "author_class": author_class(r.author),
            "body_length": len(r.body or ""),
            "checks": check_record(r),
        }
        for r in sample
    ]
    # spot checks: 10 items, mixed from inside and outside the 30 sample
    inside = sample[: spot_size // 2]
    rest = ordered[len(sample) :]
    outside = rest[: spot_size - len(inside)]
    spot_urls = {r.url for r in inside} | {r.url for r in outside}
    spot_rows = [
        {"article_id": r.article_id, "url": r.url, "checks": check_record(r)}
        for r in sorted((x for x in records if x.url in spot_urls), key=lambda x: x.url)
    ]
    total_critical = sum(int(row["checks"]["critical_errors"]) for row in qa_rows)
    return {
        "sample_size": len(qa_rows),
        "spot_check_count": len(spot_rows),
        "total_critical_errors": total_critical,
        "qa_rows": qa_rows,
        "spot_rows": spot_rows,
    }


def write_qa_sample(qa: dict[str, object], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in qa["qa_rows"]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out


def write_manifest(extended: dict[str, object], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(extended, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
