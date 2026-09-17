"""M2.1B deterministic stratified sampler — stdlib only, no network.

Input: discovery candidate rows (as produced by parse_listing_page plus
archive_source/listing_page provenance), each with an optional listing
date string ("DD.MM.YYYYг. ...").

Output: deterministic selection honoring:
- total target 150 (allowed 120-180, hard cap 200)
- time bands: 2024-2026 ~60 / 2020-2023 ~35 / 2015-2019 ~30 / 2009-2014 ~25
  (bands derive from the candidate's listing date; under-fill is allowed
  and reported, never padded with out-of-band picks)
- category soft cap: a candidate is skipped if taking it would push any
  of its known categories past CATEGORY_SOFT_CAP of the total target
- deterministic seeded order: sorted by (date, url) then seeded shuffle
  within equal-date groups — no headline desirability picking
- replacement policy: failed URLs are removed from the candidate pool
  and stratified_selection is re-run with the same seed; ordering is
  deterministic, so the replacement set is reproducible

Ties are broken by URL everywhere so results are fully reproducible.
"""

from __future__ import annotations

import json
import random
import re
from datetime import date
from pathlib import Path

from editor_assistant.style.corpus import DEFAULT_BAND_TARGETS, band_for_date

CATEGORY_SOFT_CAP = 0.30
MAX_ARTICLES = 200
SAMPLING_VERSION = "m2.1b-sampling-1"

_BG_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def listing_date_to_iso(raw: str | None) -> str | None:
    """'03.08.2009г. 20:46ч., обновена на ...' -> '2009-08-03' (first date)."""
    text = (raw or "").strip()
    match = _BG_DATE_RE.search(text)
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def candidate_sort_key(row: dict) -> tuple:
    return (
        listing_date_to_iso(row.get("date")) or "",
        (row.get("url") or "").strip(),
    )


def deterministic_order(rows: list[dict], *, seed: int) -> list[dict]:
    """Sort by (date, url), then seeded-shuffle inside equal-date groups.

    Grouping by date keeps recency spread inside a band instead of
    clumping; the permutation is fully reproducible for a given seed.
    """
    groups: dict[str, list[dict]] = {}
    for row in sorted(rows, key=candidate_sort_key):
        groups.setdefault(listing_date_to_iso(row.get("date")) or "", []).append(row)
    rng = random.Random(seed)
    ordered: list[dict] = []
    for key in sorted(groups):
        indexed = list(enumerate(groups[key]))
        rng.shuffle(indexed)
        ordered.extend(row for _, row in indexed)
    return ordered


def _candidate_categories(row: dict) -> list[str]:
    cats = row.get("categories") or ([row["category"]] if row.get("category") else [])
    return [c for c in cats if c]


def _take_with_cap(
    pool: list[dict],
    want: int,
    total_target: int,
    *,
    seen_urls: set[str],
) -> list[dict]:
    """Greedy take in pool order, skipping candidates over the soft cap."""
    chosen: list[dict] = []
    cat_counts: dict[str, int] = {}
    max_per_cat = max(1, int(total_target * CATEGORY_SOFT_CAP))
    for row in pool:
        if len(chosen) >= want:
            break
        url = (row.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        cats = _candidate_categories(row)
        if any(cat_counts.get(c, 0) + 1 > max_per_cat for c in cats):
            continue
        chosen.append(row)
        seen_urls.add(url)
        for cat in cats:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
    return chosen


def stratified_selection(
    rows: list[dict],
    *,
    seed: int = 20260913,
    total_target: int = 150,
    band_targets: dict[str, int] | None = None,
) -> list[dict]:
    """Deterministic stratified sample from discovery candidates.

    Band attribution uses listing_date_to_iso; rows without a parsable
    date land in 'unk' and are only used if their band has a target.
    Within each band the pool is seeded-shuffled (seed derived from the
    run seed + band label), so dates spread across the whole band range
    instead of clustering at the earliest dates. Returns the selected
    rows (original dicts, unmodified), sorted by (date, url) for stable
    output.
    """
    if total_target > MAX_ARTICLES:
        raise ValueError(f"total_target {total_target} exceeds hard cap {MAX_ARTICLES}")
    if not rows:
        return []
    targets = dict(band_targets or DEFAULT_BAND_TARGETS)
    unique: list[dict] = []
    seen: set[str] = set()
    for row in sorted(rows, key=candidate_sort_key):
        url = (row.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            unique.append(row)
    buckets: dict[str, list[dict]] = {}
    for row in unique:
        iso = listing_date_to_iso(row.get("date"))
        bucket = band_for_date(iso) if iso else None
        buckets.setdefault(bucket or "unk", []).append(row)
    selected: list[dict] = []
    seen_urls: set[str] = set()
    for band in sorted(buckets):
        pool = buckets[band]
        # intra-band year round-robin: spread picks across available years
        # (deterministic; availability-limited, never padded)
        year_groups: dict[str, list[dict]] = {}
        for row in sorted(pool, key=candidate_sort_key):
            iso = listing_date_to_iso(row.get("date")) or ""
            year_groups.setdefault(iso[:4], []).append(row)
        rng = random.Random(f"{seed}:{band}")
        interleaved: list[dict] = []
        years = sorted(year_groups)
        for group_years in years:
            rng.shuffle(year_groups[group_years])
        cursors = {y: 0 for y in years}
        while len(interleaved) < len(pool):
            progressed = False
            for year in years:
                group = year_groups[year]
                if cursors[year] < len(group):
                    interleaved.append(group[cursors[year]])
                    cursors[year] += 1
                    progressed = True
            if not progressed:
                break
        want = min(targets.get(band, 0), len(interleaved))
        selected.extend(
            _take_with_cap(interleaved, want, targets.get(band, total_target), seen_urls=seen_urls)
        )
    selected.sort(key=candidate_sort_key)
    return selected


def selection_summary(rows: list[dict]) -> dict:
    """Reproducible stats block for the selection: bands and categories."""
    from collections import Counter

    bands: Counter = Counter()
    categories: Counter = Counter()
    for row in rows:
        iso = listing_date_to_iso(row.get("date"))
        bands[band_for_date(iso) or "unk"] += 1
        for cat in _candidate_categories(row):
            categories[cat] += 1
    return {
        "sampling_version": SAMPLING_VERSION,
        "selected_count": len(rows),
        "band_counts": dict(sorted(bands.items())),
        "category_counts": dict(sorted(categories.items())),
    }


def write_selected_jsonl(rows: list[dict], path: str | Path) -> Path:
    """Persist selection (one JSON object per line, deterministic keys)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            )
    return out
