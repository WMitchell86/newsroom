# M3J — Jev Shadow Evaluation — 2026-09-19

Parts B–L of `m3/HARNESS_PROMPT_M3A_STABILIZE_M3J_JEV.md`, now with a **live**
run against TypeSafe Jev.

```text
JEV_INTEGRATION          = PROVEN           (149/149 calls, stable SDK, probabilities, resume, 0 errors)
JEV_GROUNDING            = PROMISING_STRONG (corrects deterministic false negatives)
JEV_ANGLE_SEMANTICS      = PROMISING        (CONCRETE_ACTION vs ROUTINE_PROCESS boundary)
JEV_CORROBORATION        = NOT_SUITABLE_AS_STANDALONE_VERIFIER
JEV_PRODUCTION_AUTHORITY = NONE
EDITORIAL_EFFECTIVENESS  = PENDING
```

`JEV_INTEGRATION = PROVEN` means the integration is proven, **not** that the
model is proven for production.

No production authority is granted from one benchmark run. No rubric, threshold,
routing or drafting behaviour changed. All results are shadow artifacts under
the ignored `var/jev_eval/`.

## Architecture (no authority)

```text
LLM           -> propose / extract / write
Jev           -> narrow typed semantic judgements   (scripts/evals only)
deterministic -> enforce policy and safety
editor        -> final authority
```

`test_adapter_is_not_wired_into_production_deciders` proves `readiness.py`,
`angles.py`, `discovery.py` and `cases.py` never reference Jev.

## B — Optional dependency + thin adapter

- `pyproject.toml`: `[project.optional-dependencies] jev = ["typesafe-sdk>=0.6,<0.7"]`.
- `src/editor_assistant/workflow/jev.py`: client created only when configured;
  submits `state + typed questions` via `TypeSafeClient.system_one`; normalizes
  answers / probabilities / confidence / latency / effective model / token usage
  to **plain JSON** (msgspec structs are flattened, stdlib-only); missing
  SDK/key → `JEV_CAPABILITY_UNAVAILABLE`, transport failure → `JEV_PROVIDER_ERROR`
  with the API key redacted. It never decides editorial status.
- Env: `TYPESAFE_API_KEY`, `JEV_MODEL` (default alias `jev-latest`).

## C — Frozen fixtures

`fixtures/evals/jev/` (public-source only):

| File | Rows | Content |
|------|-----:|---------|
| `transcript_angles_v2.jsonl` | 24 | all V2 candidate angles + deterministic assessment + prior LLM-shadow judge + focused-audit conclusion; the **7 disagreements** are identifiable |
| `transcript_fact_grounding_v2.jsonl` | 109 | retained **and** dropped facts with exact support segment text, ids/timestamps, deterministic result, risk flags, procedural status |
| `corroboration_candidates_v2.jsonl` | 16 | claim, opened public-source passage, URL/domain, authority, lexical decision, manual label where the audit established one (8 labeled) |

**Fixture fix made during this pass:** the first corroboration run used the raw
`text[:500]` head of each opened page, which is HTML boilerplate — Jev correctly
returned `NOT_ADDRESSED` for everything. The fixture now stores a **relevance
window** (~350 words) around the claim's significant tokens, so the judge sees
the actual evidence region. The corroboration results below are from the fixed
fixture; the earlier run was discarded.

## D–F — The three experiments (typed questions)

`corroboration`: `support_relation` / `event_relation` / `procedural_relation`.
`grounding`: `overall_support` / `actor_relation` / `number_relation` /
`negation_relation` / `decision_status_relation` (Jev never repairs a fact;
`extract_facts()` untouched).
`angles`: `development_type` / `evidence_completeness` / `procedural_scope` /
`affected_party` / `current_change` — never "is this publishable?".

Full probability distributions and confidence are stored; **no production
threshold is set** (Part G).

## Live results (TypeSafe Jev)

`PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment <name>`

