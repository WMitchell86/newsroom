# handoff.md — session-to-session state

Last updated: 2026-09-12 (M1.5 steps 2–4 complete) · branch `main` · Suite: 135 passed, ruff clean
Read first: `agents.md` (how to work here) · `MILESTONE.md` (current gate, top section)

## Status
DONE (committed + verified live): M0 bootstrap · M1.1 RSS parser + fixture · M1.2 live read-only fetch ·
M1.2.1 HTML description normalization · M1.3 SQLite state + SHA-256 fingerprint ·
M1.4A durable outbox + renderer · M1.4B Step A (explicit intents) ·
**M1.4B Telegram TEST delivery — LIVE-VERIFIED 2026-09-12**: real feed ingested
(20 NEW → 20 PENDING), 1 real message delivered (Telegram `message_id=4`,
`delivered_at` written), dry-run gate confirmed still holding with real
credentials present.

IN PROGRESS: **M1.5 Alert UX Calibration — steps 1–4 done, awaiting editor review.**
Step 2 implemented the deterministic editorial cleanup (`notify/present.py` + `render.py`,
render-time only — fingerprints/state untouched). Step 3 proved integrity read-only
(`sqlite3 mode=ro`): the 19 PENDING rows come from the **single declared source**
`burgas-municipal-council` ("Octopus" was an error — no such source exists in the repo),
identity `(source_id, item_url)` collision-free, **0 duplicates / 0 orphans / 0 duplicate
version intents**, `outbox.content_hash == item_state.content_hash` 19/19; **no pagination
code exists in ingestion** — documented, none invented. **Step 4 (done)**: headline/excerpt
duplication **11/19 → 0/19** via `present.strip_leading_subject()` (anchored, deterministic,
normalized comparison for matching only); 14 new tests → **135 suite green**; samples in
`var/ux_previews_step4_2026-09-12.txt`. **Step 5 (done, 2026-09-12)**: one real TEST send of
outbox_id=2/node 3636 in the new format — Telegram `message_id=5`, `delivered_at` written,
pending 19→18, other 18 rows byte-identical (verified read-only); verdict **PASS WITH UX
NOTES** in `MILESTONE.md`. No code changes in Step 5.

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
PYTHONPATH=src python3 -m pytest -q                        # expect: 135 passed
PYTHONPATH=src python3 -m editor_assistant.check_state     # RUN1 NEW → RUN2 UNCHANGED → RUN3 UPDATED
```

## Runtime data (var/, git-ignored)
`var/editor_assistant.sqlite3` holds live results: 20 ingested council items,
outbox **2 delivered** (id 1 — M1.4B `message_id=4`; id 2 — M1.5 Step 5
`message_id=5`, new format) + **18 PENDING**. Future sends drain the 18 with
`--send --limit 5` runs (CLI picks oldest-first; no row selector exists by design).

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
- Payload stores `body_excerpt` (≤500 chars), **not** the full body — fingerprint
  recompute from an outbox snapshot alone is impossible (needs the raw fetch). Fine
  for rendering; matters if anyone plans payload surgery.
- Read-only DB audits: `sqlite3.connect('file:…?mode=ro', uri=True)` — no mutation possible.

## Next smallest step
Editor reviews the Step-4 result (previews `var/ux_previews_step4_2026-09-12.txt` +
`var/ux_previews_before_after_2026-09-12.txt`). Approved options, in order: (a) send a few
real alerts in the new format to the TEST channel; (b) the open D3 noise decision — strip
`Приложение N` tails from remainder starts (out of Step-4 scope). M1.6/M1.7
(polling/scheduler) stay blocked until M1.5 closes; no sends without approval.
