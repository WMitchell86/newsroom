# V1.1 — EDITORIAL USABILITY DIAGNOSTIC

**Status:** diagnostic only. No code was implemented, changed or fixed.
**Date:** 2026-09-26 · **Baseline commit:** `a1404ff` (`main`)
**Method:** read-only code inspection + measurement against the real canonical stores + safe reproduction on isolated store copies.
**Store safety:** `var/editorial_workflow` and `var/newsroom` (257 files) SHA-256 manifested before the first measurement and re-verified after the last. **Byte-identical.** Proof in §17.

---

## 1. Executive verdict

The owner reported a usability problem. The evidence shows something more serious: **the core editorial path — Story → evidence → Draft — has never been reachable in this deployment, and the UI never said so.**

Three independent P0 defects stack on top of each other.

**P0-1 — There is no producer of the evidence basis the entire Article workflow depends on.**
`var/editorial_workflow/story_research.json` **does not exist**, and nothing in the production path ever creates it. The only writer, `story_research_store.save_story_research` (`story_research_store.py:239`), is called from `tests/` exclusively and from its own internal merge (`:302`). Measured across the real store: **0 of 253 stories** have any facts, sources, gaps or research rounds. Consequently all 7 Articles project `factsAndSources = 0` and `missingInformation = 0` — exactly the "0 / 0 / 0 / 0" the owner photographed.

**P0-2 — «Проучи още» is dead, and dead in a way that cannot be repaired from the UI.**
Research is driven by *gaps*. With zero gaps there are zero research questions, and `research_story` refuses outright (`editor_application.py:757-758`). Reproduced on the real Царево Story:

```
research_story()        -> EditorInvalidTransition: "Няма блокираща липсваща информация за проучване."
start_story_research()  -> EditorInvalidTransition: "Проучването не е налично за тази Story."
```

This is a **circular deadlock**: research requires gaps → gaps are produced only by research → no story can ever acquire a fact. The owner's proposed fix ("Няма достатъчно потвърдени източници за чернова / **Проучи още**") would not have worked — that button refuses. **This is the finding that changes the repair plan.**

**P0-3 — The eligibility predicate disagrees with the generation preflight.**
`draftEligible = focus_confirmed and not blocking_gaps` (`editor_application.py:527`) never consults the evidence basis. The generation preflight requires non-empty `facts` **and** a non-empty `source_url` (`article_generation.py:197-203`) — two gates the projection cannot see. So the UI promises a draft the backend will always refuse. Measured on the owner's own Article:

| Projection says | Command does |
|---|---|
| `draftEligible: true` → "Фокусът е потвърден и няма блокиращи липси…" | `DraftRefused BLOCKING_GAP: "Няма потвърдени факти от източници."` |
| `availableActions: [CHANGE_FOCUS, EDIT, MAKE_DRAFT]` | surfaced as: "Има непопълнена информация, която пречи да продължите." |

Both messages on screen at once. **5 of the 6 preparation Articles** are in exactly this state. The owner correctly predicted this and was right.

**The one "Draft" that exists is a false positive.** `art_c18a9311d2f3c5d` shows `state: draft` only because the owner typed `fdsfsf` into the erroneously-exposed `Редактирай` editor. It is not a generated draft. **No generated Draft has ever been produced in this deployment.**

**Supporting findings, all reproduced:**

* **Today is not sorted chronologically at all.** The effective order is `story_id` **DESC** — a reverse sort on a SHA-derived hex string. The `changed_at` sort key is empty on 251/251 rows because zero members carry `relation == "NEW_DEVELOPMENT"`. **107 of 250 adjacent pairs are out of order relative to the date printed beside them; all 251 rows sit at a different index than their own date implies.** Row 1 is dated five days stale.
* **«Обнови» does spend LLM tokens.** The owner assumed it should not. `story_identity.update` runs a real semantic stage: **23 model calls observed in the last run** (`var/model_usage/2026-09-26.json`). Cost is **$0.00** today because the only reachable route is a free OpenRouter id and `global.paid_enabled = false`. The *operator quota* is consumed regardless (story role soft 60 / hard 100 per day; `ROLE_HARD_BUDGET` already recorded on 2026-09-25).
* **The last-refresh line the owner wants already exists in the store** — `var/newsroom/last_run.json` has `finished_at: 2026-09-26T04:32:51Z`, `new: 37`, `failed: 0`. The SPA simply does not expose it. Transport work, not data work.
* **Pagination already exists in the tree** (`STORY_PAGE_SIZE = 25`, 11 pages) but only under the `/wb-legacy` rollback prefix. The shipped API returns all 253 stories in 194 284 bytes.
* **The double editor is an accidental duplicate**, present since the file's creation commit `b89e8ac`. It survived the entire 564-line test suite because the duplicated `id` makes `getByRole("textbox", {name: "Текст на статията"})` resolve to the *orphan* element.

**Bottom line.** The technical V1 is real and its safety properties hold. But the editor-facing product is blocked by a missing producer (P0-1/P0-2) that no amount of UI work will surface, plus a predicate bug (P0-3) that actively misleads. **The suggested priority order is correct, with one amendment: step 1 must be "make the evidence basis producible", not merely "understand why the draft fails".** Until a story can acquire a first fact, every downstream fix is cosmetic.

---

## 2. Today — actual data + ordering

### 2.1 Counts (measured, real stores)

| Store | Count |
|---|---|
| `var/newsroom/stories.json` → `stories[]` | **253** |
| `var/newsroom/inbox.jsonl` | **300** |
| `var/newsroom/story_editor_metadata.json` | **3** |
| `var/editorial_workflow/editor_articles.jsonl` | **7** |
| Today entries returned by `read_today()` | **258** (251 stories + 7 articles) |

### 2.2 Breakdown by reason

| Attention reason | Count | Note |
|---|---|---|
| `NEW_STORY` | **251** | `status == "NEW"` ⇒ always attention (`editor_projections.py:156-157`) |
| `FOLLOWED_DEVELOPMENT` / `UNREVIEWED_DEVELOPMENT` | **0** | structurally unreachable — see 2.3 |
| Article action | **7** | all 7 Articles have a concrete next action |
| Source problems | 0 | 0 failed in the last run |

