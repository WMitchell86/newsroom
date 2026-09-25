# Post-V1 Operational & Product Backlog Review

> **Date:** 2026-09-25
> **Baseline:** `0a1dd78` — *m4: cut the React SPA over as the default editor frontend (D2B)*
> **Status:** `EDITORIAL WORKFLOW + SPA MIGRATION COMPLETE`
> **Nature:** review + roadmap document only. **No production code was changed, no
> implementation was begun, nothing was retired.** This file waits for owner review.
> **V1 is treated as complete and stable.** It is not redesigned here.

---

## 1. Executive recommendation

V1 delivered what it promised: a non-technical editor can open the newsroom in
the morning, refresh, triage, research, prepare, draft, edit, mark ready and
finalize, and the React SPA is the default surface. The product boundary is
deliberately sharp at **`Финализирана статия`**.

The honest post-V1 verdict: *the newsroom is a working daily tool, and its
weakest point is no longer editorial intelligence — it is operations at the
edges.* Three classes of risk remain, in this order:

1. **A polling asymmetry that will produce a wrong user-facing message.**
   The backend research operation is bounded to a **900 s TTL and 32 slots**
   (`workflow/story_operations.py:10-11`), but the Research client budget is
   still **8 × 250 ms ≈ 2 s** (`frontend/src/api/client.ts:267`). Draft and
   Refresh were already raised to 60 × 1000 ms (`:263`, `:376`) *for exactly this
   reason* in D2B. Research is the one remaining operation that can be reported
   to the editor as a failure while the backend is still correctly working. Same
   defect class as the Draft one, one slice behind. **P0 correctness, not a feature.**

2. **Nothing runs unless a human remembers.** `newsroom_run.py:3` says it
   explicitly: *"One-shot process, no daemon: the operator's cron calls it."*
   There is no scheduler, no catch-up, no missed-run detection. The only cadence
   logic that exists (`newsroom_run.due_for`, `newsroom_run.py:138`) decides
   *which sources to skip inside a run that already happened* — it is not a clock.

3. **Source coverage is wide but shallow.** `SUPPORTED_COLLECTORS` is still
   `("rss", "google_news_rss")` (`newsroom_run.py:53`); `youtube` and `web` are
   declared in the registry and reported `UNSUPPORTED` rather than silently
   skipped. The 35-entry default catalogue is a monitoring-query stack, not a
   structured-adapter stack. Structured local sources (НИМХ, ВиК, EVN) are where
   the real editorial value-per-item lives.

