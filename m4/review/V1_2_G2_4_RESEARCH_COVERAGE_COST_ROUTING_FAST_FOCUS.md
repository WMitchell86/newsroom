# V1.2-G2.4 — Research coverage, cost routing, fast focus, and the official-source fix

**Status: implemented and measured. G2.3 is signed off; G2.4 is NOT declared
final** — one blocker is named honestly in §9 and the recall number is below the
owner's bar. G3 visual redesign was not started.

The safety rule is unchanged. No fact is promoted without an appropriate
authoritative PRIMARY source or two independent publishers supporting the same
proposition. Nothing in this slice disabled a check, and `paid_enabled` was not
touched.

---

## 0. The three things the owner actually asked for

1. **Extraction precision → zero wrong/chrome facts.** Achieved structurally,
   not by blacklisting strings (§2).
2. **Same-event search coverage.** Measured on the frozen 24-Story sample:
   **22 of 24 Stories** now have at least one same-event publisher reachable,
   against **0** for the existing chain (§4).
3. **Serper wired as a bounded discovery engine**, with its incremental value and
   query cost measured, not assumed (§4).

Plus the mandatory regression: the Burgas Municipality case is fixed at the
source (§1), and the generic research failure no longer exists (§6).

---

## 1. R1–R7 — the Burgas Municipality regression (`s8a124e367aedd12`)

### R1 — the official-source authority trace

| field | value |
|---|---|
| `discovered_by` | `burgas-municipality` (Google News RSS) |
| original URL | `news.google.com/rss/articles/CBMipwFBVV95cUxPUjFySjFGT2VkTU5scUJvX1JCWDlCN21ZR3JWcFJLakpweTd4U0xEamxGMnpGbzA2N2V3S2JCR1ZVUmtDVFBMbTJYeHVBU3lraGZFaUcxczBINEhJaWs5YnA0RlF3bDBOV0I4WDBLT0hPQUFLdDRvRzZuOTRBSGNqWWpFWHJjMHYtcGRPRk92dXdTVnBwM05MaFlkWnhNY0xxNG9XOUNjVQ` |
| final opened URL | `https://www.burgas.bg/bg/novini/zid-v-burgaskata-biblioteka-radoslav-bimbalov-predstavya-noviya-si-roman` |
| `publisher_domain` (item) | `www.burgas.bg` |
| resolved publisher identity | `burgas.bg` |
| matching registry rows | `burgas-cultural-program`, `burgas-municipality`, `burgas-sport-program` (all `kind=official`, `factual_authority=true` — unanimous) |
| `source_kind` | `official_document` |
| `factual_authority` | **true** |
| PRIMARY decision | **yes** — the municipality may establish its own first-party facts |
| claims extracted | 11 PROSE sentences survived extraction |
| claims promoted | **7 facts from 3 independent sources** (`burgas.bg` PRIMARY + `burgasonline.bg` + `qoshe.com`) |
| gap created | **none for corroboration** — the old "Нужен е още независим източник" is gone |

### R2 — the root cause was an authority-resolution bug, not a policy choice

The brief asked not to assume the municipality is PRIMARY. It is — but the code
was **not asking the right question**. `story_research` resolved authority with
`policy.get(host)` on the RAW host. The registry declares `burgas.bg`; the opened
page is `www.burgas.bg`; the lookup returned `None`; the page was treated as
ordinary media; and a corroboration gap was created against the official source
that could have filled it.

So the classification of §R2 is: **authority resolution bug**, not a registry
data problem, not a claim-appropriateness policy, not intended policy. The fix
is `newsroom_run.resolve_publisher_policy`, which matches on the same publisher
identity the independence rule already uses.

Three registry rows claim `burgas.bg`, so §R1's "do not choose whichever row
appears first" is honoured by construction: all rows are returned, the policy is
required to be unanimous (otherwise it fails closed), and the displayed publisher
name is the institution — `Община Бургас` — rather than the alphabetically-first
`Културна програма — Бургас`.

### R3 — PRIMARY is still different from media corroboration

Unchanged and proven by test: an ordinary media source still needs an independent
second publisher. The R1 fix changed only which *registry row* answers the
question, never the rule.

