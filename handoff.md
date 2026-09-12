# handoff.md — session-to-session state

Last updated: 2026-09-12 · HEAD: `5c21268` on `main` · Suite: 95 passed, ruff clean
Read first: `agents.md` (how to work here) · `MILESTONE.md` (current gate, top section)

## Status
DONE (committed): M0 bootstrap · M1.1 RSS parser + fixture · M1.2 live read-only fetch ·
M1.2.1 HTML description normalization · M1.3 SQLite state + SHA-256 fingerprint ·
M1.4A durable outbox + renderer · M1.4B Step A (explicit intents) ·
M1.4B Telegram TEST transport + CLI (offline-verified, commits `0c4daae` + `5c21268`).

PENDING (needs the human): **live Telegram send with real credentials.**
`MILESTONE.md` M1.4B status stays "CODE COMPLETE — pending manual verification" until then.

## Environment facts (this machine)
- No `TELEGRAM_TEST_BOT_TOKEN` / `TELEGRAM_TEST_CHAT_ID` in the environment.
- `pip install -e .` blocked (PEP 668) — use `PYTHONPATH=src python3 -m pytest`.
- Toolchain: python3 + pytest + ruff. Commit identity: `editor-assistant <editor-assistant@chernomorie-bg.com>`.

## Verify current state in one minute
```bash
PYTHONPATH=src python3 -m pytest -q                        # expect: 95 passed
PYTHONPATH=src python3 -m editor_assistant.check_state     # RUN1 NEW → RUN2 UNCHANGED → RUN3 UPDATED
```

## The one open item: manual live send
```bash
export TELEGRAM_TEST_BOT_TOKEN=...   # from @BotFather
export TELEGRAM_TEST_CHAT_ID=...     # test chat/group id
PYTHONPATH=src python3 -m editor_assistant.send_telegram           # dry run first (no HTTP)
PYTHONPATH=src python3 -m editor_assistant.send_telegram --send    # sends 1 oldest PENDING row
PYTHONPATH=src python3 -m editor_assistant.send_telegram --send --limit 5
```
Then: flip the M1.4B status line in `MILESTONE.md` to DONE, commit, STOP for review.

## Pitfalls (learned the hard way)
- Fixture `rss_burgas_municipality.xml` has **2 items** — `pending_total` caps at 2 in proofs.
- `tests/test_outbox.py` passes `destination=TELEGRAM_TEST_DESTINATION` explicitly; the
  default `None` is state-only **by design** — don't "restore" implicit enqueueing.
- Smoke guard: the token `telegram` is allowed only in `notify/telegram.py` and
  `send_telegram.py`; everything else in `src/**` must stay free of it (and of
  `publish`/`wordpress`/`n8n`/`requests`/`httpx`).
- The store↔outbox import cycles are intentional (lazy imports) — see `agents.md`.
- Messages >4096 chars fail locally and stay PENDING — correct behavior, tested.
- `--send` without `DRY_RUN=false` stays dry; without credentials it exits 2 cleanly.

## Next smallest step
Complete the manual live send above (only if the human supplies credentials), update
`MILESTONE.md`, commit. Then STOP — any M2 scope (second source, scheduler, production
channel) requires explicit review and a new milestone definition; they are non-goals today.
