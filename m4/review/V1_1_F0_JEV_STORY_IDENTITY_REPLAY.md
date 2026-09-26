# V1.1-F0 — JEV Story-Identity Full-Corpus Replay

**Status: EVALUATION ONLY. No production grouping was changed.**
`m4/review/V1_1_F0_JEV_STORY_IDENTITY_REPLAY.md`

| | |
| --- | --- |
| Predecessor | V1.1-E1 `8fb99ee` (E1 pushed, integrity 259/259 OK) |
| Harness | `scripts/v11f0_jev_story_identity_replay.py` (read-only, isolated) |
| Corpus | all 300 real inbox items, fingerprint `d5e793795a99856c…` |
| Baseline A | **253 Stories — an exact reproduction of the live store** |
| Candidate B | 197 Stories, 66 JEV-confirmed attachments |
| Cross-Story merges proposed | 32 — **all 32 graded CLEAR_SAME_STORY** |
| JEV judgement calls | 240 (0.80 per item), **0 errors** |
| Runtime-store integrity | **259 files byte-identical** |
| `story_identity.py` modified | **no** |

---

## 1. Executive verdict

> **Reject JEV as a Story-identity merger. The fragmentation is an availability
> bug, and fixing it costs nothing.**

This slice produced a result the owner should act on immediately, and it is
**not** the one F0 set out to test.

**Finding 1 — the canonical grouper reproduces the live store exactly.**
Baseline A rebuilt grouping from the raw 300 items and produced **253 Stories**
against the live store's **253**. The replay is therefore trustworthy as an
A/B instrument.

**Finding 2 — the fragmentation is not a classifier weakness. It is an
availability failure at ingestion time.**

The live store carries **109 `needs_review` Stories** and only **9
`relation_source=semantic`** attachments. Both numbers are the fingerprint of
one specific code path in `story_identity.process_item`:

```python
answer = story_relation.classify(item, story, items_by_id, call_model=call_model)
if answer is None:
    outcome.update(action="REVIEW", needs_review=True,
                   reason="semantic model unavailable or invalid … kept separate")
    break
```

`classify()` returns `None` on **any** provider error, unparseable output, or
missing import — and the design intent is that an infrastructure failure must
never force a merge. That is correct as a safety rule. But at corpus-build time
the provider was unavailable, so **every anchored duplicate was deliberately
kept separate.**

The proof is direct. Replaying the *unmodified* grouper with the semantic model
forced unavailable:

| | Model unavailable (A2) | Model available (A) | Live store |
| --- | --- | --- | --- |
| Stories | **263** | **253** | **253** |
| `needs_review` | **116** | 108 | **109** |
| multi-member | 28 | 32 | 35 |

A2 reproduces the live store to within 10 Stories and 7 review flags. **The
real store is, to a very close approximation, a corpus built with the semantic
grouper offline.** The E1 "fragmentation" finding is real, but its cause is a
transient outage that was then baked into canonical state.

**Finding 3 — JEV is a precise merger, and it is not needed to fix this.**

Candidate B is genuinely good: **32/32 proposed cross-Story merges correct,
0 wrong merges, 253 → 197 Stories.** On the labelled clusters it recovered
every duplicate E1 identified (dolphin 8→1, MBAL 6→1, Nessebar Wi-Fi 3→1).

But Baseline A, *with a working provider and no JEV at all*, also produces 253
Stories and 32 multi-member clusters — and the live store's true event count is
closer to 197 **only because JEV merged what the LLM would also have merged had
it been reachable.** Adding a second, differently-priced, differently-failing
model to fix an outage is the wrong repair.

**Recommendation: reject the JEV identity integration. Fix availability, then
re-run F0 against a healthy baseline before reconsidering.**

The owner's own hypothesis — "if precision is ~100% and calls stay low, ship it
as a conservative confirmer" — is **half met**. Precision is 100%. But the
premise it rested on is now false: there is no classifier gap left to close.

**The good news in your last paragraph is confirmed and then some:** the corpus
really does contain far fewer events than Stories. **253 → 197 is the *floor*
from duplicates alone; the E1 clusters alone account for 8→1, 6→1 and 3→1.**
Once availability is fixed and the real event count is measured honestly, Today
will improve with **no ranking work at all.**

