# CURRENT_STATE.md — authoritative state for the next harness run

**Read this first.** It is the only current-state document.

> `handoff.md` and `MILESTONE.md` are **chronological history**.
> Older `HARNESS_PROMPT_*.md` files are **historical, not current instructions**.
> When they disagree with this file, this file wins.

Last updated: 2026-09-20 (**M4A.1 default source pack + M4B daily inbox built and
live-proven; awaiting review/freeze**; M3D closed and the YouTube pipeline is
FROZEN; active work is **M4 — Daily Newsroom**, split M4A–M4E in `BACKLOG.md`).

## Primary project objective (read before choosing any task)

> **Make the system usable every day by a non-technical editor.**
>
> Score every candidate task with one question: *will this make tomorrow's work
> faster and easier for the editor?* If not → `BACKLOG.md`, not into the change.
>
> **Do not reopen YouTube / M3D unless observed production pain requires it.**
> No `player_client`, semantic-variance or transcript-engine work; no
> `ANGLE_STABILITY = PROVEN` chase. Real use is the source of truth.
>
> M4 is a **product/operations** milestone, not another AI milestone. The only new
> semantic capability admitted is *story identity / new development* (M4C), and
> only after the registry and the inbox exist.

## Checkpoint

- Base commit: `860f582` (frozen M3B.1) + the M3D harness commits; M4A `dd93e89`.
- Test baseline: **793 passed**, full suite, offline (was 738 after M4A).
- Gates: `ruff check src tests scripts` + `ruff format --check src tests scripts`
  clean; M3A smoke passes.

## Verdicts

```text
EDITOR_WORKBENCH_ENGINEERING        = PROVEN
SEARCH_EXECUTION_ENGINEERING        = PROVEN
TINYFISH_SEARCH                     = ADOPTED
TINYFISH_FETCH                      = AVAILABLE / NOT_YET_PROVEN
TRANSCRIPT_DISCOVERY_ENGINEERING    = PROMISING+
TRANSCRIPT_RESEARCH_ENRICHMENT      = PROMISING
EDITOR_WORKBENCH_ENGINEERING        = PROVEN
M3A_STABILIZATION                   = PROVEN
YOUTUBE_INTAKE_ENGINEERING          = PROVEN
TRANSCRIBER_INTEGRATION             = PROVEN
ANTIBAN_HARDENING_ENGINEERING       = PROVEN
PLAYER_CLIENT_ROTATION              = PROVEN
CRON_ENTRY_POINT                    = PROVEN
YOUTUBE_QUEUE_ENGINEERING           = PROVEN
INVIDIOUS_FALLBACK                  = NOT_AVAILABLE
REAL_TRANSCRIPT_DISCOVERY           = PROMISING
JEV_REAL_WORLD_SHADOW_COLLECTION    = ACTIVE
JEV_INTEGRATION                     = PROVEN
JEV_GROUNDING                       = PROMISING_STRONG
JEV_ANGLE_SEMANTICS                 = PROMISING
JEV_CORROBORATION                   = NOT_SUITABLE_AS_STANDALONE_VERIFIER
JEV_PRODUCTION_AUTHORITY            = NONE
EDITORIAL_EFFECTIVENESS             = PENDING
DISCOVERY_REPLAY_HARNESS            = PROVEN
DETERMINISTIC_STAGE_STABILITY       = PROVEN
MODEL_EXECUTION_RELIABILITY         = PROMISING
FACT_EXTRACTION_STABILITY           = PROMISING
ANGLE_STABILITY                     = PROMISING
READINESS_STABILITY                 = PROVEN with versioned cache
CATASTROPHIC_ZERO_YIELD             = RESOLVED
DISCOVERY_REPRODUCIBILITY           = PROVEN (operational, L4)
OPERATIONAL_REPRODUCIBILITY         = PROVEN (versioned L4 cache)
YOUTUBE_PIPELINE_V1                 = FROZEN / GOOD_ENOUGH
ANGLE_STABILITY                     = PROMISING (model-capacity-sensitive)
UNSEEN_VALIDATION                   = PENDING (provider quota)
SOURCE_REGISTRY_ENGINEERING         = PROVEN (M4A)
DAILY_COLLECTION_ENGINEERING        = PROVEN (M4A, live)
DEFAULT_SOURCE_PACK                 = PROVEN (M4A.1, live: 30 active / 5 disabled)
SOURCE_EXCLUSION_POLICY             = PROVEN (M4A.1, live)
SOURCE_CADENCE_ENGINEERING          = PROVEN (M4A.1, live: 21 skipped on run 2)
SAFE_BOOTSTRAP                      = PROVEN (M4A.1)
PUBLISHER_AUTHORITY_INHERITANCE     = PROVEN (M4A.1 correction, live)
DAILY_INBOX_ENGINEERING             = PROVEN (M4B, live)
```