**Recommended order (matching the owner's stated preference):**

```text
P0 operation-following policy → P0 scheduler/catch-up → P1 structured sources
  → P1 events/calendar → P1 tracked topics → P2 remote interface
  → P2 conversational assistant → later: X, voice, speech-to-text
```

The single recommended first post-V1 slice is **S1 — one shared bounded
operation-following policy** (§23). It is small, it removes a real class of
user-facing wrongness, it depends on nothing, and it is the prerequisite for any
later remote/conversational interface (a Telegram or voice assistant inherits
this exact policy on day one).

Two of the brief's three "risks" are **already solved** in the repository and
need no work: the integrity-manifest gate is real and permanent
(`tests/browser/conftest.py:37-64`, session-scoped `autouse`), and a
deterministic build helper already exists (`scripts/build_frontend.sh`). Neither
should be rebuilt.

---

## 2. The V1 boundary (preserved, not reopened)

Frozen and treated as complete:

```text
Обнови
→ Днес
→ Story
→ Review / Follow / Ignore
→ Research
→ Start Article
→ Preparation
→ Editorial Focus
→ Draft generation
→ Editing / autosave / conflicts
→ Ready
→ Finalize
→ Archive
```

- The React SPA is the **default** editor frontend (`WB_EDITOR_FRONTEND` unset
  ⇒ SPA, `spa.py:58`).
- The server-rendered Workbench remains reachable at `/wb-legacy/…`
  (`spa.py:63`) and as a whole-process rollback mode. **Not retired.**
- The system **stops** at `Финализирана статия`. It does not publish to
  chernomorie-bg.com, push to a CMS, schedule publication, post to social media,
  or distribute externally.
- Publishing/CMS is **not** the next phase and is not assumed anywhere below.

No contradiction with the frozen V1 decisions was found during this review. The
only candidate — Event vs Story — is resolved in §6 without touching V1.

---
## 3. Current operational risks

### 3.1 Research operation polling — the real one

**Evidence (all current at `0a1dd78`):**

| Fact | Value | Source |
|---|---|---|
| Research client budget | `8 × 250 ms` ≈ **2 s** | `frontend/src/api/client.ts:267` |
| Draft client budget | `60 × 1000 ms` = 60 s | `client.ts:263` |
| Refresh client budget | `60 × 1000 ms` = 60 s | `client.ts:376` |
| Backend operation registry | in-process, `TTL_SECONDS = 900`, `MAX_OPERATIONS = 32` | `story_operations.py:10-11` |
| Backend work | daemon `threading.Thread`, result held in a `dict` | `story_operations.py:100` |
| Exhausted-budget wording | already a *transport* message, not a failure claim | `client.ts:350` |

**Why P0 rather than a tweak.** The three operations share *one* endpoint
(`workbench/api.py:251-254` → `app.operation_status`) and *one* documented policy
("Every long-running editor action … share this loop instead of each carrying
its own copy", `client.ts:243-250`). Research is the single deliberate exception
still on the old budget, kept with a comment that is now stale
(`client.ts:265-266`). In practice:

- a real research round performs live search + page fetching
  (`story_research.py:11` imports `web_fetch`; `:146` builds real search
  constraints) and will routinely exceed 2 s;
- when it does, the editor sees a failure-style message and the Story is not
  updated in the UI, while the backend finishes and writes the result;
- the operation row then persists until the 900 s TTL prunes it, occupying one of
  32 slots, and **a repeated click returns the still-running operation**
  (`story_operations.start`, `:44-45` returns an existing non-`failed` row's
  current view) — so the editor stays stuck until the TTL expires.

The failure is therefore not cosmetic: it is a **stuck editor** plus a slow slot
leak, and it is self-reinforcing.

**Options, and the recommendation.**

| Option | Assessment |
|---|---|
| (a) Immediate one-line Research budget bump | Necessary but insufficient: three constants would still describe one policy. |
| (b) **Align Research with the existing Draft/Refresh bounded polling** | **The substance.** `{ attempts: 60, delayMs: 1000 }` via the existing shared helper — zero new behaviour. |
| (c) Shared operation-following policy | The right long-term shape, and it is (b) + one named export + one guard test. Do it as a *thin slice*, not a framework. |

**Recommended: (b)+(c) as one slice** — collapse the three budget constants into
one documented constant with one rationale, and add a test that fails when a new
operation is registered with a budget that is not the shared one.

**Explicitly not recommended now:** a generic operation engine, a durable
operation store, or a push/streaming channel. The bounded poll handles every
current case, and the assistant work in §15 will exercise this policy far harder
than today's three calls do. Making `story_operations` durable is only justified
if a *second process* must observe operations (a remote assistant, a separate
scheduler) — and even then the first fix is a command surface, not a table.

### 3.2 Legacy Workbench

**Evidence.** `spa.py:60-63` defines `/wb-legacy` as a *"technical rollback
prefix … never linked from the SPA and never presented to editors as
navigation."* `RUNBOOK.md` §0.1 states the rollback period: both the
`WB_EDITOR_FRONTEND=legacy` mode and `/wb-legacy/…` stay supported *"for at least
the whole V1 operational period. Keep them until a post-V1 review explicitly
decides otherwise; there is no announced end date and no code is scheduled for
removal. Until that decision, assume the Workbench is part of the production
surface."*

**What still depends on it (operator, not editor).** The SPA owns only `/`,
`/stories`, `/stories/:id`, `/articles`, `/articles/:id`, `/archive`,
`/archive/:id`, `/settings`. These stay **backend-rendered even in SPA mode** and
have no SPA equivalent: `/cases`, `/inbox`, `/sources`, `/models`, `/intake`,
`/static/style.css` (cf. `tests/browser/helpers.py` `LEGACY_ONLY_HREFS`). So the
Workbench is currently the *only* UI for source-registry management, raw inbox
material, AI model policy/usage, the M3A case queue and the YouTube intake
display — a real operator surface, not a ghost.

**Assessment.**

- **Do not remove it** (non-goal, and the code says so explicitly).
- **Do not set a retirement date now.** Any date set before prolonged real use is
  a guess. Honest position: no end date; the question reopens only when the SPA
  gains the operator surfaces (§22, S12) — a *product* slice, not a rollback
  decision.
- **Retirement preconditions**, before the question is even reopened:
  1. the five operator surfaces have SPA equivalents, or the owner accepts
     CLI-only operation for them;
  2. at least one full newsroom operating period has run on the SPA with no
     rollback;
  3. the D2A/D2B browser proofs pass against a freshly rebuilt `frontend/dist` —
     those proofs are what currently keep the legacy path honest.
- **Recommendation:** keep `/wb-legacy` **indefinitely as a technical/operator
  surface.** It costs one routing branch, is never linked to editors, and is the
  only thing between a bad SPA build and a lost newsroom. Revisit only if 1–3 are
  met and the owner explicitly asks.

### 3.3 Frontend build requirement

**Already solved — do not build a deployment system.** `scripts/build_frontend.sh`
wraps `npm ci` + `npm run build` and asserts `dist/index.html` exists, *"so a
deployment fails here rather than at the editor's first click."* Its own header
forbids the obvious overreach: *"no service manager, no pipeline, no rollback
logic."* The server already fails loudly (a plain-text `503`, never a silent
legacy fallback) when the build is missing (`spa.py:26-30`).

The only residual is **operational, not architectural**: the build step is manual
and not documented as a single unit outside `RUNBOOK.md` §0.2. The proportionate
answer is a *documentation* item — one "daily deploy" block naming the script —
not a deploy tool. See §22, S3.

### 3.4 Runtime-store safety

**Already permanent and strong.** `tests/browser/conftest.py:37-64` computes a
SHA-256 manifest of every file in `var/editorial_workflow` and `var/newsroom`
before the first browser test and compares it after the last, as a
**session-scoped `autouse` fixture** — so it also fires when the suite fails
part-way. The comment names it *"the permanent migration gate, §4"*.

**Should it become part of normal integration testing?** It already does in
effect: `tests/browser/` is the integration suite and the gate is autouse there.
What it does *not* cover is the non-browser suites. Two options:

- **Do nothing** (recommended). The gate is where the risk lives — a real server
  plus a real browser against real store paths.
- **Widen it** with a session-scoped autouse fixture in the root
  `tests/conftest.py` over the same two store roots. Cheap, and it would catch a
  test leaking into `var/`. Additive only: pure test infrastructure, no product
  impact.

Recommended: fold into slice **S9** (test/ops hardening), not a standalone project.

---

## 4. Existing reusable foundations (verified in the repository)

Before designing anything new, this is what already exists. Most of the roadmap
below is **composition of these**, not invention.

| Foundation | Evidence | What it already gives us |
|---|---|---|
| Editor-owned source registry | `workflow/sources_registry.py` | closed enums, `cadence` ∈ {`each_run`,`daily`,`weekly`}, time-boxed mute, `factual_authority`, `calendar`, `priority`, `collector`. Deterministic bytes, one atomic write path. |
| Cadence decision | `newsroom_run.due_for:138` | (is_due, reason) per source from **real** `last_success_at` on the `Europe/Sofia` date. |
| Cross-process lock | `newsroom_run.acquire_lock:98` | `O_CREAT|O_EXCL` lock, stale takeover after `LOCK_STALE_SECONDS = 3600`. Already stops cron vs button interleaving. |
| Source health store | `workflow/source_health.py` | `source_health.json` (`OK`/`EMPTY`/`FAILED`/`NEVER_RUN`) + `last_run.json`. **Separate from config, on purpose.** |
| Collection runner | `workflow/newsroom_run.py` | one-shot, dry-run with zero network, per-source status, one broken source never stops the run, dedup + 72 h rolling window. |
| Newsroom refresh | `workflow/newsroom_refresh.py` | the single editor-facing «Обнови» orchestration, `RefreshBusy`, capability preflight. |
| Story identity | `workflow/story_identity.py`, `story_store.py`, `publication_identity.py` | three separate identities (source / publication / story), `NEW_DEVELOPMENT` relations, never rewriting the inbox. |
| Bounded operations | `workflow/story_operations.py` | token, TTL, slot cap, pending/running/succeeded/failed, deterministic token from (story, gap signature, generation, key). |
| Shared client poll helper | `frontend/src/api/client.ts:242-343` | `pollOperationFor` + `OperationPollBudget` — the *one* policy, already shared. |
| Idempotency | `workbench/api.py:198`, `editor_article_store.py:362` | `Idempotency-Key` on POST article/draft/research; a retried command addresses the same record deterministically. |
| Per-source `event_at` | `inbox_store.py:42-43` | *"Real event dates, supplied only by a collector that knows them. Empty for every collector wired today; never populated from `published_at`."* |
| YouTube retry ladder | `workflow/intake_queue.py` | statuses, `attempts`, `next_attempt_at`, exponential backoff, terminal vs retryable separation. |
| YouTube safety policy | `workflow/youtube_policy.py` | pacing, nightly cap, jitter, circuit breaker, cooldown, clamping of hand-edited values. |
| Telegram transport | `notify/telegram.py` | stdlib `sendMessage`, token never logged, 4096-char guard, redacted errors. |
| Durable outbox | `notify/outbox.py` | at-least-once pending rows, `list_pending`, `mark_delivered`. |
| Default source catalogue | `workflow/default_sources.py` | 35 entries, 30 active seeded, pure data, no I/O, no cycles. |
| Blocked-domain policy | `workflow/blocked_domains.py` | `chernomorie-bg.com` and `flagman.bg` never used as a factual input — enforced before any network call. |
| Canonical action gate | `editor_application` `availableActions` / `nextAction` | the *single* source of truth about what may be done to a Story/Article. |
| Store integrity gate | `tests/browser/conftest.py:37-64` | permanent SHA-256 manifest over the two real runtime stores. |
| Build helper | `scripts/build_frontend.sh` | deterministic `npm ci` + build + artifact check. |

**Not present anywhere** (searched, not assumed): a scheduler, a cron/catch-up
mechanism, a tracked-topic or watch-entity concept, an event store or event
extractor, a church-calendar source, НИМХ/ВиК/EVN adapters, X/Twitter ingestion,
Telegram *inbound* (receive/update), a conversational or voice interface, and
speech-to-text. `newsroom_run.SUPPORTED_COLLECTORS` and
`sources_registry.COLLECTORS` are the only collector vocabularies today.

---

## 5. Scheduled collection / cron (catch-up design)

**Required behaviour:**

```text
scheduled run missed because the server was offline
→ server starts
→ it determines an important run was missed
→ it performs a safe catch-up promptly
```

**Key repo fact that shapes the design:** there is already a *durable,
app-owned* record of "when did this source last succeed" —
`source_health.json` with `last_success_at`, plus `last_run.json` with
`started_at`/`finished_at`. The system therefore **already knows** whether a run
was missed. It simply never looks. That is the entire gap.

### 5.1 Options evaluated

| Option | Verdict |
|---|---|
| **OS cron / systemd timers only** | **Insufficient alone.** Cron cannot express catch-up: a machine that was off at 07:00 simply skips, and nothing in the system notices or repairs it. It also cannot coordinate with a running editor process beyond the existing lock. |
| **Durable scheduler metadata inside the app** | The right *concept*, but a general workflow engine is overkill. The durable state mostly exists already. |
| **Startup reconciliation + cron trigger** | **Recommended (hybrid).** |
| Full in-app daemon / polling loop | Rejected: contradicts the project's explicit "no daemon" design (`newsroom_run.py:3`, `poll.py:9-10`), adds a supervision problem, and is unnecessary for a single-user local tool. |

### 5.2 Recommended architecture (the smallest reliable one)

```text
OS cron (or systemd timer) → the existing one-shot CLI, exactly as today
                              no new process, no new privilege

newsroom collect / newsroom refresh (unchanged entry points)
        │
        ├── startup reconciliation   (new, read-only, cheap)
        │      reads last_run.json + source_health.json
        │      decides: nothing due / catch-up due / operator notice
        │
        └── the existing collect.lock, cadence and dedup keep it safe
```

**The reconciliation rule should be boring and deterministic:**

- read `last_run.json`; if absent, or its `finished_at` is older than the
  configured interval, a run is *missed*;
- for each active source, `due_for(entry, record, today)` already answers "is
  this source behind?" from real `last_success_at` — **reuse it verbatim**, do
  not re-derive cadence;
- a missed run triggers **one** catch-up collect, not N, and never a per-source
  stampede;
- the catch-up is inherently bounded: the 72 h rolling window and
  `MAX_ITEMS_PER_SOURCE` mean a late run cannot flood the inbox with old
  material. This is already true today, which is exactly why catch-up is safe;
- cadence is respected automatically — a source that succeeded today is not due,
  no matter how long the machine was off;
- duplicate collection is prevented by existing dedup + `collect.lock`; a cron
  run colliding with a manual «Обнови» yields `RefreshBusy`, not corruption.

**Missed-run detection must be visible, not silent.** One operator-facing fact
— reusing the existing `today_problems` channel (`newsroom_refresh.py`, capped at
`MAX_TODAY_PROBLEMS = 5`) — is enough. A scheduler that quietly repairs the past
without telling anyone is a scheduler the editor cannot trust.

**Anti-goal:** no `scheduled_tasks` table, no cron parser, no calendar library,
no queue. If S2 is done and no second consumer has appeared, stop there.

---

## 6. Editorial events calendar (`Редакционен календар / Събития`)

A genuinely new product concept, not a V1 extension. **Design before
implementation.**

```text
fetched source
→ extract future event
→ canonical event record
→ editorial calendar
```

### 6.1 What already exists (and is a gift)

`inbox_store.py:42-43` already carries `event_at` / `event_end_at` per item, with
the rule written into the data model: **"Real event dates, supplied only by a
collector that knows them. Empty for every collector wired today; never
populated from `published_at`."** The ±45-day window logic
(`newsroom_run.CALENDAR_WINDOW_DAYS = 45`) and the `calendar` flag on registry
entries already exist. So the *ingestion slot* is present and deliberately empty
— the system has already refused to guess event dates, which is the single most
important property this feature must preserve.

### 6.2 The design questions, answered

| Question | Answer |
|---|---|
| **Event vs Story?** | Different objects with different lifecycles. A **Story** is *editorial attention on a developing situation* and already exists. An **Event** is *a thing that will happen at a time and place*. A Story may reference 0..n Events; an Event may have 0..n Stories. They must not be merged. |
| **Can several publications refer to one Event?** | Yes — that is the point, and it is the dedup win. But **only when the source supplies a real event date**. Grouping by fuzzy title similarity is exactly the hallucination risk the existing rule forbids. |
| **Dates / timezones / venue changes?** | Store an explicit `event_at` in UTC *plus* the original wall-clock string and the source's stated timezone. Never normalize away the original phrasing. Venue/time changes are **updates to the same Event record with provenance**, never a second Event — source id + original announcement URL is the identity anchor. |
| **Provenance?** | Every Event field carries the item id and source that supplied it. An Event derived from prose is a *proposal*, not a fact. Provenance is mandatory. |
| **How do we avoid hallucinated event dates?** | Three hard rules: (1) only a collector that genuinely supplies a date may set `event_at`; (2) never infer a date from `published_at`; (3) an Event with no sourced date is not an Event. This is the existing M4B.1 F2 rule and it must survive verbatim. |
| **How does an Event link to Story/Article?** | One-directional by default: Story → Events. An Article may *mention* an Event, but that link carries no editorial authority by itself. |
| **Cancelled / postponed?** | First-class Event state with the change recorded as a dated provenance entry: `UPCOMING → OCCURRED / CANCELLED / POSTPONED`. Never delete — the history is the editorial value. |

### 6.3 Time windows

`Днес · Утре · През уикенда · Следващата седмица · По-късно` are a **read-only
view over `event_at` in Europe/Sofia**, not stored buckets. All five derive
trivially from a sorted event list; storing them would create timezone bugs and
stale copies.

### 6.4 Lifecycle (proposed, not forced into V1 states)

```text
upcoming event
  → optional preview Article   (an ordinary Article, normal V1 path)

event occurs
  → follow-up Story            (a new Story, normal V1 triage)
  → optional review Article of how it went
  → possible video integration (see §8)
```

**Explicitly: an Event is not an Article and has no Article state.** The three
Article states (`preparation` / `draft` / `ready`,
`editor_projections.ACTIVE_ARTICLE_STATES`) stay exactly as they are. An Event is
a *planning object*; an Article is a *written object*. Forcing the mapping would
corrupt a frozen V1 decision for no product gain.

### 6.5 Why this is P1, not P0

It adds a new object type to a system one week past its first complete workflow,
and its value depends entirely on §7 — events are only useful if something
actually *supplies* dates. Building the calendar before the adapters would
produce an empty calendar.

---

## 7. Source expansion

Current coverage: `rss` + `google_news_rss` only. The 35-entry catalogue is
mostly publisher/locality-constrained **monitoring queries** through Google News
— wide, but every item costs a search-provider call and none of it is structured.

### 7.1 Candidate classes, assessed

| Class | Reliability | Cadence | Parsing | Provenance | Copyright | Dup risk | Authority | Maintenance |
|---|---|---|---|---|---|---|---|---|
| **RSS/Atom (verified feeds)** | High | min–hourly | trivial (parser exists) | excellent | link-only, safe | low | high when official | very low |
| **Official municipal/government pages** | Med–high | daily | med | good | link-only | med | **highest** | med (markup churn) |
| **Structured APIs (НИМХ, EVN, ViK)** | **High** | min–hourly | **trivial once mapped** | **excellent (fields)** | read-only per terms | med (update vs new) | high | low once mapped |
| **HTML pages (generic)** | Low–med | ad hoc | **high** | weak | ⚠ scraping risk | high | low | **high** |
| **YouTube** | Med | ad hoc | exists (M3B) | timestamped, excellent | transcript kept locally | low | med | med (anti-ban) |
| **Telegram (source)** | High | minutes | easy (JSON) | excellent (post id + date) | read-only | low | med | low |
| **Weather (structured)** | **High** | minutes | trivial | **excellent** | read-only | low (updates, not new) | high | low |
| **Utilities (structured)** | Med–high | min–daily | med | good | read-only | **med (notice revisions)** | high | med |
| **Social (X)** | Low | real-time | **high, and gated** | weak | ⚠ ToS | high | low | **very high** |

### 7.2 Staged onboarding (never dozens at once)

- **Stage 1 — verify feeds.** Add official RSS/Atom where a real feed exists.
  Lowest risk, immediate value, near-zero new code.
- **Stage 2 — structured adapters**, one at a time, in this order:
  **НИМХ → ViK → EVN** (§13, §14). Highest value-per-item and lowest parsing
  risk, because data arrives as fields rather than prose.
- **Stage 3 — YouTube as a collector** (not just a CLI), which requires §8's
  retry work to be safe first.
- **Stage 4 — Telegram as a source** (§9.A).
- **Stage 5 — generic HTML / social**, only if Stages 1–4 prove insufficient.
  Generic HTML scraping should be the *last* thing built, not the second.

**One rule to protect provenance:** a source may be added as *monitoring* only
(`factual_authority=False`) until it has been observed to deliver what it
promises. The registry already encodes exactly this distinction, and it is the
main brake on a bad adapter quietly corrupting evidence.

---

## 8. YouTube transcript retry / availability

**Desired behaviour:**

```text
video discovered
→ transcript unavailable
→ record retry condition
→ check again later
→ ingest transcript once available
```

### 8.1 The important finding: this is *mostly already built*

`workflow/intake_queue.py` is a purpose-built deferred-work queue that does
almost exactly this, with the same discipline the rest of the project uses:

- URL normalization + dedup to one entry per video id (`_key_for`, `:106`);
- `attempts`, `next_attempt_at`, `last_error`, `failure_category` per entry;
- exponential backoff ladder 15 m → 1 h → 6 h → 24 h, then parked (`:257`);
- `max_attempts` before parking as `blocked` (`:252-255`);
- **terminal vs retryable separation** (`:41-51`): `no_captions`,
  `unavailable`, `invalid_url` are permanent and are *never* retried, because
  "retrying a dead video is just extra requests aimed at an IP that may already
  be flagged";
- registry/queue split on purpose — the queue is operational state and can be
  deleted without losing a single transcript (`:1-19`);
- a run lock shared with interactive intake (`run.lock`, `RUNBOOK.md` §0d), so a
  pasted URL during a nightly run exits `3` instead of doubling request rate;
- append-only run history in `runs.jsonl`.

### 8.2 What is actually missing

Only two things, both small:

1. **Discovery is manual.** `youtube-intake` is a one-URL CLI and
   `youtube-batch add` a manual paste. No collector *discovers* a video and
   enqueues it, so "retry a transcript" only works for URLs a human already
   queued. Adding discovery means adding a `youtube` collector (§7 Stage 3) —
   the queue already accepts what such a collector would produce.
2. **"Not ready yet" is conflated with "will never work."** `no_captions` is
   terminal, and both `TRANSCRIPT_EMPTY` and `UNSUPPORTED_LANGUAGE` map to it
   (`:243-248`). But YouTube publishes auto-captions **after** upload, sometimes
   hours later. A video that is merely *early* is currently parked as
   permanently caption-less. **This is the real defect.**

### 8.3 Recommended design for the fix

- Add a **new distinct status**, e.g. `pending_captions` — *known to exist and
  reachable, but no track published yet*. This is the honest distinction the
  brief asks for, and it must be separate from `no_captions`.
- Retry on a **capped age ladder** rather than an attempt ladder: e.g. 1 h, 6 h,
  24 h, 72 h, then park with a clear reason. A max retry **age** (e.g. 7 days)
  is the right primary bound, because the real constraint is time, not attempts.
- Backoff must **respect the existing policy module** — never lower pacing, never
  raise the nightly cap, never bypass the circuit breaker or the 12 h cooldown.
  `RUNBOOK.md` §0d is explicit: *"Never lower the cap or the delays to 'catch
  up'."* A retry feature must not become a quiet ban risk.
- Dedup is already solved (one entry per video id), and the content-addressed
  transcript store means a changed transcript is never silently overwritten.
- **Startup catch-up** reuses §5's reconciliation: a queue with due
  `next_attempt_at` entries is a "missed run" like any other, served by the same
  one-shot, lock-protected path.
- Relationship to the general scheduler: **the queue is a consumer of the
  scheduler, not a second scheduler.** §5 decides *when a catch-up runs*; the
  queue decides *what is due inside it*. No new timing mechanism.

### 8.4 Speech-to-text (future, optional)

Worth considering only when available transcripts never arrive, and it introduces
a **cost, a privacy question and a trust-level change** (existing transcripts
carry a trust level; `TRUST_AUTO_CAPTION` is one rung and a machine transcript is
a different, lower rung). Recommendation: **retry first, transcribe last**;
transcription is P2/experimental and needs an explicit owner decision on cost and
trust labelling.

---

## 9. Telegram

Telegram today is **outbound only**: `notify/telegram.py` (stdlib `sendMessage`
transport), `notify/outbox.py` (at-least-once pending rows), `notify/render.py`
(frozen renderer), `send_telegram.py` (manual, `DRY_RUN`-gated). There is **no
inbound** code — no `getUpdates`, no webhook, no command parser. The two
capabilities below are new and must not be confused with each other.

### 9.A Telegram as a *source*

Channel posts become ordinary collected material.

- `telegram` is already a legal `collector` value in
  `sources_registry.COLLECTORS` (`:35`) — the vocabulary is prepared, the
  implementation is not.
- Ingestion is JSON and trivially structured; provenance is excellent (post id +
  date); dedup is trivial.
- Clean path: `TelegramSourceDef → normalized inbox item`, i.e. **exactly the
  shape `SourceItem` already has**. No new identity concept, no new Story logic.
- The editor-facing consequence is identical to every other source: a new inbox
  item, which may become a Story through the existing `story_identity` path.
- Must respect: blocked domains (the linked article's domain, not the channel
  itself), `factual_authority` (a channel is *monitoring* until observed), and
  cadence (a busy channel does not need `each_run`).
- **This is the lower-risk half and should precede the remote-editor half.**

### 9.B Telegram as a *remote editor interface*

The editor sends a command from Telegram.

**The architectural rule, stated as a flow rather than a slogan:**

```text
Telegram
→ authenticated editor instruction
→ resolve canonical Story/Article
→ same application/API command
→ backend availableActions + safety gates
→ result
```

There must be **no Telegram-specific shortcut** around evidence, focus,
readiness, finalization or permissions. A Telegram command must land on the
*same* `editor_application` entry points the HTTP API uses, subject to the same
`availableActions` / `nextAction` gate. If Telegram can do something the web
editor cannot, that is a security defect, not a feature.

**Authentication / confirmation / audit requirements:**

- **Authenticate the chat id** against an explicit allowlist. Never trust a
  Telegram username. A chat-id allowlist plus the existing env-var pattern
  (`TELEGRAM_TEST_CHAT_ID`) is the minimum.
- **Mutating commands require an explicit, unambiguous instruction**;
  consequential ones require a confirmation step (§15).
- **Every issued mutation is audited**: received text, resolved target,
  canonical action, whether confirmation was required, and the result (§17).
- **Idempotency is mandatory** — a Telegram client and an HTTP client can easily
  issue the same command twice. `Idempotency-Key` already exists on the
  article/draft/research commands; Telegram-originated commands must use it,
  derived deterministically from `(chat, message_id)`.
- **Unknown / ambiguous / unresolvable input is refused with a question**, never
  guessed (§16).
- A runaway loop ("keep researching") must be bounded by the same operation
  slots as everything else.
- Telegram is a **remote control for a local system**; its blast radius is
  bounded by the local bind and existing safety defaults. It widens no product
  boundary and adds no publishing path.

**Recommendation: build 9.A first, and 9.B only after the operation policy
(§3.1) and a canonical command surface exist** — because 9.B's correctness
depends entirely on there being one canonical command path to target.

---

## 10. Church (Bulgarian Orthodox) calendar

A **recurring structured source**, not a news source — the distinction matches how
the system already thinks.

**Potential data:** saint/feast day; church holiday; fasting rule; movable feasts
(computed, not scraped); local tradition notes for the Burgas region.

**Key design decisions:**

- **Authoritative Bulgarian source, vendored or generated — never inferred.** A
  *year* of church-calendar data is small, stable and effectively immutable once
  correct. That makes it a candidate for a **checked-in, human-verified dataset**
  with a regeneration script rather than a live scraper: a live scraper here
  would be a permanent maintenance burden for data that changes once a year. This
  is deliberately a different choice from §7's adapters.
- **Movable feasts must be computed by rule**, not copied per year, or the
  dataset rots the moment the next year is added.
- **Automation:** one deterministic generator plus a test that the checked-in
  data matches it. No network in the test path.
- **Daily editorial prompts:** a recurring calendar entry is exactly what the
  **Events calendar** (§6) is for, and it is the ideal first producer of Events
  because its dates are authoritative by construction — the strongest possible
  answer to the "no hallucinated dates" requirement.
- **Relationship to Events:** the church calendar is a *recurring upcoming Event*
  with a known, sourced date. It is a low-risk first dataset for §6 and a cheap
  validation that the Event model is right before wiring in messier sources.

**The provenance boundary the brief raises:** a church-calendar entry is a
**cultural/traditional fact**, not evidence about a current news situation. It
must be a different *kind* of record from collected news material and must never
be promotable as evidence for a current claim. The existing machinery supports
this directly: a distinct record type plus `factual_authority` semantics, and the
same discipline that keeps `chernomorie-bg.com` out of the factual inputs.

**Priority: P1, small.** Cheap to build, high local relevance, validates the Event
model cheaply. Not P0 because it creates no operational risk.

---

## 11. Eurovision / Burgas and the general `watch topic` question

**The requirement is real** — a high-priority tracked topic with official
EBU/Eurovision sources, Burgas Municipality and local organizer sources,
Bulgarian *and* international coverage, English-language Article capability,
Event-calendar integration, later video/social monitoring.

**The risk is turning the newsroom topic-specific.** The system must stay a
general newsroom, with Eurovision as one tracked topic among others.

**The decisive test — does a general mechanism earn its place?** Yes, but only a
*very small* one, and here is the evidence:

| Candidate need | Occurrences |
|---|---|
| Eurovision topic | 1 |
| Church calendar as a tracked recurring topic | 2 |
| НИМХ warning region as a watch | 3 |
| ViK / EVN outage areas as watches | 4, 5 |
| "Следи тази история" already exists on Story | 6 |

There is a **sixth**, and it is the strongest argument: `followStory` /
`unfollowStory` already exist as canonical Story actions (`client.ts:120-130`,
and the `Следени` filter in the SPA). A tracked *topic* is the same editorial
intent applied one level above Story. The concept is not an invention — it is an
existing, proven, already-implemented idea that currently stops one level too low.

**Recommended minimal concept — `watch topic / tracked entity`:**

```text
watch_id
name                 (e.g. "Евровизия 2026 — Бургас")
kind                 (topic | entity | region | series)
query_terms          (explicit, editor-owned)
source_ids[]         (optional allowlist of official sources)
priority             (normal | high)
status               (active | paused)
created_at / updated_at
```

Deliberately excluded from the first version: automatic classification, event
detection, per-watch AI behaviour, and any escalation. It is a **filter and a
priority hint**, nothing more.

**What a watch must NOT do:** grant `factual_authority`, create a Story, bypass
triage, or re-rank the whole newsroom. It sharpens *attention*; it does not create
*evidence*. This mirrors the existing Story-level rule and keeps the boundary
clean.

**English-language Article capability** is a separate, smaller concern: a
*style/locale* dimension on Article generation, not a topic mechanism. It should
be its own slice, and only if the owner confirms the corpus needs it — the style
subsystem is currently tuned for Bulgarian output profiles, so "add English" is
real (if bounded) work, not a checkbox.

**Priority: P1, sequenced after the structured sources** — a watch over sources
that do not exist yet has nothing to watch. Build the *mechanism* only once there
is a second real case beyond Eurovision; otherwise one high-priority registry
entry plus the existing Story `follow` may be enough for V1.1.

---

## 12. X / Twitter monitoring

**Recommendation: do not build a general X integration.** Prefer explicit
account/topic monitoring over a broad social firehose, and treat all X material
as **discovery only** unless it is independently promotable under existing
evidence rules.

| Concern | Assessment |
|---|---|
| API cost | The basic tier is heavily restricted; useful volume costs more than current model spend |
| Reliability | Real-time monitoring is best-effort; free/basic endpoints are not a dependable newsroom input |
| Rate limits | Polling is throttled hard; a monitoring loop is the wrong shape |
| Legal / ToS | Scraping is contractually and reputationally risky; the honest path is the official API or nothing |
| Noise | Very high; a firehose would drown `Днес` and destroy its current clarity |
| Provenance | A post is a claim, not a source; it needs corroboration like any other material |

**The one safe, cheap first step:** Eurovision and Burgas monitoring can be served
*today* through the existing `google_news_rss` collector (public monitoring
queries, the `default_sources` pattern) plus official feeds. That captures most of
the editorial value — *who is reporting on this* — with no X dependency, no cost
and no ToS exposure. Do that in §7 Stage 1 and revisit X only if real reporting
shows a genuine gap.

**If X is ever built:** explicit account/topic lists only, a spike heuristic over
a *known* set, every item tagged discovery-only, and a hard rule that nothing
enters evidence without independent corroboration. **Later / experimental**,
pending cost and policy decisions by the owner.

---

## 13. НИМХ (severe weather / conditions)

High-value local information, and a good first *structured* adapter.

**Desired flow:**

```text
НИМХ warning
→ structured alert/event record
→ «Днес» attention when relevant to the Burgas region
```

**Candidate data:** warning type; severity; affected region; validity window
(`from`/`until`); the dangerous phenomenon; update/cancellation events.

**Design points that matter:**

- **Region filtering is the product.** A national warning that does not touch
  Burgas must not create Burgas attention. The registry already carries
  `domain`/locality discipline and blocked-domain enforcement; region filtering
  reuses that pattern.
- **A warning is an Event with a validity window**, not a Story. It belongs in
  §6's Event model with `UPCOMING → OCCURRED / CANCELLED`, and it can then
  generate a Story through the normal triage path when it is editorially
  significant. This makes НИМХ the second real producer for the Event model
  after the church calendar.
- **Updates and cancellations are updates to the same Alert record**, not new
  items — otherwise a re-issued warning floods `Днес`. This is the "duplicate /
  updating notices" problem in its purest form and must be solved in the
  adapter, using the warning's own identity plus validity window.
- **Every warning carries its own validity end.** A warning whose window has
  passed must stop surfacing automatically, with no cron needed.

**The guardrail the brief explicitly asks for:** *do not turn every routine
forecast into breaking-news attention.* Concretely — only warnings above a
severity threshold, and only ones affecting the region, should reach `Днес`. A
daily "chance of rain" forecast is a **silent ingest** item, not attention. The
threshold must be an explicit, editor-owned setting, not a model judgement.

**Priority: P1, and the recommended first structured adapter** — highest
value-per-item, cleanest data, and it validates the Event model with real,
machine-supplied, authoritative dates.

---

## 14. ВиК / EVN (utilities)

Excellent candidates for structured adapters: small, frequent, highly local, and
genuinely useful to a Burgas reader.

**Candidate data — ViK:** water outages; аварии; planned repairs; affected
settlements/streets; expected restoration.
**Candidate data — EVN:** electricity outages; planned maintenance; affected
areas; restoration windows.

**Shared design points (both sources):**

- **Geographic normalization is the hard part, and it must be explicit.** Both
  publishers describe areas in their own vocabulary. Normalization to a
  canonical locality/street form must be a *stored, inspectable mapping* with
  the original string preserved — never a silent string transformation. A wrong
  normalization would tell Burgas readers the wrong neighbourhood has no water.
- **Duplicate / updating notices.** Both publishers re-issue and amend notices.
  Identity should be (source, notice reference, locality, window) and a changed
  notice is an **update to the same record**, not a new item. This is the same
  rule as НИМХ (§13) and should be implemented once, in the adapter contract.
- **Start/end time and resolved status** are first-class: an outage is
  `ACTIVE → RESOLVED`, and it must stop surfacing on its own when the window
  passes or the resolution is published.
- **Event-calendar relationship:** an outage is a bounded Event (a time window in
  a place), so §6's model covers it without extension.
- **Should a meaningful change reopen a Story?** **No, not by default.**
  Reopening is an *editorial* decision, and the system already has the canonical
  action for it. What the adapter should provide is a **"meaningful change" flag**
  on the update (a new locality, a new window, a new restoration estimate), which
  makes the change visible to the editor in the Story's «Нови развития». The
  editor decides; the adapter never re-activates anything itself. This keeps V1's
  triage authority intact.

**Priority: P1, after НИМХ** — same adapter contract, so the second and third
adapters should be much cheaper than the first.

---

## 15. Conversational / voice AI newsroom assistant — action safety

**The one architectural rule:**

> The assistant is an **ORCHESTRATOR over the existing system**. It does **not**
> get a privileged bypass.

It must obey canonical Story/Article identity, `availableActions`, evidence
gates, research provenance, focus confirmation, readiness, version conflicts and
finalization safety. Concretely, the assistant produces **intent**, and the
existing `editor_application` command path executes it. If the assistant can do
something the UI cannot, that is a defect.

**Action classification by consequence:**

| Class | Handling | Examples |
|---|---|---|
| **Read-only** | Execute immediately | „Какво има ново?", „Покажи следните истории", „Какво липсва по тази история?" |
| **Low-risk reversible** | Execute with clear feedback | „Следи тази история", „Спри следването" |
| **Editorial creation/change** | Require an explicit target when ambiguous | „Започни статия", „Промени фокуса", „Направи чернова" |
| **Consequential checkpoint** | Require explicit confirmation | „Отбележи като готова", „Финализирай" |

These classes map onto machinery that already exists — read projections; the
existing Story actions; `Idempotency-Key`-protected commands; the readiness and
finalization guards with their 409-on-conflict behaviour. The assistant's safety
model is therefore mostly *composition of existing safety*, not new safety logic.
That is a strong argument for building it late.

**Non-negotiable:** do not design an assistant capable of bypassing final human
authority. The editor remains the only actor who can finalize.

---

## 16. Context resolution — the hard design problem

> „Проучи я още." — what is „я"?

**Safe conversational context model, in resolution order:**

1. **Explicitly referenced Story/Article** in this or a recent turn.
2. **Currently open Story/Article** — the same object the editor has on screen.
3. **The most recent assistant result** the editor is evidently responding to.

**Rules:**

- The resolved target is **always stated back** before a consequential action
  („Продължавам: „Общински съвет приема бюджета" — Story s-…"), so a wrong
  resolution is catchable.
- **Never guess between multiple materially plausible Stories** for a
  consequential action. If two Stories match, the assistant asks. Cost: one extra
  turn. Benefit: no wrong-article writes.
- Read-only actions may proceed with a single best candidate *and* say which
  object they used.
- Context is **per-conversation and explicit** — never inferred from editor
  behaviour in a way that cannot be inspected.
- A resolved target is bound at the moment of the action; a Story that changes
  state mid-action must be re-validated by the existing guards, not by the
  assistant.

---

## 17. Audit trail

Every assistant-issued mutation must remain attributable. The record must answer:

- what instruction was received;
- what canonical action was requested;
- what Story/Article was targeted;
- whether editor confirmation was required (and given);
- the command result.

**What to store:** concise structured intent/action records — interface, session,
received text, resolved target, canonical command, confirmation flag, result,
timestamp. **What not to store:** hidden model chain-of-thought. There is already
a precedent for exactly this discipline: the model usage ledger stores a
`request_id` and provider attempts, **never prompts**
(`drafting/model_usage.py`, with its privacy gate). The assistant audit record
should follow the same rule and be a first-class store from day one, not a log
added later.

---

## 18. Speech to text

Speech-to-text is an **input mechanism, not a separate editorial workflow.**

Evaluate later: browser microphone; local vs remote transcription; Bulgarian
recognition quality; punctuation; entity names (proper nouns are the hard part
for ASR); and confirmation when transcription is ambiguous.

**The canonical rule:** the command that executes must be based on **confirmed
interpreted text/intention**, never on raw audio. Ambiguous entities — exactly the
ones ASR mangles — must go through §16's rules before anything happens. A
misheard „финализирай" must not finalize an article.

**Priority: Later / experimental**, after the text assistant has proven itself.

---

## 19. Relationship between scheduler, calendar and watches

Several backlog items clearly want the same thing: missed runs, transcript
retries, event refresh, tracked-topic checks, source cadence, weather/utility
refresh. The brief warns correctly against jumping to a generic workflow engine.

**The smallest durable abstraction actually needed — three things only:**

1. **A due-check.** Already exists twice: `newsroom_run.due_for` (per source) and
   `intake_queue` (`next_attempt_at` per entry). Both answer "is this due?".
2. **A durable last-success record.** Already exists twice:
   `source_health.last_success_at` and the intake queue's own timestamps. Both
   answer "when did this last work?".
3. **A startup reconciliation that looks at (1) and (2) and decides whether a
   catch-up run is owed.** Does not exist. This is the only genuinely new part.

**Recommendation: add only (3).** It reads state that already exists, decides a
boolean "a run is owed", and triggers the existing one-shot entry points. That is
the whole abstraction. Call it the **catch-up decision** — not a scheduler, not a
task queue, not a workflow engine.

**What two or more real backlog items demonstrably need (the test for a shared
foundation), and what they do *not* need:**

| Need | Consumers | Shared? |
|---|---|---|
| "Is a run owed since we were last up?" | newsroom collection, YouTube queue, future adapter refresh | **Yes — build once (S2)** |
| Per-item due-time with backoff | YouTube queue (exists); future НИМХ/ViK/EVN alert refresh, transcript retries | **Yes — the pattern already exists in `intake_queue`; reuse it, don't abstract it** |
| Source cadence | registry + `due_for` (exists) | Already built |
| "Event" semantics | church calendar, НИМХ, ViK/EVN, Eurovision dates | **Yes — one model (§6), not one engine** |
| "Watch" semantics | Eurovision, church, weather region, outages | Only after ≥2 real cases (§11) |
| Command surface | web, Telegram, voice | **Yes — one canonical path, several front ends** |

**The honest conclusion:** the shared foundation is **small and boring** — a
catch-up decision, an existing due/last-success pair, an Event model, and one
command surface. Anything larger would be over-engineering, and the brief's
instinct to avoid it is correct.

---

## 20. Prioritization (qualitative, no numeric scoring)

### P0 — operational reliability (before prolonged real newsroom usage)

| Item | Value | Dependency | Complexity | Operational risk |
|---|---|---|---|---|
| **S1 Shared bounded operation-following policy** | Removes a wrong user-facing failure and a stuck-editor state that will recur daily | none | **Small** (one constant + guard test) | Very low — reuses the existing helper |
| **S2 Startup catch-up / missed-run reconciliation** | The newsroom collects itself; missed runs are repaired and *visible* | reads existing `last_run` / `source_health` | **Small–medium** | Low — bounded by existing caps and lock |
| **S3 Runbook/deploy documentation pass** | The operator knows the exact deploy + cron sequence | `scripts/build_frontend.sh` (exists) | **Trivial** | None |
| **S4 «Още» after an exhausted budget** (client UX) | The editor can resume a still-running operation instead of starting over | S1 | **Small** | Low |

### P1 — high-value newsroom expansion

| Item | Value | Dependency | Complexity | Operational risk |
|---|---|---|---|---|
| **S5 НИМХ structured adapter** | Highest value-per-item; authoritative local alerts | S2 (cadence), Event model | **Medium** | Med (region + severity logic must be right) |
| **S6 Event model + calendar view** (validate with the church calendar first) | Planning capability; «По-късно» / «Следващата седмица» views | a real date supplier (S5 or the church dataset) | **Medium–large** | Med — new object type |
| **S7 ViK + EVN adapters** | Highly local, genuinely useful | the adapter contract from S5 | **Medium** each | Med (geographic normalization) |
| **S8 YouTube `pending_captions` retry fix** | Recovers material wrongly parked as permanent | existing queue | **Small** | Low — must respect `youtube_policy` |
| **S9 Test/ops hardening** (widen the store-integrity gate; add reconciliation tests) | Protects the real stores | S2 | **Small** | None |
| **S10 Telegram as a source** | Cheap new material; clean shape | S2 | **Small–medium** | Low |
| **S11 Tracked topic/watch** + Eurovision | High editorial value without making the newsroom topic-specific | S5–S7 having real sources | **Small** | Low |
| **S12 SPA operator surfaces** (`/sources`, `/models`, `/inbox`) | Prerequisite for ever reconsidering the Workbench | none | **Medium–large** | Low |

### P2 — strategic expansion

| Item | Value | Dependency | Complexity | Operational risk |
|---|---|---|---|---|
| **S13 Canonical command surface** (one non-HTTP path onto `editor_application`) | Enables every remote front end safely | S1 | **Medium** | **Med** — it is the security boundary for 9.B |
| **S14 Text conversational assistant (read-only first)** | Large daily-editorial time saving | S1, S13 | **Large** | Med — intent misinterpretation |
| **S15 Church calendar dataset + generator** | Local relevance; validates the Event model cheaply | S6 | **Small** | Low |
| **S16 English-language Article capability** | Only if the corpus needs it | style subsystem work | **Medium** | Low |

### Later / experimental (need research or external dependencies)

| Item | Why later |
|---|---|
| **S17 Telegram as a remote editor interface (9.B)** | Needs S13 and S1 first; highest security sensitivity |
| **S18 Voice / speech-to-text input** | Needs S14 to exist, plus an ASR decision (cost, quality, privacy) |
| **S19 Audio transcription of videos** | Cost + a new trust level below `TRUST_AUTO_CAPTION` |
| **S20 X / Twitter monitoring** | Cost, ToS, noise; `google_news_rss` covers most of the value first |
| **S21 Watch mechanism as a general feature** | Unjustified until a second real case exists beyond Eurovision |

**Explicitly NOT scheduled by this roadmap:** publishing/CMS integration, social
distribution, and automatic publication of any kind. The product boundary stays
at `Финализирана статия`.

---

## 21. Shared foundations — what actually earned its place

Applying the brief's own test (*recommend a shared foundation only if at least two
real backlog items demonstrably need it*):

