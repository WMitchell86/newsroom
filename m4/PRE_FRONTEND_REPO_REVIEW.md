# Repository Review — Pre-Frontend Gate
Date: 2026-09-23

## Scope

Reviewed the uploaded full repository snapshot plus the supplied reports. I also ran the
repository gates available in this environment.

Independent verification:

```text
PYTHONPATH=src python3 -m pytest -q
→ 934 passed

PYTHONPATH=src python3 scripts/m3a_smoke.py
→ 25/25

PYTHONPATH=src python3 scripts/ui_proof.py
→ 56/56
```

`ruff` is not installed in this review environment, so the reported clean ruff gate could
not be independently rerun here.

The repository is structurally strong enough for the planned frontend strangler migration,
but I do NOT recommend starting the React/Vite frontend yet. One compact correctness round
should land first.

The supplied Review #3 correctly identified three real defects:
- G1 wrong model provenance in live draft lineage;
- G2 Workbench status parity bug;
- G3 style-retrieval shortfall checked too late.

Direct repository inspection confirms all three.

I found additional issues that matter more now because model routing and the final drafting
path are becoming operational.

---

# Executive verdict

```text
CORE_PIPELINES                  = SOUND
SOURCE / STORY LAYERS           = GOOD_ENOUGH
SERVER UI                       = GOOD_ENOUGH AS STRANGLER BACKEND
MODEL_ROUTER_ARCHITECTURE       = GOOD DIRECTION
MODEL_ROUTER_SAFETY             = NEEDS ONE CORRECTION ROUND
IDEA_TO_DRAFT_PATH              = NEEDS ONE CORRECTION ROUND
FRONTEND_MIGRATION              = WAIT FOR THIS ROUND
TELEGRAM                        = NOT NEXT
```

Do one scope-locked pre-frontend correction commit, re-run the gates, STOP, review it, and
only then start `frontend/`.

---

# Findings

## P1 — Model-add UI can accidentally bypass both the paid gate and the privacy gate

Current `/models` add-route form sends:

```text
provider
model
public_only checkbox
```

but it does NOT send `billing`.

`model_policy._normalize_route()` defaults an OpenRouter route with missing billing to:

```text
billing = "free"
```

and the unchecked UI checkbox sends:

```text
public_only = false
```

This means an operator can add:

```text
openai/gpt-5.6-luna
```

from the Workbench and the stored route can become:

```json
{
  "provider": "openrouter",
  "model": "openai/gpt-5.6-luna",
  "billing": "free",
  "public_only": false
}
```

That route can then bypass `paid_enabled=false`.

The mirror-image privacy failure also exists: a genuinely free OpenRouter route added with
the checkbox left unchecked can become eligible for private/unpublished content.

This defeats the two most important promises of the model-policy layer.

### Required correction

- OpenRouter additions must have an explicit billing class.
- Missing/unknown billing must never default to free.
- Unknown OpenRouter models should fail closed as paid, or addition should be refused until
  billing is explicitly chosen.
- `billing=free` on OpenRouter must imply `public_only=true`; do not allow an operator
  checkbox to weaken that invariant.
- A recent catalog validation that contradicts the declared billing should refuse the edit.
- Gemini additions use `operator_declared`.
- Known Gemini IDs should inherit the known local RPD guard when available.

Add both policy-level and HTTP-level regression tests.

---

## P1 — Usage accounting counts SKIPPED routes as real calls

The daily ledger currently records `SKIPPED` rows, which is useful for diagnostics, but:

```text
model_calls_today()
role_calls_today()
```

count every ledger row.

Reproduced from the uploaded code:

```text
one logical judge request
route 0 disabled → SKIPPED
route 1 succeeds → OK

role_calls_today = 2
disabled model calls_today = 1
successful model calls_today = 1
```

So:
- a disabled route consumes the displayed/local model quota;
- missing-key/privacy/paid-disabled routes consume role hard budgets;
- one logical request can consume 3–5 "role calls";
- fallback-heavy routing reaches a hard role budget much earlier than intended.

This is especially damaging because the whole point of M4D is to exploit independent model
pools cleanly.

### Required correction

Separate three concepts:

```text
logical role request
provider attempt
diagnostic skip
```