Jev was evaluated live (TypeSafe SDK 0.6.0, effective model `jev-1.13.0`,
149/149 calls OK). `JEV_INTEGRATION = PROVEN` means the integration is proven,
not the model for production. Shadow results live under the ignored
`var/jev_eval/`. No Jev threshold or production authority exists. **M3J is
frozen.** Details: `m3/review/M3J_JEV_SHADOW_EVALUATION.md`.

## YouTube pipeline v1: FROZEN (2026-09-20)

```text
YOUTUBE_PIPELINE_V1 = FROZEN / GOOD_ENOUGH

YouTube is a secondary source.
No further optimization without observed production pain.
```

The M3D report (`m3/review/M3D_DISCOVERY_STABILITY_REPORT.md`) is **closed and
authoritative**, including its FREEZE section. Do not open another round of
`player_client` / semantic-variance / transcript-engine work. `ANGLE_STABILITY`
is `PROMISING` and that is the accepted end state; `OPERATIONAL_REPRODUCIBILITY`
is `PROVEN` through the versioned L4 cache. The one measured, optional change —
running the **angle stage** on a stronger model pool (measured: 0/4 flips vs
22.2–31.6% for the shipped Lite pool on the flaky recording) — is recorded in
`BACKLOG.md` and is pulled **only if real use shows the flip hurting the editor**.

## Frozen boundaries (do not change without an approved scope change)

- `AUTO_PUBLISH=false`, `DRY_RUN=true` hard defaults; the only external write is
  the Telegram **TEST** channel.
- **The YouTube pipeline is frozen** (`YOUTUBE_PIPELINE_V1`, above): intake,
transcriber, pacing/anti-ban, queue, discovery semantics and the L4 cache are
done. Maintenance only.
- SITE DNA; VOICE/MODE profiles; newsworthiness thresholds; readiness
  thresholds; hook guidance; factual-gate semantics; provider routing
  (`PROVIDER_ORDER`); transcript discovery semantics; deterministic-vs-model
  authority; current editor-pilot results.
- M3A (`workflow/workbench/`) is frozen after this reliability cleanup.
- Jev has **zero production authority**: it is invoked only by the eval runner.
- No drafting, no publishing, no LIVE 6–10 in M3J.
- The intake stack contains **no scheduler**: `youtube-batch run` is a one-shot
  process, the repository installs no timer, and `tests/test_intake_antiban_guards.py`
  fails if a scheduler, an editorial token or a publishing path appears in it.

## Active Search routing

```text
NEWS       -> google_news_rss -> tinyfish -> serper -> ddgs -> brave
WEB        -> tinyfish -> serper -> ddgs -> brave
BACKGROUND -> wikipedia -> tinyfish -> serper -> ddgs
```

Key-gated members degrade explicitly (`<name>:no-key`), never fabricate.

## M3D outcome (2026-09-19, closed 2026-09-20)

`m3/review/M3D_DISCOVERY_STABILITY_REPORT.md` is the authoritative report — read its
**FREEZE** banner first, then §11–§13 for the closing measurements (still-blocked
corpus, the angle-model A/B, final verdicts). Headline:

- **Not "fact extraction collapses"**: across **79 live runs** on 4 recordings, 0
  `CATASTROPHIC_ZERO_YIELD`, fact overlap 0.955–0.977, segmentation byte-identical.
- **Flip root cause (measured):** same facts → divergent angle-proposition wording → different
  cited-fact counts → ±1 rubric point around the threshold → `RESEARCH_MORE` ↔
  `NO_PUBLISHABLE_ANGLE`. 22.2–31.6% OUTCOME_FLIP on the flaky recording, 0% on the stable one.
