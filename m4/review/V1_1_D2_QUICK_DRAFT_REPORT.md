# V1.1-D2 — TODAY FAST TRIAGE + QUICK DRAFT

**Status:** implemented. **Baseline:** `36b8a88` (V1.1-D1, pushed) ·
**Date:** 2026-09-26 · **Scope:** the Today triage row and the one Quick Draft
command. No JEV, no categories, no pagination, no Settings, no publishing.

Stop condition met:

```text
Днес → вижда Story → Чернова → готова Чернова        (one click, no intermediate screen)
Днес → Чернова → concise truthful blocker             (no bad evidence, no duplicate Article)
```

## 1. What the click means

`Чернова` says: *this Story is worth turning into a straightforward news Article —
do the necessary preparation and produce a Draft if the evidence supports it.*

It authorises the **default straight-news Focus** and nothing more. It never
authorises inventing a fact, ignoring a gap, bypassing a source requirement,
publishing or finalising. The command ends at `Чернова`; `Готова`, `Финализирай`,
CMS and social remain exactly where they were.

## 2. The canonical sequence

`editor_application._run_quick_draft` — one synchronous worker, every step
delegated to existing machinery:

| # | Step | Reuses |
| --- | --- | --- |
| 1 | reload the canonical Story | `story_store` |
| 2 | if the basis still warrants an **allowed** research round, run it | the **same** `research_story` |
| 3 | reload the canonical evidence and re-evaluate honestly | `article_readiness.evaluate_evidence` |
| 4 | resolve the Article; create one only now | `quick_draft.plan` |
| 5 | establish the quick Focus if none is confirmed | `editor_article_store.update_editor_focus` |
| 6 | ask the ONE readiness decision | `article_readiness.evaluate` |
| 7 | generate | the **same** `_run_draft_generation` worker as «Направи чернова» |
| 8 | return the narrow result | `quick_draft` |

**The only extraction (§7).** The C2 Draft worker's body moved out of the
`Направи чернова` closure into module-level `_run_draft_generation(article_id,
token)`, and the normal command now calls it. Quick Draft calls the *same*
function. There is no second generation path, no simplified prompt, and no
second failure mechanism.

**The only readiness change.** `article_readiness.evaluate_evidence` was extracted
from `evaluate` so the evidence question can be asked *before* an Article exists
(§10 requires evidence first, Article second). `evaluate` now delegates to it, so
there is still exactly one taxonomy, one message per code and one place a new
evidence reason is added. Nothing was restated.

## 3. Ordering: evidence before Article

An unassessed Story that cannot acquire enough evidence leaves **no** Preparation
Article behind. The evidence gate runs before `create_editor_article`, and the
gap-path test asserts `articles_for() == []` and no Case.

## 4. The default Focus

Deterministic, one sentence, Story-specific, **no model call** — the click is the
confirmation:

```text
Да се отрази потвърденото развитие „{clean Story title}“ като кратка информационна
новина, с акцент върху проверените факти, кога и къде се случва и значението му за
читателите в региона.
```

The old V1 placeholder (`Да разкажем какво се е променило…`) is **not** restored
here; it survives only in the manual «Направи статия» screen. A confirmed editor
Focus is never touched, and a test asserts it survives byte-for-byte.

## 5. Existing-Article handling

| Situation | Outcome |
| --- | --- |
| no active Article | create (only after evidence is sufficient) |
| one empty Preparation | reuse, preserve a confirmed Focus, generate |
| one Draft | `existing_article` — never regenerate, never reopen |
| one Ready | `existing_article` — never reopen |
| more than one active Article | `needs_attention` / `MULTIPLE_ACTIVE_ARTICLES` |

Multiple Articles per Story stays a supported canonical feature: the system asks
instead of guessing, and the row renders «Историята има повече от една активна
статия. Изберете коя да продължите.» with a link to the Story.

## 6. Research behaviour

* `unassessed` → the V1.1-A first round runs automatically;
* assessed with a research-remedy reason → one further round **only** while the
  existing cap allows;
* the cap (`MAX_RESEARCH_ROUNDS = 2`) still binds the automated path — a test
  asserts an exhausted basis is not researched again.

## 7. Failure and recovery