| Proposed foundation | Verdict |
|---|---|
| **Catch-up decision** (read due + last-success, decide one boolean, trigger an existing one-shot) | ✅ **Build** — needed by collection, the YouTube queue, and every future adapter refresh |
| **Event model** (one record shape with provenance, validity window, state) | ✅ **Build** — needed by church calendar, НИМХ, ViK/EVN and Eurovision dates |
| **Canonical command surface** (one path onto `editor_application`) | ✅ **Build** — needed by web, Telegram and voice; it is also the safety boundary |
| Per-item due/backoff record | ♻️ **Reuse** `intake_queue`'s existing pattern — do not abstract it |
| Source cadence + due logic | ♻️ **Already built** (`due_for`) — do not rebuild |
| Structured source adapter contract | ⚠️ **Build only with S5**, and only as what S5 needs; ViK/EVN are hypothesis #2–3 until then |
| Generic `watch topic` framework | ⏸️ **Not yet** — one real case (Eurovision) plus three speculative ones |
| Generic task/scheduler engine | ❌ **No** |
| Event extraction from prose (AI) | ❌ **No** — would violate the "no inferred dates" rule outright |

---

## 22. Small implementation slices

Each slice: one primary goal, preserved rollback, no cross-cutting redesign, and a
clear **STOP CONDITION**.

