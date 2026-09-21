# Coding Harness Instructions — M4B.1 Stabilization + M4C Story Identity & New Development

## Starting point

Start from the current frozen source/inbox checkpoint reported as:

```text
075e81d
```

Expected current gate:

```text
805 tests
M3A smoke 25/25
M4A/M4B source + inbox engineering = PROVEN
publisher authority correction = PROVEN
```

Primary product objective remains:

> Make tomorrow's work faster and easier for a non-technical editor.

YouTube/M3D remain frozen.

Do not start Telegram in this milestone.

---

# Scope

This run has two tightly bounded parts:

```text
PART 0 — correct five concrete M4B/source-feed issues found in repo review
PART 1 — build M4C Story Identity & New Development
```

Then STOP.

No drafting changes.
No automatic research.
No CMS.
No scheduler daemon.
No embeddings/vector database.
No generic agent framework.

---

# PART 0 — bounded stabilization before story grouping

These are corrections, not a new milestone.

## 0.1 Rolling recency: fix the one-run bootstrap hole

Current behavior:

```text
first successful run:
  <=72h + max10

second run:
  no recency filter + max20
```

That causes old results intentionally excluded on bootstrap to appear on the next run.

### Required behavior

Ordinary news candidates:

```text
EVERY RUN:
  dated items older than NEWS_LOOKBACK_HOURS are excluded

FIRST SUCCESSFUL RUN:
  additional BOOTSTRAP_MAX_NEWS cap

SUBSEQUENT RUN:
  normal MAX_ITEMS_PER_SOURCE cap
```

Use the existing 72h constant unless a directly reproduced reason justifies changing it.

Missing/unparseable dates:
- keep them only within existing caps;
- do not empty an otherwise usable source solely because dates are unavailable.

Do not build a watermark database.

### Required regression

Static provider:

```text
10 recent
10 10-days-old
```

must produce:

```text
run1 → recent only
run2 immediately → no old backfill
```

Run a real isolated immediate rerun after the fix and report whether the former `+100 new` pattern disappears.

---

## 0.2 Calendar semantics must use a real event date or not pretend

Current `calendar=True` logic applies ±45 days to `published_at`.

For Google News:

```text
published_at = article publication time
```

not event time.

### Required behavior

Add optional normalized candidate fields only if a collector genuinely knows them:

```text
event_at
event_end_at
```

Then:

```text
if calendar source AND valid event_at:
    apply event window

else:
    apply ordinary news recency rules
```

Do not infer event dates from article prose in this correction.
Do not write custom calendar scrapers.

Update tests so a fake article publication date is not treated as an event date.

---

## 0.3 Fix “Днес” counts

The Workbench currently labels lifetime inbox totals as:

```text
Днес
```

Compute real Europe/Sofia daily counts.

Recommended surface:

```text
Днес:
  нови
  прегледани
  игнорирани

Непрегледани общо:
  N
```

The default view may still include older `NEW` work so unfinished items are not lost.

Use `published_at` for “published today” only when useful; for newsroom-arrival counts use `discovered_at` on the Sofia local day.

---

## 0.4 Publisher-domain authority conflicts must fail closed

Current `authority_by_domain()` silently keeps the first source ID for a shared domain.

Required:

```text
same domain + same publisher policy
→ allowed

same domain + conflicting kind/factual_authority
→ explicit configuration error
```

Do not choose the stronger authority.
Do not let alphabetical source ID decide authority.

Add a regression test.

---

## 0.5 Blocked-source refusal must inspect `entry.domain`

Before any network call:

```text
entry.url blocked
OR entry.domain blocked
OR explicit query targets blocked domain
→ source BLOCKED
```

Keep the result-level publisher filter as defense in depth.

Do not rely on broad query substring matching alone.

---

## 0.6 Keep monitoring semantics honest in the UI

Do not add a new registry field unless necessary.

Derive collection mode from the existing collector:

```text
rss
→ Директна емисия

google_news_rss
→ Наблюдение чрез Google News
```

Source health for a monitoring query means the monitor worked, not that the publisher website was directly checked.

Use this wording on the Sources page if the current UI would otherwise imply direct collection.

---

# PART 1 — M4C Story Identity

## 1.1 Fundamental identity model

M4C must keep three identities separate.

### Discovery identity

```text
source_id
source_kind
```

Meaning:

> how did the system find this item?

### Publication identity

New M4C-derived concept:

```text
publication_key
publisher_domain
```

Meaning:

> which exact published article/item is this?

### Story identity

```text
story_id
```

Meaning:

> which real-world story/event does the publication belong to?

Never use `source_id` as publication identity.

---

## 1.2 Preserve source items

The current inbox store stays the raw collected-source-item store.

Do NOT replace its rows with clustered stories.

Do NOT rewrite `item_id` to remove `source_id`.

Story storage must reference the existing item IDs.

Recommended shape:

```text
var/newsroom/stories.json
```

or another small atomic file-backed store consistent with the repository.

No database required.

---

# PART 2 — Publication identity

## 2.1 Add a narrow publication identity helper

Suggested module:

```text
workflow/publication_identity.py
```

Purpose only:

```text
InboxItem → publication_key
```

No story semantics.

## 2.2 URL normalization

For ordinary publisher URLs:

- lower-case host;
- strip fragment;
- remove default port;
- remove common tracking parameters:
  - `utm_*`
  - `fbclid`
  - `gclid`
- preserve meaningful query parameters;
- normalize trailing empty slash conservatively.

Do not rewrite arbitrary paths.

For Google News opaque URLs:
- strip query/fragment noise;
- preserve the stable article path/token;
- include `publisher_domain` in the identity input.

## 2.3 Exact identity

Preferred:

```text
publication_key = hash(
  normalized publication URL
  + publisher domain
)
```

independent of `source_id`.

If there is no usable URL:
- do NOT invent exact identity from a vague title;
- return no exact key and let story candidate matching handle it conservatively.

## 2.4 Exact duplicate behavior

Same publication found through three monitors:

```text
3 inbox item_ids
1 publication_key
```

All raw discovery rows stay preserved.

Story UI must count:

```text
discovery_count = 3
publication_count = 1
publisher_count = 1
```

not “3 sources”.

---

# PART 3 — Story store

Create a small explicit story store.

Suggested story fields:

```yaml
story_id:
status: NEW | SEEN | IGNORED

created_at:
first_seen_at:
first_public_at:
last_seen_at:
latest_material_change_at:

representative_item_id:

members:
  - item_id:
    publication_key:
    relation:
    relation_source:
    added_at:
```

Allowed membership relations:

```text
ORIGIN
SAME_STORY
NEW_DEVELOPMENT
RELATED_BACKGROUND
```

Do not store `NEW_STORY` as a membership relation; creating a new story is the action taken when no existing story matches.

If you prefer a separate membership file, keep the same semantics.

Atomic writes.
Strict validation.
Unreadable store must raise, not look empty.

---

# PART 4 — Story IDs and lifecycle

## 4.1 Stable story id

Create the story id from immutable origin identity:

```text
first publication_key
```

or, when no publication key exists:

```text
first item_id
```

Never from generated headline text.

## 4.2 Timestamps

Derive:

```text
first_seen_at
→ earliest discovered_at

first_public_at
→ earliest valid published_at among unique publications

last_seen_at
→ latest discovered_at

latest_material_change_at
→ latest NEW_DEVELOPMENT publication/discovery time
   OR origin time when no development exists
```

Do not fabricate dates.

## 4.3 Representative headline

Do not generate an AI story headline in M4C.

Use a real source-item title.

Recommended:

```text
latest material development title
```

falling back to origin/representative item.

---

# PART 5 — Candidate retrieval: cheap first

