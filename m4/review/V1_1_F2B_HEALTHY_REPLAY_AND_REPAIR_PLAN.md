# V1.1-F2B — Verified External Capacity + Healthy Replay + Repair Partition

**Status: STOPPED AT THE §1 PRECONDITION. No replay was performed.**
`m4/review/V1_1_F2B_HEALTHY_REPLAY_AND_REPAIR_PLAN.md`

| | |
| --- | --- |
| Predecessor | V1.1-F2A `1b2cef8` |
| §1 preflight (2026-09-26T15:30Z) | **FAILED — `RoleUnavailable`** |
| Replay performed | **none** — §1 forbids substituting a model |
| Corpus fingerprint | `d02f2b9b5a281434` — **identical to F1** |
| Corpus mutated | **no** |
| JEV calls | **0** |
| Runtime-store integrity | **259 files byte-identical** |

---

## 1. Executive verdict

> **F2B is externally blocked. And the capacity check that §2 required can be
> answered today, without a replay — and it is the finding.**

The owner's prediction is confirmed by measurement:

> *„утрешният тест не трябва да приема „routes recovered" = „можем да направим
> 182 здрави classifications"… Ако free routes се изчерпят на 70, 100 или 140,
> това ще бъде следващият истински архитектурен резултат."*

**The bottleneck moved exactly one level up, and it is now measured.**

```text
required classifications (300-item catch-up) : 182
internal role budget (hard)                   : 1200   -> NOT limiting
known configured FREE capacity                :   60   -> 33% of requirement
DEFICIT                                        :  122
```

Three findings, in order of importance:

**1. The known configured free ceiling (60) is below the requirement (182).**
The three `operator_declared` Gemini routes declare `daily_call_limit: 20`
each — 60 total. The two OpenRouter `:free` routes declare **no limit at all**,
so their capacity is provider-determined and not knowable from configuration.
**Per §2 this alone forbids calling any future run a "healthy replay"**: even
with every route healthy, the *declared* capacity covers a third of the work.

**2. The best day ever observed answered 89 of 182 — less than half.**
Historical throughput, reconstructed from the ledger by logical request:

| day | attempted | answered | refused | success |
| --- | --- | --- | --- | --- |
| 2026-09-21 | 1 | 1 | 0 | 100% |
| 2026-09-24 | 58 | 36 | 22 | 62.1% |
| 2026-09-25 | 182 | 79 | 103 | 43.4% |
| **2026-09-26** | **332** | **89** | **243** | **26.8%** |

Throughput *decreased* as volume increased. The best single day in the entire
record (89) is **49% of what one full rebuild requires**.

**3. Today's 332 attempts prove F2A worked and the limit moved.**
Only 332 logical requests were attempted today against a hard budget of 1200.
**The internal budget was not the binding constraint at any point today** — the
external quota was. F2A removed our ceiling; it did not create capacity, and it
was never supposed to.

**This is a real architectural result, not a deferral.** The question F2B was
built to answer — *can free capacity serve 182?* — now has a measured answer
for the configured portion: **no, not on the declared limits.**

## 2. Preflight / route state

Run at **2026-09-26T15:30Z**, before anything else:

```text
generate.call_model('... {"ok": true}', role="story")
  -> RoleUnavailable
     "story: няма достъпен маршрут (липсващ ключ, лимит, изключени
      платени модели или политика)"
     ("no accessible route: missing key, limit, excluded paid models or policy")
```

**§1 outcome: STOP.** No model was substituted, no JEV call was made, no replay
was run. Current route health:

| route | status | recovers at | reason |
| --- | --- | --- | --- |
| gemini:gemini-3.6-flash | EXHAUSTED | **2026-09-27T07:00:00Z** | QUOTA_EXHAUSTED 429 |
| gemini:gemini-3.7-flash | EXHAUSTED | **2026-09-27T07:00:00Z** | QUOTA_EXHAUSTED 429 |
| gemini:gemini-3.8-flash | EXHAUSTED | **2026-09-27T07:00:00Z** | QUOTA_EXHAUSTED 429 |
| openrouter:nemotron-3-ultra:free | EXHAUSTED | **2026-09-27T00:00:00Z** | QUOTA_EXHAUSTED 429 |
| openrouter:qwen3.8-27b:free | EXHAUSTED | **2026-09-27T00:00:00Z** | QUOTA_EXHAUSTED 429 |
| openrouter:thinkingmachines/inkling:free | INVALID | — | AUTH_FAILED 403 |
| openrouter:gpt-5.6-luna / -pro | skipped | — | `paid_enabled: false` |

