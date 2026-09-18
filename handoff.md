## Handoff — M2S-R3 TinyFish Adapters + V2 Shadow Judge + Enrichment (2026-09-18)

Verified: **393 offline tests, Ruff clean.** Verdicts:
SEARCH_EXECUTION_ENGINEERING = PROVEN (baseline re-confirmed live) ·
TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING (now also shadow-judged) ·
EDITORIAL_EFFECTIVENESS still PENDING. **No drafting, no LIVE 6–10, no
threshold/profile changes, no Monid, PROVIDER_ORDER unchanged** (harness Part H STOP).

Part A (TinyFish adapters in `workflow/search.py`, all offline-tested —
`tests/test_tinyfish_adapters.py`, 23): `TinyFishSearchProvider` +
`TinyFishFetchProvider` (stdlib urllib REST; 429→RATE_LIMITED w/ Retry-After,
402/403/outage→SEARCH_PROVIDER_ERROR never NO_RESULTS; locale/freshness/domain
mapping; `count_param_ignored=True` — API has page only), source taxonomy
(SOURCE_ACCESS_BLOCKED/FETCH_FAILED/PARSE_FAILED), privacy guard
(`guard_public_query` ≤400 chars + cue-clock/[музика]/субтитри markers;
`guard_public_url` = SSRF guard; fetch `purpose` guarded), `fetch_with_fallback`
(local first; narrow triggers; **blocked targets never forwarded**). TinyFish is
in `PROVIDER_CAPABILITIES` but NOT in `PROVIDER_ORDER` (A8); pin via
`SEARCH_PROVIDER=tinyfish` (no key → explicit `SEARCH_CAPABILITY_UNAVAILABLE`).

Part B (`tmp/tinyfish_benchmark.py` → `var/search_benchmark/tinyfish_eval.json`):
`TINYFISH_API_KEY` missing → TinyFish cells recorded capability-unavailable
(endpoint probes: both HTTP 401 without credentials — live, auth missing;
unavailable ≠ downtime ≠ zeros). Incumbent baseline re-proven live: 20 ops
(7 KNOWN + 7 UNSEEN + 6 HARD) → 17/20 SEARCH_COMPLETE, 6/7 known hits (chain
degraded on 4th same-day run; misses stay SEARCH_INCOMPLETE), avg 2.8 s;
fetch challenge 6/10 OK. Routing verdict: **NOT_JUSTIFIED**.

Part C (`tmp/shadow_judge_v2.py` →
`var/transcript_analysis_v2/shadow_judge_v2.json`): SHADOW-only model judge,
blind to the deterministic verdict, production `_model_assess` prompt verbatim,
all 24 V2 candidates: **17/24 full agreement (0.708)**, 7 disagreements
(4 model-more-permissive, 3 model-stricter; all on the routine-vs-concrete
boundary). Deterministic assessor stays authoritative; zero runtime changes.

Part D (`tmp/research_enrichment.py` →
`var/transcript_analysis_v2/research_enrichment.json`): the 2 RESEARCH_MORE
recordings enriched with gap-driven public-phrase queries (10/recording,
keyless chain) + ≤6 official-first fetches (9/9 opened); machine corroboration
candidates for 7/15 facts; `readiness.assess_readiness()` re-run with the
candidate verbatim and a gate-rebuilt assessment → **both stay RESEARCH_MORE
honestly** (lexical overlap is not publication-grade corroboration). No drafting.

Reports: `m2/review/TINYFISH_PROVIDER_EVALUATION.md`,
`m2/review/TRANSCRIPT_V2_SHADOW_JUDGE.md`,
`m2/review/TRANSCRIPT_RESEARCH_ENRICHMENT.md`.

Part B verdict, precise: **TINYFISH_INTEGRATION = READY ·
TINYFISH_EFFECTIVENESS = NOT_EVALUATED** (did not participate — HTTP 401
without credentials proves failure handling, not search quality) ·
**ROUTING_CHANGE = NOT_JUSTIFIED**.

Post-R3 state (editor-approved): search execution frozen/proven (TinyFish waits
only on a live-key benchmark re-run — no new development); transcript V2 =
PROMISING, no rubric/readiness changes; enrichment = PROMISING, the 2 unresolved
recordings stay honestly RESEARCH_MORE; editor pilot awaits human evaluation;
Monid = backlog; LIVE 6–10 = not yet. DDGS same-day degradation and the 6/10
generic fetch result remain observable via taxonomy — provider-health/cooldown
is backlog, not a redesign trigger.

Next smallest step (needs editor input): provide `TINYFISH_API_KEY` → re-run
`tmp/tinyfish_benchmark.py` to fill the TinyFish cells and revisit the routing
verdict with data. Then: focused read-only audit of the 7 shadow disagreements
(24 → 7 → which are genuinely contested vs a repeatable blind spot) plus the
enrichment candidates — no system changes. Otherwise: M2S-R3 is STOPPED; V2
sample review remains with the editor.

