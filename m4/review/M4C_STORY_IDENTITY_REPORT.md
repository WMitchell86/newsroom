# M4C — Story Identity & New Development Report

Turning the daily material list into **stories**, without losing a single collected
source item and without letting a model merge things it should not.

Part 0 (the five M4B/source-feed corrections) is reported separately in
`m4/review/M4B1_FEED_STABILIZATION_REPORT.md`.

Gate: **859 offline tests** (was 805), ruff check/format clean, M3A smoke 25/25,
plus a real isolated collection and story build (§7) and a manual review pack
(`m4/review/M4C_STORY_REVIEW_PACK.md`).

---

## 1. What was built

```text
src/editor_assistant/workflow/
  publication_identity.py   InboxItem -> publication_key (no story semantics)
  story_store.py            strict, atomic story store + lifecycle + editor overrides
  story_identity.py         the incremental service: retrieval, deterministic match,
                            update/analyze/rebuild, views, editor actions
  story_relation.py         the one narrow semantic step (role="story")
  workbench/newsroom.py     story service calls for the UI
  workbench/html.py         «Истории» list + story detail pages
  drafting/generate.py      role="story" model pool (GEMINI_STORY_MODELS /
                            OPENROUTER_STORY_MODEL), paid guard preserved
  cli.py                    newsroom stories update|rebuild, newsroom refresh
```

New commands:

```bash
newsroom stories update [--dry-run] [--no-semantic]   # assign new material to stories
newsroom stories rebuild --preview|--apply [--force]  # dev/first-install only, refuses to lose editor fixes
newsroom refresh                                      # collect -> assign -> one summary
```

`newsroom collect` is unchanged and stays the low-level collection command.

## 2. Three identities, kept apart

```text
DISCOVERY    source_id / source_kind       how did the system find this item?
PUBLICATION  publication_key + publisher_domain   which exact published article is this?
STORY        story_id                      which real-world event does it belong to?
```

* the inbox stays the raw discovery store — `item_id` is **not** rewritten, no row is
  deleted, no row's provenance changes;
* `publication_key = "p" + sha256(normalized_url + "\x1f" + publisher_domain)[:15]`,
  independent of `source_id`;
* URL normalization: lower-case host, fragment removed, default port removed, `utm_*`
  / `fbclid` / `gclid` removed, remaining query parameters preserved (sorted, so
  order can never create a second identity), one trailing empty slash normalized;
  paths are never rewritten;
* Google News opaque links: the stable article path/token is kept, query noise is
  dropped, and the publisher domain enters the identity separately;
* **no usable URL ⇒ no exact key** (never invented from a title).

Real effect in the isolated corpus: **123 discovery rows → 113 unique publications**
(10 duplicate rows collapsed, 8 groups, all same-publisher-different-monitor cases).
Story cards show `издатели` / `публикации` / `откривания` separately, so five monitors
finding two articles can never read as "5 sources".

## 3. Story store

`var/newsroom/stories.json` (env `NEWSROOM_STORIES_PATH`), atomic writes, closed
schema, `version`, and an `overrides` audit list. Unreadable/malformed ⇒
`StoryStoreError` — never "looks empty", because an empty-looking store would let the
next automatic pass rebuild over the editor's corrections.

```yaml
story_id: s…            # stable, from the origin publication_key (or first item_id)
status: NEW|SEEN|IGNORED
created_at, first_seen_at, first_public_at, last_seen_at, latest_material_change_at
representative_item_id
needs_review: bool
members: [{item_id, publication_key, relation, relation_source, added_at}]
overrides: [{action: SPLIT|MERGE, at, item_id, from_story, to_story, note}]
```

Membership relations are `ORIGIN`, `SAME_STORY`, `NEW_DEVELOPMENT`,
`RELATED_BACKGROUND` — `NEW_STORY` is deliberately **not** a relation, because
creating a story is the action taken when nothing matches. Timestamps are derived
from real member timestamps only; nothing is fabricated.

## 4. Pipeline (cheap first)

```text
Stage A  exact publication_key already in a story      -> SAME_STORY (no model call)
Stage B  recent stories only (<=7 days), cheap score, top 5
         near-identical title + close time + strong distinctive-token overlap
                                                        -> SAME_STORY (no model call)
         otherwise                                      -> Stage C
Stage C  the narrow semantic relation, ambiguous shortlist only
         provider unavailable / invalid output          -> SEPARATE + needs_review
```

* the deterministic score is built from normalized title/summary tokens, numeric
  tokens, distinctive shared tokens and publication-time proximity. A story with **no
  shared text at all is not a candidate** — time proximity alone never shortlists;