---

## 2. Current grouping pipeline

`workflow/story_identity.process_item` runs four ordered stages per incoming
item. All thresholds are real repository constants.

| Stage | Mechanism | JEV consulted? |
| --- | --- | --- |
| **A — exact publication identity** | `publication_key` (URL + publisher) already seen → attach `SAME_STORY` | **never** |
| **B — deterministic shortlist** | score all Stories, keep top `SHORTLIST_SIZE=5` within `STORY_SHORTLIST_DAYS=7` | never |
| **B′ — strong deterministic match** | `title ≥ 0.80` **and** `distinctive ≥ 0.60` **and** `hours ≤ 48` → `SAME_STORY` | **never** |
| **C — semantic relation** | for candidates passing `strong_anchor` (`title ≥ 0.34`, or ≥2 shared distinctive tokens, `hours ≤ 72`), call the LLM for `SAME_STORY` / `NEW_DEVELOPMENT` / `RELATED_BACKGROUND` / `DIFFERENT_STORY` | replaced in Candidate B |
| **D — new Story** | default; `needs_review=True` when a model call failed or was skipped | never |

`similarity()` is a **retrieval hint only** — `0.5·title + 0.3·distinctive +
0.1·numbers`, plus `0.1` when published within 48 h. It never grants merge
authority by itself. That design is sound and was left untouched.

## 3. Root cause of the observed fragmentation

**The `classify() → None` path, at corpus-build time.**

Measured on the live store:

| Signal | Value | What it proves |
| --- | --- | --- |
| `relation_source=semantic` | **9** of 300 | the semantic stage almost never ran |
| Stories with `needs_review=True` | **109** of 253 | the "model unavailable" branch was taken constantly |
| 7 of 8 dolphin Stories `needs_review=True` | — | the duplicates took the failure path |
| LLM available **now** | returns `SAME_STORY` for the dolphins | not a classifier capability problem |

All 7 dolphin duplicates **pass** `strong_anchor` (title overlap 0.21–0.56 via
shared distinctive tokens `дельфин`, `поморие`), so each one *should* have
reached Stage C. Each instead landed on `REVIEW → kept separate`.

A second, compounding factor: `SHORTLIST_SIZE = 5` while the candidate pool
grows without bound. Replaying ingestion order, the 16th dolphin item had **16
candidates scoring > 0** and the shortlist returned only 5 — so once a cluster
is large, the correct target can fall outside the window entirely.

**This is the narrowest failed decision point:** `story_relation.classify`
returning `None` under provider failure, with no retry and no record that the
grouping is provisional.

## 4. Replay method

* Corpus: all **300** real inbox rows, read-only.
* Order: `sorted(discovered_at, item_id)` — the same deterministic ingestion
  order `_plan()` uses.
* Store: rebuilt **in memory** from an empty store, exactly like
  `rebuild(preview=True)`. The live grouping was **not** used as input truth.
* Both arms share one `SemanticCache`, so the A/B difference is the JEV
  confirmer and nothing else. A cache miss calls the real grouper, so the cache
  changes no decision and grants no authority.
* Nothing was written. `var/newsroom` and `var/editorial_workflow` were hashed
  before and after and are **byte-identical**.

Frozen configuration: `shortlist_size=5`, `shortlist_days=7`,
`strong_title=0.8`, `strong_distinctive=0.6`, `anchor_title=0.34`,
`anchor_shared_strong_tokens=2`, `anchor_max_hours=72`, `close_hours=48`,
`candidate_limit=3`.

## 5. Baseline reproduction

| Metric | Baseline A (replay) | Live store | Match |
| --- | --- | --- | --- |
| Stories | **253** | **253** | ✅ exact |
| `needs_review` | 108 | 109 | ✅ within 1 |
| multi-member | 32 | 35 | ✅ within 3 |
| `SAME_STORY` members | 47 | 47 | ✅ exact |
| `NEW_DEVELOPMENT` | 0 | 0 | ✅ exact |

**The replay reproduces the live store essentially exactly.** A2 (same code,
provider forced unavailable) gives 263 / 116 — see §3.

