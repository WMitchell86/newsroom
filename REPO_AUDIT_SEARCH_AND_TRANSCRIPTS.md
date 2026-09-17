# Repo Audit — Search Reliability + YouTube Transcript Foundation

## Scope

Audit of the uploaded `media` repository with focus on:

1. web search / research reliability;
2. source fetching and failure handling;
3. targeted research-loop execution;
4. YouTube transcript ingestion and provenance;
5. feasibility of batch-testing all available committee transcripts.

Validation in the audit environment:

- `PYTHONPATH=src pytest -q` → **313 passed**
- Ruff could not be rerun because `ruff` is not installed in the audit runtime; the repository report states it was clean in the source environment.

---

# Executive verdict

The user's suspicion about search is correct.

The repository currently has a strong **research contract layer**, but it does **not** yet have a real production web-search capability.

Conceptually the code says:

```text
web discovery
→ SourceBundle
→ EvidencePacket
```

but the stable `src/` implementation currently starts effectively at:

```text
already discovered candidate/source
→ SourceBundle
→ EvidencePacket
```

Actual discovery/search in the LIVE runs was performed outside the stable product layer by harness/browser/manual temporary scripts.

That explains the inconsistent behavior around Bing consent pages, BTA 429s, inaccessible organizer pages and silent fallback to unrelated candidate types.

The transcript side has a similar boundary gap:

```text
raw YouTube SRT
→ ??? 
→ cleaned transcript / hand-authored facts and angles
→ readiness
```

The repository already has useful timestamp/provenance logic, but the current batch experiment bypasses it by reading cleaned Markdown files that have had all SRT timestamps removed. The batch script also hardcodes facts and candidate angles for each committee, so it is not yet a generic transcript-news discovery test.

The next engineering work should therefore focus on **Search Reliability Foundation + Timestamped Transcript Pipeline**, while leaving editorial profiles/readiness thresholds/hook rules frozen until editor feedback arrives.

---

# A. Search / research audit

## A1. `workflow/research.py` is a contract layer, not a search engine

`src/editor_assistant/workflow/research.py` defines:

- SourceBundle structure;
- candidate records;
- source authority;
- provenance;
- duplicate state;
- transcript intake;
- council safeguards.

It contains no search-provider client and no operation that takes a query and returns web results.

`make_bundle()`, `add_candidate()`, `open_source()` and `complete_bundle()` all assume discovery has happened elsewhere.

This is good separation, but the module/documentation currently gives the impression that `web discovery` is implemented end-to-end when it is not.

### Consequence

A harness may satisfy the contract using ad-hoc browser/search behavior. Different runs can therefore use completely different discovery mechanisms and failure behavior.

This is exactly what happened in the pilot.

---

## A2. `live-readiness --round` records research; it does not perform it

In `src/editor_assistant/workflow/cli.py`, `live-readiness --round` loads:

```text
missing_dimensions
research_questions
sources
```

from a supplied JSON payload and records the research round.

It does not:

- formulate web queries;
- invoke a provider;
- fetch results;
- classify provider errors;
- open sources;
- extract relevant claims;
- enrich the EvidencePacket.

So the current loop is:

```text
readiness says RESEARCH_MORE
→ external human/harness does something
→ CLI records what was done
```

rather than:

```text
readiness says RESEARCH_MORE
→ research engine performs targeted search
→ evidence is enriched
→ readiness reruns
```

This is the largest functional gap in the current agentic research design.

---

## A3. The only general network fetcher is intentionally RSS/XML-only

`src/editor_assistant/sources/fetcher.py` is an M1 RSS fetcher.

Its behavior is appropriate for Radar, but not for web research:

- no retries;
- no research failure taxonomy;
- blocks unrelated-host redirects;
- content type is restricted;
- body must begin with `<`;
- optimized for RSS/XML;
- default maximum 512 KiB.

It should **not** be expanded in-place into the newsroom web fetcher because Radar is frozen and has different safety requirements.

Create a separate HTML/web-source fetcher.

---

## A4. No stable search-provider configuration exists

`pyproject.toml` has zero runtime dependencies.

`.env.example` contains no:

```text
SEARCH_PROVIDER
BRAVE_SEARCH_API_KEY
TAVILY_API_KEY
...
```

There is therefore no stable provider contract in the application.

The actual search behavior in recent runs came from the harness/runtime, not from the project.

---

## A5. Search-engine HTML scraping is already failing in practice

The recorded LIV-03 research round attempted a Bing search URL and reported:

```text
search engines unavailable from environment
consent / blocked results
```

This is expected behavior for scraping consumer search-result pages from an automated runtime.

Do not make Bing/Google HTML scraping the production discovery strategy.

Use an API-backed search provider.

A suitable first provider is Brave Search API:

- real web/news search API;
- country/language targeting;
- freshness filters;
- normal machine-readable results.

A second adapter can be added later if needed.

The provider abstraction matters more than the brand.

---

## A6. Failure taxonomy is too coarse

Current research `FAILURE_REASONS` includes:

```text
ACCESS_BLOCKED
SOURCE_UNRELIABLE
INSUFFICIENT_EVIDENCE
...
```

but search infrastructure needs to distinguish at least:

```text
SEARCH_CAPABILITY_UNAVAILABLE
SEARCH_PROVIDER_ERROR
RATE_LIMITED
NO_RESULTS
QUERY_EXHAUSTED
SOURCE_ACCESS_BLOCKED
SOURCE_FETCH_FAILED
SOURCE_PARSE_FAILED
```

Why this matters:

```text
no result exists
```

is not equivalent to:

```text
provider returned HTTP 429
```

and neither is equivalent to:

```text
search found the page but the page fetch was blocked
```

The system must never translate infrastructure failure into editorial absence.

---

## A7. LIV-05 demonstrates bad fallback semantics

The task was:

```text
today's Burgas-region story from major Bulgarian national media
```

BTA returned 429.

The workflow then selected Burgas Municipality stories.

That may produce a valid article, but it changes the experiment.

Required general rule:

> Research failure must not silently change the semantic class of the editor request.

A fallback candidate must still satisfy the original discovery constraint, or the case should report:

```text
SEARCH_INCOMPLETE / EDITOR_DECISION_REQUIRED
```

---

## A8. Search audit tests are currently contract-only

Current tests strongly cover:

- provenance;
- snippets cannot become evidence;
- duplicate state;
- council safeguards;
- lineage.

They do not test:

- provider calls;
- 429;
- 403;
- Retry-After;
- query generation;
- result normalization;
- provider fallback;
- HTML source fetch;
- search observability.

That is appropriate because those capabilities do not yet exist, but they are the next testing gap.

---

# B. Transcript audit

## B1. Good news: seven Bulgarian raw SRT transcripts are already present

The repo contains seven `*.bg-orig.srt` committee recordings from 2026-09-16.

Combined:

- about **9,704 raw caption words**;
- about **90 minutes** of recording;
- committees covering social activities, healthcare, economy/investment, culture, science/innovation, education and tourism.

This is enough for a useful first batch benchmark.

---

## B2. `clean_subs.py` destroys the provenance we now need

`var/youtube_transcripts/clean_subs.py` explicitly removes timestamps.

That was reasonable when the goal was human-readable text.

It is no longer acceptable as the authoritative machine-analysis input because we now need:

```text
claim
→ exact transcript time
```

The cleaned Markdown files may remain as human-readable previews.

The authoritative pipeline should use raw SRT.

---

## B3. `ingest_transcript()` does not parse standard SRT

`workflow/research.py` can preserve custom cue formats such as:

```text
0:44 text...
8:13 text...
```

but it does not parse standard SRT blocks:

```text
31
00:01:31,280 --> 00:01:36,040
...
```

A direct audit run on the raw healthcare SRT produced claims containing the literal SRT sequence numbers and arrow timestamps, with only coarse locators such as:

```text
chunk:0-2000
```

Therefore a proper `parse_srt()` / `TranscriptDocument` adapter is required before batch analysis.

---

## B4. Current committee batch is not generic

`tmp/committee_cases.py` is useful experimental work, but it manually defines for each committee:

- facts;
- keywords used to locate them;
- 3–5 candidate angles;
- rubric scores and editorial explanations.

This means the test already knows what to look for.

It does **not** prove:

```text
arbitrary transcript
→ AI discovers candidate news
```

It proves:

```text
human-preselected facts/angles
→ existing angle/readiness contracts behave correctly
```

Keep it as historical experimental evidence, but do not use it as the generic batch benchmark.

---

## B5. There is no autonomous angle-discovery step in `src/`

`angles.assess_angles()` is a validator/ranker.

It deliberately expects 3–5 supplied candidate judgments.

This is good architecture, but a missing capability exists before it:

```text
TranscriptDocument
→ candidate developments
→ candidate facts
→ 3–5 grounded angle proposals
```

