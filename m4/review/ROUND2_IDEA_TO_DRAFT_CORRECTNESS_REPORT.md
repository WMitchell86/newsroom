# ROUND 2 — Idea → Draft Correctness (REVIEW → FIX → VERIFY)

- Date: 2026-09-24
- Baseline: `0642058` (main, clean tree at start; ROUND 1 accepted, not reopened)
- Scope: G1 lineage model provenance, G2 idea-status parity, G3 style retrieval
  preflight, G4/style body — plus the no-regression boundaries needed to trust
  them. Out of scope (untouched): role qualification, routing redesign,
  React/Vite, Telegram, locking redesign, angles UI, story/source, research wiring.

**Verdict: no production defect found in G1–G4. The fixes already applied in
`0642058` are confirmed correct by code trace + reproduction. No production
code changed this round.** The gaps found were in *proof tests* that PART G
explicitly requires: 7 tests added, 1 existing test strengthened (see PART G).
One P3 (G8 dead sort) re-confirmed as harmless; P3 classifications in PART F.

## Summary table

| Finding | Already fixed? | Review result | Extra fix needed? |
|---|---|---|---|
| G1 — actual generation model in lineage | Yes (in `0642058`) | CONFIRMED CORRECT — router metadata reaches `lineage.model` in live_draft, case and Workbench view; ledger agrees | No code fix. 1 test added (A3 legacy no-metadata shape); A2 UI-visibility test added |
| G2 — editor-rejected idea cannot be revived | Yes (in `0642058`) | CONFIRMED CORRECT — one canonical guard at all entry points; refusals leave stores byte-identical | No code fix. 1 CLI `NO_PUBLISHABLE_ANGLE` test added; 1 test strengthened |
| G3 — style retrieval preflight before model spend | Yes (in `0642058`) | CONFIRMED CORRECT — retrieval (→ fallback → dedupe → exactly-3 validation) completes BEFORE any model/judge call | No code fix. 2 tests added (real 2-example corpus; cross-step dedupe) |
| G4 — real style prose reaches the prompt | Yes (in `0642058`) | CONFIRMED CORRECT — P1/MID/LAST hydrated from archive bodies; STYLE-ONLY boundary intact; bodies never persisted | No code fix. 1 MID-prose test + 1 hermetic happy-path test added |

Everything below shows the code path reviewed, the reproduction/proof, the
tests, and the change made this round. Where no code change was needed the
item is marked **VERIFIED AS-IS** (production code unchanged; test-only
additions are listed explicitly).

---

## G1 — Actual model provenance (PART A)

### Code path reviewed (A1 trace)

```text
ideas/assert_draftable_status (G2 guard)
→ live.live_generate_draft            workflow/live.py:214
→ gen.call_model(role="draft", payload_class="private")   drafting/generate.py:348
→ model_router.call_role              drafting/model_router.py:389  (request_id per call, B1)
→ _try_route                           drafting/model_router.py:589
    meta["model"] = route.get("model")   ← ALWAYS set from the winning route
→ back in live_generate_draft:
    lineage = gen.make_lineage(..., model=(generation_meta or {}).get("model") or gen.MODEL_ID)
→ CLI cmd_live_generate: LIVE_DRAFTS_PATH append (store["lineage"]) + cases_mod.open_case(draft=store)
→ Workbench state.articles_view(): drafts[].model = (d.get("lineage") or {}).get("model", "")
```

The router's `_try_route` stamps `meta["model"]` (and `provider`,
`route_index`, token counts, latency) from the route that actually answered
before returning, and `call_role` re-stamps it with role/route metadata. The
`or gen.MODEL_ID` term in `live_generate_draft` is therefore reachable only
when metadata is absent — a legacy/mock shape the production router never
produces.

### A2 fallback reproduction (hermetic)

Existing test `test_lineage_reports_the_route_that_actually_drafted`
(`tests/test_live_generate_offline.py`): route 0 of the real draft policy
raises a daily-quota 429, route 1 returns the draft as its own model id.
Asserts:

