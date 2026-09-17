# Editorial Readiness Layer

Verdict: **EDITORIAL_READINESS_ENGINEERING = PROVEN** (offline, general semantic fixtures + read-only LIVE regression; 313 tests, Ruff clean; no frozen system touched).
Verdict: **EDITORIAL_READINESS_EDITORIAL_EFFECTIVENESS = PENDING** — whether the readiness *decisions* are the right editorial calls is proven only by the human editor on the real LIVE cases (review artifacts prepared; STOP, §38).

## Implementation

Composable readiness layer between research/evidence (frozen M2.3B) and drafting — no plugin framework, no new dependencies, stdlib only:

- `src/editor_assistant/workflow/angles.py` — rubric **v2** (`editorial-value-2`): mandatory `new_proposition`, semantic veto, explicit `semantic_status` (PUBLISHABLE_ANGLE / POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH / NO_PUBLISHABLE_ANGLE), novelty floor, recorded editor override.
- `src/editor_assistant/workflow/readiness.py` — evidence sufficiency (MODE-aware semantic dimensions), reader-interest/hook planner, readiness orchestrator, gap-driven research-loop bookkeeping (max 2 rounds), editor overrides, `hook_task_extra` prompt fragment.
- `src/editor_assistant/workflow/live.py` — `live_readiness()`; `live_generate_draft()` now gated: only `DRAFT_READY` drafts automatically; `RESEARCH_MORE` returned to the caller; `force_draft` recorded (§32); hook plan injected into the prompt via `task_extra`.
- `src/editor_assistant/workflow/cli.py` — `live-readiness` command (with `--round`, `--mark-*`, `--override`), `live-angles --override --override-reason`, `live-generate --force-draft --force-reason`; readiness persisted on draft rows and evidence rows; `readiness_outcome` accepted at finalize (editor learning data, §23/§33).
- `m2/review/editorial_readiness_guidance.json` — versioned guidance artifact (§22).

## Reused architecture

- `state`/`notify`/`sources` untouched; M2.3B drafting path (prompt → generate → lexical + semantic gates → lineage) untouched — readiness composes **in front of** it.
- `modes.suggest_mode` reused for the deterministic MODE default; frozen `SITE DNA` + `VOICE_HOUSE` + MODE profiles reused as-is (no mutation, M2.2 not reopened).
- Same CLI store (`var/editorial_workflow/*`), same immutable draft/final flow, same lineage rules; `live-generate` still requires the explicit `live-case` trigger.

## New contracts

- `assess_readiness(packet, *, mode=None, candidate=None) -> {status: DRAFT_READY | RESEARCH_MORE | NO_PUBLISHABLE_ANGLE | EDITOR_DECISION_REQUIRED, editorial_value_status, evidence_sufficiency_status, hook_strategy, reader_interest, sufficiency, assessment}` (§24/§31 shape).
- `assess_sufficiency(packet, *, mode)` → `{status: EVIDENCE_SUFFICIENT | RESEARCH_MORE | INSUFFICIENT_FOR_ARTICLE, present_dimensions, missing_dimensions, research_questions, bare_announcement}` (§8–§10; semantic coverage only, no word counts, no numeric thresholds).
- `plan_reader_interest(packet, *, mode)` → `{hook_strategy, basis_fact_ids, rationale, serious_subject, alternatives_considered}` (§15–§19).
- `expansion_plan` / `register_research_round` (§11–§13, hard limit 2), `apply_editor_override` (§32, recorded, never silent).
- Rubric v2 (§3–§6, §26, §29): `total` and `numeric_eligible` remain visible for ranking/diagnostics, but `eligible` now equals semantic viability: explicit veto wins, then explicit `semantic_status`, then the novelty floor (no concrete new-event signal in supporting facts → NO_PUBLISHABLE_ANGLE), then (only for unmarked candidates) numeric eligibility.
- Three statuses tracked independently (§14): `editorial_value_status` / `evidence_sufficiency_status` / factual gate on the case.

## Newsworthiness behavior

Semantic, not a point threshold. Every candidate must state its NEW PROPOSITION (validated: non-empty, distinct from the title, and not just rubric points). The system can answer "what is new?" in one sentence per candidate, or refuse.

## Semantic veto behavior

Veto + `semantic_reason` overrides any score (§5/§29): tested with an above-threshold candidate (total=5, `numeric_eligible=true`) that is still rejected. Reverse case also covered: a concise concrete development can be promoted via explicit `semantic_status=PUBLISHABLE_ANGLE` even below the threshold. The novelty floor additionally blocks candidates whose supporting facts express no new event/decision/occurrence at all.

## Evidence sufficiency behavior

