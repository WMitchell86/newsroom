# AI Harness Prompt — Search Reliability Foundation + Generic YouTube Transcript Batch

## Context

Continue the current Chеrnomorie Editorial AI repository.

The current editorial state is frozen while human editor review is pending:

```text
EDITORIAL_READINESS_ENGINEERING = PROVEN
EDITORIAL_READINESS_EDITORIAL_EFFECTIVENESS = PENDING
```

Do NOT change:

```text
SITE DNA
VOICE profiles
MODE profiles
editorial-value threshold
semantic-veto policy
hook guidance
reader-interest rules
editor feedback interpretation
```

Do NOT start LIVE cases 6–10 as new editorial pilot cases.

This phase is infrastructure/capability work only.

The repository audit found two concrete foundation gaps:

```text
A. no stable production web-search provider/executor
B. no generic timestamp-preserving YouTube transcript discovery pipeline
```

Fix those two gaps, validate them, run a read-only transcript batch, and STOP.

---

# PART A — SEARCH RELIABILITY FOUNDATION

## A1. Preserve current separation

Keep:

```text
workflow/research.py
```

as the research contract / SourceBundle / provenance layer.

Do not turn it into a giant network module.

Add small dedicated modules, using names that fit the existing repository, conceptually:

```text
sources/web_fetch.py
workflow/search.py
```

or equivalent.

Do not modify the frozen RSS/Radar fetcher behavior in:

```text
sources/fetcher.py
```

Radar remains frozen.

---

# A2. Implement a real SearchProvider contract

Add an inspectable provider interface.

Conceptual input:

```yaml
query:
country:
search_language:
freshness:
count:
domains_optional:
```

Conceptual result:

```yaml
provider:
query:
started_at:
completed_at:
status:
results:
  - rank:
    title:
    url:
    snippet:
    published_at:
    source_name:
failure:
```

The exact schema may follow repository conventions.

Important:

> Search result snippets are discovery-only and remain non-promotable evidence.

The existing SourceBundle provenance rule stays unchanged.

---

# A3. Do not scrape consumer search HTML as the primary search engine

The LIVE run already showed Bing consent/blocked-result behavior.

Do not build production discovery around:

```text
https://www.bing.com/search?q=...
https://www.google.com/search?q=...
```

Use an API-backed provider.

Preferred first implementation:

```text
Brave Search API
```

if `BRAVE_SEARCH_API_KEY` is available.

Add environment configuration only; never commit secrets:

```text
SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=
```

The provider must use stdlib HTTP if possible; no new dependency is required merely for convenience.

If the key is missing, return:

```text
SEARCH_CAPABILITY_UNAVAILABLE
```

Do not fabricate results.

Design the provider interface so another provider can be added later without touching research/editorial logic.

---

# A4. Search failure taxonomy

Introduce explicit operational outcomes.

At minimum:

```text
SEARCH_OK
SEARCH_CAPABILITY_UNAVAILABLE
SEARCH_PROVIDER_ERROR
RATE_LIMITED
NO_RESULTS
QUERY_EXHAUSTED
SOURCE_ACCESS_BLOCKED
SOURCE_FETCH_FAILED
SOURCE_PARSE_FAILED
```

Do not collapse them into `NO_RESULTS`.

Persist:

```text
HTTP/status where available
Retry-After where available
provider
query
attempt
elapsed time
result count
```

No secrets in logs.

---

# A5. Retry behavior

Keep retries bounded.

Suggested:

```text
429:
  respect Retry-After when reasonable
  maximum 2 provider attempts in one operation

500/502/503:
  bounded retry

401/403:
  classify, do not loop aggressively

NO_RESULTS:
  optionally reformulate query once
```

Do not build a complex scheduler.

---

# A6. Generic opened-page fetcher

Add a separate read-only web page fetcher for research sources.

It should support at least:

```text
text/html
application/xhtml+xml
text/plain
```

with:

```text
timeout
size limit
redirect handling
user agent
explicit failure category
final_url
content_type
```

Do not reuse/relax the RSS-specific XML fetcher.