A generation that passes readiness and then genuinely fails reuses **V1.1-C's**
durable marker. The result is `needs_attention` carrying the Article id, and the
Preparation Article is where the editor finds the retry plus the earned
«Редактирай». No second failure mechanism was created.

## 8. API / operation contract

```text
POST /api/v1/stories/{storyId}/quick-draft
  Idempotency-Key: <required>
  → 202 { "operationToken": "op_..." }
GET  /api/v1/operations/{token}
  → { status, result: { status, articleId? | storyId, reasonCode?, message? } }
```

The existing bounded registry; no Celery, no queue, no second job system. A
repeated request with the same key returns the same operation, and a second click
while the work is in flight reattaches to it.

## 9. Cost behaviour

The click is the only spending decision. No background Quick Draft, no
pre-generation, nothing runs because a Story merely appears on Today. A click on
a fully assessed Story costs one model generation and no research; a click on an
unassessed Story costs one research round **and** one generation.

## 10. Frontend behaviour

* `Игнорирай` / `Прегледай` / `Чернова`, in that visual order, with `Чернова` the
  only filled control and `Игнорирай` deliberately quiet (not destructive-red);
* while running: exactly `Подготвя се чернова…` and a disabled control — no stage
  vocabulary, no modal, no wizard;
* success → `/articles/{id}`; existing Draft → the same, without regenerating;
* blocked → one sentence on the row, `Прегледай` still available, no navigation;
* poll budget `180 × 1000 ms`; an exhausted budget says the Draft is *still being
  prepared*, never that generation failed, and never cancels backend work.

`Прегледай` keeps its previous behaviour exactly: it is a link to the Story
workspace, as it was before this slice. It is not a review command and was not
redefined to suit the layout.

## 11. Browser proof

Real Chromium, real `npm run build`, real Python server, isolated stores. Only
the search provider, the page opener and the model transport are substituted.

The load-bearing assertion is an **absence**: after one click on an unassessed
Story the recorded route sequence contains neither `/stories/…` nor any
Preparation route — the editor lands on the Draft. `PageProbe` now records
`visited_routes` and `requests` so a proof can assert what did *not* happen, which
is stronger than a duration check.

The fast-path proof asserts the *absence of a research call* in the request
sequence rather than a wall-clock bound.

## 12. Real-data read-only analysis

30 of 165 qualifying rows are shown today. Read-only, nothing clicked:

| Measure | Value |
| --- | --- |
| unassessed | **30 of 30** |
| assessed | 0 |
| `QUICK_DRAFT` offered by the backend | 30 |
| rows with a unique active Article | 1 (already a Draft) |
| rows that would require a research round | 30 |
| rows that could take the assessed fast path | **0** |

**This is the finding that matters for cost planning.** Every Story on today's
first screen is unassessed, so every click costs a research round plus a
generation. The fast path is currently theoretical on this corpus — which is
exactly what the owner's instinct to rank first was pointing at. Nothing was
clicked and no real store was modified.

## 13. A pre-existing limitation this slice surfaced

The V1.1-A research executor takes **one claim per opened page** (the first
sentence answering a bootstrap question) and promotes it to a fact only when it
is PRIMARY or corroborated by two independent opened domains. In practice a
single research round frequently lands on a blocking gap rather than sufficient
evidence — and Quick Draft then correctly stops with that gap instead of
producing a low-quality Draft.

This is the safety design working, and it is **not** changed here: the scope of
this slice is the orchestration, not the research extractor. It is recorded
because it directly bounds how often the happy path can fire, and because the
real-data numbers above are consistent with it.

## 14. Explicitly deferred

JEV/ranking — not implemented. Categories — not implemented. Stories pagination —
not implemented. Settings — not implemented. Publishing — not implemented, and
Quick Draft cannot reach it.

## 15. Gate

| Gate | Result |
| --- | --- |
| Backend suite | 1362 passed (1 pre-existing, unrelated failure) |
| New backend tests | 29 passed |
| Browser suite | 58 passed |
| Vitest | 118 passed |
| typecheck / ESLint / production build | clean |
| Ruff check / format / compileall / `git diff --check` | clean |
| runtime-store integrity | byte-identical (259 files) |
