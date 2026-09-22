# BACKLOG — deferred ideas (do NOT implement without a new scope decision)

Per harness rule §3.3: ideas discovered mid-task go here, not into the current change.

## M1.x (Radar)
- [x] M1.1 — Source Contract + Fixture Only (fixture → parser → normalized object → local output; no network) — done
- [x] M1.2 — One Real Source, Read-Only (1 public source → fetch → parser → console/JSON; no Telegram/DB) — done (+ M1.2.1 description normalization)
- [x] M1.3 — Local State + Dedupe (SQLite; NEW / UNCHANGED / UPDATED) — done
- [x] M1.4 — Telegram TEST channel (M1.4A outbox+renderer, M1.4B manual dry-run-gated delivery) — done, live-verified
- [x] M1.5 — Alert UX calibration (steps 1–5: audit → deterministic cleanup → provenance/pagination proof → de-dup 11/19→0 → live TEST send `message_id=5`) — DONE, renderer frozen
- [ ] M1.6 — Manual poll cycle (manual command: fetch → parse/normalize → NEW/UPDATED/UNCHANGED → atomic outbox → report; NO automatic Telegram sending; ingestion and delivery separated)
- [ ] M1.7 — Scheduled polling (only after the alert format is confirmed worth automating)

## Deferred to later levels
- [ ] L2 editorial triage (risk/priority/region/type rules)
- [ ] L3 action suggestions; L4 safe drafts (allow-listed types only); L5 WordPress draft helper
- [ ] L6 follow-up/deadline memory; L7 author style (retrieved examples first, no LoRA)
- [ ] L8 routine ops (health-check, broken-link detection, parser canary)
- [ ] Ideas for later: source diff assistant, promise/deadline memory, archive capsule, storm mode

## Explicitly NOT for V1 (spec §12)
LoRA/fine-tuning, generic NER platform, large gazetteer, CRM, pgvector-by-default,
enterprise social listening, autonomous hard-news writing, closed-FB-group scraping,
complicated confidence scoring, 80-source Playwright farm, heavy multi-agent newsroom.

## M2+ deferred by editor decisions (do NOT implement without a new scope decision)
- [ ] Provider-health/cooldown for repeated same-day DDGS degradation (observed
      M2S-R3/R3b; for now observable via the failure taxonomy, not a redesign trigger)
- [ ] TinyFish fetch fallback promotion — only if real cases show it saving pages
      (current verdict: TINYFISH_FETCH = AVAILABLE / NOT_YET_PROVEN, narrow
      failure-category trigger only)
- [ ] Semantic correction CONCRETE_ACTION_NEEDS_RESEARCH vs ROUTINE_REPORT_VETO —
      FROZEN until the editor V2 sample review (hypotheses + evidence:
      m2/review/SHADOW_DISAGREEMENT_ENRICHMENT_AUDIT.md)
- [ ] Monid integration — backlog (explicitly not in the runtime path)
- [ ] LIVE 6–10 — not yet (gated on the editor V2 sample review)

## M3B.1 deferred (do NOT implement without a new scope decision)
- [ ] **Invidious bypass is `NOT_AVAILABLE`** — 9 public instances probed live on
      2026-09-19, none served captions. The integration is ready; re-probe before
      trusting it. A self-hosted Invidious instance would be a new scope decision
      (new infrastructure, not a code change).
- [ ] **Cookies + TLS impersonation are OFF by default.** Enabling them is an
      operator decision (`YOUTUBE_COOKIES_FILE`, `YOUTUBE_IMPERSONATE`, optional
      `curl-cffi` extra) and needs a *logged-out* cookies export. No code change
      pending — the knobs exist.
- [ ] **Cookies/proxy for the bypass engine.** `invidious.py` uses plain
      `urllib` and ignores `YOUTUBE_PROXY`; only the yt-dlp path honours it.
      Add only if the bypass ever starts serving and needs a proxy.
- [ ] **M1.7 scheduled polling** (see M1.x above) is still deferred for the *RSS*
      radar. M3B.1 added a cron entry point for **YouTube transcripts only**;
      that is not a precedent for the radar or for any other source.
