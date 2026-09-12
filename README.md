# editor-assistant (chernomorie-bg.com) — M0 Safety Foundation

Assistant to the editor-in-chief. M0 is the **safety foundation only**:
no Telegram, no WordPress, no scrapers, no LLM, no network writes.

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
