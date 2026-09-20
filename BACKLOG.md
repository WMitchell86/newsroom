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

## M4 — Daily Newsroom Operations & Source Management (NEXT major milestone; scope recorded 2026-09-20, NOT started)

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

Components, in the order they are worth building:

1. **Scheduled collection** — plain cron over the existing intake/radar
   primitives. The repo still installs no timer itself (`youtube-batch run --cron`
   stays a one-shot entry point); the schedule is operator-owned.
2. **Default source registry** — per-source type (official / media / national /
   regional), status (active / disabled / muted), priority, and the
   *monitoring-only vs factual-authority* flag. The editor must be able to add,
   disable, mute and re-prioritise sources themselves from the Workbench.
3. **Story inbox** — replaces case-ids and developer artifacts with
   `NEW STORY / NEW DEVELOPMENT / RELATED / DUPLICATE` (`NEW_DEVELOPMENT` vs
   `DUPLICATE` is the part that carries the value; borrow the Newsjack taxonomy
   as a starting point, not as a spec) plus an interest label and source count.
4. **Research when needed** — the existing bounded research loop, triggered from
   the inbox rather than by a developer.
5. **Editor workbench UX** — a non-technical editor must be able to work without
   knowing what an EvidencePacket, JSONL, readiness or grounding is. Bulgarian
   first, labels never raw enum ids alone.
6. **Telegram editorial channel** — a *notification* channel (new strong story /
   new development on a followed story, with a reason and a Workbench link), not
   a publishing channel and not 40 signals a day. One-way in v1; the
   `👍 преглед / 🔎 проучи още / 🗑 игнорирай` actions are a later increment.
7. **Operational status / failures** — what ran, what failed, what is degraded,
   visible without reading logs.

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