- **L4 cache verified on the production intake path** (`--cache-verify`): 6/6 seeded replays
  byte-identical, forced reruns always bypass and keep `*.prev.json`, failures/partial runs are
  never frozen. Live verification caught the partial-freeze bug (now fixed).
- **STABILITY ≠ CORRECTNESS**: the cache pins operational reproducibility; it does not certify
  the pinned facts. Forced reruns keep the variance observable.
- Provider quota (Gemini free tier 500/day, then OpenRouter HTTP 402) left recordings
  `b13U-N_Vk9c` / `xvsdi_j7s5c` without a completed baseline; all 17 blocked runs classified as
  `DISCOVERY_DEGRADED`, never editorial zero.
- **Model / provider selection is fully env-driven** — see the block below; no code edit is
  required to switch providers, reorder Gemini models, or pick OpenRouter models. Jev is untouched.

## Provider reality check (measured 2026-09-20)

- **The free Gemini judge pool cannot carry the discovery chain.**
  Live probe: `gemini-2.5-flash-lite` → HTTP 404 (empty body),
  `gemini-3.1-flash-lite` + `-preview` → HTTP 429, `gemini-flash-lite-latest` →
  HTTP 400 (empty body); the first live draft bucket was `gemini-3.6-flash`.
  Fact extraction, angle proposals **and** the grounding judge all sit in the
  judge pool, so a 12-topic run needs 12+ Lite calls and degrades to
  `DISCOVERY_DEGRADED` (`MODEL_CALL_FAILED`) rather than producing a measurement.
  Pacing does not fix it (5 s and 12 s behave the same), so this is quota, not
  self-inflicted RPM pressure. Blocked corpus rows are preserved under
  `var/discovery_stability_corpus2/` (git-ignored).
- **OpenRouter's free tier is not usable for the measurement workload either**
  (upstream 429s + multi-minute stalls; the free arm of the A/B is recorded as
  *not measured*). The paid `openai/gpt-5.6-luna-pro` call path works and is
  fast (~10 s/run) — but paid use needs an explicit owner OK, and the production
  guard is unchanged.
- **OpenRouter is the working alternative** when `GEMINI_API_KEY` is absent;
  `generate.call_model` resolves an explicit key → `GEMINI_API_KEY` →
  `OPENROUTER_API_KEY`, so an OpenRouter-only run **must** unset the Gemini key
  (the A/B script refuses rather than mislabel an arm).
- **Fixed 2026-09-20:** `_call_openrouter` parsed SSE frames without sending
  `"stream": true`, so *every* OpenRouter call returned an empty completion —
  the whole fallback path was silently dead. Regression tests:
  `tests/test_openrouter_transport.py`.

## Model / provider selection (how to steer the fallback chain)

One file owns the whole chain: `src/editor_assistant/drafting/generate.py`. Resolution order:
explicit `api_key` → `GEMINI_API_KEY` → `OPENROUTER_API_KEY` → `RuntimeError`. The `role`
argument only selects the *model pool*, not the provider.

**Set these in `.env` (or export) — all are optional; the file documents the defaults:**