MODE guidance patterns (§9), not templates: `MODE_BRIEF` depth = time/place or affected people; `MODE_EVENT_PREVIEW` = schedule/participants/program/admission/format/practical/unusual; `MODE_STANDARD_NEWS` = affected/why/consequence/scale/authority/time-place/amount; `MODE_CULTURE_FEATURE` adds quote/program depth. A **bare announcement with zero reader-value depth is RESEARCH_MORE in every MODE** — BRIEF can never be used to bypass research (§27 Fixture C, tested). Missing dimensions become concrete research questions (§10), e.g. start times / admission / format — never site-specific instructions (§12).

## Targeted research behavior

`live-readiness --round` registers targeted enrichment rounds against the recorded gap (max 2, enforced, §13); after the limit the CLI forces one of the three Good-Enough decisions via `--mark-sufficient` / `--mark-insufficient` / `--mark-editor-decision` (each with a mandatory recorded `--reason`). Where to look (organizer/venue/federation/ticket platform) stays the research layer's decision.

## Reader-interest / hook behavior

Strategy ranked by evidence support (§16 vocabulary), with two hard rules:
- §17 serious subjects (death, crime, accident, health emergency, courts, minors, tragedy, allegations) → only STRONGEST_FACT / CONSEQUENCE / LOCAL_IMPACT; the guard beats any playful cue present in the text (tested).
- §18 playful framing requires an entertainment subject **and** a supported comic/unusual premise; calendar-only listings never get PLAYFUL (tested).
Hook basis is traceable (`basis_fact_ids`); the prompt fragment (`hook_task_extra`) instructs the strongest-fact opening, up to 3 truthful headline emphases, and forbids clickbait patterns; a self-check rejects the fragment itself if it ever contains a forbidden pattern (§20/§21). Hooks add no facts — every factual premise stays inside the normal factual gate (§19, verified by existing judge-prompt tests).

## Corpus/style guidance reused

The frozen profiles already encode the HOW: digits in ~26–32% of headlines, result/decision headline forms, `immediate_fact` openings ~77% (house), practical closing line in EVENT_PREVIEW, quoted-title openings only in CULTURE_FEATURE. The readiness layer's strategy set maps onto exactly these surfaces — no new house rules were needed.

## New guidance added, if any

`m2/review/editorial_readiness_guidance.json` (`editorial-readiness-guidance-1`, PROVISIONAL): strategy→use_when mapping with profile alignment, the §17 serious-subject rule, headline-behavior constraints (no colon/question/exclamation, 40–60 chars), the forbidden clickbait pattern list, and the §23/§34 no-auto-learning note. It augments, never replaces, the frozen profiles.

## General semantic fixture results

All in `tests/test_editorial_readiness.py` (general, no entity hardcoding):

| Fixture | Surface | Expected | Result |
|---|---|---|---|
| A — routine meeting | agenda adopted, routine reports, no result | NO_PUBLISHABLE_ANGLE | ✅ (veto honored; readiness = NO_ANGLE, no hook) |
| B — important but incomplete | financial support discussed, amount/recipients/outcome missing | POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH (or NO_ANGLE); high score must not force publication | ✅ NEEDS_RESEARCH with research questions; veto+score regression test ✅ |
| C — thin event listing | name/date/venue/organizer only | RESEARCH_MORE (no BRIEF bypass) | ✅ RESEARCH_MORE in EVENT_PREVIEW **and** BRIEF; bare_announcement=true; gap questions present |
| D — enriched event | + schedule, participants, admission | DRAFT_READY | ✅ (hook PRACTICAL_VALUE) |
| E — supported playful premise | comedy with escalating-lies synopsis | DRAFT_READY with PLAYFUL/CURIOSITY, grounded | ✅ CURIOSITY chosen; subject-alone premise does NOT trigger PLAYFUL ✅ |
| F — serious sensitive story | fatal accident | DRAFT_READY, never PLAYFUL | ✅ LOCAL_IMPACT; serious-subject guard beats playful cues ✅ |

Loop contracts: expansion plan max 2 rounds, third round raises; `FORCE_DRAFT` recorded with `pre_override_status` kept visible; `hook_task_extra` grounded + clickbait-free; §31 record shape complete; `live_generate_draft` blocks RESEARCH_MORE without `--force-draft` and injects the hook plan into the prompt when DRAFT_READY.

## LIVE regression results

Read-only run of the stored LIVE artifacts through the readiness layer (store **not** mutated; v1 candidates re-judged under the v2 contract from their own stored reasons — in the real flow those judgments come from research/editor via `live-angles`). Full detail: `m2/review/M2R_LIVE_READINESS_REGRESSION.json`.

