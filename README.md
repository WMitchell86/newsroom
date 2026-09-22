# editor-assistant (chernomorie-bg.com)

Assistant to the editor-in-chief. M0 was the **safety foundation only**:
no WordPress, no scrapers, no LLM, no network writes. The single external
write added since is the M1.4B Telegram **TEST-channel** alert, which stays
dry-run by default (see below).

Full harness rules: [`AI_HARNESS_EDITOR_ASSISTANT.md`](./AI_HARNESS_EDITOR_ASSISTANT.md).
**Current state: [`CURRENT_STATE.md`](./CURRENT_STATE.md).** (`MILESTONE.md` and
`handoff.md` are chronological history.) Deferred ideas: [`BACKLOG.md`](./BACKLOG.md).
Alert format calibration (editor decisions pending): [`UX_AUDIT.md`](./UX_AUDIT.md).
Session guides for AI agents: [`agents.md`](./agents.md) (how to work in this repo).

## Safety defaults

| Setting        | Default | Meaning                                    |
|----------------|---------|--------------------------------------------|
| `AUTO_PUBLISH` | `false` | Hard default; cannot publish in M0 at all |
| `DRY_RUN`      | `true`  | Future external writes default to dry-run |

## Quickstart (clean checkout)

```bash
cp .env.example .env                 # optional; safe placeholders only
PYTHONPATH=src python3 -m pytest -q  # full suite, offline, no side effects
```

Note: `pip install -e .` is blocked on this machine (PEP 668 externally-managed
environment) — always run tests and CLIs with `PYTHONPATH=src`.

Expected: smoke + safety tests pass, no network calls, no external side effects.

## Editor Workbench (local browser UI)

The editor-facing surface: a daily newsroom home, stories, materials, sources and
operator settings — in a browser instead of Markdown files. The landing page at
`/` is the daily «Начало»; the older M3A case workflow (review LIVE cases,
inspect sources/warnings, edit, answer the structured review questions,
finalize) still lives under **«Случаи»** at `/cases`.

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench   # http://127.0.0.1:8123/
PYTHONPATH=src python3 -m editor_assistant.workflow.workbench       # equivalent
```

Binds `127.0.0.1` by default; `--host`/`--port` exist, and `--host` is opt-in
(there is **no auth** on this local MVP). Stdlib only — no framework, no build
chain; JavaScript is optional feedback only (confirm dialogs + busy overlay).

The workbench lives under `workflow/`, which the M0 smoke guard's token scan
`src/editor_assistant/{*.py,sources,notify}` does not cover — so it adds **no**
new allow-listed exceptions to that guard. There is no publish capability in it.

Safety: the AI draft is immutable; **Запази работно копие** is never
finalization; **Финализирай редакторската версия** is an explicit, validated
action that goes through `cases.record_editor_final`. If a newer AI draft landed
since the working copy was started, finalization is refused (409) until the
editor explicitly accepts the new version as the base. There is no publish path.
See `m3/review/M3A_EDITOR_WORKBENCH_REPORT.md`. Scripted smoke (against a copy of
the store, never the live one): `PYTHONPATH=src python3 scripts/m3a_smoke.py` (25/25).

## M3J Jev shadow evaluation (optional, no production authority)

TypeSafe **Jev** is integrated only as a *shadow semantic judge* for evaluation:
it answers narrow typed questions over public-source material and never decides
newsworthiness, readiness, factual validity or publication. The SDK is an
optional extra, so normal functionality is untouched when it (or the key) is absent.

```bash
pip install 'editor-assistant[jev]'                      # optional: typesafe-sdk
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all
```

Without `TYPESAFE_API_KEY` the runner reports `JEV_CAPABILITY_UNAVAILABLE` and
changes nothing. Frozen fixtures + method: `fixtures/evals/jev/README.md`.
Adapter: `workflow/jev.py`. Report: `m3/review/M3J_JEV_SHADOW_EVALUATION.md`.

## M3B YouTube URL intake (no drafting)

One YouTube URL → canonical identity → raw timestamped SRT → discovery V2 →
readiness, with an optional Jev **shadow** layer. Requires `yt-dlp` on PATH for
transcription (metadata + subtitles only; no media download).

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-intake \
  "https://www.youtube.com/watch?v=<id>" [--language bg] [--skip-jev-shadow]
```

