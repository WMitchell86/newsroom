# M4A — Source Registry + Scheduled Collection (plan)

**Status 2026-09-20: BUILT, LIVE-PROVEN, awaiting review.** Every success
criterion below is demonstrated (see §8). No new scope was added.

This file is the design contract for the slice, so the work stays inside the
milestone.

**Why M4A is first.** M4's object is *a daily system that opens in the morning and
works* for a non-technical editor. Nothing else in M4 can be built before the
editor can say which sources exist and how each one is treated — the inbox, the
story identity and the alerts all read that configuration. Scoring rule for every
task here: *will this make tomorrow's work faster and easier for the editor?*

## 1. Scope

```text
IN   editor-owned source registry (add / disable / mute-until / priority / kind /
     monitoring-only vs factual authority / cadence)
IN   scheduled collection: one-shot cron entry point reading the registry
IN   first story-inbox skeleton so collected items land somewhere a human reads
OUT  any adaptive/smart monitoring, scoring redesign, or new semantic capability
     (that is M4C); any YouTube/M3D reopening; any publishing channel
```

## 2. Registry (built)

`workflow/sources_registry.py`, store `var/newsroom/sources.json`
(`NEWSROOM_SOURCES_PATH` override), one atomic writer (`live_store.atomic_write`),
deterministic bytes ordered by `source_id`.

| field | values | note |
|---|---|---|
| `source_id` | lowercase slug | immutable key |
| `name` | display text | Bulgarian first |
| `kind` | `official` · `media` · `national` · `regional` · `aggregator` | editor-facing |
| `collector` | `rss` · `google_news_rss` · `youtube` · `web` | how it is collected |
| `url` / `query` | http(s) URL / ≤400 chars | required per collector; the query limit matches the existing public-query privacy guard |
| `status` | `active` · `disabled` · `muted` | `muted` requires `muted_until` |
| `muted_until` | `YYYY-MM-DD` (UTC) | **time-boxed**: expiry is computed, never written back |
| `priority` | `high` · `normal` · `low` | collection order |
| `cadence` | `each_run` · `daily` · `weekly` | runner input |
| `factual_authority` | bool | `false` = collect, never treat as a factual authority |

Design decisions worth keeping:

- **Fail closed.** An unknown field, an unknown enum value, an open-ended mute or a
  malformed entry is refused — nothing is stored and the existing store is
  untouched (test: `test_a_bad_entry_never_touches_the_existing_store`).
- **A mute can never become permanent by accident.** `effective_status()` computes
  the expiry; the stored window is history, not state.
- **An unreadable store raises** instead of looking empty (a corrupt registry must
  not silently stop collection).
- **No collection, no network, no scheduling in this module.** It is configuration.

## 3. Scheduled collection (built)

`workflow/newsroom_run.py` + `cli newsroom collect`:

```text
sources_registry.collectable()            # active, highest priority first
  -> per collector: rss | google_news_rss | youtube | web
  -> normalize into the existing intake/radar shapes (no new schema)
  -> deduplicate (item identity already exists in state/fingerprint.py)
  -> append to the inbox store (M4B skeleton)
  -> print ONE run summary: collected / new / duplicate / failed, per source
```

Rules:

- **One-shot process, no daemon.** The repo installs no timer; the operator's cron
  calls it (identical to `youtube-batch run --cron`). The M3B.1 guard
  (`tests/test_intake_antiban_guards.py`) stays green.
- **A failing source never fails the run**: per-source failure is reported in the
  summary and recorded, never silently dropped. Missing capability degrades
  explicitly (never fabricate items).
- **Dry-run first**: the runner must be able to run against the registry and print
  what it *would* collect, with zero network, for review.
- Reuse, don't rebuild: `sources/rss.py`, `workflow/search.py` (News RSS provider),
  `workflow/intake.py` for YouTube, `state/fingerprint.py` for identity.

## 4. First inbox skeleton (built)

The minimum that makes collection useful: an append-only inbox store with one row
per collected item (`source_id`, `url`, `title`, `published_at`, `collected_at`,
`item_hash`) plus a Workbench page listing them newest first. The full inbox
(`НОВИ` / `ВАЖНИ` / `ЗА ПРОВЕРКА` / `СЛЕДЕНИ` / `ИГНОРИРАНИ`) is M4B and reads
this store; M4A only needs the store + a readable list so nothing is invisible.

## 5. Workbench page «Източници» (built)

`GET /sources` (list + status counts) and POST actions `add` · `enable` ·
`disable` · `mute` · `unmute` · `priority` · `authority` · `remove`, through the
same service-layer functions the CLI uses (`workflow/sources_registry.py`) — the
UI must not reimplement validation. Bulgarian labels next to the stored enum ids,
`muted until`/`mute expired` shown explicitly, and refusals shown as a plain
message, never a 500.

## 6. Tests the slice must end with

- registry schema / mute expiry / refusal semantics (done, 15 tests);
- CLI wiring (done);
- Workbench page: GET renders, POST actions change the store, invalid input shows
  the message and leaves the store untouched;
- collection runner: `--dry-run` makes zero network calls; a stubbed failing
  source appears in the summary and does not abort the run; `disabled`/`muted`
  sources are never collected;
- no scheduler/daemon token anywhere in the run module (extend the existing guard).

## 7. Definition of done

```text
[x] editor can add / disable / mute / re-prioritise sources from the Workbench
[x] one cron entry point collects from those sources and prints a run summary
[x] collected items are visible in the Workbench (inbox skeleton)
[x] every refusal is a readable Bulgarian message, never a traceback/500
[x] offline tests + ruff + M3A smoke green; no scheduler installed by the repo
[x] docs updated (MILESTONE/handoff/CURRENT_STATE); STOP for review
```

## 8. Live proof (2026-09-20)

Ran end to end on an isolated runtime dir (`/tmp`, never the real `var/`):

```text
sources seed            -> 3 declared sources (1 official RSS + 2 monitoring queries)
sources list            -> 3 total · 3 active · 2 monitoring-only
newsroom collect --dry-run
                        -> "ПРОБЕН (без мрежа): 3 източника · очаквани мрежови заявки: 3"
newsroom collect        -> 60 items collected, 0 failures, exit 0
                           burgas-municipal-council OK (20) · both queries OK (20 each)
newsroom collect again  -> 0 new, 60 already known (idempotent, item identity holds)
GET /sources            -> 200: table with type/status/priority/next-collection,
                           inline edit, mute-to-date, priority and authority actions
GET /inbox              -> 200: 60 candidates with source name, kind, priority,
                           timestamp and Прегледан/Игнорирай actions
```

One real defect was caught by looking at the live render: Google News descriptions
are HTML, so the inbox showed markup. Fixed at the collector boundary by reusing
the frozen `sources/html_desc.normalize_description` (the same normalizer the RSS
path uses), with a regression test.

**Deliberate limits of the seed** (owner's rule: only sources already used or
explicitly approved): the seed is **3**, not 10, because the repository has exactly
one verified feed URL (`sources/live.py`). The rest are monitoring queries through
the adopted News RSS provider. No outlet and no feed URL was invented; the editor
adds БНР / BTA / Флагман etc. from the UI once their URL or query is decided.
