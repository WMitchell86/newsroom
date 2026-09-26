# V1.1-F2B2 — Bounded-Paid Healthy Replay

**Status: READY TOOL FOR A FAIR REPLAY — not a completed healthy-replay result.**
`m4/review/V1_1_F2B2_BOUNDED_PAID_HEALTHY_REPLAY.md`

| | |
| --- | --- |
| Predecessor | V1.1-F2B `bea21bc` |
| §1 preflight (2026-09-26T15:37Z) | **FAILED — no route reachable** |
| Replay performed | **none** |
| **Money spent** | **$0.00** — no paid call was ever made |
| JEV calls | **0** |
| Proven: isolation / caps / restoration semantics | **yes** |
| **NOT proven: real paid-provider reachability** | **see §1a** |
| `global.paid_enabled` | **`false` before and after; `true` only inside the replay process** |
| Runtime-store integrity | **259 files byte-identical** |

---

## 1. Executive verdict

> **The bounded-paid mechanism is built and its safety semantics are proven. It
> is a ready tool for a fair replay — not a healthy-replay result. One thing it
> has *not* proven is that a paid route can actually answer.**

The replay is blocked by the same external condition as F2B: 15.4 hours before
the free routes recover. **No money was spent.**

| § requirement | Status |
| --- | --- |
| §1 no permanent `paid_enabled=true` | ✅ policy file unchanged, asserted by test |
| §2 scoped, process-dying override | ✅ **`MODEL_POLICY_PATH` + a /tmp file** |
| §3 hard call cap | ✅ `MAX_SEMANTIC_CALLS = 220`, bounded and tested |
| §4 spend cap | ✅ existing `soft_paid_budget_usd_day: $2.00` used, nothing invented |
| §5 paid as fallback, not first choice | ✅ route order byte-identical, asserted |
| §6 corpus freeze | ✅ fingerprint `d02f2b9b5a281434` matches F1 |
| §7 pre-run proof | ✅ recorded |
| §20 policy restored | ✅ verified after the run |

## 1a. What is proven, and what is not

This distinction matters more than the test count, and it is recorded here so
that "8 tests passing" is never read as more than it proves.

### Proven — mechanism and policy semantics

* the normal production policy is `paid_enabled = false`, and the scoped replay
  policy is `true` **only inside the replay process**. This is the intended
  behaviour and is asserted from both sides;
* the operator override (`var/model_policy.json`) and the tracked default
  (`config/model_policy.default.json`) are **byte-identical** before and after;
* `MODEL_POLICY_PATH` is absent from the environment at exit, and the harness
  pops it in a `finally` block;
* the call cap is finite, bounded above the measured demand, and a capped run
  yields a conservative no-merge that is counted as quality loss;
* free routes still precede every paid route, so paid is a fallback by
  construction;
* the corpus is frozen to the F1 fingerprint.

### **Not proven — real paid-provider reachability**

> **No end-to-end evidence exists that a paid route can actually be invoked
> successfully.**

The preflight deliberately did **not** spend a paid call, so no paid provider
request was ever issued from this harness. The OpenAI-class paid routes have
never been exercised here: not their reachability, not their latency, not their
reported cost, and not whether the router's price table matches the provider's
actual billing.

**Consequence:** if the 2026-09-27 replay exhausts free capacity and falls
through to a paid route for the first time, the paid path is **unproven code
meeting an unproven provider.** The isolation, cap and restoration semantics are
already known-good, so a paid failure would degrade conservatively and visibly
rather than corrupt anything — but the run could still come back `DEGRADED` or
`OTHER_PROVIDER_FAILURE` for reasons this slice could not have foreseen.

This will be settled naturally by the next replay, and only if free capacity is
actually exhausted.

## 2. Temporary paid-policy scope

The repository already provides the exact hook F2B2 needed, so **no production
code was changed and no feature-flag system was built**.

`model_policy.policy_path()` reads `MODEL_POLICY_PATH` before falling back to
`var/model_policy.json`. The harness:

1. writes a minimal policy to **`/tmp/…/replay_policy.json`**;
2. sets `MODEL_POLICY_PATH` **for this process only**;
3. pops it in a `finally` block, unconditionally.

The override diff is deliberately tiny — only `global.paid_enabled`, the story
role's `hard_calls_day`, and nothing else. **The operator's
`var/model_policy.json` and the tracked `config/model_policy.default.json` are
never written**, which a test asserts by byte-comparing them around the call.

**Leak proof** (`tests/test_f2b2_scoped_policy.py`, 8 tests, all passing):

| Test | Property |
| --- | --- |
| `test_normal_runtime_policy_keeps_paid_disabled` | runtime policy reports `False` |
| `test_scoped_policy_lives_outside_the_repository` | operator + tracked policy byte-unchanged |
| `test_scoped_override_raises_then_lowers_a_cap` | honoured only while the env var is set |
| `test_route_order_is_not_reordered_by_the_override` | every free route precedes every paid route |
| `test_default_cap_is_bounded_and_above_expected_demand` | 220 is finite and above 182 |
| `test_cap_exhaustion_is_never_a_merge` | a capped run yields `None` and counts as degraded |
| `test_corpus_freeze_matches_f1` | fingerprint identical to F1 |
| `test_expected_demand_is_the_measured_f1_number` | 182 is F1's measurement |

