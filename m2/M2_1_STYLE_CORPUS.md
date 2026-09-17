# M2.1 — Chеrnomorie Style Corpus

## Goal

Build a clean, inspectable corpus of published Chеrnomorie articles.

```text
published archive
→ fetch/import
→ article extraction
→ normalization
→ ArticleRecord
→ local corpus
→ manual QA
```

No draft generation, style synthesis, embeddings, or fine-tuning.

## Start small

Pilot sample:

```text
100–300 articles
```

Cover several categories, dates, house-signed pieces, and named authors.

## ArticleRecord contract

```text
article_id
url
published_at
author
category
headline
subheadline
lead
body
quotes
tags
source_type = "chernomorie_archive"
```

Missing values remain explicit.

## Extraction rules

Extract article content only.

Exclude where possible:
- navigation
- footer
- related-story cards
- ads
- share buttons
- sidebars

Preserve published wording. Do not rewrite, summarize, or paraphrase.

## Author handling

Preserve author exactly as published. Keep house-signed and named-author material separate.

## Category handling

Preserve original site category. Do not invent semantic categories yet.

## Duplicate detection

At minimum inspect:
- canonical URL
- headline + date
- normalized body hash

Record duplicates; do not silently destroy evidence.

## Storage

Use inspectable JSONL or SQLite. No vector DB in M2.1.

## Corpus manifest

Report:
- total articles
- date range
- category counts
- author counts
- missing author/date/body
- duplicate count
- parse failure count
- median body length

## QA sample

Manually inspect at least 30 articles for:
- headline
- author
- date
- category
- body start/end
- no nav/footer pollution
- Bulgarian characters
- missing paragraphs
- URL

## Failure quarantine

Store failures separately with:
- url
- failure_type
- failure_detail
- observed_at

## Tests

Cover:
1. valid extraction
2. missing author
3. missing category
4. Bulgarian Unicode
5. multi-paragraph body
6. quote preservation
7. metadata cleanup
8. navigation exclusion
9. deterministic normalization
10. duplicate detection
11. malformed page quarantine
12. re-run stability

## Verification Gate

PASS only if:
- pilot corpus exists
- 30-article QA completed
- parse pollution is low
- duplicates understood
- no generation code exists
- frozen Radar untouched
- tests pass
- corpus manifest reproducible

## Result Report

```markdown
# M2.1 Report

## Corpus size
## Date coverage
## Category coverage
## Author coverage
## Extraction contract
## Files changed
## Tests run
## Test result
## 30-article QA
## Duplicate findings
## Parse failures
## Corpus manifest
## Frozen Radar verification
## Known limitations
## Verdict
## Recommended next smallest step
```

Then STOP.