Safety:

- HTTP/HTTPS only;
- reject localhost/private-network targets;
- bounded response size;
- no JavaScript execution;
- GET only.

The purpose is source opening/extraction, not browser automation.

---

# A7. Preserve semantic editor-request constraints

A failed provider/source must never silently change the task.

Example:

```text
request:
today's Burgas story from major national Bulgarian media
```

If national-media search fails:

BAD:

```text
silently switch to municipality event calendar
```

GOOD:

```text
SEARCH_INCOMPLETE
reason: national-media constraint not satisfied
```

A fallback candidate may be used only when it still satisfies the original editor-request constraints.

Persist those constraints in the research operation.

---

# A8. Query planning

Implement small semantic query planning, not a generic agent framework.

Input may include:

```text
topic
missing_dimensions
research_questions
source preference
freshness
location
```

Output:

```text
1–3 queries maximum per round
```

Examples are regression guidance only:

```text
event + organizer + Burgas
event + schedule
topic + official source
```

Do not hardcode Royal Boxing, DOCK or any current LIVE case.

For Bulgarian local research, support:

```text
country=BG
search_language=bg
```

when the provider supports them.

---

# A9. Search result → source opening

A provider result is never enough for evidence.

Flow:

```text
SearchResult
→ candidate
→ open URL
→ extract page text
→ relevant claims
→ SourceBundle.open_source()
```

Only the opened source can become PRIMARY/CORROBORATING evidence.

Persist the distinction clearly.

---

# A10. Search observability

Create a small append-only or per-run search audit artifact, conceptually:

```text
var/editorial_workflow/search_runs/
```

Store:

```text
query
provider
constraints
status
results returned
selected URLs
open/fetch status
failure category
```

Do not store API keys or authorization headers.

---

# A11. Known-answer diagnostic benchmark

Create a small benchmark of roughly 12–20 queries.

Purpose:

```text
diagnose search capability
```

not:

```text
train editorial behavior
```

Include:

- several known current/local sources from the previous pilot as regression examples;
- several different/unseen Bulgarian local queries;
- exact-domain expectations only when the target is known to exist.

Measure:

```text
target/domain discovered in top N?
usable result count
source open success?
failure type
latency
```

Do not make the benchmark the query planner's rule base.

If no search API key is available, all live provider tests must clearly SKIP / report capability unavailable rather than pretending success.

---

# PART B — TIMESTAMPED YOUTUBE TRANSCRIPT FOUNDATION

## B1. Raw SRT becomes authoritative

The repository currently contains 7 Bulgarian:

```text
var/youtube_transcripts/raw/*.bg-orig.srt
```

Use these as the first batch.

Do NOT use:

```text
transcripts_2026-09-16/*.md
```

as authoritative machine input because `clean_subs.py` intentionally removed timestamps.

Those Markdown files may remain for human readability.

---

# B2. Add a proper TranscriptDocument

Implement a generic contract conceptually like:

```yaml
transcript_id:
source_url:
title:
language:
origin:
trust_level:

segments:
  - segment_id:
    cue_index:
    start_ms:
    end_ms:
    raw_text:
    normalized_text:
```

`trust_level` vocabulary should include at least:

```text
AUTO_CAPTION
HUMAN_TRANSCRIPT
HUMAN_VERIFIED
OFFICIAL_VERBATIM
```

The current YouTube SRT files are:

```text
AUTO_CAPTION
```

unless explicitly marked otherwise.

---

# B3. Parse standard SRT correctly

Add a deterministic SRT parser.

Requirements:

```text
sequence number
start timestamp
end timestamp
caption text
```

must be preserved.

Do not pass raw SRT directly to the existing custom-cue parser.

Tests must prove that:

```text
00:06:21,000
```

becomes an exact transcript locator/span.

---

# B4. Time-aware overlap normalization

Auto-caption SRT often overlaps.

Normalize for analysis while retaining provenance.

Do not simply concatenate duplicate caption text.

Each normalized claim/topic span must still map back to one or more original:

```text
segment_id / start_ms / end_ms
```

Do not mutate the raw transcript.

---

# B5. Keep `clean_subs.py` only as a presentation helper

Its current purpose is human-readable text.

Update comments/docs so nobody treats its output as authoritative evidence.

If useful, make it consume TranscriptDocument and render readable Markdown, but do not let it destroy the only timestamped copy.

---

# B6. Auto-caption reliability guard

Current council safeguards treat a PRIMARY transcript as enough for decision claims.

Refine this generically.

For `AUTO_CAPTION`, mark high-risk claims as requiring corroboration before publication when they concern:

```text
final adopted/rejected/approved decision
material numbers / money
critical personal or organization names
exact quotations
legal/institutional status
negation-sensitive claims
```

The transcript may still establish:

```text
candidate story
research question
topic discussed
possible angle
```

but should not automatically establish a fragile exact fact when ASR error can reverse meaning.

Human-verified or official-verbatim transcripts can carry more authority.

Do not hardcode any committee/case.

---

# B7. Add generic transcript segmentation

The product unit is:

```text
meeting
→ topic / agenda segments
→ candidate developments
```

not:

```text
meeting
→ one article
```

Build a small generic segmentation layer.

Use deterministic cues when available:

```text
точка първа
втора точка
дневен ред
преминаваме към
```

but do not depend exclusively on those exact words.

Fallback can use semantic/model-assisted boundaries constrained to transcript segment IDs.

Output each topic with:

```text
topic_id
start segment/time
end segment/time
short neutral topic label
```

No article writing here.

---

# B8. Add autonomous candidate fact extraction

This is the missing step before `angles.assess_angles()`.

For each topic segment:

```text
TranscriptDocument segment(s)
→ grounded candidate facts
```

Use the existing model infrastructure if useful.

Hard requirements:

- no web/model-memory facts;
- every extracted fact references transcript segment IDs/timestamps;
- uncertainty/ASR ambiguity must be marked;
- no factual correction by model memory;
- names/numbers may carry risk flags.

Do not manually predefine facts for each committee.

---

# B9. Add autonomous candidate-angle discovery

Current `angles.assess_angles()` remains the validator/ranker.

Add a preceding step that proposes up to 3–5 real candidate angles from the grounded extracted facts.

Every proposed angle must already satisfy the current contract:

```text
angle_id
title
new_proposition
fact_ids
reason
scores
semantic_status / veto if appropriate
research_questions if NEEDS_RESEARCH
```

Do not weaken `angles.assess_angles()`.

The model proposes; the deterministic gate validates.

No padding angles merely to reach 3.

If fewer than 3 plausible topics exist for a segment/meeting, allow a controlled:

```text
INSUFFICIENT_CANDIDATE_ANGLES
```

path rather than inventing topics.

If needed, update the existing 3–5 contract carefully so that `NO_PUBLISHABLE_ANGLE` can be reached without fabricated padding.

Document the change.

---

# B10. Agenda/document enrichment seam

Do not build a council crawler yet.

Provide a seam so candidate topics can later be enriched with:

```text
official agenda
dokladna
protocol
decision
```

using the new Search Foundation / direct official URLs.

For this batch, absence of those documents may legitimately produce:

```text
RESEARCH_MORE
```

especially for auto-caption decision/number claims.

---

# B11. Do not generate articles in the first transcript batch

This phase tests:

```text
Can the system discover the news?
```

not:

```text
Can it write seven articles?
```

Run:

```text
SRT
→ timestamped evidence
→ topics
→ candidate angles
→ readiness
```

and STOP.

No draft model calls are required after readiness.

---

# PART C — BATCH RUN ON ALL 7 EXISTING BG TRANSCRIPTS

Use every current:

```text
var/youtube_transcripts/raw/*.bg-orig.srt
```

There are 7 recordings.

Do not use manually hardcoded facts/angles from:

```text
tmp/committee_cases.py
```

for the new batch.

Keep that script as historical experimental evidence or mark it deprecated.

The new batch must discover its own facts/angles.

---