`derive_story_attention` has exactly three outcomes (`editor_projections.py:151-160`): `IGNORED`→none, `NEW`→`NEW_STORY`, else `FOLLOWED_DEVELOPMENT` if a followed story has an unreviewed development. **Two of the three reason codes are dead against current data.**

### 2.3 Ordering — **P0: not chronological**

Declared key (`editor_queries.py:137-143`):

```python
story_entries.sort(
    key=lambda row: (
        ((row["story"].get("latest_development") or {}).get("changed_at") or ""),
        row["story"]["id"],
    ),
    reverse=True,
)
```

`latest_development` is `None` for every story, so `changed_at` is `""` for all 251 rows and the sort degenerates to **`story_id` DESC**. Independently confirmed: sorting the 251 ids as strings reproduces the API order exactly.

Member relation distribution across all 253 stories:

```
{'ORIGIN': 253, 'SAME_STORY': 47, 'NEW_DEVELOPMENT': 0}
```

The `changed_at` branch is **dead code against current data** — precisely why the degenerate path is taken 100% of the time.

The timestamp the UI prints is a **different field**: `editor_application.py:1120` sets `"timestamp": detail["latestChangeAt"]`, and `:663` sets `latestChangeAt = latest_material_change_at or last_seen_at`. Consequence, measured on the real response:

```
API first row timestamp : 2026-09-21T17:04:22Z   <- 5 days stale, shown as row 1
adjacent DESC violations                     : 107 / 250
rows at a different index than their date     : 251 / 251
```

**Articles are ordered correctly** (`editor_application.py:1155` sorts the same `timestamp` it emits — 0 violations).

### 2.4 Missing Today capabilities — all verified ABSENT

| Property | Verdict | Evidence |
|---|---|---|
| Time horizon | **ABSENT** | `editor_queries.py` (189 lines) contains no `datetime`/`now`; `read_today` has no date filter |
| Item cap | **ABSENT** | no `[:n]`/`limit`; emits all 251 |
| Pagination | **ABSENT** | `api.py:207-208` matches `/api/v1/today` and passes **zero** query params (contrast `/stories`, `:216-220`) |
| Prioritization | **ABSENT** | exactly one `sort()` per group; no score, tier or bucket |
| Category/importance | **ABSENT** | story field set has no `priority`/`score`/`importance`/`category`/`topic`/`weight` |

### 2.5 The 251 items are 90.9% historical backlog

| Day | Stories | Share |
|---|---|---|
| 2026-09-26 (today) | 23 | 9.1% |
| 2026-09-25 | 142 | 56.1% |
| 2026-09-21 | 88 | 34.8% |

**230 / 253 (90.9%) are older than 24h** relative to the last run. Only 23 are genuinely current. A 3-day collection gap (09-22…09-24) contributed 0 stories. The owner's reading is correct: **this is a backlog dump, not "what needs attention today".** Unreviewed legacy stories are treated as fresh attention because `status == "NEW"` has never been cleared.

### 2.6 Signals present in the data but unused by Today

```
inbox 'priority'          : {high: 187, normal: 76, low: 37}   <- read by nothing in the Today path
inbox 'source_kind'       : {official: 132, media: 80, regional: 52, aggregator: 36}
story 'needs_review'      : present on all 253, read by no Today projection
```

The legacy inbox view *does* filter on `priority`/`authority` (`workbench/newsroom.py:322-331`) — but that is the dead `/wb-legacy` surface.

### 2.7 Server cost — N+1 amplification

```
read_today() -> 258 entries in 2.59s
   story_store.read_store                    x 259
   inbox_store.read_items                    x 259
   editor_article_store.read_editor_articles x 281
   _story_detail                             x 251
```

Cause: `editor_application.py:1113` calls `_story_detail(id)` once per entry, and `_story_detail` (`:669-676`) re-reads all four stores each time. Response payload: **142 873 B**. P1, and it grows linearly with story count.

---

## 3. Stories — actual data + ordering/payload

### 3.1 Implementation

`editor_application.list_stories` (`:1167-1191`), served at `GET /api/v1/stories` (`api.py:216-220`). Final line:

```python
1190    result.sort(key=lambda row: (row["latestChangeAt"], row["id"]), reverse=True)
```

**This ordering is correct** and is the exact opposite of Today's behaviour — which is what makes the Today defect so visible. Measured: 0 adjacent inversions out of 252.

### 3.2 Payload and render

| Measure | Value |
|---|---|
| Rows in one response | **253** (no cap, no page, no `total`, no `hasMore`) |
| Payload | **194 284 B** raw / 21 662 B gzip-equivalent |
| Average per story | 768 B |
| Browser render | all 253, bare `.map`, no virtualization (`StoryListPage.tsx:113-135`) |

### 3.3 Pagination exists — but is unreachable from the SPA

```
legacy workbench.stories_view(page=1):  25 rows, page_count 11, 25 271 B, 0.01s
live v1 /api/v1/stories:                253 rows, 194 284 B
```

`spa.py:58 DEFAULT_MODE = MODE_SPA`; the legacy paged view survives only at `spa.py:63 LEGACY_COMPAT_PREFIX = "/wb-legacy"`. **The owner's P1-5 is a projection/transport task, not new pagination work.**

### 3.4 Title/summary redundancy — **100%**

* **253/253** summaries are identical or near-identical to the title; **248/253 (98.0%)** at similarity ≥ 0.90.
* Median summary 85 chars vs median title 86 chars. ~25% of the payload is the same string twice.
* Cause: `editor_application.py:655-656` derives both from the same representative inbox item.

### 3.5 Source name stuffed into the title — **246/253 (97.2%)**

Titles end in a `" - X"` suffix across **37 unnormalized variants** of ~10 brands. The list DTO has **no structured source field** (`_publication_dto`, `:602-617`, is detail-only), so the only source signal is that text suffix. Simultaneously a cosmetic defect and a missing-data defect.

### 3.6 Filters — 2 of 4 are permanently empty

| filter | rows |
|---|---|
| `all` | 253 |
| `followed` | 1 |
| `developments` | **0** |
| `ignored` | **0** |

Search is a naive `casefold()` substring over `title + summary` only (`:1187`) — no ranking, not id/source/URL.

