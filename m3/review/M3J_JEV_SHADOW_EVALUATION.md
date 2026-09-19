# M3J — Jev Shadow Evaluation — 2026-09-19

Parts B–L of `m3/HARNESS_PROMPT_M3A_STABILIZE_M3J_JEV.md`.

```text
JEV_INTEGRATION        = READY
JEV_CORROBORATION      = NOT_EVALUATED
JEV_GROUNDING          = NOT_EVALUATED
JEV_ANGLE_SIGNALS      = NOT_EVALUATED
JEV_PRODUCTION_AUTHORITY = NONE
EDITORIAL_EFFECTIVENESS  = PENDING
```

## Why no effectiveness verdicts

No `TYPESAFE_API_KEY` is available in this environment and the optional SDK is
not installed, so no live Jev call was made. Per the harness, all integration /
offline work is finished, the effectiveness verdicts are honestly
`NOT_EVALUATED`, and the runner reports `JEV_CAPABILITY_UNAVAILABLE` cleanly:

```text
$ PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all
JEV_CAPABILITY_UNAVAILABLE: typesafe_sdk is not installed (pip install 'editor-assistant[jev]')
...
```

A Jev result is **not** promoted to production from one benchmark run; there is
no production authority to grant.

## Architecture (no authority)

```text
LLM           -> propose / extract / write
Jev           -> narrow typed semantic judgements   (scripts/evals only)
deterministic -> enforce policy and safety
editor        -> final authority
```

Regression test `test_adapter_is_not_wired_into_production_deciders` asserts
`readiness.py`, `angles.py`, `discovery.py` and `cases.py` never reference Jev,
and the adapter imports no decider.

## B — Optional dependency + thin adapter

- `pyproject.toml`: `[project.optional-dependencies] jev = ["typesafe-sdk>=0.6,<0.7"]`
  (not a mandatory runtime dependency).
- `src/editor_assistant/workflow/jev.py`: create the client only when
  configured; submit `state + typed questions`; normalize
  answers/probabilities/confidence/latency/model/usage; map
  missing SDK/key → `JEV_CAPABILITY_UNAVAILABLE` and transport failures →
  `JEV_PROVIDER_ERROR` (API key redacted); never decides editorial status.
- Env: `TYPESAFE_API_KEY`, `JEV_MODEL` (default alias `jev-latest`). The
  effective returned model/version is recorded per result
  (`model_effective`); the alias may move.
- SDK primitives used: `Choice` (fixed option set → full probability
  distribution + confidence). `Noul`/`Score` are supported by the builder.

## C — Frozen fixtures

`fixtures/evals/jev/` (public-source only; no keys, drafts or editor notes):

| File | Rows | Content |
|------|-----:|---------|
| `transcript_angles_v2.jsonl` | 24 | all V2 candidate angles + deterministic assessment + prior LLM-shadow judge + focused-audit conclusion; the **7 disagreements** are identifiable |
| `transcript_fact_grounding_v2.jsonl` | 109 | retained **and** dropped facts with exact support segment text, ids/timestamps, deterministic result, risk flags, procedural status |
| `corroboration_candidates_v2.jsonl` | 16 | claim, opened public-source excerpt, URL/domain, authority, lexical decision, manual label where the audit established one |

Provenance and honesty rules: `fixtures/evals/jev/README.md`. Labels come only
from `m2/review/SHADOW_DISAGREEMENT_ENRICHMENT_AUDIT.md`; angle conclusions are
flagged as hypotheses; unlabeled items stay `null` (never inferred by another
model and called ground truth).

## D–F — The three experiments (typed questions)

- **corroboration** (highest priority): `support_relation`
  (EXACT/PARTIAL/NOT_ADDRESSED/CONTRADICTED), `event_relation`
  (SAME/RELATED/DIFFERENT/UNCLEAR), `procedural_relation`
  (SAME_STAGE/DIFFERENT_STAGE/NOT_STATED/UNCLEAR); state =
  claim, source passage, authority, claim procedural status, source context.
- **grounding**: `overall_support`, `actor_relation`, `number_relation`,
  `negation_relation`, `decision_status_relation`. Jev never repairs/rewrites a
  fact; `extract_facts()` is untouched.
- **angles**: narrow signals only — `development_type`,
  `evidence_completeness`, `procedural_scope`, `affected_party`,
  `current_change`. Jev is never asked "is this publishable?".

Full probability distributions are preserved; no production threshold is set
(Part G) — the project lacks enough independent human labels to calibrate one.

## I — Runner

`scripts/evals/jev_shadow_eval.py`:

```bash
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment corroboration
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all [--limit N] [--summary]
```

Loads frozen fixtures, runs one or all experiments, appends results under the
ignored `var/jev_eval/` and **resumes safely** (already-evaluated cases are
skipped; partial runs continue). It never mutates fixtures, workflow/runtime
state, or drafts, and never drafts an article. Provider errors are recorded
per case and do not abort the run.

## J — Offline tests (+37 across the pass)

`tests/test_jev_adapter.py` (10) and `tests/test_jev_shadow_eval.py` (13),
covering: missing SDK/key → unavailable; typed-question construction; response
normalization; probability/confidence preservation; provider failure mapping +
key redaction; default alias; fixture schema (24/7, retained+dropped, honest
nulls, no secrets/drafts); runner resume/idempotence; no drafting/publishing
path; and the no-authority regression.

## K/L — Gate

- [x] `ruff check src tests scripts` clean
- [x] `ruff format --check src tests scripts` clean
- [x] `PYTHONPATH=src pytest -q` → **512 passed**, offline
- [x] `PYTHONPATH=src python3 scripts/m3a_smoke.py` → **25/25**
- [x] live shadow eval attempted → `JEV_CAPABILITY_UNAVAILABLE` (nothing changed)
- [x] no fixture stored under `var/`; no production state mutated

## Metadata

```text
TypeSafe SDK version       : not installed (optional extra `jev`)
Jev model alias            : jev-latest (default; JEV_MODEL overrides)
Jev effective version      : n/a (no live call)
Experiment fixture counts  : corroboration 16 · grounding 109 · angles 24
Latency / cost             : n/a (no live call)
Prompt text sent by any run: none
```

## STOP

Do not continue into M3B YouTube intake, M3C automatic enrichment, CMS
publishing, LIVE 6–10, rubric/threshold changes, Jev production authority, or
editor-profile learning.
