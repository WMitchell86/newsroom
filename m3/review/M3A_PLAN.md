# M3A Editor Workbench — implementation plan (pre-implementation, frozen before code)

Derived from a full read of the current `main` checkpoint (60d09d2) before any
implementation. This plan fixes the architecture, boundaries and file layout.
No frozen contract is modified: SITE DNA, VOICE/MODE profiles, newsworthiness
rubric, semantic-veto rules, readiness thresholds, hook guidance,
model-vs-deterministic authority, transcript-discovery semantics and search
routing stay untouched.

## 1. Verified repo facts the plan builds on

- Stack: **stdlib-only** Python 3.10 package `editor_assistant` under `src/`,
  pytest under `tests/`, run with `PYTHONPATH=src` (pip install is PEP-668
  blocked). Ruff (line 100) formats/checks `src tests`.
- Canonical workflow contracts already exist and are validated:
  - `workflow/cases.py` — `open_case`, `record_editor_final` (validates
    `editor_outcome ∈ {ACCEPTED_FOR_EDIT, REJECTED, MIXED}`,
    `editing_weight ∈ {LIGHT, MODERATE, HEAVY, REWRITE, REJECTED}`,
    `time_saved_estimate ∈ {<5 min, 5-15 min, 15-30 min, >30 min}`,
    `readiness_outcome ∈ READINESS_OUTCOMES`, `readiness_answers` keys/values),
    `save_cases`/`read_cases`, `workflow_metrics`, `lineage_problems`.
  - `workflow/readiness.py` — statuses `DRAFT_READY / RESEARCH_MORE /
    NO_PUBLISHABLE_ANGLE / EDITOR_DECISION_REQUIRED`; `assess_readiness(packet,
    mode=...)` is the real orchestrator; `expansion_plan`, `apply_editor_override`.
  - `workflow/live.py` — `live_readiness(packet)` (exact callable recompute
    contract), `live_generate_draft` (needs API key → NOT wired in M3A).
  - `workflow/diff.py` — deterministic `diff_draft_final` + `classify_diff`.
- Stores (all under `var/editorial_workflow/`, git-ignored runtime data):
  `cases.jsonl` (append-lineage, `save_cases` rewrites sorted-by-key), 10 WFX
  dry-run benchmark cases + 5 LIVE pilot cases (LIV-01…05, none finalized),
  `live_evidence.jsonl` (packet + stored readiness status per evidence),
  `ideas.jsonl`, `review/*.md` scorecards (incl. LIV-03-DECISION,
  LIV-06-NOSTORY), `research/*.json` (sources with claims + retrieval dates).
- Pilot fixture statuses (rendered from stored contracts, never hardcoded):
  LIV-02 generation 3 (superseded generation 2 draft archived in
  `superseded/`, case `draft_id=dba1ef620f33` matches current); LIV-03
  evidence readiness `RESEARCH_MORE` + `post_loop_decision=
  EDITOR_DECISION_REQUIRED`, 2/2 research rounds; LIV-05
  `FACTUAL_GATE_REVIEW`; LIV-06 `NO_PUBLISHABLE_ANGLE` (evidence
  `LIV-06-EVIDENCE`, no case row, no draft); LIV01/04 `DRAFT_READY`.
- Provenance shapes: packet `provenance.attached[fact_id] =
  [{source_id, locator: "seg1@t=08:37"}, ...]` (LIV-02) or fact
  `source_reference: "source_text"` (web cases); research files
  `sources[] = {source_id, source_name, source_type, authority
  (PRIMARY/CORROBORATING/DISCOVERY_ONLY), url, published_at, retrieved_at,
  relevant_claims[]}`; transcript trust vocabulary in
  `workflow/transcripts.py` (AUTO_CAPTION / HUMAN_TRANSCRIPT / HUMAN_VERIFIED /
  OFFICIAL_VERBATIM), locators are `t=HH:MM` (no ms stored in packets).
- CLI: `finalize` guard "already finalized" exists; dry-run benchmark track
  refuses effort fields. There is **no generation field** on drafts —
  draft identity is `lineage.draft_id` + `lineage.generated_at`.


## 2. Architecture: thin UI service layer over existing contracts

```text
workflow contracts (frozen)  cases.read_cases/record_editor_final/save_cases,
                             readiness.assess_readiness, diff.*, live.*
        ↑
editor_assistant/workbench/  service layer (queue, case view, working copy,
                             finalization, audit, labels) — the ONLY module
                             that writes; passes through validated functions
        ↑
workbench/http.py            stdlib http.server + html.py escaping renderer
        ↑
browser (no build chain, no framework)
```

- **stdlib `http.server`** (not FastAPI/Jinja2): the repo is deliberately
  stdlib-only (`pyproject dependencies = []`); a pip dependency would break the
  repo rule for zero benefit on this surface. HTML is produced by a tiny
  `html.py` (all dynamic values escaped via `html.escape`; URLs via
  `_safe_href` scheme allow-list: http/https only).
- **Bind `127.0.0.1` by default**; `--host`/`--port` opts exist but `--host` is
  opt-in with a printed warning. No auth (local MVP), no secrets ever rendered
  (no `.env` reading anywhere in `workbench/`).
- One command: `PYTHONPATH=src python3 -m editor_assistant.workflow.workbench`
  (sub-CLI of the existing workflow CLI, same invocation pattern as the rest).

## 3. New/changed files

