# M4D — Role qualification harness: status report

Status: **ROLE_QUALIFICATION_HARNESS = PROVEN** · **LIVE_ROLE_QUALIFICATION = PENDING**

> Honesty banner: the harness is proven *as engineering* — production-faithful
> prompts, deterministic scoring, safe runner, honest reports. Running it proves
> nothing about any model. No model has been qualified for production, and no
> verdict below may be read as a promotion decision.

## Wiring truth table (pre-frontend gate PART I)

| role    | contract                                                            | wiring               |
|---------|---------------------------------------------------------------------|----------------------|
| story   | production `story_relation.render_prompt` + false-merge metric      | production-faithful  |
| judge   | production `_ENTAIL_JUDGE_PROMPT` + production parser (fact entailment fixture subtype only) | production-faithful |
| angle   | production `_ASSESS_PROMPT` (seven criteria, real semantic statuses) + production parser/validation; fixture includes the 7 M3D shadow-disagreement cases | production-faithful |
| draft   | real `build_prompt()` over frozen EvidencePackets + real style retrieval + `parse_draft_json` + deterministic `audit_claims`/`originality_check`; semantic gate only on explicit request; human-review sheet artifact | production-faithful (style verdict = HUMAN) |
| judge / draft semantic subtype | `generate._semantic_judge_prompt` has no fixture of its own | pending (`draft_semantic = PENDING_NO_FIXTURE`) |
| research| synthetic plumbing fixture only — no production `role="research"` caller exists | `RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED` |
| extract | defined role, no qualification corpus                               | `NOT_EVALUATED`      |
| utility | defined role, no qualification corpus                               | `NOT_EVALUATED`      |

Every report the harness writes carries `wiring`, and the runner reports the
research role's `RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED` explicitly —
a synthetic benchmark is never presented as production qualification.

## What changed in the pre-frontend correctness round (PART I)

- The harness-local duplicated `JUDGE_PROMPT` and tiny `DRAFT_PROMPT` are gone:
  judge/angle/draft now send the same bytes production sends, rendered and
  parsed by production code (`discovery.render_entail_prompt` /
  `parse_entail_answer`, `discovery.render_assess_prompt` / `parse_assess_answer`,
  `prompt.build_prompt`, `generate.parse_draft_json` / `audit_claims` /
  `originality_check`).
- Angle answers are validated by the production seven-criterion parser; the old
  simplified status-only eval prompt is gone. A status-only answer no longer
  counts as valid.
- The angle fixture now carries the seven M3D shadow-disagreement cases from
  `fixtures/evals/jev/transcript_angles_v2.jsonl` (expected label = the
  deterministic assessment, the production-authoritative one; shadow/audit
  labels are metadata only — they are hypotheses, never ground truth).
- The draft fixture carries frozen EvidencePackets; missing style assets fail
  the case before any model call (`EvalAssetsError`), and a human-review sheet
  (`draft_human_review.md`) is generated with blank human fields — Bulgarian
  naturalness / headline quality / Chernomorie fit / editing effort are decided
  by a human, never by another model.
- Paid eval guard (I7): paid candidate routes refuse to run without an explicit
  `--allow-paid` flag (CLI + runner), mirroring `angle_model_ab.py`.

## How to run (after an owner-approved key setup)

```bash
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role judge --limit 1
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role draft
```

Reports land under `var/model_role_eval/` (git-ignored). No live role
qualification was run in the pre-frontend correction round (and none may be
inferred from the hermetic tests).
