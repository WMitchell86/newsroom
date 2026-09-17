# M2.1B Report — Style Corpus Pilot (150 articles)

## Implemented

Deterministic, offline-testable pilot corpus pipeline for chernomorie-bg.com:
listing discovery (same-scope pagination only) → stratified sampling
(120–180 target 150; band targets 60/35/30/25; category soft cap 30%;
year round-robin inside bands; seeded, reproducible) → GET-only fetching
(1.5s pacing, same-domain enforcement, raw snapshots) → M2.1A extraction
→ extended manifest + deterministic 30-item stratified QA sample with
automated integrity checks.

## Files changed

- `src/editor_assistant/style/discover.py` (new) — listing parser, paging scoping
- `src/editor_assistant/style/sampling.py` (new) — stratified sampler
- `src/editor_assistant/style/fetch.py` (new) — GET-only collector + quarantine
- `src/editor_assistant/style/report.py` (new) — extended manifest, QA sample
- `src/editor_assistant/style/corpus.py` (modified) — M2.1B stratification helpers
- `tests/test_style_pipeline.py` (new, 19 tests), `tests/test_style_corpus.py` (12 tests)
- `fixtures/style/listing_kultura.html` (new) — offline listing fixture
- `var/style_corpus/*` (git-ignored data): candidates (611), selection (150),
  raw snapshots (150), articles.jsonl (150), failures.jsonl (0),
  duplicates.json, manifest.json, qa_sample.jsonl (30), qa_summary.json

## Contracts introduced

- Candidate row: `{url, headline, author, date, archive_source, listing_page}`
- Extended manifest: M2.1 manifest fields + `article_count`,
  `band_counts`, `author_class_counts`, `category_membership_count`,
  `multi_category_count`, `parse_failure_types`
- QA row: article identity + band/author-class + 10 automated checks
- Sampling version tag: `m2.1b-sampling-1` (seed `20260913`)

## Tests run

`python3 -m pytest tests/ -q` — **181 passed** (offline only; network paths
covered by allow-list + monkeypatched fetch, never live in tests).
`ruff check src/editor_assistant/style/ tests/test_style_pipeline.py` — clean.

## Manual verification (spot checks on live data)

- Deep archive page (id-form pagination, e.g. `/author/desislava/posts/4707`)
  parsed with identical markup to page 2 — discovery works on old listings.
- 611-candidate pool → deterministic 150 selection; re-run over frozen
  `candidates.jsonl` reproduces `selected_urls.jsonl` exactly (True).
- Raw snapshots written to `var/style_corpus/raw/`; extractor runs clean
  on all 150 (0 parse failures, 0 missing body/date).

## Failure-case verification

- Cross-domain/query/redirect URLs rejected by allow-list (unit-tested).
- Fetch errors quarantined to `failures.jsonl` with failure_type/detail;
  extraction failures quarantined as MALFORMED/MISSING_CONTENT (tested).
- Band under-fill allowed and visible in `band_counts` (no padding).
- Hard cap 200 enforced by ValueError (tested).

## Frozen-area verification

`git status`: only `src/editor_assistant/style/*`, `tests/*`,
`fixtures/style/*`, `m2/` spec docs. No changes to Radar/frozen components
(`sources/`, `state/`, `notify/`, `poll.py` untouched).

## Known limitations

- Category counts on candidates are listing-page-derived; per-article
  categories come from the M2.1A extractor (multi-category: 38 of 150).
- `author_counts` reflect extractor-preserved authors (8 of 150 missing,
  preserved as explicit None, not guessed).
- 2 duplicate post_id groups kept and recorded (evidence not destroyed).
- 2024–2026 band is 2026-heavy on the live site; year round-robin
  surfaces available 2024/2025 items but availability limits them.
- Bulgarian auto-checks (start/end/pollution) are heuristics; the 30-item
  QA sample is generated for human review, not a substitute for it.

## Production side effects

None. Read-only GETs against the public site; storage under git-ignored
`var/style_corpus/`. No generation code, no M2.2 analysis.

## Rollback

Delete `var/style_corpus/` and the four new style modules + tests/fixture;
`corpus.py` helper additions are additive and unused elsewhere.

## Verdict

PASS — pilot corpus (150) exists with exact band targets
(2024–2026: 60, 2020–2023: 35, 2015–2019: 30, 2009–2014: 25),
author split house 83 / named 59 / unknown 8, date coverage
2009-08-02 → 2026-09-11, 17 categories, median body 1172 chars,
0 parse failures, duplicates recorded (2 groups), QA sample clean
(0 critical errors), tests green, frozen areas untouched,
manifest + selection reproducible from committed code + frozen candidate pool.

## Recommended next smallest step

M2.2 Style Analysis (deterministic stats only) on this frozen 150-article
corpus — or first, a human pass over `qa_sample.jsonl` (30 items) before
freezing the corpus for analysis.
