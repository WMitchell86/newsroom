# Jev shadow-evaluation fixtures (M3J)

Frozen, tracked evaluation corpus for the TypeSafe **Jev** shadow experiments.
Jev has **zero production authority**; these fixtures exist only so the three
shadow experiments are reproducible from a clean clone (the source artifacts
otherwise live under the git-ignored `var/`).

**Privacy:** every row is derived from already-public material — public YouTube
auto-captions (Burgas Municipal Council recordings), public municipal pages, and
public source passages. No API keys, no unpublished drafts, no editor notes.

## Files

| File | Rows | What it freezes |
|------|-----:|-----------------|
| `transcript_angles_v2.jsonl` | 24 | every V2 candidate angle: proposition, supporting facts, deterministic assessment, prior LLM-shadow judge, focused-audit conclusion where one exists |
| `transcript_fact_grounding_v2.jsonl` | 109 | retained **and** dropped extracted facts: claim, exact supporting segment text, segment ids/timestamps, deterministic grounding result, risk flags, procedural status |
| `corroboration_candidates_v2.jsonl` | 16 | lexical corroboration candidates: claim, opened public-source excerpt, URL/domain, authority, lexical decision, manual semantic label where the focused audit established one |

## Provenance (frozen 2026-09-19)

Derived once from `var/transcript_analysis_v2/{*.json,shadow_judge_v2.json,research_enrichment.json}`
and `var/youtube_transcripts/raw/*.bg-orig.srt` (7 recordings). The corroboration
candidates reproduce the deterministic lexical matcher from
`tmp/research_enrichment.py`; the fixtures do **not** introduce a new rule.

`source_excerpt` in `corroboration_candidates_v2.jsonl` is a **relevance window**
(~350 words) selected from the opened page around the claim's significant tokens.
It is *not* the first 500 chars of the page — that earlier head-of-page snapshot
was HTML boilerplate and made the semantic judge see nothing (the 2026-09-19
corroboration run on it was discarded and re-run).

**Do not regenerate these blindly.** Re-running the (scratch) generator against a
changed `var/` would silently move the evaluation baseline. Treat the fixtures as
immutable; add new versions as new files instead.

## Label honesty

* Deterministic results and prior LLM-shadow results are **baselines, not ground
  truth** — `type-safe` means output-schema safety, not factual infallibility.
* `manual_audit_conclusion` / `manual_support_relation` are set only where
  `m2/review/SHADOW_DISAGREEMENT_ENRICHMENT_AUDIT.md` (§3, §5) already
  established a conclusion. Those angle labels are **hypotheses**, flagged with
  `manual_audit_label_is_hypothesis: true`.
* Items the audit did not label stay explicitly `null` — never filled in by
  another model and then called ground truth.
* `model_judge_result` is `null` where the V2 artifacts did not persist a
  per-fact model judge.

## The 7 known angle disagreements

`transcript_angles_v2.jsonl` contains 7 rows whose
`prior_llm_shadow.agreement_with_deterministic` is `false`
(4 judge-more-permissive, 3 judge-stricter); they are all covered by the
hypotheses above.

## Running the evaluation

```bash
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment corroboration
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all
```

Results (ignored) land under `var/jev_eval/`. Without `TYPESAFE_API_KEY` the run
reports `JEV_CAPABILITY_UNAVAILABLE` and changes nothing.
