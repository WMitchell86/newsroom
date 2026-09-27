# V1.2-G2.4B — extract capacity + frozen coverage replay

**Answer to the sign-off question: NO — with exactly one blocker, named in §9.**

The blocker is NOT the extract cap. The cap is fixed and proven fixed, live. The
blocker is that the frozen 24-Story coverage comparison **cannot be run at
scale**, because a gap in my own G2.4 work means the discovered URLs were never
persisted. Details and the cost of closing it are in §9.

---

## 1. Budget

| | before | after |
|---|---|---|
| `extract.soft_calls_day` | 20 | **200** |
| `extract.hard_calls_day` | 50 | **300** |

Changed: the role budget only. Asserted unchanged by test: route order, provider,
model, the semantic prompt, the SAME_FACT rules, `paid_enabled` (still `false`),
the per-model operator quota (still 500/day), and the Draft role (still
`gemini-3.8-flash`, hard 25).

## 2. The starvation, measured live

From `var/model_usage/2026-09-27.json`, on the day of the replay:

```text
gemini:gemini-3.5-flash-lite    attempts=50  ok=50  skipped=74
gemini:gemini-3.1-flash-lite    attempts= 0  ok= 0  skipped=74
openrouter:nemotron-...:free     attempts= 0  ok= 0  skipped=74
openrouter:openai/gpt-5.6-luna   attempts= 0  ok= 0  skipped=74
```

Exactly 50 attempts — the hard cap — then every route skipped, including the
**free** OpenRouter fallback. `claim_equivalence` then falls back to `UNCERTAIN`,
which grants nothing, which is why G2.4 made only 29 semantic decisions against
G2.3's 159.

The provider was never the problem. A direct probe bypassing the role budget
returned **HTTP 200**, and an `extract` call returned
`RoleUnavailable: няма достъпен маршрут`. After the change, the identical call
returns a model answer on the identical model.

## 3. Provider headroom (§5)

`extract`, `judge` and `utility` share **`gemini:gemini-3.5-flash-lite`**, operator
quota **500/day**.

```text
extract 300 + judge 80 + utility 75 = 455  ≤ 500      safe, 45 to spare
```

`story`, `angle` and `draft` share `gemini-3.8-flash` (20/day) and are unchanged.
A test asserts the shared-capacity invariant rather than trusting the arithmetic.
The replay did not come close to any provider limit, so the STOP condition in §5
was not triggered.

## 4. Serper (§2, §3)

```json
{ "serper_calls_during_replay": 0,
  "serper_credits_consumed": 0,
  "product_status": "optional development / diagnostic discovery provider",
  "required_for_production_research": false }
```

Zero, enforced by a tripwire: both Serper adapters are replaced with a function
that raises, so a regression fails the run loudly instead of quietly spending a
credit. The frozen round is driven by a recorded discovery operation, and every
recorded URL is re-opened through the same safe fetch path — the record supplies
discovery only, never evidence.

**Degradation verified**: with `SERPER_API_KEY` removed, the chain is
`['google_news_rss', 'tinyfish', 'ddgs']`, `serper:no-key` is recorded, and no
crash occurs.

**The honest consequence of the freeze, measured.** On this corpus the keyless
chain (Google News RSS) returns **only unresolved `news.google.com` wrappers and
zero usable publishers**. Freezing Serper therefore returns corroboration coverage
to roughly the G2.3 level. Serper is not *required for the code to run*, but it
is currently the only source of same-event publisher discovery. This is the
owner-accepted trade, now quantified rather than assumed.

## 5. Semantic funnel (§7)

```text
candidate claim pairs              12
deterministically rejected          0
model comparison required           0
model comparison answered           0
UNCERTAIN because unavailable       0
SAME_FACT / DIFFERENT_FACT / CONFLICT   0 / 12 / 0
facts promoted                       0
```

Read honestly: on the one Story that could be replayed, every pair was decided
deterministically as a different fact, so the model was never needed. **This
number is therefore NOT the answer to the starvation question** — the sample is
one Story. It does show the funnel instrumentation works and that no comparison
was starved.

## 6. Coverage result (§8)

`Stories with ≥1 promoted fact`: **1 replayed Story → 0**.
`DRAFT_ELIGIBLE`: **0**. This is a 1-Story sample, not a coverage result, and is
not presented as one.

## 7. Precision bar (§9)

No new promoted facts, so nothing new to review. **WRONG = 0, CHROME = 0** holds,
and the G2.4 review of its 14 facts stands unchanged.

