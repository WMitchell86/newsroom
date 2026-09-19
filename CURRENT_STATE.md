# CURRENT_STATE.md — authoritative state for the next harness run

**Read this first.** It is the only current-state document.

> `handoff.md` and `MILESTONE.md` are **chronological history**.
> Older `HARNESS_PROMPT_*.md` files are **historical, not current instructions**.
> When they disagree with this file, this file wins.

Last updated: 2026-09-19 (M3A stabilization + M3J Jev shadow evaluation, live).

## Checkpoint

- Base commit: `60d09d2` (main) + the M3A-stabilization / M3J working tree
  (uncommitted at time of writing).
- Test baseline: **512 passed**, full suite, offline (was 481).
- Gates: `ruff check src tests scripts` + `ruff format --check src tests scripts`
  clean; M3A smoke **25/25**.

## Verdicts

```text
EDITOR_WORKBENCH_ENGINEERING        = PROVEN
SEARCH_EXECUTION_ENGINEERING        = PROVEN
TINYFISH_SEARCH                     = ADOPTED
TINYFISH_FETCH                      = AVAILABLE / NOT_YET_PROVEN
TRANSCRIPT_DISCOVERY_ENGINEERING    = PROMISING+
TRANSCRIPT_RESEARCH_ENRICHMENT      = PROMISING
M3A_STABILIZATION                   = PROVEN
JEV_INTEGRATION                     = READY
JEV_CORROBORATION                   = NOT_PROMISING  (standalone decision; this sample)
JEV_GROUNDING                       = PROMISING
JEV_ANGLE_SIGNALS                   = PROMISING
JEV_PRODUCTION_AUTHORITY            = NONE
EDITORIAL_EFFECTIVENESS             = PENDING
```

Jev was evaluated live (TypeSafe SDK 0.6.0, effective model `jev-1.13.0`,
149/149 calls OK). Shadow results live under the ignored `var/jev_eval/`.
No Jev threshold or production authority exists. Details:
`m3/review/M3J_JEV_SHADOW_EVALUATION.md`.

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

## Active Search routing

```text
NEWS       -> google_news_rss -> tinyfish -> serper -> ddgs -> brave
WEB        -> tinyfish -> serper -> ddgs -> brave
BACKGROUND -> wikipedia -> tinyfish -> serper -> ddgs
```

Key-gated members degrade explicitly (`<name>:no-key`), never fabricate.

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q                 # full suite, offline (512)
ruff check src tests scripts
ruff format --check src tests scripts
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench   # M3A UI (127.0.0.1:8123)
PYTHONPATH=src python3 scripts/m3a_smoke.py         # M3A scripted smoke: 25/25
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all       # M3J shadow eval (no authority)
```

## Editor feedback state

`EDITORIAL_EFFECTIVENESS = PENDING`. The V2 editor sample review and the
`CONCRETE_ACTION_NEEDS_RESEARCH` vs `ROUTINE_REPORT_VETO` calibration are still
awaiting the human editor. No rubric/threshold change is justified yet.

## Allowed next work

- M3B YouTube URL intake, **or** M3C automatic research enrichment — one at a
  time, only via the canonical `workflow/live_store.py` writer.
- A larger, editor-labeled corroboration set and manual review of the grounding
disagreements (the open question) — then decide whether Jev earns a place.
- Re-run the M3J shadow eval after any fixture or prompt change (results are
  under `var/jev_eval/`; delete a file to force a fresh run for that experiment).
- Anything else goes to `BACKLOG.md`, never into a change.

Not allowed now: CMS publishing, LIVE 6–10, rubric/threshold changes, Jev
production authority, editor-profile learning.

## Required optional environment variables

```text
TINYFISH_API_KEY=      # search/fetch provider (optional; keyless chain degrades)
TYPESAFE_API_KEY=      # Jev live evaluation only (optional; offline tests stay green)
JEV_MODEL=jev-latest   # Jev model alias (optional)
TELEGRAM_TEST_BOT_TOKEN / TELEGRAM_TEST_CHAT_ID   # only for the Telegram TEST send
```

Never commit secrets. Missing keys must always degrade explicitly, never fabricate.

## Authoritative reports

- `m3/review/M3A_EDITOR_WORKBENCH_REPORT.md` — workbench (frozen)
- `m3/review/M3A_STABILIZATION_REPORT.md` — this pass's Part A
- `m3/review/M3J_JEV_SHADOW_EVALUATION.md` — Jev shadow evaluation
- `m2/review/*` — M2S history (TinyFish, transcripts, enrichment audit)