## 3. Call / spend caps

| Cap | Value | Source |
| --- | --- | --- |
| Replay call cap | **220** | §3; 182 expected + narrow headroom |
| Scoped `hard_calls_day` | **220** | set *inside the scoped policy*, so the router's own budget stop bounds the run |
| `soft_paid_budget_usd_day` | **$2.00** | **existing policy field** — reused, not invented |
| `paid_cost_today_usd` at start | **$0.00** | measured |

**On §4's "do not invent billing estimation from token counts":** the router
already reports `paid_cost_usd` per call from its own price table, and the
existing `soft_paid_budget_usd_day` is the monetary ceiling. Both are used as-is.
No token→USD arithmetic was performed anywhere in this harness.

**Cap behaviour (§9):** the harness returns `None` — a conservative no-merge —
once the cap is passed, and counts it as `MAINTENANCE_CAP_INSUFFICIENT`. It
**never raises the cap automatically** and never continues silently.

> **A real bug this slice found and fixed in its own harness:** the first
> implementation of the cap path raised before recording anything, so capped
> items were neither counted as degraded nor as budget failures. A cap that
> hides the quality loss it causes is worse than no cap, because it would let a
> truncated replay report a healthy-looking result. The cap now routes through
> the same failure classifier as every other cause, and
> `test_cap_exhaustion_is_never_a_merge` pins that 5 capped items produce 5
> degraded and 5 budget failures.

## 4. Free vs paid usage

**No usage occurred** — the preflight failed before any classification.

```text
required semantic calls : 0 (replay never started)
answered free           : 0
answered paid           : 0
paid cost               : $0.00
```

## 5. Replay health

> ## `PRECONDITION_FAILED` — externally blocked.

Not `FULLY_HEALTHY`, not `MAINTENANCE_CAP_INSUFFICIENT`. The preflight under the
scoped policy still returned no reachable route at **2026-09-26T15:37Z**:

```text
[proof] fingerprint d02f2b9b5a281434 (frozen: True)
[proof] normal paid_enabled=False  scoped=True
[proof] route order unchanged: True
[proof] call cap 220  daily soft paid ceiling $2.0
[preflight] reachable=False provider=None model=None 421.9ms
[stop] no route reachable; no replay performed
```

**The scoped policy did its job** — `paid_enabled` was `True` in scope while the
runtime policy stayed `False`, the corpus was frozen, and route order was
intact. There was simply nothing to route to.

**Time to recovery: 15.4 hours** (Gemini routes at 2026-09-27T07:00:00Z).

---

## 6–15. Measurements that require a replay

**Not produced.** The §8 healthy criterion (`semanticRequired ==
semanticAnswered`, `semanticDegraded == 0`) has not been evaluated, so per §8
and §10 none of the following exist and **no repair conclusion is drawn**:

| § | Section | Status |
| --- | --- | --- |
| 6 | Healthy partition metrics | not produced |
| 7 | LIVE vs HEALTHY co-clustering | not produced |
| 8 | Known duplicate clusters (HEALTHY column) | not produced |
| 9 | Every cross-Story merge audit | not produced |
| 10 | Precision / recall | not produced |
| 11 | Existing classifier vs JEV | not produced |
| 12 | Latency (replay) | not produced |
| 13 | Is JEV needed? | **undetermined** |
| 14 | Repair buckets | not recomputed |
| 15 | Survivor / metadata validation | not validated against real candidates |

**What survives unchanged from earlier slices:**

* **F1** — LIVE ⊃ NO_MODEL strictly (47 shared pairs, 12 LIVE-only, 0
  NO_MODEL-only).
* **F0** — JEV precision 32/32, 0 wrong merges, 15/15 on labelled clusters.
* **F1/F2A** — the labelled clusters remain fragmented in LIVE (dolphin 8,
  MBAL 11, sports 4, Wi-Fi 2, Bulgaria Air 2).

**The comparison in §11 remains structurally unfair and is left unfair.** The
existing classifier has still never been funded; a fair verdict requires the
replay, not another argument.

**No JEV call was spent re-running the frozen comparison** (§14). The corpus
fingerprint, question schema and model are unchanged, so re-running would spend
money to reproduce a valid frozen result.

## 12. Latency

No new measurement. F1's **~4.2 s mean per semantic answer** remains the only
figure, and §21's derived cost stands: a full 182-classification rebuild is
**~13 minutes of pure classifier time**. The bounded-paid cap of 220 does not
change that; it bounds *spend*, not duration.

## 13. Is JEV needed?

> **Undetermined — unchanged, and honestly so.**

Nothing in this slice bears on classifier quality, because the classifier was
never reached. What this slice *does* establish is the **operational** half:

> For a maintenance rebuild, free-only capacity is insufficient (60 configured
> vs 182 needed) and a **bounded paid fallback is a viable, cost-capped,
> leak-proof mechanism** that requires no second semantic dependency.

