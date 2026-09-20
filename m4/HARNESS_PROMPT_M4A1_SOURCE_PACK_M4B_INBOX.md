# Harness Instructions — M4A.1 Default Source Pack + M4B Daily Inbox UX

## Starting point

Start from commit `dd93e89`.

M4A is functionally complete:
- editor-owned source registry;
- Workbench Sources page;
- one-shot `newsroom collect`;
- zero-network dry run;
- normalized inbox store;
- basic Inbox triage;
- collection failure isolation.

Reported gate:
- 738 tests
- ruff check/format clean
- M3A smoke 25/25
- anti-ban guards 20/20

Primary objective:
> Make the system usable every day by a non-technical editor.

Do not reopen YouTube/M3D.
Do not start M4C story identity yet.

## Mission

Do two bounded pieces of work:

```text
PART A — expand and harden the default source stack
PART B — turn the current raw Inbox skeleton into a practical daily-editor screen
```

Then STOP.

No AI ranking.
No story clustering.
No Telegram yet.
No drafting changes.

# PART A — Default source catalogue

## A1. Replace the 3-source new-install seed

Create one declarative, versioned default-source catalogue.

Do not scatter defaults through CLI/UI code.

Suggested location:
`src/editor_assistant/workflow/default_sources.py`
or a tracked JSON/YAML fixture if that better matches the architecture.

No credentials.

## A2. Do not silently overwrite editor-owned stores

New/empty registries receive the expanded default set.

Existing non-empty registries must not be silently mutated.

Provide an explicit additive path, e.g.:

```text
sources defaults --preview
sources defaults --apply
```

Rules:
- preview performs no writes;
- apply adds only missing default IDs;
- never re-enables a disabled source;
- never changes editor-modified priority/status/cadence;
- report added/already-present/skipped;
- repeated apply is idempotent.

## A3. Source set

Use `M4_DEFAULT_SOURCE_STACK_RESEARCH.md`.

Core frequent sources must include at least:

```text
burgas-municipal-council
burgas-municipality
pomorie-municipality
odmvr-burgas
bnr-burgas
bta-burgas
google-news-burgas-region
chernomorski-far
darik-burgas
```

Daily rubric coverage must include at least:

```text
pomorie-council
burgas-regional-administration
burgas-prosecution
burgas-district-court
riosv-burgas
rzi-burgas
ruo-burgas
umbal-burgas
burgas-state-university
burgas-free-university
burgas-cultural-program
burgas-sport-program
gotoburgas-events
rim-burgas
port-burgas
burgas-airport-fraport
nessebar-municipality
sozopol-municipality
sozopol-council
tsarevo-municipality
primorsko-municipality
```

Optional, catalogued but disabled:

```text
burgasinfo
burgas-library
burgas-opera
aytos-municipality
karnobat-municipality
```

Explicitly forbidden:

```text
flagman.bg
```

Do not seed/query it.

Do not use `chernomorie-bg.com` as current factual/discovery input.

## A4. Collector assignment: verify, do not guess

For every source:

1. inspect current generic collector capabilities;
2. use an existing direct/RSS/page collector where it works;
3. use publisher/site-constrained News/search monitoring if direct collection is not safely supported;
4. never guess RSS endpoints;
5. do not create one bespoke parser per source.

Bounded live smoke per source:
- max 3–5 items
- correct domain/publisher
- plausible `published_at`
- title non-empty
- URL opens
- no navigation/HTML junk

If clean collection requires bespoke scraping:
- seed disabled
- reason `COLLECTOR_PENDING`
- move on.

## A5. Blocked publisher/domain policy

Required M4A correction.

Broad News/search collectors may return unwanted publishers.

Add a small editor-owned blocked-domain policy.

Initial default:
`flagman.bg`

Requirements:
- blocked search/news results filtered before inbox insertion;
- direct blocked source refused;
- collection summary reports filtered count;
- Workbench Sources page has compact `Забранени домейни`;
- editor can add/remove domain;
- normalize scheme/www/case to host;
- reject paths/full malformed URLs as stored values;
- atomic writes;
- no expiration.

Tests must prove Flagman cannot enter via direct source, Google News fixture, or generic search fixture.

## A6. Trust semantics

Preserve fields, document semantics.

Official/institution:
- monitoring_only=false
- factual_authority=true

BTA/BNR:
- monitoring_only=false
- factual_authority=true
- kind remains media

Darik/Черноморски фар/BurgasInfo:
- monitoring_only=true
- factual_authority=false

Do not weaken high-risk evidence rules.

## A7. Make cadence real if needed

Inspect implementation.

If `cadence` is display-only, fix it before enabling the bigger source set.

Operational state stays separate from registry config:

```yaml
source_id:
last_attempt_at:
last_success_at:
last_status:
last_item_count:
last_error:
```

Rules:
- every_run: due on every invocation
- daily: due only if no successful collection on current Europe/Sofia date
- muted/disabled: never due

Add `newsroom collect --force` only if needed.

Dry-run reports:
`due / cadence-skipped / muted / disabled`.

No scheduler installed here.

## A8. Source health

Add to Workbench Sources:
- Последно успешно
- Последен резултат
- Нови материали