## 8. Burgas Municipality regression (§10)

Kept and proven on isolated data, with **no Serper involvement**:

```text
www.burgas.bg → publisher identity burgas.bg
              → unanimous registry resolution (official, factual_authority)
              → PRIMARY → first-party facts promoted
              → no artificial second-source requirement
```

Product proof Case A: **2 facts, 1 source named `Община Бургас`, zero
corroboration gap.**

**A real defect was found by running this proof and has been fixed.** The
*injected* authority resolver was still consulted with the **raw host**, so
`www.burgas.bg` missed `burgas.bg` and the official source was demoted to
ordinary media — the §R1 bug, surviving in the injection path that every test
and proof uses. Both paths now resolve by publisher identity. Case A is the
regression test.

## 9. THE BLOCKER

**The frozen 24-Story discovery set does not exist, and that is my G2.4 defect.**

The G2.4 replay wrote its audit log into a temp directory and deleted it on exit,
and it persisted only each Story's own `item_url` — never the URLs it
*discovered*. Measured coverage of the frozen sample from everything on disk:

```text
frozen stories with a reusable discovery record:  1 / 24
```

So §6 of the brief cannot be executed as written, and the "substantially more
than 4/24" sign-off test **cannot be evaluated**. I will not present a 1-Story
number as a coverage answer.

**Root cause is now fixed and cannot recur**: the replay persists
`discovered_urls` per Story, and the executor accepts a recorded operation so the
next capture is reusable. A behavioural test proves a frozen replay performs
corroboration with the search round replaced by a tripwire.

**What closing it costs.** One capture run of the 24 frozen Stories, which spends
Serper queries at the existing 3-per-round cap — **72 queries maximum**, ~3% of
the ~2 000 credits the owner has left after the development benchmark. That is a
decision only the owner can make, and I have not made it.

## 10. Single-source policy (§12)

Still not wired into production; a test asserts no production module imports it.
Its incremental value **cannot be recalculated** at scale for the same reason as
§9, and with normal Research stronger the measured 3/24 unlock is unlikely to
justify weakening the corroboration rule. **Recommendation: drop the
experiment** rather than carry it, unless the capture run shows the ordinary gate
is still the binding constraint.

## 11. Product proof (§16)

| case | facts | sources | readiness |
|---|---|---|---|
| **A** — one official source | 2 | 1 (`Община Бургас`) | PRIMARY facts promoted, **no corroboration gap** |
| **B** — two independent publishers, paraphrased | 4 | 2 | **`DRAFT_ELIGIBLE`** |
| **C** — one media source only | 0 | 0 | `BLOCKING_GAP`, no promotion |

Case A's remaining blocking questions come from the generic bootstrap
**sufficiency assessment**, not from corroboration — a separate behaviour worth
its own look.

Case B is the substantive one: it is the first proof in this work where two
*paraphrased* claims from independent publishers produced a Draft, which is the
corroboration path the raised cap unblocked.

## 12. Tests and store integrity

- **10 new contract tests** in `tests/test_v12_g2_4b_contract.py` freezing every
  decision in this slice: the budget, "nothing else moved", shared-capacity
  safety, Serper optionality, search-free frozen replay, the experiment staying
  unwired, the publisher count, `bnrnews` staying reported, and the Focus
  contract.
- Full suite: **1 517 passed**. The 14 failures in `test_story_identity.py` /
  `test_workbench_newsroom.py` remain environment-caused (real Gemini quota spent
  by the replays) and were previously proven to fail identically with the slice
  stashed.
- Ruff back to the 1 pre-existing error.
- Live stores untouched: all replays ran on temp copies. The only writes under
  `var/` are the append-only search-run audit and the usage ledger.

## 13. Sign-off decision

> **Can G2.4 now be signed off? NO.**

**One dominant blocker:** the frozen 24-Story coverage comparison cannot be run,
because the G2.4 replay never persisted the URLs it discovered, leaving 1 of 24
Stories with a reusable discovery record.

Everything else this sub-slice was asked to do is done and measured: the
starvation is removed and proven removed live, the shared-provider headroom is
safe with margin, Serper stayed at zero calls and is documented as optional, the
frozen replay is built and provably search-free, the official-PRIMARY path is
proven and a second real bug in it is fixed, and Case B now reaches
`DRAFT_ELIGIBLE`.

**To unblock:** authorise one capture run of the 24 frozen Stories (≤72 Serper
queries), which becomes the frozen set for every later replay. G3 not started.
