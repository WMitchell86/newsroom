# LIVE Pilot Generation Report

> Status: GENERATION COMPLETE — all 5 drafts generated 2026-09-16.
> Gates: 3 PASS (LIV-01, LIV-04, LIV-05), 2 REVIEW (LIV-02, LIV-03).
> Duplicate checks DEFERRED per editor decision 2026-09-16 (human-review stage).
> NOTHING is published — review-only drafts for human correction.

## Research capability added

- `src/editor_assistant/workflow/research.py` — minimal SourceBundle layer
  (no crawler/index/vector DB): candidates incl. preserved failures with one
  explicit reason, opened sources with PRIMARY/CORROBORATING/DISCOVERY_ONLY
  authority, claim-level provenance (`source_refs: {source_id, locator}`),
  duplicate-check contract incl. new `DUPLICATE_CHECK_DEFERRED` (never clean),
  transcript intake with timestamp/chunk locators, council decision safeguard,
  Europe/Sofia time records.
- Real-execution fixes: CLI dict→ArticleRecord adapter, site_dna str→dict,
  repeat-`live-generate` guard moved before the model call, `--case-id`.

## Tests

266 passed, ruff clean. New: `test_workflow_research.py` (8 tests),
`test_workflow_live_cli.py` (repeat-generation regression),
`test_live_generate_offline.py` (hermetic prompt→draft→judge→case e2e +
frozen 503-retry proof).

## Cases attempted

5 (LIV-01…LIV-05). Clock: 2026-09-16 Europe/Sofia.

## Cases generated

5 of 5 complete (LIV-01…LIV-05). Clock: 2026-09-16 Europe/Sofia.

## Cases waiting

None — all generated. Awaiting editor review + duplicate checks.

## Failed/replaced cases

- LIV-01: only PAST Burgas performance findable at first → then REAL target
  found via Brave (organizer Artvent + ticket.bg: Burgas 14.10.2026 19:00
  NHK). Old 2025 Morska-gara page kept as REJECTED candidate (temporal trap).
- LIV-05: BTA Burgas regional page HTTP 429 → failed candidate, not dropped.

## LIV-01

### Research result

Organizer Artvent: Burgas 14.10.2026 19:00 NHK + Yambol 13.10; ~4 weeks lead.
### Sources

S-ARTVENT (organizer, PRIMARY), S-TICKETBG (ticket platform, CORROBORATING).
### Duplicate check

`DUPLICATE_CHECK_DEFERRED` — resolve before publication.
### Suggested mode

MODE_EVENT_PREVIEW (explicit editor step).
### Factual gate

**FACTUAL_GATE_PASS** — draft “Комедията «Съвършени натрапници» гостува
в Културен дом НХК”.
### Warnings

Eventim listing page unreachable (timeout) — not used as source.


## LIV-02

### Research result

Editor transcript (health committee, 8 items, timestamps). 5 developments
ranked; selected forensic-medicine equipment funding (unanimous committee).
### Sources

S-TR (transcript, PRIMARY) with t=/chunk locators.
### Duplicate check

`DUPLICATE_CHECK_DEFERRED`.
### Suggested mode

MODE_STANDARD_NEWS (tool suggestion accepted).
### Factual gate

**FACTUAL_GATE_REVIEW** — judge flagged unsupported claims; correct first.
### Warnings

Committee vote is not a council decision (“комисията подкрепи”, never
“съветът прие”). DCC vote cut off mid-record — NOT a decision, excluded.

## LIV-03

### Research result

Municipal sport calendar (Sept block): boxing “Купа Бургас 2026” 18-20.09,
hall Mladost, BC Royal — nearest future event with real lead time.
### Sources

S-CAL (municipality, PRIMARY). Single source, no invention.
### Duplicate check

`DUPLICATE_CHECK_DEFERRED`.
### Suggested mode

MODE_BRIEF (3 facts, 206 chars).
### Factual gate

**FACTUAL_GATE_REVIEW** (headline: boxing tournament in Mladost).
### Warnings

Thin evidence — details limited to calendar lines.

## LIV-04

### Research result

Municipal news 16.09.2026: 9th DOCK 17-22.09, opening 17.09 19:30
Dom na neftohimika, “Silvi Vartan” (dir. Ema Konstantinova), audience
award + short-film program new, free entry.
### Sources

S-DOCK (municipality, PRIMARY). Organizer page not fetched.
### Duplicate check

`DUPLICATE_CHECK_DEFERRED`.
### Suggested mode

MODE_EVENT_PREVIEW (CULTURE_FEATURE considered — preview urgency wins).
### Factual gate

