# Transcript Discovery V2 Report — V1 vs V2 semantic comparison (M2S Track T)

Verdict: **TRANSCRIPT_DISCOVERY_V2 = SEMANTICALLY DIFFERENTIATED, NOT YET PROVEN.**

V2 (gap A-H mechanisms) changes *what the pipeline can decide*, not merely how it labels:
the same 7 raw SRTs that V1 compressed into 16 topics and 7/7 `ANGLE_SELECTED` now produce
56 topics (49 agenda-bound), 93 grounded facts, 16 rejected facts, 24 candidates and — for
the first time — **three different angle statuses and three different real readiness
statuses**. The result is *differentiated*, not *proven*, because model-assisted extraction
quality still needs human editorial inspection before any editor involvement, and because
the assessor pass in this run was the deterministic rubric-v2 implementation (the separate
model judge is wired and tested but not required).

This is an **engineering/discovery benchmark only** — no drafting was run, no article was
generated, and the readiness totals below are not editorial-quality proof (harness §19).

Artifacts: `var/transcript_analysis_v2/` (7 JSON + `MANUAL_AUDIT_SAMPLE_V2.md`).
V1 preserved unchanged in `var/transcript_analysis/` and snapshotted to
`var/transcript_analysis_v1/` for comparison (harness §2).

## 1. Mechanisms fixed (V2)

| gap | V1 behavior | V2 mechanism | artifact evidence |
|---|---|---|---|
| A | agenda cue search only near a merged span's start (8 items → 2 topics) | boundary-first segmentation: cues searched inside continuously overlapping captions; deterministic-boundary flag per topic | `topics[].deterministic_boundary`, 49/56 true |
| B | fact "ID exists" treated as entailed | entailment gate with coverage floor plus number/actor/negation/decision checks; losers dropped, never repaired | `dropped_facts[].grounding_failures`, 16 rejects |
| C | proposer could self-label `PUBLISHABLE_ANGLE` | proposal/assessment split; proposer semantic fields never authoritative | `proposals` vs `candidate_angles`; `assessment_diagnostics.assessor` |
| D | explicit proposer status bypassed validation | assessor authors `semantic_status`/`semantic_reason`; rubric vocabulary and threshold frozen | `candidate_angles[].semantic_status` |
| E | batch scoring did not implement rubric-v2 semantics | deterministic evidence-surface scorer for all 7 criteria plus a separate assessor pass (model judge optional, separate call) | `candidate_angles[].scores`, `assessment_diagnostics.assessor[]` |
| F | angle-gate status was persisted as "readiness" | real `readiness.assess_readiness()` on the selected-angle packet; two separate persisted fields | `angle_assessment_status` vs `article_readiness_status` |
| G | committee action promotable to council/municipality | procedural status per fact plus title/proposition scope validator before eligibility | `procedural_status`, `assessment_diagnostics.scope_downgrades` |
| H | repeated routine agenda items over-selected | cross-recording fingerprint index; a repeated item cannot gain novelty from another committee vote | `repeated_agenda`, `batch_repeated_context()` |

Two source-level corrections were required for F to work at all (see §10).

## 2. Pipeline actually executed

```text
raw SRT → TranscriptDocument (ms provenance, AUTO_CAPTION)
→ boundary-first topics (deterministic agenda cues + neutral fallback)
→ per-topic model facts (judge pool) → entailment gate (drop, never repair)
→ independent assessment pass (7 criteria + semantic veto)
→ angles.assess_angles (rubric v2, min_candidates=1 explicit)
→ selected-angle packet → readiness.assess_readiness() (real orchestrator, no drafting)
```

## 3. V1 vs V2 per recording

| video | V1 topics | V2 topics (agenda-bound) | V1 facts | V2 facts | V2 rejects | V1 cands | V2 cands (eligible) | V2 angle status | V2 readiness |
|---|---|---|---|---|---|---|---|---|---|
| 7k-FZXrcmq8 | 1 | 8 (7) | 3 | 14 | 2 | 3 | 3 (1) | ANGLE_SELECTED | DRAFT_READY |
| 8h51zs_NUbw | 3 | 4 (3) | 7 | 8 | 0 | 4 | 4 (0) | NO_PUBLISHABLE_ANGLE | NO_PUBLISHABLE_ANGLE |
| CIs4AIKuOiw | 4 | 7 (6) | 13 | 9 | 1 | 3 | 3 (0) | POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH | RESEARCH_MORE |
| HB1avBfeiRw | 2 | 12 (11) | 6 | 20 | 1 | 3 | 4 (0) | NO_PUBLISHABLE_ANGLE | NO_PUBLISHABLE_ANGLE |
| YsqD4T0D850 | 2 | 5 (4) | 6 | 6 | 2 | 3 | 3 (0) | POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH | RESEARCH_MORE |
| b13U-N_Vk9c | 3 | 12 (11) | 10 | 21 | 4 | 3 | 3 (1) | ANGLE_SELECTED | DRAFT_READY |
| xvsdi_j7s5c | 1 | 8 (7) | 3 | 15 | 6 | 2 | 4 (0) | NO_PUBLISHABLE_ANGLE | NO_PUBLISHABLE_ANGLE |
| **totals** | **16** | **56 (49)** | **48** | **93** | **16** | **21** | **24 (2)** | — | — |