Do NOT compare every item semantically to every story.

For each unassigned item:

## Stage A — exact publication

If publication key already belongs to a story:

```text
relation = SAME_STORY
relation_source = exact_publication
```

No model call.

## Stage B — recent story shortlist

Only compare against recent stories.

Start with a simple configurable window such as:

```text
7 days
```

Do not build long-term topic memory here.

Compute a cheap deterministic similarity from:
- normalized title tokens;
- normalized summary tokens;
- numeric tokens;
- distinctive shared tokens;
- publication time proximity.

Reuse simple token-normalization patterns already present in the repository where sensible.

Do NOT add embeddings.

Return only:

```text
top 3–5 plausible stories
```

for semantic consideration.

A cheap score is a retrieval hint only, not authority to merge loosely related stories.

---

# PART 6 — Conservative deterministic auto-match

Allow deterministic auto-assignment only for extremely strong cases.

Examples:

```text
same publication_key
→ SAME_STORY

near-identical normalized title
+ close publication time
+ strong distinctive-token overlap
→ SAME_STORY
```

Keep threshold deliberately conservative.

Do not auto-label `NEW_DEVELOPMENT` from token similarity alone.

False split is acceptable.
False merge is expensive.

---

# PART 7 — Semantic relation, only for ambiguous shortlisted cases

M4C is allowed one narrow semantic capability:

```text
new publication
vs
existing story
→ relation
```

Output contract:

```json
{
  "same_event": true,
  "relation": "SAME_STORY | NEW_DEVELOPMENT | RELATED_BACKGROUND | DIFFERENT_STORY",
  "material_change": true,
  "shared_anchors": ["..."],
  "reason": "short explanation"
}
```

Strict JSON validation.

No free-form editorial scoring.

## Definitions

### SAME_STORY

Same event/story, no materially new development.

Examples:
- another outlet reports the same decision;
- rewritten agency copy;
- same accident with no meaningful new fact.

### NEW_DEVELOPMENT

Same story, but something materially changed.

Examples:
- proposal → committee approval;
- committee approval → final council adoption;
- investigation → charge;
- announced event → cancellation/change of date;
- new official number materially updates the situation.

### RELATED_BACKGROUND

Related context, history, explainer or adjacent material, but not the same current event/development.

### DIFFERENT_STORY

Different event/story even if actors/locality overlap.

---

# PART 8 — Model strategy: do not repeat the M3D mistake

Do NOT route story relation through the weak Lite `judge` pool by default.

This task is semantic event comparison, not mechanical entailment.

Add a dedicated role without changing existing draft/judge behavior, e.g.:

```text
role="story"
```

with env-configurable model pool:

```text
GEMINI_STORY_MODELS
OPENROUTER_STORY_MODEL
```

Safe default:
- reuse the normal/full-capability draft pool if available;
- never silently use a paid OpenRouter model;
- preserve the existing paid-model guard.

If the semantic model is unavailable, rate-limited, invalid, or returns malformed output:

```text
DO NOT MERGE
```

Conservative outcome:

```text
create a separate story
needs_review = true
```

or equivalent explicit audit field.

Infrastructure failure must never force a merge.

---

# PART 9 — Story comparison context

Do not send an entire long story history.

For a candidate story provide only a compact surface:

```text
representative title
origin title
up to 2 latest material-development titles
short summaries
publisher domains
published/discovered times
```

Maximum roughly 3 unique publications from the existing story.

No article bodies.

---

# PART 10 — Incremental update service

Create one shared service, e.g.:

```text
workflow/story_identity.py
workflow/story_store.py
```

and a one-shot command:

```bash
newsroom stories update
newsroom stories update --dry-run
```

It processes only source items not yet assigned to a story.

No daemon.

No polling loop.

## Optional bootstrap command

For development/first install:

```bash
newsroom stories rebuild --preview
newsroom stories rebuild --apply
```

Only if needed.