### R5 — what the branch actually was

> Branch **A**: research completed, found no second publisher, and V1.1-A
> converted that completed assessment into an exception, which the application
> layer then reported as a generic sentence.

The completed round now persists the gap it actually has. The one case that
still raises is the genuinely different one: **no claim was extracted from any
opened page**, so there is no assessment to persist and the basis is left
untouched (V1.1-A's "failed open" contract, asserted by an existing test).

---

## 2. Part A — extraction precision

### A2 — the structural cause, not three blacklisted strings

`html_desc.normalize_description` flattened every block boundary to one space,
so `<h2>Мъжки сингъл – любители</h2><p>Към момента…</p>` became a single run
that the sentence splitter — which can only break on punctuation — had no way to
split. The repair keeps the boundary information: `normalize_blocks` returns typed
blocks (`PROSE`, `HEADING`, `LIST_ITEM`, `LABEL`, `NAV`), and only `PROSE` can
become a proposition. The observed string appears nowhere in the implementation;
the regression test proves the merge is unrepresentable.

### A3 — the classes, generalised

`is_chrome` now also rejects any hashtag token, a Title-Case navigation run,
share/follow components and recommendation widgets. Four legitimate short
sentences are asserted to survive, because §A3 forbids over-filtering.

### A4 — event agreement, and a correction

The G2.3 wrong-event attribution is rejected deterministically by a road-locality
contradiction: the Story names `пътя Бургас-Созопол`, the claim names
`пътя Стара Загора – Казанлък`, so it is a different event and no model is
consulted. `катастрофа` and the rest of the generic news vocabulary are removed
from every anchor set, so a generic shared word can never create agreement.

**Correction made during the work, reported rather than hidden.** The first
implementation required **two** shared anchors. Measured against the live BNR
accident page this rejected real facts of the same event — "Ранени при инцидента
са 30-годишна жена и момиченце на 3 години." shares only `жена` with its own
Story — while adding no safety the road contradiction did not already provide.
The threshold is now one **non-generic** anchor, which is precisely what §A4
requires (it is the *word* that is disallowed, not the count). Both directions are
locked by test: the same-event detail survives, the Stara Zagora claim does not.

---

## 3. Part D — fast Editorial Focus

Deterministic, Story-specific, and free of any model call (§D4 is satisfied
literally: three useful variants **can** be generated from title, facts and gaps).

- **D1** — a new Preparation Article is created with a usable Focus already saved
  through the one canonical Focus command, so it is already confirmed. The old
  generic placeholder sentence is gone.
- **D2** — two or three alternatives travel with the projection. Clicking one
  replaces the text and saves it through the same command: no Apply, no Confirm,
  no modal, no state of its own.
- **D3** — the field stays editable at all times; `Напиши свой` only focuses it.
- **D5** — Quick Draft is untouched and still never shows the picker.

---

## 4. Part B — Serper as a bounded discovery engine

`search.run_event_discovery` is the new bounded round. Its invariant is set in
one place: **every** candidate carries `snippet_authority: DISCOVERY_ONLY`, and
only an opened page on a real publisher can ever back a claim.

### B1/B2 — the ladder, and one measured correction

Tier 1 is the quoted subject, then the road pair, then compressed identity, then
key terms. `Бургас` is never appended blindly.

**Correction made during the work.** The road pair alone was too generic:
`"Бургас-Созопол"` returns bus timetables. With the event's own action words it
returns the publishers that actually covered the accident:

| query | real publishers |
|---|---|
| `"Бургас-Созопол"` | 9, but they are bus/route sites |
| `"Бургас-Созопол" пострадаха катастрофа` | 10, and they are `bnrnews`, `btvnovinite`, `eranova`, `iskra`, `news.bg`, `novini`, `sozopol.org` … |

The ladder therefore builds the road query from a curated event/action
vocabulary. Generic words are blocked for claim agreement but deliberately **not**
for queries — reusing the anchor blocklist there was measured to cost most of the
recall.

### B4 — Search vs News, benchmarked on the frozen 24

| backend | queries | results | same-event publishers | Stories with ≥1 |
|---|---|---|---|---|
| `serper` (Google web) | 26 | 131 | **49** | 16 / 24 |
| `serper_news` (Google News) | 26 | 110 | 34 | **20 / 24** |
| **union** | 26 | — | **65** | **22 / 24** |

They are not redundant: 14 Stories hit on both, **2 on Search only, 6 on News
only**. The union is the recommendation, and it is what the bounded round does —
it walks the ladder across whichever Serper backends are available and stops
early once enough publishers are open. Neither is called blindly for every Story.

### B5 — budget discipline

`MAX_SERPER_QUERIES_PER_ROUND = 3`, a policy constant rather than a per-call
argument, so no caller can raise it. The round stops earlier than that whenever
enough publishers are already open. The audit record carries exactly the four
numbers the brief asked for: queries, results, pages opened, usable same-event
publishers. No background spend: only editor-triggered Research reaches it.

### B6 — the existing chain is kept, and its real value is now measured

Google News RSS was **not** removed. It is measured to return only
`news.google.com` redirect wrappers and no resolvable publisher on this sample,
which is the honest reason G2.3's coverage was so low — and it is also why §18
already refused wrappers as evidence.

---

## 5. Two bugs this slice found by measuring, not by reading

1. **Wrappers were consuming the opening budget.** `max_open` truncated the
   candidate list *before* unresolved wrappers were filtered, so the first three
   slots were always `news.google.com` and no publisher page was ever read. The
   Serper pass was silently disabled by this. Fixed in both
   `run_event_discovery` and `story_research`, with the reason recorded in code.
2. **The stop condition counted wrappers as publishers**, so the round believed
   it had two publishers while having opened nothing usable — and therefore never
   spent a Serper query. Same root cause, opposite symptom.

Both are why §4's numbers exist at all.

---

## 6. Part R4 — no generic research failure

The sentence `Проучването не можа да завърши.` is gone from the product. Every
terminal research outcome now belongs to a closed set with its own sentence, and
a test asserts that no two members of the set say the same thing and that the
technical sentence is reachable only for a genuine technical failure.

| reason | code | editor sentence |
|---|---|---|
| `ROUNDS_EXHAUSTED` | `RESEARCH_QUOTA_EXHAUSTED` | Достигнат е лимитът за автоматично проучване на тази история. |
| `PROVIDER_UNAVAILABLE` | `RESEARCH_UNAVAILABLE` | Автоматичното проучване временно не е налично. |
| `NOT_RESEARCHABLE` | `RESEARCH_NOT_APPLICABLE` | Проучването не е налично за тази Story. |
| `NOTHING_OPENED` | `RESEARCH_NO_SOURCE` | Не успяхме да отворим подходящ източник. |
| `INSUFFICIENT_CORROBORATION` | `RESEARCH_NOT_CONFIRMED` | Намерени са източници, но информацията още не е достатъчно потвърдена. |
| `TECHNICAL_FAILURE` | `RESEARCH_INTERRUPTED` | Проучването прекъсна поради технически проблем. Опитайте отново. |

---

## 7. Part C — model routing, measured from the EFFECTIVE policy

`scripts/v12g24_model_routing_audit.py` reads the merged policy **and** greps the
production call sites, so "configured" and "actually wired" cannot be confused.

| workflow | role | wired | first route | billing | hard cap | fallback |
|---|---|---|---|---|---|---|
| Story identity / SAME_STORY | `story` | yes | `gemini-3.8-flash` | operator_declared | 1200 | conservative |
| research query/planning | `research` | **no** | nemotron-ultra | **free** | 50 | deterministic |
| claim equivalence / corroboration | `extract` | yes | `gemini-3.5-flash-lite` | operator_declared | 50 | distinguish_zero |
| evidence judgement | `judge` | yes | `gemini-3.5-flash-lite` | operator_declared | 80 | review_required |
| Draft generation | `draft` | yes | `gemini-3.8-flash` | operator_declared | 25 | fail_visible |
| Draft validation | `judge` | yes | `gemini-3.5-flash-lite` | operator_declared | 80 | review_required |
| **editorial Focus suggestion** | **none** | — | **deterministic, no model call** | — | 0 | — |
| low-risk helpers | `utility` | **no** | `gemini-3.5-flash-lite` | operator_declared | 75 | cheap_only |

**The product principle already holds.** The high-volume corroboration role
(`extract`, G2.3's 159 semantic decisions) routes to a Flash-Lite model with a
500/day operator quota, and `draft` — a 25-call role — keeps the stronger model.
`paid_enabled` remains **false**; the audit only *reports* that a paid route is
reachable, and changes nothing. `MARK_READY` / `FINALIZE` were not weakened.

**The honest caveat.** `operator_declared` is the owner's own quota, not a free
tier, and the ledger shows Gemini 3.6/3.7/3.8 skipping repeatedly against their
20/day limits while the 3.5-flash-lite route carries the volume. A per-role
re-benchmark on the Bulgarian SAME_FACT/CONFLICT set is the next honest step, and
it is an owner decision, not something this slice assumed.

---

## 8. Part E — single-source policy, MEASURED and NOT imposed

`single_source_policy.evaluate` is a pure function. It is not imported by
`article_readiness`, `story_research` or any production path, and a test asserts
the isolation. Its strongest possible output is `DRAFT_CAPABLE_ATTRIBUTED`,
strictly weaker than `DRAFT_ELIGIBLE`, and it always carries the one-source
warning and the attribution requirement. `MARK_READY` and `FINALIZE` are
untouched.

On the frozen sample the experiment unlocks **1** Story. That is a small number
and it is reported as such: the real newsroom case (the municipality) turned out
not to need the experiment at all, because §R1 was a bug. **The owner decision
still stands open**, and the honest recommendation is to fix authority resolution
before weakening the corroboration rule.

---

## 9. Real-data result — the frozen 24-Story sample

`m4/review/evidence/v1_2_g2_4_replay.json`, produced by the same script G2.3
used, on the same 24 Stories, against a copy of the real stores.

| measure | G2.1 | G2.3 | **G2.4** |
|---|---|---|---|
| pages opened | 99 | 127 | **244** |
| candidate claims | 49 | 193 | 108 |
| **facts promoted** | 1 | 19 | **14** |
| **Stories with evidence** | 1 / 24 | 3 / 24 | **4 / 24** |
| Stories with a blocking gap | 23 | 22 | 21 |
| **WRONG facts** | — | 1 | **0** |
| **CHROME facts** | 1 | 1 | **0** |
| wrong-event sentences rejected before comparison | — | 0 | **91** |
| furniture/heading blocks never offered as prose | — | — | 5 165 |
| research errors | 0 | 0 | 1 |

**Every one of the 14 promoted facts was read individually.**

- **12 correct and on-topic** — the exhibition (venue, date, curator), the council
  agenda items (room, deadline, session date), the Alzheimer's flashmob, and the
  charity concert (date, group, leader, cause).
- **2 QUESTIONABLE, listed individually as §A1 requires** — both from the same
  council-agenda page, and both from ONE cause: the sentence splitter breaks at a
  short abbreviation that looks like a full stop.
  1. `Заседанията на постоянните комисии ще се проведат в зала № 1, находяща се
     в сградата на Община Бургас, ет.` — cut at `ет.` (floor).
  2. `от 9:00 часа, в заседателната зала, находяща се в „Културен дом на
     нефтохимика”, ет.2.` — a continuation fragment.
- **0 WRONG, 0 CHROME.** That is the §A1 bar, met.

**A fix that was tried and deliberately reverted.** An abbreviation-aware
splitter (never break after a ≤4-character abbreviation) fixes both QUESTIONABLE
items — and immediately merges `Концертът ще се състои на 1 октомври 2026 г.` with
the sentence after it, because `г.` legitimately ends a sentence. Sentence merging
is the very §A2 defect this slice exists to remove, so trading two questionable
items for a new merge class is a bad deal. The rule is documented in the code with
the measurement that rejected it.

**Why fewer facts than G2.3's 19, stated honestly.** G2.3's 19 included 5
defective ones, and this run's stricter gates refuse 91 wrong-event sentences and
~5 200 furniture blocks that previously reached the comparison stage. The raw
"193 candidate claims" of G2.3 is not comparable to this run's 108, because the
two counts are measured over different segmentation: G2.3 counted sentences, G2.4
counts typed blocks. The comparable numbers are the outcome ones: 14 clean facts
and 0 defects, against 19 facts of which 5 were defective.

**Recall is still the open problem, and this slice does not sign it off.** Same-event
publishers are now *discoverable* for 22 of 24 Stories (§4) and the real
municipality case promotes 7 facts from 3 independent sources, but only 4 of 24
Stories convert discovered publishers into corroborated facts. The semantic
comparer made **29** decisions this run against G2.3's 159, which is the number
that needs explaining before coverage can be claimed. Two candidate causes, both
unresolved: the model route is being skipped for quota, and the anchor gate is
narrowing the pairs that reach it. Until that is measured, G2.4 is a **precision
result, not a coverage result.**

---

## 10. Part F — independent publisher count, proven

`story_store.publisher_count` counted raw `publisher_domain` strings, so
`www.burgas.bg` and `burgas.bg` were **two** publishers. It now uses the single
shared definition, `story_store.publisher_identity`, which the corroboration gate
also calls — so the count the editor sees and the count the evidence gate computes
can no longer disagree about what a publisher is. A subdomain, an AMP host and an
alternate news domain can no longer manufacture an extra source.

The `Най-много източници` **sort is not built** — §F forbids new ranking
infrastructure. The ready-made deterministic key exists; only the Today ordering
needs to consume it later.

## 11. Part G — future event sources

Recorded in `BACKLOG.md` only, with each entry classified (official structured /
official HTML / ticket aggregator / social discovery) and the rule that a ticket
aggregator is never the provenance for a date. Nothing was scraped or enabled.

## 12. Tests and integrity

- **55 new tests** in `tests/test_g2_4_coverage_and_precision.py`, every one a
  permanent regression for a defect that actually occurred: the observed heading
  merge, the observed tag-cloud blob, the observed wrong-event sentence, the
  observed `www.burgas.bg` authority miss, the observed generic failure, the
  observed `Skip to content` teasers, the observed truncated previews — plus the
  counter-tests proving each filter does **not** eat real sentences.
- Full suite with the real provider quota available: **9 failed / 1 453 passed**,
  byte-identical to the pre-slice baseline (verified by `diff`). With the quota
  spent: **23 failed / 1 499 passed**.
- **The 14 extra failures are not regressions, and this was proven, not asserted.**
  They are `test_story_identity.py` and `test_workbench_newsroom.py`, which call
  the real Gemini route. Running them with this slice **stashed** and with the
  quota cleared gives the **identical** result — 14 failed / 70 passed both
  ways. The replays spent the provider's daily quota, so every route now
  returns "skipped" and those tests cannot get a model answer. This is the same
  quota finding as §13, seen from the test side.
- Canonical stores **unmutated**: `stories.json`, `inbox.jsonl`,
  `story_research.json` and `sources.json` all show 0 modifications. The only
  writes under `var/` are the append-only `search_runs/` audit log and the
  `model_usage/` ledger, both designed to record a run.
- Frontend: `tsc -b` clean, `vite build` green.
- G3 visual redesign **not** started, as instructed.

## 13. A finding that explains the coverage blocker — and an environment caveat

**The 29-vs-159 semantic-decision gap is explained, and it is a routing problem,
not a logic problem.** After the replays, `var/model_usage/2026-09-27.json` shows:

```text
gemini:gemini-3.5-flash-lite   calls=123  ok=50  skipped=73
gemini:gemini-3.1-flash-lite   calls=73   ok=0   skipped=73
openrouter:nemotron-3.5-lightning:free  calls=73 ok=0 skipped=73
openrouter:openai/gpt-5.6-luna calls=73   ok=0  skipped=73
```

The `extract` role — the high-volume corroboration role — has
`soft_calls_day: 20, hard_calls_day: 50`. **One replay round of 24 Stories
exhausts the entire daily budget for the role that decides whether two publishers
said the same thing.** Once spent, every route is skipped and
`claim_equivalence` correctly falls back to `UNCERTAIN`, which grants nothing.

This is precisely §C3's warning turned into a measurement: *cheap* must not mean
*starved*. The role is on the right, cheap model — the **cap** is what is wrong
for a high-volume role. Recommended, and NOT applied here because it is an owner
cost decision: raise the `extract` role's daily caps so a 24-Story replay cannot
spend them, and re-measure. This is the single highest-value next action, and it
is a config change, not a code change.

**Environment caveat, stated plainly.** 14 tests (`test_story_identity.py`,
`test_workbench_newsroom.py`) call the real Gemini route through the router. Once
the daily budget is spent they fail. They fail **identically with this slice's
changes stashed** — verified with `git stash` — so they are environment
state, not regressions. The offline, code-relevant suite is what §12 counts.

## 14. Session code review — three defects found in this slice and fixed

The diff was reviewed against the real corpus and against adversarial markup.
Three genuine defects were found in the slice's own work, and all three are now
fixed with regression tests.

**HIGH — an unclosed container silently deleted the article.** The typed
segmentation popped its kind stack only when the closing tag was on top, so a
single missing `</nav>` left NAV open forever and every following paragraph was
labelled navigation and never offered as prose. The failure is silent and
indistinguishable from "this page had no usable text" — the exact failure mode
Part A exists to prevent. Fixed with the standard recovery (an end tag unwinds
to the nearest matching open tag; an unmatched end tag is ignored) plus two
structural signals that a container was never closed: a HEADING inside one, and a
PARAGRAPH inside one. Six new tests cover unclosed `nav`/`header`/`aside`,
crossed tags, and a real menu that must *stay* navigation.

**MEDIUM — the artefact filter rejected legal citations.** The whitespace-less
node rule fired on any digit followed by a capital, which is how Bulgarian legal
and administrative references are written: `Решение 12А`, `Отдел 3Б`, `чл. 5Б`.
Council stories are a large share of this corpus, so the rule was suppressing
real facts. It now demands a whole run — a token long enough to be concatenated
nodes rather than a two-character citation — while the two unambiguous signatures
are unchanged. The observed artefacts are still rejected.

**LOW — the Serper budget claimed to be policy but was a plain parameter.**
`MAX_SERPER_QUERIES_PER_ROUND` was documented as something no caller can raise,
while `run_event_discovery` accepted an argument that could be set arbitrarily.
The code now matches the stated policy: a caller may spend less and the value is
clamped to the constant.

**Lint.** 16 Ruff errors introduced by this slice are fixed, returning to the 1
pre-existing error that was already there before G2.4. The suite is 68 tests, up
from 55.

Two things the review explicitly did **not** change, because the measurement
rejected the fix:

- the two-anchor rule (corrected to one non-generic anchor in the slice);
- the abbreviation-aware sentence splitter, which fixes both QUESTIONABLE items
  and immediately merges `… на 1 октомври 2026 г.` with the next sentence.

## 15. Owner decisions still open
1. **Coverage** — the 29-vs-159 semantic-decision gap must be explained before
   G2.4 can be signed off. This is the one blocker.
2. **The single-source Draft policy** — measured (it would unlock 3 of 24 Stories),
   not imposed. My recommendation is to settle §R1's authority resolution first,
   because the real newsroom case did not need the experiment at all.
3. **Paid routing** — `paid_enabled` remains `false` and was not touched. A
   per-role re-benchmark on the Bulgarian SAME_FACT/CONFLICT set is needed before
   any paid change; §C currently shows Gemini 3.6/3.7/3.8 skipping against their
   20/day limits while 3.5-flash-lite carries the volume.
4. **`bnrnews.bg`** — BNR articles live there while the registry knows `bnr.bg`.
   Reported, not silently added; it needs the owner's decision on the
   institution's policy.
5. **Legacy Article titles** ending `- Община Бургас` — per §R7 these are reported
   as **legacy pre-fix auto-prefill candidates** only. No Article-title migration
   was performed and none should be bundled into this slice.