Agenda-boundary recovery is the headline: V1 recovered 16 topics from 7 recordings (1–4
each); V2 recovers 56 (4–12), 49 with a deterministic agenda cue. Later agenda items are
therefore independently fact-extracted now — 7k reaches its 5th point and HB1 its 6th point,
both absent from V1's topic set. V2 extracts fewer facts than V1 in exactly one recording
(CIs4AIKuOiw, 13 → 9, which lost 1 to the gate); the other 6 gained facts
(3→14, 6→20, 3→15, 10→21, 6→8, 6→6).

Fact-quality surface (V2, 93 facts): 93/93 `corroboration_required` under AUTO_CAPTION rules;
entailment coverage min 0.40 / mean 0.86; procedural status
`UNKNOWN 66 / PROPOSED 21 / COMMITTEE_SUPPORTED 5 / DISCUSSED 1`; risk flags
`exact_quote 51, personal_or_org_name 39, material_number 22, legal_institutional_status 3,
negation_sensitive 2, final_decision 2`.

Grounding rejects (16) by reason: `unsupported_paraphrase 10`, `wrong_decision_status 6`,
`wrong_number 3`. Examples: "Отрицателното бюджетно салдо … се дължи на указания на
Министерс[твото]" → `wrong_number: 2025 not in support`; "При гласуването на първата точка
… четири или пет гласа „за“" → `wrong_decision_status: no decision stem in support`;
"Предложението беше гласувано и прието единодушно." → `unsupported_paraphrase: coverage
0.25 < 0.40`. None were repaired or guessed.

## 4. Angle status totals vs REAL readiness totals (gaps D/F, §13, §16)

```text
angle_assessment_status (V2, 7):  ANGLE_SELECTED 2 | POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH 2 | NO_PUBLISHABLE_ANGLE 3
article_readiness_status (V2, 7): DRAFT_READY 2     | RESEARCH_MORE 2                            | NO_PUBLISHABLE_ANGLE 3

V1 (7):                           ANGLE_SELECTED 7  (no readiness orchestrator ever invoked)
```

V1's uniform `7/7 ANGLE_SELECTED` was the symptom the audit named: the persisted "readiness"
*was* the angle-gate status, so the pipeline could never say "there is no story here" or
"this needs research first". V2 separates the layers and, on this batch, refuses a story in 3
recordings and demands research in 2. Readiness uses the frozen M2R vocabulary; all 7
recordings ran the real orchestrator (mode `MODE_STANDARD_NEWS`; sufficiency
`EVIDENCE_SUFFICIENT` for the two `DRAFT_READY` cases). 2 of 24 candidates cleared the frozen
rubric threshold (total ≥ 5 with current local novelty) — the low eligibility rate is the
expected consequence of replacing "sounds important" with "there is a concrete new
development".

## 5. Routine / repeated-agenda flags (gap H, §11, §16)

Routine vetoes fired on CIs4AIKuOiw for `budget_report_2025` and `commission_voting_process`
("рутинен процедурен материал без конкретна новост в опората") — V1 had selected that same
annual-report material as its main story (`angle_001`). Cross-recording repeated-agenda
fingerprints flagged 3 facts: `8h51zs_NUbw-f002`, `HB1avBfeiRw-f003`, `YsqD4T0D850-f001`
(budget/agenda items also present in other recordings). Flagged candidates lose a point on
`concrete_change`/`burgas_novelty` and cannot reach eligibility on repetition alone. Honest
reading: the suppression is exercised and test-covered, but only 3 facts were flagged on this
batch, so the mechanism is demonstrated rather than stress-tested.

## 6. Procedural scope and institutional overclaim rejects (gap G, §10)