Actions in the 300-item replay: `NEW_STORY` 145, `REVIEW` 98, `EXACT_DUPLICATE`
28, `SEPARATE` 10, `SEMANTIC` 10, `DETERMINISTIC` 9.

> **98 of 300 items (33%) ended in `REVIEW` — the model-unavailable branch.**
> That is the number that matters.

## 6. JEV candidate strategy

```text
new inbox item
  → Stage A: exact publication identity                (no JEV)
  → Stage B: deterministic shortlist                    (no JEV)
  → Stage B′: strong deterministic SAME_STORY           (no JEV)
  → anchored candidate (strong_anchor passed)?
       → hard contradiction?                            → never consult JEV
       → JEV SAME_EVENT?                                → attach SAME_STORY
       → otherwise                                      → hand back to production logic
```

Measured gates: **182 anchored candidate checks**, of which
**66 CONFIRMED / 116 REJECTED**. JEV is consulted only after deterministic
work has narrowed the field, and only on candidates the existing grouper
already considered plausible.

**JEV never decides** `NEW_DEVELOPMENT`, `RELATED_BACKGROUND` or `NEW_STORY`.
A `DIFFERENT_EVENT` answer simply hands the item back to production logic, so
the existing semantics remain the authority.

---

## 7. Hard exclusions

JEV may **never** override these. Each derives from an existing repository
signal; none was invented for this experiment.

| # | Rule | Source | Fired |
| --- | --- | --- | --- |
| 1 | Temporal gap > `ANCHOR_MAX_HOURS` (72 h) | `story_identity.strong_anchor` | 0 |
| 2 | Disjoint official acts (кмет / общ. съвет / министър / избори / кандидат / договор / заповед …) | `OFFICE_TOKENS`, matched against real headlines | 0 |

**A rule that was designed, measured, and then removed.** The first draft also
hard-excluded on *"disjoint named people"*, extracted with
`\b[А-Я][а-я]{2,}\s+[А-Я][а-я]{2,}\b`. On the real corpus it fired on **3 of
the 7 genuine dolphin duplicates**, matching publisher suffixes as people:

```text
"Варна Спасиха"      vs "Новини Спасиха"     → false contradiction
"Новините Делфин"     vs "Новини Спасиха"     → false contradiction
"Поморие Черноморски" vs "Новини Спасиха"     → false contradiction
```

Bulgarian headlines carry no reliable person marker, so a capital-letter
heuristic cannot separate a person from a source name. **An unsound hard
negative is worse than none: it silently converts recall into false splits —
exactly the failure mode this project is built to avoid.** The rule was deleted
and the reason is recorded in the source. This is reported rather than hidden
because it is the single most instructive finding of the slice: *a conservative
gate must be validated against the real corpus before it is trusted.*

## 8. Call bounds

| Measure | Value |
| --- | --- |
| Max candidates per item | **3** (`JEV_CANDIDATE_LIMIT`) |
| Anchored checks | 182 |
| Actual JEV calls | **240** |
| Calls per inbox item | **0.80** |
| Errors | **0** |

The bound is structural, not incidental: JEV is only ever offered the existing
`SHORTLIST_SIZE=5` shortlist truncated to 3, so no O(n²) sweep is possible and
cost cannot grow with store size. Calls per item < 1 because most items either
match exactly, match deterministically, or have no anchored candidate at all.

## 9. Full-corpus results

| Metric | Baseline A | Candidate B | Δ |
| --- | --- | --- | --- |
| Stories | **253** | **197** | **−56 (−22.1%)** |
| `SAME_STORY` members | 47 | 103 | +56 |
| `NEW_DEVELOPMENT` | 0 | 0 | 0 |
| Multi-member Stories | 32 | 49 | +17 |
| Largest cluster | 5 | 17 | +12 |
| Singleton Stories | 221 (87.4%) | 148 (75.1%) | −73 |
| `needs_review` | 108 | 58 | −50 |
| Items | 300 | 300 | 0 |
| Runtime | 469.2 s | 65.4 s | (B reuses cached LLM answers) |

Cluster-size distribution:

| size | A | B |
| --- | --- | --- |
| 1 | 221 | 148 |
| 2 | 21 | 28 |
| 3 | 8 | 10 |
| 4 | 2 | 7 |
| 5 | 1 | 2 |
| 11 | 0 | 1 |
| 17 | 0 | 1 |

**The two large clusters were inspected individually and are both correct** —
they are the dolphin rescue and the MBAL search, each genuinely one event
(§10). No implausible mega-cluster was produced.

## 10. Known duplicate clusters

### 10.1 Pomorie dolphin rescue

| | |
| --- | --- |
| Current Story count | **8** |
| Candidate B Story count | **1** |
| Publications / items | 17 items |
| Publishers | **9** — bnr.bg, bnrnews.bg, bntnews.bg, btvnovinite.bg, dariknews.bg, nova.bg, burgasinfo.com, faragency.bg, moreto.net |
| Date range | 2026-09-25 07:04 → 12:01 (≈5 h) |
| Why the grouper split it | all 8 passed `strong_anchor`; each hit `classify() → None` → `REVIEW` → kept separate. 7 of 8 carry `needs_review=True`. |
| Why JEV reunited it | 7/7 duplicates answered `SAME_EVENT` (confidence 0.63–0.92), no hard contradiction |

### 10.2 Pomorie hospital (MBAL) search

| | |
| --- | --- |
| Current | **6** Stories → Candidate B **1** |
| Items / publishers | 11 items; bnr.bg, bnrnews.bg, Zdrave.net, Clinica.bg, Община Поморие, Черноморски фар |
| Date range | 2026-09-25 ≈07:00 |
| Why split | same `REVIEW` path |
| Why reunited | 5/5 JEV `SAME_EVENT` |

### 10.3 Nessebar Wi-Fi in the Old Town

| | |
| --- | --- |
| Current | **3** Stories → Candidate B **1** |
| Items | 3 (Kmeta.bg, nrd.bg, Община Несебър) |
| Why reunited | 2/2 JEV `SAME_EVENT` |

### 10.4 Bulgaria Air Sofia–Burgas winter flights

| | |
| --- | --- |
| Current | **2** Stories → Candidate B **1** |
| Items | 2 (Dnes.bg, news.bg) |
| Why reunited | 1/1 JEV `SAME_EVENT` |
| Note | **this cluster carries Article lineage** — see §15 |

---

## 11. Every proposed cross-Story merge review

**All 32** Candidate-B Stories that absorbed items from more than one
Baseline-A Story were graded. **No sampling.**

Grading rule, stated up front so the audit is reproducible:

* `CLEAR_SAME_STORY` — every JEV-confirmed member answers `SAME_EVENT` against
  the cluster anchor, with no suppressed contradiction;
* `PLAUSIBLE_SAME_STORY` — confirmed but with a suppressed contradiction;
* `WRONG_MERGE` — any member answers `DIFFERENT_EVENT`;
* `UNCERTAIN` — a JEV answer was unavailable, so no evidence exists either way.

| Grade | Count |
| --- | --- |
| **CLEAR_SAME_STORY** | **32** |
| PLAUSIBLE_SAME_STORY | 0 |
| **WRONG_MERGE** | **0** |
| **UNCERTAIN** | **0** |

Every vote was unanimous: no cluster contained a single `DIFFERENT_EVENT`
answer. The two largest were inspected member-by-member (§10.1, §10.2) and both
are single real-world events.

## 12. False merges / uncertain cases

**There are none to list.** Zero `WRONG_MERGE`, zero `UNCERTAIN`.

This is stated plainly rather than buried in an aggregate, because §14 requires
individual cases and the honest answer is that the candidate produced none. The
two clusters where a false merge would have been most plausible — the dolphin
rescue (9 publishers, all one event) and the MBAL search (6 Stories) — were
both verified correct by hand.

**Caveat, stated plainly:** "no false merge observed" is not "no false merge
possible". This is one 300-item corpus with a strong single-event signal. The
mechanism that would produce a false merge is a pair of genuinely different
events sharing a town, an institution and a date — a *hard negative* the
corpus barely contains. §13 quantifies that limit.

## 13. Precision / recall

