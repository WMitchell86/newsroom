# V1.1-C — PREPARATION MANUAL CONTINUATION + SINGLE EDITOR CLEANUP

**Status:** implemented. **Baseline:** `8491d4a` (V1.1-B, pushed) ·
`m4/review/V1_1_EDITORIAL_USABILITY_DIAGNOSTIC.md` §13 (P1-6, P1-7), §14 P2

**Date:** 2026-09-26 · **Scope:** the two Preparation/Draft UX defects only. No
Today work, no quick Draft, no pagination, no Settings, no JEV, no readiness
change.

Stop condition met:

```text
fresh Preparation            -> NO Edit
real eligible gen failure    -> Edit becomes available
Edit -> exactly ONE body textarea -> non-empty autosave -> Draft
```

Repeatable proof: `PYTHONPATH=src python3 scripts/v11c_manual_continuation_proof.py`

## 1. The two defects

| # | Defect | Where | Cause |
| --- | --- | --- | --- |
| A | `EDIT` on every focus-confirmed Preparation Article | `editor_application._article_actions` | C3 shipped manual continuation as an always-on escape hatch; no durable state distinguished "generation failed" from "deliberately hand written" |
| B | Two body textareas bound to one state | `ArticleContentEditor.tsx` | A duplicated block since `b89e8ac`, same `id`, same autosave, and the duplicate `id` made every existing test drive the orphan |

## 2. The durable failure marker

One optional Article field, written by exactly one function
(`editor_article_store.record_draft_generation_failure`):

```json
"draft_generation_failure": {
  "content_version": 0,
  "basis_digest": "<sha256[:24]>",
  "failed_at": "2026-09-26T09:16:57Z",
  "reason_code": "PROVIDER_UNAVAILABLE"
}
```

The schema is **closed** (`DRAFT_FAILURE_FIELDS`), so a provider exception, a
prompt, a payload, a model name or a secret cannot be persisted here even by
accident — it is not one of the four fields. `reason_code` is validated against
`article_draft_failure.REASON_CODES`, so an internal exception name can never be
stored as if it were an editor-safe class.

**Invalidation.** The marker is bound to the *generation basis*, not merely
recorded:

| Part | Retires the marker when |
| --- | --- |
| `content_version` | the editor's own text or working title moves on |
| `basis_digest` | the Focus, the Story evidence status, its assessment time, or the fact/gap identities change |

`basis_digest` reuses the one snapshot `article_readiness.build_snapshot` already
assembles — no new versioning infrastructure, no second evidence read. The
invalidation is **lazy and self-healing**: the marker may still be on disk but is
inert against a new basis, so a stale failure can never keep authorizing the
editor forever. A new genuine failure on the new basis restores the path.



## 3. What counts as a generation failure

An **allow-list**, so a refusal code that nobody classified stays non-qualifying
by default and a readiness refusal can never leak open the editor:

| Qualifies (marker written) | Reason class |
| --- | --- |
| the unclassified transport failure (the `""` code the command path raises for an exception that is not a readiness decision) | `PROVIDER_UNAVAILABLE` |
| `DRAFT_UNAVAILABLE` — the pipeline ran and published no usable Draft | `GENERATION_FAILED` |

Never qualifies: `STORY_UNASSESSED`, `NO_CONFIRMED_FACTS`, `NO_OPEN_SOURCE`,
`BLOCKING_GAP`, `FOCUS_NOT_CONFIRMED`, `ARTICLE_HAS_TEXT`, `WORKING_TITLE_REQUIRED`,
`STORY_UNAVAILABLE`, `NOT_IN_PREPARATION`, `SAFETY_BLOCKED`, a stale
`ARTICLE_VERSION_CONFLICT` and the in-flight `INVALID_TRANSITION`. A test asserts
this against the live readiness taxonomy, not against a copy of it.

**The ordering contract** is the whole correctness argument, and it is enforced by
where `_record_draft_failure` is called — inside the worker, after
`article_generation.evaluate` has passed and `generate` has been entered, with no
Draft published:

```text
preflight refuses      -> raises before the call site -> NO marker
generation attempted   -> provider/pipeline fails     -> marker
success                -> publish_generated_draft      -> marker cleared
```

Two reason classes only, not three: `AUDIT_FAILED` was deliberately not created,
because nothing in the C2 pipeline reports an audit failure under its own code —
it surfaces as `DRAFT_UNAVAILABLE` — so a separate class would be a distinction
the editor cannot act on. A test asserts the two classes and the mapping are
exactly the stored set.

## 4. AvailableActions changes

`_article_actions` no longer appends `EDIT` unconditionally; it appends it only
when the marker is current for this basis.

| State | Before | After |
| --- | --- | --- |
| fresh, focus confirmed, eligible | `[CHANGE_FOCUS, EDIT, MAKE_DRAFT]` | `[CHANGE_FOCUS, MAKE_DRAFT]` |
| after a qualifying failure | `[CHANGE_FOCUS, EDIT, MAKE_DRAFT]` | `[CHANGE_FOCUS, MAKE_DRAFT, EDIT]` |
| ineligible (any readiness reason) | `[CHANGE_FOCUS, EDIT, …]` | `[CHANGE_FOCUS, …]` |
| draft / ready / finalized | unchanged | unchanged |

`nextAction` is unchanged: after a failure with readiness still valid it stays
`MAKE_DRAFT`, because a provider outage is worth a retry before the editor writes
the story by hand. Manual continuation is a recovery option, never a forced one.

