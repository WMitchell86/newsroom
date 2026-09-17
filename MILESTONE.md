## M2S-R2 Provider Stack + Live Search Benchmark — 2026-09-17 — LIVE-PROVEN, AWAITING EDITOR REVIEW

Verdicts: **SEARCH_EXECUTION_ENGINEERING = PROVEN** (live benchmark passed) · **TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING** (unchanged) ·
EDITORIAL_EFFECTIVENESS still **PENDING** (editor review unchanged; no profile/threshold/hook changes).

M2S-R2 changes (per editor-approved provider-stack plan; `ddgs` approved as the
repo's first non-stdlib dependency, positioned as fallback only):

- Capability-based provider stack replacing single-provider routing:
  NEWS → google_news_rss → serper → ddgs → brave; WEB → serper → ddgs → brave;
  BACKGROUND → wikipedia → serper → ddgs. Brave adapter kept, key-optional;
  Serper adapter implemented (2,500 free queries, no CC) and activates on key.
- New stdlib providers: GoogleNewsRSSProvider (best-effort discovery,
  DISCOVERY_ONLY redirects, 0 results ≠ news does not exist) and
  WikipediaBackgroundProvider (MediaWiki search API, background only).
- **Live benchmark executed for real, no key, no mocks**: 14 ops (7 known-answer
  + 7 unseen) — 7/7 known targets discovered (including the boxing story that
  stalled LIV-03, found via News RSS), 7/7 unseen returned candidates,
  42/42 pages FETCH_OK, 0 infra→semantic collapses. Latency: RSS ~0.5 s,
  Wikipedia ~0.4 s, DDGS ~2.7 s. Records: `var/search_benchmark/`.
- Live-found product bug fixed: `web_fetch` crashed on Cyrillic URLs
  (UnicodeEncodeError) — IRI→URI percent-encoding added with regression test.
- Full details: `m2/review/SEARCH_RELIABILITY_AUDIT.md` (Live benchmark section).

## M2S Search + Transcript Foundation — 2026-09-17 — BUILT + BATCH-VALIDATED (superseded in part by M2S-R2 above)

Verdicts at the time: SEARCH_EXECUTION_ENGINEERING = PROMISING (now PROVEN
per M2S-R2) · TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING ·
EDITORIAL_EFFECTIVENESS still **PENDING** (editor review unchanged; no profile/threshold/hook changes).

Track S (audit A): real SearchProvider contract + Brave adapter (stdlib only,
no scraping of consumer search HTML), explicit failure taxonomy
(SEARCH_CAPABILITY_UNAVAILABLE / PROVIDER_ERROR / RATE_LIMITED / NO_RESULTS /
QUERY_EXHAUSTED — infrastructure failure is never evidence of absence), bounded
429/Retry-After handling, generic SSRF-guarded page fetcher
(`sources/web_fetch.py`; frozen Radar fetcher untouched), semantic editor-request
constraints (SEARCH_INCOMPLETE instead of silent task change), gap-driven query
planning (1–3 queries), snippets stay DISCOVERY_ONLY, append-only search audit.
No API key in environment → live benchmark honestly not run; provider mocked-tested.

Track T (audit B): raw SRT is authoritative — deterministic parser with exact-ms
provenance, TranscriptDocument + trust levels (AUTO_CAPTION…OFFICIAL_VERBATIM),
time-aware overlap normalization (provenance binding preserved), AUTO_CAPTION
corroboration guard (decisions/numbers/names/quotes/negation need an official
source before publication-grade provenance; `validate_council_claims` refined
generically), generic topic segmentation + model-assisted fact extraction
(segment-id binding re-verified, unknown refs dropped) + angle discovery through
the unchanged rubric v2 gate (relaxed floor explicit via min_candidates — no
padding angles). Batch on all 7 bg-orig SRTs: 7/7 parsed, 48 grounded facts
(47 corroboration-flagged), zero hand-authored data. No articles generated.

Reports: `m2/review/SEARCH_RELIABILITY_AUDIT.md`,
`m2/review/TRANSCRIPT_DISCOVERY_BATCH_REPORT.md`; artifacts:
`var/transcript_analysis/*.json` + `MANUAL_AUDIT_SAMPLE.md` (internal audit,
not sent to editor). 339 tests, Ruff clean. STOP — awaiting editor review.

Verdict split (per editor feedback): **ENGINEERING = PROVEN** · **EDITORIAL_EFFECTIVENESS = PENDING**
(editor test on the real LIVE cases is the proof that remains).

Offline-proven: rubric v2 semantic viability gate (`new_proposition` mandatory, veto
overrides numeric eligibility), MODE-aware evidence sufficiency (bare announcement →
RESEARCH_MORE in every MODE; no BRIEF bypass), targeted research loop (max 2 rounds,
Good-Enough decisions enforced), reader-interest hook planner (§17 serious guard,
§18 supported-playful rule, grounded `basis_fact_ids`, clickbait guard), readiness
orchestrator gating `live-generate` (only DRAFT_READY drafts; force_draft recorded),
`live-readiness` CLI command. Editor assessment at finalize now records the M2R
verdict (`readiness_outcome` + note + structured `readiness_answers`:
would_publish / angle_right / headline_strong / opening_engaging; LIVE-only,
validated, aggregated in metrics for future learning) and the scorecard presents
alternative headline candidates (§20).

Operational phase (same day, on the real store): LIV-03 ran the research loop to
terminal state (2/2 rounds, search blocked in harness → EDITOR_DECISION_REQUIRED,
review artifact ready; fabricated Round-1 facts removed with `evidence_correction`,
no draft ever used them). LIV-02 migrated to rubric v2 through the real gate
(editor selection preserved; generic BG participle morphology fix in NOVELTY_CUE)
→ DRAFT_READY → regenerated with hook in prompt, FACTUAL_GATE_PASS, generation 3,
lineage preserved (deterministic draft-id caveat documented; append-only draft log
+ `generation` counter are authoritative). LIV-06 migrated with explicit vetoes →
NO_PUBLISHABLE_ANGLE kept, separate NO-STORY review artifact for the editor.
LIV01/04/05 DRAFT_READY, drafts untouched.

313 tests, Ruff clean. Report: `m2/review/EDITORIAL_READINESS_REPORT.md`.
Regression: `m2/review/M2R_LIVE_READINESS_REGRESSION.json`. Guidance:
`m2/review/editorial_readiness_guidance.json`. Editor artifacts:
`var/editorial_workflow/review/LIV-0{1,2,4,5}.md` (DRAFT_READY scorecards),
`LIV-03-DECISION.md`, `LIV-06-NOSTORY.md`. Frozen M2.1/2.2/2.3 systems untouched.
No LIVE 6–10; no profile/threshold changes (§34); STOP — awaiting editor review.


# MILESTONE — M1.5: Editorial Alert UX Calibration — DONE

## Status: **DONE (2026-09-12)** — editor visual confirmation accepted (`message_id=5` channel message reviewed normal/convenient); renderer frozen, no further UX polishing.

- **Step 1 (2026-09-12)** — preview 5 real alerts + audit, no code changes (`UX_AUDIT.md`, D1–D8)
- **Step 2** — deterministic editorial cleanup implemented (presentation-only, render-time)
- **Step 3** — source provenance + pagination integrity audit (verification-only, zero mutations)
- **Step 4** — headline/excerpt de-duplication implemented (presentation-only, deterministic)
- **Step 5** — one real Telegram TEST verification send (verification-only, `message_id=5`); **PASS WITH UX NOTES** (no code changes)

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
**M1.5 CLOSED.** Renderer is frozen — no UX polishing without a new scope decision.
**Next: M1.6 — Manual Poll Cycle** (fetch → parse/normalize → NEW/UPDATED/UNCHANGED →
atomic outbox → report; ingestion and delivery stay separated: poll → queue, then
separately review/dry-run → send; NO automatic Telegram sending in M1.6).


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