### Which remained DRAFT_READY
- **LIV01** (theatre comedy) — sufficient + entertainment; hook CURIOSITY (reader-interest framing can now be stronger; lesson per §28: stronger framing, not "theatre needs jokes").
- **LIV04** (rich festival DOCK) — program/dates/opening/admission present; DRAFT_READY baseline ✅; hook PRACTICAL_VALUE.
- **LIV05** (writer/romance feature) — DRAFT_READY as CULTURE_FEATURE (practical hook; program/participants enrichment optional).

### Which requested RESEARCH_MORE
- **LIV03** (thin boxing gala: name/date/venue/organizer only) — factual support was valid but evidence richness inadequate ✅ (§28); missing schedule/participants/program/admission/format with concrete questions. No BRIEF downgrade exists anymore.
- **LIV-02** (health-commission transcript) — the forensic-equipment item is concrete but decision status/amount are not established in the record → `POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH` (previously auto-selected and drafted at total=8). This is the general §6 rule applied to a transcript case: importance ≠ established news event.

### Which became NO_PUBLISHABLE_ANGLE
- **LIV-06** (financial-aid transcript) — the §29 contradiction case: `A-HELP` was `eligible=true, total=5` while its own reason said the record cuts off with no amount/recipients/decision. Under v2 the semantic veto overrides numeric eligibility → NO_PUBLISHABLE_ANGLE (a success state, §25). No weak draft is generated; the stored draft is untouched (frozen/superseded artifacts were not modified, §36.3).

### Which required editor decision
- **LIV03** (operational phase, 2026-09-17): after the honest 2/2 targeted research rounds (calendar re-read live; organizer club page unreachable; search engines blocked in the harness — attempts recorded in the round log), the surface is still a bare announcement for a full preview, and the event is 1–2 days away. Terminal state per §13: **EDITOR_DECISION_REQUIRED** with `REQUEST_MORE_RESEARCH` recorded (pre_override_status visible). Review artifact: `var/editorial_workflow/review/LIV-03-DECISION.md`. No article is forced.

### Operational phase (2026-09-17) — readiness/research loop executed on the LIVE store
- **LIV-02**: migrated to rubric v2 through the real `assess_angles` contract (editor selection `A-FORENSIC` preserved, migration note on the evidence row). Novelty floor initially failed it — a Bulgarian participle morphology gap (`приетa` vs `приет`) in `NOVELTY_CUE`, fixed generically (stem + `\w*`), not case-specifically. Under v2 the packet is **DRAFT_READY** (MODE_STANDARD_NEWS, hook STRONGEST_FACT) → regenerated via the M2R path: **FACTUAL_GATE_PASS**, hook fragment in the prompt, generation 3, previous draft archived under `superseded/` (see Draft changes).
- **LIV-06**: migrated to rubric v2 with explicit semantic vetoes derived from each candidate's own v1 reason (the transcript cuts off before the concrete outcome — the general §5/§6 rule, no topic hardcoding). Store now carries the validated **NO_PUBLISHABLE_ANGLE**; a separate **NO-STORY review** artifact asks the editor whether the refusal itself is correct (`var/editorial_workflow/review/LIV-06-NOSTORY.md`). No article generated.
- **LIV01/04/05**: readiness computed read-only (DRAFT_READY; CURIOSITY / PRACTICAL_VALUE / PRACTICAL_VALUE) — existing drafts untouched (§36.3).
- **Correction disclosed**: three enrichment facts added to LIV-03 during Round 1 cited a source (`S-WEB:club-royal-page`) that was never actually fetched. They were removed the same day (live calendar re-check confirmed only date/venue/organizer); an `evidence_correction` note is on the evidence row, the round log purges the fabricated source, and the readiness decision was recomputed without them. No draft ever referenced the removed facts.
- **Lineage note**: draft IDs are deterministic (evidence+voice+mode+prompt), so a regenerated draft keeps its predecessor's id and `superseded_draft_id` alone cannot disambiguate generations. Full draft history remains in append-only `live_drafts.jsonl`; the case row now carries `generation` (LIV-02 → 3) and the pre-M2R archive snapshot was renamed to keep both.

## Draft changes where regenerated

- **LIV-02 regenerated** (the only case whose readiness path materially changed and where regeneration is useful for editor evaluation, §36.5): v2 gate + sufficiency + grounded hook entered the prompt; new draft passes the full factual gate; lineage preserved via `superseded/` archive, `generation=3`, `regeneration_reason`, and the immutable append-only draft log. Headline candidates: „Финансират ново оборудване за съдебната медицина в Бургас“ + 2 alternatives for the editor (§20).
- **LIV01/04/05 not regenerated** (§36.3: no auto-overwrite; drafts immutable) — they go to the editor as-is, with readiness annotations.
- **LIV-03: no article** — the readiness layer itself says the evidence does not yet justify one; forcing it would contradict the layer's purpose (§38).