| Experiment | Cases | Errors | Latency avg / max | Input / output tokens |
|------------|------:|-------:|-------------------|----------------------|
| corroboration | 16 | 0 | 648 ms / 917 ms | 54,316 / 2,702 |
| grounding | 109 | 0 | 658 ms / 1,623 ms | 76,859 / 30,621 |
| angles | 24 | 0 | 742 ms / 1,898 ms | 43,450 / 5,762 |

All 149 calls succeeded; effective model **`jev-1.13.0`** (alias `jev-latest`).

### Experiment A — corroboration: NOT_PROMISING

Distribution (16): `NOT_ADDRESSED` 8 · `PARTIAL_SUPPORT` 5 · `EXACT_SUPPORT` 3.

On the 8 manual-labeled rows: **2 exact matches**, 3 “support more permissive
than the conservative audit” (PARTIAL→EXACT on official pages), and **3 false
positives** (manual `NOT_ADDRESSED` but Jev returned support) — including the
known lexical false positive `YsqD4T0D850-f002` (attendance) and the two
`www.burgas.bg` global-overlap pages. The two most confident false positives
(0.82, 0.55) would not be filtered by a confidence gate; the f002 false positive
was low-confidence (0.41).

Conclusion: on this deliberately-hard sample Jev did **not** cleanly fix
`candidate locator ≠ corroboration`; it traded lexical false positives for its
own over-crediting of official/overlapping pages. Probabilities still carry
signal (the weakest negatives sit near 0.5), but corroboration is not a
production candidate on this evidence.

### Experiment B — grounding: PROMISING

* Retained facts (deterministic `GROUNDED`, n=93): Jev `EXACT_SUPPORT` 87 ·
  `PARTIAL_SUPPORT` 5 · `NOT_SUPPORTED` 1 — strong agreement with the gate.
* Dropped facts (deterministic `DROPPED_UNGROUNDED`, n=16): Jev `EXACT_SUPPORT`
  14 · `PARTIAL_SUPPORT` 2.

The striking result is the **dropped** set: manual inspection shows Jev is
mostly **right** where the deterministic lexical gate was wrong —
`«Пет за…»` vs `«пет гласа „за“»` (short-number morphology),
`«бюджет 26 година»` vs `«бюджет 2026»` (abbreviated year), and
decision-status phrasing. These are deterministic **false negatives**, not Jev
false accepts.

One retained fact (`xvsdi_j7s5c-f007`) was rejected by Jev — adjudicated below.
Conclusion: Jev is a promising shadow of the expensive borderline LLM judge and
a useful second opinion on the number/morphology/decision-status cases the
lexical gate mishandles. Still no authority.

### Experiment C — angle signals: PROMISING

`development_type` distribution (24): `ROUTINE_PROCESS` 12 · `CONCRETE_ACTION`
10 · `STATIC_BACKGROUND` 1 · `UNCLEAR` 1.

On the **7 known disagreements**, Jev's `development_type` aligns with the
focused-audit hypothesis in **6/7**:

| case | manual hypothesis | Jev development_type |
|------|-------------------|----------------------|
| social_aid | NEEDS_RESEARCH | CONCRETE_ACTION ✓ |
| school_funding | NEEDS_RESEARCH | CONCRETE_ACTION ✓ (0.81) |
| museum_funding_refusal | NEEDS_RESEARCH | CONCRETE_ACTION ✓ (0.29) |
| budget_execution_2026 | NO_PUBLISHABLE_ANGLE | ROUTINE_PROCESS ✓ |
| financial_management_meeting | NO_PUBLISHABLE_ANGLE | ROUTINE_PROCESS ✓ |
| midyear_budget_2026 | NO_PUBLISHABLE_ANGLE | ROUTINE_PROCESS ✓ |
| concessions_funding | NEEDS_RESEARCH | STATIC_BACKGROUND ✗ (0.51) |