**FACTUAL_GATE_PASS** — draft “Фестивалът DOCK започва утре в Бургас
с филм за Силви Вартан”.
### Warnings

Single source; titles limited to films named in source.

## LIV-05

### Research result

BTA Bulgaria feed (no usable Burgas lead) + 3 same-day burgas.bg
candidates ranked; selected author meeting 18.09 18:00 (Dom na pisatelya).
### Sources

S-AUTHOR (municipality, PRIMARY: organizers, bio, time/venue).
### Duplicate check

`DUPLICATE_CHECK_DEFERRED`.
### Suggested mode

MODE_STANDARD_NEWS (default; BRIEF considered).
### Factual gate

**FACTUAL_GATE_PASS** — draft “Бургас посреща писателя Ванцети Василев
с новия му роман”.
### Warnings

BTA regional page 429 kept as failed attempt; single-source story.

## Provenance validation

All 5 bundles COMPLETED; every claim maps to opened sources
(`relevant_claims` + content references). Packet `source_refs` attach at
draft build via `live-evidence` lineage.

## Semantic factual-gate results

LIV-01: PASS. LIV-02: REVIEW. LIV-03: REVIEW. LIV-04: PASS. LIV-05: PASS.

## Regenerations

0 (single-attempt M2.3B policy; repeat-generate refused pre-call).

## Editor review files

- `var/editorial_workflow/review/LIV-01.md` (READY — PASS)
- `var/editorial_workflow/review/LIV-02.md` (READY — REVIEW, correct first)
- `var/editorial_workflow/review/LIV-03.md` (READY — REVIEW, correct first)
- `var/editorial_workflow/review/LIV-04.md` (READY — PASS)
- `var/editorial_workflow/review/LIV-05.md` (READY — PASS)

## What went well (OK)

1. **Real research worked end-to-end.** All 5 cases grounded in actually
   fetched sources (burgas.bg municipality pages, Artvent organizer page,
   ticket.bg, BTA feed, editor transcript) — zero fabricated URLs, zero
   invented facts. Every material claim traces to an opened source.
2. **Temporal-confusion trap handled correctly (§13).** The old 2025
   Morska-gara “Натрапници” page was identified as a PAST event and kept as
   a REJECTED candidate; the real upcoming Burgas date (14.10.2026 NHK) was
   found via a working engine (Brave) and corroborated by two independent
   sources.
3. **Factual gate caught real problems.** LIV-02 and LIV-03 flagged REVIEW
   instead of silently passing — the M2.3B semantic judge did its job.
4. **Council safeguard held.** Committee vote kept distinct from council
   decision; the cut-off DCC vote excluded from the angle.
5. **Provenance + research contracts enforced by tests.** 266 tests pass,
   ruff clean; snippet-cannot-back-facts, deferred-duplicate-not-clean,
   council-guard, and repeat-generation regression all green.
6. **3 of 5 drafts passed the gate on first attempt** (LIV-01, LIV-04,
   LIV-05) — all VOICE_HOUSE, modes chosen by real suggestion logic.

## What went wrong (honest)

1. **Search-engine fragility (§23 near-miss).** DuckDuckGo (bot challenge),
   Google (consent redirect), Yahoo (500), Mojeek (captcha), Ecosia (403),
   Startpage (JS gate) all failed from this harness. Only Brave Search
   returned usable results — single point of failure. If Brave had also
   blocked, LIV-01 would have ended as RESEARCH_CAPABILITY_GAP.
2. **LIV-01 false start admitted.** The first attempt declared “no upcoming
   Burgas performance” and built a replacement lead (youth troupe) before
   Brave was tried. The editor was right to push back — corrected within
   the same session, replacement lead discarded, but the wasted path is on
   record.
3. **API-key handling bug wasted a cycle.** `.env` value quoted; naive
   `export $(grep …)` passed quotes into the key → API_KEY_INVALID. Fixed
   by proper `source .env`. (Offline hermetic e2e test added so the code
   path no longer depends on key/network state.)
4. **Latent code bugs surfaced only under real execution.** dict→record
   adapter missing (`live-evidence` crashed), `site_dna` str vs dict
   (`live-generate` crashed), repeat-generate calling the model before the
   duplicate check (wasted spend + duplicate rows). All fixed + regression
   tested — but they prove the LIVE path had never been run end-to-end
   before this checkpoint.
5. **Thin evidence on LIV-03.** Boxing preview rests on 3 calendar lines
   from a single PRIMARY source; no organizer/club page reachable. Draft
   flagged REVIEW — usable only after editor enrichment.