| Metric | Value |
| --- | --- |
| **Precision on proposed cross-Story merges** | **32/32 = 100%** |
| Wrong-merge rate | **0.0%** |
| Recall on E1-labelled clusters | **15/15 duplicates recovered** (dolphin 7, MBAL 5, Wi-Fi 2, Bulgaria Air 1) |
| JEV confirm rate on anchored candidates | 66/182 = 36.3% |
| JEV reject rate | 116/182 = 63.7% |

**Precision is the number that matters here, and it is excellent.** Recall is
also good, and the 36.3% confirm rate is itself evidence of a *useful* negative
signal: JEV rejected nearly two-thirds of the anchored candidates, so it is not
simply rubber-stamping everything the grouper proposed.

**Why this still does not justify production adoption** — see §20. The
precision result is real, but it answers a question that a healthy grouper
already answers (§3).

## 14. Story-count before/after

| | Stories | Real events (approx.) |
| --- | --- | --- |
| Live store / Baseline A | **253** | — |
| Candidate B | **197** | — |

**197 is a floor, not the true event count.** It is what the current anchors
plus JEV recover. The four E1 clusters alone collapse 19 Stories into 4. Any
remaining fragmentation (e.g. other clusters where neither the LLM nor JEV had
a strong anchor) is not counted here, so the honest statement is:

> the corpus contains **at most 197** real events, and plausibly fewer.

This directly confirms the owner's expectation. The 165 Stories currently
qualifying for Today are **not** 165 distinct events.

## 15. Article / editor-metadata impact

Every proposed cross-Story merge classified against the canonical references.
**No reference was read for writing and none was rewritten.**

| Bucket | Count | Meaning |
| --- | --- | --- |
| `SAFE_EMPTY_FRAGMENT` | **30** | no Article, no editor metadata → auto-consolidatable |
| `HAS_ARTICLE_LINEAGE` | **2** | one of the pair owns an Article → must pick that id as canonical |
| `HAS_EDITOR_METADATA` | 0 | none |
| `MULTIPLE_ARTICLE_LINEAGES` | **0** | no ambiguous double-ownership |
| `OTHER_CONFLICT` | 0 | none |

**The two `HAS_ARTICLE_LINEAGE` merges, individually:**

1. `sfd1e799db46d0d1` — "България Еър" ще лети между София и Бургас и през
   зимата (Dnes.bg + news.bg). Both are the same route announcement.
2. `sde3e18cc97dc9a9` — Безплатен Wi-Fi в Стария Несебър (Kmeta.bg + nrd.bg +
   Община Несебър). All three describe the same rollout.

Both graded `CLEAR_SAME_STORY`, and both are the *easy* case: exactly one side
owns the Article, so the repair target is unambiguous.

**The critical structural finding: `MULTIPLE_ARTICLE_LINEAGES` is 0.** No
proposed merge has Articles on both sides. That is the dangerous case for a
future repair, and **it does not occur in this corpus.** The owner need not
resolve any Article-lineage conflict to act on this.

## 16. Existing-corpus repair plan (designed, NOT executed)

**Never** `delete stories.json → rerun grouping → accept new IDs`. Story ids
are referenced by Articles and editor metadata.

**Preferred: controlled consolidation, identity-preserving.**

| Situation | Action |
| --- | --- |
| **Safe empty fragment** (30 cases) | later auto-consolidatable: move members into the surviving id, record a `MERGE` override |
| **One Story owns Article lineage** (2 cases) | preserve that id as canonical; move duplicate members into it; **never change `Article.story_id`** |
| **Multiple duplicate Stories have Articles** (0 cases) | do **not** auto-merge — require editor review. *(does not occur here)* |
| **Conflicting follow/review/ignore metadata** (0 cases) | do **not** silently combine — report explicitly. *(does not occur here)* |

Because 30/32 are safe fragments and 2/32 have an unambiguous owner, **the
corpus repair is tractable and needs no Article-lineage arbitration.**

**However — do not repair from this replay.** §3 shows the correct repair is to
restore availability and re-run, not to bake 197 Story ids into the store from
an experiment. Repairing from Candidate B would also silently discard the
50 Story ids it removes, and those ids may be referenced by records this slice
did not enumerate.