- usage ledger: the only `OK` draft row is route 1's model; route 0's row is
  `QUOTA_EXHAUSTED`; `model_calls_today` = 1 + 1; `role_calls_today("draft")` = 1
- `live_drafts.jsonl` → `lineage.model == second_model`
- opened case → `lineage.model == second_model`
- no provider call (transport is a stub)

New test `test_articles_page_shows_the_lineage_model_of_the_actual_drafter`
(`tests/test_workbench_articles.py`): a persisted lineage with
`model="mock/second"` surfaces verbatim in `state.articles_view()` drafts AND
in the rendered `/articles` HTML — the editor sees the actual drafter, not a
static default.

### A3 missing metadata behavior

- Production router path always supplies `model` (`_try_route`), so the
  lineage can never silently claim a model that did not run.
- Legacy/mock callers that return no metadata fall back to `gen.MODEL_ID` —
  documented behavior, now pinned by the new test
  `test_legacy_caller_without_model_metadata_gets_the_documented_static_model`.
- VERIFIED AS-IS (no code change; the existing `or gen.MODEL_ID` contract is
  the minimal correct one and matches the harness comment in `live.py`).

### Tests

- `tests/test_live_generate_offline.py::test_lineage_reports_the_route_that_actually_drafted` (existing)
- `tests/test_live_generate_offline.py::test_legacy_caller_without_model_metadata_gets_the_documented_static_model` (**new**)
- `tests/test_workbench_articles.py::test_articles_page_shows_the_lineage_model_of_the_actual_drafter` (**new**)

### Change made this round

Tests only. G1 production code **VERIFIED AS-IS**.

---

## G2 — Idea status parity (PART B)

### B1 canonical contract

`workflow/ideas.py` is the single source:

```python
DRAFTABLE_STATUSES = ("NEW", "FOLLOW_UP", "DRAFT_REQUESTED")
def assert_draftable_status(idea): ...   # Bulgarian refusal, never mutates
```

Repo-wide search confirms no other hard-coded status tuple exists in CLI or
Workbench; both surfaces import the canonical helper.

### B2 entry points traced

1. **CLI `cmd_live_case`** (`cli.py:238`): `assert_draftable_status` runs
   BEFORE `live_case_request`, before `save_ideas`, before `_save_live_row`.
   A closed `NO_ANGLE` idea gets the friendly print + zero mutation; any other
   refusal is `sys.exit` with the Bulgarian message. **VERIFIED AS-IS**
2. **Workbench `prepare_case`** (`workbench/state.py:1061`): the guard runs
   before anything else; `IdeaError` → `WorkbenchError` → HTTP 400/redirect
   error params; no audit action recorded on refusal. **VERIFIED AS-IS**
3. **Workbench `generate_draft`** (`workbench/state.py:1119`): requires an
   existing `prepared` row — and a prepared row can only exist if the guard
   passed at prepare time (closed ideas can never produce one). Generation
   itself re-runs the angle/readiness gates inside `live_generate_draft`.
   **VERIFIED AS-IS**
4. **`live_case_request`** (`live.py:133`): the single service boundary runs
   `assert_draftable_status` again before mutating the idea to
   `DRAFT_REQUESTED`. **VERIFIED AS-IS**

No path can mutate a closed idea to `DRAFT_REQUESTED` before the canonical
guard passes: the only writers of that status are `live_case_request` (behind
its own guard) and `ideas.request_draft` (explicit NEW/FOLLOW_UP action that
raises `IdeaError` otherwise).

### B3 store immutability on refusal

Proof by byte comparison (existing + strengthened tests):

- IGNORED via CLI: `test_live_case_cli_refuses_a_closed_idea_and_changes_nothing`
  — ideas store byte-identical, **evidence store byte-identical (assertion
  strengthened this round)**, no draft, no case.
- IGNORED / NO_PUBLISHABLE_ANGLE via Workbench POST:
  `test_post_prepare_refuses_a_closed_idea_without_touching_any_store`
  (parametrized) — ideas bytes identical, no `prepared` row, no
  `case_prepared`/`prepare_refused_no_angle` audit success, no cases.
