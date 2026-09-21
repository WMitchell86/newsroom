## Handoff — M4B.1 Feed Stabilization + M4C Story Identity (2026-09-21)

Verified: **859 offline tests**, ruff check/format clean, M3A smoke 25/25, a real
isolated collection with two immediate runs, a real deterministic story build and a
capped semantic probe. Reports: `m4/review/M4B1_FEED_STABILIZATION_REPORT.md`,
`m4/review/M4C_STORY_IDENTITY_REPORT.md`, `m4/review/M4C_STORY_REVIEW_PACK.md`.

- **What the editor can now do:** open **«Истории»** and see real stories instead of
  ~120 raw rows — each with «Нова история» / «Ново развитие», `издатели` /
  `публикации` / `откривания` counted separately, the publisher list and a one-line
  summary; open a story and see the chronology, the unique publications grouped by
  publisher and the discovery provenance; correct a bad grouping with
  **«Този материал не е част от историята»** (split) or **«Обедини с друга скорошна
  история»** (merge) without touching JSON or ids. **«Материали»** still lists every
  original collected row.
- **What cron can now do:** `newsroom refresh` = `collect` → assign new material to
  stories → one summary (`източници / нови материали / нови истории / нови развития /
  добавени към съществуващи / за преглед / грешки`). A story failure never rolls back a
  successful collection. `newsroom collect` is unchanged; the repo still installs no
  timer and runs no daemon.
- **Real proof (isolated, 2026-09-21):** run 1 → 91 items; immediate run 2 → 32
  genuinely new items, 91 known, **0 rows older than 72 h** (the old `+100 new`
  second-run backfill is gone). Corpus 123 rows → **113 unique publications**, 10
  duplicate discovery rows collapsed, 1 deterministic cross-publisher merge, 112
  stories in a deterministic-only build. Semantic probe (capped, free OpenRouter arm):
  10 answers, all `DIFFERENT_STORY`, 0 merges — failure degrades to a separate story
  with `за преглед`, never to a merge.
- **New stores:** `var/newsroom/stories.json` (atomic, strict schema, `overrides`
  audit). Env: `NEWSROOM_STORIES_PATH`. The inbox store is untouched by M4C.
- **New module map:** `workflow/publication_identity.py` (URL normalization, Google
  News token identity), `workflow/story_store.py` (schema/lifecycle/overrides),
  `workflow/story_identity.py` (retrieval, matching, update/analyze/rebuild, views),
  `workflow/story_relation.py` (the one semantic step), Workbench story pages,
  `role="story"` in `drafting/generate.py`.
- **Structural guards:** the six source/collection modules stay AI/story-free; the M4C
  modules are a new explicit allow-list and still may not reach drafting, publishing,
  Telegram, transcripts or a generic agent.
- **Open after review (deliberately not done here):** semantic call budget for a large
  ambiguous shortlist (102 items in one real corpus), Bulgarian morphology for the
  deterministic match (currently conservative because of it), and the pre-existing
  OpenRouter default-model id defect that makes any OpenRouter-only call return HTTP
  400 for **every** role (workaround: set `OPENROUTER_STORY_MODEL` / `OPENROUTER_MODEL`).
- **Next milestone is M4D (Telegram editorial alerts)** — only after this review; no
  automatic continuation was taken.

## Handoff — M4A.1 Default Source Pack + M4B Daily Inbox (2026-09-20)

Verified: **805 offline tests**, ruff check/format clean, M3A smoke 25/25, plus an
isolated live source-pack run and Workbench proof. Reports:
`m4/review/M4A1_DEFAULT_SOURCE_PACK_REPORT.md`, `m4/review/M4B_DAILY_INBOX_REPORT.md`.

- **What the editor can now do:** open `/sources` and see ~30 watched sources with a
  health column («Последно успешно · Последен резултат · Нови материали»), the real
  next collection, and a compact «Забранени домейни» policy; open `/inbox` and land on
  **NEW** with summary counts, filters, pagination, per-item actions, «Събери новите
  сега» and a readable source-problem list.
