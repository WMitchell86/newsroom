# MILESTONE — M1.5: Editorial Alert UX Calibration

## Status: IN PROGRESS — steps 1+2+3 done · awaiting editor review of the new format

- **Step 1 (2026-09-12)** — preview 5 real alerts + audit, no code changes (`UX_AUDIT.md`, D1–D8)
- **Step 2** — deterministic editorial cleanup implemented (presentation-only, render-time)
- **Step 3** — source provenance + pagination integrity audit (verification-only, zero mutations)

## Step 2 scope (implemented)
`notify/present.py` (deterministic, stdlib-only): display-name map, `относно:` subject
extraction with title fallback, boilerplate strip-list, clean→excerpt at 280 chars,
≤3 attachments + `+N още`, 🆕/🔄 markers, 🕒 BG local time (`Europe/Sofia`).
`render.py` builds the §11 editor-facing shape from immutable payload snapshots.
Store / fingerprint / outbox identity untouched (proven by tests + runtime audit).

## Step 3 — provenance + pagination audit (verification-only)
- Read-only DB audit (`sqlite3 mode=ro`): **19 PENDING rows, all `burgas-municipal-council`,
  all v1 NEW; `outbox.content_hash == item_state.content_hash` 19/19; 1 delivered
  (message_id=4)** — composition fully explained by ONE source: source A = 19, total = 19.
- **Single source, one pipeline**: `sources/live.py` `BURGAS_MUNICIPAL_COUNCIL` →
  single fetch of `last-update.xml` (RSS) → `process_items(destination="telegram-test")`.
  The earlier "Octopus vs Burgas" note was an error: `octopus` appears nowhere in the
  repo; exactly one source is declared. Nothing fixture/test-only entered the runtime DB.
- Identity `(source_id, item_url)` proven collision-free: same URL under two source_ids →
  two identities (`tests/test_state.py::test_same_url_two_sources_two_identities`);
  outbox UNIQUE `(destination, source_id, item_url, version_no)`; duplicate identity = 0,
  orphan outbox = 0, duplicate version intents = 0, cross-source URL overlap = none.
- **Pagination: none exists in ingestion** (one feed URL, no page/offset logic anywhere).
  Any "pagination" wording elsewhere referred to preview *display* pagination only.
  No speculative pagination code or tests were added (§5 documentation-only by design).

## Gate (steps 2+3)
- [x] 120 tests green (25 new present-proof tests incl. all 20 required; 3 stale format asserts updated)
- [x] BEFORE/AFTER previews, all 5 doc types: `var/ux_previews_before_after_2026-09-12.txt` (not sent)
- [x] 19-item audit: subject extracted 19/19, boilerplate removed 19/19, max excerpt 281,
      max rendered message 892 chars (<4096)
- [x] pending rows byte-identical (payload snapshots + delivered_at); no sends; no regeneration
- [x] fingerprints/state/outbox identity untouched (read-only mode=ro audit); ruff clean

## Known findings (recorded, NOT solved — §8)
- headline/excerpt duplication **11/19** (cleaned excerpt repeats display_subject verbatim)
- 3/19 subject lines >300 chars (max 343 — far under Telegram's 4096)
- Candidate future presentation rule (needs its own approval): if the cleaned excerpt
  substantially repeats display_subject, drop the repeated leading text and continue
  from the first new informative sentence.

## STOP rule
**STOP AND WAIT FOR EDITOR REVIEW** — no sends of the 19 pending rows, no scheduler, no
duplication fix until approved.


---

# MILESTONE HISTORY — M1.4B: Telegram TEST-Channel Delivery (Manual)

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
