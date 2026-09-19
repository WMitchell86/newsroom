## M3B YouTube URL Intake + Real-World Jev Shadow — 2026-09-19 — BUILT, REAL-RUN, AWAITING REVIEW

One YouTube URL becomes a real intake: canonical identity → raw timestamped SRT
→ discovery V2 → readiness, with optional Jev shadow. No drafting, no
scheduling, no publishing.

```text
YOUTUBE_INTAKE_ENGINEERING          = PROVEN
TRANSCRIBER_INTEGRATION             = PROVEN
REAL_TRANSCRIPT_DISCOVERY           = PROMISING   (unseen recordings pending)
JEV_REAL_WORLD_SHADOW_COLLECTION    = ACTIVE
JEV_PRODUCTION_AUTHORITY            = NONE
EDITORIAL_EFFECTIVENESS             = PENDING
```

- No in-repo transcriber existed; `workflow/transcriber.py` is a thin adapter
  over the available `yt-dlp` (auto-subs → SRT), with an explicit failure
  taxonomy and raw SRT kept authoritative (`AUTO_CAPTION`).
- `workflow/youtube.py` (canonical identity, no invented metadata),
  `workflow/intake_store.py` (content-addressed transcripts + atomic registry
  with version history), `workflow/intake.py` (staged orchestrator; distinct
  outcomes; no-story is valid), `workflow/jev_shadow.py` (shared specs +
  semantic-rescue collection). CLI: `youtube-intake`. Workbench displays
  completed intakes at `/intake` (initiation CLI-only; no job queue).
- Real run on known `YsqD4T0D850`: 184 segments, 12 topics, 10–11 facts,
  readiness RESEARCH_MORE; 17 grounding + 3 angle Jev shadow cases; **7
  semantic-rescue candidates** collected. Unseen-recording validation pending.
- Tests 512 → **553 passed**, ruff clean, M3A smoke 25/25. No rubric, threshold,
  routing or discovery semantic change; Jev has no authority.

Report: `m3/review/M3B_YOUTUBE_INTAKE_REPORT.md`. **STOP** — no M3C, no
monitoring/scheduler, no drafting, no CMS, no Jev authority, no LIVE 6–10.

## M3A Stabilization + M3J Jev Shadow Evaluation — 2026-09-19 — BUILT, OFFLINE-TESTED, AWAITING REVIEW

Reliability + evaluation-only milestone. No editorial logic, rubric, routing,
drafting or publishing changed.

Verdicts:

```text
M3A_STABILIZATION         = PROVEN
JEV_INTEGRATION           = PROVEN
JEV_GROUNDING             = PROMISING_STRONG
JEV_ANGLE_SEMANTICS       = PROMISING
JEV_CORROBORATION         = NOT_SUITABLE_AS_STANDALONE_VERIFIER
JEV_PRODUCTION_AUTHORITY  = NONE
EDITORIAL_EFFECTIVENESS   = PENDING
```

M3J is frozen. `JEV_INTEGRATION = PROVEN` means the integration, not the model
for production.

Part A (stabilization): hermetic offline tests — `tests/conftest.py` installs an
in-test DNS resolver so `web_fetch.guard_target()` never touches real DNS while
the SSRF guard itself is unchanged (suite now passes with DNS forced to fail);
one canonical live-evidence store `workflow/live_store.py` (atomic,
deterministic, same schema) now used by both the CLI and the Workbench;
root-level `CURRENT_STATE.md` added as the authoritative state doc with
`agents.md` read order updated; `tmp/m3a_smoke.py` promoted to tracked
`scripts/m3a_smoke.py` (25/25, live store byte-identical). M3A files not
style-refactored.

Part B–J (M3J, shadow only): optional `typesafe-sdk` extra + thin adapter
`workflow/jev.py` (typed questions, probability/confidence preservation,
explicit `JEV_CAPABILITY_UNAVAILABLE` / `JEV_PROVIDER_ERROR` with key redaction,
zero editorial authority); frozen public-source fixtures under
`fixtures/evals/jev/` (24 angles incl. the 7 disagreements, 109 fact-grounding
rows retained+dropped, 16 corroboration candidates with honest manual labels);
resumable runner `scripts/evals/jev_shadow_eval.py` writing to ignored
`var/jev_eval/`; +31 offline tests.

Live run (TypeSafe SDK 0.6.0, effective `jev-1.13.0`, 149/149 calls OK, avg
~650 ms): **grounding = PROMISING_STRONG** (Jev corrects deterministic lexical
false negatives on number morphology/abbreviated years/decision-status; 87/93
retained agree), **angle semantics = PROMISING** (`development_type` matches the
audit hypothesis on 6/7 known disagreements — the CONCRETE_ACTION vs
ROUTINE_PROCESS boundary), **corroboration = NOT_SUITABLE_AS_STANDALONE_VERIFIER**
(3/4 hard negatives still called support; head-of-page fixture passage replaced
with a relevance window and the run redone). Manual label audit of
`xvsdi_j7s5c-f007` and `concessions_funding` flipped both in Jev's favour — the
deterministic gate is a baseline, not ground truth. No Jev authority; no thresholds.