- **What cron can now do:** `newsroom collect` collects 30 sources with real cadence
  (daily sources once per Sofia day), a safe first-run bootstrap, per-source caps and
  bound failures; schedule documented in `RUNBOOK.md` §0e. The repo installs no timer.
- **Live proof:** isolated run → 29 OK / 1 EMPTY / 0 failed, 204 items; re-run → 100 new
  + 80 known, 21 cadence-skipped; `/sources` and `/inbox` render; a blocked publisher
  filtered live (20+46 items); a direct blocked source refused.
- **Real bug found while proving the policy:** Google News item links are opaque
  `news.google.com` redirects, so host-matching item URLs blocks nothing. The publisher
  domain now comes from the item's `<source url>` attribute (provider + runner updated,
  with a fixture test).
- **Second correction before freeze (reviewer-flagged): publisher authority is no
  longer inherited from the monitoring definition.** Each source declares its real
  publisher `domain`; each item stores `publisher_domain` / `publisher_kind` /
  `factual_authority` from the **publisher**, unknown publishers fail closed, and the
  inbox shows/discovery-filters both identities separately. Live: a prosecution-query
  item published by `news.bg` or Facebook carries no authority; the one published by
  БТА keeps media authority. `PUBLISHER_AUTHORITY_INHERITANCE = PROVEN`.
- **Boundary held:** no AI ranking, no story clustering, no `NEW_DEVELOPMENT`, no
  Telegram, no drafting — a structural test fails if those tokens appear as identifiers
  in the newsroom modules.
- **Next:** freeze M4A.1 + M4B, then **M4C** (story identity / new development) — the
  first new semantic capability, and only now that the registry and inbox exist.

## Handoff — M4A Source Registry + Scheduled Collection (2026-09-20)

Verified: **737 offline tests**, ruff check/format clean, M3A smoke 25/25, plus a
live end-to-end collection. Plan + proof: `m4/review/M4A_PLAN.md`.

- **What the editor can now do:** open the Workbench → «Източници», see the table
  (Източник · Тип · Статус · Приоритет · Следващо събиране) and add / edit /
  enable / disable / mute-to-date / re-prioritise / monitoring-only /
  factual-authority. Nothing else changed for them yet.
- **What cron can now do:** `newsroom collect` (one-shot; `--dry-run` = zero
  network) reads the same registry and writes inbox items. The repo installs **no
  timer**; a broken source is isolated and reported, partial failure → exit 1.
- **Live proof:** seed → collect gave **60 real items, 0 failures**; a second run
  added 0 and reported 60 already known (identity holds); `GET /sources` and
  `GET /inbox` render. Real defect caught and fixed by reading the live render:
  Google News snippets are HTML → normalized with the frozen
  `sources/html_desc.normalize_description` (+1 regression test).
- **Boundary held:** no angles, no research, no drafting, no story identity, no
  alerts in M4A. An inbox item is a candidate, never evidence.
- **Next:** freeze M4A, then **M4B** (story inbox as the start screen: НОВИ /
  ВАЖНИ / ЗА ПРОВЕРКА / СЛЕДЕНИ / ИГНОРИРАНИ + the «Какво трябва да направя
  сега?» workbench question). M4C story identity stays after M4B.

## Handoff — M3D closure + YouTube freeze (2026-09-20)

Verified: **700 offline tests**, ruff check/format clean, M3A smoke 25/25,
`--check-determinism` IDENTICAL 4/4. Report:
`m3/review/M3D_DISCOVERY_STABILITY_REPORT.md` (FREEZE banner + §11–§13).

- **Frozen:** `YOUTUBE_PIPELINE_V1 = FROZEN / GOOD_ENOUGH`. YouTube is a
  secondary source; no further optimization without observed production pain.
  `ANGLE_STABILITY = PROMISING` is the accepted end state.
