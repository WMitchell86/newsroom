# Pre-Frontend Correctness Gate — correction report

Date: 2026-09-24 · Harness: `m4/HARNESS_PROMPT_PRE_FRONTEND_CORRECTNESS.md`
Findings source: `m4/PRE_FRONTEND_REPO_REVIEW.md` (+ Review #3 G1/G2/G3)
Verdict: **all PARTs A–K applied; gates green; scope-locked STOP**

> One commit, one scope: the pre-frontend correction round. The SPA strangler
> migration starts only after this report is reviewed. Telegram, `frontend/`,
> new source work, YouTube, CMS, auto-publish and fine-tuning were not touched.

## Findings fixed (review → resolution)

| finding | severity | resolution |
|---|---|---|
| P1 model-add UI can bypass paid + privacy gates (billing omitted → `free`, checkbox → `public_only=false`) | P1 | **PART A**: OpenRouter billing must be explicit `free\|paid` (`PolicyError` otherwise); `free` forces `public_only=true`; `free + public_only=false` rejected; unknown explicit model fails paid-safe; cached billing contradiction refuses free; Workbench form has a required billing radio; CLI `models set --add` requires `--billing`. |
| P1 usage accounting counts SKIPPED routes as real calls | P1 | **PART B**: `request_id` per `call_role()`; `provider_attempts` per row (SKIPPED=0, retries counted); model quota = Σ attempts; role budgets = distinct request ids; fallback aggregate per request. |
| P1 live draft lineage records the wrong model (G1) | P1 | **PART D**: `live_generate_draft` passes `(generation_meta or {}).get("model") or gen.MODEL_ID` into `make_lineage`; end-to-end fallback test asserts lineage reports the route that actually produced the draft. |
| P1/P2 Workbench can revive an editor-rejected idea (G2) | P1/P2 | **PART E**: canonical `ideas.assert_draftable_status` (NEW/FOLLOW_UP/DRAFT_REQUESTED; Bulgarian refusal) wired into CLI `live-case` and Workbench `prepare_case` (→ 400/redirect error); stores stay byte-identical on refusal. |
| P2 style-example count validated after model spend (G3) | P2 | **PART F**: `retrieve_examples_for_generation` preflight — exactly 3 unique examples or `StyleRetrievalError` BEFORE any model call; documented composition fallback chain; truthful `fallback_used`/`fallback_trail`/`retrieval_reason` persisted. |
| P2 retrieved style examples contain no article body | P2 | **PART G**: `retrieve_examples(include_body=)`; prompt-time records carry bodies, persisted metadata keeps IDs/URLs/reasons only. |
| P2 role qualification harness is not production-faithful | P2 | **PART I**: production prompts/parsers for judge/angle/draft; M3D disagreement cases in the angle fixture; frozen EvidencePackets for draft; human-review sheet; research = `NOT_IMPLEMENTED`; extract/utility = `NOT_EVALUATED`; paid eval guard. |
| P2 public transcript calls classified private | P2 | **PART H**: call-site `payload_class`: extract/judge (transcript) = public, story relation = public, draft generation + draft semantic check = private. Role defaults unchanged. |
| P2 soft paid budget not operationally surfaced | P2 | **PART C**: `paid_soft_exceeded` in `status_report()`; CLI + Workbench warnings; non-blocking. |
| P2 documentation internally inconsistent | P2 | **PART K**: the two M4D reports created with honesty banners; one NEXT statement; stale "M4D = Telegram" text corrected. |

Deferred (unchanged, still in `BACKLOG.md` per PART L): mutation lock across
generation, cross-process ideas/cases locking, angles submission UI, Telegram,
SPA.

## PART B — before/after accounting example

Scenario (reproduced in a hermetic test, B7): `route0` disabled → `route1` OK.

```text
                          BEFORE (row counts)      AFTER (semantic accounting)
role_calls_today          2                        1   (distinct request_id)
model_calls_today(r0)     1                        0   (SKIPPED → provider_attempts=0)
model_calls_today(r1)     1                        1
transient retry+success   1 "call"                 provider_attempts=2, role requests=1
fallbacks today           2 (row sum inflation)    1   (max per logical request)
```

Live proof (temp stores; limit 3; 4 logical requests → 4th refused):

```text
per-request results: OK, OK, OK, REFUSED
model_calls_today = 3 of 3 (skip rows never counted)
role_calls_today  = 4 (logical requests)
SKIPPED rows: provider_attempts = 0
```

Legacy compatibility: old OK/FAILED rows read as 1 attempt, old SKIPPED as 0,
missing `request_id` = one logical request per non-SKIPPED row; old files are
never rewritten.

## PART A — before/after add-route billing/privacy example

Adding `openai/gpt-5.6-luna` from `/models` with no billing field:

```json
// BEFORE (normalized silently)
{"provider": "openrouter", "model": "openai/gpt-5.6-luna", "billing": "free", "public_only": false}
// → bypassed paid_enabled AND could receive private payloads

// AFTER
PolicyError: OpenRouter маршрут 'openai/gpt-5.6-luna' трябва да посочи billing (free | paid)
```

Adding a genuinely free model with the checkbox unchecked:

```text
BEFORE: accepted → eligible for private/unpublished content
AFTER:  PolicyError: free OpenRouter маршрут … изисква public_only=true
```

Unknown explicit model: `known_billing()` returns `""` → `_explicit_route`
fails it **paid-safe** (billing="paid"), before any network call.

## PART D — lineage fallback proof (G1)

`tests/test_live_generate_offline.py`: draft route 0 fails (429), route 1
succeeds as `mock/second` → stored `live_draft.lineage.model == "mock/second"`
and the opened case's lineage reports `mock/second`; the usage ledger's
successful row names the same model. Old/mock callers without metadata keep the
documented static fallback.

## PART E — status parity proof (G2)

- Unit: `ideas.assert_draftable_status` refuses IGNORED / NO_PUBLISHABLE_ANGLE /
  unknown with a Bulgarian message; allows NEW / FOLLOW_UP / DRAFT_REQUESTED.
- CLI parity: `tests/test_workflow_live_cli.py` — live-case on a closed idea
  refuses, stores unchanged.
- UI parity: `tests/test_workbench_articles.py` (parametrized
  IGNORED / NO_PUBLISHABLE_ANGLE) — `prepare_case` raises → 400/redirect error,
  no prepared row, no success audit.

## PART F/G — style prompt proof (G3 + body hydration)

- `tests/test_drafting_m23.py`: preflight returns exactly 3 unique bodies;
  composition fallback chain (VOICE+MODE → HOUSE+MODE → HOUSE+STANDARD_NEWS)
  with dedupe; refusal (`StyleRetrievalError`) before any model call; legacy
  body-less shape still available via `retrieve_examples(include_body=False)`.
- `tests/test_live_generate_offline.py`: the built live prompt carries
  non-empty P1/LAST prose from all three selected examples under
  `STYLE_EXAMPLES` (explicitly "STYLE ONLY"), while the persisted retrieval
  metadata contains no bodies.

## PART I — qualification-harness truth table

```text
role      wiring                    note
story     production-faithful       production prompt + false-merge metric (kept)
judge     production-faithful       production entailment prompt+parser; draft semantic subtype = PENDING_NO_FIXTURE
angle     production-faithful       7-criterion production prompt+parser; 7 M3D disagreement cases in fixture
draft     production-faithful       real build_prompt + parse_draft_json + audit/originality; style verdict = HUMAN sheet
research  NOT IMPLEMENTED           RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED (no production caller)
extract   NOT_EVALUATED             no qualification corpus
utility   NOT_EVALUATED             no qualification corpus

LIVE_ROLE_QUALIFICATION = PENDING   no model is qualified by this round
```

Paid eval guard: paid candidate routes refuse to run without `--allow-paid`.

## PART M — gates

```text
PYTHONPATH=src python3 -m pytest -q         → 978 passed
ruff check src tests scripts                → All checks passed!
ruff format --check src tests scripts       → clean
PYTHONPATH=src python3 scripts/m3a_smoke.py → 25/25 ALL CHECKS PASSED
PYTHONPATH=src python3 scripts/ui_proof.py  → 56/56 ALL CHECKS PASSED
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list → OK (no calls)
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models status → OK
```

Test count went 934 → 978 (+44: billing/privacy, accounting, soft-budget,
lineage, status parity, retrieval preflight/body, harness fidelity suites; the
harness tests were rewritten for the production contracts). The suite baseline
at review time (934) had 8 date-fragile `test_newsroom_collect.py` failures vs
the real clock — fixed by injecting `now` (`newsroom_run.collect(now=None)`
resolved at call time; tests monkeypatch `newsroom_run._now`), included here so
the gate is reproducible on any day.

No live provider calls were made in this round.

## Operator-visible changes (README/RUNBOOK relevant)

- `/models` add form: required Billing radio (Безплатен/Платен); free shows
  «само публични материали»; paid refused while paid is disabled.
- CLI: `newsroom models set --add --provider openrouter … --billing free|paid`
  (mandatory); `models status` prints logical requests, provider attempts and
  the soft-budget warning when exceeded.
- Eval harness: `--allow-paid` and `--semantic-gate` flags; reports carry the
  wiring truth; `draft_human_review.md` sheet under `var/model_role_eval/`.