* `NEW_DEVELOPMENT` is **never** inferred from token similarity: only a real semantic
  answer may reopen a story;
* the score is a *retrieval hint*; it is never authority to merge;
* `uncertain → separate`. A false split is cheap (the editor merges it); a false
  merge hides news.

Score weights and the conservative thresholds (`title ≥ 0.8`, `distinctive ≥ 0.6`,
`≤ 48 h`) are module constants in `story_identity.py`.

## 5. The semantic step is narrow and fail-safe

One question, one strict JSON contract:

```json
{"same_event": true, "relation": "SAME_STORY|NEW_DEVELOPMENT|RELATED_BACKGROUND|DIFFERENT_STORY",
 "material_change": true, "shared_anchors": ["…"], "reason": "…"}
```

* validated before it can act: unknown fields rejected, relation enum enforced,
  `same_event` / `material_change` must be booleans, and contradictions are refused
  (`DIFFERENT_STORY` + `same_event=true`, `NEW_DEVELOPMENT` + `material_change=false`);
* the model may not return scoring, confidence or authority fields — the contract is
  closed and there is no code path from a relation into publisher authority, drafting
  or publishing;
* context is compact: representative title, origin title, up to two latest
  development titles, short summaries, publisher domains and times, **at most 3**
  unique publications — never article bodies, never a long history;
* **failure never merges**: no provider, rate limit, timeout, non-JSON or invalid JSON
  all return `None` → the item becomes its own story with `needs_review = true`;
* the role has its own pool (`role="story"`): `GEMINI_STORY_MODELS` (defaults to the
  full draft pool — never the weak Lite `judge` pool, the M3D lesson) and
  `OPENROUTER_STORY_MODEL`. The existing paid-model guard runs before any call, and
  `role="story"` does not change draft/judge routing (tests included).

## 6. Editor workflow

* story statuses `NEW` / `SEEN` / `IGNORED` with the M4C lifecycle:
  `SAME_STORY` and `RELATED_BACKGROUND` keep a `SEEN` story seen, `NEW_DEVELOPMENT`
  reopens it to `NEW`, an `IGNORED` story stays ignored;
* story status propagates to member inbox rows (`SEEN`/`IGNORED`), so the material
  view is not left full of misleading `NEW` rows; reopening to `NEW` does not rewrite
  the materials;
* **«Този материал не е част от историята» → отделяне** on every timeline row (the
  most important correction: false merges are the dangerous failure);
* **«Обедини с друга скорошна история»** with a dropdown of recent story headlines —
  no IDs are typed or read by the editor;
* both are stored as explicit `overrides` and `is_editor_locked()` makes a later
  automatic pass report the item instead of moving it again;
* `rebuild` refuses to run at all when overrides exist unless `--force` is passed.

## 7. Real isolated evaluation

One fresh collection into a throwaway `NEWSROOM_DIR` (30 default sources, 2026-09-21),
two immediate runs (see the M4B.1 report §1 for the recency proof).

**Step 1 — deterministic only (before turning semantics on):**

```text
source items (discovery rows)      123
unique publication_keys            113
exact-duplicate rows collapsed      10   (8 groups)
deterministic high-confidence merges 1
remaining ambiguous items          102
stories from a deterministic build 112
```

So *without any model cost* the duplicate-discovery inflation is removed and the one
obvious cross-publisher pair is grouped. Everything else stays separate — by design.

**Step 2 — semantic relation, ambiguous shortlist only, capped probe:**

```text
probe A: 12 calls  ->  9 answers (all DIFFERENT_STORY), 3 unavailable, 0 merges
probe B (review pack): 10 calls -> 10 answers (all DIFFERENT_STORY), 0 merges
```

Not one suggestion from the semantic step merged two items in this corpus; the model
answered conservatively on the sampled near-miss pairs. **No model/provider failure is
hidden**: the 3 unavailable calls in probe A are reported (they degrade to separate
stories + `needs_review`, never to a merge).

Model used for the probe: free OpenRouter tier (`OPENROUTER_STORY_MODEL=qwen/qwen3.8-27b:free`).
Note the pre-existing environment defect recorded in §10 — the *default* OpenRouter
model id committed in `generate.py` (`google/gemma-4-31b`) is not valid in this
account's catalog and returns HTTP 400 **for every role, including `draft`**; the M4C
probe therefore set the story arm explicitly.

## 8. Manual review pack

`m4/review/M4C_STORY_REVIEW_PACK.md`, generated from the corpus above:

```text
5 exact publication duplicates            (8 available)
1 cross-publisher deterministic merge    (all available shown)
10 semantic probe cases with score+reason
10 near-miss / DIFFERENT_STORY cases
5 suspicious/uncertain stories
```

It records titles, publishers, timestamps, the deterministic shortlist score/reason,
the semantic relation when used, and the final story. The model's own answer is
explicitly **not** ground truth; `за преглед` marks uncertain cases and a human
checklist closes the document.

## 9. Workbench

Navigation: `Истории | Материали | Източници | Случаи | YouTube`.

* **`/stories`** lists stories with a type badge (`Нова история` / `Ново развитие`),
  status, honest counts, publisher list, one-line summary and
  `Прегледана / Игнорирай / Отвори историята`;
* **`/stories/{id}`** shows first seen, first public, latest material change, the
  chronology (origin → developments), unique publications grouped by publisher, and
  discovery provenance inside a `<details>` block — different monitors of the same
  article are shown as *discoveries*, never as independent sources;
* internal ids, Jaccard scores, model confidence, relation JSON and prompt/model names
  are never shown (they exist in CLI/audit output only);
* a publisher blocked *after* collection keeps its raw row (audit) but does not
  create or reinforce a story, and is badged `забранен издател`;
* `Материали` (`/inbox`) is unchanged and still reachable, so every collected row
  remains inspectable.

## 10. Findings, weak spots, open items

1. **Pre-existing: the default OpenRouter model id is not valid** in this account
   (`google/gemma-4-31b` → HTTP 400 for every role). The free-tier default constant
   (`OPENROUTER_FREE_MODEL`) is only read from the *environment* at call time, so the
   documented default never applies. Not fixed here (drafting routing is out of M4C
   scope) — recorded in `BACKLOG.md`. M4C's story arm has its own env knob and works.
2. **Token matching is morphology-blind.** Bulgarian inflections (`бюджета` vs
   `бюджетът`) do not match, so the deterministic step is more conservative than a
   stemmer would be. That is the safe direction, but it is why only 1 of 123 rows
   merged deterministically and why 102 items reach the ambiguous shortlist.
   A light stemming step is a candidate for a follow-up **only** if review shows the
   recall is hurting the editor — recorded in `BACKLOG.md`.
3. **`наблюдение`-only recall**: the corpus has almost no cross-publisher rewrites of
   the same event, so `SAME_STORY`/`NEW_DEVELOPMENT` recall is
   `NOT_EVALUATED` on real material (§ verdicts). The lifecycle rules are proven by
   hermetic tests, and the semantic probe shows the path works end-to-end.
4. **Semantic cost is real**: 102 ambiguous items would have needed ~102 calls on this
   corpus. The service has no budget knob yet; the probe was capped by the evaluation
   script. A `max semantic calls` cap is a candidate follow-up.
5. Stored publisher-authority snapshot vs current policy (from the review's
   "Deferred") is still deferred.

## 11. Verdicts

```text
ROLLING_NEWS_RECENCY        = PROVEN
CALENDAR_DATE_SEMANTICS     = HONEST
DAILY_COUNT_SEMANTICS       = PROVEN
PUBLICATION_IDENTITY        = PROVEN
STORY_STORE_ENGINEERING     = PROVEN
DETERMINISTIC_STORY_MATCHING= PROVEN (conservative; low recall on this corpus, by design)
SEMANTIC_STORY_RELATION     = PROMISING (path proven end-to-end; all sampled answers
                              were DIFFERENT_STORY, no merge produced)
NEW_DEVELOPMENT_DETECTION   = NOT_EVALUATED on real material (hermetic tests pass)
EDITOR_CORRECTION_WORKFLOW  = PROVEN
STORY_INBOX_ENGINEERING     = PROVEN
EDITORIAL_EFFECTIVENESS     = PENDING
JEV_PRODUCTION_AUTHORITY    = NONE
```

Not collapsed into one PASS on purpose: the engineering is proven, the editorial
value of story grouping still needs the human review of the pack.

## 12. Product test

```text
open Stories        -> 2-112 stories instead of 123 raw rows (deterministic build)
open one story      -> where it came from (discoveries, monitors) and how it developed
"Ново развитие"     -> means the story changed, not that a duplicate arrived
correct a grouping  -> Отдели / Обедини from the page, no JSON, no IDs
open Материали      -> every original collected item is still there
```

## 13. STOP

No Telegram, no drafting, no automatic research, no CMS, no scheduler daemon, no
visual polish, no new scrapers, no YouTube change. Awaiting review.
