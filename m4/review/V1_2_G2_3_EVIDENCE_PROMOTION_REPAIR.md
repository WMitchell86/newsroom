# V1.2-G2.3 — Research Evidence Promotion Repair

**Status: STOPPED AND REPORTED, not complete.** Per §26 the repair must improve
recall **and** precision, and a slice is not successful merely because promotion
went up. The machinery is measurably repaired and the first real Drafts now
appear, but the precision gate is not yet met. Numbers below, not adjectives.

**The safety rule is unchanged.** A fact still requires an authoritative source
or two independent publishers supporting the same factual proposition. Nothing
in this slice disabled a check, and no global evidence switch was added (§24).

---

## 1. Before vs after — the frozen G2.1 sample (§25)

The same 24 Stories, recorded in the G2.1 evidence file, on a copy of the real
stores, through the real `execute_story_research`.

| measure | G2.1 | G2.3 |
|---|---|---|
| pages opened | 99 / 103 attempts | **127** |
| candidate claims extracted | 49 | **193** |
| usable claims after quality filtering | not separated | **193** |
| chrome sentences rejected | not measured | **870** |
| **facts promoted** | **1** | **19** |
| Stories with ≥ 1 fact | 1 / 24 | **3 / 24** |
| Stories left with a blocking gap | 23 / 24 | 22 / 24 |
| research errors | 0 | **0** |
| semantic decisions (bounded) | 0 | 159 |

The G2.1 single promoted "fact" was a navigation menu. It is now permanently
rejected by a named regression test.

---

## 2. Claim extraction (§9–§12)

Four claims per opened page, each tagged with the research question it answers,
instead of the first matching sentence. Before promotion, deterministic filters
reject navigation menus, tag clouds, cookie banners, footers, site-ownership and
legal-notice boilerplate, breadcrumb blobs, all-caps label runs, bare domains,
read-more previews, clauses that start with a copula, and anything that is not a
complete proposition ending in punctuation.

Two defects were found only by reviewing the promoted facts:

- **Merged sentences.** Splitting on `[.!?]` alone merged unrelated sentences
  across an ellipsis or a legal citation, producing a "fact" made of two
  different stories. Splitting now also breaks on `…`, `т. N`, `ал. N`, `чл. N`.
- **Irrelevant but well-formed sentences.** Matching a *dimension* is not
  relevance. A claim must now share a content key with the Story's own subject,
  and a place, a year or a weekday never counts. This is what removed
  "Лесотехническият университет ... в Бургас" from the poetry contest
  "Бургас вдъхновява", and "Дом, в който влизат лазарки..." from a council agenda.

## 3. Corroboration (§2, §5, §7, §8, §21)

`compare_claims(a, b)` → `SAME_FACT | DIFFERENT_FACT | CONFLICT | UNCERTAIN`.

- **Deterministic first.** Different explicit dates, different incompatible
  quantities for the same measure, a negation mismatch, a different named
  organisation, and a different central identity are decided in code and **can
  never be overridden by a model** — a test proves the model is not consulted.
- **Similarity alone never grants a match.** Token overlap only gates the
  contradiction check and the clearly-different case.
- **Bounded.** Only claims extracted for the same reason are compared, capped at
  12 model-assisted pairs per round, asserted by a test.
- **Independence is per publisher, not per host.** Found while reviewing: the
  code compared hosts, so a subdomain and its parent counted as two publishers.
  The test that claimed to cover this passed a duplicate dict key and never
  opened two hosts at all; both are fixed.
- **Conflicts are not corroboration.** A detected contradiction is persisted as
  a plain-language question and never counts as support.
- **Council-decision guard preserved.** The pre-existing M2S rule requires an
  official record for "the council approved X". G2.3's stronger extractor can now
  *see* such claims, so the executor declines to corroborate them from media
  using the same pattern the guard enforces (`research.decision_claim_pattern()`).
  Two media articles agreeing on a decision is still not enough, and the round
  ends with a truthful gap instead of aborting after pages have been opened.

## 4. Model involvement (§6, §29, §30)

The project's own routing, the existing `extract` role — no new provider, no new
permanent dependency. Closed single-word output; malformed output, no route, no
key or a failure all yield `UNCERTAIN`, which grants nothing. 159 decisions in
the replay, all within the per-round cap. PRIMARY-only sources still work when
the semantic route is dead, proven by a test.

## 5. Source authority (§13–§16)