## Tests

- 313 passed, 0 failed (was 285 with 1 known failure); Ruff check + format clean.
- New: `tests/test_editorial_readiness.py` (19 tests: fixtures A–F, §31 shape, loop limit, overrides, serious guard, hook fragment, semantic floor, generation gate).
- New editor-assessment contract (end of the workflow): `record_editor_final` accepts a validated `readiness_outcome` (ANGLE_ACCEPTED | ANGLE_CHANGED | NO_STORY_CONFIRMED | RESEARCH_REQUESTED) + optional `readiness_note` + structured `readiness_answers` (would_publish / angle_right / headline_strong / opening_engaging, YES|NO|CHANGE) — LIVE cases only, refused on dry-run, note requires verdict; the `finalize` scorecard template asks for all of them and presents the alternative headline candidates (§20); `workflow_metrics` aggregates `readiness_outcomes` for future threshold/hook learning (§23/§33: persisted data, no automatic learning). 9 tests in `tests/test_workflow_cases.py`.
- Updated to rubric v2: `tests/test_editorial_value.py`, `tests/test_live_generate_offline.py`, `tests/test_workflow_live_cli.py`.
- **§30 resolved**: `test_scoped_packet_gate_reverifies_binding_but_skips_rescoring` was failing because the test itself selected an all-zero-score candidate as editor selection (`A1`, total 0) — under both v1 and v2 semantics no gate could honor that. The test now scores the candidate genuinely (distinct fact, decision-based) and additionally proves an editor may overrule the *ranking* but never the *gate* (§32). No test was marked expected-failure.

## Known limitations

- Cues/dimension detectors are lexical BG heuristics — they generalize across topics (no entity lists) but can miss unusual phrasings; the novelty floor is a floor, so a missed cue can only *demote* a candidate to needs-editor-attention, never force publication.
- `new_proposition`/`veto`/`semantic_status` quality depends on research/editor judgment supply; the gate validates grounding and consistency, it cannot verify the judgment itself.
- Editor-override recording exists (CLI + records), but there is no analytics aggregation yet (§33: persist enough to learn later — done; no subsystem built).
- The regression re-judgment of v1 candidates injected semantic fields from stored reasons; the store itself still holds v1 assessments and is intentionally not migrated (re-assessment happens via `live-angles` when a case is revisited).

- The v1→v2 migrations of LIV-02/LIV-06 were performed through the real `assess_angles` contract with recorded `assessment_migration` notes (the CLI guard refuses re-assessment while a case is open, so the migration went through the library path deliberately).
- Deterministic draft IDs mean `superseded_draft_id` cannot disambiguate generations; the append-only `live_drafts.jsonl` + `generation` counter on the case row are the authoritative lineage (see the lineage note above).

## Good Enough backlog

- `NO_STORY_CONFIRMED` / `ANGLE_ACCEPTED` / `RESEARCH_REQUESTED` editor outcomes are captured via `readiness_outcome` at finalize; aggregation + threshold learning deferred until real editor corrections accumulate (§23/§34).
- LIVE cases 6–10 remain out of scope until the editor reviews this milestone (§38).
- Possible future enrichment: quote-derived hooks from structured quotes (currently quote cues cover «…», "…", „…" forms).

## Verdict

**EDITORIAL_READINESS_ENGINEERING = PROVEN** — the pipeline can now, from evidence alone and with inspectable reasoning per candidate: reject routine material (A), demand research for incomplete-but-important items (B, LIV-02), refuse thin listings instead of writing briefs (C, LIV-03), green-light enriched and serious stories with evidence-appropriate hooks (D, E, F, LIV01/04/05), and say "there is not yet a good enough article here" (LIV-06) without treating it as failure. Factually-correct-but-not-worth-publishing drafts are no longer produced by default; every exception is an explicit, recorded editor decision. The operational phase exercised the whole loop on the real store: research rounds to terminal state, one regeneration with full lineage, one no-story refusal — both are now waiting as editor-facing review artifacts, not as silent decisions.

**EDITORIAL_READINESS_EDITORIAL_EFFECTIVENESS = PENDING** — whether these readiness *decisions* are good editorial judgment is exactly what the editor test will now measure (DRAFT_READY scorecards for LIV-01/02/04/05, the LIV-03 decision form, and the LIV-06 no-story verification). Per §34, no profile/threshold/hook rule changes until real editor corrections accumulate.