**Zero accessible routes.** Recovery is ~8.5 h away (Gemini) / ~8 h (OpenRouter).

## 3. Internal budget headroom

| | |
| --- | --- |
| `hard_calls_day` | 1200 |
| `soft_calls_day` | 900 |
| required for the replay | 182 |
| **headroom** | **1018** |
| actually attempted today | 332 |

**§4 assertion satisfied with large margin** — the internal budget was not and
would not have been the limiting factor. F2A achieved exactly its purpose.

## 4. External free capacity — the finding

### 4a. Configured (knowable)

| route | billing | `daily_call_limit` |
| --- | --- | --- |
| gemini:gemini-3.8-flash | operator_declared | 20 |
| gemini:gemini-3.7-flash | operator_declared | 20 |
| gemini:gemini-3.6-flash | operator_declared | 20 |
| **configured ceiling** | | **60** |

### 4b. Unknown (provider-determined)

| route | billing | declared limit |
| --- | --- | --- |
| openrouter:nemotron-3-ultra:free | free | **none** |
| openrouter:qwen3.8-27b:free | free | **none** |

No `daily_call_limit` is declared, so **no capacity figure is knowable from
configuration**, and none is invented here. Per the brief: *„Do not invent
capacity where providers do not expose it."*

### 4c. The capacity ledger (§2 / §14)

```text
required classifications              : 182
internal role budget (hard)           : 1200
known configured free capacity        :   60
unknown external capacity             :  unknown (2 free routes, no declared limit)
known deficit                         :  122   (33% covered)
best observed single-day throughput   :   89   (49% of requirement)
```

### 4d. §2 verdict

> **The known configured maximum (60) is already < 182. This run may not be
> called a possible "healthy replay."**

Any future attempt is a **measured capacity experiment**, not a healthy replay —
and its outcome must be reported as `FREE_CAPACITY_INSUFFICIENT` if the free
routes run out mid-replay, which §7 defines as outcome **B**.

**§2 also requires reporting the sustainable figures. Measured, not invented:**

| workload | semantic decisions | configured capacity | viable? |
| --- | --- | --- | --- |
| normal 37-publication refresh | ~23 | 60 | **yes** |
| 100-publication batch | ~61 | 60 | **borderline** (61 > 60) |
| 300-publication catch-up | 182 | 60 | **no** |

**Normal daily operation fits inside the declared free capacity. Rebuilds and
catch-ups do not.** That is a much sharper statement than "capacity is
sometimes a problem", and it is the actionable one.

---

## 5. Replay outcome

> ## `PRECONDITION_FAILED` — F2B is externally blocked.

Not `FULLY_HEALTHY` (A), not `FREE_CAPACITY_INSUFFICIENT` (B) as an *observed
replay outcome*, and not `OTHER_PROVIDER_FAILURE` (C).

**Distinction that matters:** B and C describe what happened *during* a replay.
F2B never reached a replay, so claiming either would be reporting a measurement
that was not taken. The honest classification is that the precondition failed.

**What is nevertheless established** is the capacity arithmetic in §4 — which is
a *configuration* fact, not a replay outcome, and was exactly what §2 asked to
be checked before burning a full replay.

Had the replay been attempted anyway (it was not), §7 predicts outcome **B**:
the internal budget has 1018 headroom, the declared free ceiling is 60, so the
run would have exhausted free capacity partway through and degraded — a
capacity result, **not** a classifier-quality result.

## 6. Semantic required / answered / degraded

No replay, so no new per-item instrumentation. The **historical** figures are
the relevant evidence and are reproduced here:

| day | required (=attempted) | answered | degraded | internal budget failures | external quota failures |
| --- | --- | --- | --- | --- | --- |
| 2026-09-24 | 58 | 36 | 22 | 0 (cap 100) | dominant (ROUTE_UNHEALTHY 19, RATE_LIMITED 10) |
| 2026-09-25 | 182 | 79 | **103** | **705 skips** | 5 quota failures |
| 2026-09-26 | 332 | 89 | **243** | **1389 skips** | 5 quota failures |

**Expected healthy condition (`required == answered`, `degraded == 0`) has never
been observed on any day with real volume.** The single 100%-success day
(2026-09-21) had exactly 1 classification.