- **A/B (the plan's only admitted model research):** facts pinned to
  `YsqD4T0D850__r003`, only `propose_angles` varies. Lite pool (M3D corpus):
  22.2–31.6% OUTCOME_FLIP; `openai/gpt-5.6-luna-pro`: **0/4 flips, overlap
  1.00** → the flip is model-capacity-driven. **Not rewired** — the switch is a
  backlog item needing a dedicated pool/role (`propose_angles` shares `judge`).
- **Fixed a real bug:** `_call_openrouter` never requested `stream: true` while
  parsing SSE, so the entire OpenRouter fallback returned empty completions.
  Regression tests: `tests/test_openrouter_transport.py`. Also removed a
  pre-existing `ruff` finding (useless `return`) left in the working tree.
- **Still blocked (recorded, not instability):** the free Gemini judge pool is
  unusable (404/429/400 empty-body signatures), so recordings `b13U-N_Vk9c` /
  `xvsdi_j7s5c` keep no 10-run baseline. Blocked rows preserved in
  `var/discovery_stability_corpus2/` (git-ignored).
- **Next:** **M4 — Daily Newsroom Operations & Source Management** (scope in
  `BACKLOG.md`): scheduled collection, source registry, story inbox, editor UX,
  Telegram editorial notifications, operational status. Smallest next step
  first; one milestone at a time.

## Handoff — M3D Discovery Reproducibility & Stability (2026-09-19)

Verified: **695 offline tests**, ruff/format clean, M3A smoke passes. Report:
`m3/review/M3D_DISCOVERY_STABILITY_REPORT.md`.

- **What was built:** replay harness `scripts/evals/discovery_stability.py`
  (replay runs, failure taxonomy with `STABLE`/`OUTCOME_FLIP` semantics,
  `--check-determinism`, `--cache-verify [--cache-seed]`) and the L4
  successful-stage cache `workflow/discovery_cache.py` (model stages only;
  failures/empty/**partial** runs never frozen; `--force-discovery` bypasses and
  keeps `*.prev.json`; version/config change = automatic miss).
- **Measured:** 79 live runs on 4 recordings; 0 `CATASTROPHIC_ZERO_YIELD`; flip
  rate 22.2–31.6% on the flaky recording, 0% on the stable one. **Root cause:**
  angle-proposition wording on identical facts (±1 rubric point flips the
  outcome), not extraction/grounding/parsing. `--cache-verify` on the real flaky
  recording: 6/6 seeded replays byte-identical.
- **Live bug caught by the harness:** the cache froze a PARTIAL run (4/5 topics
  execution-failed) as a success. Fixed in both directions (refuse at write,
  ignore at read).
- **Blocked:** Gemini free tier exhausted (500/day; surfaced 429 then a
  misleading `HTTP 400`), OpenRouter has no balance (HTTP 402). 17/40 corpus
  runs classified `DISCOVERY_DEGRADED` — correct behaviour, but recordings
  `b13U-N_Vk9c` / `xvsdi_j7s5c` still need their 10-run baselines, and
  forced-rerun variance is only unit-proven (all live forced runs degraded).
- **Next:** after quota reset re-run the two blocked recordings
  (`--out var/discovery_stability_corpus2`) and re-run `--cache-verify` with live
  forced runs; then the editor decides whether `OUTCOME_FLIP` is accepted as
  residual risk under the cache (recommended) or gets a mitigation scope.

## Handoff — M3B.1 YouTube Intake Operational Hardening (2026-09-19)

Verified: **653 offline tests**, ruff/format clean, M3A smoke 25/25, plus live
runs on two real recordings. Verdicts: `ANTIBAN_HARDENING_ENGINEERING = PROVEN` ·
`PLAYER_CLIENT_ROTATION = PROVEN` · `CRON_ENTRY_POINT = PROVEN` ·
`YOUTUBE_QUEUE_ENGINEERING = PROVEN` · `INVIDIOUS_FALLBACK = NOT_AVAILABLE` ·
`JEV_PRODUCTION_AUTHORITY = NONE` · `EDITORIAL_EFFECTIVENESS = PENDING`.

- Source of the ideas: sibling project `../youtube scripts downloader` (ytvault).
  Adopted pacing, browser identity, circuit breaker + cooldown, exponential
  backoff with parking, lock file, player-client rotation, bypass latch. Not
  copied: `rich`/`curl-cffi` as hard deps, the channel-catalog model, and the
  scheduler concept (the run stays a one-shot process).
- New: `youtube_policy.py`, `invidious.py`, `intake_queue.py`, `intake_run.py`.
  Hardened: `transcriber.py`, `intake.py`, `cli.py` (`youtube-batch`).
- Live evidence: `youtube-batch` dedupe + cache reuse 2.5 s; fresh transcription
  3.1 s / 184 cues; a second fresh recording ran end to end to `RESEARCH_MORE`;
  rotation rescued a deliberately failing client.
- Two real bugs were caught by the live runs and fixed before commit:
  rotated clients failing format selection (fixed with
  `--ignore-no-formats-error`), and the bypass producing a bare `None` that threw
  away every per-instance reason.
- Review also fixed: a temp-dir leak on every failed transcription, a racy
  lock, a block consuming the 15-minute backoff rung instead of the cooldown, an
  unmapped permanent failure category, and config warnings vanishing on the
  failure path.
- Post-review decisions (settled at review, 2026-09-19): `YOUTUBE_FALLBACK`
  defaults **off**; interactive `youtube-intake` takes the **same lock** as cron
  (exit `3`) without entering the retry/backoff lifecycle; clamped out-of-range
  `YOUTUBE_*` values now print a `policy warning:` line; stop-on-block, the
  registry/queue split, the rotation budget, fuse=5 and the historical origin
  strings all stay as built.
- **Next milestone decided: M3D Discovery Reproducibility & Stability** (see
  `BACKLOG.md`) — `same raw SRT` gave `RESEARCH_MORE` once and
  `NO_EXTRACTED_FACTS` another time, so the model-driven semantic layer is now
  the weak link. Not started here.
- STOP: no M3D yet, no M3C automatic enrichment, no story monitoring, no
  scheduler daemon, no article drafting, no publishing, no LIVE 6–10.

Reports: `m3/review/M3B1_CODE_REVIEW.md` (findings + settled decisions),
`m3/review/M3B1_INTAKE_HARDENING_REPORT.md` (design + live evidence).

## Handoff — M3B YouTube URL Intake + Real-World Jev Shadow Collection (2026-09-19)

Verified: **553 offline tests**, ruff clean, M3A smoke 25/25, plus a real
end-to-end intake on a known recording. Verdicts: `YOUTUBE_INTAKE_ENGINEERING =
PROVEN` · `TRANSCRIBER_INTEGRATION = PROVEN` · `REAL_TRANSCRIPT_DISCOVERY =
PROMISING` (unseen recordings pending) · `JEV_REAL_WORLD_SHADOW_COLLECTION =
ACTIVE` · `JEV_PRODUCTION_AUTHORITY = NONE` · `EDITORIAL_EFFECTIVENESS = PENDING`.

- `youtube-intake <URL>`: normalize → metadata → transcribe/reuse → raw SRT →
  discovery V2 → readiness (+ optional Jev shadow). `yt-dlp` is the transcriber;
  raw SRT cached content-addressed under `var/youtube_intake/`.
- No drafting, no scheduler/monitoring, no publish, no rubric/routing change.
- Workbench displays completed intakes at `/intake` (initiation CLI-only).
- Real run: YsqD4T0D850 → 184 segments, 12 topics, RESEARCH_MORE; 7
  semantic-rescue candidates (`DETERMINISTIC_REJECT__JEV_SUPPORTS`).
- STOP: no M3C automatic enrichment, no story monitoring, no LIVE 6–10.

Report: `m3/review/M3B_YOUTUBE_INTAKE_REPORT.md`.

## Handoff — M3A Stabilization + M3J Jev Shadow Evaluation (2026-09-19)

**Current state lives in `CURRENT_STATE.md`.** This file is chronological history.

Verified: **512 offline tests** (was 481), `ruff check`/`format --check` clean on
`src tests scripts`, M3A smoke **25/25**. Verdicts: `M3A_STABILIZATION = PROVEN` ·
`JEV_INTEGRATION = PROVEN` · `JEV_GROUNDING = PROMISING_STRONG` ·
`JEV_ANGLE_SEMANTICS = PROMISING` · `JEV_CORROBORATION =
NOT_SUITABLE_AS_STANDALONE_VERIFIER` · `JEV_PRODUCTION_AUTHORITY = NONE` ·
`EDITORIAL_EFFECTIVENESS = PENDING`. **M3J frozen.**

Live Jev (SDK 0.6.0, `jev-1.13.0`, 149/149 calls OK): grounding corrects
deterministic lexical false negatives (numbers/morphology/abbreviated years);
angle `development_type` matches the audit hypothesis on 6/7 known disagreements.
Manual label audit flipped both reviewed cases in Jev's favour. Corroboration
fixture passage was fixed (relevance window, not head HTML) and re-run. Shadow
results under ignored `var/jev_eval/`; no thresholds, no authority.

- Part A: hermetic test DNS (`tests/conftest.py`); one canonical live store
  `workflow/live_store.py` (CLI + Workbench); new root `CURRENT_STATE.md`;
  `scripts/m3a_smoke.py` promoted from `tmp/`. No M3A style refactor.
- Part B–J: optional `typesafe-sdk` extra + thin `workflow/jev.py` adapter;
  frozen `fixtures/evals/jev/`; resumable `scripts/evals/jev_shadow_eval.py`
  (`--experiment corroboration|grounding|angles`, `--all`) writing ignored
  `var/jev_eval/`; +31 offline tests; Jev has zero authority.
- STOP: no M3B YouTube intake, no M3C enrichment, no CMS, no LIVE 6–10, no
  rubric/threshold change, no Jev production authority.

Reports: `m3/review/M3A_STABILIZATION_REPORT.md`,
`m3/review/M3J_JEV_SHADOW_EVALUATION.md`.

## Handoff — M3A: Editor Workbench MVP (2026-09-18)

Verified: **468 offline tests, Ruff clean** (check + format on the new files),
scripted end-to-end smoke **25/25**. Verdicts: `EDITOR_WORKBENCH_ENGINEERING =
PROVEN` · `EDITOR_WORKBENCH_EDITORIAL_EFFECTIVENESS = PENDING` (no real editor
has used it) · `EDITORIAL_EFFECTIVENESS = PENDING` (unchanged).

M3A is a product/UX milestone: a Bulgarian-first browser workbench over the
unchanged frozen contracts. No rubric/threshold/profile/hook/routing change, no
drafting, no LIVE 6–10, no publishing.

- Run: `PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench`
  (≡ `python3 -m editor_assistant.workflow.workbench`). Defaults to
  **127.0.0.1:8123**; `--host` opt-in with a warning; no auth (local MVP);
  `--allow-quit` / `WB_ALLOW_QUIT` for the test-only `/quit`.
- Modules: `workflow/workbench/{state,html,http,labels,cli,__main__}.py`.
  Canonical writes only through `cases.record_editor_final` + `save_cases`;
  decisions through `readiness.apply_editor_override` on the live evidence row.
  Working copy: `var/editorial_workflow/editor_working/{CASE}.json` (atomic,
  `base_draft_id` staleness). Audit: `workbench_actions.jsonl`.
- Save ≠ finalize (separate POST endpoints). Stale generation → 409 with
  „Междувременно е генерирана по-нова AI версия…“ — checked against both the
  working copy's recorded base *and* the submitted `base_draft_id`, so
  resubmitting the current id cannot bypass it. The workspace then offers the
  explicit **„Приемам новата AI версия за основа“** re-base (a plain save never
  re-bases), so the guard is not a dead end. Dry-run benchmark cases refuse
  effort metrics. Invalid enums → 400 via the contract's own errors.
- Immutability guards: a finalized case renders no editor workspace and refuses
  working-copy saves; finalization requires a non-empty headline and body (a
  no-story case uses the decision endpoint instead); a corrupt/truncated
  working-copy file is read as “no working copy” instead of erroring.
- Evidence-only special cases (e.g. `LIV-06-EVIDENCE`,
  `NO_PUBLISHABLE_ANGLE`, no case row) are now listed in the queue and open a
  decision-only page with no article editor; ids are derived from stored
  readiness status, never hardcoded.
- Tests: `tests/test_workbench.py` (+74) — queue/filters (bucket vs. page
  surfaces agree), BG labels vs the canonical vocabularies, immutable draft
  (bytes unchanged), safe source
  rendering, working-copy save/load + atomicity, save-never-final, stale block
  + the re-base path through real HTTP, validated finalization (diff metrics +
  audit + AI draft untouched), empty-final refusal, invalid enums, the special
  cases (incl. a recorded decision staying out of «За редакция»), HTML escaping,
  transcript trust label + humanized locators, localhost default, and real-HTTP
  routing/400/404/409. HTTP tests use a private opener because
  `tests/test_search_foundation.py` used to leak a global
  `urllib.request.urlopen` (it assigns the module global directly instead of
  going through monkeypatch) — **fixed in the review pass below**.
- Smoke: `PYTHONPATH=src python3 tmp/m3a_smoke.py` runs against a copy
  (`var/wb_smoke/`) and asserts the real store is sha256-identical afterwards.
  25 checks, incl. the stale-generation guard (409) and the re-base → finalize
  path end-to-end through the browser flow.
- Note: `ruff format --check src tests` still flags two **pre-existing** files
  (`workflow/search.py`, `tests/test_tinyfish_adapters.py`) — left untouched
  (scope lock).

Report: `m3/review/M3A_EDITOR_WORKBENCH_REPORT.md`. **STOP for review** — no M3B
YouTube adapter, no M3C automatic enrichment, no LIVE 6–10, no CMS publishing,
no editorial-rule changes.

## Review pass — pipeline (M0/M1) + workflow (M2) modules (2026-09-18)

Read-only review of the modules outside the M3A workbench, with the confirmed
bugs fixed. Verified: **475 offline tests, Ruff clean**, workbench smoke 25/25,
real store untouched. No frozen contract changed (no rubric/threshold/profile/
ranking/semantics change); all fixes preserve existing output bytes.

Fixed (each reproduced before the fix):

- `notify/outbox.py` — `enqueue_notification` reported a **stale row id** for a
  duplicate intent instead of `None`: SQLite does not reset `lastrowid` for an
  `INSERT OR IGNORE`, so it returned the id of an unrelated earlier insert. The
  "did we insert?" signal is now `rowcount`.
- `sources/html_desc.py` — a self-closing `<script/>`/`<style/>` left the skip
  depth permanently raised and **silently dropped every remaining text chunk**
  in the description. Reachable from real feeds: ElementTree re-serializes an
  empty `<script></script>` as `<script />`. It corrupted the stored body and
  therefore the fingerprint.
- `workflow/cases.py` — `save_cases` truncated the case store in place; a crash
  or unserializable case mid-rewrite destroyed **every finalized article in it**.
  Now serializes first and publishes via same-directory temp file + `os.replace`.
- `notify/telegram.py` — an unexpected exception type (e.g.
  `http.client.InvalidURL`) escaped un-redacted and would have surfaced the
  request URL, which contains the bot token. All transport failures now fail
  closed with a type-only redacted error.
- `sources/web_fetch.py` — research page fetches never closed the response
  (socket held until GC); now closed in a `finally` (compatible with injected
  test openers that have no `close`).
- `tests/test_search_foundation.py` — two test-hygiene leaks: default-path
  audits appended fixture runs to the **real** `var/editorial_workflow/
  search_runs` (61 such files removed), and `_provider_with` left a fake
  `urlopen` installed for the rest of the session. Both contained by an autouse
  fixture; the suite no longer writes the real store at all.
- `notify/render.py` — the legacy `format_published_bg` comment claimed a
  UTC/`%Z` format it no longer returns (it delegates to the Europe/Sofia §6
  formatter).

Second pass — `workflow/readiness.py`, `notify/present.py`,
`drafting/generate.py`, plus the cross-module readiness/evidence contracts.
Verified: **481 offline tests**, Ruff clean, smoke 25/25.

- `drafting/generate.py` — **the semantic factual gate auto-passed with no
  verdicts.** `verify_claims_semantic` computed
  `pass = no unsupported and no parse errors`, so a judge reply of prose, an
  empty body, or a refusal yielded zero claims and zero errors → `pass: True`
  → the case was stamped `FACTUAL_GATE_PASS` with nothing checked. Reproduced
  for all four reply shapes. Now fails closed (`bool(claims) and …`), so an
  empty verdict set becomes `FACTUAL_GATE_REVIEW`.
- `notify/present.py` — `attachment_summary` counted every non-attachment link
  as hidden, so a fully displayed attachment list still rendered "+N още"
  under "📎 Документи:" (reproduced: `+2 още` with zero documents hidden). It
  now counts only further labeled attachments.
- `notify/present.py` — `attachment_label` read the extension from the full URL,
  so a real document served as `doklad.pdf?download=1` was silently dropped
  from the alert. Query/fragment are now stripped before the extension is read
  (still never guessed from the query: `…/download?file=doc.pdf` stays
  unlabeled).
- Verified as correct (no change needed): the real evidence rows use the nested
  `readiness_rounds.research_rounds` shape the workbench reads, and stored
  angle assessments keep `selected_angle_id` inside `candidates`.

Reported, NOT changed (owner decision — each touches a frozen contract or a
cross-cutting pattern beyond a review's remit):

- `poll.py` reports `new_outbox_intents` as `NEW + UPDATED` rather than the
  intents actually created; the outbox is first-intent-wins, so the number is
  assumed, not measured.
- 8 more canonical JSONL writers still truncate in place (`workflow/ideas.py`,
  `workflow/cli.py::_save_live_row`, `drafting/evidence.py`, `style/*`). The
  same atomic-write treatment should be applied project-wide.
- `workflow/cases.record_editor_final` validates `editor_outcome` only when
  `final_text` is non-empty (the CLI published-reference path), so an empty
  final with a bogus outcome enum is stored as-is. The workbench service layer
  now refuses empty finals; the contract itself is unchanged (frozen).
- `sources/fetcher.py`'s redirect guard runs after `urlopen` has already
  followed the redirect — it discards the payload but does not prevent the
  request to the foreign host.
- `workflow/live.py::live_readiness` accepts only 3 of the 4 override actions
  `readiness.apply_editor_override` supports (no `CHANGE_ANGLE`) and synthesizes
  a generic reason instead of the editor's.
- `workflow/readiness.py::assess_readiness` returns an inconsistent shape: the
  NO_ANGLE and NEEDS_RESEARCH branches omit `sufficiency` and `reader_interest`,
  which the other two branches always carry. Consumers currently use
  `.get(...)` guards, so nothing breaks today.
- `workflow/readiness.py` selects the chosen angle with a bare
  `next(c for c in candidates if …)`: an inconsistent stored assessment would
  surface as `StopIteration` rather than a `ReadinessError`. Its sibling in
  `angles.py` uses the safe `next((…), None)` + explicit-error form. Not
  demonstrably reachable, so left alone.
- Two shapes exist for research rounds: the CLI writes nested
  `readiness_rounds.research_rounds` (which the workbench reads, and which the
  real store uses), while `readiness.register_research_round` writes a flat
  top-level `research_rounds` list on whatever record it is handed.

## Handoff — M2S-R4: TinyFish Search ADOPTED — Routing Implemented (2026-09-18)

Editor decision on the M2S-R3b measured benchmark → routing implemented and
frozen. Verified: 394 offline tests, Ruff clean.

- `PROVIDER_ORDER` (search.py): NEWS -> google_news_rss -> tinyfish -> serper
  -> ddgs -> brave · WEB -> tinyfish -> serper -> ddgs -> brave · BACKGROUND
  -> wikipedia -> tinyfish -> serper -> ddgs. TinyFish is the first general
  WEB provider; RSS/wikipedia keep the keyless specialist slots; serper/brave
  stay key-gated. Evidence pointer lives in the PROVIDER_ORDER comment block.
- Keyless degradation: missing `TINYFISH_API_KEY` → explicit
  `tinyfish:no-key` note, chain continues (e.g. ddgs next for WEB). The
  `SEARCH_PROVIDER=tinyfish` pin is unchanged; out-of-order pin mismatch stays
  an explicit unavailability, never a silent fallback.
- `TINYFISH_FETCH = AVAILABLE / NOT_YET_PROVEN`: NOT promoted to default fetch
  fallback (0/2 on the only live fallback cases); adapter remains behind
  `fetch_with_fallback`'s narrow failure-category trigger as a candidate
  rescue path for JS-heavy/parse failures if real cases show it saving pages.
- `.gitignore`: `media.zip` ignored specifically (not `*.zip`).
- Verdicts frozen: SEARCH_EXECUTION_ENGINEERING = PROVEN · TINYFISH_SEARCH =
  ADOPTED · TINYFISH_FETCH = AVAILABLE/NOT_YET_PROVEN ·
  TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING+ ·
  TRANSCRIPT_RESEARCH_ENRICHMENT = PROMISING · EDITORIAL_EFFECTIVENESS = PENDING.
- The semantic correction (`CONCRETE_ACTION_NEEDS_RESEARCH` vs
  `ROUTINE_REPORT_VETO`) stays FROZEN until the editor V2 sample review; when
  it arrives, compare the editor's decisions against the audit's four semantic
  cases (social aid, school funding, museum refusal, routine budget reports)
  before any narrow, structure-based correction.

Next: editor — V2 sample review (the only open gate). No thresholds, no
drafting, no LIVE 6–10, no Monid.


## Handoff — M2S-R3b: TinyFish Keyed Benchmark + Focused Audit (2026-09-18)

Verified: 393 offline tests, Ruff clean. `TINYFISH_API_KEY` provided (the
editor's `TINY_FISH_APY_KEY` was renamed to the correct variable name). The
benchmark was extended to measure TinyFish live on the same cells and re-run —
no PROVIDER_ORDER change:

- TinyFish search: **20/20 SEARCH_OK, 7/7 known-answer hits, latency avg
  0.3 s (max 0.9 s)**. Incumbent chain in the same run: 18/20 COMPLETE, 6/7
  known hits (DDGS degraded on its 5th same-day run; misses honest
  SEARCH_INCOMPLETE), avg 3.2 s. TinyFish found the needle the degraded chain
  dropped (`Община Бургас бюджет 2026`).
- TinyFish fetch fallback: exercised only on the 2 local FETCH_HTTP_ERROR
  cells (narrow triggers held; blocked targets never forwarded); TinyFish
  also failed both (`page_not_found` → honest SOURCE_FETCH_FAILED), 0/2
  opened; local opener alone 6/10.
- Verdicts: TINYFISH_INTEGRATION = READY · TINYFISH_EFFECTIVENESS = MEASURED
  (favored on search) · ROUTING_CHANGE = DEFERRED — routing is now an editor
  decision with data; adapter stays pin-addressable.
- Focused audit (`m2/review/SHADOW_DISAGREEMENT_ENRICHMENT_AUDIT.md`): no
  rubric redesign; two semantic hypotheses (CONCRETE_ACTION_NEEDS_RESEARCH vs
  ROUTINE_REPORT_VETO) await editor calibration;
  TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING+; enrichment = PROMISING
  (candidates ≠ confirmations; lexical matcher is a source locator, not a
  corroboration engine); EDITORIAL_EFFECTIVENESS = PENDING.
- Harness fix while measuring: verdict logic + fetch-fallback instrumentation
  corrected (fallback attempted ≠ unexercised); docstring updated. Harness
  script only — production adapters untouched.

Next: editor — V2 sample review + routing decision on the measured cells.
No thresholds, no drafting, no LIVE 6–10, no Monid.

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
