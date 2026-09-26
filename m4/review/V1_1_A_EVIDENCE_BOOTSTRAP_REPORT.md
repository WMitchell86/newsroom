# V1.1-A — EVIDENCE BOOTSTRAP + FIRST RESEARCH ROUND

**Status:** implemented. **Baseline:** `a1404ff` + `m4/review/V1_1_EDITORIAL_USABILITY_DIAGNOSTIC.md`
**Date:** 2026-09-26 · **Scope:** the structural deadlock only (Story → Evidence). No eligibility fix, no Today redesign, no quick Draft.

Stop condition met:

```text
real Story (s16943311c9c782f) → UNASSESSED → Проучи още → first research round
→ canonical facts and/or explicit gaps → ASSESSED
```

Repeatable proof: `PYTHONPATH=src python3 scripts/v11a_evidence_bootstrap_proof.py`

## 1. Product decision — first research is on demand

No network/model research happens during grouping, during refresh, or merely
because the editor opens a Story. A new Story is simply `unassessed`; the editor
(or a later quick-Draft command) explicitly requests `Проучи още`, and that one
command is the single canonical evidence path. Spending cost on hundreds of
Stories the editor may never use is not acceptable, and this slice does not seed
facts at grouping time (V1.1-A §1, §17).

## 2. Unassessed vs assessed

`story_research_store` now carries an explicit evidence status — **not** a Story
workflow state:

| State | `evidence_status` | `assessed_at` | facts | gaps |
| --- | --- | --- | --- | --- |
| No canonical research row | `unassessed` | `null` | `[]` | `[]` |
| Completed round with evidence | `assessed` | real timestamp | `>= 1` + sources | any |
| Completed round without evidence | `assessed` | real timestamp | `0` | `>= 1` |

* The absent-row projection is a pure read: nothing is written for the 253 real
  Stories just to represent absence.
* The store **refuses** a persisted assessed row with `facts == 0` and
  `gaps == 0` — a false clean state is now unrepresentable.
* Legacy rows without the field resolve to `assessed` from a real `assessed_at`;
  the absent projection stays `unassessed`.
* Verified legacy Article lineage also lifts the status to `assessed`, so an
  unassessed projection can never be paired with a real timestamp.

## 3. First research questions without gaps

For an unassessed Story the executor builds a small bounded set of bootstrap
questions from canonical Story context only — title, representative/origin
publication, source identity, URL, timestamp, members — and never from archive
material or snippets:

1. which claim of the title is confirmed by an opened source;
2. which organisation or person is involved according to the source;
3. when/where it happened (if the source provides it);
4. which opened authoritative source supports the claim;
5. what important information is still unconfirmed;
6. whether a second independent opened source exists.

Assessed Stories keep the existing gap-driven `expansion_plan` path unchanged.

## 4. Evidence safety (B4A preserved)

Reused unchanged: search execution + `run_search_operation`, the `web_fetch`
safe opener, `blocked_domains`, `authority_by_domain`/`resolve_authority`,
`research.make_bundle`/`open_source`/`validate_provenance`/
`validate_council_claims`/`provenanced_packet`, `readiness.assess_sufficiency`,
the circular-corroboration rule and the two-round cap. Nothing was lowered.
The Google News RSS redirect is never promoted: the bootstrap opens the
representative publication through the existing safe fetch path and uses only
the **final canonical URL** of a resolved page; an unresolved `news.google.com`
final URL is rejected as evidence. The evidence bar is untouched.

## 5. Failure semantics

| Situation | Result |
| --- | --- |
| Provider/fetch exception before any assessment | Story stays `unassessed`, nothing persisted, calm retryable `SOURCE_UNAVAILABLE` |
| Round completed, no usable opened source | Story becomes `assessed` with an explicit blocking gap |
| Round completed with evidence | Story becomes `assessed` with facts + sources |

The two are never collapsed into empty arrays.

## 6. API/DTO changes

* `missingInformation.evidenceStatus: "unassessed" | "assessed"` on Story and
  Article DTOs; `assessedAt` is `null` when unassessed.
* `availableActions` exposes `RESEARCH_MORE` when the Story is `unassessed` **or**
  has a real researchable gap; an assessed clean basis no longer offers it and
  the command answers `409 INVALID_TRANSITION`.
* No new endpoint and no new operation registry: `POST /api/v1/stories/{id}/research`
  + `GET /api/v1/operations/{token}` are reused. Bootstrap rounds share one
  operation identity (`bootstrap:unassessed`), so a second click returns the
  in-flight operation instead of duplicating work.
* Frontend: truthful empty state (`Историята още не е проучена.`) with the real
  `Проучи още` action; `Оценено на …` is never rendered for an unassessed Story.

## 7. Tests

* `tests/test_story_research.py` — unassessed projection, bootstrap questions,
  first round without gaps, successful evidence, insufficient evidence,
  empty-basis refusal, failure integrity.
* `tests/test_workbench_api.py` — DTOs for unassessed / assessed-with-facts /
  assessed-with-gaps, `POST /research` for an unassessed Story with no prior gap,
  an insufficient-evidence round, a clean-basis refusal, and no internal
  research or provider vocabulary in the payload.
* `frontend/src/test/frontend.test.tsx` — unassessed UX: honest message, visible
  `Проучи още`, no `Оценено на …`, no clean "no missing information" claim.
* `tests/browser` — real Chromium research smoke through the production bundle.

## 8. Isolated real-Story proof

`scripts/v11a_evidence_bootstrap_proof.py` (exit 0) proved, on isolated copies of
the real stores and through the real HTTP API:

```text
before  s16943311c9c782f  evidenceStatus=unassessed  facts=0 gaps=0 assessedAt=null
        253/253 real Stories: unassessed, RESEARCH_MORE available
after   s16943311c9c782f  assessed  facts=2  opened sources  rounds=1  real assessedAt
after   (second Story)    assessed  facts=0  gaps=1  "Не е намерен отворен източник…"
never   assessed + facts=0 + gaps=0
```

Only the search provider and the page opener were substituted; the command, the
operation registry, the worker thread, the stores, the readiness assessment and
the projection are production code.

## 9. Runtime-store integrity

The proof re-verifies the real `var/newsroom` (7 files) and
`var/editorial_workflow` (251 files) SHA-256 manifests byte-for-byte before and
after. The browser suite's own session-scoped store-integrity gate also passed.

## 10. Explicitly deferred (not implemented here)

Draft eligibility fix · Today redesign · quick Draft on Today · pagination ·
JEV/TypeSafe integration · automatic research at grouping/refresh/open.

**Next slice (not started):** `V1.1-B — One shared Draft eligibility/preflight predicate`.