- The refusal itself writes nothing (the Workbench only records
  `prepare_refused_no_angle` when the angle gate legitimately closes an
  OPEN idea — that is the documented, non-success-shaped path).

### B4 UI behavior

- Workbench: refusal lands as `?error=<български текст>` on the redirect; the
  articles page renders it. No raw traceback, no success-looking redirect.
- CLI: new test
  `test_live_case_cli_refuses_no_publishable_angle_with_readable_print` pins
  the `NO_PUBLISHABLE_ANGLE` outcome as one friendly line
  (`EV-T: NO_PUBLISHABLE_ANGLE; no article`) — no traceback, no stores touched.

### Tests

- `tests/test_workflow_live_cli.py::test_live_case_cli_refuses_a_closed_idea_and_changes_nothing` (existing, **strengthened**)
- `tests/test_workflow_live_cli.py::test_live_case_cli_refuses_no_publishable_angle_with_readable_print` (**new**)
- `tests/test_workbench_articles.py::test_post_prepare_refuses_a_closed_idea_without_touching_any_store` (existing, parametrized)
- `tests/test_workbench_articles.py::test_post_prepare_still_works_for_draftable_statuses` (existing, parity both ways)
- `tests/test_workflow_cases.py::test_assert_draftable_status_allows_only_new_follow_up_and_draft_requested` / `..._refuses_closed_and_unknown_states_without_mutation` (existing)

### Change made this round

Tests only. G2 production code **VERIFIED AS-IS**.

---

## G3 — Style retrieval preflight (PART C)

### C1 ordering proof

`live_generate_draft` calls `retrieve_examples_for_generation` BEFORE
`gen.call_model`; a `StyleRetrievalError` is converted to `LiveError` before
any model call. Proofs:

- Existing `test_style_preflight_failure_refuses_before_any_model_call`: a
  retrieval refusal leaves the stub transport with **zero** calls (no draft
  request, no judge request) and no store writes.
- **New** `test_thin_corpus_with_only_two_usable_examples_refuses`
  (`tests/test_drafting_m23.py`): a REAL hermetic corpus that yields only two
  usable house/news rows raises `StyleRetrievalError` with the truthful
  `2/3` count — the exactly-3 precondition fails at the corpus level, not
  only at the monkeypatch level.
- Existing `test_generation_preflight_refuses_when_three_unique_examples_are_impossible`.

Model calls on the refusal path = 0, judge calls = 0 (asserted).

### C2 fallback chain semantics

`retrieve_examples_for_generation` (`drafting/retrieval.py:260`):

```text
steps = [(voice, mode)]
      + [("VOICE_HOUSE", mode)]        if voice != VOICE_HOUSE
      + [("VOICE_HOUSE", "MODE_STANDARD_NEWS")]  if mode != MODE_STANDARD_NEWS
dedupe via picked dict (first step wins) → raise if < top_n
```

This matches the documented M2.3 chain (`style.profiles.composition_fallback`)
— no new taxonomy, no new style profile invented. Proofs:

- `test_generation_preflight_walks_only_the_documented_fallback_chain`
  (existing): step order, stop-as-soon-as-3, `fallback_used=True`, reason text.
- **New** `test_generation_preflight_dedupes_overlapping_fallback_steps`: an
  article returned by two chain steps counts ONCE, the requested-composition
  pick keeps its preferred first position, and the exclusion list really
  travels to the next step (`(VOICE_HOUSE, MODE_BRIEF, ("d1",))` observed).
- Determinism: lexical scoring + stable sorts, no randomness, no clock in the
  ranking path.
- Exactly 3 unique on success is enforced twice: by the precondition raise AND
  by `make_lineage` (`lineage needs exactly 3 style_example_ids`).

### C3 truthful retrieval metadata