```bash
# Provider / key selection
GEMINI_API_KEY=         # primary provider (Gemini). Unset → falls through to OpenRouter.
OPENROUTER_API_KEY=     # fallback / primary-if-no-gemini.

# Gemini model ORDER per role — comma-separated, first = tried first.  A model that
# returns a daily-quota 429 is skipped for the rest of the process.  Defaults:
#   GEMINI_DRAFT_MODELS (role="draft", quality-critical):
GEMINI_DRAFT_MODELS=gemini-2.5-flash,gemini-3-flash,gemini-3.5-flash,gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-3-flash-preview
#     2.5 Flash (0/20 RPD) and 3 Flash (10/20 RPD) are the only fresh Gemini text-out
#     buckets in the 2026-09-19 quota snapshot; the 3.x family (3.5/3.6/3.7/3.8 Flash) is
#     RPD-exhausted (22/20 each) and kept only to resume after a reset (it will 429 and be
#     skipped until then).
#   GEMINI_JUDGE_MODELS (role="judge", cheap entailment / fact grounding):
GEMINI_JUDGE_MODELS=gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-3.1-flash-lite-preview,gemini-flash-lite-latest
#     2.5 Flash Lite (0/20 RPD, 10 RPM) is the fresh judge bucket; 3.1 Flash Lite is
#     RPD-exhausted (503/500) in that snapshot — kept to resume after a reset.  3.5 Flash
#     Lite is intentionally absent: it rejects thinkingConfig with 400 (even budget=0).

# OpenRouter model selection (only used when no GEMINI_API_KEY).  Set to any
# FREE OpenRouter model id; the `openai/`-prefixed ids are resolved through
# OpenRouter's catalog, not the OpenAI endpoint.  During the test phase ONLY
# FREE models are allowed — paid models are forbidden at call time by
# _check_openrouter_model_not_paid() (raises RuntimeError BEFORE any call).
# Default (the best free option for BG drafting from the current list):
OPENROUTER_MODEL=google/gemma-4-31b          # 262K ctx  $0/M  dense 30.7B, 140+ langs,
#                                       document understanding, coding, reasoning
#   VERIFY the exact id in your OpenRouter account: if Gemma 4 has a paid tier,
#   use google/gemma-4-31b:free instead of the plain id above.  Free-tier models
#   that have a paid tier use the `:free` suffix (e.g. qwen/qwen3.8-27b:free).
#   Models that are always free (no paid tier) use the plain id.
#
#   Full free-model list from the current OpenRouter free catalog (suitable for BG
#   drafting vs not, see src/editor_assistant/drafting/generate.py for the full
#   table with context sizes and notes):
#   Suitable for BG drafting:
#     google/gemma-4-31b               262K ctx  $0/M  (DEFAULT — dense 30.7B, 140+ langs)
#     qwen/qwen3.8-27b:free            262K ctx  $0/M  (Qwen models are generally strong
#                                           at Bulgarian)
#     nvidia/nemotron-3-super:free      262K ctx  $0/M  (120B hybrid MoE, 12B active,
#                                           very capable but more agentic)
#     google/gemma-4-26b-a4b:free       262K ctx  $0/M  (3.8B active MoE)
#     thinkingmachines/inkling-small:free 1.05M ctx $0/M  (12B active MoE)
#     z-ai/glm-5.2:free                 1M ctx    $0/M  (reasoning/coding focus, large
#                                           context but not drafting-primary)
#   NOT suitable for BG drafting (specialized / too small / guardrail / coding):
#     inclusionai/ling-3.0-flash-sante:free  262K ctx  (medical)
#     nvidia/nemotron-3.5-content-safety:free 128K ctx (guardrail/moderation)
#     cohere/north-mini-code:free       256K ctx  (coding agent)
#     nex-agi/nex-n2.5-mini:free        262K ctx  (agentic coding)
#     poolside/laguna-xs-2.1:free       262K ctx  (coding agent)
#     nvidia/nemotron-3-nano-omni:free  256K ctx  (multimodal perception)
#     liquid/lfm-2.5-2.6b:free          66K ctx  (small, "not for knowledge-heavy")
#
#   Paid models explicitly forbidden during the test phase (set by
#   _OPENROUTER_PAID_FORBIDDEN in generate.py — a RuntimeError is raised
#   BEFORE any network call so a forbidden model never consumes quota):
#     openai/gpt-oss-20b              (the previous default — now forbidden)
#     openai/gpt-oss-120b             (more capable, ~5x cost — now forbidden)
#     openai/gpt-oss-20b / -120b     (forbidden during test phase)
#     openai/gpt-5.6-luna-pro         (the paid model authorised ONCE for the M3D
#                                      angle-model A/B; NOT in the forbidden set,
#                                      but paid use needs an explicit owner OK.
#                                      The id previously written here,
#                                      `openai/gpt-luna-5.6`, does not exist in the
#                                      OpenRouter catalog — the real ids are
#                                      openai/gpt-5.6-luna, openai/gpt-5.6-luna-pro,
#                                      ~openai/gpt-luna-latest)
#
# OpenRouter free-tier model: used ONLY when no Gemini key AND no explicit
# OPENROUTER_MODEL AND no explicit model arg — the experimentation path.
# Default (2026, current-age, JSON-instructable):
OPENROUTER_FREE_MODEL=qwen/qwen3.8-27b:free  # free tier — ONLY when no Gemini key AND no
#   explicit OPENROUTER_MODEL AND no explicit model arg (experimentation path).
#   Older default (2024, historical reference only): meta-llama/llama-3.3-70b-instruct
#
GEMINI_THINKING_BUDGET=0   # default: send thinkingConfig.budget=0 → disables internal
#   reasoning for structured JSON output.  -1 = hand control back to the model (do NOT set
#   this with gemini-3.5-flash-lite anywhere in the judge pool — re-introduces the 400).
GEMINI_MIN_GAP_SECONDS=5   # process-wide pacing.  Safe for the 10-RPM 2.5 Flash Lite judge
#   and the 15-RPM 3.1 Flash Lite buckets; for the 5-RPM draft models (2.5 Flash, 3
#   Flash) 5s ≈ 12 calls/min can exceed the cap under a heavy batch → set
#   GEMINI_MIN_GAP_SECONDS=12 if you see self-inflicted 429s on those two.

# Gemini quota snapshot (2026-09-19, AI Studio + Gemini API shared quota, Text-out models,
# format used/limit).  The 3.x Flash family is RPD-exhausted (22/20 each) — the direct
# cause of the M3D 429s.  The only fresh Gemini text-out buckets are gemini-2.5-flash
# (0/20 RPD, 5 RPM), gemini-2.5-flash-lite (0/20 RPD, 10 RPM) and gemini-3-flash
# (10/20 RPD, 2 RPM) — added to the pools as fallbacks.  0/0-allocated models (Gemini 2
# Flash, 2 Flash Lite, Gemini 2.5 Pro, Gemini 3.1 Pro, Gemini 2.5 Flash TTS, etc.) are
# not usable.
#   gemini-3.5-flash        RPM 3/5   TPM 11.07K/250K  RPD 22/20  (exhausted)
#   gemini-3.6-flash        RPM 5/5   TPM 5.41K/250K   RPD 22/20  (exhausted)
#   gemini-3.7-flash        RPM 4/5   TPM 12.49K/250K  RPD 22/20  (exhausted)
#   gemini-3.8-flash        RPM 3/5   TPM 13.63K/250K  RPD 22/20  (exhausted)
#   gemini-3-flash          RPM 2/5   TPM 9.09K/250K   RPD 10/20   (half-used, fallback)
#   gemini-2.5-flash        RPM 0/5   TPM 0/250K       RPD 0/20    (fresh, fallback)
#   gemini-2.5-flash-lite   RPM 0/10  TPM 0/250K       RPD 0/20    (fresh, judge only)
#   gemini-3.1-flash-lite   RPM 20/15 TPM 67.33K/250K  RPD 503/500  (exhausted, judge pool)
#   gemini-3.5-flash-lite   RPM 15/15 TPM 25.28K/250K  RPD 288/500  (nearly exhausted;
#                             dropped from judge pool — rejects thinkingConfig 400)
#   -preview/-latest judge suffixes: endpoint model ids not verifiable here without a live
#   key (Gemini models.list returned 403); assumed gemini-3.1-flash-lite-preview /
#   gemini-flash-lite-latest.  Whether they share the 503/500 RPD bucket or have their own
#   is unconfirmed — verify with a live key before relying on them.
```

