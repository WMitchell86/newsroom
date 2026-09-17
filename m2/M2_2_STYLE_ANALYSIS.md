# M2.2 — Style Analysis

## Goal

Measure and describe how Chеrnomorie writes.

```text
clean ArticleRecord corpus
→ deterministic style metrics
→ grouped profiles
→ AI-assisted synthesis
→ human-reviewed StyleProfile
```

No article generation yet.

## Deterministic metrics first

### Headline
- character length
- word count
- verb presence
- numbers
- location mention
- punctuation
- colon/question/quote frequency

### Lead
- sentence count
- character length
- overlap with headline
- first sentence length

### Body
- paragraph count
- average paragraph length
- average sentence length
- quote frequency and position
- number/date formatting
- institution naming patterns

### Structure
- headline → lead → context
- immediate-fact openings
- quote placement
- background placement
- closing pattern

## Grouping

Analyze separately where sample size supports it:

```text
HOUSE_NEWS
AUTHOR_<name>
CULTURE
EVENT
BUSINESS
SPORT
FEATURE / INTERVIEW
```

Small groups remain insufficient data.

## House vs author style

Explicitly compare house-signed, named authors, and category effects.

## AI-assisted synthesis

Only after metrics exist, allow an LLM to summarize patterns into a StyleProfile.

## StyleProfile contract

```yaml
profile_id:
scope:
sample_size:
headline:
lead:
paragraphs:
sentence_style:
quotes:
numbers_dates:
locality_language:
common_patterns:
avoidances:
confidence_notes:
example_article_ids:
```

Avoid vague labels unless translated into measurable behavior.

## Manual review

Review at least:
- 1 house profile
- 1 named-author profile
- 1 category profile

For each, inspect 10 articles.

## Verification Gate

PASS only if:
- metrics reproducible
- profiles grounded in corpus
- house vs author differences explicit
- vague claims minimized
- human review completed
- no generation introduced
- frozen Radar untouched

Then STOP.