Note the 2026-09-26 row: under the **old** cap of 100 the router was refusing
with `ROLE_HARD_BUDGET`. Under F2A's cap of 1200 those 1389 skips would not
occur — the run instead becomes bounded by external quota, which is the correct
and intended separation.

## 7. Healthy partition metrics

**Not available.** A healthy partition requires outcome A.

Stating the consequence plainly: **the corpus's true event count remains
unknown.** F0's JEV partition (197 Stories) and the live store (253) bracket
it, but neither is a verified-correct answer, and the honest position is that
**no verified-healthy partition of this corpus exists yet.**

This is why the repair partition (§16–20) below is specified as *rules and
mechanisms* rather than as a concrete list of Stories: the list cannot be
computed until a healthy partition exists, and computing it from the JEV
partition would smuggle in an unverified assumption.

## 8. LIVE vs HEALTHY partition

**Not available** — no HEALTHY partition. F1's LIVE vs NO_MODEL comparison
stands unchanged as the only verified partition result:

| LIVE vs NO_MODEL | value |
| --- | --- |
| pairs together in both | 47 |
| pairs together only in LIVE | 12 |
| pairs together only in NO_MODEL | 0 |
| identical partition? | **no** |

## 9. HEALTHY vs JEV

**Not available.** The fair comparison is deferred, and **no JEV calls were
spent** to reproduce it — F0's outputs remain valid for an unchanged corpus
(`d02f2b9b5a281434`, verified), unchanged question schema and unchanged model,
so re-running JEV would cost money to reproduce a frozen comparison. Per §12,
re-call only if a fair comparison becomes possible and the existing outputs
prove inadequate.

## 10. Known duplicate clusters

Live and NO_MODEL are identical on all five labelled clusters (F1), and JEV
reunited all of them (F0). The HEALTHY column is the missing measurement:

| event | publications | LIVE | NO_MODEL | **HEALTHY** | JEV (F0) |
| --- | --- | --- | --- | --- | --- |
| Pomorie dolphin rescue | 17 | 8 | 8 | **?** | 1 |
| Pomorie MBAL search | 17 | 11 | 11 | **?** | 1 |
| Nessebar sports capital | 4 | 4 | 4 | **?** | 1 |
| Nessebar Wi-Fi | 2 | 2 | 2 | **?** | 1 |
| Bulgaria Air flights | 2 | 2 | 2 | **?** | 1 |

**This table is the whole argument for finishing F2B.** Every labelled
duplicate cluster is still fragmented, and only one of two candidate repair
tools has been shown to fix it. Until HEALTHY is measured, choosing between
"fix the corpus" and "add JEV" is choosing blind.

## 11. Every cross-Story merge audit

**Not performed** — no HEALTHY merges exist to audit.

F0's audit of JEV's 32 proposed cross-Story merges stands: **32/32
`CLEAR_SAME_STORY`, 0 `WRONG_MERGE`, 0 `UNCERTAIN`**. That result is real and
unchanged, but it audits the JEV candidate, not the healthy classifier.

## 12. Precision / recall

| | HEALTHY (existing) | JEV (F0) |
| --- | --- | --- |
| known-cluster recall | **unmeasured** | 15/15 |
| cross-Story precision | **unmeasured** | 32/32 |
| false merges | **unmeasured** | 0 |
| semantic calls/item | ≤ 0.607 | 0.80 |
| failures | provider quota | 0 in 240 |
| mean latency | ~4.2 s (F1) | 0.28 s |
| permanent dependency | existing | additional |

**The comparison remains structurally unfair to the existing classifier** — it
has never been funded. Declaring a winner on recall alone would be the error
the owner explicitly warned against.

## 13. Shortlist-limit findings

**Not measured this run** (§22 forbids changing it, and no replay occurred).

F1's finding stands: `SHORTLIST_SIZE = 5` while the candidate pool grows
unbounded — the 16th dolphin item had 16 scoring candidates and only 5 were
returned. Unchanged, and it remains a plausible **latent recall ceiling**
distinct from both budget and classifier quality. A later narrow tuning slice
may be warranted, once a healthy baseline exists to measure it against.

## 14. Latency

No new measurement. F1's observed **~4.2 s mean per semantic answer** stands as
the only figure, and it is operationally significant:

```text
182 classifications x 4.2 s  =  ~764 s  (~12.7 min) of pure classifier time
```