`scope_downgrades` = 0 across all 7 recordings: no candidate in this batch tried to promote a
committee-stage action to a council/municipality decision. That is a *pass*, but a pass by
absence, so the contract is carried by the tests instead
(`test_v2_committee_supported_is_not_council_adopted`) plus the procedural status recorded on
every fact (`COMMITTEE_SUPPORTED 5 / PROPOSED 21 / DISCUSSED 1 / UNKNOWN 66`). The `UNKNOWN`
share (71%) is a real limitation: for most facts the transcript does not state the procedural
stage, and V2 records that honestly instead of assuming a stage.

## 7. NEEDS_RESEARCH questions (§16)

Only where the angle gate reached `POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH` (CIs4AIKuOiw,
YsqD4T0D850) were concrete, source-targeted questions produced, e.g.:

- CIs4AIKuOiw: "Какви са тенденциите в приходите на общината за първите шест месеца на
  2026 г.?" / "Как се движи изпълнението на бюджета спрямо заложените цели?"
- YsqD4T0D850: the specific questions raised by the responsible deputy mayor about the
  mid-year cash execution of revenue and expenditure.

These live in `missing_research` and are the only recordings with a non-empty list — the
other 5 did not invent questions for stories they do not have.

## 8. Per-recording strongest and rejected candidates (§16)

| video | strongest candidate (selected or best) | rejected / no-story candidate |
|---|---|---|
| 7k-FZXrcmq8 | **`budget_2026` (total 6, SELECTED)** — "Комисията одобри финансовата рамка за 2026 г. с мнозинство от 5 гласа „за“ и двама въздържали се…" (facts 00:04:09 / 00:05:57 / 00:06:40) | `concessions_funding` (total 0) |
| b13U-N_Vk9c | **`budget_2026_uncertainty` (total 4, SELECTED)** — "внесеният проект за бюджет не е окончателен и ще се наложи нов такъв след 2-3 месеца" (facts 00:14:04 / 00:16:53 / 00:22:23) | `municipal_projects_funding` (0), `budget_priorities_2026` (1) |
| 8h51zs_NUbw | none eligible (best `budget_2026`, total 3) | `financial_reporting` — routine procedural material |
| CIs4AIKuOiw | none eligible (best `budget_execution_2026`, total 3, NEEDS_RESEARCH) | `budget_report_2025`, `commission_voting_process` — routine vetoes |
| HB1avBfeiRw | none eligible (best `budget_priorities_2026`, total 1) | `pediatric_hospital_expansion`, `forensic_medicine_upgrades`, `health_innovation_funding` (0–1) |
| YsqD4T0D850 | none eligible (best `midyear_budget_2026`, total 3, NEEDS_RESEARCH) | `budget_report_2025` (1) |
| xvsdi_j7s5c | none eligible (best `school_funding`, total 2) | `museum_funding_refusal`, `budget_report_2025`, `budget_2026` (0–1) |

V1 selected a budget-flavoured angle in 6 of 7 recordings with reasons such as "Бюджетът е
най-важният финансов документ на общината" — i.e. importance, not novelty. The sharpest
V1→V2 difference is b13U-N_Vk9c: V1 selected `municipal_property_program_2026`, V2 selected
the concrete, checkable development that the budget *is not final*.

## 9. §17 semantic regression probes (V1 vs V2, manual inspection)

| probe class | V1 hits | V2 hits | example (V2) |
|---|---|---|---|
| late agenda items (≥4th point) | 2 | 4 | 7k "Пета точка … програма за управление и разпореждане" @ 00:03:36; HB1 "Точка шеста е писмо от г-н Михаил Нев" @ 00:00:28 |
| service/infrastructure creation | 0 | 3 | HB1 "предложения за телемедицина, иновации и средства за реновиране на центъра за психично здраве" @ 00:04:12; 7k museum-exposition repair letter @ 00:07:36 |
| education enrollment / under-capacity | 0 | 3 | xvsdi "осигуряване на допълнителни средства за учебния процес…" (school parallel classes below the minimum) @ 00:00:50 |
| specific new numbers / scale | 4 | 6 | xvsdi "регистрирани пет гласа „за“ и двама „въздържали се“" @ 00:16:23; b13 "изпълнен на 92%" |
| unusual budget timing / context | 0 | 3 | b13: the *selected* proposition — budget not final, new one needed in 2–3 months |
| culture / event statements needing verification | 2 | 4 | xvsdi initiative committee „Памет“ letter re museum premises @ 00:16:40; 7k "Бюджетът за култура е балансиран" |

