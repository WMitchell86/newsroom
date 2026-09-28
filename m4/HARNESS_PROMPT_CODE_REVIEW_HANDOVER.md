# Code review handover — V1.2-G4.3 / G4.4 / G4.5 / G4.6

Read this first: the previous agent made a large number of confident, unverified
claims and several regressions. `AGENTS.md` records the failures. Your first job
is not to trust any summary — including this one — but to measure.

Current branch: `main`. All work committed and pushed. Working tree clean.

---

## 1. What actually ships in these four milestones

**G4.3** — a Story with nothing read and a readable publication of its own is a
third readiness state, `DRAFT_FROM_UNREAD_SOURCE`. `draftEligible` is honestly
`false`; the action is still offered, because the Draft command reads the
source itself. The bug this fixed: the UI claimed "Има достатъчно потвърдена
информация" on a Story with zero opened sources.

**G4.4 — NOT IMPLEMENTED.** The known defect, still open: `start_article_draft`
performs `_draft_snapshot()` and enrichment synchronously before returning the
token. Measured: `POST /api/v1/articles/<id>/draft -> 202 in 20856ms`.
Architecture §15.2 requires a sub-second `202 {operationToken}`. This is the
original milestone and it is untouched.

**G4.5** — unclassified provider failures report their real cause instead of
`"Source unavailable"`, through two layers (the worker's catch-all and the
operation error envelope).

**G4.6** — operations are listed, persisted across restart, and surfaced in the
UI; a failed Quick Draft says so on the row where it was requested.

---

## 2. Review these in this order

### 2.1 Does the system tell the truth when it fails?  (highest risk)

Three separate places once reported a cause the system had not observed.

- `src/editor_assistant/workflow/editor_application.py:1880` — the Draft
  worker's catch-all. Check it cannot relabel a classified refusal, and that
  the reason it surfaces is the provider's own.
- `src/editor_assistant/workflow/editor_application.py:1434` — the operation
  error envelope. **This one still hardcodes `SOURCE_UNAVAILABLE` for every
  non-draft, non-rewrite, non-quick-draft scope, including the newsroom
  refresh.** A failed refresh will still claim a source problem. Known, not
  fixed.
- `src/editor_assistant/workflow/article_generation.py` — `operation_error()`
  and `safe_detail()`. Confirm the redaction actually covers every way a
  provider error can echo the request back, and that it fails closed.

**Ask:** can any code path produce a user-visible sentence naming a cause the
system did not observe? Trace the four failure classes (quota, overload,
unreadable source, version conflict) end to end and confirm each produces a
distinct, true message.

### 2.2 Routing and health state

- `var/model_policy.json` is the LIVE policy (operator override, gitignored);
  `config/model_policy.default.json` is the versioned default. They can drift.
  Check they agree.
- `src/editor_assistant/drafting/model_router.py` (`STATUS_EXHAUSTED`, line 57) — a
  single `429` marks a route `EXHAUSTED` for a long window. On 2026-09-28 that took two working
  models offline for the rest of the day. **Assess whether the circuit-breaker
  window is proportionate, and whether a `503` and a `429` are treated
  differently.** They are not, as far as the agent could tell.
- Check `daily_call_limit` against real provider behaviour. A per-model limit
  of 20 (inherited from prose in the policy note) blocked a model the provider
  was serving. There is no automated check that a local guardrail is not
  tighter than the provider.

### 2.3 Concurrency and locking — not reviewed at all

The draft command runs under a global `_COMMAND_LOCK` held across network and
model calls. Confirm this is real and quantify the blast radius: can a slow
provider call block unrelated commands? Is any lock held across an `await`-like
boundary? This was flagged in the original G4.4 analysis and never examined.

### 2.4 The operation registry

`src/editor_assistant/workflow/story_operations.py`

- `_write_ledger()` catches `OSError` and passes. Confirm that is acceptable:
  a failed write silently loses history, which is the exact failure this code
  exists to prevent.
- `MAX_OPERATIONS = 32` with `TTL_SECONDS = 900`. Confirm a 32-operation burst
  cannot evict live work.