---

## 4. Refresh semantics + cost surface

### 4.1 The path

| # | Layer | Location |
|---|---|---|
| 1 | Button `«Обнови»` | `TodayPage.tsx:97-105` |
| 2 | Mutation | `TodayPage.tsx:82-93` — invalidates only `today` + `stories` |
| 3 | `POST /api/v1/today/refresh` | `client.ts:388-401` |
| 4 | Poll, **60 s budget**, result **discarded** | `client.ts:376-386`, `:293-315` |
| 5 | Route → `202 {operationToken}` | `api.py:209-215` |
| 6 | Command + capability gate | `editor_application.py:880-932` |
| 7 | `newsroom_refresh.refresh_newsroom(root=root)` | `:919-923` |
| 8 | `newsroom_run.collect(use_lock=True)` | `newsroom_refresh.py:198-210` |
| 9 | `story_identity.update(semantic=…, call_model=…)` | `newsroom_refresh.py:216-224` |

### 4.2 Cost surface — the owner's assumption is wrong on tokens, right on money

| Item | On «Обнови»? | Evidence |
|---|---|---|
| `news.google.com` HTTPS GET | **YES**, 8 today (keyless) | `search.py:469` |
| `burgascouncil.org` HTTPS GET | YES, 1 today | `sources.json` |
| YouTube / Invidious | NO (not wired) | `newsroom_run.py:53-60` |
| Brave / Serper / Exa (paid search) | **NO** | not imported; no keys in `.env` |
| **LLM call (free OpenRouter)** | **YES — 23 observed** | `var/model_usage/2026-09-26.json` |
| LLM call (Gemini) | only if `GEMINI_API_KEY` in process env (was `NO_KEY`) | ledger |
| Paid LLM route (`luna-pro`) | NO — `global.paid_enabled = false` | `model_router.py:356` |
| **Model tokens** | **YES** | `ok: 23` in today's ledger |
| **Monetary cost today** | **$0.00** | `cost_usd: 0.0`, `paid_cost_usd: 0.0` |
| Operator quota consumed | **YES** (story soft 60 / hard 100/day) | `ROLE_HARD_BUDGET` on 2026-09-25 |
| Rate-limit surface | YES (Google News 429 already observed) | `news-search.last_error` |

**Cadence is real**: 9 of 31 sources are due; the other 22 are genuinely skipped (`newsroom_run.py:138-152`, `:191-192`). Each click re-fetches only the due set.

**Privacy caveat**: the free route is `public_only: true` — newsroom titles/summaries go to a public endpoint that may train on the request (`generate.py:407-412`).

**Latency defect risk**: the observed identity stage took **3 m 45 s**; the SPA waits 60 s. A button-initiated refresh reaching the semantic path on many new items will time out client-side, and re-click is blocked by the lock until the work finishes.

### 4.3 Metadata the owner wants — **already persisted, just not exposed**

`var/newsroom/last_run.json`, verbatim:

```json
{ "finished_at": "2026-09-26T04:32:51Z", "new": 37, "failed": 0, ... }
```

| Owner wants | Field that already exists |
|---|---|
| `Последно обновяване: …` | `last_run.json → finished_at` |
| `X нови публикации` | `last_run.json → new` (also `collected`, `duplicate`) |
| `Y нови истории` | `refresh_newsroom → stories.newStories` (**transient only**) |
| `Z проблема с източник` | `last_run.json → failed`; `source_health.json` (32 records) |

**Why the SPA can't show it:** `read_today` (`editor_application.py:1156-1164`) and `TodayProjection` (`dto.ts:230-235`) expose only four attention fields. No last-refresh field exists in the DTO at all. The **legacy HTML view still renders the same data today** (`html.py:1549-1552`).

`stories.newStories` is the one value returned but not persisted — persisting it is a small change to `source_health.record_run`.

---

## 5. Problem Story trace — `s16943311c9c782f` (Царево)

Source/publication → inbox → Story → evidence → Article:

| Step | Finding |
|---|---|
| Underlying Publications | **1** (`members`: 1 × `ORIGIN`) |
| Inbox item | `i361d8f371042d77` |
| Source id | `tsarevo-municipality`, `source_kind: official`, `factual_authority: false` |
| **Actual source URL** | **an opaque `news.google.com/rss/articles/CBMi4AF…` redirect** — the real article URL was never resolved |
| Publisher domain | `pronewsdobrich.bg` |
| Was the original page opened? | **NO** — no fetch, no `EvidencePacket`, no research round |
| `story_research.json` | **does not exist** |
| Basis | `facts: 0, sources: 0, gaps: 0, research_rounds: 0` |
| **Why Facts/Sources == 0** | the basis store is absent; `get_story_research` returns `_empty(story_id)` for an absent row (`story_research_store.py:213-217`) — **silently, never an error** |
| **Why Missing Information == 0** | same root cause. `assessed_at` is a *timestamp of an empty assessment*, which the UI renders as "Оценено на …" — implying a real assessment that never happened |
| Is "no gaps" treated as sufficiency? | **YES** — `draftEligible` (`:527`) never inspects facts |

**Note on the missing `source_url` gate.** Even if a fact existed, `_draft_snapshot` (`:950-957`) derives `source_url` **only from a fact's source URL** — it never falls back to the inbox item's URL. With the Google News redirect this would in any case not be a usable source. The gate chain requires *both* a fact and a resolvable URL, and the refresh path guarantees neither.

---

## 6. Preparation/readiness contradiction — **P0**

### 6.1 The two predicates

**C1 — preparation readiness** (`editor_application.py:521-529`):

```python
preparation = {
    "focusConfirmed": focus_confirmed,
    "blockingGaps": blocking_gaps,
    "nonBlockingGaps": non_blocking_gaps,
    "draftEligible": focus_confirmed and not blocking_gaps,   # <-- evidence never consulted
    "availableActions": actions,
}
```

**C2 — generation readiness** (`article_generation.py:197-203`):

```python
if snapshot["blocking_gaps"]:
    raise DraftRefused("BLOCKING_GAP", "Има непопълнена информация, която пречи да продължите.")
if not snapshot["facts"]:
    raise DraftRefused("BLOCKING_GAP", "Няма потвърдени факти от източници.")
url = str(snapshot.get("source_url") or "")
if not url:
    raise DraftRefused("BLOCKING_GAP", "Няма отворен източник за тази история.")
```

