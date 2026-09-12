# Skill: source-adapter

Source: `AI_HARNESS_EDITOR_ASSISTANT.md` §8.

## Purpose
Add **one** source to ingestion. Never add several sources in one change.

## Required contract (record before coding)
```yaml
source_id:
source_url:
fetch_method:
update_frequency:
parser:
normalizer:
dedupe_key:
failure_behavior:
fixtures:
tests:
```

## Required tests
- valid response
- empty response
- changed content
- duplicate
- timeout
- malformed HTML/XML

## Rules
- Deterministic parsing first (parser/regex/RSS/API/date parsing/hash);
  LLM only for summarize/classify/headline/draft/semantic-dedupe/follow-up.
- One source failure must not break the others (isolate per-source errors).
- New automation runs in shadow mode first (test channel / local mock / log-only).
- Never invent names, numbers, dates, addresses, quotes, titles, causality,
  or institutional positions — missing info is `UNKNOWN`.
