# Proposal — research should search like a person, not re-fetch the story it has

Date: 2026-10-02 · Status: **PROPOSAL, not implemented** · No code changed for
item 3. The owner asked for this to be reviewed before it is built, because it
changes search behaviour rather than a diagnostic.

## 1. What was measured

Decoded from the append-only search audit
(`var/editorial_workflow/search_runs/run-*.jsonl`, 876 runs, 513 recorded
queries). This is what actually went to Google for the real story
`s068227d4dd9391a`:

```
q=БСУ отваря нови хоризонти с португалски и китайски език - Бургаски свободен университет Бургас
```

Three defects are visible in that one line:

1. **The model's questions are never used as queries.** The round asked
   *"Кой отворен авторитетен източник подкрепя основното твърдение?"* and
   *"Кога и къде се е случило..."* — then searched for the headline instead.
   The questions are written to the store and displayed, which made them look
   like the agent thinking. They are not.
2. **` - ` is a NOT-term to Google.** 98 of 513 recorded queries contain it, so
   the query excludes the publisher's own name from its own story.
3. **The queries are sentences.** 372 of 513 exceed 60 characters. A person
   types 2–4 words; so does a good search.

## 2. Why it happens (traced to one function)

`event_search.event_anchors()` builds the anchors every query tier is derived
from. Run against that exact title:

```
subject  : БСУ отваря нови хоризонти с португалски и китайски език - Бургаски свободен университет
entities : ['Бургаски']          <-- "БСУ" NOT found
terms    : ['отваря','хоризонти','португалски','китайски','език','бургаски', ...]
road     : ''
```

so every tier collapses onto the raw title:

```
"БСУ отваря нови хоризонти с португалски и китайски език - Бургаски свободен университет"
"... - Бургаски свободен университет" site:bfu.bg
```

Two independent causes:

- **`subject` is the uncleaned title.** The ` - Publisher` suffix is never
  stripped, so it is quoted verbatim and read as an exclusion.
- **The entity extractor misses all-caps acronyms.** `БСУ` is the single most
  identifying token in the story and it is not in `entities`. Only "Бургаски"
  was found — a common word, not the actor.

Tier 2 ("entity + action + locality") therefore has no entity to work from and
never fires. The ladder is well designed; it is being fed nothing.

## 3. What is NOT broken

Stated so the fix is not aimed at the wrong thing:

- **Serper works.** 228 of 876 runs issued a Serper query against Google News'
  513. The provider chain (`google_news_rss → tinyfish → serper → ddgs`) is
  live and falls back correctly.
- **The claim gate works.** 8 claims were dropped for want of independent
  corroboration, which is the rule doing its job.
- **Page opening works.** Pages are fetched (`FETCH_OK`); they are just not
  *found*.

## 4. Proposed change (three parts, each independently testable)

**(a) Clean the title.** Strip the trailing ` - Publisher` from `subject` before
any tier uses it, and stop emitting it as a NOT-term. Keep the full title for
display. *Smallest change with the largest effect.*

**(b) Recognise acronyms as entities.** `БСУ`, `ОД`, `МВР` are the strongest
anchors in Bulgarian news and the extractor currently skips them. Add an
all-caps-token rule (2–6 chars, not a common word) to `_entities()`.

**(c) One query per question — the actual change in behaviour.** This is the
part that makes the agent behave like you do, and the part most worth arguing
about:

- currently: 1 query built from the headline, per round
- proposed: derive 2–4 keyword terms from **each** model question, run them as
  **independent** queries, open the top publisher pages from the union, then let
  the claim gate decide what survives

The questions stop being decoration and become the plan.

## 5. Open questions for the owner

1. **Query budget.** (c) multiplies queries per round. Today the round spends a
   bounded Serper allocation (`MAX_SERPER_QUERIES_PER_ROUND`). Should one round
   be allowed to spend the whole budget across its questions, or stay at one
   query per question with a hard cap?
2. **Rate limiting.** More queries per story against Google News RSS invites
   throttling. Should the extra queries go to Serper preferentially rather than
   the keyless chain?
3. **Latency.** A round with 5 questions × 3 keywords could take minutes. Is
   that acceptable, or should the first question's results short-circuit?
4. **Language.** Should keywords be generated in Bulgarian only, or should the
   entity/acronym terms be tried in both?

## 6. How it would be verified (not asserted)

- A test pinning that a ` - Publisher` suffix never reaches a query string.
- A test pinning that `БСУ` is found as an entity.
- A recorded-run comparison: query count, distinct hosts opened, and facts
  gathered per round, before vs after — on real stories, not mocks.
- The existing `research-trace` store already records every considered page, so
  the improvement is measurable from data the product already keeps.

## 7. What I did do in this slice (items 1 and 2, shipped)

- **Reasoning is now parsed and reported.** `delta.reasoning` /
  `delta.reasoning_content` are counted and surfaced; they are never returned as
  the answer. A model that spends its budget thinking now logs
  `SPENT_BUDGET_ON_REASONING` instead of a bare `EMPTY_OUTPUT`.
- **A raised token ceiling was tried, measured, and REVERTED.** 32768 produced
  `completion_tokens=32768` (the full budget), 101 417 chars of reasoning, zero
  content, in 292 s. The one 352 s success was the exception, not the rule.
  `OPENROUTER_MAX_TOKENS` stays at 8192 and a test pins that negative result.
- **Lesson recorded:** a single successful run was reported to the owner as a
  fix. It was one sample out of four. Run counts, not single observations
  (AGENTS.md rule 8).
So this is a query-construction defect, not a scraping or provider defect.