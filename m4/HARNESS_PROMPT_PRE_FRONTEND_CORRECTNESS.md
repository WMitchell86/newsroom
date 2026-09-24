# Coding Harness — Pre-Frontend Correctness Gate

## Starting point

Use the current clean repository state represented by the uploaded snapshot.

Expected current gates:

```text
pytest = 934
M3A smoke = 25/25
ui_proof = 56/56
ruff reported clean
```

The existing server-rendered Workbench stays operational.

The owner has approved a later:

```text
frontend/ — Vite + React + TypeScript SPA over a JSON API
```

but DO NOT start it in this run.

This is one scope-locked correctness patch before the frontend strangler migration.

Read:
1. `CURRENT_STATE.md`
2. `agents.md`
3. the latest idea→draft Review #3 supplied by the owner
4. the existing M4 model-routing code/tests

Then implement the parts below and STOP.

---

# PART A — Fix model-route billing/privacy safety first

## A1. OpenRouter billing must never default to free

Current bug:

```text
provider=openrouter
billing omitted
→ normalize() chooses "free"
```

This can make a paid model bypass `paid_enabled=false`.

Required invariant:

```text
OpenRouter route
→ billing MUST be explicit: free | paid
```

Tracked defaults already carry billing.

For operator-added routes:
- Workbench form must require a billing choice for OpenRouter;
- CLI/helper must require it too;
- missing billing → `PolicyError`;
- do not silently infer "free" from provider name.

For Gemini:

```text
billing = operator_declared
```

is the normal classification.

## A2. Free OpenRouter always means public-only

Required invariant:

```text
provider=openrouter
billing=free
→ public_only=true
```

Do not allow an unchecked checkbox or malformed override to weaken it.

If a policy file declares:

```text
openrouter + free + public_only=false
```

reject the policy.

Paid OpenRouter routes may be private.

## A3. Unknown explicit OpenRouter model fails paid-safe

`known_billing()` / `_explicit_route()` must not treat an unknown model as free.

Safe behavior:

```text
unknown OpenRouter billing
→ paid-safe
```

unless a live catalog or explicit policy route proves it free.

The paid gate must run before network.

## A4. Add-route UI

Keep the page simple.

For OpenRouter show:

```text
Billing:
  Безплатен
  Платен
```

No blank implicit default.

If "Безплатен":
- display "само публични материали";
- force public_only=true.

For Gemini:
- do not ask the operator to choose paid/free here;
- use operator_declared;
- fill known local RPD from `GEMINI_DAILY_LIMITS` when available.

Optional daily limit field only if needed for an unknown Gemini ID.

## A5. Catalog contradiction

If a recent cached validation knows an OpenRouter model is paid and the operator attempts
to add it as free:
- refuse the edit;
- say to run model validation.

Likewise free-vs-paid mismatches remain visible in `models validate`.

Do not require a network call every time the page renders.

## A6. Tests

Prove:
- adding `openai/gpt-5.6-luna` without billing is refused;
- adding it as paid cannot run while paid is disabled;
- free OpenRouter + public_only=false is rejected;
- free OpenRouter cannot receive private payload;
- unknown explicit model cannot bypass paid gating;
- Gemini known ID inherits declared RPD.

---

# PART B — Correct model-usage accounting

The ledger may keep diagnostic SKIPPED events, but they are NOT provider calls.

## B1. Introduce a logical request id

At the start of every `call_role()` create:

```text
request_id
```

Every ledger event for that router invocation carries the same request id.

No prompt content in the ledger.

## B2. Provider attempt count

Each ledger row gains:

```text
provider_attempts
```

Semantics:

```text
SKIPPED → 0
one actual HTTP/provider call → 1
retry → +1
```

If `_try_route()` performs two transport attempts before success, the successful route must
record `provider_attempts=2`.

If it performs two then fails, the failed route records 2.

## B3. Model quota accounting

`daily_call_limit` / model RPD uses:

```text
sum(provider_attempts)
```

for that provider+model.

It must NOT count:
- disabled-route skips;
- privacy skips;
- missing-key skips;
- paid-disabled skips.

## B4. Role budget accounting

Role soft/hard budgets use:

```text
distinct logical request_id
```

not ledger rows and not fallback routes.

One request that skips 3 routes and succeeds on route 4 consumes:

```text
1 role request
1+ actual provider attempts
0 provider calls on the skipped routes
```

## B5. Fallback accounting

Daily fallback summary must represent fallback steps per logical request, not the sum of the
running fallback counter written on every intermediate row.

Keep the per-event trace if useful; fix the aggregate.

## B6. Backward compatibility

Old usage files must still load.

For old rows:
- OK/FAILED without provider_attempts → assume 1;
- SKIPPED → 0;
- missing request_id → keep readable; do not rewrite old files destructively.

