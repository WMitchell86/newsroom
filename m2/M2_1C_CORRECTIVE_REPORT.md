# M2.1C — Corrective Pass Report (Human QA FAIL → rebuilt corpus)

## Gate outcome (from human QA review)

- `total_pass: 19` · `pass_with_note: 8` · `fail: 3` · **`critical_failures: 3`**
- Verdict: **FAIL / CORRECTIVE PASS REQUIRED** — corpus freeze BLOCKED, M2.2 not started.

## Failure pattern (independently re-verified against raw data)

1. **Body incomplete on legacy `<div>` content** — 9/148 raw pages carry direct
   text-bearing `<div>` blocks inside `.entry-content` that the old `<p>`-only
   extractor dropped (~600–800+ chars each; the regatta and "Бебе пред елхата"
   records were the 2 in-sample FAILs).
2. **`post_id` is not unique identity** — two collision groups (7720, 6057);
   pairs shared `article_id`; 148 snapshot files existed for 150 records
   (`7720.html`/`6057.html` each silently held two records).
3. **`subheadline` was SEO/meta description** — mapped from `og:description`
   / meta description; the template has no structural subheadline element.
4. **`<br>` glued sentences** — 9/148 pages had `<br>` inside `<p>`;
   extractor dropped the boundary → "експлоатация.Пътниците".

## Corrective step applied (deterministic, stdlib-only)

1. **Identity → canonical-URL only** (`extract.stable_article_id`): seed is
   `chernomorie-url:<canonical>`. `post_id` stays metadata + duplicate signal
   (`by_post_id` groups still recorded in duplicates.json).
2. **Snapshot filenames → `{article_id}.html`** (`fetch._snapshot_path`):
   unique per URL; re-fetched the 4 collided URLs (old files ambiguous);
   M2.1B snapshots preserved verbatim under `raw_m21b_v1/` (evidence).
3. **Body extraction preserves direct `<div>` content blocks** in DOM order
   (block-frame stack: `p`/`div`/`li` content frames; `h1-6`/`figure` as
   non-content frames whose text is dropped). Locked by new
   `fixtures/style/legacy_div_body.html`.
4. **`<br>` boundary** — bare `<br>` (CMS form) and `<br/>` insert a space
   inside paragraph/quote/caption buffers → no sentence gluing.
5. **`subheadline = None`** — meta description no longer mapped; verified 0
   non-None subheadline across the corpus.

## Verification after rebuild (same 150 URLs, seed 20260913)

- 150/150 unique `article_id`; 150 snapshot files (article_id-named).
- Former FAIL records now complete: regatta 11 ¶ / 1086 chars; "Бебе пред
  елхата" 5 ¶ / 1317 chars.
- Collision pairs now distinct: 7720 → `1428c0b2…`/`159770f1…`;
  6057 → `ef3e8c0d…`/`8f09db3d…`.
- Glued `<word>.<Word>` signatures corpus-wide: **0**.
- `subheadline` non-None: **0**.
- `missing_body: 0` · `parse_failure_count: 0` · bands/author split unchanged
  (25/30/35/60 · house 83 / named 59 / unknown 8).
- QA sample: 30 + 10 spot checks, **0 critical errors**.
- Tests: **186 passed**; ruff clean.

## New staged snapshot (frozen only after re-review)

```
sha256_bytes     = 5b5cd0622b436646d793492baf4b94b45f1bc4dae6ede0e578f12205ed4ef9b6
sha256_canonical = d32629ae7e9d3b726a0264056a37c7fa550dfbf6272cf25d34cc51718bfdbcba
article_count    = 150   sampling_seed = 20260913   sampling_version = m2.1b-sampling-1
```

## Re-review list (per M2.1C step 6)

- All 30 records in `var/style_corpus/qa_review.md` (regenerated; bodies now
  include the previously-missing `<div>` content; verdicts blank).
- Appendix: the 4 identity-collision records (3 not in the 30 sample) with
  full fields + verdict lines.

## Files changed (corrective step)

- `src/editor_assistant/style/extract.py` — identity, frame-based body, `<br>`
  boundary, `subheadline=None`.
- `src/editor_assistant/style/fetch.py` — article_id snapshot naming.
- `tests/test_style_pipeline.py` — snapshot-name fix + M2.1C regressions
  (URL-based identity, div-body DOM order, br boundary, subheadline=None,
  unique snapshots for colliding post_ids).
- `fixtures/style/legacy_div_body.html` — new offline fixture (bare `<br>` form).
- `var/style_corpus/*` — rebuilt: articles.jsonl, manifest.json,
  qa_sample.jsonl, qa_review.md (+collision appendix), corpus_snapshot.json,
  duplicates.json; `raw/` (article_id names), `raw_m21b_v1/` (M2.1B evidence).

## Untouched

Sampling seed/version, `candidates.jsonl`, `selected_urls.jsonl` (same 150
URLs), legacy `make_article_id`, frozen Radar, all non-style modules.

## Next gate

Human re-review of the 30 QA records + 4 collision-pair records.
If `critical_failures == 0` → fold `corpus_snapshot` into `manifest.json`,
freeze, declare **M2.1 — STYLE CORPUS DONE**, STOP. Else → smallest
corrective step only, no M2.2.
