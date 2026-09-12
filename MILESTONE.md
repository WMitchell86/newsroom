# MILESTONE — M1.5: Editorial Alert UX Calibration

## Status: IN PROGRESS — steps 1–5 done · awaiting editor review (Step 5 = 1 live send)

- **Step 1 (2026-09-12)** — preview 5 real alerts + audit, no code changes (`UX_AUDIT.md`, D1–D8)
- **Step 2** — deterministic editorial cleanup implemented (presentation-only, render-time)
- **Step 3** — source provenance + pagination integrity audit (verification-only, zero mutations)
- **Step 4** — headline/excerpt de-duplication implemented (presentation-only, deterministic)
- **Step 5** — one real Telegram TEST verification send (verification-only, 1 message sent)

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

## Step 4 — headline / excerpt de-duplication (implemented)
`present.strip_leading_subject()` removes a *strong, deterministic LEADING* duplication only:
(A) the excerpt begins with `display_subject`, or (B) an administrative prefix ends at an
`относно:` marker (within the first 200 chars) immediately followed by the subject.
Comparison normalization (case/whitespace) exists for MATCHING ONLY — the displayed remainder
keeps the original spelling; nothing is ever removed mid-body (§5), no fuzzy/semantic matching
(§4), empty remainder → excerpt omitted, never repeated (§6). The 280-char limit applies AFTER
de-duplication (§7). Renderer passes the extracted subject through.

Real 19-item audit: duplicate_before **11** → duplicate_after **0**; 12 excerpts removed
entirely (their 500-char snapshots ended at the subject — nothing informative lost), 7 remain;
max excerpt 108 chars; max rendered message 615 chars (<4096).

## Step 5 — one real Telegram UX verification (2026-09-12)
- Dry run first (real CLI path, default gate): rendered outbox_id=2 / node 3636,
  all §2 checks pass (human source label, extracted subject headline, BG local
  date `11.09.2026, 16:23`, deduplicated excerpt OMITTED — no boilerplate, 2
  attachments, source URL, plain text, message 615 chars).
- Real send (existing M1.4B gates: `--send` + `DRY_RUN=false`, limit=1):
  **status SENT · Telegram `message_id=5` · remaining_pending 18.**
- State verified read-only: id=2 `delivered_at=2026-09-12T18:08:45.296916+00:00`;
  pending 19 → 18; the 18 remaining rows byte-identical (payload sha256 +
  delivered_at NULL compared against a pre-send snapshot).
- Selection caveat: the CLI has no row-selection flag (oldest-first by
  `ORDER BY id` only). The 16-attachment candidate (node 3631, outbox id 7)
  was therefore verified at RENDER level only (first 3 links + `+13 още`,
  no "main" labeling) and NOT live-sent — adding a selector would be a
  feature change, out of scope for a verification-only milestone.
- Verdict: **PASS WITH UX NOTES** — the sent message rendering is clean and
  complete; notes: (a) excerpt omitted by design when the 500-char snapshot
  ends at the subject (12/19 items) — editor to confirm acceptable; (b) the
  high-attachment layout is renderer-verified, not chat-verified; (c) final
  visual confirmation is the editor's eyeball in the TEST chat.

## Gate (steps 2+3+4+5)
- [x] 135 tests green (14 new Step-4 proofs incl. §9 1–14; 39 present tests; 120 prior green)
- [x] BEFORE/AFTER previews: `var/ux_previews_before_after_2026-09-12.txt` (steps 2) +
      `var/ux_previews_step4_2026-09-12.txt` (5 representative examples; not sent)
- [x] Step-4 metrics: duplicate 11→0; excerpt 12 fully removed / 7 present; max 108/615
- [x] false-positive review: for every removed excerpt the removed region = prefix +
      `относно:` + subject (tail after subject was only punctuation/whitespace, verified
      for all 12) — no informative content was swallowed
- [x] pending rows byte-identical, 19 PENDING; no sends; no regeneration; fingerprints/
      state/outbox identity untouched (tests + read-only audit); ruff clean
- [x] Step 5: 1 real TEST message sent (message_id=5), pending 19→18, other 18 rows
      byte-identical (verified read-only), no code changes, docs only

## Known findings after step 4
- headline/excerpt duplication **11/19 → SOLVED (0/19)** by step 4.
- Remaining item-noise visible in step-4 previews: `Приложение N` appendix labels at the
  start of some remainders (e.g. node 3631) — this is the open D3 noise-strip decision,
  NOT in step-4 scope (deduplication only). Also noted: 3/19 registry subjects are 300+ chars.
- Known limitation: payload snapshots keep only a 500-char `body_excerpt`, so when the
  subject ends at the snapshot edge there is no further informative text to show — the
  excerpt is then omitted entirely (12/19) rather than repeated.

## STOP rule
**STOP AND WAIT FOR EDITOR REVIEW** — no sends of the 19 pending rows, no scheduler,
no `Приложение N`/noise changes until approved.


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
