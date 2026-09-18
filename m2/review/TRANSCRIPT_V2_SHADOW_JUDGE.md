# Transcript V2 Shadow Judge — model vs deterministic assessor (M2S-R3 Part C)

Verdict: **SHADOW_MEASURED — 17/24 full agreement (70.8%); deterministic assessor
remains authoritative; no runtime status changed.**

This was a shadow-only pass (harness): the judge ran blind to the deterministic
verdict, its output lives beside — never inside — the V2 artifacts
(`var/transcript_analysis_v2/shadow_judge_v2.json`), and the persisted V2
records (`candidate_angles[].semantic_status`, `scores`, readiness statuses)
are byte-identical to before. Nothing here re-decides anything.

## 1. Method

- Candidates: all **24** `candidate_angles` from the 7 V2 recordings
  (2 `PUBLISHABLE_ANGLE`, 3 `POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH`,
  19 `NO_PUBLISHABLE_ANGLE`).
- Judge: `discovery._model_assess` verbatim — the production assessor prompt
  (rubric v2, 7 criteria, semantic status + research questions), judge model
  pool, same schema validation. Blindness is structural: the call receives
  only `{title, new_proposition, reason}` + supporting fact texts; no
  deterministic status/total/eligibility reaches the prompt.
- Scoring: full agreement (same semantic status), partial pair
  (`PUBLISHABLE_ANGLE` vs `..._NEEDS_RESEARCH`), veto agreement
  (`NO_PUBLISHABLE_ANGLE` on both sides or neither). Schema-failed or
  unavailable calls would count as `judge_unavailable`, never as disagreement.
- Run: 2026-09-18, 24/24 judged, 0 unavailable.

## 2. Result

```text
full agreement      17/24  (0.708)
partial pair         0/24  (0.000)
veto agreement      17/24  (0.708)
judge unavailable    0/24
```

All 7 disagreements are status flips, not score noise:

| # | video | angle | deterministic | model | direction |
|---|---|---|---|---|---|
| 1 | 7k-FZXrcmq8 | concessions_funding | NO_PUBLISHABLE_ANGLE | PUBLISHABLE_ANGLE | model more permissive |
| 2 | 8h51zs_NUbw | social_aid | NO_PUBLISHABLE_ANGLE | NEEDS_RESEARCH | model more permissive |
| 3 | CIs4AIKuOiw | budget_execution_2026 | NEEDS_RESEARCH | NO_PUBLISHABLE_ANGLE | model stricter |
| 4 | YsqD4T0D850 | financial_management_meeting | NEEDS_RESEARCH | NO_PUBLISHABLE_ANGLE | model stricter |
| 5 | YsqD4T0D850 | midyear_budget_2026 | NEEDS_RESEARCH | NO_PUBLISHABLE_ANGLE | model stricter |
| 6 | xvsdi_j7s5c | school_funding | NO_PUBLISHABLE_ANGLE | PUBLISHABLE_ANGLE | model more permissive |
| 7 | xvsdi_j7s5c | museum_funding_refusal | NO_PUBLISHABLE_ANGLE | PUBLISHABLE_ANGLE | model more permissive |

## 3. Reading the disagreements

The disagreements cluster exactly on the **routine-vs-concrete boundary** the
M2S semantic audit named as the hardest judgment, and they cut both ways:

- **Model more permissive (4):** on `concessions_funding`, `school_funding`,
  `museum_funding_refusal` the model accepts a concrete administrative fact
  (a funding mechanism, a funding refusal, an under-capacity report) as
  news-worthy even where the rubric-v2 requirement — *novelty expressible from
  the supporting facts* — is not met; on `social_aid` it reasonably asks for
  the missing parameters instead of vetoing outright.
- **Model stricter (3):** on all three `NEEDS_RESEARCH` candidates
  (`budget_execution_2026`, `financial_management_meeting`,
  `midyear_budget_2026`) the model applies the routine-procedural veto the
  deterministic path reserves for `wrapper_only` signals — arguably the more
  honest verdict for mid-year cash-execution reporting.

Tension to note: the model is simultaneously more permissive on small concrete
stories and stricter on routine reports. That is precisely the human-editor
disagreement pattern, and it is why the deterministic rubric stays authoritative
(and auditable) while the model judge stays shadow.

## 4. Explicit non-changes

- `article_readiness_status` totals unchanged: 2 DRAFT_READY / 2 RESEARCH_MORE /
  3 NO_PUBLISHABLE_ANGLE.
- No threshold, profile, prompt, or routing change was made as a result.
- No artifact under `var/transcript_analysis_v2/` other than
  `shadow_judge_v2.json` (this report's data) was written or modified.
