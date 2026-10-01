# V1.2-G4.19/G4.20 — Cron self-healing, role fallback, and the two debugging trails

Date: 2026-10-01 · Commits: `66d4cf1` (cron + routing), `21c59ea` (debug trails) ·
Scope: operations and observability. No new editorial capability.

Owner question that started this: *"check the cron job behavior, fix it."* It
turned into four defects and two missing audit trails, three of which were found
by **measuring** rather than by reading.

---

## 1. The cron jobs were dead on a fresh checkout

`scripts/newsroom_cron.sh` contained `mkdir -p var/cron`, which reads like it
protects the log directory. It does not.

**A shell opens a crontab's `>> file.log` redirect BEFORE it runs the command.**
That `mkdir` executes too late to matter. Reproduced, not inferred:

```console
$ /bin/sh -c '.../newsroom_cron.sh newsroom doctor >> .../var/cron/doctor.log 2>&1'
exit=2   cannot create .../var/cron/doctor.log: Directory nonexistent
```

`var/` is gitignored (`git ls-files var` → 0 files), so a **fresh checkout has no
`var/cron/` at all**. All four jobs would die at the redirect, exit 2, and write
nothing anywhere the operator reads.

### Why it was worse than a silent failure

`cron_status()` only string-matched the crontab against `NEWSROOM_CRONS`, so
`newsroom doctor` would answer `РАЗПИС: на място (4 задачи).` about four jobs that
could not run. It looked healthy on this machine **only** because the directory
happened to exist from earlier runs — a self-check disagreeing with the thing it
checks.

### Fix

- Each crontab line now creates the log directory before the redirect, generated
  by one `cron_line()` so the installer, the matcher and the docs cannot drift —
  the exact trap `849b455` recorded for the schedule field.
- `cron_status()` **measures** the directory and returns `logDirOk`.
- `doctor` reports a schedule that cannot run (exit 1) with the one-command fix.

### Verified both directions

| check | result |
|---|---|
| old line shape, `var/cron` absent | still dies at the redirect, exit 2 — the bug reproduces |
| new line shape, `var/cron` absent | self-heals, writes a real log |
| live cron | `14:43:01 CRON[7167]` ran the new shape; `repair.log` mtime `14:43:02` |

6 tests, including one asserting the *old* line shape no longer satisfies the
check — otherwise the fix would be invisible and a reinstall would reintroduce it.

---

## 2. `angle` had no free substitute

Asked to check the OpenRouter free substitutes, which surfaced a real wiring gap.

```console
angle  eligible=1/5  free=0  free_eligible=0   <-- NO FREE SUBSTITUTE
```

`angle` went straight from the three Gemini Flash routes to two **paid** OpenRouter
models. With `paid_enabled: false` a paid route is *skipped*, so once the Gemini
per-model daily limits were spent the role had **nothing** eligible and quietly
degraded — precisely what `on_exhausted: degraded` exists to prevent.

**OpenRouter is the provider, not a billing class** (owner correction, and it is
right): the same provider serves free and paid models, and its free endpoints keep
the desk running when Gemini is spent. Fix = a free route in the chain, **not**
loosening the paid gate. The gate held all day: 11 paid rows, every one
`SKIPPED`/`PAID_DISABLED`, 0 attempts, $0.00.

| | before | after |
|---|---|---|
| `doctor` angle | ✗ 0/5 | **✓ 3/7** |
| doctor exit | 1 | **0** |

**Live proof it earns its place** — the 16:17 cron refresh, all three Gemini routes
spent or genuinely 429'd:

```
16:17:01 draft  gemini-3.8-flash  MODEL_LIMIT_REACHED
16:17:01 draft  gemini-3.7-flash  ROUTE_UNHEALTHY  ← genuine HTTP 429
16:17:01 draft  gemini-3.6-flash  MODEL_LIMIT_REACHED
16:17:01 draft  nemotron-3-ultra-550b-a55b:free  OK   ← carried the work
```

Grouping finished **10/6 classified, zero degraded** (earlier runs today: 3
unexpected).

---
## 3. The sent-prompt log

`lineage.model` already recorded which model wrote a draft. The **prompt text was
stored nowhere**, so *"what exactly did you ask it?"* was unanswerable.