Important:
- an automatic rebuild must NEVER overwrite editor corrections silently;
- if a destructive rebuild would lose editor merges/splits, refuse unless explicitly forced;
- preferably incremental update is the normal path.

---

# PART 11 — Daily orchestration

Keep:

```bash
newsroom collect
```

as the low-level collection command.

Add a user-facing one-shot orchestration only if it stays simple:

```bash
newsroom refresh
```

Meaning:

```text
collect
→ assign newly collected items to stories
→ report summary
```

Story failure must not roll back successful collection.

Example summary:

```text
източници: 30
нови материали: 14
нови истории: 5
нови развития: 3
добавени към съществуващи: 4
за преглед: 2
грешки: 0
```

Cron can later call `newsroom refresh`.

Do not install cron.

---

# PART 12 — Story status and editor workflow

Story statuses:

```text
NEW
SEEN
IGNORED
```

Rules:

```text
new story
→ NEW

SAME_STORY added to SEEN story
→ keep SEEN

RELATED_BACKGROUND added to SEEN story
→ keep SEEN

NEW_DEVELOPMENT added to SEEN story
→ reopen to NEW

new material added to IGNORED story
→ keep IGNORED
```

The editor's ignore is intentional.

Story-level `SEEN` / `IGNORED` may propagate to the current member inbox items so the raw-material view does not remain full of misleading NEW rows.

Document whichever propagation rule you implement and test it.

---

# PART 13 — Editor correction is required

Machine clustering must be reversible.

At minimum provide:

## Split

On a story detail page:

```text
Този материал не е част от историята
→ Отдели като нова история
```

This is the most important correction because false merges are the dangerous failure.

## Merge

Provide a minimal editor action:

```text
Обедини с друга скорошна история
```

Use a dropdown/search over recent story headlines.

No story IDs required in the visible UI.

Editor decisions must be persisted as explicit overrides/audit events and must win over later automated updates.

Do not build a generic rules engine.

---

# PART 14 — Workbench story-first view

Add a new editor-facing page:

```text
Истории
```

Do not remove raw:

```text
Входящи / Материали
```

yet.

Recommended navigation:

```text
Истории
Материали
Източници
Случаи
YouTube
```

Eventually Stories becomes the daily landing surface, but do not replace the existing homepage in this run unless real usability testing clearly supports it.

---

# PART 15 — Story card UX

A non-technical editor should see:

```text
[Нова история] / [Ново развитие]

REAL SOURCE TITLE

3 издателя · 5 публикации · открито 08:14 · обновено 10:42

БТА · Община Бургас · БНР
one-line summary from the representative/latest source item

[Прегледана] [Игнорирай] [Отвори] [Материали ▾]
```

Do not expose:
- Jaccard scores;
- model confidence;
- internal story IDs;
- relation JSON;
- prompt/model names.

Those may exist in debug/audit output only.

---

# PART 16 — Story detail page

Show:

```text
representative/latest headline
first seen
first public
latest material change

Хронология
  08:12 — origin
  10:40 — NEW_DEVELOPMENT
  ...

Материали
  unique publications grouped by publisher
  discovery provenance available in secondary detail
```

Different discovery monitors for the same exact publication must not look like independent corroborating sources.

Show distinct:

```text
издатели
публикации
откривания
```

when useful.

---

# PART 17 — Current blocked domains and stories

A publisher blocked after collection may still exist in the raw inbox for audit.

Story processing should not use a currently blocked publisher to create/reinforce active story grouping.

Recommended:

```text
raw item remains preserved
active story view excludes currently blocked publisher material
```

Do not delete historical rows.

Document this behavior.

---

# PART 18 — Authority discipline inside M4C

Never use:

```text
source_kind == official
```

to decide story trust or publisher diversity.

Publisher semantics always come from:

```text
publisher_domain
publisher_kind
factual_authority
```

A story may contain:

```text
official publishers
authoritative media publishers
unknown/monitoring publishers
```