So one of the four options F2B listed is now **de-risked and ready to execute**,
while the JEV-vs-existing quality question remains exactly as open. That is the
correct state of knowledge: a working mechanism, an unrun experiment.

## 16–19. Repair design status

The F2B design stands unchanged and is **still deliberately not enumerated**,
because no HEALTHY partition exists. Specifically:

* **§16 repair buckets** — F0's counts are *not* reused; recomputation is
  required from a HEALTHY partition, and none exists.
* **§17 survivor rules** — unchanged and unvalidated against real candidates:
  Article-owning id survives → else ORIGIN owner → else lexicographic; never
  rewrite `Article.story_id`.
* **§18 editor metadata** — `followed`=OR, `last_reviewed_at`=max,
  `reviewed_development_ids`=union, `IGNORED`=blocking. **Unvalidated.** §18
  asks that a real unsafe case be reported if one appears; none could be
  examined, because no candidate set exists.
* **§19 merge override** — `record_merge_override` remains the smallest
  sufficient provenance mechanism, needing no schema change. Unchanged.

## 20. Normal policy restored — proof

```text
$ python3 -c "import json; print(json.load(open('config/model_policy.default.json'))['global']['paid_enabled'])"
False

operator override var/model_policy.json contains global.paid_enabled: False
$ env | grep MODEL_POLICY_PATH      -> (nothing)
```

**Required safety gate: PASSED.** The scoped override left no residue in the
tracked policy, the operator override, or the process environment. The harness
additionally pops `MODEL_POLICY_PATH` in a `finally` block, and the test suite
deletes it in an autouse fixture so no test can inherit it.

## 21. Actual usage

```text
required semantic calls : 0
answered free           : 0
answered paid           : 0
failed                  : 0
total logical classifications : 0
wall-clock runtime      : 0.0 s (replay not started)
paid cost               : $0.00
```

**No monetary usage to report, and none is estimated.** The preflight consumed
no successful call.

## 22. Runtime-store integrity

| | |
| --- | --- |
| Stores guarded | `var/newsroom` (7), `var/editorial_workflow` (252) |
| Files hashed | **259** |
| Differences | **0** |
| Result | **BYTE-IDENTICAL** ✅ |

Replay state was in-memory and never created. No Story merge, no Article write,
no Refresh, no Research, no Quick Draft. The only file written outside the repo
is the scoped policy under `/tmp`.

## 23. Acceptance criteria for the second run

**No new slice.** The next action is **measurement, not code**: the same
command, unchanged, once the free routes have recovered.

> **2026-09-27, after 07:00 UTC (10:00 in Bulgaria)**
>
> ```bash
> PYTHONPATH=src python3 scripts/v11f2b2_bounded_paid_healthy_replay.py --out /tmp/v11f2b2
> ```

The run passes only if **all six** criteria hold:

| # | Criterion |
| --- | --- |
| **1** | `semanticRequired == semanticAnswered` **and** `semanticDegraded == 0`. Only then is the replay called **`FULLY_HEALTHY`**. |
| **2** | Free routes are used first; paid is reached only after real free exhaustion or unavailability. |
| **3** | Paid classifications stay within the **220-call cap** and reported spend within the **$2.00** ceiling. |
| **4** | After the process: normal policy is `paid_enabled = false`, `MODEL_POLICY_PATH` is absent, and the tracked + operator policy files are byte-identical. |
| **5** | **Only on `FULLY_HEALTHY`:** run LIVE vs HEALTHY, audit every cross-Story merge, compare fairly against the frozen JEV result, and recompute the repair buckets. |
| **6** | **No `V1.1-F2C`** if the replay is degraded, or if paid capacity is also insufficient. |

**Criterion 5 is conditional on purpose.** On a degraded run the healthy
partition, precision/recall and repair buckets stay **unreproduced** — exactly
as they are now. Filling them from the JEV partition would substitute a stale
hypothesis for a missing measurement, and that is the one outcome this sequence
has been built to avoid.

**Criterion 6 is the discipline that keeps the corpus safe.** A degraded replay
means the target partition is still unknown, so consolidation has no verified
basis and must not be planned.

### Branching on the measured outcome

| Outcome | Next step |
| --- | --- |
| `FULLY_HEALTHY`, precision acceptable (§15 Case A) | **Do not integrate JEV.** Freeze the architecture: daily free-only, maintenance free-first → bounded paid fallback. Then `V1.1-F2C`. |
| `FULLY_HEALTHY` but materially misses duplicates JEV finds (Case B) | Report the exact incremental value; decide on a JEV fallback **separately**. |
| `DEGRADED` with false merges (Case C) | **Stop.** Classifier quality before consolidation. |
| `DEGRADED`, paid path also failing | External/provider result. Report it; do not raise the cap. |
| `MAINTENANCE_CAP_INSUFFICIENT` | Report the measured deficit. A cap decision, never an automatic raise. |

**Not recommended: `V1.1-F2C` yet.** Corpus repair must not be planned against
the JEV partition, and no verified HEALTHY partition exists.
