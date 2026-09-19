# CURRENT_STATE.md — authoritative state for the next harness run

**Read this first.** It is the only current-state document.

> `handoff.md` and `MILESTONE.md` are **chronological history**.
> Older `HARNESS_PROMPT_*.md` files are **historical, not current instructions**.
> When they disagree with this file, this file wins.

Last updated: 2026-09-19 (M3D Discovery Reproducibility & Stability: harness built, 79 live
runs, flip root-caused, L4 cache verified; provider quota blocked the rest).

## Checkpoint

- Base commit: `860f582` (frozen M3B.1) + the M3D harness commits.
- Test baseline: **695 passed**, full suite, offline (was 653).
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
UNSEEN_VALIDATION                   = PENDING (provider quota)
```

Jev was evaluated live (TypeSafe SDK 0.6.0, effective model `jev-1.13.0`,
149/149 calls OK). `JEV_INTEGRATION = PROVEN` means the integration is proven,
not the model for production. Shadow results live under the ignored
`var/jev_eval/`. No Jev threshold or production authority exists. **M3J is
frozen.** Details: `m3/review/M3J_JEV_SHADOW_EVALUATION.md`.

## Frozen boundaries (do not change without an approved scope change)

- `AUTO_PUBLISH=false`, `DRY_RUN=true` hard defaults; the only external write is
  the Telegram **TEST** channel.
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

## M3D outcome (2026-09-19)

`m3/review/M3D_DISCOVERY_STABILITY_REPORT.md` is the authoritative report. Headline:

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

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q                 # full suite, offline (691)
ruff check src tests scripts
ruff format --check src tests scripts
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench   # M3A UI (127.0.0.1:8123)
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

- **Finish the provider-blocked M3D measurements** once quota resets (Gemini free tier resets
  daily): re-run recordings `b13U-N_Vk9c` and `xvsdi_j7s5c`
  (`--runs 10 --out var/discovery_stability_corpus2`), then repeat `--cache-verify` with live
  forced runs so `forced_rerun_observes_variance` is proven live, not only by unit test.
- **M3D residual-risk decision (editor):** accept `OUTCOME_FLIP` (22–32% on the flaky recording)
  as residual risk under the L4 cache, or scope a mitigation (fact-id-stable prompt, or a
  readiness rubric less sensitive to ±1 point). Discovery semantics and thresholds stay frozen
  until then.
- Bounded execution retries for discovery model calls (L1 of the plan) — still open.
- Run M3B intake on **2 genuinely unseen recordings** to complete Part M
  (real transcript discovery is `PROMISING` until then).
- Tune pacing via `YOUTUBE_*` env values only (never by editing the policy
  module) once the first real nightly runs show real block/latency data.
- Re-probe the Invidious instance fleet before trusting the bypass; instances
  rotate and die, and the per-instance reasons now print in the run output.
- M3C automatic research enrichment — one milestone at a time, any live-evidence
  write only via the canonical `workflow/live_store.py` writer. **Ranks below
  M3D** (the semantic layer is now the weak link, not the transport).
- `youtube-batch doctor` (P2/P3 ops nicety): yt-dlp version, cookies path,
  curl-cffi availability, stale lock, active cooldown, fallback state.
- A future `M3J.1 — Semantic Rescue Evaluation`
  (`deterministic borderline/reject → Jev grounding → manual adjudication`) on
  ~100–200 borderline cases **before** Jev could become a second-stage verifier.
- Re-running a frozen M3J experiment is fine (delete that file under
  `var/jev_eval/` to force a fresh run); the fixtures themselves stay frozen.
- Anything else goes to `BACKLOG.md`, never into a change.

Not allowed now: CMS publishing, LIVE 6–10, rubric/threshold changes, Jev
production authority, editor-profile learning.

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