Other work-capable OpenRouter picks (set `OPENROUTER_MODEL` to any of these):
`openai/gpt-oss-120b` (more capable, ~5× cost), `qwen/qwen3.8-flash`, `z-ai/glm-5.3-flash`,
`google/gemini-3.6-flash` / `3.7-flash` / `3.8-flash` (Gemini served via OpenRouter),
`deepseek/deepseek-v4-flash-0731`. Other free-tier picks: `deepseek/deepseek-v4-flash-0731:free`,
`nvidia/nemotron-3.5-lightning:free`. The full current catalog is in `generate.py` (2026-09-19
snapshot comments) and at https://openrouter.ai/api/v1/models — do not invent model ids.

**Jev is untouched by every knob above** — it has its own path (`workflow/jev.py` + `JEV_MODEL`).

**Are the Gemini flash-lite models good enough as judges?** Measured answer, with the evidence
attached: yes for the *mechanical/factual* jobs, with known noise on the *quality* judgment that
is acceptable because the deterministic assessor stays authoritative.

- **Factual jobs (fact extraction, semantic verification of drafted claims):** the Lite pool is
  the production judge for these and has never been the source of an editorial zero-yield. Across
  the M3D corpus the 17 quota-blocked runs were correctly classified `DISCOVERY_DEGRADED`, never
  editorialized. The Lite buckets (500/day, 15 RPM) are cheap and fast enough that the judge role
  is not the cost or rate-limit bottleneck.
