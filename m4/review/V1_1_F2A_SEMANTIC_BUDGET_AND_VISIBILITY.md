# V1.1-F2A — Semantic Budget Sizing + Grouping-Degraded Visibility

**Status: IMPLEMENTED. Conservative fallback behaviour unchanged.**
`m4/review/V1_1_F2A_SEMANTIC_BUDGET_AND_VISIBILITY.md`

| | |
| --- | --- |
| Predecessor | V1.1-F1 `1c8a0d7` (root cause `B. SEMANTIC_BUDGET_EXHAUSTION`) |
| Internal role budget | `soft_calls_day` 60 → **900**, `hard_calls_day` 100 → **1200** |
| `on_exhausted` | **`conservative` — unchanged** |
| `global.paid_enabled` | **`false` — unchanged** |
| New status | `healthy · degraded · budget_exhausted · unavailable` |
| Runtime-store integrity | **259 files byte-identical** |
| Existing Story store repaired | **no** — nothing merged, no id rewritten |
| JEV integrated | **no** |

---

## 1. Implemented

Two changes, both deliberately small:

1. **Internal budget sizing.** The `story` role's daily budget is raised from
   60/100 to 900/1200, sized from *measured* demand (§4–5). Nothing else in the
   routing policy changed.
2. **Grouping-degraded visibility.** A run now records whether its identity
   stage could classify everything it needed to, and Today shows one compact
   editor-language warning when — and only when — that did not happen.

**Not changed:** the conservative fallback, the shortlist, the anchors, the
thresholds, the semantic prompt, `SAME_STORY` semantics, the Story schema, and
any paid route.

## 2. Budget semantics — what the counters actually measure

This mattered more than expected, and F1's raw numbers would have produced a
badly sized budget.

`model_usage.role_calls_today()` counts **distinct logical requests**, not
ledger rows:

```python
"""Distinct **logical requests** for a role today (B4): one `call_role()`
invocation is one request however many routes it skipped"""
```

Verified by reconstructing the unit from the persisted ledger:

| day | raw ledger rows | **logical story requests** | answered |
| --- | --- | --- | --- |
| 2026-09-24 | 58 | 58 | 36 |
| **2026-09-25** | **980** | **182** | **79** |
| 2026-09-26 | 1956 | **331** | 89 |

| Counter | Increments when |
| --- | --- |
| `soft_calls_day` / `hard_calls_day` | once per `call_role()` invocation, **regardless of how many routes were skipped or retried** |
| route skips (`provider_attempts=0`) | **not** a provider call; a skipped paid/unhealthy route still counts as one logical request |
| provider retries on a route | **not** a separate role request (only `provider_attempts`) |
| per-model `daily_call_limit` | counted **separately**, per provider attempt |

**Sizing from the 1000 ledger rows would have been a ~5.5× over-estimate.** The
correct unit is 182–331. One `story_relation.classify()` call produces exactly
one logical request.

## 3. Measured demand

From the F0/F1 instrumented replay over the real 300-item corpus:

| Measure | Value |
| --- | --- |
| items processed | 300 |
| deterministic / exact matches | 47 (`SAME_STORY` members) |
| items with no usable candidate | remainder → new Stories, **no model needed** |
| **anchored items requiring semantic classification** | **182** |
| anchor rate | **0.607 consultations per new item** |
| max consultations for one item | 1 (the loop breaks on the first decision) |

**The system already has the correct efficiency property: one classification per
publication maximum, because `process_item` breaks on the first decision.**

## 4. Normal refresh vs catch-up

| Workload | Basis | New publications | Semantic consultations |
| --- | --- | --- | --- |
| **Normal incremental day** | 2026-09-26 real run | 37 | **~23** (37 × 0.607) |
| **Backlog / startup catch-up** | 2026-09-25 rebuild, measured | 300 | **182** (measured) |
| **Worst observed day** | 2026-09-26 ledger | — | **331** (measured) |
| **First substantial ingestion** | 2026-09-21 | 99 | **~60** (derived) |

The old budget of 100 was below the **measured catch-up requirement of 182** —
it could not complete a single full rebuild, which is exactly what happened.

## 5. New budget — values and reasoning

```text
BEFORE:  soft_calls_day = 60    hard_calls_day = 100
AFTER:   soft_calls_day = 900   hard_calls_day = 1200
```