That is a *throughput* problem layered on top of the capacity problem, and it
reinforces §15: even a fully funded classifier at current latency would need
~13 minutes to rebuild the corpus. Not optimized here, per §15.

## 15. Is JEV needed?

> **Undetermined — and that is now a sharper statement than before.**

F2B cannot conclude anything about classifier quality, because the classifier
was never funded. But it **can** conclude something about the architecture:

* the free-only routing configuration declares **60** classifications/day;
* a catch-up needs **182**;
* the best day ever observed answered **89**;
* normal daily operation (~23) **does** fit.

So the honest position is:

> **For normal daily operation, the free-only architecture is sufficient and no
> second dependency is justified. For rebuilds and catch-ups, it is not — and
> the choice between paid fallback, JEV fallback, more free capacity, or
> accepting degraded grouping is a genuine architectural decision that should
> be made deliberately rather than by accident.**

That is a real narrowing of the decision, and it is the most useful thing F2B
produced.

---

## 16–20. Repair design (specified, not executed, not enumerated)

**No concrete Story list is produced**, because a healthy target partition does
not exist (§7). What follows is the *mechanism*, derived from the real schemas,
so that F2C can enumerate the instant a healthy partition is available.

### 16. Repair buckets — recomputed, not reused

For each proposed consolidation, classify the source Story ids against canonical
references. **F0's bucket counts are not carried forward**; the buckets are
recomputed per §16, because the merge set will differ.

| Bucket | Definition | Automatic? |
| --- | --- | --- |
| `SAFE_EMPTY_FRAGMENT` | no Article lineage, no editor metadata | yes |
| `HAS_ARTICLE_LINEAGE` | exactly one side owns an Article | yes, with a fixed survivor rule |
| `HAS_EDITOR_METADATA` | reviewed/followed state exists | case by case |
| `MULTIPLE_ARTICLE_LINEAGES` | Articles on both sides | **no — manual** |
| `OTHER_CONFLICT` | ignore/override conflict | **no — manual** |

F0's encouraging result (`MULTIPLE_ARTICLE_LINEAGES` = 0) **must be recomputed**,
not assumed: a different partition merges different pairs.

### 17. Canonical-survivor rules

```text
exactly one side owns Article lineage  ->  THAT story_id survives
zero Article lineages                  ->  deterministic survivor (below)
two or more Article lineages           ->  no automatic repair
```

For the no-lineage case, the deterministic survivor is chosen by the store's own
canonical signals, in this order:

1. the Story owning the `ORIGIN` member (earliest publication);
2. ties broken by the lexicographically smallest `story_id` (hash-derived, so
   it is arbitrary but stable and never depends on iteration order).

**Never** `Article.story_id` is rewritten. That is the invariant that makes the
whole repair identity-preserving.

### 18. Editor-metadata implications

Metadata lives outside the Story store in `story_editor_metadata.json`
(`followed`, `last_reviewed_at`, `reviewed_development_ids`).

| Field | Merge rule | Rationale |
| --- | --- | --- |
| `followed` | **OR** — survivor becomes followed if any side was | following is an editor *intent* to watch an event; splitting it silently would lose that intent |
| `last_reviewed_at` | **max** — the most recent review wins | a later review is strictly more informed about the merged event |
| `reviewed_development_ids` | **union** | development ids are content-derived (`sha256(story_id, item_id)`) and independent of the Story, so a union is lossless **provided the survivor id is stable** — see §20 |
| `IGNORED` story status | **blocking** | an editor explicitly ignoring an event must never be auto-merged into another Story |

**Any conflicting editor intent blocks automatic consolidation** and is reported
rather than resolved by a guessed "latest wins" rule. The `IGNORED` case above is
the concrete instance.

### 19. Member / relation rewrite

For each consolidation, into the survivor:

* move every non-survivor member verbatim — `item_id`, `publication_key`,
  `added_at`, `relation` are **preserved, never regenerated**;
* the moved member's `relation` is set to `SAME_STORY` with
  `relation_source = first_item` (the existing source label) — **no semantic
  history is fabricated**: the merge is recorded as a structural consolidation,
  not as a classifier verdict;
* `story_store.refresh_times` recomputes the timestamps from the real member
  timestamps, never from "now";
* validation runs through the existing `story_store.validate_store`, which
  already refuses a member belonging to two Stories.