States:
`OK / EMPTY / FAILED / NEVER_RUN`.

No uptime dashboard.

## A9. Safe bootstrap

First run with 20+ sources must not backfill history.

Ordinary news/press:
- <=72h lookback OR max 10 newest items.

Recurring:
- normal identity/idempotence.

Event/calendar sources:
- upcoming window ~45 days;
- publication-date age must not remove future events.

Use reasonable per-source caps.

## A10. Live source-pack verification

Run expanded pack in isolated runtime.

Prove:
- catalogue loads
- preview no-write
- apply additive/idempotent
- blocked-domain filter
- dry-run zero network
- source failure isolation
- second run no exact identity duplicates
- daily cadence skip
- source health update

Report:
- active source count
- disabled optional count
- success/empty/failure
- blocked-domain filtered
- new items
- already-known items

Not every source needs live success.

# PART B — M4B Daily Inbox UX

Current Inbox is a skeleton. Improve it for a non-technical editor.

Do not add M4C story identity.

One inbox item remains one collected source item.

## B1. Daily editor mental model

Page should answer:
> Какво ново има и какво трябва да погледна?

Top summary:
- Нови
- Прегледани
- Игнорирани
- Източници с проблем

No AI score.

## B2. Inbox item

Show:
- headline
- source name
- source kind
- priority
- published time
- discovered time
- short normalized description

Actions:
- Прегледан
- Игнорирай
- Отвори източника

Hide internal IDs by default.

## B3. Filters

Practical only:
- Всички
- Нови
- Прегледани
- Игнорирани
- source
- source kind
- priority
- date

If metadata supports:
- official only
- monitoring only

No semantic topic filters yet.

## B4. Noise control

Before M4C:
- default view = NEW
- pagination / page cap
- preserve stored items
- no fuzzy dedup
- exact identity dedup remains

## B5. Collection control in UI

Add:
`Събери новините сега`

It delegates to the same one-shot service.

Show:
- running/result feedback
- readable source failures
- Последно събиране
- X нови
- Y вече известни
- Z източника с проблем

Do not create a generic job framework.

## B6. Cron-ready operator path

Do not install cron automatically.

Document a recommended example schedule in Europe/Sofia:
- 07:00
- 12:00
- 16:00
- 20:00

Provide one stable cron command.

Ensure concurrent collection runs cannot corrupt inbox/source-health state.

If collection lacks a process lock, add the smallest shared lock.

No scheduler daemon.

## B7. Visual direction

Editor-first, calm UI:
- readable headline
- source badge
- time
- small status badge
- one-line summary
- few obvious actions

Avoid engineering labels.

Sources page editor labels:
- Официален източник
- Само за наблюдение
- Изключен
- Заглушен до...
- Проблем при последното събиране

## B8. No AI scope creep

Do NOT add:
- story clustering
- NEW_STORY / NEW_DEVELOPMENT
- semantic duplicate detection
- AI ranking
- angle generation
- automatic research
- drafting
- Telegram
- recommendation scores

# PART C — Tests

Add focused tests for:
- default catalogue schema/unique IDs
- preview no-write
- apply additive/idempotent
- editor modifications preserved
- blocked-domain canonicalization
- blocked publisher filtered before inbox
- direct blocked publisher refused
- cadence due/skipped
- Europe/Sofia daily boundary
- source health
- failed source isolation
- bootstrap lookback/cap
- future calendar event survives bootstrap
- Inbox defaults to NEW
- Inbox filters
- collection UI delegates shared service
- concurrency lock if added
- no story-identity/AI imports

Keep all existing tests green.

# PART D — Reports

Create:
- `m4/review/M4A1_DEFAULT_SOURCE_PACK_REPORT.md`
- `m4/review/M4B_DAILY_INBOX_REPORT.md`

Update:
- CURRENT_STATE.md
- README.md
- RUNBOOK.md
- MILESTONE.md
- handoff.md
- BACKLOG.md

Record active defaults and optional disabled sources explicitly.

# PART E — Verdicts

```text
DEFAULT_SOURCE_PACK =
  PROVEN / PROMISING / NOT_PROVEN

SOURCE_EXCLUSION_POLICY =
  PROVEN / PROMISING / NOT_PROVEN

SOURCE_CADENCE_ENGINEERING =
  PROVEN / PROMISING / NOT_PROVEN

DAILY_INBOX_ENGINEERING =
  PROVEN / PROMISING / NOT_PROVEN

EDITORIAL_EFFECTIVENESS = PENDING
```

Source pack needs a real isolated collection run, not only schema validation.

# PART F — STOP

After source-pack verification + M4B UX, STOP.

Do not continue into:
- M4C story identity/new development
- M4D Telegram
- M4E further polish
- M3C automatic enrichment
- YouTube changes
- AI ranking
- CMS publishing

## Product rule

At the end, a non-technical editor should be able to:

```text
open Sources
→ understand what is watched
→ add/disable/mute/block sources

open Inbox
→ see what arrived today
→ know which source produced it
→ open / mark seen / ignore it

press "Събери новините сега"
→ get a clear result
```

That is enough.
