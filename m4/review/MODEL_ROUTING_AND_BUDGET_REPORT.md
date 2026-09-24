# M4D — Model Routing + Role Budget: engineering report

Status: **MODEL_ROUTER_ENGINEERING = PROVEN** · **MODEL_POLICY_ENGINEERING = PROVEN** ·
**MODEL_USAGE_LEDGER = PROVEN** · **LIVE_ROLE_QUALIFICATION = PENDING**

> Honesty banner (pre-frontend docs-integrity gate): this report proves the
> *engineering* — routing, policy invariants, accounting, operator surfaces. It does
> NOT claim any model is qualified for a role. Live role qualification on real
> fixtures is still pending (needs provider keys and an owner-approved run); see
> `m4/review/MODEL_ROLE_QUALIFICATION_REPORT.md` for the harness truth table.

## What was built

- `config/model_policy.default.json` — tracked defaults: 7 roles, ordered routes,
  Gemini Lite 500 RPD for volume work, Gemini Flash 20 RPD for quality, paid
  GPT-5.6 Luna/Luna Pro fallback, named free OpenRouter routes.
- `drafting/model_policy.py` — policy store, normalization, env overrides,
  operator-editing helpers. Pre-frontend gate invariants (A1–A3):
  OpenRouter billing is always explicit `free|paid` (no default), `free` forces
  `public_only=true`, `known_billing()` returns `""` for an undeclared id and the
  router fails an unknown explicit model **paid-safe**.
- `drafting/model_router.py` — `call_role()` with true cross-provider fallback,
  failure classification (429 daily vs transient, 402 payment, 404 invalid,
  auth), route health tracking, bounded retries.
- `drafting/model_usage.py` — daily ledger (Europe/Sofia day), no prompts stored.
- `drafting/model_catalog.py` — live catalog validation + cached
  billing-contradiction refusal (`cached_billing_contradiction`).
- CLI `newsroom models status|validate|show|set`; Workbench `/models` page.

## Accounting semantics (after the pre-frontend correction, PART B)

Three concepts are counted separately:

```text
logical request    one call_role() invocation = one request_id
provider attempt   one real transport call to a provider (a retry adds 1)
diagnostic skip    a route never entered (SKIPPED, provider_attempts=0)
```

- `role_calls_today` = distinct `request_id`s (legacy rows without an id: one
  logical request per OK/FAILED row, never for SKIPPED).
- `model_calls_today` = `sum(provider_attempts)` for that provider+model.
- Daily fallback summary = per-request max of the running counter, not the row sum.
- Old ledgers stay readable and are never rewritten destructively.
- Role budgets (`soft_calls_day`/`hard_calls_day`) therefore throttle on real
  logical requests; per-model RPD counts real provider attempts only. They are
  two different controls, both editable from `/models` or `newsroom models set`.

Live proof (temp stores, 4 logical requests against `daily_call_limit: 3`, the
4th refused):

```text
per-request results: OK, OK, OK, REFUSED
model_calls_today (provider attempts) = 3 of 3
role_calls_today (logical requests)   = 4
SKIPPED row provider_attempts         = 0
fallbacks aggregate                   = 1 per request (max), not 2 (row sum)
```

## Paid gate and privacy gate

- `paid` routes skip before any network call while `paid_enabled=false`
  (diagnostic SKIPPED row, zero attempts).
- `public_only=true` routes refuse `payload_class="private"` before any call.
- `openrouter + billing=free` is always `public_only=true`; a policy declaring
  `free + public_only=false` is rejected at normalization.
- The paid soft budget (`soft_paid_budget_usd_day`) stays a **soft**, non-blocking
  warning: `status_report()` exposes `paid_soft_exceeded`, shown in
  `newsroom models status` and on the Workbench `/models` page.

## What is NOT proven here

- That any specific model is good enough for a role (`LIVE_ROLE_QUALIFICATION
  = PENDING`).
- The `role="research"` wiring — there is no production research caller;
  `RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED`.
- `extract` / `utility` qualification corpora — `NOT_EVALUATED`.