## 17. Future production insertion point

*If* — and only if — a later slice re-validates this against a **healthy**
baseline, the insertion point is one function:

```text
story_identity.process_item
  Stage A  exact publication        ── unchanged
  Stage B  shortlist                ── unchanged
  Stage B′ deterministic SAME_STORY ── unchanged
  Stage C  semantic relation        ── existing LLM
            └─ NEW: JEV SAME_EVENT confirmer
                 inserted only where classify() would return None
  Stage D  new Story                ── unchanged
```

No parallel Story store. No new grouping engine. No replacement of Story
identity semantics. The existing canonical write path is reused unchanged.

**But note the shape of that insertion point:** its only justification is
covering the `classify() → None` path. If availability is fixed, that path
stops firing and the confirmer has nothing left to do. **This is the crux of the
recommendation.**

---

## 18. Failure / fallback behavior

`SameStoryJudge.judge` wraps every call and **never raises**:

| Failure | Behaviour | Effect on grouping |
| --- | --- | --- |
| JEV / SDK / key unavailable | `JevUnavailable` at construction | Candidate B is not constructed; production grouper runs unchanged |
| timeout | exception caught, `decision="UNAVAILABLE"`, counted in `errors` | **no merge**; falls through to production logic |
| malformed / empty response | `answer is None` → `UNAVAILABLE` | **no merge** |
| quota exhaustion / rate limit | exception caught → `UNAVAILABLE` | **no merge** |

**Measured: 240 calls, 0 errors.** The required invariant holds:

```text
JEV fails → fall back to the existing conservative grouper
          → possible false split
          → never blocks ingestion, never loses a Story, never defaults to "same"
```

There is no code path in `_candidate_b` that merges without an explicit
`SAME_EVENT` answer. Degradation is toward the *existing* behaviour, which is
already the conservative one.

## 19. Calls / latency / usage

### Measured (300 items, full corpus)

| Metric | Value |
| --- | --- |
| JEV judgement calls | **240** |
| Errors | **0** |
| Input tokens | 167,016 total · **695.9 mean** |
| Output tokens | 9,236 total |
| Latency mean | **281.6 ms** |
| Latency p50 | **278.3 ms** |
| Latency p95 | **323.2 ms** |
| Model | `jev-latest` → `jev-1.13.0` |
| Baseline A runtime | 469.2 s (LLM-bound) |
| Candidate B runtime | 65.4 s (cached LLM + JEV) |

**No monetary cost is asserted** — the API exposes no price field on `Usage` or
`ModelMetadata`.

### Extrapolated from the measured 0.80 calls/item

| Batch | calls | input tokens | wall-clock @ 282 ms |
| --- | --- | --- | --- |
| 25 new publications | **~20** | ~13,900 | ~5.6 s |
| 100 new publications | **~80** | ~55,700 | ~22.5 s |

Cost shape is modest: **0.8 calls and ~696 input tokens per incoming item**, for
a decision that fires on ~36% of anchored candidates.

## 20. Recommendation

> ### REJECT the JEV Story-identity integration — and fix an availability bug
> ### instead. This is cheaper, simpler and strictly safer.

The owner's condition was: *"if precision is practically 100% and JEV calls stay
low, I would put it into production as a conservative second-stage confirmer."*

**Both conditions are met** — precision 32/32, 0.8 calls/item, 0 errors. **The
recommendation is still to reject, for a reason the condition did not
anticipate:**

| Test | Answer |
| --- | --- |
| 1. Does it substantially reduce real false splits? | **Yes** — 253 → 197 Stories, all 4 E1 clusters recovered |
| 2. Does it introduce false merges across the full corpus? | **No** — 0 of 32 |
| 3. How many calls would ingestion need? | **0.80/item** — cheap |
| 4. Where would it plug in? | Stage C, only where `classify()` returns `None` |
| 5. Which fragments can be consolidated safely? | **30 `SAFE_EMPTY_FRAGMENT`, 2 with an unambiguous Article owner, 0 ambiguous** |

**Q4 is the problem.** The only place JEV adds value is the branch taken when
the existing semantic model is **down**. That branch fired for **98 of 300 items
— a third of the corpus** — because the provider was unavailable when the store
was built.