The returned dict carries `fallback_used` / `fallback_trail` /
`retrieval_reason` computed from the actual chain walk (never hard-coded):
`fallback_used = len(trail) > 1`, the reason names the exact composition used.
The CLI (`cmd_live_generate`) and the Workbench (`generate_draft`) persist
`{"retrieval": {…without examples…}, "retrieval_example_ids": [...]}`.
Asserted by `test_live_prompt_carries_real_style_prose_from_all_three_examples`
(bool trail list, non-empty reason) and the new happy-path test (truthful
`fallback_used=True`, trail `found` counts, reason starting with `fallback:`).

### Tests

- `tests/test_drafting_m23.py::test_thin_corpus_with_only_two_usable_examples_refuses` (**new**)
- `tests/test_drafting_m23.py::test_generation_preflight_dedupes_overlapping_fallback_steps` (**new**)
- `tests/test_drafting_m23.py::test_generation_preflight_returns_three_unique_bodies_without_fallback` (existing)
- `tests/test_drafting_m23.py::test_generation_preflight_walks_only_the_documented_fallback_chain` (existing)
- `tests/test_live_generate_offline.py::test_style_preflight_failure_refuses_before_any_model_call` (existing)

### Change made this round

Tests only. G3 production code **VERIFIED AS-IS**.

---

## G4 — Style body (PART D)

### D1 body hydration

`retrieve_examples_for_generation` always retrieves with `include_body=True`,
so the TRANSIENT example records passed to `drafting.prompt.build_prompt`
carry the archive prose. `prompt._example_text` renders, per example:
`P1` (first paragraph, 700 chars), `MID` (middle paragraph, 600 chars, when
the article has >3 paragraphs), `LAST` (last paragraph, 400 chars).
The legacy `retrieve_examples(..., include_body=False)` body-less shape is
kept for old callers (pinned by `test_legacy_retrieve_examples_keeps_the_bodyless_shape_by_default`).

### D2 prompt proof

- Existing `test_live_prompt_carries_real_style_prose_from_all_three_examples`:
  a real CLI run's draft prompt has 3 non-empty `P1:` and 3 non-empty `LAST:`
  blocks. Not just a `STYLE_EXAMPLES` marker check.
- **New** `test_prompt_mid_paragraphs_carry_real_prose_for_all_three_examples`
  (`tests/test_drafting_m23.py`): with a 5-paragraph archive shape, all three
  examples contribute a `MID` block and the GENUINE middle archive paragraph
  (`Абзац 3 на mid-N.`) appears in the prompt, alongside the real first and
  last paragraphs.

### D3 factual boundary

The prompt states the boundary in three places, verified in code and tests:

- `STYLE_EXAMPLES` section ends with: "Style examples above are STYLE ONLY.
  Their people/numbers/dates/quotes/places/institutions must not enter the
  draft."
- `FORBIDDEN` lists style-derived facts and evidence-unsupported attributions.
- `SYSTEM`: "Write a Bulgarian news draft grounded ONLY in CURRENT EVIDENCE."
- Belt-and-braces at runtime: `gen.audit_claims(..., style_texts=[headlines])`
  flags style leaks (`leak_hits`), and style-example facts are not in
  `allowed`. Tests: `test_style_examples_marked_style_only`,
  `test_prompt_keeps_evidence_and_style_sections_separate`, prompt
  ordering assertion (`STYLE EXAMPLE` before `TASK`). No wording was found
  that permits archive facts to leak. **VERIFIED AS-IS**

### D4 persistence boundary

The live/case stores never receive archive bodies:

- `live_generate_draft` strips bodies from the persisted view:
  `{"examples": [{k: v for k, v in example.items() if k != "body"} ...]}`
  (`workflow/live.py`, G4 comment), and the CLI/Workbench persist even less —
  `{"retrieval": {k: v for k, v in result["retrieval"].items() if k != "examples"},
  "retrieval_example_ids": [...]}` — IDs/URLs/reasons/metadata only.
- Existing test asserts `"body" not in json.dumps(stored["retrieval"])` and
  `"examples" not in retrieval_meta`; the new happy-path test re-proves it
  end-to-end with hydrated bodies (prompt saw `Архивно тяло N.`, persisted
  JSON did not).

### Tests