| Criterion | Value | Reasoning |
| --- | --- | --- |
| hard ≥ measured catch-up (182) | 1200 = **6.6×** | the worst observed day (331) is the real floor; 1200 ≈ 3.6× that |
| hard finite | 1200 < 10 000 | asserted in tests — not an unbounded "unlimited" |
| soft < hard | 900 | — |
| soft does not warn on a normal day | 900 ≫ 23 | a normal refresh never warns |
| soft does not warn on a catch-up | 900 > 182 | a legitimate rebuild does not immediately warn |
| paid routes not required | unchanged | budget assumes free routes only |

**Why 1200 and not 200?** A hard cap below the worst *observed* day would simply
reproduce this bug on the next heavy day. 1200 absorbs the measured peak with
roughly 3.6× headroom, is a finite number an operator can reason about, and is
still ~8× below "unlimited". If real demand ever approaches it, the **soft**
warning fires first at 900 and the operator sees `degraded` on Today before any
quality is lost.

**This does not guarantee free capacity** — that is the next section.

## 6. Provider capacity is a separate limit

Three independent limits are now distinguished rather than conflated:

```text
INTERNAL_ROLE_BUDGET   -> status: budget_exhausted   (self-imposed, fixable in config)
EXTERNAL_PROVIDER_QUOTA-> status: unavailable        (HTTP 429, outside our control)
PAID_POLICY            -> status: unavailable        (routes skipped by policy)
```

`story_relation.classify_failure()` reads the router's own trace and maps the
internal-limit marker to `budget_exhausted`; everything else — quota, auth,
provider outage, no key — is `unavailable`. A test asserts these are **not**
conflated, because they need different operator responses: one is a config
change, the other is waiting or changing provider.

Raising the internal budget does **not** create capacity. It only stops the
newsroom from refusing to use capacity it already pays for.

---

## 7. Grouping health — exact state semantics

Derived by `grouping_health.GroupingHealth` from one run's counters:

| Status | When |
| --- | --- |
| `healthy` | no semantic decision was needed, **or** every needed one was answered |
| `budget_exhausted` | degradation occurred and **every** degraded item failed on the internal role budget |
| `unavailable` | degradation occurred and **every** degraded item failed for an external reason (quota, auth, outage, no key) |
| `degraded` | degradation occurred with **both** causes present, or an unrecognised failure |

Two decisions worth stating explicitly:

* **A run that never needed the model is `healthy`, not `unavailable`.** Reporting
  "unavailable" because nothing asked would train the operator to ignore the
  signal — the opposite of the slice's purpose. Pinned by test.
* **Mixed causes report `degraded`**, not a single cause, because a single label
  would be a claim the evidence does not support.

**This is deliberately not source-collection health.** "The feeds are down" and
"grouping could not classify" are different problems with different fixes, and
Today already reports collection problems separately.

## 8. Run counters

Persisted in the existing latest-run record (`var/newsroom/last_run.json`) under
a `grouping` key — **no new store**:

```json
{
  "grouping": {
    "status": "budget_exhausted",
    "lastSuccessfulSemanticClassificationAt": "2026-09-26T07:10:00Z",
    "semanticRequired": 182,
    "semanticAnswered": 79,
    "semanticDegraded": 103,
    "semanticDegradedBudgetExhausted": 103,
    "semanticDegradedUnavailable": 0
  }
}
```

| Counter | Counts | Does **not** count |
| --- | --- | --- |
| `semanticRequired` | publications that reached the anchored shortlist | deterministic-only decisions |
| `semanticAnswered` | classifications that returned a usable relation | — |
| `semanticDegraded` | **quality loss**: needed a decision, did not get one | `NEW_STORY` with no candidate; exact-publication matches; deterministic `SAME_STORY`; deliberate `DIFFERENT_STORY` |

`semanticDegraded` is the metric F1 said was missing. **It is a measure of
quality loss, not of traffic** — a run that grouped 200 items perfectly reports
`0`.

`lastSuccessfulSemanticClassificationAt` is taken from the run itself (the
recorder stamps it at the moment of a successful classification), not from a
ledger scan, so it answers the run-specific question directly.

## 9. Today behaviour

A single compact line, **only when grouping actually degraded**:

| Status | Rendered (editor language) |
| --- | --- |
| `budget_exhausted` | `Лимитът за групиране е изчерпан. Част от публикациите може да се показват като отделни истории (103 публикации).` |
| `unavailable` / `degraded` | `Групирането на истории е ограничено. Част от публикациите може да се показват отделно (40 публикации).` |
| `healthy` | **nothing** |
| unknown (pre-F2A run) | **nothing** |

Explicitly **not** rendered anywhere in the editor DOM: `ROLE_HARD_BUDGET`,
`gemini`, `openrouter`, `429`, model ids, route ids, "quota", "provider". A
backend test and a frontend test both assert this against the rendered output.

