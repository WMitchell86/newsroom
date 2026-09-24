# ROUND 1 — Model Routing Safety & Usage Accounting: review → fix → verify report

Scope: the narrow ROUND 1 loop (billing/privacy safety, usage accounting, soft
paid-budget warning). The later rounds (G1 lineage, G2 idea-status parity, G3
style retrieval, harness fidelity) were already applied in this same tree by the
pre-frontend correctness harness; their proofs live in
`m4/review/PRE_FRONTEND_CORRECTNESS_REPORT.md`. This report covers exactly the
ROUND 1 items.

## A — Pre-fix review (reproduced from the committed code, `git show HEAD`)

Written before changing anything, per the harness.

### A1. OpenRouter billing omission → silent `free`

HEAD `model_policy._normalize_route`:

```python
billing = str(route.get("billing") or ("operator_declared" if provider == "gemini" else "free"))
```

Reproduction of the stored route after adding `openai/gpt-5.6-luna` with no
`billing` from the Workbench form (which sent only `provider`, `model`,
`public_only`):

```json
{"provider": "openrouter", "model": "openai/gpt-5.6-luna",
 "billing": "free", "public_only": false}
```

→ a paid model normalized to **free** and, with the checkbox unchecked, also
eligible for private payloads — both the paid gate and the privacy gate bypassed
by one form submit.

### A2. Free route + `public_only=false` accepted

HEAD normalized `public_only = bool(route.get("public_only", provider ==
"openrouter" and billing == "free"))` — an explicit `public_only=false` overrode
the free-route default, so `openrouter + free + public_only=false` was accepted
and could receive `payload_class="private"`.

### A3. Unknown explicit model could become implicitly free

HEAD `_explicit_route` used `known_billing(policy, model)` directly and only
forced `paid` for ids with a known price snapshot; an id unknown to both the
policy and the price table was tried with `billing=None` → normalized to `free`
(A1 default) → an unknown model could bypass the paid gate.

### A4. Workbench add-route POST path (traced, not just unit-level)

`/models` add form (html.py) posted `action=add, role, provider, model,
public_only` — **no `billing` field** → `http.py` → `newsroom.edit_policy(...)`
→ `model_policy.add_route` → `_normalize_route` (the A1 default). Exactly the
bug the form's omission made reachable; policy-file routes were safe (they carry
explicit billing).

## B — Fixes applied

- **B1 explicit billing**: OpenRouter routes without `billing` raise
  `PolicyError` (`billing must be explicit: free | paid`); no default is inferred.
- **B2 free ⇒ public-only**: `openrouter + free` forces `public_only=true`;
  `free + public_only=false` is rejected with a readable error through the policy
  file, helpers, CLI and Workbench POST alike.
- **B3 paid routes**: still gated by `paid_enabled` — skipped before any network
  call with a diagnostic row that costs zero attempts.
- **B4 unknown = paid-safe**: `known_billing()` returns `""` for an undeclared
  id and `_explicit_route` fails it paid-safe (`billing="paid"`), so an unknown
  explicit model can never bypass the paid gate.
- **B5 catalog contradiction**: `model_catalog.cached_billing_contradiction()`
  refuses adding a model as free when a recent validation cached it as paid
  (no network call on page render).
- **B6 Gemini untouched**: stays `operator_declared`; known ids inherit
  `GEMINI_DAILY_LIMITS` on the env-override path only; no new quotas hard-coded.
- Workbench add form now sends a **required** `billing` radio (Безплатен /
  Платен); free shows «само публични материали» and forces public-only. The CLI
  `models set --add` requires explicit `--billing free|paid` for OpenRouter.

## C/D — Usage accounting

Pre-fix (HEAD `model_usage`): `model_calls_today` / `role_calls_today` counted
**ledger rows** (`len(payload["calls"])` buckets), and HEAD `call_role` wrote a
row per route event with no `request_id` / `provider_attempts`. Reproduced
scenario `route0 disabled → SKIPPED, route1 OK`:

| quantity                        | before (rows) | after (accounting) |
|---------------------------------|---------------|--------------------|
| role_calls_today                | 2             | **1** (distinct request_id) |
| model_calls_today(route0)       | 1             | **0** (SKIPPED = 0 attempts) |
| model_calls_today(route1)       | 1             | **1** |
| one transient retry + success   | 1 row / 1 call| **provider_attempts = 2**, role requests = 1 |
| fallback aggregate              | row-sum inflation (2) | **1** (per-request max) |

Implementation: `request_id` per `call_role()` invocation on every row; 
`provider_attempts` per row (SKIPPED=0, retries counted, `_try_route` returns the
exact transport attempt count); model RPD = Σ attempts; role budgets = distinct
request ids; fallbacks aggregated per logical request. Legacy rows stay readable:
OK/FAILED without the field = 1 attempt, SKIPPED = 0, missing `request_id` = one
logical request per non-SKIPPED row; old files are never rewritten destructively.

## E — Soft paid-budget warning

`status_report()` exposes `paid_soft_exceeded` (`paid_cost_today >=
soft_paid_budget_usd_day`); `newsroom models status` prints
«ПРЕВИШЕН СОФТ БЮДЖЕТ ЗА ПЛАТЕНИ», the Workbench `/models` page shows
«Платеният софт бюджет … не блокада». No auto-disable, no route reorder, no hard
cap.

## G — Tests added (hermetic, all passing)

Safety: missing-billing refusal, `luna` without billing refused, free +
`public_only=false` rejected, `known_billing("")` + unknown explicit paid-safe,
free route cannot receive a private payload, cached paid-vs-free contradiction,
Workbench add-route HTTP parity (missing billing → 400; luna as paid refused
while paid disabled).
Accounting: B7 disabled-route reproduction (role requests 1 / attempts 0+1),
transient retry (attempts 2, requests 1), legacy ledger rows, model-limit counts
attempts only, role hard limit counts request ids only, fallback aggregate
request-based.
Soft warning: below budget → no warning; at/above → warning with routing
allowed (CLI + `/models`).

## H — Verification (full gate, this tree)

```text
PYTHONPATH=src python3 -m pytest -q        → 978 passed
ruff check src tests scripts               → All checks passed!
ruff format --check src tests scripts      → 145 files already formatted
PYTHONPATH=src python3 scripts/m3a_smoke.py → 25/25 ALL CHECKS PASSED
PYTHONPATH=src python3 scripts/ui_proof.py  → 56/56 ALL CHECKS PASSED
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models status → OK
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list → OK (plan only)
```

No live provider calls were made; the role qualification suite was not run live.

## Summary table

| Scenario                        | Before            | After                       |
|---------------------------------|-------------------|-----------------------------|
| disabled route                  | 1 "call"          | 0 provider calls (SKIPPED row only) |
| one logical fallback request    | 2+ role calls     | 1 role request              |
| paid model, billing omitted     | silently `free`   | REFUSED (`PolicyError`)     |
| free route + private payload    | possible          | REFUSED (forced public-only)|
| unknown explicit model          | could become free | paid-safe                   |
| catalog says paid, added free   | accepted          | REFUSED (contradiction)     |
| soft paid budget exceeded       | invisible         | CLI + Workbench warning (non-blocking) |

## Still uncertain / notes

- The two rounds were applied in one tree (owner direction: "finish the task,
  then process the next prompt"); ROUND 2 items (G1/G2/G3, harness fidelity,
  payload classification) are therefore already present and covered by their own
  report. Nothing from ROUND 1's "do NOT fix" list was invented here — those
  fixes came from the pre-frontend harness and are documented separately.
- `ruff` was unavailable in the original reviewer's environment; here it is
  0.16.3 and clean.