| Slice | Goal | Stop condition |
|---|---|---|
| **S1** | One shared bounded operation budget for Research/Draft/Refresh + a guard test | Research uses the shared budget; the full suite + browser parity pass; a test fails if a new operation registers a non-shared budget. **Stop.** |
| **S2** | Startup catch-up decision + one visible missed-run fact | With the clock moved back, one start triggers exactly one catch-up collect, respects cadence, reports it once. **Stop** — no `scheduled_tasks` table. |
| **S3** | Document deploy + cron as one runbook block | `RUNBOOK.md` names `scripts/build_frontend.sh` and the two cron lines. **Stop.** Docs only. |
| **S4** | «Още» resume affordance after an exhausted budget | The editor can re-poll the same token and see the result. **Stop.** |
| **S5** | НИМХ adapter (region + severity + validity window) | A real warning reaches `Днес` for Burgas only; a non-Burgas warning does not; an expired warning stops surfacing. **Stop** — no calendar view yet. |
| **S6a** | Event record + store + provenance (no UI) | A sourced date produces an Event; a `published_at` never does. **Stop.** |
| **S6b** | Calendar view with the five time windows | The five windows derive from `event_at` in Europe/Sofia. **Stop** — read-only. |
| **S7** | ViK, then EVN, one per slice | Notices dedupe/update correctly; a resolved outage stops surfacing. **Stop** each time. |
| **S8** | `pending_captions` status + age-based retry ladder | An early video is retried, not parked; a truly caption-less one still is; `youtube_policy` limits are untouched. **Stop.** |
| **S9** | Widen the integrity gate + reconciliation tests | A test that leaks into `var/` fails. **Stop.** |
| **S10** | Telegram source collector | A channel post becomes a normal inbox item with normal dedup and health. **Stop.** |
| **S11** | `watch` record + one editor-facing use (Eurovision) | A watch changes attention only — it cannot create a Story or grant authority. **Stop.** |
| **S12** | `/sources` in the SPA (then `/models`, `/inbox`) | The registry is fully manageable without the legacy Workbench. **Stop.** |
| **S13** | Canonical command surface (one path, no Telegram) | The same intent over the new path and the HTTP API produces identical results and identical refusals. **Stop.** |
| **S14** | Conversational assistant, read-only intents only | Questions are answered from projections; **no** mutation is possible. **Stop** before any write intent. |
| **S15** | Church calendar dataset + generator | Generated data == checked-in data; movable feasts computed by rule. **Stop.** |
| **S16** | English Article capability (only if confirmed) | An English Article passes the same validation gates. **Stop.** |