V1's topic compression is the direct cause of the first three rows: with 1–4 topics per
recording, material in the 5th/6th agenda point and in smaller follow-up items was never
independently extracted. These are inspection categories, not acceptance values.

## 10. Source changes in this pass

1. `src/editor_assistant/workflow/angles.py::check_angle_gate` — re-verification now honours
the *recorded* `min_candidates` floor (`assessment["min_candidates"]`, persisted only when it
differs from the pilot default 3). Previously the gate re-ran `assess_angles` under the strict
3-candidate pilot floor, so every M2S assessment with the explicit 1–2 candidate relaxation
was re-judged against a floor it could not meet and `readiness.assess_readiness()` could
never run for it (gap F unfixable in practice). Scores, grounding and semantic viability are
still fully recomputed; a missing or absurd floor fails closed (default 3; `min_candidates`
outside 1–3 raises `AngleError`).
2. `src/editor_assistant/workflow/discovery.py` — `extract_facts` no longer reports a
swallowed model failure as "0 facts": every zero-yield topic is recorded on
`extract_facts.skipped_topics` with a reason (`MODEL_CALL_FAILED`, `NO_JSON`, `INVALID_JSON`,
`EMPTY_MODEL_OUTPUT`, `EMPTY_TOPIC_TEXT`). The batch persists them as
`fact_extraction_skips` and defers retryable failures (bounded, 3 attempts) instead of
permanently losing a topic. On this run the mechanism paid off immediately: an `HTTPError` on
HB1avBfeiRw topic 1 was deferred and that topic extracted successfully on a later invocation,
and 3 topics are honestly recorded as zero-fact (`EMPTY_MODEL_OUTPUT`) instead of being
indistinguishable from a quota outage.
3. Tests: added `test_v2_relaxed_angle_floor_survives_gate_reverification` and
`test_v2_zero_fact_topics_are_attributed_not_silently_empty`, and rewrote
`test_v2_readiness_orchestrator_invoked_angle_status_is_not_readiness` to run the real
single-candidate path — its previous version had to fabricate two padding candidates to
satisfy the strict floor, which the harness explicitly forbids.

## 11. Wording truthfulness (§21)

```text
fact references existing segment IDs   ≠   fact semantically entailed by those segments
```

Evidence: `supporting_segment_ids` + `entailment_coverage` + `fact_grounding_status=GROUNDED`,
and `dropped_facts[].grounding_failures` for the 16 cases where the ID binding held but the
text did not entail. The V1 report's "timestamp provenance coverage 100%" claim described only
the former.

```text
an angle was selected   ≠   article is ready
```

Evidence: two separate persisted fields, `angle_assessment_status` and
`article_readiness_status`; `ANGLE_SELECTED` is never reported as a readiness result.

```text
committee supported a proposal   ≠   council/municipality adopted it
```

Evidence: per-fact `procedural_status` plus the scope validator before eligibility.

## 12. Verification

```text
PYTHONPATH=src python3 -m pytest -q   → 370 passed
ruff check src tests                  → All checks passed
ruff format --check src tests         → 78 files already formatted
V2 batch                              → 7/7 artifacts, 0 drafting calls
```

## 13. Limitations (not hidden)

- The assessor pass in this run was the deterministic rubric-v2 implementation. The separate
model judge (`_ASSESS_PROMPT`, a distinct call from the proposal call) is implemented and
tested but was not used for the 7 persisted artifacts, so `semantic_reason` strings are
rule-authored. Switching it on is a one-flag change.
- 3 topics yielded zero facts (`EMPTY_MODEL_OUTPUT`) and 3 recordings have facts for only part
of their agenda; the skips are recorded, not hidden.
- 71% of facts carry `procedural_status=UNKNOWN`: transcripts usually do not state the stage
and the pipeline refuses to guess it.
- Eligibility is strict (2/24 candidates). Whether that rejects too much is an editorial
judgment this benchmark cannot make.
- `ANGLE_SELECTED` in 2 recordings means the gate found a viable candidate — not that an
editor would publish it, and no fact-checking or drafting followed.

## 14. Manual audit artifact coverage (§18)

`var/transcript_analysis_v2/MANUAL_AUDIT_SAMPLE_V2.md` shows, per recording: discoverable
title (the transcript-derived topic labels and recording id — no committee name is invented),
topic boundaries with clock ranges, candidate proposition, supporting facts with exact
`[start–end]` clocks, `procedural_status`, ASR risk flags and entailment coverage, angle
assessment with at least one rejected/routine candidate and its reason, the real readiness
status plus mode and reason, zero-fact topics with reasons, and research questions where they
exist.