**Healthy is quiet by design.** No permanent green status chrome: operational
health that is always visible is operational health the editor stops reading.

Recovery needs no browser reload — «Обнови» refetches the projection, and the
notice disappears because the canonical latest-run state changed. Proven in the
browser (§13) and in Vitest.

## 10. Paid policy — confirmed unchanged

```text
global.paid_enabled == false     (unchanged, asserted in tests)
```

Historical `PAID_DISABLED` skips, reported but **not** acted on:

| day | `PAID_DISABLED` skips |
| --- | --- |
| 2026-09-25 | 211 |
| 2026-09-26 | 480 |

Paid fallback remains a later, explicit owner decision.

## 11. Tests

### Backend — `tests/test_grouping_health.py` (14 new)

| § | Test | Pins |
| --- | --- | --- |
| 19 | `test_story_budget_exceeds_measured_catch_up_demand_with_margin` | hard > 182 **and** > 331; soft < hard; hard < 10 000 |
| 19 | `test_soft_budget_does_not_warn_during_normal_refresh` | normal demand < soft |
| 19 | `test_paid_routes_remain_disabled` | `paid_enabled is False` |
| 19 | `test_on_exhausted_stays_conservative` | unchanged |
| 20 | `test_healthy_run_reports_healthy_and_no_degradation` | healthy, 0 degraded, last-success set |
| 21 | `test_internal_budget_exhaustion_is_reported_and_never_merges` | `budget_exhausted`, degraded > 0, **0 semantic matches**, review flagged |
| 22 | `test_provider_outage_is_unavailable_not_budget_exhausted` | `unavailable`, budget counter stays 0 |
| 23 | `test_mixed_run_keeps_last_success_and_counts_both_sides` | last-success retained, both counters right |
| 24 | `test_run_without_semantic_need_is_healthy_not_unavailable` | required = 0 → healthy |
| — | `test_today_exposes_grouping_health_when_degraded` | DTO shape |
| — | `test_today_stays_quiet_for_healthy_and_unknown` | healthy → quiet; missing block → `None` |
| — | `test_grouping_health_never_carries_provider_vocabulary` | no provider/model/HTTP leakage |
| — | `test_observability_never_changes_a_merge_decision` | a recorder that **raises** cannot suppress a legitimate merge |
| — | `test_story_store_is_untouched_by_degraded_runs` | degraded run keeps publications separate |

Budget assertions are computed from the **measured constants** (182, 331), not
magic numbers.

### Regression

`test_story_identity.py` + `test_story_operations.py`: **47 passed**, unchanged.
The observability additions are proven not to alter grouping by the existing
suite, not only by new tests.

## 12. Frontend

Vitest **124 passed** (was 118; +6):

* healthy → no warning
* unknown → no warning
* `budget_exhausted` → editor-language warning with the count
* `unavailable` → generic warning, **not** described as a budget problem
* no provider/model/HTTP vocabulary anywhere in the DOM
* warning clears after a healthy refresh, from canonical state, without reload

Typecheck, ESLint and the production build are clean.

---

## 13. Browser proof

`tests/browser/test_v11_f2a_grouping_health.py` — 4 tests, all passing against
the **real production topology**: the compiled `npm run build` bundle served by
the real Python `ThreadingHTTPServer` over the real `/api/v1`, on an isolated
store root. No Vite dev server, no preview server, no mocked client, no
intercepted response.

| Test | Proves |
| --- | --- |
| `test_degraded_grouping_is_visible_and_editor_safe` | warning renders with the real count; no provider vocabulary in the DOM; **Stories still listed, row actions still present**; console clean |
| `test_healthy_grouping_is_silent` | healthy run renders **no status chrome at all** |
| `test_a_run_without_grouping_health_shows_no_warning` | a pre-F2A run is *unknown*, not unhealthy — no false warning |
| `test_a_later_healthy_run_clears_the_warning_after_refresh` | store updated to healthy **behind the loaded page**; one «Обнови» click clears the notice; no reload |

The recovery test is the one that matters most: it changes the canonical
latest-run state without touching the browser, proving the editor is never
reading a stale signal. Playwright's strict-mode violation on
`get_by_role("status")` during refresh (the transient «Обновява се.» indicator
shares that role) is a genuine finding from this proof and the notice is
addressed by its own class instead.

## 14. Real-data read-only report

Against the normal stores. **No refresh was run, no external quota consumed.**

```text
configured story budget : soft=900  hard=1200   (was 60 / 100)
on_exhausted            : conservative          (unchanged)
global.paid_enabled     : false                 (unchanged)
```

