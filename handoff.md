## Handoff — M2R Editorial Readiness Layer (2026-09-17)

Verified: 310 offline tests, Ruff clean. New readiness layer gates drafting:
rubric v2 (`new_proposition` + semantic veto override numeric eligibility),
MODE-aware sufficiency (bare announcement never SUFFICIENT; BRIEF cannot bypass
research), research loop max 2 rounds, hook planner with §17 serious guard and
§18 playful-only-with-supported-premise, `live-readiness` CLI (rounds/mark-*/
override), `live-generate --force-draft --force-reason` (recorded). Editor
assessment at finalize: validated `readiness_outcome` + `readiness_note`
(LIVE-only, in the scorecard template, aggregated in `workflow_metrics` —
persisted for future learning, no auto-learning).
Fixtures A–F pass; LIVE regression read-only: LIV01/04/05 DRAFT_READY,
LIV03 RESEARCH_MORE, LIV-02 NEEDS_RESEARCH, LIV-06 NO_PUBLISHABLE_ANGLE.
Report: `m2/review/EDITORIAL_READINESS_REPORT.md`; regression JSON + guidance
JSON alongside. Prior pilot drafts untouched; committed; STOP for review.
Incident note: a stray `git checkout -- src/` reverted tracked M2.2 work in
`style/corpus.py` + `style/extract.py`; both were restored intact from a
dangling git checkpoint (`deb9653`) and the full suite verifies them.



# handoff.md — session-to-session state

Last updated: 2026-09-12 (M1.5 DONE — no renderer changes afterwards) · branch `main` · Suite: 135 passed, ruff clean
Read first: `agents.md` (how to work here) · `MILESTONE.md` (current gate, top section)

## Status
DONE (committed + verified live): M0 bootstrap · M1.1 RSS parser + fixture · M1.2 live read-only fetch ·
M1.2.1 HTML description normalization · M1.3 SQLite state + SHA-256 fingerprint ·
M1.4A durable outbox + renderer · M1.4B Step A (explicit intents) ·
**M1.4B Telegram TEST delivery — LIVE-VERIFIED 2026-09-12**: real feed ingested
(20 NEW → 20 PENDING), 1 real message delivered (Telegram `message_id=4`,
`delivered_at` written), dry-run gate confirmed still holding with real
credentials present.

IN PROGRESS: **M1.6 — Manual Poll Cycle (not started)** — next milestone as directed by the editor:
manual command (`fetch live RSS → parse + normalize → NEW / UPDATED / UNCHANGED →
atomic outbox → report: new / updated / unchanged / pending`), then STOP. Ingestion and
delivery stay separated: `poll → queue`, separately `review/dry-run → send`.
**NO automatic Telegram sending in M1.6**; goal is to run manual polling across days and
observe behavior on genuinely new material and on real edits of published documents.

DONE (committed + verified): **M1.5 Alert UX Calibration — CLOSED 2026-09-12.** Editor reviewed
`message_id=5` in the TEST chat as normal/convenient. New format delivered live
(`Общински съвет – Бургас` · source-derived subject headline · BG local date · no duplicate
excerpt · neutral compact attachments · separate source page · no main-document inference);
the 16-attachment case separately proven at render level (`3 + N още`). **Renderer is frozen**
— no UX polishing, D3 noise items (`Приложение N` tails) deferred without a new scope decision.
Earlier provenance proof stands: single declared source, identity collision-free,
0 duplicates / 0 orphans, no ingestion pagination (documented). Outbox state:
20 ingested items, **2 delivered** (`message_id=4`, `message_id=5`) + **18 PENDING**.

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
M1.6 — Manual Poll Cycle: define scope narrowly (single operator command combining fetch
→ parse → state → atomic outbox → operator report; no Telegram sends, no scheduler).
Do NOT start implementation until the editor issues the M1.6 scope note.