**No host was made authoritative.** Registry coverage audit of the 82 audited
opens: 22 distinct hosts, 17 unregistered (69 opens, 84%). Ranked, and the two
most frequent are not publishers at all — `news.google.com` (23) and
`facebook.com` (16) were search results whose redirect never resolved. The
highest-value fix was therefore **not** a registry entry but a guard: §18 now
refuses an unresolved aggregator or social page as a source, so one wrapper
cannot manufacture the independent second source.

One genuine coverage gap is identified but **not** silently added:
`bnrnews.bg` is where BNR articles actually live, while the registry knows the
same institution as `bnr.bg`. That entry needs an owner decision on the
institution's policy, so it is reported rather than added.

## 6. Every promoted fact reviewed (§27)

All 19 promoted facts in the final run were read individually. Classification
and the full list are in `evidence/v1_2_g2_3_replay.json` under `fact_texts`.

- **Correct and on-topic: 14** — the accident (who was hurt, how, which
  hospital), the council agenda items, the tennis tournament (venue, format,
  prize), the poetry contest (theme, organisers, ceremony).
- **Defective: 5** —
  1. one tag-cloud blob (`#катастрофа … Новини Нашите инициативи БНР …`);
  2. one **wrong-event attribution**: a sentence about a *different* accident
     (Stara Zagora–Kazanlak, 20 Sept) promoted inside the Burgas–Sozopol Story;
  3. three heading-plus-sentence merges ("Мъжки сингъл – любители Към момента…").

**This is why the slice is not declared complete.** §26 requires zero chrome and
zero false matches; the honest count is **1 chrome, 1 wrong attribution out of
19** (~74–79% precision). Recall also remains low: **3 of 24 Stories** produce
evidence, against the owner's bar of a reasonable percentage.

## 7. Draft readiness (§31)

The **existing** `article_readiness` evaluator, with no success shortcut. Of the
3 Stories that produced evidence:

| Story | facts | readiness | `MAKE_DRAFT` |
|---|---|---|---|
| accident (Burgas–Sozopol) | 7 | `BLOCKING_GAP` | no |
| council agenda №42 | 6 | `DRAFT_ELIGIBLE` | **yes** |
| Black Sea Open | 6 | `DRAFT_ELIGIBLE` | **yes** |

**This is the first time real research has produced enough evidence for a Draft.**
Before G2.3: 1 Story with a fact, 0 Draft-eligible.

## 8. Remaining blockers — the honest list

1. **Corpus coverage, not the gate.** The 21 blocked Stories open 2–4 pages each
   and extract claims, but the publishers found are frequently not covering the
   *same event*: an inspected example paired "Министър Шишков ще инспектира
   ремонта на художествената галерия" with "Царево с две отличия в конкурс…".
   The comparer correctly said DIFFERENT_FACT. Two independent publishers
   carrying one proposition is the real bottleneck, and it is a search/coverage
   problem, not an evidence-policy problem.
2. **Decision claims need an official record.** For council stories this is
   correct and unchangeable without owner policy.
3. **Heading merges and one tag blob** remain in promoted output (§6).
4. **`bnrnews.bg`** registry coverage is identified but unadded (§5).

## 9. Tests

- 24 equivalence + benchmark cases, including a **model-failure** proof, a
  **no-similarity-alone** proof, and the permanent chrome regressions.
- 14 end-to-end promotion proofs on the real executor: paraphrases corroborate,
  exact duplicates still corroborate, one source does not, same publisher twice
  does not, conflicting quantity and date do not, chrome is rejected, several
  claims per page, PRIMARY still works, media corroborate without authority, the
  model-unavailable path is conservative, unresolved aggregators are refused.
- Full Python suite: **1523 passed**, failure set byte-identical to the
  pre-slice baseline (22 pre-existing environmental failures, zero regressions).
- G2.2 browser proofs re-run green after the change.

## 10. Runtime-store integrity

274 real runtime files, SHA-256 before and after every replay: **0 changed**.

## 11. Explicitly untouched

Snippets remain discovery-only. Google News wrappers remain non-evidence (now
enforced, not just intended). The independent-publisher requirement remains. No
global evidence-disable switch. No publishing. Corroboration, authority and every
evidence threshold are as V1.1-A left them.

## 12. Recommended next slice — NOT begun

Because precision is not yet zero-defect and only 3 of 24 Stories yield facts,
**G2.3 should not be signed off yet.** The next work is narrow and identified:
close the two extraction defects (§6), then attack **event-level coverage** —
find independent publishers covering the *same* Story — which is the actual
bottleneck. It is recommended as `V1.2-G2.4 — Research Coverage & Extraction
Precision`, not as a return to G3 visual polish.