# C1. Per-recording output

Create a deterministic artifact per recording, conceptually:

```text
var/transcript_analysis/<video_id>.json
```

containing:

```yaml
video_id:
source_url:
title:
duration:
trust_level:

topics:
  - topic_id:
    start:
    end:
    label:
    extracted_facts:
    candidate_angles:
    readiness:
    missing_research:
    risk_flags:
```

---

# C2. Batch summary

Create:

```text
m2/review/TRANSCRIPT_DISCOVERY_BATCH_REPORT.md
```

Report:

```text
7 transcripts attempted
7 parsed?
timestamp provenance coverage
topic counts
candidate angle counts

readiness totals:
DRAFT_READY
RESEARCH_MORE
NO_PUBLISHABLE_ANGLE
EDITOR_DECISION_REQUIRED

high-risk ASR claims
decision claims needing corroboration
number/name claims needing corroboration

per-recording summary
```

Do not present readiness totals as editorial-quality proof.

This is an engineering/discovery benchmark only.

---

# C3. Manual audit sample

For each of the 7 recordings select:

```text
1 strongest candidate
1 rejected / no-story candidate where available
```

Produce a human-readable audit file with:

```text
candidate proposition
timestamp links/spans
transcript excerpt
readiness decision
why
```

This is for us to inspect before involving the editor.

Do not send this batch to the real editor yet unless explicitly requested later.

---

# PART D — TESTS

Add focused tests.

## Search tests

At minimum:

```text
provider success normalization
missing API key -> SEARCH_CAPABILITY_UNAVAILABLE
429 -> RATE_LIMITED
Retry-After respected/bounded
403 -> SOURCE_ACCESS_BLOCKED or provider error as appropriate
no results != provider failure
query constraints persist through fallback
HTML page fetch success
oversized page rejected
private/local network URL rejected
search snippet cannot become evidence
```

## Transcript tests

At minimum:

```text
standard SRT parsing
exact start/end timestamp preservation
overlapping caption normalization
raw -> normalized provenance binding
AUTO_CAPTION trust level
high-risk decision claim requires corroboration
HUMAN_VERIFIED transcript may satisfy stronger provenance
topic segmentation on agenda-style transcript
topic segmentation fallback without agenda numbering
candidate fact refs point to real transcript segments
candidate angle refs point to real fact IDs
no hardcoded entity requirement
```

Keep existing 313 tests green.

Run full pytest.

Run Ruff in the development environment.

---

# PART E — IMPORTANT NON-GOALS

Do NOT:

```text
change editor profiles
change readiness thresholds
change hook guidance
learn from pending editor feedback
start LIVE 6–10 editorial cases
generate articles from all seven transcripts
build a crawler
build a vector database
build a scheduler
integrate auto-publishing
rewrite the user's external transcriber
```

The user's existing transcriber can be connected later through:

```text
YouTube URL
→ external transcriber
→ raw SRT / timestamped TranscriptDocument
→ this pipeline
```

For now, use the seven raw SRTs already in the repo.

---

# PART F — REPORTING / STOP

Create:

```text
m2/review/SEARCH_RELIABILITY_AUDIT.md
m2/review/TRANSCRIPT_DISCOVERY_BATCH_REPORT.md
```

Update:

```text
MILESTONE.md
handoff.md
```

with a clear split:

```text
SEARCH_EXECUTION_ENGINEERING = PROVEN / PROMISING / NOT_PROVEN
TRANSCRIPT_DISCOVERY_ENGINEERING = PROVEN / PROMISING / NOT_PROVEN
EDITORIAL_EFFECTIVENESS = still PENDING editor review
```

Then STOP.

Do not continue to drafting or new LIVE pilot cases.

---

# Core principles

Search:

> Infrastructure failure is never evidence that information does not exist.

Transcript:

> Automatic captions are discovery evidence, not automatically perfect factual authority.

Editorial:

> The system must discover a story before it is allowed to write one.

Generalization:

> Do not encode the answers from the seven committee recordings into the implementation. They are a test corpus, not a rule book.
