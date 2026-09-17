# M2.3B Report — Corrective Regeneration Experiment (Gemini)

Date: 2026-09-15. Status: complete. Awaiting editor review.

## Goal

Resolve the `DRAFT_EXPERIMENT_NOT_PROVEN` verdict (3/10 factual-gate failures from
the M2.3 baseline review) by regenerating all 15 experiment drafts on Gemini with
provider-aware lineage, quota-aware model rotation, and a semantic judge, and by
re-measuring the baseline with the same judge.

## What changed vs M2.3

| | M2.3 baseline | M2.3B corrective |
|---|---|---|
| Provider / model | OpenRouter, `openai/gpt-oss-20b` | Gemini: 3.5/3.7/3.8-flash, 3-flash-preview |
| Prompt version | `m2.3-prompt-1` | `m2.3b-prompt-1` (same sections, hardening vs leakage) |
| Factual gate | lexical token-overlap audit only | lexical audit **+ semantic judge** (LLM entailment, scoped facts) |
| Thinking tokens | n/a | disabled (`thinkingConfig.thinkingBudget=0`) — they were starving output |
| Lineage | model only | model, provider, prompt_trimmed_chars, regenerated_attempt |

## Results — primary drafts (10)

| KEY | 20B baseline (semantic) | M2.3B Gemini (semantic) | lexical auditU | Gemini model |
|---|---|---|---|---|
| EV-01 | FAIL | **PASS** | 0 | gemini-3.5-flash |
| EV-02 | FAIL | **PASS** | 0 | gemini-3.5-flash |
| EV-03 | PASS | PASS | 3* | gemini-3.5-flash |
| EV-04 | FAIL | **PASS** | 0 | gemini-3.5-flash |
| EV-05 | PASS | PASS | 0 | gemini-3.5-flash |
| EV-06 | FAIL | **PASS** | 0 | gemini-3.7-flash |
| EV-07 | FAIL | **PASS** (after 1 regen) | 2* | gemini-3-flash-preview |
| EV-08 | PASS | PASS | 0 | gemini-3.7-flash |
| EV-09 | PASS | PASS | 1* | gemini-3.7-flash |
| EV-10 | FAIL | **PASS** | 2* | gemini-3.8-flash |

**Baseline: 4/10 semantic-pass → M2.3B Gemini: 10/10 semantic-pass.**

\* Remaining lexical `auditU` flags are formatting artifacts (dot-separated times
"17.00 ч." vs "17:00 ч.", spelled-out ordinals) — the semantic judge confirms all
are entailed by the evidence. Zero archive-leak hits in all 15 drafts.

## Results — extras (5, blind/mode)

| KEY | semantic | lexical auditU | leaks | Gemini model |
|---|---|---|---|---|
| EV-01B | PASS | 0 | 0 | gemini-3.7-flash |
| EV-05B | PASS | 0 | 0 | gemini-3.8-flash |
| EV-04B | PASS | 0 | 0 | gemini-3-flash-preview |
| EV-02B | **FAIL** (1 connective claim) | 0 | 0 | gemini-3-flash-preview |
| EV-10B | PASS | 4* | 0 | gemini-3-flash-preview |