The DTO gains one narrow field, `preparation.draftFailure`
(`{reasonCode, failedAt} | null`), and never carries a provider error. It is
`null` exactly when `EDIT` is absent, so React has one source of truth and
derives nothing locally.

## 5. Manual recovery behavior

Unchanged C3 semantics, reached only after a genuine failure: the same editor,
the same atomic content save, the same Article, Story lineage, Focus and internal
refs. The first non-empty save establishes Draft identity; an empty save never
does, so "typed then deleted" stays in Preparation. Nothing is fabricated: no
Case, no immutable generated Draft, no `generatedContent_version`, no provider
lineage. The marker is retired by the Draft it produced, in both the generated
and the manual path, so no Preparation recovery metadata leaks into Draft state.

## 6. Duplicate-editor fix

`ArticleContentEditor` rendered the body textarea twice — the same `id`, the same
state, the same autosave — with the label attached to the second copy. The
duplicate block and its duplicated retry button and navigation warning are gone:

```text
Заглавие
[title input]

Текст на статията
[ONE body textarea]
```

The remaining control keeps its unique `id` (`article-working-body`), its
associated label, and the accessible name `Текст на статията` that the tests and
the browser proof interact with. No orphan textarea, no duplicate ids.

## 7. Autosave preservation

Not redesigned and not weakened. Untouched: the 800 ms passive autosave, the
blur flush, the serialized save loop, the expected-version optimistic
concurrency, the local-conflict preservation (`Използвай моите промени` /
`Зареди запазената версия`), the unload and internal-link guards, and the
existing feedback. Deleting a duplicate control changed persistence semantics by
exactly zero: a test drives a non-empty save through the single field on the


## 9. Tests

`tests/test_manual_continuation.py` — 17 new tests. The only seam substituted is
the external model transport (and, for `NO_OPEN_SOURCE`, the evidence basis the
command reads — the same seam C2 uses, because the canonical store forbids
persisting a source without a URL):

| § | Test | Asserts |
| --- | --- | --- |
| 22 | fresh eligible Article | `MAKE_DRAFT` present, `EDIT` absent, no marker |
| 23 | five readiness refusals | command refuses, no marker, `EDIT` absent |
| 24 | real provider failure | provider really called, marker persisted, `EDIT` appears, retry stays |
| 24 | store reload | `EDIT` survives a full wipe of the registry, `_ACTIVE` and the attempt counter |
| 25 | success | real Draft, unchanged C2 lineage, no marker, no Preparation fallback |
| 7 | fail → retry → succeed | the marker is cleared by the successful attempt |
| 26 | focus / title / evidence change | marker retired, and a new failure re-enables the path |
| 27 | manual continuation | same Article, same Story, Draft, no Case, no generated Draft, no fake lineage |
| 17 | empty body | never establishes Draft identity |
| 3/19 | marker schema | a closed four-field schema; no exception, prompt, payload or model name |
| 5 | taxonomy | every readiness and transition code is non-qualifying |

Frontend: 6 new Vitest cases — no `Редактирай` on a clean Article; `Редактирай`
secondary to `Направи чернова`; exactly one `Текст на статията` control with a
document-wide duplicate-id guard; no contradictory notice while editing; the
800 ms autosave still firing on the single field; and a stale DTO not keeping the
editor open.

Two existing tests changed because they encoded the old defects rather than the
old contract: the C3 manual-continuation test now earns `EDIT` through a real
failure first, and the two V1.1-B action-list assertions in
`test_workbench_api.py` now assert the absence of `EDIT` on a clean Article.

## 10. Browser proof

`tests/browser/test_d2a_articles.py::test_manual_continuation_reaches_draft_in_the_browser`
drives the §30 sequence against a real production server, a real build and real
Chromium, on an isolated store: Preparation with no `Редактирай` → a real
`Направи чернова` whose provider really fails → canonical refetch →
`Редактирай` appears → exactly one `Текст на статията` control → autosave →
Draft → a real browser reload with the text still there and the Article a normal
Draft. `test_finalize_...` uses the same earned path.

**Browser suite: 48/48 passed**, including the permanent session-scoped
runtime-store integrity gate.

## 11. Runtime-store integrity

All mutating proofs use isolated copies. The normal `var/newsroom` (7 files) and
`var/editorial_workflow` (252 files) are **byte-identical** to the pre-slice
SHA-256 manifest, re-verified after the proof and after the browser suite.

## 12. Regression gate

| Gate | Result |
| --- | --- |
| Python (non-browser) | 1341 passed; 13 failures, byte-identical to the V1.1-A baseline (network/credential-dependent) |
| Browser | 48 passed |
| Isolated real-data proof | 31/31 |
| Vitest | 94 passed |
| typecheck / ESLint / production build | clean |
| Ruff check / format / compileall / `git diff --check` | clean |

## 13. Explicitly deferred

Untouched, as instructed: Today ordering, horizon/cap, quick Draft, Stories
pagination, last-refresh display, Settings, evidence-rail layout, Story
empty-section layout, Research polling, JEV, ranking/categories,
scheduler/catch-up. `article_readiness.py` is unchanged by this slice:
"can generation start?" and "did an eligible attempt fail?" remain two separate
questions, and nothing here was merged into one boolean.

The marker is persisted in application/domain state, not React state, so a
future quick-Draft orchestration that fails at the provider can offer the same
recovery without any further change here.

timer alone, with no blur and no navigation.

## 8. The no-Draft notice

`Текстът на статията още не е създаден.` was rendered unconditionally, including
while the body editor was open — a sentence contradicting the control directly
above it. It is now suppressed while editing. The editor *is* the current state
while it is open, so the notice is not merely hidden, it is untrue.