- [ ] **Bounded run log.** `var/youtube_intake/runs.jsonl` is append-only and
      never rotated. Rotate only if a real run history becomes long enough to
      matter.
- [ ] **Discovery nondeterminism is promoted to M3D** (see below) — it is the
      next milestone, not a leftover M3B.1 item.

## M4 — Daily Newsroom (ACTIVE; sliced 2026-09-20, decided by the repo owner)

M4 is a **product / operations** milestone, not another AI milestone. Slices, in
order — each one is done, reviewed and frozen before the next starts:

```text
M3D  FROZEN            YouTube  GOOD ENOUGH (maintenance only)

M4A   Source Registry + Scheduled Collection       DONE (frozen)
M4A.1 Default Source Pack + Source Hardening      DONE (frozen)
M4B   Daily Inbox UX                               DONE (frozen)
M4B.1 Feed stabilization (review F1-F7)            DONE (awaiting review/freeze)
M4C   Story Identity / New Development             DONE (awaiting review/freeze)
M4D   Model Routing + Role Budget                  DONE (awaiting review/freeze)
M4E   Telegram Editorial Alerts                    <-- next
M4F   Editorial workflow polish
```

Scoring rule for every task in this milestone: *will this make tomorrow's work
faster and easier for the editor?* If not → this file, not into the change.
The only new semantic capability admitted anywhere in M4 is **story identity /
new development** (M4C), and only after the registry and the inbox exist.

### M4A — Source Registry + Scheduled Collection (BUILT, LIVE-PROVEN 2026-09-20; awaiting review/freeze)

Success criteria, all demonstrated live (`m4/review/M4A_PLAN.md` §8):

```text
[x] editor opens the Workbench and sees/manages the sources          -> GET /sources
[x] can enable / disable / mute-to-date / re-prioritise              -> POST /sources
[x] a cron-ready collector uses the SAME registry                    -> newsroom collect
[x] the collector writes real inbox items                            -> 60 items, live
[x] the Workbench shows those items                                  -> GET /inbox
[x] one-shot, no daemon; the repo installs no timer                  -> guard tests green
```

- [x] **Registry core** `workflow/sources_registry.py` + `tests/test_sources_registry.py`
      (15 offline tests): closed schema, time-boxed mute, priority, cadence,
      monitoring-only vs factual authority, one atomic writer, deterministic bytes.
- [x] **CLI** `sources list|seed|add|enable|disable|mute|remove|priority|cadence|authority`.
- [x] **Workbench page «Източници»** with a table (Източник · Тип · Статус ·
      Приоритет · Следващо събиране) and inline actions (Добави, Редактирай,
      Активирай/Изключи, Заглуши до..., Промени приоритет, Monitoring only,
      Factual authority). No JSON in the UI, no advanced config editor.
- [x] **Default registry seed** — 3 entries, declared sources only: the one verified
      official feed in `sources/live.py` plus two monitoring queries via the adopted
      News RSS provider. Deliberately short; no outlet or feed URL invented.
- [x] **Scheduled collection** — `workflow/newsroom_run.py` + `cli newsroom collect`
      (`--dry-run` = zero network, `--source`, `--limit`). One-shot; a broken source
      is isolated and reported; exit 1 on partial failure so cron mail surfaces it.
- [x] **Inbox skeleton** — `workflow/inbox_store.py` (`NEW`/`SEEN`/`IGNORED`, no story
      identity yet — that is M4C) + `GET /inbox` with Прегледан/Игнорирай actions.