- `tests/test_drafting_m23.py::test_prompt_mid_paragraphs_carry_real_prose_for_all_three_examples` (**new**)
- `tests/test_live_generate_offline.py::test_live_prompt_carries_real_style_prose_from_all_three_examples` (existing)
- `tests/test_live_generate_offline.py::test_hermetic_idea_to_draft_happy_path_with_stubbed_retrieval` (**new**)
- `tests/test_drafting_m23.py::test_style_examples_marked_style_only` (existing)
- `tests/test_drafting_m23b.py` STYLE-ONLY/trimming boundary tests (existing)

### Change made this round

Tests only. G4 production code **VERIFIED AS-IS**.

---

## PART E — hermetic idea→draft happy path

**New** `test_hermetic_idea_to_draft_happy_path_with_stubbed_retrieval`
(`tests/test_live_generate_offline.py`) walks the full path with a stubbed
retrieval seam and the stubbed transport (frozen-packet route uses the real
corpus in the pre-existing `test_offline_end_to_end_generation_path`):

- draftable idea → `live-case` preparation (`NEW` → `DRAFT_REQUESTED`) →
  3 hydrated style examples reach the prompt → generation via mocked
  successful route → semantic/deterministic gates → stored live draft →
  case opens (`LIV-01`, `TRACK_LIVE`).
- Assertions: exactly 3 style example IDs (`m1..m3`); the prompt contained the
  archive bodies; persisted `retrieval` metadata is truthful
  (`fallback_used=True`, trail, reason) AND body-free; lineage is 1:1 between
  live draft and case; the actual successful model appears in lineage (G1
  tests); working-copy/finalization behavior untouched (`final_text == ""`
  contract test exists and was not modified).

---

## PART F — Review #3 P3 observations (REPORT ONLY — no code changes)

> NB: the P3 numbering below follows Review #3 (G4–G9) and intentionally
> collides with the ROUND 2 finding numbers G1–G4 used above.

| P3 | Observation | Classification | Evidence checked 2026-09-24 |
|---|---|---|---|
| G4 | `lineage_problems` normal-state alarm noise | **ALREADY_RESOLVED** | Current `cases.lineage_problems` checks only real invariants (duplicate idea/evidence ids, missing idea card / evidence row, source_url mismatch, idea-status drift). Proved on clean state: empty stores → `[]`; a non-LIVE case → `[]`. The alarm behavior belonged to an earlier implementation; nothing fires in the normal state today. |
| G5 | transcript/council angle-review heuristic | **STILL_BACKLOG** | `angles.needs_angle_review` is still the substring-cue heuristic (`transcript`, `council`, `транскрипт`, `съвет`). Deliberate, documented M2S heuristic; does not block G1–G4. |
| G6 | CLI NO_ANGLE prepared-shape difference | **NO_LONGER_APPLIES** (as a correctness risk; cosmetic divergence remains) | `cli.cmd_live_case` stores the NO_ANGLE-shaped `row["prepared"]` and prints; the Workbench persists idea status + audit action and does not set `prepared`. `cmd_live_generate` re-runs `check_angle_gate` and refuses BEFORE reading `prepared`, so the difference cannot produce a wrong draft; the CLI row is consumed by nothing else. Report-only per scope. |
| G7 | raw CLI traceback for parse/lineage failures | **STILL_BACKLOG** | `cmd_live_generate` has no try/except around `live_generate_draft`: malformed model JSON (`ValueError` from `parse_draft_json`) or a lineage validation error still surfaces as a Python traceback. Fail-visible and fail-closed (no partial writes — the store append happens only after lineage), degraded UX only. Not blocking G1–G4. |
| G8 | dead `retrieve_examples` sort | **STILL_BACKLOG** | Confirmed at `drafting/retrieval.py` (~line 218): the first `scored.sort` key contains `-ord((t[1] or " ")[0]) if False else t[1]` — a dead conditional; the correct second sort (`(-score, article_id)`) fully determines order. Zero behavioral impact; cleanup candidate for a future chore commit. |
| G9 | two-store transaction / locking | **STILL_BACKLOG** (owner-approved BACKLOG M4F) | Ideas and evidence/cases remain separate atomic writes; the Workbench mutation paths share `_MUTATION_LOCK`, CLI paths do not. Deferred by explicit scope decision (BACKLOG M4F); out of ROUND 2 scope. |

