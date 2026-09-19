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

## M3A Editor Workbench (local browser UI)

The editor-facing surface over the frozen workflow: review LIVE cases, inspect
sources/warnings, edit, answer the structured review questions and finalize —
in a browser instead of Markdown files.

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench   # http://127.0.0.1:8123/
PYTHONPATH=src python3 -m editor_assistant.workflow.workbench       # equivalent
```

Binds `127.0.0.1` by default; `--host`/`--port` exist, and `--host` is opt-in
(there is **no auth** on this local MVP). Stdlib only — no framework, no build
chain, no JavaScript required.

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