M4C is still not the factual evidence engine.

Do not promote story membership into factual truth.

---

# PART 19 — Real evaluation before semantic expansion

Use a fresh isolated real collection after PART 0 fixes.

Target roughly:

```text
150–250 source items
```

or whatever one normal isolated run honestly produces.

## First measure deterministic-only behavior

Before turning on semantic relation calls, report:

```text
raw discovery rows
unique publication_keys
exact duplicate collapse
deterministic high-confidence SAME_STORY groups
remaining unassigned/ambiguous items
```

This tells us how much value we get without model cost.

## Then semantic relation

Run semantic classification only on the ambiguous shortlist.

Report:

```text
semantic calls
model unavailable/error count
SAME_STORY
NEW_DEVELOPMENT
RELATED_BACKGROUND
DIFFERENT_STORY
conservative separate-story fallbacks
```

Do not hide model/provider failures.

---

# PART 20 — Manual review pack

Create:

```text
m4/review/M4C_STORY_REVIEW_PACK.md
```

Include a manageable sample, not hundreds of rows.

At least:

```text
5 exact publication duplicates
10 SAME_STORY cross-publisher examples
10 NEW_DEVELOPMENT examples if present
5 RELATED_BACKGROUND examples if present
10 near-miss / DIFFERENT_STORY examples
all uncertain or suspicious auto-merges
```

For each show:
- titles;
- publishers;
- timestamps;
- deterministic shortlist score/reason;
- semantic relation if used;
- final assigned story.

Do not use the model's own answer as ground truth.

Mark uncertain cases for human review.

---

# PART 21 — Acceptance philosophy

Do NOT chase perfect recall.

The priority is:

```text
avoid false merges
```

A false split:
- creates an extra story;
- editor can merge it.

A false merge:
- hides a distinct story;
- can cause the editor to miss news.

Therefore:

```text
uncertain → separate
```

is correct.

---

# PART 22 — Practical success criteria

Do not set an arbitrary target such as:

```text
204 → exactly 35 stories
```

Instead demonstrate:

1. duplicate discovery paths no longer inflate publication/source counts;
2. obvious same-story coverage is grouped;
3. clear material developments reopen a story;
4. similar-but-different events stay separate in manual review;
5. editor can split a bad merge;
6. editor can merge a false split;
7. model failure degrades to separate stories, not bad merges;
8. source items remain preserved.

A substantial reduction in the editor's daily row count is expected, but correctness matters more than compression ratio.

---

# PART 23 — Tests

Add hermetic tests for at least:

## Stabilization
- rolling recency applies on second/subsequent runs;
- old rows do not backfill on run 2;
- Google News publication date is not treated as event date;
- real `event_at` window when supplied;
- today counts use Europe/Sofia discovery date;
- shared publisher-domain authority conflict fails closed;
- blocked `entry.domain` refuses network collection.

## Publication identity
- same article from two source_ids → same publication_key;
- tracking params do not create a new publication;
- meaningful query params remain distinct;
- Google News article path identity is stable;
- missing usable URL does not fabricate exact duplicate identity.

## Story store
- strict schema;
- atomic save;
- unreadable store raises;
- source items are not modified/deleted;
- stable story id;
- exact duplicate joins existing story without semantic call.

## Story lifecycle
- SAME_STORY does not reopen SEEN;
- NEW_DEVELOPMENT reopens SEEN;
- RELATED_BACKGROUND does not reopen;
- IGNORED remains ignored;
- split and merge editor overrides persist.

## Semantic safety
- semantic classifier sees only shortlisted stories;
- invalid JSON → no merge;
- provider unavailable → no merge;
- relation model cannot modify source authority;
- relation model cannot draft or publish;
- no Jev production authority.

## UI
- Stories page renders;
- distinct publisher/publication/discovery counts are correct;
- story detail expands raw publications;
- split action works;
- merge action works without visible story IDs;
- raw Materials/Inbox view remains accessible.