This should be model-assisted but strictly source-bound:

- every extracted fact points to transcript segment IDs/timestamps;
- every angle references fact IDs;
- model memory cannot create evidence;
- uncertainty stays explicit.

---

## B6. Automatic captions need reliability metadata

The raw YouTube subtitles contain obvious ASR errors.

Examples include malformed:

- names;
- numbers;
- negation;
- institutional phrases.

This creates special risk around statements such as:

```text
приема / не приема
5 млн. / 15 млн.
person names
company names
```

The current council validator treats any PRIMARY transcript as sufficient provenance for decision claims.

For auto-caption material that is too permissive.

Introduce transcript provenance quality:

```text
AUTO_CAPTION
HUMAN_TRANSCRIPT
HUMAN_VERIFIED
OFFICIAL_VERBATIM
```

For `AUTO_CAPTION`, high-risk claims should require corroboration before they can support publication:

- final decision/adoption/rejection;
- material numbers;
- personal names where identity matters;
- exact quotes;
- legal/institutional status.

The transcript can still be enough to discover the story and formulate research questions.

---

# C. Recommended next architecture

Do not touch:

```text
SITE DNA
VOICE profiles
MODE profiles
editorial-value threshold
hook guidance
editor-readiness semantics
```

while editor review is pending.

Build two independent foundations.

## Track S — Search Reliability Foundation

```text
ResearchQuestion
→ QueryPlan
→ SearchProvider
→ SearchResult[]
→ opened SourcePage
→ extracted claims
→ SourceBundle
```

Key pieces:

```text
SearchProvider interface
SearchOutcome / SearchFailure taxonomy
API-backed provider
generic HTML/text fetcher
query/result audit log
retry / Retry-After handling
freshness + BG locale support
semantic-request constraint preservation
known-answer benchmark
```

Do not scrape consumer Bing/Google result pages as the primary provider.

## Track T — Timestamped Transcript Pipeline

```text
raw SRT
→ TranscriptDocument
→ time-preserving deduplication
→ topic / agenda segmentation
→ candidate fact extraction
→ candidate angle discovery
→ angles.assess_angles
→ readiness
```

Do not generate articles in the first batch.

Run all seven existing BG SRTs and inspect:

```text
DRAFT_READY
RESEARCH_MORE
NO_PUBLISHABLE_ANGLE
EDITOR_DECISION_REQUIRED
```

with exact timestamp provenance.

---

# D. Priority findings

| Priority | Finding | Decision |
|---|---|---|
| P0 | No real production search provider | Build before further autonomous research claims |
| P0 | Search failures can silently alter the requested task | Add semantic request constraints + explicit failure states |
| P0 | Current transcript batch is hand-authored | Replace with generic candidate extraction |
| P0 | Clean transcript path removes timestamps | Raw SRT must become authoritative input |
| P1 | Standard SRT is not supported by `ingest_transcript()` | Add timestamped SRT adapter |
| P1 | Auto-caption transcript is treated too strongly for council decisions | Add transcript trust level / corroboration requirement |
| P1 | Research rounds are bookkeeping only | Add executor that can actually enrich evidence |
| P2 | Search provider observability absent | Add query/provider/status/result logs |
| P2 | Duplicate search lives in `tmp/` | Later productize after Search Foundation; not urgent for transcript batch |

---

# E. What can be tested immediately after the foundation work

The seven existing recordings are a good initial batch.

The first batch should answer:

```text
Can the system discover candidate stories from transcripts
without human-preselected facts/angles?
```

Not yet:

```text
Can it write perfect articles from every meeting?
```

Desired output per recording:

```yaml
video:
segments:
candidate_developments:
  - proposition:
    supporting_transcript_refs:
    risk_flags:
    candidate_angles:
readiness:
```

No auto-drafting.

No editor-profile changes.

No threshold learning.

---

# Final audit verdict

The current project is in good condition and the tests confirm the implemented contracts are stable.

The search problem is **not primarily a bad-query problem**. The largest cause is architectural: the product has a research data model but no stable search execution layer.

The transcript opportunity is real, but the existing committee script is still a hand-curated experiment. The repository already contains enough raw data and readiness machinery to build the generic version without reopening the editorial model.

Recommended next work:

```text
SEARCH RELIABILITY FOUNDATION
+
TIMESTAMPED TRANSCRIPT FOUNDATION
→ 7-transcript batch
→ inspect results
→ wait for editor feedback
```