## B7. Required regression

Exactly reproduce:

```text
route0 disabled
route1 succeeds
```

Expected:

```text
logical role requests today = 1
route0 provider attempts = 0
route1 provider attempts = 1
```

Also test:

```text
route0 429 transient then success
→ provider attempts = 2
→ role requests = 1
```

---

# PART C — Paid soft-budget warning

`soft_paid_budget_usd_day` remains a SOFT warning, not a hard money cap.

After the accounting correction:

```text
paid_cost_today >= soft_paid_budget
→ paid_soft_exceeded=true
→ visible warning in CLI + Workbench
→ routing continues only because paid_enabled was already explicit
```

Do not add a new hard global budget in this run.

---

# PART D — Correct draft provenance (Review G1)

In `workflow/live.py` keep the generation router metadata:

```python
raw, generation_meta = gen.call_model(...)
```

and pass the actual successful model to lineage:

```text
lineage.model = generation_meta["model"]
```

Do not leave `MODEL_ID` as the effective live model when a fallback fires.

Backward compatibility:
- if old/mock callers omit metadata, use a clearly documented fallback only where tests need it;
- production router returns model metadata.

Required end-to-end test:

```text
draft route 0 fails
draft route 1 succeeds as "mock/second"
→ stored live_draft.lineage.model == "mock/second"
→ opened case lineage.model == "mock/second"
```

Usage ledger and lineage must agree.

---

# PART E — Canonical idea-status drafting guard (Review G2)

Do not copy the allowed tuple into another function.

Create/reuse one canonical check, e.g.:

```text
ideas.assert_draftable_status(idea)
```

Allowed:

```text
NEW
FOLLOW_UP
DRAFT_REQUESTED
```

Closed:

```text
IGNORED
NO_PUBLISHABLE_ANGLE
anything unknown
```

Use it in:
- CLI `live-case`;
- Workbench `prepare_case`;
- future JSON API service boundary.

Refusal:
- readable Bulgarian;
- no mutation of idea;
- no prepared row;
- no audit action claiming success.

Tests:
- UI preparation of IGNORED refuses;
- NO_PUBLISHABLE_ANGLE refuses;
- NEW/FOLLOW_UP/DRAFT_REQUESTED work;
- CLI/UI parity.

---

# PART F — Style retrieval is a pre-generation contract (Review G3)

No generation call may happen before exactly three usable style examples are ready.

## F1. Add a retrieval-with-metadata helper

Keep legacy `retrieve_examples()` compatible if tests depend on it.

Add a helper such as:

```text
retrieve_examples_for_generation(...)
→ {
    examples: [... exactly 3 ...],
    fallback_used: bool,
    fallback_trail: [...],
    retrieval_reason: ...
  }
```

Use the intended composition fallback, not a new taxonomy:

```text
requested VOICE + MODE
→ HOUSE same MODE when appropriate
→ HOUSE STANDARD_NEWS
```

Deduplicate article IDs.

If three unique examples still cannot be produced:
- raise a clean retrieval error BEFORE `call_model()`;
- no draft request;
- no semantic judge request;
- no spend.

## F2. Persist honest fallback metadata

Replace hard-coded:

```text
fallback_used = False
```

with actual metadata.

Case/draft stores keep the existing lightweight IDs/reasons.

---

# PART G — Put the actual style prose into the live prompt

Current `retrieve_examples()` drops `body`, while `prompt._example_text()` expects it.

Fix the transient prompt-time record:

```text
article_id
headline
...
body
```

The drafting model must receive non-empty:
- P1;
- LAST;
- MID when applicable.

Do not persist full archive article bodies into live draft/case JSON unless they are already
part of an existing frozen artifact. IDs + URLs + retrieval metadata remain enough for
lineage.

Tests:
- `retrieve_examples` or the new generation helper returns body for prompt use;
- the built live prompt contains non-empty style prose from all 3 examples;
- style prose remains under `STYLE_EXAMPLES` and remains explicitly `STYLE ONLY`;
- archive facts still cannot become current evidence.

This is a style-quality fix, not an invitation to weaken the factual boundary.

---

# PART H — Make payload classification accurate at call sites

Do NOT change the entire role's privacy default.

Explicitly classify known-public calls.

Required:

```text
workflow.discovery transcript fact extraction
role=extract
payload_class=public

workflow.discovery transcript fact entailment
role=judge
payload_class=public

workflow story relation
role=story
payload_class=public  # already expected

final article drafting
role=draft
payload_class=private

semantic verification of unpublished draft
role=judge
payload_class=private
```

For transcript angle proposal/assessment, the input is public transcript evidence; mark it
public if that is factually true for that code path.

Tests must prove:
- a public transcript call may fall through to a named free OpenRouter route;
- an unpublished draft judge/draft call may not.