Keep all current tests green.

---

# PART 24 — Update the old structural guard correctly

The existing M4A test deliberately forbids story/AI tokens in all newsroom modules.

Do not delete architectural protection entirely.

Change the guard so that:

### These remain AI/story-free

```text
default_sources.py
blocked_domains.py
source_health.py
sources_registry.py
newsroom_run.py
inbox_store.py
```

except for narrow calls to a story orchestration boundary if absolutely needed.

### Story semantics are allowed only in explicit M4C modules

For example:

```text
publication_identity.py
story_store.py
story_identity.py
story_relation.py
workbench/story views
```

Still forbid:
- drafting imports;
- publishing;
- Telegram;
- transcript discovery;
- generic agents.

---

# PART 25 — Model-role boundary

If adding `role="story"` to `drafting/generate.py`:

- do not change current draft role behavior;
- do not change judge role behavior;
- keep env-driven provider selection;
- keep paid-model guard;
- add tests proving story role does not silently route other workloads.

Suggested knobs:

```text
GEMINI_STORY_MODELS
OPENROUTER_STORY_MODEL
```

Do not hard-code a paid model as production default.

For an evaluation-only paid A/B, require the repository's existing explicit paid opt-in mechanism.

---

# PART 26 — Reports

Create:

```text
m4/review/M4B1_FEED_STABILIZATION_REPORT.md
m4/review/M4C_STORY_IDENTITY_REPORT.md
m4/review/M4C_STORY_REVIEW_PACK.md
```

Update:

```text
CURRENT_STATE.md
BACKLOG.md
MILESTONE.md
handoff.md
README.md
RUNBOOK.md
```

Correct stale documentation while touching it:

```text
M3A case-editing workflow = frozen
M4 newsroom Workbench surfaces = active development
```

Update real test count.

---

# PART 27 — Verdicts

Report separately:

```text
ROLLING_NEWS_RECENCY =
  PROVEN / PROMISING / NOT_PROVEN

CALENDAR_DATE_SEMANTICS =
  HONEST / NOT_PROVEN

DAILY_COUNT_SEMANTICS =
  PROVEN / NOT_PROVEN

PUBLICATION_IDENTITY =
  PROVEN / PROMISING / NOT_PROVEN

STORY_STORE_ENGINEERING =
  PROVEN / PROMISING / NOT_PROVEN

DETERMINISTIC_STORY_MATCHING =
  PROVEN / PROMISING / NOT_PROVEN

SEMANTIC_STORY_RELATION =
  PROVEN / PROMISING / NOT_PROVEN / NOT_EVALUATED

NEW_DEVELOPMENT_DETECTION =
  PROVEN / PROMISING / NOT_PROVEN / NOT_EVALUATED

EDITOR_CORRECTION_WORKFLOW =
  PROVEN / PROMISING / NOT_PROVEN

STORY_INBOX_ENGINEERING =
  PROVEN / PROMISING / NOT_PROVEN

EDITORIAL_EFFECTIVENESS = PENDING
JEV_PRODUCTION_AUTHORITY = NONE
```

Do not collapse them into one PASS.

---

# PART 28 — STOP discipline

STOP after:
- stabilization;
- story identity;
- story Workbench;
- real isolated evaluation;
- manual review pack.

Do NOT automatically continue to:

```text
M4D Telegram
M4E broader visual polish
automatic research
drafting
CMS
continuous monitoring
new custom source scrapers
YouTube changes
```

Wait for review.

---

# Product test

At the end, the editor should be able to:

```text
open Stories
→ see a manageable list of actual stories rather than 200 raw items

open one story
→ see where it came from and how it developed

see "Ново развитие"
→ understand that the story changed, not that a duplicate arrived

correct a bad grouping
→ without touching JSON or IDs

open Materials
→ still inspect every original collected source item
```

That is the milestone.