Raw SRT is authoritative (`AUTO_CAPTION`); transcripts are content-addressed and
cached under `var/youtube_intake/` (re-runs reuse; a changed transcript is never
silently overwritten). `NO_PUBLISHABLE_ANGLE` is a valid outcome, not a failure.
The Workbench **displays** completed intakes at `/intake` (initiation stays CLI).
There is no drafting, no scheduler, no monitoring, no publish path.
See `m3/review/M3B_YOUTUBE_INTAKE_REPORT.md`.

## M3B.1 YouTube intake queue + nightly run (anti-ban)

`youtube-intake` is the interactive one-URL path. `youtube-batch` is the slow,
paced path and the **only** cron entry point (a one-shot process — the repo
contains no scheduler and installs no timer):

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch add "<URL>"
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch status
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch run --cron
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch reset
```

Guardrails (defaults in `workflow/youtube_policy.py`, all env-tunable): one video
at a time, a random pause between entries, a nightly cap, random startup jitter
in `--cron` mode, player-client rotation, a lock file, an exponential backoff
ladder, and a **circuit breaker** that stops the run and cools the IP down on the
first explicit block. Interactive `youtube-intake` takes the same lock. Exit
codes: `0` ok · `1` systemic abort · `2` breaker / cooldown active · `3` locked.

The Invidious bypass is **off by default** (`YOUTUBE_FALLBACK=on` opts in: it
sends the video id to an unrelated third party). A hand-edited value outside its
safety bound is clamped, and the run prints which value it clamped.

Pacing/jitter are the *only* scheduling-adjacent surface: cron installs nothing
by itself and there is no daemon, retry thread or background worker.

See `m3/review/M3B1_INTAKE_HARDENING_REPORT.md` (design) and
`m3/review/M3B1_CODE_REVIEW.md` (review + settled decisions), plus `RUNBOOK.md`
§0d.

## M4 Daily Newsroom (sources + stories + daily materials)

The editor owns which sources are watched, and opens a daily inbox instead of
Markdown case files.

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --preview  # no write
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --apply    # add missing defaults
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources list
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect --dry-run  # zero network
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect            # cron calls this
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom stories update --dry-run  # M4C plan
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom stories update     # assign to stories
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom refresh            # collect -> stories -> summary
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models status      # per-role model view
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models validate    # check model IDs
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list                     # qualification plan
```

The Workbench is meant for a **non-technical editor**, so the first screen answers
"what is new?": `/` = **«Начало»** (read-only daily landing — unreviewed stories,
unreviewed materials, arrived-today counts in Europe/Sofia, the newest stories,
and a three-step «Как се работи» card with the very button to press). The
navigation has two levels: `Начало · Истории · Материали · Източници` and
`AI модели · Случаи · YouTube` under «Настройки и архив:». The frozen M3A case
queue lives at `/cases` (old `/?filter=…` links still resolve), the stylesheet is
served once at `/static/style.css`, and long actions disable their button and show
a «Събиране…» overlay. Destructive buttons ask for confirmation first.
Report: `m4/review/WORKBENCH_UI_OVERHAUL_REPORT.md`.

The Workbench adds **«Истории»** (`/stories` + `/stories/{id}`: real-world stories
with `издатели / публикации / откривания` counted separately, a chronology, unique
publications grouped by publisher, and editor **split** / **merge** corrections),
**«Източници»** (`/sources`: table with health, next collection,
add/edit/enable/disable/mute-until/priority/monitoring-only/factual-authority, a
compact **«Забранени домейни»** policy and additive default controls) and
**«Материали»** (`/inbox`: default **NEW** view, real Europe/Sofia daily counts,
filters, pagination, per-item actions and **«Събери новите сега»** /
**«Пробен преглед»**).