| day | logical story requests | answered | degraded | dominant skip reason |
| --- | --- | --- | --- | --- |
| 2026-09-24 | 58 | 36 | 22 | ROUTE_UNHEALTHY 19, RATE_LIMITED 10 |
| 2026-09-25 | 182 | 79 | **103** | **ROLE_HARD_BUDGET 705**, PAID_DISABLED 211 |
| 2026-09-26 | 331 | 89 | **242** | **ROLE_HARD_BUDGET 1389**, PAID_DISABLED 480 |

The 2026-09-25 figure — **103 degraded** — matches the live store's 109
`needs_review` Stories almost exactly. That is the exact quantity F2A will now
report on the day it happens.

**Current grouping-health status of the live store: unknown** — the existing
`last_run.json` predates this field, so Today shows **no warning**. Correct: a
run that never reported grouping health cannot be claimed to have been
unhealthy.

## 15. Runtime-store integrity

| | |
| --- | --- |
| Stores guarded | `var/newsroom` (7), `var/editorial_workflow` (252) |
| Files hashed | **259** |
| Differences | **0** |
| Result | **BYTE-IDENTICAL** ✅ |

Verified against the D1 manifest (`sha256sum -c` → 259 OK). **No refresh, no
Research, no Quick Draft, no Story rewrite was run.** Every test used `tmp_path`
stores.

## 16. Regression gate

### Regression gate

| Gate | Result |
| --- | --- |
| Backend + browser suite | **1426 passed, 13 failed** |
| Pre-existing failures (measured on a stashed tree) | **identical 13** — network/provider tests, unrelated to grouping |
| New failures introduced | **0** |
| Story identity + operations | 47 passed, unchanged |
| Grouping health | 14 new, all passing |
| Browser proof | 4 new, all passing |
| Vitest | **124 passed** (was 118) |
| typecheck / ESLint / production build | clean |
| Ruff check / format / compileall / `git diff --check` | clean |

The 13 pre-existing failures were verified by stashing this slice's changes and
running the full suite on the clean tree: the failure set is byte-identical.

## 17. Explicitly deferred

| Item | Status |
| --- | --- |
| **JEV integrated** | ❌ **not integrated.** `workflow/jev.py` untouched, no TypeSafe call, no JEV config, no JEV fallback. F0 remains evidence only. |
| **Existing corpus repaired** | ❌ **not repaired.** No Story merged, no id rewritten, no `Article.story_id` touched. The 253 fragmented Stories remain until F2B. |
| **Shortlist / thresholds** | ❌ `SHORTLIST_SIZE=5`, `ANCHOR_TITLE_OVERLAP=0.34`, `STRONG_TITLE_OVERLAP=0.80`, `ANCHOR_MAX_HOURS=72` — **all unchanged** |
| **Semantic prompt / relation semantics** | ❌ unchanged |
| **Ranking / locality / category** | ❌ untouched |
| **Grouping repair / reclassification** | ❌ F2B |
| **Settings page** | ❌ not built; the DTO is shaped so it can read status, last success and degraded count without touching ledger files |
| **Paid routes** | ❌ still disabled — separate owner decision |
| **`on_exhausted`** | ❌ **unchanged at `conservative`.** Never weakened to guess `SAME_STORY`. |

## 18. Recommended next slice

> ## V1.1-F2B — Verified Healthy Replay + Identity-Preserving Corpus Repair Plan
>
> **Blocked until the free routes recover: 2026-09-27T07:00Z.**

| # | Step | Gate |
| --- | --- | --- |
| 1 | Confirm the semantic route is reachable (preflight) | a real `story` call succeeds |
| 2 | Replay all 300 items with the **unmodified** grouper and the **new** budget | budget is not the limiting factor this time |
| 3 | Compare **partitions**, not counts, against LIVE | reuse F1's co-clustering method |
| 4 | **The fair test:** healthy classifier vs JEV on the same labelled clusters | recall, precision, calls/item, failures, latency |
| 5 | Re-derive the repair buckets from the healthy partition; re-audit every cross-Story merge | fresh false-merge review |
| 6 | Design — **do not execute** — the identity-preserving repair | `Article.story_id` never changes |

**Step 4 is the question this whole sequence has been building toward.** JEV
passed its precision test; the architecture has not yet shown it *needs* JEV.
If a properly funded classifier closes the gap on its own, we keep a working
system with one fewer permanent dependency. If it does not, F0's 32/32 becomes
directly actionable and the F1 insertion point is ready.

**Note on timing:** the routes are exhausted until 2026-09-27T07:00Z. F2A's
budget and visibility changes are complete and committed-ready now; F2B should
run after recovery, when the comparison is finally fair.