Tests: 481 → **512 passed** (offline, DNS-unavailable-safe). Reports:
`m3/review/M3A_STABILIZATION_REPORT.md`, `m3/review/M3J_JEV_SHADOW_EVALUATION.md`.
**STOP** — awaiting review; no M3B/M3C/CMS/LIVE 6–10/rule changes.

## M3A Editor Workbench MVP — 2026-09-18 — BUILT, TESTED, AWAITING REVIEW

Product/UX milestone (not another AI-quality milestone): a minimal **Editor
Workbench** so the editor can review and finalize articles in a browser instead
of editing Markdown files.

Verdict:

```text
EDITOR_WORKBENCH_ENGINEERING        = PROVEN (offline tests + scripted smoke)
EDITOR_WORKBENCH_EDITORIAL_EFFECTIVENESS = PENDING (no real editor has used it)
EDITORIAL_EFFECTIVENESS             = PENDING (unchanged)
```

Architecture: a thin service layer (`workflow/workbench/`) over the **unchanged**
frozen contracts. Every canonical write goes through the validated functions the
CLI already uses (`cases.record_editor_final` + `save_cases`;
`readiness.apply_editor_override` for decisions); the UI reimplements no
ewsworthiness, factual gate, readiness or case state. Stdlib `http.server` +
hand-rolled escaped HTML — no framework, no build chain, no JS required.

- One command: `PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench`
  (or `python3 -m editor_assistant.workflow.workbench`); `--host` defaults to
  **127.0.0.1** and is opt-in with a warning (no auth on this local MVP).
- Pages: queue (`/`, filters Всички · За редакция · Нужна информация · Нужно
  решение · Без достатъчна новина · Финализирани), case detail (`/case/{id}`)
  with four surfaces (immutable draft / sources / status+warnings / editor
  workspace), and POST `save` · `finalize` · `decision`. Bulgarian-first: every
  stored enum id stays visible next to its Bulgarian label.
- Non-authoritative editor working copy in
  `var/editorial_workflow/editor_working/{CASE}.json` (atomic writes,
  `base_draft_id` staleness binding). **Save ≠ Finalize** (separate endpoints;
  save can never finalize, publish, change readiness or mutate the AI draft).
  Stale finalization → HTTP 409 with the Bulgarian „по-нова AI версия“ banner,
  and the workspace offers the explicit **„Приемам новата AI версия за основа“**
  re-base so staleness is never a dead end (no silent re-base, no locking).
- Special no-draft cases are rendered generically from stored readiness status
  (never hardcoded ids), including the evidence-only `NO_PUBLISHABLE_ANGLE` lead
  (`LIV-06-EVIDENCE`, no case row): no article editor, decision-only recording.
- Append-only minimal audit: `var/editorial_workflow/workbench_actions.jsonl`.
- Tests: `tests/test_workbench.py` (+74; suite 394 → **468 passed**), offline,
  env-isolated, plus a real localhost HTTP server on an ephemeral port. Ruff
  check + format clean on the new files. Scripted smoke `tmp/m3a_smoke.py`:
  **25/25**, run against a copy of the store; the live store stays byte-identical.
- Bugs found and fixed while finishing (all in the new surface): dead case
  routing (`/case/{id}` returned 404 for everything), queue-filter 500, redirects
  losing `Location`, an unsubmittable finalize form (missing required
  `editor_outcome`/`editing_weight`), a working-copy answer-prefix mismatch,
  `prefer_ai_start` leaking into `readiness_answers`, invisible evidence-only
  special cases, and a missing `threading` import.
- Adversarial review pass on the finished surface fixed eight more: a **stale
  guard bypass reachable through the UI** (only the submitted `base_draft_id`
  was compared), a re-base action that existed in the service layer but had no
  caller (permanently blocked finalization), a corrupt working copy that 500'd
  every page for its case, a recorded „не публикувай“ decision bouncing the case
  back into «За редакция», empty-body finalization, a finalized case still
  offering an editor workspace, the half-built §16/§17 rendering (raw
  `seg1@t=08:42.250` locators, unused `TRUST_LABELS`), and a queue bucket that
  contradicted the surfaces its case page offered.

Report: `m3/review/M3A_EDITOR_WORKBENCH_REPORT.md`. Pre-implementation plan:
`m3/review/M3A_PLAN.md`. **STOP** — no M3B YouTube adapter, no M3C automatic
enrichment, no LIVE 6–10, no CMS publishing, no editorial-rule changes.