Both are mapped to the **same** editor-facing code `BLOCKING_GAP`, which the client renders as the single message "Има непопълнена информация, която пречи да продължите." (`editor_application.py:993-996`).

### 6.2 How both are visible simultaneously

They are different predicates over the same state, so the projection can be green while the command refuses. Confirmed on the real Article in the owner's exact pre-`Редактирай` state (isolated copy):

```
state            : preparation
focusConfirmed   : true
blockingGaps     : []
draftEligible    : true        <- renders the green "Фокусът е потвърден..." text
factsAndSources  : 0           <- right rail: "Няма налични факти и източници."
availableActions : [CHANGE_FOCUS, EDIT, MAKE_DRAFT]

app.start_article_draft(...)  ->  EditorBlockingGap:
                                 "Има непопълнена информация, която пречи да продължите."
```

The refusal occurs **before any provider call** — see §7.

**Confounding factor:** `focus` itself is a placeholder constant. All 7 Articles carry the identical string *"Да разкажем какво се е променило в тази история и защо е важно за хората."* It is not a suggestion produced per Story; it is one constant applied to all of them. Confirming is therefore not a meaningful editorial act, which is what makes `focus_confirmed` a weak gate.

---

## 7. Draft failure reproduction

**Method:** isolated `copytree` of both real stores into `/tmp/v11diag/`, with `NEWSROOM_DIR` / `WB_EDITORIAL_WORKFLOW_DIR` / `WB_STORY_RESEARCH_PATH` redirected. The real stores were never opened for writing.

| Probe | Result |
|---|---|
| `_draft_snapshot` facts | **0** |
| `_draft_snapshot` blocking_gaps | **0** |
| `_draft_snapshot` source_url | **`''`** |
| `article_generation.evaluate` | `DraftRefused BLOCKING_GAP — "Няма потвърдени факти от източници."` |
| `app.start_article_draft` | `EditorBlockingGap` |
| With a source_url but still 0 facts | **still refused** (facts gate fires first) |
| With 1 fact + source_url | **PASSES** — the preflight is satisfiable |

**The failure occurs strictly before the paid transport boundary.** No model call, no network call, no cost. The gate chain is `blocking_gaps → facts → source_url → safety → generate`. The first two fail.

**Scope: 5 of 6 preparation Articles** project `MAKE_DRAFT` with 0 facts and will always refuse:

```
art_d57e1dbe08a4b83  preparation  facts=0 gaps=0  [CHANGE_FOCUS, EDIT, MAKE_DRAFT]
art_0e29cbfcd51eb77  preparation  facts=0 gaps=0  [CHANGE_FOCUS, EDIT, MAKE_DRAFT]
art_fe93ff9151f27c4  preparation  facts=0 gaps=0  [CHANGE_FOCUS, EDIT, MAKE_DRAFT]
art_1629f22a652292a  preparation  facts=0 gaps=0  [CHANGE_FOCUS, EDIT, MAKE_DRAFT]
art_0699b8347457391  preparation  facts=0 gaps=0  [CHANGE_FOCUS, EDIT, MAKE_DRAFT]
art_2a3547ac1f018d1  preparation  facts=0 gaps=0  [SELECT_FOCUS]
art_c18a9311d2f3c5d  draft*       facts=0 gaps=0  [CHANGE_FOCUS, EDIT]
   * false positive: body "fdsfsf" typed by the owner via the mis-exposed EDIT button
```

---

## 8. EDIT exposure

### 8.1 Where it comes from

**Backend.** `editor_application.py:452-459`:

```python
# Backend-authorized manual continuation uses the same editor and the
# same atomic content save. There is no separate manual Draft mode.
actions = ["CHANGE_FOCUS", "EDIT"]
```

Line 454 is **unconditional** inside the focus-confirmed preparation branch. Note also that `content` is a parameter but is **never read** in this branch — an empty body does not suppress EDIT.

**Frontend.** `PreparationWorkspace.tsx:191` faithfully mirrors it; it invents nothing.

### 8.2 Is generation-failure context persisted? — **NO**

* The operation registry (`story_operations.py:10-13`) is an in-process `OrderedDict`, `TTL_SECONDS = 900`, pruned and LRU-evicted. A restart loses it; `get(token)` requires the caller to already hold the token.
* `article_generation._ACTIVE` (`:95`) is likewise in-process and covers only *running* work.
* `editor_article_store.validate_editor_article` (`:174-260`) has **no** field for attempt count, last failure, or refusal code. `internal_refs` holds only lineage ids.

So there is **no durable representation of "generation failed"** anywhere. The frontend cannot distinguish the two cases because the backend never tells it.

### 8.3 Verdict

**Not a frontend bug. Intentional-by-design but wrong for the product — a backend predicate gap.** It is locked by four test assertions (`test_workbench_api.py:454,487`; `test_article_draft_command.py:227`; `test_article_ready_command.py:403,424`) and by a dedicated frontend test that encodes manual continuation as the *feature* (`frontend.test.tsx:944`).

The durable raw material for a correct predicate already exists but is unused: `article_generation._attempts` (`:155-160`) counts generation attempts in `live_evidence.jsonl`. **Caveat:** it counts *all* attempts, not failures, so it cannot by itself distinguish success from failure; it would need pairing with the pipeline's persisted refusal state.

**One purely frontend defect in the same area:** `PreparationWorkspace.tsx:228` renders "Текстът на статията още не е създаден." **unconditionally**, outside the `editing` ternary (`:120-123`), so it stays visible *while* the editor is open and has already saved a body — the notice contradicts the editor directly above it. `.noDraftNotice` is a full-width tinted bar (`ArticleWorkspace.module.css:498-503`), not a footnote.

---

## 9. Double-editor explanation