**Discipline preserved throughout:** no slice introduces a second canonical path,
no slice touches the frozen Article states, and no slice ends with a half-built
abstraction waiting for a hypothetical second consumer.

---

## 23. Recommended first post-V1 slice

**S1 — one shared bounded operation-following policy.**

Chosen over "scheduler/catch-up" and "source-expansion foundation" because:

- **Operational necessity: highest.** It is a defect that will produce a wrong
  user-facing message on a routine action, and the owner already identified the
  exact class from the Draft incident. It is not a hypothesis — it is a known gap
  between the backend's 900 s TTL and the client's 2 s budget.
- **Dependency: none.** It needs nothing and blocks nothing, but it is the
  prerequisite for S4, S13, S14 and S17 — every remote or conversational surface
  inherits this exact policy on day one.
- **User value: immediate and visible.** „Проучи още" stops failing spuriously
  and stops stranding the editor.
- **Risk: minimal.** One constant, reusing `pollOperationFor`, plus a guard test.
  Rollback is a one-line revert. It cannot affect collection, evidence or
  finalization.

**Sequencing rationale:** operational reliability (S1 → S2) before content
expansion (S5 → S7 → S6), and remote/conversational interfaces (S13 → S14 → S17)
strictly last. The assistant will be far more useful once it orchestrates a rich,
reliable system than if built early against a thin one — the owner's stated
ordering is exactly right.

**No implementation prompt is generated here, by instruction.** The stop condition
for this task is this document awaiting owner review.

---

## 24. Explicit non-goals for this phase

- ❌ No implementation. No production code change.
- ❌ No retirement of the Workbench or `/wb-legacy`; no announced end date.
- ❌ No publishing, CMS, scheduled publication, social or external distribution.
- ❌ No change to the frozen V1 product, workflow, vocabulary or Article states.
- ❌ No in-app daemon, no generic workflow engine, no task queue, no cron parser.
- ❌ No speculative abstractions: nothing is proposed as a "shared foundation"
  unless two real backlog items need it today.
- ❌ No X/Twitter integration.
- ❌ No commits. This document is uncommitted and awaits review.

---

## 25. Verification performed for this review

- Repository inspected at `0a1dd78` on branch `main`, working tree clean.
- Every architectural claim cites a concrete file and line in the current tree;
  the "not present anywhere" claims in §4 are search results, not assumptions.
- `git diff --check` clean; **only** `m4/review/POST_V1_ROADMAP.md` is added.
  No production file, test or config was touched.
- No commit was made.

**Status: `POST_V1_ROADMAP = AWAITING OWNER REVIEW`.**