## M2S-R4 TinyFish Search ADOPTED — Routing Implemented — 2026-09-18 — EDITOR DECISION ON MEASURED DATA

Editor routing decision on the M2S-R3b keyed benchmark; implemented and
frozen. Verdict state:

```text
SEARCH_EXECUTION_ENGINEERING      = PROVEN
TINYFISH_SEARCH                   = ADOPTED (first general WEB provider)
TINYFISH_FETCH                    = AVAILABLE / NOT_YET_PROVEN (not a default fetch fallback)
TRANSCRIPT_DISCOVERY_ENGINEERING  = PROMISING+ (frozen until editor sample review)
TRANSCRIPT_RESEARCH_ENRICHMENT    = PROMISING (frozen)
EDITORIAL_EFFECTIVENESS           = PENDING (human editor is the arbiter)
```

Implemented (offline-tested, `search.py` + `tests/test_tinyfish_adapters.py`):

- `PROVIDER_ORDER` (M2S-R4): NEWS -> google_news_rss -> tinyfish -> serper ->
  ddgs -> brave; WEB -> tinyfish -> serper -> ddgs -> brave; BACKGROUND ->
  wikipedia -> tinyfish -> serper -> ddgs. Rationale: TinyFish won every
  measured search cell (20/20 SEARCH_OK, 7/7 known-answer, avg 0.3 s vs
  3.2 s; DDGS showed repeated same-day degradation). RSS keeps the NEWS lead
  as the keyless specialist layer for Bulgarian media, wikipedia keeps
  BACKGROUND; serper/brave stay key-gated members (run only with keys).
- `provider_chain`: tinyfish is default-routed; a missing `TINYFISH_API_KEY`
  degrades the chain explicitly (`tinyfish:no-key`), never fabricating
  results. The `SEARCH_PROVIDER=tinyfish` pin is unchanged. TinyFish FETCH
  deliberately NOT promoted — no added value on the 2 live fallback cases
  (0/2 opened, `page_not_found` both); the adapter stays behind
  `fetch_with_fallback`'s narrow failure-category trigger.
- Tests: the registered-not-default test was replaced by adoption assertions
  + a keyless-degradation test (23 -> 24 TinyFish tests).
- `.gitignore`: `media.zip` ignored specifically (not `*.zip`, so future
  legitimate ZIP fixtures stay trackable) — unknown local upload in root,
  not part of build/runtime; file itself left on disk, untracked.

Frozen (editor instruction): no `CONCRETE_ACTION_NEEDS_RESEARCH` vs
`ROUTINE_REPORT_VETO` semantic change until the V2 editor sample review
arrives; no thresholds; no drafting; no LIVE 6–10; no Monid.


## M2S-R3 TinyFish Adapters + V2 Shadow Judge + Research Enrichment — 2026-09-18 — MEASURED WITH KEY, AWAITING EDITOR

Verdicts: SEARCH_EXECUTION_ENGINEERING = **PROVEN (baseline re-confirmed)** ·
TRANSCRIPT_DISCOVERY_ENGINEERING = **PROMISING (differentiated, now shadow-judged)** ·
EDITORIAL_EFFECTIVENESS still **PENDING** (no drafting, no editor contact, no
profile/threshold/routing changes).

M2S-R3 (provider-evaluation harness; `TINYFISH_API_KEY` not in environment —
live TinyFish cells recorded as explicit capability-unavailable):

- **Part A — TinyFish adapters landed in `workflow/search.py`** (stdlib urllib
  direct REST, no Monid in the runtime path): `TinyFishSearchProvider`
  (429→`RATE_LIMITED` w/ Retry-After backoff, 402/403/outage→
  `SEARCH_PROVIDER_ERROR` never `NO_RESULTS`; `country→location`,
  `search_language→language`, `freshness→recency_minutes`,
  `domain_types→domain_type`; no `count` param → client-side truncation +
  `count_param_ignored=True` recorded) and `TinyFishFetchProvider` (batch ≤10
  URLs, per-URL failure categories, returns the local opened-source record
  shape). Source taxonomy (`SOURCE_ACCESS_BLOCKED/FETCH_FAILED/PARSE_FAILED`),
  privacy guard A6 (`guard_public_query`: ≤400 chars + cue clocks/[музика]/
  субтитри markers; `guard_public_url` reuses the SSRF guard; fetch `purpose`
  guarded), `fetch_with_fallback` (local first; TinyFish only on
  HTTP-error/parse/timeout/unreachable or <200-char extractions; a
  `FETCH_BLOCKED_TARGET` is **never forwarded**). Registered in
  `PROVIDER_CAPABILITIES` but deliberately **not** in `PROVIDER_ORDER`
  (harness A8): reachable via `SEARCH_PROVIDER=tinyfish`, missing key →
  explicit `SEARCH_CAPABILITY_UNAVAILABLE`.
