# V1.1-B — ONE SHARED DRAFT ELIGIBILITY / PREFLIGHT PREDICATE

**Status:** implemented. **Baseline:** `03609c6` (V1.1-A, pushed) ·
`m4/review/V1_1_EDITORIAL_USABILITY_DIAGNOSTIC.md`

**Date:** 2026-09-26 · **Scope:** the projection/command disagreement only. No
Preparation `EDIT` gating, no duplicate-editor cleanup, no Today redesign, no
quick Draft, no pagination, no JEV.

Stop condition met:

```text
for every tested canonical Article state:
    projection.preparation.draftEligible == true
    MUST imply  POST /api/v1/articles/{id}/draft passes every deterministic
                pre-provider preflight check — and refuse with the SAME reason
                when it is false.
```

Repeatable proof: `PYTHONPATH=src python3 scripts/v11b_shared_readiness_proof.py`

## 1. The defect, and the shape of the fix

The diagnostic's P0-3 was two independent predicates answering one question:

| Consumer | Old question | Old answer |
| --- | --- | --- |
| `editor_application._article_actions` | focus confirmed? any blocking gap? | `draftEligible = focus and not gaps` |
| `article_generation.evaluate` | the above **+** assessed evidence **+** ≥1 fact **+** an opened source URL **+** safety guards | refused |

The projection rose to the command's level, and the command was **not**
weakened. No C2 generation requirement was removed, relaxed or reordered against
the editor's benefit.

One new module, `src/editor_assistant/workflow/article_readiness.py`, now owns
the decision:

```text
build_snapshot(article, content, story, facts, missing) -> snapshot   # pure
evaluate(snapshot) -> DraftReadiness{eligible, reason_code, reason_message,
                                    blocking_gaps, evidence_status,
                                    fact_count, has_open_source, remedy}
```

Both consumers call `evaluate` on a snapshot built by the same
`build_snapshot`. `article_generation.evaluate` is now a four-line adapter that
converts the decision into the `DraftRefused` the command path already speaks —
it contains **no** precondition logic of its own. There is exactly one evidence
snapshot in the product: the existing C2 `_draft_snapshot` now delegates its
readiness-relevant part to the shared builder and adds only its own packet
metadata (headline, summary).

## 2. Canonical predicate — exact inputs, in evaluation order

| # | Input | Source |
| --- | --- | --- |
| 1 | Article is not finalized | `article.finalized_at` |
| 2 | Story lineage valid: the Story exists and is the Article's own | `story.story_id == article.story_id` |
| 3 | Story is not ignored | `story.status != "IGNORED"` |
| 4 | Current Article version valid (stale-command guard) | `content.content_version == snapshot.content_version` |
| 5 | Article has no text (a generation would overwrite it) | `content.body` |
| 6 | Working title is non-empty | `content.title` |

## 3. Reason taxonomy

Twelve codes, one message each, all distinct — the UI renders the backend string
verbatim, so two codes sharing wording would silently re-collapse the taxonomy.
There is a test asserting exactly that.

| Code | Editor message | Remedy |
| --- | --- | --- |
| `DRAFT_ELIGIBLE` | Има достатъчно потвърдена информация за чернова. | `Направи чернова` |
| `FOCUS_NOT_CONFIRMED` | Потвърдете фокуса, преди да правите чернова. | confirm Focus |
| `STORY_UNASSESSED` | Историята трябва първо да бъде проучена. | `Проучи още` |
| `NO_CONFIRMED_FACTS` | Няма потвърдени факти, върху които да се изгради черновата. | `Проучи още` |
| `NO_OPEN_SOURCE` | Няма отворен източник, върху който да се изгради черновата. | `Проучи още` |
| `BLOCKING_GAP` | Има непопълнена информация, която пречи да продължите. | `Проучи още` |
| `NOT_IN_PREPARATION` | Черновата не е налична в текущото състояние на статията. | — |
| `STORY_UNAVAILABLE` | Историята на статията вече не е достъпна. | — |
| `ARTICLE_HAS_TEXT` | Статията вече има текст. | — |
| `WORKING_TITLE_REQUIRED` | Работното заглавие не може да е празно. | — |
| `SAFETY_BLOCKED` | Проверката за безопасност спря операцията. | — |
| `ARTICLE_VERSION_CONFLICT` | Статията е променена, преди черновата да се създаде… | retry |