---

# PART I — Repair the role qualification harness before using it for model promotion

The harness engineering is useful, but it must stop claiming production fidelity where it
does not have it.

## I1. Story

Keep the current production relation prompt and false-merge metric.

## I2. Judge

Reuse the actual production fact-entailment prompt/parser for the fact-judge fixture.

If also evaluating the final draft semantic judge, treat it as a separate fixture subtype; do
not merge its metric silently with fact entailment.

## I3. Angle

Use the real production assessment contract:
- seven criteria;
- real semantic status values;
- production parser/validation.

Do not use the simplified status-only eval prompt.

Include the M3D disagreement cases.

## I4. Draft

Use the real draft prompt path:
- frozen EvidencePacket;
- Site DNA;
- VOICE;
- MODE;
- real three style examples;
- `parse_draft_json`;
- deterministic factual audit;
- semantic gate only when explicitly requested;
- originality guard.

The automatic draft eval may score:
- JSON validity;
- unsupported/invented numbers/names;
- required fact coverage;
- originality warning.

But final language/style promotion is HUMAN.

Generate a small human-review artifact:

```text
model
case
headline
body
Bulgarian naturalness: ___
headline quality: ___
Cherno­morie fit: ___
editing needed: ___
notes: ___
```

Do not let another LLM make the final Bulgarian style decision.

## I5. Research

There is currently no production `role="research"` call in the source tree.

Report:

```text
RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED
```

Do not call a synthetic research benchmark "production qualification".

Keep the role configured for future work if useful.

## I6. Extract / utility

Remain `NOT_EVALUATED` until a real fixture corpus exists.

No invented promotion verdict.

## I7. Paid eval guard

A live eval must require explicit paid opt-in.

Do not silently enable paid models merely because the model policy contains them.

---

# PART J — Model policy default budgets

After PART B, role budgets mean logical requests rather than fallback rows.

Do NOT tune them from generic theory in this patch.

However:
- make sure the current defaults no longer accidentally throttle after only a fraction of
  their stated calls because of skip inflation;
- document that per-model quotas and role caps are different controls;
- leave the operator able to raise/lower role caps from `/models`.

Do not chase maximum theoretical quota consumption.

---

# PART K — Documentation integrity

The repository currently names two authoritative reports that are missing from the uploaded
tree:

```text
m4/review/MODEL_ROUTING_AND_BUDGET_REPORT.md
m4/review/MODEL_ROLE_QUALIFICATION_REPORT.md
```

Create/restore them OR remove the references.

If created now, they must be honest:

```text
MODEL_ROUTER_ENGINEERING = PROVEN
ROLE_QUALIFICATION_HARNESS = PROVEN
LIVE_ROLE_QUALIFICATION = PENDING
```

Do not claim the models themselves are qualified merely because the harness runs.

Also fix milestone drift:
- M4D = model routing in current history;
- stale text that calls Telegram "M4D next" must not remain authoritative;
- `CURRENT_STATE.md` must have one unambiguous NEXT statement.

Owner-approved next after THIS correction round:

```text
frontend/ Vite + React + TypeScript SPA over a JSON API
(strangler migration)
```

Telegram remains backlog unless the owner changes priority.

---

# PART L — Do not solve the deferred locking work here

Leave in BACKLOG:
- `_MUTATION_LOCK` held across long model generation;
- cross-process writes to ideas/cases;
- angle-submission UI.

They are real, but they are not part of this correctness patch.

Do not create a generic transaction/locking framework.

---

# PART M — Tests and gates

Add targeted tests for every correction above.

Run:

```bash
PYTHONPATH=src python3 -m pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
PYTHONPATH=src python3 scripts/m3a_smoke.py
PYTHONPATH=src python3 scripts/ui_proof.py
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models status
```

No live provider calls are required for this correction.

If keys are available, a bounded catalog validation is fine, but do not burn quota on role
qualification in this run.

---

# PART N — Commit / STOP

Produce one review report:

```text
m4/review/PRE_FRONTEND_CORRECTNESS_REPORT.md
```

It must include:
- findings fixed;
- before/after accounting example;
- before/after add-route billing/privacy example;
- lineage fallback proof;
- status parity proof;
- style example prompt proof;
- qualification-harness truth table (`production-faithful`, `not wired`, `pending`);
- gates.

Update:
- CURRENT_STATE.md
- BACKLOG.md
- MILESTONE.md
- handoff.md
- README/RUNBOOK only where operator behavior changed.

Commit as one scope-locked correction commit.

Then STOP.

Do NOT start:
- `frontend/`;
- Telegram;
- new source work;
- YouTube;
- CMS;
- automatic publishing;
- fine-tuning.

Wait for review. The next prompt will define the SPA strangler migration after this gate is
clean.
