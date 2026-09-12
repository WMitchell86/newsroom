# editor-assistant (chernomorie-bg.com) — M0 Safety Foundation

Assistant to the editor-in-chief. M0 is the **safety foundation only**:
no WordPress, no scrapers, no LLM, no network writes. The single external
write added since is the M1.4B Telegram **TEST-channel** alert, which stays
dry-run by default (see below).

Full harness rules: [`AI_HARNESS_EDITOR_ASSISTANT.md`](./AI_HARNESS_EDITOR_ASSISTANT.md).
Current status: [`MILESTONE.md`](./MILESTONE.md). Deferred ideas: [`BACKLOG.md`](./BACKLOG.md).

## Safety defaults

| Setting        | Default | Meaning                                    |
|----------------|---------|--------------------------------------------|
| `AUTO_PUBLISH` | `false` | Hard default; cannot publish in M0 at all |
| `DRY_RUN`      | `true`  | Future external writes default to dry-run |

## Quickstart (clean checkout)

```bash
cp .env.example .env   # optional; safe placeholders only
pip install -e ".[dev]"
pytest
```

Expected: smoke + safety tests pass, no network calls, no external side effects.

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
(never committed; `.env` and `*.sqlite3` are git-ignored). Limit is 1 by
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
src/editor_assistant/  config.py, logging_setup.py (stdlib only)
tests/                 smoke + safety tests (no network)
fixtures/              empty in M0 (M1.1 adds parser fixtures)
.ai/skills/            harness skill files
```