`RESEARCH_REMEDY_CODES` is the exact set whose remedy is research; it is what
decides whether `RESEARCH_MORE` is offered, so the page never suggests research
for a condition research cannot fix. `LIFECYCLE_CODES` is the set that keeps the
historical `INVALID_TRANSITION` HTTP contract, because those are transition
problems rather than evidence-readiness problems.

The four previously-collapsed conditions (`no facts`, `no open source`,
`blocking gap`, and the never-distinguished unassessed case) are now four
distinct, editor-actionable reasons. The generic `Има непопълнена информация…`
string is used **only** for a real blocking gap.

## 4. How disagreement became impossible

Three independent mechanisms, in increasing strength:

1. **One predicate.** `MAKE_DRAFT` is no longer decided in `_article_actions`;
   it is read off the same `DraftReadiness` object the command enforces. There is
   no second action predicate left to drift.
2. **One message table.** `REASON_MESSAGES` is the only source of editor
   wording. The projection, the `nextAction.reasonCode`, the HTTP error envelope
   and the operation-error envelope all reference these same strings, so the UI
   and the command cannot describe one state with two sentences.
3. **An assertion in the command.** `start_article_draft` re-evaluates the
   decision, refuses on it, and then independently asserts that
   `"MAKE_DRAFT" in dto["availableActions"]`. If `MAKE_DRAFT` were ever derived
   from anything other than this decision, the command fails loudly rather than
   the UI quietly diverging.

`start_article_draft` never trusts client eligibility: it re-reads canonical
state through `_draft_snapshot` immediately before generation, and the worker
re-reads again.

## 5. API / DTO changes

* `preparation.draftReadiness: { code, message }` — new, on every preparation
  Article. React does not derive the reason and does not render a second one.
* `preparation.draftEligible` now equals the command's preflight verdict.
* `nextAction.reasonCode` carries the readiness code (`STORY_UNASSESSED`,
  `BLOCKING_GAP`, `FOCUS_NOT_CONFIRMED`, `DRAFT_ELIGIBLE`, …) instead of only
  `DRAFT_ELIGIBLE`/`BLOCKING_GAP`.
* `availableActions` offers `RESEARCH_MORE` for every research-remedy reason,
  not only for a real blocking gap.
* HTTP error envelope: the four evidence-remedy codes are distinct `409`s. The
  lifecycle codes keep `INVALID_TRANSITION`; `SAFETY_BLOCKED` and
  `ARTICLE_VERSION_CONFLICT` keep their classes.
* No new endpoint, no new operation registry.

The `PreparationProjection` and `ApiErrorCode` TypeScript types were extended in
lockstep; `npm run typecheck` fails if the backend adds a field React does not
know about.

## 6. Frontend behavior

`PreparationWorkspace` renders **exactly one** readiness sentence, taken
verbatim from `preparation.draftReadiness.message`, and marks it
`data-readiness-code` so the class and the reason cannot drift apart. The Draft
button is rendered from `availableActions.includes("MAKE_DRAFT")` alone — the
local `&& preparation.draftEligible` guard is gone, because the backend already
guarantees the two agree. A blocking message and an enabled Draft button are now
structurally impossible on the same page.

Research navigation is rendered whenever the backend offers `RESEARCH_MORE`, so
an unassessed Story (no gaps to show) still gets a direct `Проучи още` link to its
owning Story. No Article-level research orchestration was added.

## 7. Tests

`tests/test_draft_readiness_parity.py` (new, 18 tests) is the permanent
regression gate:

* **The readiness matrix** — the §22 table, as data, driving every assertion.
  For each canonical state it asserts `draftEligible`, the presence/absence of
  `MAKE_DRAFT`, the reason code, the real blocking gaps, the command's
  deterministic preflight, and that the provider boundary was never reached.
* **Command/preview parity** — the same fixtures through the real command: an
  eligible projection must pass preflight; an ineligible one must refuse with the
  identical reason string. The model transport is substituted **only** to detect
  whether the boundary was reached.
* **Stale state, both directions** — an eligible page that goes stale refuses; an
  ineligible page that becomes eligible after research turns eligible on refetch.
* **The taxonomy itself** — every required code exists, all messages are
  distinct, and only the four research-remedy codes route to `Проучи още`.

Matrix (as implemented; the two rows the canonical stores make unrepresentable
are documented in the test file and covered elsewhere):

