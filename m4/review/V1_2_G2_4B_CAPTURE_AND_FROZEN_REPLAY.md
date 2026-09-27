# V1.2-G2.4B — one-time capture, frozen 24-Story replay, precision repair

> **Sign-off: NO — but the blocker has changed, and it is no longer internal.**

The extract cap is fixed and proven fixed. The frozen 24-Story replay ran end to
end with **zero Serper calls**. The blocker is now *editorial*, not engineering:
coverage moved 4 → 5, and the funnel says exactly why.

---

## 1. The capture (authorised once, ceiling 72)

| | |
|---|---|
| authorised ceiling | **72** queries |
| **actual spend** | **35** |
| Stories attempted | 24 / 24 |
| Stories reaching ≥2 independent publishers | **9** |
| URLs persisted with provenance | **124** |
| stop reason | `sample complete` (not the ceiling) |

The ceiling is enforced in production code, not in a script:
`SERPER_GLOBAL_QUERY_BUDGET` is read inside `run_event_discovery`, so no loop,
script or future caller can exceed it. Unset means no ceiling, so a deployment
that has genuinely paid for Serper is unaffected. Reaching it makes Serper
unavailable and Research continues without it.

Every Story persisted `discovered_urls`, the query ladder, and per-query
provider/status/result provenance. The artifact is the frozen input every later
replay consumes. **No further Search-vs-News benchmarking was performed.**

## 2. The frozen replay — all 24 Stories, zero Serper

```text
frozen stories            24
stories with discovery    24
stories replayed          24
serper calls               0      <- enforced by a tripwire that raises
```

```text
candidate claim pairs            22
deterministically rejected        0
model comparison required         0
model comparison answered         1
UNCERTAIN because unavailable     0      <- the starvation is gone
SAME_FACT / DIFFERENT / CONFLICT  0 / 21 / 0
facts promoted                    28
```

`uncertain_unavailable: 0` is the direct proof the cap fix landed: in G2.4 the
role was refusing 74 consecutive requests and comparisons fell to `UNCERTAIN`.

## 3. Precision — the bar, and a regression I had to repair

The first frozen replay promoted facts containing four defect classes the
tighter G2.4 gate had masked. Reviewing every fact found them:

1. **A sentence boundary whose space the source omitted** —
   `...съобщават от полицията.Колата, в която пътували...`. The splitter
   required whitespace, so two propositions merged into one fact. It now also
   breaks on a sentence-final mark followed directly by a capital.
2. **A related-article widget** — `ПредишнаPrevious post:Достойни личности от
   Поморие бяха наградени...` **This was the most serious defect in the entire
   slice**: a pager widget on the same publisher carried a genuinely *different*
   event into a football Story. The markers are deliberately unanchored on ``,
   because a renderer glues the label to the link and the word boundary lands
   *inside* the marker.
3. **A digit glued to a unit word** — `9се`, `2години`. Bulgarian writes a space.
4. **A subscription call-to-action** — `...присъединете към Община Поморие –
   актуални новини във Viber`. Anchored on the verb, so an ordinary sentence
   mentioning a platform is untouched.

```text
final: 28 facts promoted   WRONG = 0   CHROME = 0
```

Every one was read individually. Counter-tests prove each filter still accepts
the real sentences it must keep.

## 4. Coverage — and where the bottleneck actually is

```text
Stories with >= 1 promoted fact:   4 (G2.4)  ->  5
Stories with a blocking gap:      21 (G2.4)  ->  19
```

**This is not "осезаемо повече", and I will not call it that.** But the reason is
no longer capacity, and that is the real finding:

```text
22 candidate pairs -> 21 DIFFERENT_FACT, 1 SAME_FACT, 0 UNCERTAIN
```

The publishers **are** now found — 9 Stories carry two or more independent
publishers, and the accident Story went from **0 to 6 facts** once three
publishers were available. They simply do not phrase the same proposition in
comparable words, so the comparer correctly declines. The bottleneck is now
**claim alignment between publishers**, not semantic capacity and not discovery.

Per the standing instruction, **no further Serper is spent** on this.

## 5. Serper status

```json
{ "serper_calls_during_replay": 0,
  "serper_credits_consumed": 0,
  "product_status": "optional development / diagnostic discovery provider",
  "required_for_production_research": false }
```

Degradation verified: with the key removed the chain is
`['google_news_rss','tinyfish','ddgs']`, `serper:no-key` is recorded, nothing
crashes. The measured consequence stands: the keyless chain returns only
unresolved wrappers and zero usable publishers, so coverage depends on the
optional provider being present and funded.

## 6. Burgas Municipality (§10)

Unchanged and still proven on isolated data, no Serper involved: `www.burgas.bg`
→ identity `burgas.bg` → unanimous official resolution → PRIMARY →
first-party facts promoted → no artificial second-source requirement. Product
proof Case A: 2 facts, 1 source `Община Бургас`, no corroboration gap.

## 7. Single-source policy — recommendation carried out

**Recommend dropping it.** With the ordinary gate no longer capacity-starved, the
experiment's measured 2-Story unlock is not worth a second, weaker Draft gate. It
remains unwired and a test asserts no production module imports it.

## 8. Focus contract (§13) and routing principle (§14)

Unchanged, and frozen by test. The raised budget changed **capacity only**: first
route, provider, model, semantic prompt, SAME_FACT rules, `paid_enabled` and the
Draft role are all asserted untouched.

## 9. Tests and integrity

- **1 522 passed.** New regressions for all four precision classes, including an
  end-to-end proof that a related-article widget and the other story it names
  never reach the candidate pool.
- The 14 failures in `test_story_identity.py` / `test_workbench_newsroom.py`
  remain environment-caused (real Gemini daily quota spent by the replays) and
  were previously proven to fail identically with the slice stashed.
- Ruff back to the 1 pre-existing error.
- Live stores untouched; every replay ran on temp copies.

## 10. Sign-off

> **Can G2.4 be signed off? NO.**

**The blocker has moved and is now a single, named, editorial one:**

> Two independent publishers are found and read, but 21 of 22 claim pairs are
> judged `DIFFERENT_FACT` — they describe the same event in different words that
> the comparer does not align. Capacity is no longer binding (`0 UNCERTAIN`), and
> discovery is no longer binding (24/24 replayed, 9 Stories with two or more
> publishers).

The next slice should attack **claim alignment**, most likely by matching on the
proposition's identifying slots (who / what / where / when / how many) rather than
on whole-sentence similarity. That needs no Serper credit.

Everything this sub-slice was asked to do is done: the cap is fixed and proven,
headroom is safe, Serper stayed at zero in the replay and is documented as
optional, the frozen set exists and is reusable forever, the official-PRIMARY
path is proven, Case B reaches `DRAFT_ELIGIBLE`, and precision is back to
`WRONG 0 / CHROME 0`.

**G3 not started.**