- **Part B — provider benchmark** (`tmp/tinyfish_benchmark.py` →
  `var/search_benchmark/tinyfish_eval.json`): 20 live incumbent-chain ops
  (7 known-answer + 7 unseen from R2 + 6 harder BG queries) + 10-URL fetch
  challenge, TinyFish cells recorded unavailable with endpoint probes as
  evidence (search 401 / fetch 401 without credentials). Baseline: 17/20
  `SEARCH_COMPLETE`, 6/7 known-answer hits (chain degraded by 4th same-day
  run; misses recorded `SEARCH_INCOMPLETE`, never collapsed), latency avg
  2.8 s; fetch 6/10 OK. Routing verdict: **NOT_JUSTIFIED** — PROVIDER_ORDER
  unchanged pending a keyed TinyFish run. Superseded same-day by Part B′
  (keyed re-run below).
- **Part C — shadow model judge over all 24 Transcript V2 candidates**
  (`tmp/shadow_judge_v2.py` → `var/transcript_analysis_v2/shadow_judge_v2.json`):
  judge blind to the deterministic verdict, production `_model_assess` prompt
  verbatim, 24/24 judged: **17/24 full agreement (0.708)**, 0 pair, veto
  17/24, 0 unavailable; 7 disagreements cluster on the routine-vs-concrete
  boundary and cut both ways (4 model-more-permissive, 3 model-stricter).
  Deterministic assessor stays authoritative; no runtime status changed.
- **Part D — gap-driven enrichment for the 2 RESEARCH_MORE recordings**
  (`tmp/research_enrichment.py` → `var/transcript_analysis_v2/research_enrichment.json`):
  5 public-phrase queries × 2 capabilities per recording (privacy guard on the
  outbound surface), ≤6 official-first fetch targets, 9/9 pages opened,
  machine corroboration *candidates* recorded for 7/15 facts (4/9 CIs4AIKuOiw,
  3/6 YsqD4T0D850); readiness re-run via the real orchestrator (candidate
  verbatim, gate-rebuilt assessment) → **both honestly stay RESEARCH_MORE**.
  No drafting.

- **Part B′ — keyed re-run, same day** (`TINYFISH_API_KEY` provided; the
  editor's `TINY_FISH_APY_KEY` was renamed to the correct variable; the
  benchmark now measures TinyFish live on the same cells): TinyFish search
  **20/20 `SEARCH_OK`, 7/7 known-answer hits, latency avg 0.3 s / max 0.9 s**
  vs the chain in the same run: 18/20 complete, 6/7 known hits, avg 3.2 s
  (DDGS degraded on its 5th same-day run; both misses honest
  `SEARCH_INCOMPLETE`). TinyFish found the needle the degraded chain dropped
  (`Община Бургас бюджет 2026`). Fetch: fallback exercised only on the 2
  local `FETCH_HTTP_ERROR` cells (narrow triggers held, blocked targets never
  forwarded); TinyFish fetch also failed both (`page_not_found` → honest
  `SOURCE_FETCH_FAILED`), 0/2 opened; local opener alone 6/10. Verdicts:
  `TINYFISH_INTEGRATION = READY · TINYFISH_EFFECTIVENESS = MEASURED (favored
  on search) · ROUTING_CHANGE = DEFERRED` — still no `PROVIDER_ORDER` change;
  routing is an editor decision with this evidence.
- **Focused audit** (`m2/review/SHADOW_DISAGREEMENT_ENRICHMENT_AUDIT.md`,
  read-only, checkpoint 55b4f5f): no rubric redesign justified; two semantic
  hypotheses — a concrete-but-incomplete action deserves `NEEDS_RESEARCH`
  (social aid, school funding, museum refusal) and routine-report/presence
  candidates should be vetoed (mid-year budget reports, meeting attendance) —
  await editor calibration before any narrow `CONCRETE_ACTION_NEEDS_RESEARCH`
  vs `ROUTINE_REPORT_VETO` correction. Enrichment candidates re-read
  manually: source leads, not confirmations (f002 attendance = lexical false
  positive). Verdict: TRANSCRIPT_DISCOVERY_ENGINEERING = **PROMISING+**;
  enrichment = PROMISING (lexical matcher = source locator, not a
  corroboration engine).

Reports: `m2/review/TINYFISH_PROVIDER_EVALUATION.md`,
`m2/review/TRANSCRIPT_V2_SHADOW_JUDGE.md`,
`m2/review/TRANSCRIPT_RESEARCH_ENRICHMENT.md`,
`m2/review/SHADOW_DISAGREEMENT_ENRICHMENT_AUDIT.md`.
393 tests, Ruff clean. STOP (harness Part H) — awaiting editor: the V2 sample
review and the routing decision (TinyFish cells now measured — Part B′).

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
