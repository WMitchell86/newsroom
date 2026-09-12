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

## Layout

```text
src/editor_assistant/  config.py, logging_setup.py (stdlib only)
tests/                 smoke + safety tests (no network)
fixtures/              empty in M0 (M1.1 adds parser fixtures)
.ai/skills/            harness skill files
```