6. **Duplicate checks deferred, not done.** Per editor decision, all 5 sit
   at `DUPLICATE_CHECK_DEFERRED` — none counts as a clean LIVE case yet.
   The chernomorie-bg.com search endpoint returned empty/generic listings
   from this harness; the check must be done by a human before ANY
   publication decision.
7. **Two teammate dispatches failed** (runtime Unauthorized) — research
   continued in the main agent instead. No data lost, but parallel speedup
   was lost.
8. **BTA regional page unreachable (HTTP 429).** LIV-05 triangulation is
   single-source; second corroborating source still wanted.

## Corrective pass (FIX_NARROWLY_THEN_CONTINUE)

One narrow pass, applied 2026-09-16 before editor scoring — no scope creep:

- **Repaired `src/editor_assistant/drafting/evidence.py`** (corrupted during
  the LIVE session): restored the lost `def attach_provenance(packet,
  refs_by_fact_id):` signature line and removed the duplicated
  `for key in (...)` validation line plus a stray injected text fragment
  inside `validate_packet`.
- **Re-verified after repair:** `py_compile` clean, **266 tests passed**,
  ruff clean. `attach_provenance` importable and callable; 50 rapid
  `new_idea` calls still yield 50 unique ids (identity contract intact).
- Pilot artifacts untouched and intact: 5 research bundles
  (`var/editorial_workflow/research/LIV-01…05.json`), 5 review files
  (`var/editorial_workflow/review/LIV-01…05.md`), gates unchanged
  (3 PASS / 2 REVIEW).

## Editorial-value corrective pass — 2026-09-17

**Implementation verified offline; existing LIVE drafts not regenerated or rescored.**

- Transcript/council inputs now require a persisted `editorial_assessment`.
  Missing assessment raises `ANGLE_REVIEW_REQUIRED` before model access.
- `live-angles <evidence_id> <absolute JSON path>` accepts 3–5 distinct
  research/editor candidate assessments. Seven criteria are scored 0–2:
  concrete change, people impact, money/infrastructure/services, differing
  positions, unexpected fact, strong quote, Burgas novelty. Positive scores
  require a reason and references to existing packet fact IDs.
- Pilot threshold: **5/14 plus positive current Burgas novelty**. This is an
  initial policy assumption, not an empirically calibrated editorial model.
  No eligible candidate yields `NO_PUBLISHABLE_ANGLE` with reasons, persisted
  on the idea/evidence row; no draft, case, or model call. A new explicit
  assessment can reopen the idea as FOLLOW_UP, never auto-generate it.
- Selected-angle drafting is restricted to its referenced facts. Unmapped
  meeting-wide quotes are omitted. Candidate judgments are not factual evidence;
  referenced fact IDs prove traceability, not that the judgment is correct.
- EVENT_PREVIEW prompt v2 permits one light hook for culture/comedy/entertainment
  only when source tone and evidence synopsis support it. Preferred sequence:
  hook → what/when/where → reader interest → cast/program/practical details.
  Calendar-only evidence does not license a playful synopsis. No invented plot,
  reactions, reviews, audience response, advertising exaggeration or promises.
  The semantic judge still checks every implied factual premise.
- Frozen drafts retain their original prompt version and IDs; tests distinguish
  historical artifacts from the current prompt instead of rewriting history.

### Verification and limits

**277 tests passed; Ruff clean; CLI help and temporary-store CLI flow verified.**
Tests cover absent/weak assessments, threshold selection, invalid references,
boolean scores, historical novelty, rejection persistence, no generation/files,
explicit reopening, selected-fact drafting, and prompt/judge hook boundaries.
No model/network calls or production-store writes were used for this verification.

Candidate discovery and semantic editorial scoring remain a research/editor task:
there is no automatic full-transcript angle-extraction pipeline in this pass.
With fewer than three real candidates, the current contract requests review;
it does not fabricate padding candidates. Human calibration of the rubric and
live assessment of reader interest remain pending. The existing LIV-01…05
artifacts and original gates are not evidence of performance under these rules.

See `/home/test/media/m2/review/EDITORIAL_VALUE_USAGE.md` for the input contract.

## Next editor action

1. Correct LIV-02 + LIV-03 (both REVIEW — not for use as-is).
2. Review LIV-01/04/05 PASS drafts (`finalize` with
   editing_weight/time/prefer_ai_start).
3. Run duplicate/prior-coverage checks on chernomorie-bg.com per case
   before ANY publication decision.
4. After 5 finals → `LIVE_EDITORIAL_CHECKPOINT_5.md` → checkpoint decision.