- **Quality judgment (the assessor, `discovery._model_assess`):** the M2S-R3 Part C shadow pass
  ran the production judge pool blind against the deterministic assessor on all 24 candidate angles
  from the 7 V2 recordings and got **17/24 full agreement (70.8%)**, 0 unavailable. All 7
  disagreements are status flips on the *routine-vs-concrete boundary* — the hardest judgment the
  M2S semantic audit named — and they cut both ways (4 more permissive, 3 stricter). That is
  measurable noise, not silence, and it is expected: Lite models are smaller than the full Flash
  drafting models and the assessor is a contested borderline call by construction.
- **Verdict:** keep the Lite pool for judge roles (factual grounding + semantic gate). Do **not**
  promote a Lite model to the quality-critical drafting pool or to any path that overrides the
  deterministic assessor. If a future milestone ever wants a stronger judge, the upgrade path is a
  full Flash model in `GEMINI_JUDGE_MODELS` (consumes the ~20/day drafting bucket, so budget
  planning is required) — that is a milestone-scope decision, not a config tweak. The M3J shadow
  evaluation (`scripts/evals/jev_shadow_eval.py --all`) is the place any such change gets measured
  against the deterministic assessor before it touches production.

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q                 # full suite, offline (695)
ruff check src tests scripts
ruff format --check src tests scripts
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench   # M3A UI (127.0.0.1:8123)
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --apply    # M4A.1 source pack
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect            # M4A.1 cron entry point
PYTHONPATH=src python3 scripts/m3a_smoke.py         # M3A scripted smoke: 25/25
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all       # M3J shadow eval (no authority)
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-intake "<URL>"  # M3B intake (no drafting)
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-intake "<URL>" --force-discovery  # rerun model stages (keeps *.prev.json)
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench                # + GET /intake displays results
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch add "<URL>"   # M3B.1 queue
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch status         # queue + cooldown
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch run --cron     # cron entry point
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch reset          # revive parked entries
# M3D measurement harness
PYTHONPATH=src python3 scripts/evals/discovery_stability.py --summarize --out var/discovery_stability_corpus
PYTHONPATH=src python3 scripts/evals/discovery_stability.py --check-determinism
PYTHONPATH=src python3 scripts/evals/discovery_stability.py --cache-verify --input YsqD4T0D850 \
  --cached-runs 6 --forced-runs 4 --cache-seed YsqD4T0D850__r003 \
  --cache-rows-dir var/discovery_stability_corpus --out var/discovery_stability_cache
# M3D angle-layer model A/B (facts pinned; OpenRouter arms need no GEMINI_API_KEY)
set -a; . ./.env; set +a && unset GEMINI_API_KEY
PYTHONPATH=src python3 scripts/evals/angle_model_ab.py --runs 5 \
  --facts-from YsqD4T0D850__r003 --facts-rows-dir var/discovery_stability_corpus \
  --arms luna-5.6 --allow-paid
