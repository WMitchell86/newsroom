# MILESTONE — M1.4B: Telegram TEST-Channel Delivery (Manual)

## Status: DONE (verified LIVE 2026-09-12) — real message delivered to TEST chat

## Scope
`PENDING outbox row → render → stdlib urllib POST sendMessage (TEST chat) → mark_delivered`.
One destination only (`telegram-test`). No retries, no scheduler, no worker,
no production channel, no parse_mode (plain text).

## Gate checklist
- [x] transport: urllib POST `{chat_id, text}` only, explicit 15s timeout
- [x] success requires JSON `ok=true` AND `result.message_id` (int) — else TelegramSendError
- [x] all failures (HTTP/timeout/bad JSON/ok=false/missing message_id) → TelegramSendError; token never in message/logs/URL output
- [x] >4096 chars rejected locally before any HTTP; row stays PENDING
- [x] CLI `send_telegram.py`: dry-run DEFAULT (preview, zero HTTP, no state change)
- [x] real send needs `--send` AND `DRY_RUN=false` AND both env vars present (else clean exit 2)
- [x] limit default 1, hard max 5 (0/6+ rejected); oldest-first (outbox id) order
- [x] failure mid-run: row stays PENDING, run stops, nothing marked delivered
- [x] success: `delivered_at` written (at-least-once crash window documented in module docstring)
- [x] smoke guard updated: telegram delivery confined to `notify/telegram.py` + `send_telegram.py` (only excluded files)
- [x] 95 tests green, ruff clean, no runtime DB committed

## Manual live verification (requires human-supplied secrets — never commit)
```bash
export TELEGRAM_TEST_BOT_TOKEN=...   # from @BotFather
export TELEGRAM_TEST_CHAT_ID=...     # test chat/group id
PYTHONPATH=src python3 -m editor_assistant.send_telegram          # 1: dry run preview
PYTHONPATH=src python3 -m editor_assistant.send_telegram --send   # send 1 pending row
PYTHONPATH=src python3 -m editor_assistant.send_telegram --send --limit 5
```
Secrets live only in the environment (or uncommitted `.env`); `.gitignore` covers `.env` + `*.sqlite3`.

### Live verification evidence (2026-09-12)
- Live feed ingested: 20 items parsed, 20 NEW → 20 PENDING intents
- Real send: `status: SENT`, Telegram `message_id=4`, `delivered_at` written; 19 remain PENDING (limit=1)
- Gate re-check with real credentials present: `--send` without `DRY_RUN=false` stayed dry (no HTTP, no state change)

## STOP rule
**STOP AND WAIT FOR REVIEW** before any M2 scope (second source, scheduler, production channel).

---

# MILESTONE HISTORY — M1.4A: Durable Notification Outbox + Local Alert Rendering

## Status: DONE (verified 2026-09-12)

## Scope
`NEW/UPDATED → PENDING outbox row (same SQLite transaction) → local renderer`.
One destination id (`telegram-test`, no Telegram code/credentials/network).
No delivery, retries, workers, scheduling. M1.3 fingerprint/identity unchanged.

## Gate checklist
- [x] all previous tests green (77 passed: 20 outbox + 57 prior)
- [x] NEW→1 intent; UNCHANGED→none; UPDATED→new version intent; no duplicates
- [x] state + outbox atomic (outbox-fail rolls back state; state-fail adds no row)
- [x] payload snapshots render later (excerpt ≤500+…, links ordered, bg Unicode)
- [x] pending survives UNCHANGED runs; mark_delivered lifecycle works locally
- [x] renderer deterministic; NEW vs UPDATED visually distinct
- [x] no Telegram import/credential/network write; ruff clean
- [x] no runtime DB committed

## STOP rule
**STOP AND WAIT FOR REVIEW.** No Telegram delivery (M1.4B) without approval.

---

# MILESTONE HISTORY — M1.3: Local State + Identity + Version Detection

---

# MILESTONE HISTORY — M1.2.1: RSS Description Normalization

---

# MILESTONE HISTORY — M1.2: One Real Source, Read-Only

---

# MILESTONE HISTORY — M1.1: Source Contract + Fixture Only

## Status: DONE (verified 2026-09-12, commits fb84a57 + corrective 344dbf1)
One RSS 2.0 fixture → rss20 parser → SourceItem → local JSON. Corrective patch:
naive pubDate raises SourceParseError (no UTC/Sofia/local guess); timezone matrix tests.

---

# MILESTONE HISTORY — M0: Project Bootstrap + Safety Foundation

---

# MILESTONE HISTORY — M0: Project Bootstrap + Safety Foundation

## Status: DONE (verified 2026-09-12, commit c3c6634 on main)

## Scope (spec §15)
1. Minimal project/package structure ✅
2. `.gitignore` ✅
3. `.env.example` (no real credentials) ✅
4. Config loader (`AUTO_PUBLISH=false`, `DRY_RUN=true` hard defaults) ✅
5. Structured logging skeleton (stdlib JSON) ✅
6. Test runner + smoke/safety tests ✅
7. `BACKLOG.md` + milestone file ✅
8. `.ai/skills/` starter files (project-bootstrap, source-adapter, verification-gate) ✅
9. Verify: `pytest` green; `pip install -e .` blocked by PEP 668 externally-managed
   env — used `PYTHONPATH=src` instead.

## Gate checklist
- [x] Test runner starts, smoke test passes
- [x] Config loads without production credentials
- [x] AUTO_PUBLISH=false / DRY_RUN=true by default
- [x] No network calls in tests
- [x] No external write path
- [x] No secrets in repo
- [x] Structured local log works