Explicitly **not** done in M4A (owner's boundary): AI angle generation, full
research, drafting, `NEW_DEVELOPMENT`/`DUPLICATE` story identity, Telegram alerts.
The shape is `SOURCE -> RAW/normalized INBOX ITEM` and stop.

### M4A.1 — Default Source Pack + Source Hardening (BUILT, LIVE-PROVEN 2026-09-20)

Owner-authorized correction of M4A before scaling the source count. Report:
`m4/review/M4A1_DEFAULT_SOURCE_PACK_REPORT.md`. Source research:
`m4/M4_DEFAULT_SOURCE_STACK_RESEARCH.md`.

- [x] **Declarative catalogue** `workflow/default_sources.py` — 35 entries; new
      install seeds **30 active** (9 core `each_run` + 21 `daily`) and catalogues
      **5 disabled** optionals. `sources defaults --preview|--apply` is additive,
      idempotent and never re-enables or overwrites an editor-owned entry.
- [x] **Blocked-domain policy** `workflow/blocked_domains.py` — defaults to
      `flagman.bg`, host-suffix matching, refuses page URLs as values, filters
      broad-monitor results **before** inbox insertion (publisher domain from the
      Google News `<source url>` attribute, not the opaque redirect link), refuses a
      direct blocked source.
- [x] **Real cadence + source health** `workflow/source_health.py` —
      `each_run`/`daily`/`weekly` resolved on the `Europe/Sofia` day, separate
      operational store, `OK`/`EMPTY`/`FAILED`/`NEVER_RUN`, health columns in the
      Workbench, `newsroom collect --force`.
- [x] **Safe bootstrap + caps** — first collection keeps ≤72 h / 10 newest (news) or
      a ±45-day window (calendars), 20 items per source per run.
- [x] **One shared collection lock** between cron and the Workbench button.
- [x] **Publisher authority is never inherited** (post-review correction): every
      source declares its real publisher `domain`, every item stores
      `publisher_domain` / `publisher_kind` / `factual_authority` from the publisher
      (direct feeds are their own publisher; unknown publishers get none), and the
      inbox shows and filters both identities separately.
- [ ] (accepted limitation) A publisher that is the same newsroom under another host
      (e.g. `bnrnews.bg` vs `bnr.bg`) is treated as unknown rather than assumed. Add a
      second source or an alias field only if real use shows the editor needs it.

### M4B — Daily Inbox UX (BUILT, LIVE-PROVEN 2026-09-20)

Report: `m4/review/M4B_DAILY_INBOX_REPORT.md`.

- [x] Inbox answers «Какво ново има и какво трябва да погледна?», with a top summary
      (нови · прегледани · игнорирани · източници с проблем).
- [x] Per item: headline · source name · kind · priority · published/discovered time ·
      one-line summary · Прегледан / Игнорирай / Отвори източника; internal ids hidden.
- [x] Filters: status (**default NEW**) · source · kind · priority · date · authority;
      50-per-page pagination. No semantic filters yet.
- [x] **«Събери новите сега»** delegates to the same one-shot service cron calls;
      **«Пробен преглед»** is zero network; result + source problems + last run shown.
- [x] Cron schedule documented (`RUNBOOK.md`): 07:00 / 12:00 / 16:00 / 20:00 Sofia.
- [ ] Still M4B/M4E later (not built): multi-source grouping of the same event — that
      is exactly M4C; the owner's `ВАЖНИ` / `СЛЕДЕНИ` buckets need a signal that does
      not exist yet, so they are deferred rather than faked.

### M4B.1 — Feed Stabilization (BUILT, REAL-ISOLATED-PROVEN 2026-09-21)

Bounded corrections from `m4/M4_CHECKPOINT_REPO_REVIEW.md`; report:
`m4/review/M4B1_FEED_STABILIZATION_REPORT.md`.

- [x] **F1 rolling recency** — the 72 h news window now applies on **every** run, so a
      second immediate run cannot backfill what the first excluded. Real proof: run 1
      → 91 items, run 2 (immediately) → 32 genuinely new, **0** stored rows older than
      72 h (the old `+100 new` pattern is gone).
- [x] **F2 honest calendar semantics** — a ±45-day event window needs a real
      `event_at`/`event_end_at` from a collector that knows it; otherwise a calendar
      source is ordinary news. `published_at` is never an event date.
- [x] **F3 real «Днес»** — `Europe/Sofia` arrival-day counts from `discovered_at`,
      plus a separate lifetime `Непрегледани общо` so nothing unfinished is lost.
- [x] **F5 authority conflict fails closed** — same publisher domain with differing
      `kind`/`factual_authority` raises `RegistryError` instead of letting the
      alphabetically-first `source_id` decide authority.
- [x] **F6 declared blocked domain refused pre-network** — `blocked_reason()` now
      checks `entry.domain` as well as the URL and the query text.
- [x] **F7 collection-mode wording** — derived from `collector` (`Директна емисия` /
      `Наблюдение чрез Google News`); no new registry field.

### M4C — Story Identity / New Development (BUILT, REAL-ISOLATED-PROVEN 2026-09-21)

Report: `m4/review/M4C_STORY_IDENTITY_REPORT.md`; manual sample:
`m4/review/M4C_STORY_REVIEW_PACK.md`.

- [x] three separate identities (discovery / publication / story); the raw inbox is
      never rewritten or deleted;
- [x] `publication_identity.py` (URL normalization + tracking-param removal, Google
      News token identity, no key invented from a title);
- [x] `story_store.py` — strict, atomic, overrides audit, lifecycle rules,
      propagation to member items;
- [x] `story_identity.py` — cheap-first retrieval (exact publication → 7-day
      shortlist → conservative deterministic test → narrow semantic fallback),
      incremental `update`, `analyze`, `rebuild`, views and editor actions;
- [x] `story_relation.py` — one narrow JSON relation contract, strict validation,
      failure never merges;
- [x] `role="story"` model pool (`GEMINI_STORY_MODELS`, `OPENROUTER_STORY_MODEL`),
      never the Lite judge pool, paid guard preserved;
- [x] CLI `newsroom stories update|rebuild`, `newsroom refresh` (collect → assign →
      one summary; story failure never rolls back collection);
- [x] Workbench `Истории` list + story detail with split («Този материал не е част от
      историята») and merge; `Материали` (raw inbox) stays;
- [x] real isolated evaluation + review pack; 123 rows → 113 publications, 10
      duplicate rows collapsed, 112 stories deterministic-only.

Open after review (NOT in this change): semantic call budget (102 ambiguous items in
one corpus would mean ~102 calls), Bulgarian stemming/morphology for the deterministic
match, and the pre-existing OpenRouter default-model id defect (see the report §10).

### M4C — original scoping note (delivered above)

- [x] `SAME_STORY` / `NEW_DEVELOPMENT` / `RELATED_BACKGROUND` / `DIFFERENT_STORY`
      (Newsjack-inspired starting point, not a spec). `NEW_STORY` is an action, not a
      relation.
- [x] Why it mattered now: with cron collection the same event arrives from many
      sources; this is what stops the inbox becoming noise. Deliberately **after**
      M4A + M4B, never before them.

### M4D — Model Routing + Role Budget

- [x] Central role-based model policy (`config/model_policy.default.json`, 7 roles)
- [x] True cross-provider fallback (`model_router.call_role()`)
- [x] Failure classification + health tracking + bounded retries
- [x] Daily usage ledger (no prompts stored)
- [x] CLI `newsroom models status|validate|show`
- [x] Workbench `AI модели` page (`/models`)
- [x] Role qualification harness + fixtures (judge/story/angle/draft/research)
- [x] Anchor gate tightening (PART 12: weak candidates rejected without model call)
- [x] Safe degradation per role (story=conservative, judge=review_required, etc.)
- [x] Privacy gate (public_only routes never receive private payload)
- [x] Gemini per-model quotas (500 RPD Lite, 20 RPD Flash) + named OpenRouter free models
- [x] Paid fallback: GPT-5.6 Luna/Luna Pro (not GPT-5.4)
- [ ] Live qualification run on real fixtures (needs provider keys)
- [ ] M4C semantic-call reduction measurement on real corpus

### M4E — Telegram Editorial Alerts

- [ ] Notification layer only (the Workbench stays the place to work):
      🔴 new important story · 🟡 research needed · 🔵 new development on a followed
      topic — with a reason and a Workbench link, not 40 signals a day.
- [ ] One-way in v1; the `👍 / 🔎 / 🗑` actions are a later increment.
- [ ] Reuses the existing gated TEST transport (`--send` + `DRY_RUN=false`), never
      a publishing channel.

### M4F — Editorial workflow polish

- [ ] Whatever real daily use shows is missing (article workspace, sources panel,
      missing-facts panel). Nothing here is designed speculatively.

## M4 (original scoping note, kept for context)

**Why this outranks any further semantic work.** The transport, the discovery
layer and the YouTube module are good enough for v1 (`YOUTUBE_PIPELINE_V1 =
FROZEN / GOOD_ENOUGH`, `CURRENT_STATE.md`). The largest remaining product gap is
not intelligence — it is that **the editor has no daily system that simply
opens in the morning and works**. Every remaining milestone-level item below is
about that system, not about another engine.

**Goal.** A scheduled daily routine that collects, dedupes, routes and delivers
a *story inbox* to one non-technical editor, with the sources under their
control.

```text
07:00 collect -> official sources
              -> Google News RSS
              -> TinyFish
              -> selected regional/national sources
              -> YouTube only when relevant (frozen pipeline)
   -> normalize -> coarse relevance -> deduplicate -> rank/route -> editor inbox
repeat runs at 12:00 / 16:00 / 20:00 (plain cron; adaptive monitoring NOT required)
```

Mapping of the original components onto the slices above: source registry → M4A;
story inbox → M4B; story identity / new development → M4C; Telegram editorial
channel → M4D; workbench UX + operational status/failures → M4B/M4E (every run
prints a summary; the UI surfaces what is degraded).

**Hard boundaries that stay in force:** `AUTO_PUBLISH=false`, `DRY_RUN=true`, no
CMS publishing, no LIVE 6–10, Jev keeps zero production authority, no rubric or
threshold change, media/DB writes only through the canonical writers.

**Explicitly NOT in M4:** an adaptive/smart monitoring engine, a second
semantic-tuning round, a new transcript engine, a Jev semantic-equivalence run,
per-source scraping farms.

## M3D — Discovery Reproducibility & Stability (BUILT 2026-09-19; measured; residual decision open)

**Status:** built and measured. Report:
`m3/review/M3D_DISCOVERY_STABILITY_REPORT.md`. Harness
`scripts/evals/discovery_stability.py`; L4 successful-stage cache
`workflow/discovery_cache.py` + `--force-discovery` on `youtube-intake`.

```text
DISCOVERY_REPLAY_HARNESS         = PROVEN     (79 live runs, 4 recordings)
DETERMINISTIC_STAGE_STABILITY    = PROVEN     (segmentation byte-identical)
MODEL_EXECUTION_RELIABILITY      = PROMISING  (0/40 spontaneous failures; 17/40 quota-blocked)
FACT_EXTRACTION_STABILITY        = PROMISING  (overlap 0.955–0.977; 0 catastrophic)
ANGLE_STABILITY                  = PROMISING  (overlap 0.389–0.789 — the flip source)
READINESS_STABILITY              = PROVEN with versioned cache (6/6 identical replays)
CATASTROPHIC_ZERO_YIELD          = RESOLVED   (0/79)
DISCOVERY_REPRODUCIBILITY        = PROVEN (operational, L4)
UNSEEN_VALIDATION                = PENDING (provider quota)
```

**Measured root cause of OUTCOME_FLIP (22.2–31.6% on the flaky recording, 0% on
the stable one):** identical fact sets, divergent angle-proposition wording →
different cited-fact counts → ±1 rubric point around the threshold → outcome
flip. Not extraction, not grounding, not parsing. Jev shadow agrees
(same-fact paraphrase `SAME_CLAIM` p=1.00; competing candidates
`OVERLAPPING_CLAIM` p=0.77).

**Status 2026-09-20: CLOSED & FROZEN** — `YOUTUBE_PIPELINE_V1 = FROZEN /
GOOD_ENOUGH`. The editor accepted `OUTCOME_FLIP` as residual risk under the L4
cache; `ANGLE_STABILITY = PROMISING` is the accepted end state, and the angle
stage was **measured** (not switched). Report §11–§13; decisions below.

Closed:

- [x] Editor decision: `OUTCOME_FLIP` accepted as residual risk under the L4
      cache (an accepted analysis is pinned and replayable;
      `--force-discovery` re-opens it explicitly and non-destructively).
- [x] Angle-layer model A/B measured: `openai/gpt-5.6-luna-pro` → **0/4 flips,
      proposition overlap 1.00** vs 22.2–31.6% for the shipped Lite pool on the
      same recording → the flip is model-capacity-driven.

Still open (backlog, no milestone):

- [ ] **Optional one-knob switch: run the angle stage on a stronger model.**
      Measured and NOT built. Needs a small code change first — `propose_angles`
      currently shares the `judge` role with fact grounding, so the switch wants
      a dedicated pool/role (e.g. `GEMINI_ANGLE_MODELS`) rather than a judge-pool
      reorder. Paid providers require an explicit owner OK (the guard is
      unchanged). **Pull only if real editor use shows the flip hurting.**
- [ ] The two provider-blocked recordings (`b13U-N_Vk9c`, `xvsdi_j7s5c`) still
      have no 10-run baseline: the free Gemini judge pool cannot carry 12+ calls
      per run (404/429/400 empty-body signatures; pacing does not help).
      Blocked rows preserved under `var/discovery_stability_corpus2/`. Re-run
      only if a real need appears.
- [ ] Bounded execution retries for discovery model calls (L1) — still open.

## M3D — Discovery Reproducibility & Stability (original scope, decided 2026-09-19)

**Status:** first-class next milestone, decided 2026-09-19. Do not start it
without a harness prompt; this entry only records *why* it outranks M3C.

**Evidence.** The transport layer is now more reliable than the semantic layer.
The same cached transcript, byte-identical raw SRT, produced different editorial
outcomes on repeat runs:

```text
same raw SRT, run A -> RESEARCH_MORE
same raw SRT, run B -> NO_EXTRACTED_FACTS / NO_PUBLISHABLE_ANGLE
```

This is not cosmetic variance: it changes whether the editor sees a story at all.
It is a pre-existing model-driven property of transcript discovery V2 (M3B), not
a regression introduced by M3B.1, and it is the reason
`EDITORIAL_EFFECTIVENESS` cannot leave `PENDING`.

**Goal (to be scoped).** Measure and bound the variance rather than make an LLM
trivially deterministic:

```text
same transcript -> N repeated runs -> topic stability
                                   -> fact stability
                                   -> angle stability
                                   -> readiness stability
```

then decide which stages should be **frozen/cached after the first successful
extraction** (a frozen artifact is not a semantic change — it is reuse).

**Explicitly out of scope until scoped:** changing discovery semantics, prompt
tuning, new thresholds, LLM-judge authority. Those stay frozen.

**Preferred over:** M3C automatic research enrichment.

## M3B.1 settled decisions (2026-09-19 review — do not re-litigate)

Decided by the repo owner after the M3B.1 code review; all are implemented.

- **Q1 two stores stay split.** `registry.json` is evidence/history;
  `queue.json` is disposable operational state. Deleting the queue loses no
  transcript or evidence — that boundary is intentional, do not merge them.
- **Q2 fallback defaults OFF.** `YOUTUBE_FALLBACK` is opt-in (third-party
  contact + 0/9 live instances).
- **Q3 stop-on-block, not rotate-on-block.** A block is IP-level; extra client
  attempts escalate it. Rotation stays for ordinary client-specific failures.
- **Q4 the yt-dlp default client stays last in the rotation** (a client can lack
  captions while the default client succeeds).
- **Q5 interactive `youtube-intake` takes the same run lock as cron** (exit `3`
  if held) — but does **not** go through retry/backoff lifecycle.
- **Q6 out-of-range policy values are clamped *and* reported**
  (`policy warning:` line); never silent.
- **Q7 the failure fuse stays the constant `CONSECUTIVE_FAILURE_FUSE = 5`.**
  Not an env knob; parameterize only if real use demands it.
- **Q9 `youtube-batch doctor`** — optional P2/P3 operational feature, not a
  blocker (yt-dlp version, cookies path, curl-cffi, lock/cooldown, fallback
  state).
- **Q10 no origin-string migration.** Historical `var/` records keep the old
  origin string; the newer origin is more informative, not a correction.