**All 15: 14/15 semantic-pass** (vs. the baseline's 6/10 primary failures).
The single remaining flag (EV-02B) is one connective/interpretive sentence —
soft-claim class, no invented names/numbers/dates/quotes.

## Engineering fixes that made this work

1. **Thinking-token starvation**: Gemini 3.x spent 1,921 "thinking" tokens vs 75
   visible tokens under `maxOutputTokens=2000` — JSON contracts were truncated
   and every parse failed. Fix: `thinkingConfig.thinkingBudget=0` (env-overridable
   via `GEMINI_THINKING_BUDGET`) + `max_tokens=8192`.
2. **Thought-part leakage**: responses concatenated internal reasoning into the
   draft. Fix: skip parts with `thought: true` (also exposes `finish_reason`).
3. **Section-aware prompt trim**: the old 6k tail-trim deleted `TASK`/`FORBIDDEN`
   (which carry the JSON contract) because `STYLE_EXAMPLES` precedes them in the
   prompt. New trimmer is section-aware (30k cap, only shortens examples body).
4. **Quota semantics**: free-tier daily buckets are per-model. 429 bodies saying
   "rate limit" (RPM pressure) must be retried, while "exceeded your current
   quota" (daily bucket spent) must rotate models — the original code conflated
   both and crashed the batch. `gemini-3-flash-preview` rescued the batch when
   all three primary Flash buckets were spent.
5. **Judge pool hygiene**: `gemini-3.5-flash-lite` 400s on `thinkingConfig`
   (`INVALID_ARGUMENT`) — removed from `JUDGE_MODEL_POOL` so judge calls don't
   burn a wasted request per call.

## Packet defect found (EV-07)

`source_headline` ("...от 11 държави") contradicts fact EV-07-f03 (which
enumerates 12 countries). First-pass Gemini drafts copied the headline's wrong
count — flagged as `invented_number` by the judge. One corrective regeneration
(attempt=1, recorded in lineage) resolved it. **Recommend fixing the packet** so
future drafts can't inherit the headline's error.

## Artifacts

- `var/draft_experiment/drafts.jsonl` — 15 Gemini records, full lineage
- `var/draft_experiment/audits.json` — refreshed lexical audits (same schema)
- `var/draft_experiment/blind_map.json` — resealed against new draft_ids
- `/tmp/m23b_drafts_20b_legacy.jsonl` — quarantined 20B drafts (never reused)
- `/tmp/m23b_20b_semantic.json` — baseline re-measured with the same judge
- `/tmp/m23b_drafts.json` — raw runner output with audit + semantic payloads

## Verdict (proposed)

`GROUNDING_PROVEN_STYLE_PENDING` — the factual half that failed under the 20B
baseline (6/10 semantic failures) is now **10/10 primary / 14/15 overall
semantic-pass with zero leaks** under Gemini + the semantic judge. The style
half remains the editor's call via the resealed blind pairs in `review.md`.
Editor accepted the factual gate on 2026-09-15 — factual half is FROZEN.

## Recommended next step

Editor scores `review.md` blind pairs, then confirms or amends the verdict.
If EV-02B's connective-claim class matters, tighten the prompt's "no attitude
not in evidence" wording (M2.3 backlog item D) — do NOT reopen M2.1; the 20B
drafts stay quarantined.

## Post-acceptance housekeeping (2026-09-15, editor-approved)

Editor accepted the factual gate as-is: EV-02B stays open as a Good-Enough
backlog item (soft connective phrase; no invented names/numbers/dates/quotes/
relationships) and the factual half is frozen. One housekeeping fix was
required before freezing — the EV-07 EvidencePacket contradiction:

- Defect: `source_headline` says "11 държави"; fact `EV-07-f03` enumerates
  12 countries. The headline is an editorial surface, NOT evidence.
- Fix (no draft rerun): new `annotate_headline_number_conflicts()` in
  `evidence.py` appends an `ANNOTATION:` entry to `packet["unknowns"]`
  (rendered into the prompt via CURRENT_UNKNOWNS) for headline numbers that
  no fact/quote/number confirms; boundary-safe token matching (a "60" is not
  confirmed by "160"); idempotent (re-annotation is a no-op).
- Runtime rules: annotate at `write_packets` freeze time AND at
  `read_packets` load time (legacy packets are fixed in memory, file
  untouched on disk).
- Version: all 15 packets bumped to `packet_version: "1.1"` in
  `var/draft_experiment/evidence_packets.jsonl`; `validate_packet` passes.
- No lexical regression: fresh `audit_claims` on the EV-07 primary draft is
  identical to its frozen generation audit (unsupported/contradicted/
  leak_hits) — the annotation never enters `packet_claims_text`.
- Record: `m2/review/M2_3B_EV07_PACKET_RESOLUTION.json`; contract tests:
  `tests/test_packet_annotations.py` (7 tests).

---

## Style gate — CLOSED (editor verdict, 2026-09-16)

The editor reviewed the rendered artifact without opening `blind_map.json`
(protocol kept) and returned a qualitative PASS WITH NOTES. During review an
artifact-integrity defect was found: the rebuilt `review.md` rendered
Draft A = primary draft in every pair, while `blind_map.json` maps the
primary to label B for 3 of 5 pairs. Verified programmatically — renderer
pattern is A=primary,B=variant for all pairs; map contradicts the render on
exactly **EV-01, EV-04, EV-02** (EV-05, EV-10 consistent). Root cause: the
rebuild renderer ordered texts fixed (primary, variant) and ignored the
sealed shuffle. Consequence: the sealed experiment cannot yield a valid
blind-accuracy score; the artifact is **RETIRED UNSCORED** and no re-run is
made (editor decision: no further synthetic A/B cycles). The style
assessments stand on the editor's qualitative read of the rendered pairs.

Final verdict:

```text
M2.3 — PASS WITH NOTES
GROUNDING_PROVEN              (factual gate frozen, packets v1.1)
HOUSE_DRAFTING_PROVEN         (VOICE_HOUSE = default production voice)
MODE_COMPOSITION_GOOD_ENOUGH  (STANDARD/BRIEF/EVENT_PREVIEW/CULTURE_FEATURE
                               kept; mode is an editorial instruction, not a
                               classifier target)
DESISLAVA_VOICE_PROVISIONAL   (opt-in/experimental; profile registry already
                               carries PROVISIONAL, n=12 — unchanged)
PROCEED_TO_EDITORIAL_WORKFLOW
```

Next milestone: real editorial workflow prototype — idea/source → evidence →
VOICE_HOUSE default (+ editor-selected or suggested MODE) → grounded draft →
editor edit. Track: accepted headline, factual corrections, paragraphs
removed/added, tone edits, mode changed, time saved, published after
light/moderate/heavy edit. No auto-publishing; no fine-tuning (M2.10 gate
stays closed); no further lab blind cycles; do not reopen M2.2/M2.3 unless
real editorial use exposes a repeated failure pattern.

Artifact-integrity record: `m2/review/M2_3B_BLIND_ARTIFACT_RETIREMENT.json`;
`review.md` carries a retirement banner; `blind_map.json` is flagged
`retired_for_scoring: true`.

---

CLOSED — editor verdict recorded 2026-09-16. Next: editorial workflow.