| Focus | Evidence | Facts | Open source | Blocking gap | Expected |
| --- | --- | ---: | ---: | ---: | --- |
| no | assessed | 1 | yes | 0 | `FOCUS_NOT_CONFIRMED` |
| no | unassessed | 0 | no | 0 | `FOCUS_NOT_CONFIRMED` |
| yes | unassessed | 0 | no | 0 | `STORY_UNASSESSED` |
| yes | assessed | 0 | no | 1 | `BLOCKING_GAP` |
| yes | assessed | 0 | no | 0 | `NO_CONFIRMED_FACTS` |
| yes | assessed | 1 | yes | 1 | `BLOCKING_GAP` |
| yes | assessed | 1 | yes | 0 | **`DRAFT_ELIGIBLE`** |

* `assessed + 0 facts + 0 gaps` is absent: V1.1-A made it the forbidden false
  clean state and `story_research_store` refuses to persist it.
* `assessed + 1 fact + no open source` is absent: a fact must reference a
  persisted source with a non-empty URL. The `NO_OPEN_SOURCE` branch is reached
  through verified legacy Article lineage and is covered in
  `tests/test_article_draft_command.py`.

Updated, not weakened: `tests/test_article_draft_command.py` (four refusal tests
now assert the exact semantic code; two new tests cover `STORY_UNASSESSED` and
`NO_OPEN_SOURCE`) and `tests/test_workbench_api.py` (the preparation test now
asserts the honest `STORY_UNASSESSED` refusal that V1.1-B is about, then proves
the same Article becomes eligible once the Story carries evidence — the exact
transition that used to be a contradiction).

Frontend: 6 new Vitest cases covering the unassessed message, a blocking gap, a
missing opened source, "exactly one readiness line", the eligible case, and
research navigation to the owning Story.

## 8. Isolated real-data proof

`scripts/v11b_shared_readiness_proof.py` — **30/30 checks, exit 0**, on isolated
copies of the real stores through production code.

```text
A  6 of 7 real preparation Articles: STORY_UNASSESSED, draftEligible=false,
   no MAKE_DRAFT, blockingGaps=[], and the command refuses with the identical
   string. No contradictory green text anywhere.
B  the same real Article (art_dbe04fea341a427 / sfd1e799db46d0d1) after a real
   research round written through the store's production path:
   facts=1, opened source, no gap, focus confirmed
   -> DRAFT_ELIGIBLE, MAKE_DRAFT present, preflight passes
C  a real Story researched to a gap only: stays ineligible, reason BLOCKING_GAP
   with the real question, remedy RESEARCH_MORE.
   0 provider calls throughout — no paid quota.
```

The diagnostic's own Царево Story (`s16943311c9c782f`) was **not** used for the
eligibility case: it owns only the `draft` Article the diagnostic itself flagged
as a false positive, not a preparation Article.

## 9. Runtime-store integrity

The proof re-verifies the real `var/newsroom` (7 files) and
`var/editorial_workflow` (252 files) SHA-256 manifests byte-for-byte before and
after: **identical**. The browser suite's own session-scoped store-integrity gate
also passed. No test wrote to a normal runtime store.

## 10. Regression gate

| Gate | Result |
| --- | --- |
| Backend full non-browser suite | **1289 passed, 1 failed** |
| Readiness matrix + parity | 18 passed |
| Draft command | 20 passed |
| API / projection | passed |
| V1.1-A research | passed |
| Browser (separate process) | **48 passed** |
| Vitest | **89 passed** (was 83) |
| Typecheck | passed |
| ESLint | passed |
| Production build | passed |
| Ruff check | passed |
| Ruff format | 188 files already formatted |
| compileall | passed |
| `git diff --check` | clean |

The single backend failure is
`tests/test_sources_registry.py::test_cli_registers_and_manages_the_registry` —
the **known date-dependent baseline failure**, present identically before any
V1.1-B change (confirmed by re-running the suite on the stashed baseline). Its
behavior is unchanged and it is not newly introduced.

## 11. Explicitly deferred

* Preparation `EDIT` gating — **not fixed** (separate P1 predicate gap, V1.1-C).
* Duplicate body editor — **not fixed** (V1.1-C).
* Today redesign — **not implemented**.
* Quick Draft on Today — **not implemented**, but §20 is now unblocked: a future
  orchestration can ask `readiness` and branch on `unassessed` / researchable /
  blocked, because the function lives in the application layer, not in HTTP or UI
  code.
* Pagination — **not implemented**.
* JEV — **not integrated**; it has no role in Draft readiness.
* Evidence column layout (P1-8), `read_today` N+1 (P1-9), Today sorting, search
  ranking — all untouched.

## 12. Recommended next slice

`V1.1-C — Preparation EDIT gating + duplicate editor cleanup.` Not started.


