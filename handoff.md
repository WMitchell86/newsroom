# handoff.md — session-to-session state

Last updated: 2026-09-12 (post live verification) · branch `main`, M1.4B complete (code `5c21268`) · Suite: 95 passed, ruff clean
Read first: `agents.md` (how to work here) · `MILESTONE.md` (current gate, top section)

## Status
DONE (committed + verified live): M0 bootstrap · M1.1 RSS parser + fixture · M1.2 live read-only fetch ·
M1.2.1 HTML description normalization · M1.3 SQLite state + SHA-256 fingerprint ·
M1.4A durable outbox + renderer · M1.4B Step A (explicit intents) ·
**M1.4B Telegram TEST delivery — LIVE-VERIFIED 2026-09-12**: real feed ingested
(20 NEW → 20 PENDING), 1 real message delivered (Telegram `message_id=4`,
`delivered_at` written), dry-run gate confirmed still holding with real
credentials present.

IN PROGRESS: **M1.5 Alert UX Calibration — step 1 done (audit only, no code changes).**
5 real pending alerts rendered locally (one per doc type), evidence + answers in
`UX_AUDIT.md`; **D1–D8 decisions awaited from the editor.** 19 rows still PENDING (untouched).

Roadmap (editor, 2026-09-12): M1.5 Alert UX → M1.6 manual polling command →
M1.7 scheduled polling. Scheduler only after the format is confirmed worth automating.

## Environment facts (this machine)
- `TELEGRAM_TEST_BOT_TOKEN` / `TELEGRAM_TEST_CHAT_ID` now hold **REAL secrets in the
  uncommitted `.env`** (git-ignored). Never `cat`/print/log them; never copy them into
  any other file. The CLI does not auto-load `.env` — source it:
  `set -a; . ./.env; set +a`, then add `DRY_RUN=false` only for real sends.
- `pip install -e .` blocked (PEP 668) — use `PYTHONPATH=src python3 -m pytest`.
- Toolchain: python3 + pytest + ruff. Commit identity: `editor-assistant <editor-assistant@chernomorie-bg.com>`.

## Verify current state in one minute
```bash
PYTHONPATH=src python3 -m pytest -q                        # expect: 95 passed
PYTHONPATH=src python3 -m editor_assistant.check_state     # RUN1 NEW → RUN2 UNCHANGED → RUN3 UPDATED
```

## Runtime data (var/, git-ignored)
`var/editor_assistant.sqlite3` holds live results: 20 ingested council items
(state NEW/UNCHANGED on rerun), outbox 1 sent + 19 PENDING (limit=1 on the
verification send — intentional). Future sends drain the 19 with
`--send --limit 5` runs.

## Sending more PENDING rows (routine)
```bash
set -a; . ./.env; set +a
PYTHONPATH=src python3 -m editor_assistant.send_telegram --db var/editor_assistant.sqlite3            # dry run first
env DRY_RUN=false PYTHONPATH=src python3 -m editor_assistant.send_telegram --db var/editor_assistant.sqlite3 --send --limit 5
```

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
Await the editor's D1–D8 answers in `UX_AUDIT.md`; then implement the approved
format changes as a narrow M1.5 milestone (render-time only, fingerprints untouched,
one-time comparison preview before/after). Do NOT start M1.6/M1.7 (polling/scheduler)
until M1.5 closes.