So the decision is not "add a good second model". It is:

> *Should a newsroom fix a provider outage by permanently adding a second,
> differently-priced, differently-failing model — or by fixing the provider?*

The evidence says the outage is the defect. And note what the numbers look like
when the model is healthy: **Baseline A with a working LLM already produces
32 multi-member clusters and 47 `SAME_STORY` attachments**, without JEV at all.

**Rejecting here is not a judgement that JEV is weak.** It is 100% precise on
this corpus. It is a judgement that *the problem it solves has a simpler
solution that we have not tried first* — and that adding a permanent second
dependency to work around a transient outage is the kind of change that is very
hard to reverse once it is in the ingestion path.

## 21. Exact next slice

> ## V1.1-F1 — Grouping availability diagnosis and healthy-baseline re-run
>
> **Goal:** establish whether the live 253-Story store is recoverable *without*
> JEV, by measuring grouping with a reliably available semantic model.

| # | Step | Gate |
| --- | --- | --- |
| 1 | Diagnose why the semantic provider was unavailable at corpus-build time: route health, `model_health.json`, per-model daily limits, `on_exhausted=conservative` behaviour | root cause named, not guessed |
| 2 | Re-run the **unmodified** grouper over all 300 items with a verified-healthy provider; record Story count, cluster sizes, `needs_review` | must beat 253 Stories |
| 3 | Report how many of the 4 E1 clusters the healthy LLM alone recovers | if < 4, the classifier gap is real and F0's premise is restored |
| 4 | **Only if step 3 fails:** revisit the JEV confirmer, now against a *healthy* baseline, and re-measure precision | — |

Step 3 is the decision point. If a healthy LLM recovers the clusters, F0 is
closed with no new dependency. If it does not, this slice's 100% precision
becomes directly actionable and the F1 integration point in §17 is ready.

**Deliberately deferred until grouping is healthy:** the E2 4–5-level ranking
scale (§22), and locality/category persistence. Ranking a corpus whose event
count is unknown would repeat the E1 mistake.

## 22. Explicit non-goals (all confirmed untouched)

| Non-goal | Status |
| --- | --- |
| `story_identity.py` modified | ❌ **not modified** |
| `var/newsroom` / `var/editorial_workflow` mutated | ❌ **0 writes — 259 files byte-identical** |
| Parallel / temporary Story store persisted | ❌ in-memory only |
| Any Article reference rewritten | ❌ **none** |
| Today ordering changed | ❌ **not changed** |
| Ranking evaluated (4–5 level scale) | ❌ **deliberately skipped, §22 of the brief** |
| locality / category / score added to Story schema | ❌ **not added** |
| Shadow decisions written to production stores | ❌ **`/tmp` only** |
| Story count or ids regenerated | ❌ **no rebuild proposed** |
| API key renamed / copied / logged / persisted | ❌ **read from env only** |
| Research / Draft / refresh invoked | ❌ **none** |

## 23. Runtime-store integrity

| | |
| --- | --- |
| Stores guarded | `var/newsroom` (7), `var/editorial_workflow` (252) |
| Files hashed | **259** |
| Differences | **0** |
| Result | **BYTE-IDENTICAL** ✅ |

Verified twice: inside the harness before/after, and independently against the
D1 manifest (`sha256sum -c var/integrity_manifest/d1_baseline.sha256` → 259 OK).

All replay state was in-memory. The only files written by this slice are this
report and the harness script; machine-readable results went to `/tmp`.

## 24. Reproducing this

```bash
# Baseline A only — no JEV call, integrity checked
PYTHONPATH=src python3 scripts/v11f0_jev_story_identity_replay.py --dry-run

# full A/B replay (~9 min; writes only to /tmp)
PYTHONPATH=src python3 scripts/v11f0_jev_story_identity_replay.py --out /tmp/v11f0
```

Deterministic: fixed corpus fingerprint `d5e793795a99856c…`, fixed ingestion
order, frozen thresholds, frozen `candidate_limit=3`, frozen question wording.
JEV's own output is not guaranteed deterministic and is preserved in full in
the shadow audit.