A new install seeds **30 active** default sources (9 core every-run + 21 daily)
from a declarative catalogue (`workflow/default_sources.py`); 5 optional sources
are catalogued but disabled. No outlet or feed URL is invented: the one verified
feed is used directly, every other entry is a publisher/locality-constrained
monitoring query. `flagman.bg` is never a source and is blocked as a domain.

Cadence is operational (`each_run`/`daily`/`weekly` on the Europe/Sofia day) with
a separate health store (`OK`/`EMPTY`/`FAILED`/`NEVER_RUN`); **every run** keeps only
dated news from the last 72 h (the first run of a source additionally caps to the 10
newest), and a ±45-day event window applies only when a collector supplies a real
`event_at` — an article's publication time is never treated as an event date. The
repository still installs **no timer** — cron is the operator's (see `RUNBOOK.md`
§0e) and one shared lock makes cron and the Workbench button safe to run
concurrently.

Story identity (M4C) is deterministic first: exact publication identity collapses the
same article found by several monitors, a conservative title/time/token test groups
the obvious cross-publisher pairs, and only the ambiguous shortlist reaches one narrow
semantic relation (`role="story"`). A failure of that step **never** merges — the item
stays a separate story marked «за преглед». Collected rows are never rewritten or
deleted: stories reference them.

Reports: `m4/review/M4A1_DEFAULT_SOURCE_PACK_REPORT.md`,
`m4/review/M4B_DAILY_INBOX_REPORT.md`, `m4/review/M4B1_FEED_STABILIZATION_REPORT.md`,
`m4/review/M4C_STORY_IDENTITY_REPORT.md`, `m4/review/M4C_STORY_REVIEW_PACK.md`.
**Next milestone: M4D Telegram editorial alerts** — see `BACKLOG.md`.

## M1.4B Telegram TEST delivery (manual, opt-in)

Enqueue intents while ingesting, then deliver to the **test** chat by hand:

```bash
PYTHONPATH=src python3 -m editor_assistant.check_state \
  --db var/editor_assistant.sqlite3 \
  --live https://burgascouncil.org/last-update.xml          # ingest + enqueue intents
PYTHONPATH=src python3 -m editor_assistant.send_telegram    # dry run: preview 1 message, no HTTP
PYTHONPATH=src python3 -m editor_assistant.send_telegram --send   # send 1 pending row (needs env below)
```

Real sending requires ALL of: `--send`, `DRY_RUN=false`, and
`TELEGRAM_TEST_BOT_TOKEN` / `TELEGRAM_TEST_CHAT_ID` in the environment
(never committed; `.env` and `*.sqlite3` are git-ignored). If you keep
credentials in an uncommitted `.env`, source it first: `set -a; . ./.env; set +a`.
Limit is 1 by
default, hard max 5. Failures leave rows PENDING; delivery is at-least-once
(duplicate TEST-chat messages are possible after a crash between send and
`delivered_at` write — by design). No retries, no scheduler.

## M1.2 live read-only run (manual, needs internet)

```bash
PYTHONPATH=src python3 -m editor_assistant.fetch_live
# optional explicit URL: PYTHONPATH=src python3 -m editor_assistant.fetch_live https://burgascouncil.org/last-update.xml
```

Prints HTTP envelope then normalized `SourceItem[]` JSON to stdout.
Read-only: no persistence, no Telegram/WordPress/LLM.

## Layout

```text
src/editor_assistant/  package (stdlib only)
  sources/             RSS fetch + parse + HTML description normalization
  state/               fingerprint, SQLite item_state, process_items
  notify/              outbox, renderer, telegram transport
  workflow/            editorial workflow contracts + CLIs (incl. workbench/)
  *.py                 CLIs: check_state, fetch_live, send_telegram
tests/                 offline tests; HTTP mocked where present
fixtures/              RSS fixtures (Burgas council, HTML description)
  evals/jev/           frozen M3J Jev shadow-evaluation corpus (public-source only)
scripts/               tracked verification/eval tools (m3a_smoke.py, evals/jev_shadow_eval.py)
var/youtube_intake/    M3B intake registry + raw transcripts + summaries (git-ignored)
.ai/skills/            harness skill files
var/                   runtime SQLite (git-ignored, never committed)
```