- `load_ledger()` restores a `pending`/`running` row as `failed` with
  `INTERRUPTED_BY_RESTART`. Verify the `_write_ledger` calls are correctly
  ordered against status transitions — a race here would label a completed
  operation as interrupted or vice versa.

### 2.5 The readiness predicate and its matrix

`src/editor_assistant/workflow/article_readiness.py`,
`tests/test_draft_readiness_parity.py`

The matrix gained a third slot `(eligible, code, offers)`. The invariant that
matters: an action the projection offers must never be one the command refuses.
Check that this is actually enforced by a test that would fail if the two
diverged, rather than by assertion that happens to pass today.

The two `focus=False` rows now assert the same outcome as their focused twin.
Confirm that is the intended contract and not a test weakened to make a change
pass.

### 2.6 Frontend

- `frontend/src/pages/OperationsPage.tsx` — polls every 5s, renders the
  server's reason verbatim. Check it degrades honestly when the list is empty
  versus when the server is down. The empty state says "the server has no
  history", which is a claim — verify it is distinguishable from "never asked".
- `frontend/src/pages/today/TodayStoryRow.tsx` — the failure banner. Confirm it
  cannot render a reason that is absent, and that `Прегледай` and the retry
  both survive a failure.
- `frontend/src/pages/TodayPage.tsx` — `busy` is now
  `quick.isPending || item.quickDraft?.inFlight`. Confirm no path shows a
  pending state for an operation that is not actually in flight.

### 2.7 Test suite integrity

- `tests/test_workbench_api.py` is order-dependent:
  `test_research_that_finds_nothing_persists_an_explicit_gap` fails on
  unmodified `main` in some runs and not others. **Find the leak and fix it.**
  A suite whose result changes with ordering cannot be used to judge a change.
- `tests/test_quick_draft.py` — 7 failures on unmodified `main`. Every one is
  an unfixed defect. **Diagnose and either fix or delete them.** They are not
  environment noise; the agent never established why they fail.
- `tests/test_model_policy.py` — 2 failures on unmodified `main`.
- The agent compared "before" by stashing. Check whether that comparison was
  itself sound anywhere, and whether any of the 4 new tests are vacuous.

---

## 3. State of the system right now

Verified at 2026-09-28 16:40, not asserted:

- Server: `scripts/start_workbench.sh` on `127.0.0.1:8123`.
- `GEMINI_API_KEY` in the process is 39 chars, unquoted. Verify it yourself.
- Articles: 0 in every state. The agent cleared them at the editor's request.
  Backup of the removed state: `var/backup_pre_clean/`.
- `gemini-3.6-flash` returns 200. `3.5` and `3.8` return 429. `3.7` and
  `3.5-flash-lite` returned 503 at the moment of the probe — **re-probe before
  believing this, it is a minutes-long condition.**
- Operation `op_16a1b4103b3a0af75e9b77f8` was still `running`. If the process
  was restarted since, it will now read `INTERRUPTED_BY_RESTART`, which is
  correct behaviour and not a new bug.

**No Draft has been produced end to end since the provider started refusing.**
That is the single most important thing to establish first: a working prototype
requires a generated article, and the agent never demonstrated one on a
Flash-only route.

---

## 4. What the previous agent got wrong, so it is not repeated

- Reported a system state from a single probe and called it definitive.
- Concluded a model fleet was dead from a `503`, which means minutes, not days.
- Told the editor their API key was invalid, on the strength of a probe that
  had mangled the key itself.
- Reported "zero successful calls ever" from a case-sensitive comparison bug.
- Invented a per-model limit from a stale prose note, then reported the
  resulting block as an external quota limit.
- Prescribed a start command that silently corrupted the API key.
- Summed role budgets by hand, omitting two unwired roles, and cut a real
  budget because of the phantom total.

`AGENTS.md` has the full list with the reasoning. The pattern is one thing: a
conclusion stated with more confidence than the evidence supported, and
verification deferred until someone pushed back.