### 20. Retired Story ids — a real gap

Requirement: no dangling Article references, no silent id reuse, no accidental
resurrection on refresh.

**The current store does not support this.** `STORY_FIELDS` has no alias or
tombstone, and `story_id_for_item()` resolves only live members. After a
consolidation, a removed Story id would be:

* **resurrectable** — an item re-added by a later collection pass would
  `story_store.new_story(...)` and hash to a *different* id, so the old id would
  not literally return, but the **event would split again** with no record that
  it had been merged;
* **untraceable** — nothing would record that `sabc…` became `sdef…`.

`overrides` (SPLIT/MERGE, currently 0 rows) is the existing mechanism and the
right home: a `MERGE` override already exists in
`story_identity.merge_stories`, and `rebuild()` already refuses to run when
overrides are present.

**Smallest required mechanism:** record a `MERGE` override per consolidation
(`{action, at, from_story, to_story, note}`) via the existing
`story_store.record_merge_override`. That gives provenance, blocks a rebuild
from silently discarding the decision, and requires **no schema change**.

*Designed here, implemented nowhere.*

### 21. Future ingestion after repair

A new publication arriving post-repair must attach to the survivor through
**ordinary grouping** — the repair moves members into a real Story, so
`shortlist()` and `strong_anchor()` see it with no special-casing. No side
table, no alias lookup in the hot path, and no divergence between what the
editor sees and what grouping believes.

This is why §20 uses the existing override pattern rather than inventing a
redirect map: the override is audit metadata, not a routing input.

## 22. Runtime-store integrity

| | |
| --- | --- |
| Stores guarded | `var/newsroom` (7), `var/editorial_workflow` (252) |
| Files hashed | **259** |
| Differences | **0** |
| Result | **BYTE-IDENTICAL** ✅ |

No replay state was created. No Story merged, no id rewritten, no member moved,
no Article or editor-metadata record touched. No refresh, no Research, no Quick
Draft. **Zero JEV calls.**

## 23. Explicitly deferred

| Item | Status |
| --- | --- |
| Corpus repair | ❌ **not performed** — no merge, no id deletion, no member move |
| JEV | ❌ **not integrated, 0 calls.** F0/F2A evidence only |
| Paid routes | ❌ `paid_enabled: false`, unchanged |
| Grouping thresholds | ❌ `SHORTLIST_SIZE`, anchors, strong-overlap all unchanged |
| Today / Quick Draft / research / Article workflow / ranking | ❌ untouched |
| F0's JEV buckets reused | ❌ **recomputation required**, not reuse |
| Repair execution | ❌ a later, separately approved slice |

## 24. Exact next slice

> ### An explicit capacity decision is required before any further replay.

**Not** `V1.1-F2C` yet: §27 says that if free capacity is insufficient, an
explicit capacity decision comes first. That condition is met.

| Option | What it buys | What it costs |
| --- | --- | --- |
| **A. Bounded paid fallback** | restores the missing ~122 classifications/day; uses the already-configured `gpt-5.6-luna` routes | real spend; needs a bounded per-day cap |
| **B. JEV as fallback/confirmer** | F0 measured 32/32 precision, 0 false merges, 0.80 calls/item, 0.28 s | a second permanent dependency in the ingestion path |
| **C. More free capacity** | more Gemini `operator_declared` models, or declared limits on the two `:free` routes | depends on provider willingness; limits are operator-declared, not guaranteed |
| **D. Accept degraded grouping** | nothing to build | the corpus stays fragmented; F2A's warning becomes permanent |

**Measured inputs for that decision** (all from this report):

```text
normal daily operation   ~23 classifications  -> fits in 60  -> no action needed
100-publication batch    ~61 classifications  -> exceeds 60 by 1
300-publication rebuild  182 classifications  -> exceeds 60 by 122
best observed day         89 answered
per-classification latency ~4.2 s -> ~13 min for a full rebuild
```

**Recommendation: decide A–D explicitly, then re-run F2B's replay arm as a
measured capacity experiment** (routes recover 2026-09-27T07:00Z). The
partition comparison, the cross-merge audit and the fair HEALTHY-vs-JEV test all
become possible the moment a funded classifier exists — and remain impossible
until then.

**The corpus repair must not be planned against the JEV partition.** Doing so
would bake an unverified grouping into canonical state, which is precisely the
outcome this whole sequence has been avoiding.