New private store `var/editorial_workflow/model_prompts.jsonl` (`0600`), written at
the transport boundary in `model_router._try_route`. Three things decided by
reading the code first:

- **capture point** — `_trim_for_model` runs *inside* `generate._call_gemini`, so a
  prompt logged by the caller would be the PRE-TRIM text, and would differ from
  what the provider received whenever the 30 000-char valve fires;
- **before the call, not after** — my first version logged post-transport and the
  two *failed* Gemini attempts vanished. Those are exactly the rows that explain
  why the expected model was not used;
- **explicit `0600`** — umask 0022 makes a plain `open("a")` create `0644` and
  expose unpublished source text. Pinned by a test on the mode.

**Not** in the usage ledger. `test_usage_ledger_aggregates_and_never_stores_prompts`
freezes that, and it is right: the ledger is aggregated and diffed while
investigating a provider failure. A test proves the new store is not a back door.

### Verified on a real rewrite (not a simulation)

`POST /api/v1/articles/art_3358910f87547be/rewrite` → `succeeded`:

```
16:38:30  draft route#0  gemini:gemini-3.5-flash   13024 chars  payload=private
16:38:30  draft route#1  gemini:gemini-3.8-flash   13024 chars  payload=private
16:39:15  draft route#3  gemini:gemini-3.6-flash   13024 chars  payload=private  ← answered
16:39:35  judge route#0  gemini:3.5-flash-lite      2352 chars
```

## 4. The research trace — and where I instrumented it wrong

`story_research.json` records only what **survived**: promoted sources, claims,
fact ids. The round has five drop points and every one was a silent `continue`, so
*"did it look anywhere else?"* had no answer in the product.

New `var/editorial_workflow/research_trace.jsonl` (`0600`) and
`newsroom stories research-trace [--story-id --outcome --limit --json]`. It reads
the trace — it never re-runs research and never spends a credit.

A separate store because `story_research_store._row()` validates a **closed** field
set (`req <= set(v) <= req | optional`); a trace field on the research row would
break that contract, and that row is the canonical assessment the editor reads.
Dropped pages record url/host/reason, **not** page text.

### The dominant drop is not where I first instrumented

I added traces to the in-loop `continue`s. **My own test caught that a facebook
result never appeared.** `publisher_opened` filters wrapper/social hosts *before*
the reading loop, so most pages never reach any in-loop point — the first version
would have looked complete while missing the majority of drops.

Live confirmation, a real round on story `s3089d50cc4f7cb5` at 17:28:

```
КРЪГ  разгледани=4  запазени=1  факти=0  claim gate=4
· SKIPPED_NON_PUBLISHER  news.google.com  (×3)  wrapper/social page (§18)
· SKIPPED_CLAIM_GATE     bnrnews.bg       (×4)  not corroborated by an independent publisher
```

That story produced **0 facts**, and the trace now says exactly why.

### The join is complete

```
research_trace source_id
  → story_research.json  sources[].id + claims[].text
  → facts[].sourceId / .locator
  → draft prompt         - [fact_…] (current_event) …
  → model_prompts.jsonl  request_id + model      ← which model got it
```

`fact_ids` are `sha256(story_id \0 source_id \0 text)`, so a fact in the prompt
identifies its source without guessing.

**Recorded asymmetry, not papered over:** live-evidence facts carry only
`source_reference: "source_text"` and one packet-level `source_url`. Per-fact
source attribution exists on the **research** path, not on the live-evidence path.

The full 13 024-character prompt came back verbatim, including
`===== CURRENT_EVIDENCE =====` with the real source facts. The last row of a
`request_id` is the answering model, and it **matches `lineage.model`**
(`gemini-3.6-flash`).

## 5. Two measured facts that corrected the record

**"34 drafts today" was wrong — there were 2.** 34 draft-role provider calls, but
only **2** carried any token (11:19:02 in 4382/out 557; 12:14:39 in 4594/out 450).
The other 32 had `in=0 AND out=0` and persisted nothing (`live_drafts.jsonl`: 0
rows today). They are one logical request walking its fallback chain — rows
sharing a `request_id`. Total draft output: **1007 tokens**.