```text
src/editor_assistant/workflow/workbench/
  __init__.py
  state.py        service layer: queue(), case_view(), working copy store,
                  finalization via record_editor_final, decision recording
                  via readiness/live recompute + evidence-row override,
                  workbench_actions.jsonl audit. var paths overridable
                  (env WB_EDITORIAL_WORKFLOW_DIR) for test isolation.
  http.py         handler, routing, dispatch, form parsing (127.0.0.1 default)
  html.py         escaping renderers (queue page, case page x4 surfaces)
  __main__.py     arg parsing → serve()
  cli.py          adds `workbench` subcommand to workflow.cli
tests/test_workbench.py        backend + HTML tests (main suite, offline)
tmp/m3a_smoke.py               §25 manual smoke script (writes to var/wb_smoke/)
m3/review/M3A_EDITOR_WORKBENCH_REPORT.md
```

Only `workflow/cli.py` is modified (subcommand registration, ~3 lines).

## 4. Route/page map (Bulgarian-first; internal IDs shown alongside)

- `GET /` — Редакторска опашка. Rows: CASE ID, заглавие/тема, статус, готовност
  (readiness), фактологична проверка, режим (mode), последна обнова (draft
  generated_at / decision updated_at), финализиран. Filters: Всички · За
  редакция · Нужна информация · Нужно решение · Без достатъчна новина ·
  Финализирани. WFX dry-run cases listed in a separate benchmark-only section
  (their effort fields are invalid; the finalize form is not offered there).
- `GET /case/{id}` — four surfaces: А. Чернова (AI headline + body +
  alternative headlines, immutable, flagged «Неизменима AI чернова») ·
  Б. Източници (name, domain, authority BG label, date, relevant claims,
  fact-level locators in collapsible `<details>`; `t=HH:MM` timestamps;
  transcript trust BG labels; no raw internal JSON) · В. Статус (readiness,
  factual gate, research warnings incl. „последното изречение не е достатъчно
  подкрепено…“ from semantic n_unsupported, duplicate state, stale-edit
  banner) · Г. Редакторско работно поле (headline + body textareas prefilled
  from working copy or AI draft; review form; diff summary vs AI draft;
  Save/Finalize are separate actions).
- `POST /case/{id}/save` — save working copy (atomic tmp+os.replace;
  `{case_id, base_draft_id, headline, body, review_answers, updated_at}`).
  Never canonical, never touches the AI draft or readiness.
- `POST /case/{id}/finalize` — staleness check (`base_draft_id != case
  draft_id` → HTTP 409 with the §11 Bulgarian banner, no overwrite) →
  `record_editor_final(...)` through the existing contract → `save_cases`
  (atomic via tmp+os.replace) → audit. Dry-run track → HTTP 400.
- `POST /case/{id}/decision` — for the three special cases: maps UI choices to
  the **existing** readiness override contract (`readiness.
  apply_editor_override` action FORCE_DRAFT/REQUEST_MORE_RESEARCH/REJECT_STORY
  with a required reason) recorded on the live evidence row via the same
  re-save path the CLI uses (`_save_live_row` pattern), plus a case-level
  `workbench_decision` record (decision, readiness_outcome, note,
  missed_angle, updated_at). No draft required (NO_PUBLISHABLE_ANGLE has
  no editor). No research executor in M3A (M3C hook).
- `GET /healthz` + `POST /quit` (test-only, refused unless `WB_ALLOW_QUIT=1`).

Working-copy store: `var/editorial_workflow/editor_working/LIV-01.json`
(non-authoritative, schema per harness §10, `base_draft_id` for staleness).
Stale case-queue status pairs a working copy with a newer draft.

## 5. Validation boundaries (enforced, tested)

- All canonical writes: `record_editor_final` + `save_cases` only.
- Invalid enums → HTTP 400 with the contract's error text (tested).
- `save` can never finalize (separate endpoints, tested).
- Finalizing an already-finalized case → HTTP 409.
- Stale-generation finalize → HTTP 409 (tested with LIV-02-style lineage).
- HTML escaping: `<script>` in source fields / article text renders escaped
  (tested); `_safe_href` blocks `javascript:` etc.
- Working-copy store failures never corrupt canonical state (atomic writes).
- Dry-run cases: finalize endpoint refuses (effort fields are fabricated data).
- Special cases: decision endpoint records without a draft body;
  NO_PUBLISHABLE_ANGLE page shows no article editor; RESEARCH_MORE page shows
  known/missing/research questions/checked sources from stored evidence.

## 6. Tests (offline; var redirected via env; main suite stays green)

Queue renders LIVE cases · BG status labels map (all vocab pairs) · case page
renders draft without mutation (file mtime/bytes unchanged) · sources render
safely (escaped, incl. `<script>` + scheme block) · working copy save/load ·
atomic working-copy write (crash leaves no partial file) · save-never-final ·
stale-generation finalize blocked · valid finalization uses
`record_editor_final` (diff metrics + classification + immutable draft +
audit row asserted) · invalid editor enum rejected (400) ·
NO_PUBLISHABLE_ANGLE requires no article body (decision recorded) ·
RESEARCH_MORE records research-request decision · FACTUAL_GATE_REVIEW warning
renders · server defaults to localhost (handler default binding).

## 7. Manual smoke (§25) — scripted in tmp/m3a_smoke.py against var/wb_smoke/
(a copy of the real editorial_workflow dir; the real editor's pending pilot
answers and canonical cases.jsonl are never modified)

Then: docs (report + README/RUNBOOK/MILESTONE/handoff), full suite, ruff,
STOP.