The `CONCRETE_ACTION` vs `ROUTINE_PROCESS` boundary — exactly the editor's open
question — is therefore a real, measurable Jev signal. The “concrete-but-
incomplete” hypothesis shows up as `CONCRETE_ACTION` + `evidence_completeness
INSUFFICIENT` + `affected_party PRESENT`. Treat as a **supplemental** signal
only; labels are hypotheses, not ground truth.

### Manual label audit (editor-requested)

Two cases were inspected by hand, not to tune Jev but to test **our own labels**:

**`xvsdi_j7s5c-f007`** — claim `„Гласувано е за предложения дневен ред.“`, support
`„така предложения дневен ред, моля да гласува за“`. Deterministic gate:
`GROUNDED` (lexical coverage 1.0). Jev: `NOT_SUPPORTED` (0.65),
`decision_status_relation = OVERSTATED`.
→ The passage is the chair **inviting** a vote, not a record that it happened.
**Jev is right; the deterministic gate produced a lexical false positive.**

**`7k-FZXrcmq8:concessions_funding`** — proposition about concession-fund
distribution (`Приложение 12`, 50%). Deterministic `NO_PUBLISHABLE_ANGLE`; LLM
shadow `PUBLISHABLE_ANGLE`; manual hypothesis `NEEDS_RESEARCH`. Jev:
`STATIC_BACKGROUND` (0.63), `evidence_completeness INSUFFICIENT`,
`current_change ABSENT`, `affected_party ABSENT`.
→ The supporting facts describe a **standing financial mechanism**, not a
concrete action; Jev's `STATIC_BACKGROUND + INSUFFICIENT` reads better than the
manual `NEEDS_RESEARCH`. **Our own manual label is doubtful here.**

Both flips favour Jev. The practical lesson is not “trust Jev” but that the
deterministic gate is a **comparison baseline, not ground truth**, and the
manual-set quality must be re-checked before any threshold is calibrated.

## I/J — Runner + tests

`scripts/evals/jev_shadow_eval.py` loads frozen fixtures, runs one or all
experiments, appends to ignored `var/jev_eval/`, and resumes safely. +31 offline
tests (`test_jev_adapter.py`, `test_jev_shadow_eval.py`, `test_live_store.py`,
`conftest.py` resolver + 2 search tests) cover capability handling, typed-question
construction, normalization, probability preservation, provider-failure redaction,
fixture schema, resume/idempotence, and the no-authority regression.

## K/L — Gate

- [x] `ruff check src tests scripts` clean
- [x] `ruff format --check src tests scripts` clean
- [x] `PYTHONPATH=src pytest -q` → **512 passed**, offline (DNS-safe)
- [x] `PYTHONPATH=src python3 scripts/m3a_smoke.py` → **25/25**
- [x] live shadow eval: 149/149 calls OK, 0 errors, fixtures/runtime unmutated

## Metadata

```text
TypeSafe SDK version    : 0.6.0  (system install, --break-system-packages)
Jev model alias         : jev-latest
Jev effective version   : jev-1.13.0  (recorded per result)
Experiment counts       : corroboration 16 · grounding 109 · angles 24
Latency / tokens        : 648/658/742 ms avg; 174,625 in / 39,085 out total
No thresholds set; no production authority
```

## STOP

**M3J is frozen.** Jev stays a shadow measurement layer; it is not built around
any further. No M3B YouTube intake, M3C automatic enrichment, CMS publishing,
LIVE 6–10, rubric/threshold changes, Jev production authority, or editor-profile
learning happens without a new milestone decision.

Recommended next direction (editor decision): freeze Jev, then start **M3B
(YouTube URL → transcript)** and let Jev keep measuring real semantic-rescue
cases on new recordings rather than adding further synthetic evals. A future
`M3J.1 — Semantic Rescue Evaluation` would test
`deterministic borderline/reject → Jev grounding → manual adjudication` on
~100–200 borderline cases before Jev could become a second-stage verifier.