Recommended minimal implementation:
- create one `request_id` per `call_role()` invocation;
- every ledger row carries it;
- `SKIPPED` has `provider_attempts=0`;
- a real transport call increments `provider_attempts`;
- bounded retries count as additional provider attempts;
- per-model RPD guards use actual provider attempts;
- role soft/hard budgets use distinct logical request IDs;
- daily fallback count is computed per logical request, not by summing the running fallback
  counter from every route row.

Keep old ledger files readable:
- old OK/FAILED row → assume one provider attempt;
- old SKIPPED row → zero provider attempts.

Do not delete diagnostic SKIPPED rows.

---

## P1 — Live draft lineage records the wrong model (Review G1)

`live_generate_draft()` does:

```text
raw, _meta = call_model(...)
...
make_lineage(...)
```

without passing the actual model.

`make_lineage` then falls back to the old static `MODEL_ID`.

When the router falls through to another Gemini or OpenRouter model:
- usage ledger says one model;
- Workbench lineage says another.

Thread the successful router metadata into lineage before persistence.

At minimum:

```text
model = _meta["model"]
```

If provider is added to lineage, keep it additive and backward-compatible; do not redesign the
lineage schema merely for this fix.

Add an end-to-end live generation test where route 0 fails and route 1 succeeds and assert
the persisted lineage reports route 1.

---

## P1/P2 — Workbench can revive an editor-rejected idea (Review G2)

The CLI refuses preparation unless:

```text
NEW
FOLLOW_UP
DRAFT_REQUESTED
```

The Workbench `prepare_case()` has no equivalent guard. It passes the idea to
`live_case_request()`, which writes:

```text
status = DRAFT_REQUESTED
```

Thus a UI call can silently overwrite `IGNORED` or another closed editor state.

### Required correction

Create one canonical helper for "may this idea enter drafting?" and use it in:
- CLI;
- Workbench prepare;
- any future JSON API endpoint.

Do not duplicate the status tuple in three places.

`NO_PUBLISHABLE_ANGLE` remains non-draftable.

Refusal must be readable in Bulgarian and leave all stores byte-identical.

---

## P2 — Style-example count is validated after model money/time is spent (Review G3)

`make_lineage()` requires exactly 3 style example IDs.

The live path does not guarantee that before:
- draft generation;
- semantic factual verification.

A thin compatible corpus can therefore spend one or two model calls and only then fail.

### Required correction

Style retrieval is a generation precondition.

Before ANY model call:
1. retrieve/hydrate style examples;
2. fill the intended fallback chain if fewer than 3;
3. validate exactly 3 unique examples;
4. otherwise refuse cleanly before generation.

Use the already documented composition concept:

```text
requested VOICE + MODE
→ HOUSE same MODE when appropriate
→ HOUSE STANDARD_NEWS
```

Do not invent new style profiles.

Persist truthful:

```text
fallback_used
fallback_trail / retrieval_reason
```

rather than hard-coding `fallback_used=False`.

---

## P1/P2 — The live retrieved style examples contain no article body

This is a separate issue from G3 and is important for final draft quality.

`_load_rows()` loads the body, but `retrieve_examples()` returns only:

```text
article_id
url
headline
author
category
published_date
score
...
```

It drops `body`.

`drafting.prompt._example_text()` expects `record["body"]`, so the live prompt's style
examples have:
- headline/meta;
- empty P1;
- empty MID;
- empty LAST.

The system therefore claims to use three style articles while the live drafting model does
not actually see their prose.

### Required correction

Hydrate the body into the transient retrieval result used by the prompt.

Do not needlessly persist whole archive bodies into live case JSON:
- prompt-time result may contain body;
- persisted lineage/retrieval metadata may continue to store IDs/URLs/reasons only.

Add a test proving a live-built prompt contains non-empty P1/LAST text from all selected
examples.

This correction is likely more useful for Bulgarian/style quality than another model layer.

---

## P2 — Role qualification harness is not production-faithful enough

The harness says it uses production contracts, but:
- `story` does use the production relation prompt;
- `judge` is close to a production fact-entailment prompt;
- `angle` uses a simplified status-only prompt instead of the production seven-criterion
  assessment contract;