**`daily_call_limit` is per MODEL per day, shared by every role.** There is no role
filter in `model_usage.model_calls_today`. `story` alone spent `gemini-3.8-flash`
to 22 attempts; because `story`/`angle` declare `20` for that model while `draft`
declares `80` for the same one, `models status` showed:

```
× 0: gemini-3.8-flash · днес 22/20 · дневен лимит на модела (20) е достигнат   ← story
✓ 1: gemini-3.8-flash · днес 22/80                                              ← draft
```

The `20` is **our own declared guardrail, not a measured provider limit**, and the
message reads like the provider's quota. Documented in RUNBOOK as AGENTS.md rule 3
requires. **Not changed** — it is an owner decision, and picking a new number blind
would repeat the recorded failure.

---

## 6. Mistakes made in this slice

Recorded because each is a trap someone else will hit:

1. **Asserted free-before-paid route ordering.** Wrong — I had not read the router. A
   gated paid route is a skip that `continue`s, so `draft` ships paid-then-free and
   works. Test corrected to assert only what the router depends on.
2. **Wrote an order-dependent test.** Passed alone, failed in a full run: caused by
   `tests/browser/conftest.py` setting `GEMINI_API_KEY` in `os.environ` with no
   cleanup. My *first* fix was also wrong — deleting both keys made the test fail
   alone, because with no key **every** route is skipped with `липсва …KEY` and the
   test asserted nothing. Reproduced deterministically before/after: 8 failed → 7.
3. **Nearly shipped `return`** in the research round-summary `except`, which would
   have abandoned the round's own result.
4. **Repeated the isolation mistake.** The autouse fixture redirected the ledger but
   not the two new stores, so one suite run wrote **328 rows / 3 MB of test prompts**
   into the operator's store — silently, since nothing reads that file
   automatically. Backed up to `var/backup_pre_promptlog_clean_1649/`, cleaned,
   fixture fixed, regression tests added.

Best-effort guards were proven **non-vacuous** by sabotaging each one and confirming
the test fails.

---

## 7. Open — recorded, not fixed

- **The cron path never records grouping health.** `_run_newsroom_refresh`
  (`cli.py:1311`) calls `story_identity.update` directly and never calls
  `record_run_grouping` / `record_run_stories`; only
  `newsroom_refresh.refresh_newsroom` (the Workbench path) does. Verified live:
  after the 16:17 run the log reported `10/6 класифицирани`, yet `last_run.json` has
  no `grouping` key and `api/v1/today` returns `groupingHealth: null`. Since `None`
  means *unknown* and the frontend renders unknown as *no warning*, **a
  cron-refreshed degraded grouping is silent to the editor** — the rule-6 shape
  again. Small fix, separate commit, awaiting the owner's go-ahead.
- `qwen/qwen3.8-27b:free` is eligible but **0-for-14** today
  (`EMPTY_OUTPUT` / `RATE_LIMITED`). Eligibility is decided by limits and health
  marks, not by whether the model has ever produced output.
- `src/editor_assistant/workflow/claim_quality.py:346` has one pre-existing
  `SIM103`. Untouched (`git diff HEAD` on it is empty).

---

## 8. Gates

| gate | result |
|---|---|
| full suite, before | 27 failed / 2000 passed |
| full suite, after | **27 failed / 2019 passed**, failure set **identical** (`diff` empty), 0 errors |
| `ruff check` | clean on every file touched |
| `ruff format` | new files clean; `cli.py` / `test_model_policy.py` fail on unmodified `main` too, none of the hunks touch this work |
| `newsroom doctor` | exit 0, all 7 roles routable |
| live cron | 16:13 repair, 16:17 refresh — both fired, logged, released the lock |
| operator stores | both untouched by a full suite run |
| server | `127.0.0.1:8123` 200 on `/`, `/inbox`, `/stories`, `/sources`, `/models`, `/api/v1/today` |

`AGENTS.md` baseline list was itself stale (`test_model_policy` 2,
`test_quick_draft` 7 — both measured clean on 2026-10-01) and was replaced with
measured numbers, plus new rule 11 for the ambient-env test trap.