---

## PART G — required-tests map (nothing weakened)

| Required test | Covered by | Status |
|---|---|---|
| fallback generation persists actual model in lineage | `test_lineage_reports_the_route_that_actually_drafted` | existing |
| usage ledger model and lineage model agree | same test (OK rows == [route-1 model]; counters) | existing |
| IGNORED cannot prepare via CLI | `test_live_case_cli_refuses_a_closed_idea_and_changes_nothing` | existing, **strengthened** (evidence-store bytes) |
| IGNORED cannot prepare via Workbench | `test_post_prepare_refuses_a_closed_idea_without_touching_any_store[IGNORED]` | existing |
| NO_PUBLISHABLE_ANGLE cannot prepare | same parametrized test + `test_post_prepare_no_angle_refusal_persists_status` + **new** CLI print test | existing + 1 **new** |
| allowed statuses have CLI/UI parity | `test_post_prepare_still_works_for_draftable_statuses` + `test_assert_draftable_status_allows_only_...` | existing |
| refusal leaves semantic stores unchanged | byte-identity assertions in the refusal tests above | existing + 1 strengthened |
| 2-style-example corpus fails before any model call | **new** `test_thin_corpus_with_only_two_usable_examples_refuses` + existing zero-call preflight test | existing + 1 **new** |
| fallback retrieval yields exactly 3 unique examples | `test_generation_preflight_returns_three_unique_bodies_without_fallback` + chain test + **new** dedupe test | existing + 1 **new** |
| fallback metadata is truthful | prompt-prose test (bool/list/reason) + **new** happy-path (`fallback_used=True` + trail + reason) | existing + 1 **new** |
| live prompt contains real prose for all 3 style examples | `test_live_prompt_carries_real_style_prose_...` (P1/LAST) + **new** MID test | existing + 1 **new** |
| persisted retrieval metadata does not contain full bodies | prompt-prose test (`"body" not in ...`) + **new** happy path | existing + 1 **new** |
| factual prompt boundary still says style-only | `test_style_examples_marked_style_only` + prompt-section tests | existing |
| one hermetic idea→draft happy path | **new** `test_hermetic_idea_to_draft_happy_path_with_stubbed_retrieval` (+ existing offline end-to-end on the real corpus) | existing + 1 **new** |

No existing assertion was weakened; the only modification to an existing test
added a stronger byte-identity assertion.

## PART H — gate results

| Gate | Result |
|---|---|
| `PYTHONPATH=src python3 -m pytest -q` | **985 passed** (baseline 978 + 7 new), ~36 s, offline |
| `ruff check src tests scripts` | All checks passed |
| `ruff format --check src tests scripts` | 145 files already formatted |
| `PYTHONPATH=src python3 scripts/m3a_smoke.py` | 25/25 checks passed |
| `PYTHONPATH=src python3 scripts/ui_proof.py` | 56/56 checks passed |

No live provider calls were made; live model qualification was NOT run
(out of scope per ROUND 1 acceptance).

## PART J — commit

The review found **no additional production bug**; per the ROUND 2 contract a
report/docs-only commit is acceptable, and the proof tests required by PART G
ride along with it (test-only diff, no production code changed):

- `tests/test_workbench_articles.py` — A2 Workbench-visible-model test (+`json` import)
- `tests/test_workflow_live_cli.py` — CLI `NO_PUBLISHABLE_ANGLE` friendly-refusal test; strengthened IGNORED refusal test
- `tests/test_drafting_m23.py` — thin-corpus preflight, cross-step dedupe, MID-prose tests
- `tests/test_live_generate_offline.py` — hermetic happy path, A3 legacy no-metadata lineage test
- `m4/review/ROUND2_IDEA_TO_DRAFT_CORRECTNESS_REPORT.md` — this report

STOP — awaiting ROUND 2 review before any further round.