- `draft` uses a tiny generic 2–4 sentence prompt, not the real Site DNA + VOICE + MODE +
  style-example prompt;
- `research` is evaluated even though `role="research"` is not currently wired into a
  production research call.

Therefore the harness is useful as plumbing, but it cannot yet answer the owner's real
question:

> Which model is good enough for each production role?

### Required correction

Before any live role qualification/promotion:
- `angle`: use the real production assessment prompt/parser;
- `draft`: use the real `build_prompt()` and `parse_draft_json()` path over 5–10 frozen
  evidence packets plus real style retrieval;
- record deterministic factual/originality checks;
- export a small human-review sheet for Bulgarian naturalness, headline quality, site fit,
  and edit effort;
- `research`: report `NOT_WIRED_TO_PRODUCTION` until a real production caller exists;
- keep story's false-merge metric primary.

Do not benchmark dozens of models. 2–4 candidates per role is enough.

---

## P2 — Public transcript calls are unnecessarily classified as private

The routing policy is safely conservative by default, but the callers do not override payload
classification for known-public material.

Examples:
- transcript fact extraction (`role="extract"`);
- transcript fact entailment (`role="judge"`).

Both operate on already-public transcript/source material, yet default to `private`, which
makes the named free OpenRouter fallbacks ineligible.

Meanwhile the semantic check of an unpublished draft SHOULD remain private.

### Required correction

Set payload classification at the call site:

```text
public transcript extraction        → public
public transcript entailment        → public
public M4 story relation             → public (already correct)
unpublished final draft generation   → private
semantic check of unpublished draft  → private
editor notes/private files           → private
```

Do not change a whole role to public just because one caller is public.

---

## P2 — Soft paid budget is displayed but not operationally surfaced as a warning

`soft_paid_budget_usd_day` is shown in CLI/UI, but the router does not currently expose a
clear "soft paid budget exceeded" warning when selecting a paid route.

This is not a hard cap and should remain non-blocking.

After the accounting fix:
- show `paid_soft_exceeded`;
- add an operator warning in `/models` and CLI;
- continue routing if paid is explicitly enabled.

Do not add a hard global money cap in this correction unless the owner asks.

---

## P2 — Documentation state is internally inconsistent

The snapshot references:

```text
m4/review/MODEL_ROUTING_AND_BUDGET_REPORT.md
m4/review/MODEL_ROLE_QUALIFICATION_REPORT.md
```

as authoritative reports, but those files are absent from the uploaded repository.

There is also milestone naming/order drift:
- one section says M4D = model routing;
- stale text still says M4D = Telegram;
- BACKLOG says M4E Telegram / M4F polish;
- top-level CURRENT_STATE says the owner-approved next milestone is the Vite/React frontend.

This is exactly the kind of drift that causes the next coding harness to reopen the wrong
scope.

### Required correction

At the end of the correction round:
- either restore/write the two M4D reports, accurately saying live role qualification is
  still pending, or remove the dead references;
- make one single `NEXT` statement in `CURRENT_STATE.md`;
- preserve old milestone names only as history;
- do not let stale "Telegram next" text override the owner-approved frontend direction.

---

# Deliberately deferred

These are real but should NOT be mixed into this correction round:

- `_MUTATION_LOCK` held across long model generation;
- cross-process locking for `ideas.jsonl` / `cases.jsonl`;
- angles submission UI;
- Telegram M4E;
- React/Vite SPA;
- new source scrapers;
- YouTube work.

The locking work should be reconsidered when the JSON API/frontend introduces real concurrent
mutation pressure. Do not solve it speculatively in the same patch.

---

# Recommended sequence

```text
CURRENT CLEAN BACKEND
        ↓
PRE-FRONTEND CORRECTION ROUND
  model route paid/privacy safety
  model usage accounting
  lineage provenance
  idea status parity
  style retrieval preflight
  real style body examples
  role-eval production fidelity
  public/private call-site classification
  docs cleanup
        ↓
FULL GATES
        ↓
STOP / REVIEW
        ↓
ONLY THEN: frontend/ Vite + React + TS strangler migration
```

Do not start Telegram or the SPA inside the correction commit.