**Verdict: accidental duplicate rendering, present since the file was created.** `git blame -L 183,232` attributes every line to commit `b89e8ac` (the file's creation); it was never touched by `73236b6` or the SPA cutover `0a1dd78`.

### 9.1 Field-by-field

| # | Component | Label | DOM id | State | API field |
|---|---|---|---|---|---|
| 1 | `<input>` `:192-198` | „Заглавие" | `article-working-title` | `title` | `title` |
| 2 | `<textarea>` `:199-205` | **none (orphan)** | `article-working-body` | `body` | `body` |
| 3 | `<textarea>` `:211-218` | „Текст на статията" | `article-working-body` **(duplicate id)** | `body` | `body` |

### 9.2 Both textareas write the same state and the same API field — YES

* Both bind `value={body}` to the same `body` state (`:201`, `:215`).
* Both use the identical closure `onChange={(event) => change(title, event.target.value)}` (`:203`, `:216`).
* `change` (`:110-118`) writes `localRef.current.body` and schedules the same autosave.
* `flush` sends `snapshot.title, snapshot.body` (`:68-73`) → `PUT /api/v1/articles/{id}/content`.

`ArticleContentEditor` is mounted **once**. The title field is **not** duplicated.

### 9.3 Why the test suite never caught it

`getByRole("textbox", {name: "Текст на статията"})` resolves to **1** element — the *orphan* — because `getElementById` returns the first match for the duplicated id. Measured with `computeAccessibleName`:

```
[0] INPUT    accName="Заглавие"
[1] TEXTAREA accName="Текст на статията"
[2] TEXTAREA accName=""          <- the orphan has NO accessible name
```

So **every one of the 4 editor tests** (`frontend.test.tsx:838,864,898,950`) drives the wrong element and the labelled one is never asserted. The rendered DOM matches screenshot 06 exactly: title, large unlabelled box, „Текст на статията" label, second identical box.

### 9.4 Smallest repair

**Delete `ArticleContentEditor.tsx:209-218`.** One edit removes the second textarea, the second autosave-retry button and the second navigation warning.

---

## 10. Empty-space / UX causes

### 10.1 Article — why the right column is empty

`ArticleWorkspace.module.css:58-64`:

```css
.workspaceGrid {
  display: grid;
  grid-template-columns: minmax(0, 940px) 300px;
  align-items: start;
  gap: 32px;
}
```

A **fixed** track, not content-sized, so the 300px column is always reserved. Worse, it is *painted* even when empty (`:279-285` gives it padding, background, border, radius), and its `Disclosure` is **closed by default** (`EditorPrimitives.tsx:42,48` — `defaultOpen = false`, body `hidden={!open}`). On a fresh load the 300px column contains only a collapsed button.

**Total dead width: 332px.** Inside the left column, `.contentTitle`/`.contentBody` cap at `max-width: 780px` (`:118,:127`) inside an 860px content box, wasting a further 80px.

`PreparationWorkspace` has the identical defect: `.preparationGrid` (`:354-359`) uses the same `940px 300px`, and `<aside>` is always rendered (`:218-226`) with a hardcoded heading — never collapsible.

The `940px` figure appears in four rules: `ArticleWorkspace.module.css:60`, `:30-32`, `:45-51`, and `shared/ui.module.css:69` (`.articleLayout` — **orphaned pre-SPA dead CSS**). `.articles { max-width: 1272px }` is exactly `940+32+300`, leaving zero slack on a wide monitor.

### 10.2 Story — sections that always reserve vertical space

`StoryWorkspace.tsx:362-389` renders **seven** blocks unconditionally. Each costs `margin-top: 40px` + an `EmptyState` (`ui.module.css:11, 88`) ≈ **123px per empty section**. `Publications` and `Chronology` additionally render `<EmptyState>` *inside a `hidden` disclosure body* (`:196,:216`) — a defect independent of any layout opinion.

**All seven are pure presentational reads with no mutation and no callback.** Two already have `return null` guards for empty collections (`:82`, `:115`). Hiding a zero-item section is a **no-op in the domain** — no action, no state, no server call.

### 10.3 Owner proposals, assessed

* **"If the evidence rail is empty → expand the main editing area"** — correct, and cheaper than expected. `grid-template-columns: minmax(0, 1fr) auto` with a `minmax(0, 300px)`-constrained child collapses the track to 0 **purely in CSS, with no JSX edit and no domain impact**, because the evidence data is fetched regardless.
* **"Increase vertical density"** — supported by the measurements above.
* **Compounding effect:** the duplicated textarea is `min-height: 420px` (`:562`), so the double-editor bug alone adds ~430px of dead vertical space to every editing view.

---

## 11. Settings reality

`SettingsLanding.tsx` (53 lines) is **100% placeholder** — four subsections, each an explicit "Още не е налично", with a self-declared placeholder note (`:34-36`) and a dead-by-construction list (`:37-51`). Locked in by a test. CSS for all four subsections **is** present, proving the design was prepared but the data never was.

Routing: `/settings` is a dead stub; the complete route table (`App.tsx`, 35 lines) contains no settings children. The frontend API client has **zero** settings endpoints, and `api.py:204-328` has no settings route.

### 11.1 What already exists

| Surface | Data exists? | Service fn? | `/api/v1`? | Effort |
|---|---|---|---|---|
| **Източници** | **YES** — 35 registry rows, 32 health records, `last_run` | `newsroom.sources_view()` + 8 write fns | none | **Projection only** |
| **AI и разходи** | **YES** — day-ledgers (up to 1000 calls), budgets, prices, `model_health` (6) | `model_router.status_report()` — **one call** | none | **Projection only** (~15 LOC) |
| **Входни канали** | **YES** — `registry.json`, `queue.json`, `runs.jsonl` | `intake_registry()` / `intake_view()` | none | Display projection; **write side owner-frozen** |
| **Система** | scattered, **no aggregate** | **none anywhere** | none | **Real new work** |
| last refresh | `last_run.json` | `read_last_run()` | token-only, transient | Small DTO field |

**Bottom line: of the four advertised subsections, three are already fully data-backed and need only transport + rendering.** Only «Система» requires a new domain composition. The owner's preference for real Settings is well-founded and cheaper than expected — but it still belongs *after* the editorial path, as proposed.

**Two caveats:** (a) `var/model_usage` shows `paid_cost_usd = 0.0` for every day, so cost rendering would be exercised for the first time when a paid route actually runs; (b) `PRICES_USD_PER_MTOK` covers only 4 models — any other model yields `estimate_cost == 0.0`, which a cost view would silently display as `$0.00`.

---

## 12. Existing classification / ranking primitives

| # | Primitive | Exists? | Canonical location | Real data? | In `/api/v1`? | In SPA? |
|---|---|---|---|---|---|---|
| K.1 | **Locality / region** | **NO** | — | 0/300, 0/253 | NO | NO |
| K.2 | **Topic / category** | **NO** (editorial) | corpus taxonomy only | archive corpus (150 articles) | NO | NO |
| K.3a | Source priority | **YES** | `sources_registry.py:37,41` | sources {high:11,normal:14,low:10} | **dropped** | NO |
| K.3b | Source authority | **YES** | `sources_registry.FIELDS.factual_authority` | {True:29, False:6} | **dropped** | NO |
| K.3c | Source kind / tier | **YES** | `sources_registry.py:34` | {official:27, regional:5, media:2, aggregator:1} | **dropped** | NO |
| K.4 | **Story priority / importance / score** | **NO** | — | 0/253 | NO | NO |
| K.5a | Story clustering | **YES** | `story_identity.py` | 253 stories; 47 `SAME_STORY` | indirect | YES |
| K.5b | **Independent-source count** | **YES (computed only)** | `story_store.metrics()` → `publisher_count` | derived every read | **NOT in any DTO** | NO |
| K.5c | Cross-source corroboration judgement | **NO** | per-fact flag only | transcripts | NO | NO |
| K.6 | Followed Story | **YES** — most complete primitive | `story_editor_metadata.py:22-27` | 3 rows (1 followed) | YES | YES |
| K.7 | Meaningful development count | **YES** (canonical) | `editor_projections.py:97-115` | **0 `NEW_DEVELOPMENT` in live store** | YES | YES |
| K.8 | Semantic dedup | **YES** (lexical + narrow LLM; **no embeddings**) | `story_identity.strong_anchor` | 47 `SAME_STORY` | indirect | YES |

### 12.1 Two findings that directly shape the owner's plan

**Positive — the cheapest ranking input already exists.** `story_store.metrics().publisher_count` (`story_store.py:575-595`) is a fully-implemented, real-data-backed "number of independent sources", computed on every read and **rendered on the legacy HTML story page** (`html.py:1740-1742`) — and simply never added to the editor DTO. Surfacing it is a one-field projection, not new domain work. `followed` (K.6) and `meaningful_developments` (K.7) are the two reference patterns showing exactly how a new editor flag must be wired end-to-end.

**Negative — locality, topic and story priority do not exist anywhere.** Not in the backend schema, not in the 253 stories / 300 inbox items, not in `/api/v1`, not in the frontend. Every hit for those words in `var/` belongs to the style corpus, the search provider or the transcript pipeline. `BACKLOG.md:15` ("L2 editorial triage") is unchecked, and three planning documents record "add AI ranking" as explicitly out of scope.

**Design constraint:** every newsroom store uses a **closed schema that rejects unknown keys** (`inbox_store.py:80-81`, `story_store.py:176-178`, `story_editor_metadata.py:88-92`). Adding locality/topic/priority to a Story is **not** a matter of writing an extra key — it needs a deliberate `STORY_FIELDS` schema change plus a migration story for 253 rows, or a parallel metadata store following the `story_editor_metadata` pattern.

**Seeds already available:** `var/style_analysis/category_summary.json` is the only real Bulgarian topic taxonomy with data (10 values, 150 articles) but does **not** contain the proposed categories. `workflow/angles.py:19-34` is a 7-axis editorial-value rubric including `burgas_novelty` — transcript/angle path only. `style/features.py:13-38 LOCATION_TOKENS` holds 24 explicit Burgas-region tokens.

No AI ranking system is designed here. This section is inventory only.

---

## 13. Confirmed bugs

### P0-1 — The evidence basis has no producer. *The editorial path is structurally unreachable.*

* **Evidence:** `var/editorial_workflow/story_research.json` does not exist. `save_story_research` (`story_research_store.py:239`) is called only from `tests/` and from its own merge (`:302`). Measured: **0/253 stories** have facts, sources, gaps or research rounds; **0/300 inbox items** have ever been opened. `get_story_research` returns `_empty()` for an absent row (`:213-217`) — **silently, never an error**, so the system reports "no gaps" as if it meant "sufficiently researched".
* **Root cause:** B4A Story Research was built as an isolated module and wired to a command, but nothing was connected to the Story lifecycle. The refresh path deliberately does not call it (`newsroom_refresh.py:14-17`), and no other entry point does either.
* **Smallest repair surface:** the producer decision (seed the basis from the representative inbox item at grouping time, vs. a first-class research round triggered by opening a Story), plus a non-silent failure mode for an absent store. **This is a design decision, not a one-line fix — it should not be attempted as one.**
* **Regression tests:** every Story projects a non-empty basis or an explicit "not assessed" state; `get_story_research` never reports an empty basis as "no gaps"; an end-to-end Story→first-fact test.

### P0-2 — «Проучи още» is permanently dead (circular deadlock).

* **Evidence:** reproduced on the real Царево Story: `research_story` → "Няма блокираща липсваща информация за проучване."; `start_story_research` → "Проучването не е налично за тази Story." Source: `editor_application.py:757-758` refuses when the question list is empty; the list is derived from gaps (`:745-746`); gaps come only from research.
* **Root cause:** research questions are derived from a gap set that only research can create.
* **Smallest repair surface:** make the first research round unconditional for an un-assessed Story (it does not need pre-existing gaps to decide *what* to look for — it needs the Story, its representative publication and a topic).
* **Regression tests:** a Story with an empty basis can start exactly one research round; the round produces ≥1 gap or ≥1 fact; the UI exposes the action whenever the basis is empty **or** gaps exist.

### P0-3 — `draftEligible` ignores the evidence basis; contradicts the generation preflight.

* **Evidence:** §6.2. `draftEligible = focus_confirmed and not blocking_gaps` (`:527`) vs. the preflight's `facts` + `source_url` gates (`article_generation.py:199-203`). Reproduced on the owner's Article; 5/6 preparation Articles affected. Both refusal reasons collapse into one client message (`:995-996`).
* **Root cause:** the projection was specified over *preparation* state while generation was specified over *evidence* state, and no shared predicate was introduced.
* **Smallest repair surface:** one shared eligibility function used by both the projection and `evaluate`; distinct client-visible codes for "no facts" vs "no open source"; `draftEligible` must also drive a *reason*, not just a boolean.
* **Regression tests:** for a matrix of (facts, gaps, source_url, focus) combinations, assert `preparation.draftEligible == (generation preflight passes)`; assert the two screens cannot disagree; assert an empty basis never renders green.

### P1-1 — Today is ordered by `story_id` DESC, not chronologically.

* **Evidence:** §2.3. 107/250 adjacent inversions vs. the displayed date; 251/251 rows misplaced; row 1 is 5 days stale.
* **Root cause:** the sort key's primary component (`latest_development.changed_at`) is empty because no member carries `NEW_DEVELOPMENT`; the code path was never exercised with real data.
* **Smallest repair surface:** sort on the same field the UI prints (`latestChangeAt`) — a one-line change; separately, decide what populates `NEW_DEVELOPMENT`.
* **Regression tests:** ordering invariant over a fixture containing developments and ties; a test asserting the displayed timestamp is non-decreasing.

### P1-2 — Today is an unbounded backlog dump.

* **Evidence:** 251 rows, 90.9% older than 24h; no horizon, no cap, no pagination (`api.py:207-208`).
* **Root cause:** `status == "NEW"` doubles as "needs attention" and is never aged out.
* **Smallest repair surface:** a time horizon + cap in `read_today`; mark stories seen on open.
* **Regression tests:** cap honoured; items outside the horizon excluded; a fixture of 1 000 stories returns ≤ cap.

### P1-3 — `/api/v1/stories` returns all rows, unpaginated.

* **Evidence:** 253 rows / 194 284 B; pagination exists only at `/wb-legacy` (`STORY_PAGE_SIZE = 25`).
* **Smallest repair surface:** add page params to `list_stories` + `api.py:216-220` + DTO + `StoryListPage`; the legacy view is a ready reference.
* **Regression tests:** page size respected; `total`/`hasMore` correct; filters applied before paging.

### P1-4 — Title/summary duplication and source-name suffix.

* **Evidence:** 253/253 near-identical; 246/253 (97.2%) end in a `" - X"` source suffix across 37 variants; no structured source field in the list DTO.
* **Root cause:** `_story_summary` (`:655-656`) derives both from one item; the publisher name is only in the title text.
* **Smallest repair surface:** stop emitting a summary when it restates the title; add a structured `source` to the list DTO (the data already exists in the inbox item).
* **Regression tests:** summary suppressed when redundant; source present and equal to the registry name.

### P1-5 — No last-refresh / run-summary surfaced.

* **Evidence:** §4.3. The data is persisted; the DTO has no field for it.
* **Smallest repair surface:** add a `lastRefresh` block to the Today projection reading `last_run.json`; persist `stories.newStories` if it must be shown.
* **Regression tests:** the SPA shows the persisted `finished_at`/`new`/`failed` verbatim; a failed source appears in `problems`.

### P1-6 — Double editor.

* **Evidence:** §9. Duplicate block `ArticleContentEditor.tsx:209-218`, present since `b89e8ac`; both textareas write `body`; the duplicate `id` makes every existing test drive the orphan.
* **Smallest repair surface:** delete lines 209-218.
* **Regression tests:** exactly one `textarea` for the body; the labelled control is the one under test; add an assertion that fails if a second body field appears.

### P1-7 — `EDIT` exposed on every preparation Article.

* **Evidence:** §8. `editor_application.py:454` unconditional; no failure context is persisted anywhere; locked by 4 test assertions.
* **Root cause:** C3 shipped manual continuation as an always-on escape hatch, with no durable state to distinguish it from deliberate hand-writing.
* **Smallest repair surface:** gate EDIT in `_article_actions` on a *durable* failure/attempt signal; `article_generation._attempts` is a starting point but counts all attempts and must be paired with a persisted refusal state.
* **Regression tests:** a fresh preparation Article with focus confirmed does **not** offer EDIT; a preparation Article after a recorded generation failure does.

### P1-8 — 300px evidence column permanently reserved and painted.

* **Evidence:** §10.1. Fixed track, painted background, closed disclosure.
* **Smallest repair surface:** `grid-template-columns: minmax(0, 1fr) auto` + a constrained evidence child — CSS only, no JSX.
* **Regression tests:** with zero facts the main column spans the content width; with facts present the rail renders at 300px.

### P1-9 — N+1 store re-parsing in `read_today` (259×/281×, 2.59 s).

* **Evidence:** §2.7. `_story_detail` per entry re-reads all four stores.
* **Smallest repair surface:** batch the join in `read_today` (`list_stories` already does it correctly — use it as the reference).
* **Regression tests:** instrumented store-reader call counts asserted to be O(1), not O(n).

### P2 — Story workspace empty sections, `noDraftNotice`, and the focus placeholder

* Seven sections always reserve ~123px each; `EmptyState` rendered into `hidden` disclosure bodies (`StoryWorkspace.tsx:196,216`); `noDraftNotice` rendered unconditionally while the editor is open (`PreparationWorkspace.tsx:228`); `.articleLayout` is orphaned dead CSS (`ui.module.css:66-83`).
* All are presentational, collapsible without domain change.

---

## 14. UX / design deficiencies

1. **The placeholder focus is a single constant applied to all 7 Articles** — *"Да разкажем какво се е променило в тази история и защо е важно за хората."* The owner's judgement is right: better to show nothing than this. It also means `focus_confirmed` is not evidence of an editorial decision.
2. **"Няма налични факти и източници." is not actionable.** It should say *why* there are none and offer the one action that can change it — but only once P0-2 makes that action real.
3. **Four identical "Още не е налично" strings** read as an unfinished product. Three of the four Settings surfaces are in fact data-backed and cheap (§11).
4. **`assessed_at` on an empty basis renders as "Оценено на …"** — implying an assessment that never happened. An empty basis should not carry a confident assessment timestamp.
5. **2 of 4 Stories filters are permanently empty** (`developments` = 0, `ignored` = 0) yet are presented as working navigation.
6. **Search is an unranked `casefold()` substring** over title+summary.
7. **The refresh button gives no feedback for up to 60 s** while the work it triggers took 3 m 45 s last run — the client poll budget is shorter than the real task.

---

## 15. Missing capabilities

| Capability | Status | Note |
|---|---|---|
| Any producer of Story evidence | **missing (P0)** | the blocking gap |
| A working first research round | **missing (P0)** | circular dependency |
| Today time horizon / cap / pagination | **missing** | P1-2 |
| Stories server-side pagination | **missing from the API** | exists at `/wb-legacy` |
| Last-refresh display | **missing from the DTO** | data already persisted |
| Locality classification | **missing** | no field anywhere; closed schema needs a migration |
| Topic classification | **missing** | only a style-corpus taxonomy exists |
| Story priority / score | **missing** | no field anywhere |
| Independent-source count in the editor DTO | **missing** | **already computed** — one-field projection |
| Story sort options in the UI | **missing** | list sorts correctly but offers no choice |
| Settings: Източници / AI / Входни канали | **missing transport only** | data exists |
| Settings: Система | **missing** | requires a new composition |

---

## 16. Recommended repair sequence

Reordering is required: **P0-1 and P0-2 come before P0-3**, and all three come before every UI item. Until a Story can acquire a first fact, a green "draft ready" screen is worse than an honest dead end.

**Stage 0 — unblock the evidence path (P0). No UI work.**
1. Decide and implement the **producer** for the Story evidence basis. The system currently has none.
2. Make an un-assessed Story distinguishable from an assessed-and-clean one; stop rendering `assessed_at` for an empty basis.
3. Make the first research round unconditional for an un-assessed Story, breaking the deadlock.
4. Unify the eligibility predicate so the projection and the preflight cannot disagree; give "no facts" and "no open source" distinct, honest messages.

**Stage 1 — remove the false and misleading surfaces (P0/P1).**
5. Delete the duplicated editor block; make the body label bind to the field under test.
6. Gate `EDIT` on a durable failure signal; stop rendering `noDraftNotice` unconditionally.
7. Fix Today ordering to the field the UI prints; add a horizon and a cap.

**Stage 2 — daily-operation usability (P1).**
8. Stories pagination (reuse the legacy `STORY_PAGE_SIZE = 25` pattern), drop the redundant summary, add a structured source field.
9. Expose `last_refresh` from the already-persisted `last_run.json`.
10. Collapse empty sections; make the evidence rail collapse when empty.
11. Batch the `read_today` join (N+1 → O(1)).

**Stage 3 — Settings (owner-preferred, now cheap).**
12. Източници, AI и разходи, Входни канали as pure projections; Система as a small new composition. Persist `stories.newStories` so the refresh line is complete.

**Stage 4 — only then the operational roadmap (S1/S2).**

**Explicitly deferred:** locality/topic/priority classification and any "Топ за редакцията" ranking. When it is taken up, note that (a) `publisher_count` is already computed and needs only a DTO field, (b) `followed` and `meaningful_development_count` are the two end-to-end reference patterns, and (c) the closed story schema means a deliberate migration story is required, not an added key.

**Note on the owner's proposal.** The suggested order is correct in substance. The one amendment: item 1 must be *"make the evidence basis producible"*, not *"understand why the draft fails"* — the answer to the latter is already established above, and acting on it without item 1 will only move the failure.

---

## 17. Store safety proof

Baseline captured before the first measurement; re-verified after the last.

```bash
$ find var/editorial_workflow var/newsroom -type f -not -name '*.lock' -print0 \
    | sort -z | xargs -0 sha256sum > /tmp/v11diag/store_baseline.sha256
$ wc -l /tmp/v11diag/store_baseline.sha256
257 /tmp/v11diag/store_baseline.sha256
$ sha256sum /tmp/v11diag/store_baseline.sha256
d54a3c9da3253b8c4bc20010c47af08b1f3c6b502e5126ac494e4ecfe7dc7a06

# ... all diagnostic work, on isolated copytree copies under /tmp/v11diag/ ...

$ find var/editorial_workflow var/newsroom -type f -not -name '*.lock' -print0 \
    | sort -z | xargs -0 sha256sum > /tmp/v11diag/store_after.sha256
$ diff /tmp/v11diag/store_baseline.sha256 /tmp/v11diag/store_after.sha256 && echo IDENTICAL
STORES BYTE-IDENTICAL (257 files)
```

Every mutation-capable probe (§7) ran against a `shutil.copytree` copy with `NEWSROOM_DIR`, `WB_EDITORIAL_WORKFLOW_DIR` and `WB_STORY_RESEARCH_PATH` redirected. No refresh was executed. The server was never started. The only product code executed was read-only (`read_today`, `read_article`, `list_stories`, `get_story_research`, `_draft_snapshot`, `evaluate`, `research_story` — the last two against copies, where they refuse before any network or model call).

## 18. Repository state

Only this file was created. No code modified. No commit made.

---

## Appendix — items explicitly marked UNVERIFIED

1. **Browser render cost** for the 251/253/258-row lists: row counts and payload bytes are measured, but wall-clock, DOM node count and scroll behaviour were not (would require running the server and a browser).
2. **Transfer size**: the 21 662 B figure is what `gzip -9` *would* yield; the server does not appear to set `Content-Encoding`, and this was not observed on the wire.
3. **Which entry point produced the 2026-09-26T04:32:51Z run.** The SPA's 60 s budget cannot cover the observed 3 m 45 s identity stage, so it was probably the CLI. The cost surface is identical either way.
4. **Whether `global.paid_enabled` has ever been true** in any environment. It is `false` here, and the only override (`var/model_policy.json`) does not touch `global`.
5. **Whether `_attempts` is semantically safe as an `EDIT` predicate** — it counts all attempts, not failed ones. Flagged, not resolved.
6. **Whether `needs_review` was intended to gate Today.** Written on all 253 stories, read by no projection. An observation, not a claim about intent.
7. **Growth curve** at 1 000 / 5 000 / 30 000 stories. Only the current 253-story snapshot exists; the 768 B/story constant is a measured average, not an extrapolation.
8. **Conflict-block duplication** was confirmed by source inspection rather than a live 409 render.