## Handoff — M2S-R2 Provider Stack + Live Search Benchmark (2026-09-17)

Verified: 355 offline tests, Ruff clean. Verdicts: SEARCH_EXECUTION_ENGINEERING =
**PROVEN** (live benchmark passed, no key needed) · TRANSCRIPT_DISCOVERY_ENGINEERING =
PROMISING · EDITORIAL_EFFECTIVENESS still PENDING (editor review unchanged;
editorial profiles/thresholds untouched).

M2S-R2 (editor-approved provider-stack plan): capability routing NEWS/WEB/
BACKGROUND over google_news_rss / serper / ddgs / wikipedia (+ brave optional).
`ddgs` approved as the repo's first non-stdlib dependency (user-site, pyproject
optional extra `search`; fallback role only). Serper adapter implemented,
activates on `SERPER_API_KEY` (free 2,500 queries, no CC). Live benchmark
(14 ops, keyless, zero mocks): 7/7 known-answer discovered (incl. the boxing
story that stalled LIV-03 — found via News RSS), 7/7 unseen with results,
42/42 pages FETCH_OK, taxonomy held everywhere; details + records in
`m2/review/SEARCH_RELIABILITY_AUDIT.md` + `var/search_benchmark/`. Live-found
bug fixed: Cyrillic URLs crashed `web_fetch` (IRI→URI encoding + regression
test).

Previous M2S foundation (still valid): Track S
(`workflow/search.py` provider contract + Brave adapter, failure taxonomy,
retry/Retry-After, constraints preservation, query planning, audit log;
`sources/web_fetch.py` SSRF-guarded fetcher; Radar fetcher frozen) and Track T
(`workflow/transcripts.py` SRT parser with ms provenance + trust levels +
overlap normalization + corroboration guard; `workflow/discovery.py` generic
topic segmentation + model-assisted fact/angle discovery through the unchanged
v2 gate with explicit relaxed floor). AUTO_CAPTION decision claims now need an
official corroborating source (`research.validate_council_claims` refined).
Batch on all 7 bg-orig SRTs: 7/7 parsed, 48 grounded facts, 47 corroboration-
flagged, zero hand-authored facts/angles, no articles generated. Artifacts:
`var/transcript_analysis/*.json` + `MANUAL_AUDIT_SAMPLE.md`. Reports:
`m2/review/SEARCH_RELIABILITY_AUDIT.md` (now incl. live benchmark + PROVEN) +
`m2/review/TRANSCRIPT_DISCOVERY_BATCH_REPORT.md` +
`m2/review/TRANSCRIPT_SEMANTIC_AUDIT.md`. STOP.

## Handoff — M2R Editorial Readiness Layer (2026-09-17)

Verified: 313 offline tests, Ruff clean. Verdict split per editor feedback:
**ENGINEERING = PROVEN · EDITORIAL_EFFECTIVENESS = PENDING** (editor test pending).
New readiness layer gates drafting: rubric v2 (`new_proposition` + semantic veto
override numeric eligibility), MODE-aware sufficiency (bare announcement never
SUFFICIENT; BRIEF cannot bypass research), research loop max 2 rounds, hook planner
with §17 serious guard and §18 playful-only-with-supported-premise, `live-readiness`
CLI (rounds/mark-*/override), `live-generate --force-draft --force-reason` (recorded).
Editor assessment at finalize: validated `readiness_outcome` + `readiness_note` +
structured `readiness_answers` (would_publish/angle_right/headline_strong/
opening_engaging; LIVE-only, scorecard asks all + shows alternative headlines,
aggregated in `workflow_metrics` — persisted for future learning, no auto-learning).

Operational pass (same day): LIV-03 research loop → terminal EDITOR_DECISION_REQUIRED
(2/2 rounds; search blocked in harness; fabricated Round-1 facts removed with
`evidence_correction`, no draft used them) → `review/LIV-03-DECISION.md`. LIV-02
migrated v1→v2 via the real gate (editor selection preserved; generic BG participle
morphology fix in NOVELTY_CUE: `приетa` never matched `\bприет\b`) → DRAFT_READY →
regenerated (FACTUAL_GATE_PASS, hook in prompt, generation 3, superseded archive;
lineage caveat: deterministic draft IDs mean `superseded_draft_id` cannot
disambiguate — append-only `live_drafts.jsonl` + case `generation` are authoritative).
LIV-06 migrated with explicit vetoes → NO_PUBLISHABLE_ANGLE kept → separate
`review/LIV-06-NOSTORY.md` asking the editor to verify the refusal. LIV01/04/05
DRAFT_READY read-only, drafts untouched. Current editor-facing state:
4 DRAFT_READY scorecards + 2 special artifacts, all in `var/editorial_workflow/review/`.
Report: `m2/review/EDITORIAL_READINESS_REPORT.md`; regression JSON + guidance JSON
alongside. No LIVE 6–10; no profile/threshold changes (§34); STOP for editor test.
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