```

The discovery stage cache lives in `var/discovery_stage_cache/` (git-ignored);
deleting a `*.json` entry forces a fresh model run on the next intake.

Exit codes for `youtube-batch run`: `0` ok · `1` systemic abort (consecutive
failures with zero successes) · `2` breaker tripped or a cooldown is active ·
`3` another run holds the lock. `youtube-intake` shares that lock and also exits
`3` when the nightly run holds it.

Settled M3B.1 behaviours (decided at review, 2026-09-19; see `BACKLOG.md`):

- `YOUTUBE_FALLBACK` defaults **off** (opt-in: third-party contact, 0/9 live
  instances served captions).
- A **block stops the run**; only ordinary client-specific failures rotate
  clients. The yt-dlp default client stays last in the rotation.
- Out-of-range `YOUTUBE_*` values are **clamped and reported**
  (`policy warning:` line), never silently applied.
- The registry/queue split is intentional and stays: queue deletion loses no
  evidence.

## Editor feedback state

`EDITORIAL_EFFECTIVENESS = PENDING`. The V2 editor sample review and the
`CONCRETE_ACTION_NEEDS_RESEARCH` vs `ROUTINE_REPORT_VETO` calibration are still
awaiting the human editor. No rubric/threshold change is justified yet.

## Allowed next work

**Active work: M4 — Daily Newsroom**, sliced M4A–M4E in `BACKLOG.md` (M4A = Source
Registry + Scheduled Collection). M4 is a product/operations milestone: the largest
remaining gap is not intelligence, it is that *the editor has no daily system that
simply opens in the morning and works*. Slice order: **M4A** source registry +
collection → **M4B** story inbox + source/status UX → **M4C** story identity /
new development → **M4D** Telegram editorial alerts → **M4E** workflow polish. One
slice at a time, reviewed and frozen before the next; plan: `m4/review/M4A_PLAN.md`.

M4A.1 / M4B state (2026-09-20): **BUILT, LIVE-PROVEN, awaiting review/freeze.**
M4A (`sources_registry.py` + `sources` CLI + Workbench «Източници» +
`newsroom_run.py` + `inbox_store.py`) was corrected and completed by:

- `workflow/default_sources.py` — a declarative **35-entry** catalogue; a new
  install seeds **30 active** sources (9 core `each_run` + 21 `daily`) and
  catalogues **5 disabled** optionals. `sources defaults --preview|--apply` is
  additive, idempotent and never re-enables or overwrites an editor-owned entry.
- `workflow/blocked_domains.py` — editor-owned policy, default `flagman.bg`, in
  force before any editor action; filters broad-monitor results before inbox
  insertion (using the Google News publisher domain, not its opaque redirect
  link) and refuses a direct blocked source.
- `workflow/source_health.py` — real cadence (`each_run`/`daily`/`weekly` on the
  `Europe/Sofia` day) plus a separate operational health store
  (`OK`/`EMPTY`/`FAILED`/`NEVER_RUN`), shown in the Workbench.
- Safe bootstrap (≤72 h / 10 newest for news, ±45-day window for calendars,
  20 items per source per run) and one shared collection lock between cron and
  the Workbench button.
- **Publisher authority is never inherited** (post-review correction): a registry
  entry has its own `domain`, each inbox item stores `publisher_domain` /
  `publisher_kind` / `factual_authority` resolved from the **real publisher**, and
  `source_id`/`source_kind` mean "how it was discovered". An unapproved publisher
  gets no authority. Live: a "Прокуратура Бургас" item published by `news.bg` or
  Facebook carries no authority, while one published by БТА carries media
  authority.
- M4B daily inbox: default **NEW** view, summary counts, practical filters,
  pagination, per-item actions, «Събери новите сега» / «Пробен преглед» (both via
  the same one-shot service) and a readable source-problem list.

Reports: `m4/review/M4A1_DEFAULT_SOURCE_PACK_REPORT.md`,
`m4/review/M4B_DAILY_INBOX_REPORT.md`; research `m4/M4_DEFAULT_SOURCE_STACK_RESEARCH.md`.
None of it is scheduled by the repo: the cron entry point is still a one-shot
process (schedule documented in `RUNBOOK.md` §0e).

```text
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --preview
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --apply
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources list
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect --dry-run   # no network
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect             # cron calls this
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect --force     # ignore cadence
```

Boundary held in M4A.1/M4B: no AI angles, no research, no drafting, no story
identity, no ranking, no alerts — `SOURCE -> normalized INBOX ITEM` and stop.
A structural test fails if a story-identity/AI identifier appears in the newsroom
modules. M4C (story identity / new development) is next.

YouTube (frozen) — **maintenance only**, and only on observed production pain:

- Tune pacing via `YOUTUBE_*` env values only (never by editing the policy
  module) once real nightly runs show real block/latency data.
- Re-probe the Invidious instance fleet before trusting the bypass; instances
  rotate and die, and the per-instance reasons now print in the run output.
- `youtube-batch doctor` (P2/P3 ops nicety): yt-dlp version, cookies path,
  curl-cffi availability, stale lock, active cooldown, fallback state.
- The optional one-knob switch of the **angle stage** to a stronger model pool
  (measured in the M3D A/B) — backlog, gated on observed editor pain.

Backlog / measurement, not milestones:

- The provider-blocked corpus (recordings `b13U-N_Vk9c`, `xvsdi_j7s5c`) still has
  no 10-run baseline: the free Gemini judge pool cannot carry it (see *Provider
  reality check*). Re-run only if a real need appears; the runner stays resumable
  (`--runs 10 --out var/discovery_stability_corpus2`).
- Bounded execution retries for discovery model calls (L1 of the plan) — open in
  `BACKLOG.md`.
- M3C automatic research enrichment — any live-evidence write only via the
  canonical `workflow/live_store.py` writer.
- `youtube-batch doctor` (P2/P3 ops nicety): yt-dlp version, cookies path,
  curl-cffi availability, stale lock, active cooldown, fallback state.
- A future `M3J.1 — Semantic Rescue Evaluation`
  (`deterministic borderline/reject → Jev grounding → manual adjudication`) on
  ~100–200 borderline cases **before** Jev could become a second-stage verifier.
- Re-running a frozen M3J experiment is fine (delete that file under
  `var/jev_eval/` to force a fresh run); the fixtures themselves stay frozen.
- Anything else goes to `BACKLOG.md`, never into a change.

Not allowed now: CMS publishing, LIVE 6–10, rubric/threshold changes, Jev
production authority, editor-profile learning, **and any further YouTube
optimization without observed production pain** (`YOUTUBE_PIPELINE_V1` is frozen).

## Required optional environment variables

```text
TINYFISH_API_KEY=      # search/fetch provider (optional; keyless chain degrades)
TYPESAFE_API_KEY=      # Jev live evaluation only (optional; offline tests stay green)
JEV_MODEL=jev-latest   # Jev model alias (optional)
TELEGRAM_TEST_BOT_TOKEN / TELEGRAM_TEST_CHAT_ID   # only for the Telegram TEST send
# M3B.1 intake pacing/anti-ban (all optional; conservative defaults in
# workflow/youtube_policy.py, documented in .env.example and RUNBOOK.md §0d).
YOUTUBE_NIGHTLY_CAP / YOUTUBE_DELAY_MIN_S / YOUTUBE_DELAY_MAX_S
YOUTUBE_STARTUP_JITTER_MIN_S / YOUTUBE_STARTUP_JITTER_MAX_S
YOUTUBE_MAX_ATTEMPTS / YOUTUBE_BLOCK_COOLDOWN_H / YOUTUBE_PLAYER_CLIENTS
YOUTUBE_IMPERSONATE / YOUTUBE_COOKIES_FILE / YOUTUBE_PROXY
YOUTUBE_FALLBACK / YOUTUBE_INVIDIOUS_INSTANCES
```

Never commit secrets. Missing keys must always degrade explicitly, never fabricate.

## Authoritative reports

- `m3/review/M3D_DISCOVERY_STABILITY_REPORT.md` — discovery stability, flip root cause, L4 cache
- `m3/review/M3A_EDITOR_WORKBENCH_REPORT.md` — workbench (frozen)
- `m3/review/M3A_STABILIZATION_REPORT.md` — M3A Part A
- `m3/review/M3J_JEV_SHADOW_EVALUATION.md` — Jev shadow evaluation
- `m3/review/M3B_YOUTUBE_INTAKE_REPORT.md` — YouTube intake + real-world Jev shadow
- `m3/review/M3B1_INTAKE_HARDENING_REPORT.md` — anti-ban, pacing, queue, cron
- `m3/review/M3B1_CODE_REVIEW.md` — self code review, fixed bugs, open questions
- `m2/review/*` — M2S history (TinyFish, transcripts, enrichment audit)
