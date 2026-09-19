# M3A — Editor Workbench MVP — Engineering Report

**Date:** 2026-09-18 · **Checkpoint:** working tree on `main` after M2S-R4
**Verdict:** `EDITOR_WORKBENCH_ENGINEERING = PROVEN` (offline tests + scripted
end-to-end smoke) · `EDITOR_WORKBENCH_EDITORIAL_EFFECTIVENESS = PENDING`
(no real editor has used it yet) · `EDITORIAL_EFFECTIVENESS = PENDING` (unchanged).

Scope was the M3A editor Workbench only. No frozen contract changed: SITE DNA,
VOICE/MODE profiles, newsworthiness rubric, semantic-veto rules, readiness
thresholds, hook guidance, model-vs-deterministic authority, transcript-discovery
semantics and search routing are all untouched. Nothing was added to
`src/**` that reimplements editorial logic in the UI.

---

## 1. Architecture — a thin product layer over the frozen workflow

```text
frozen workflow contracts      cases.read_cases / record_editor_final / save_cases,
                               readiness.apply_editor_override, diff.diff_draft_final, live.*
          ^
workbench/state.py             service layer — the ONLY writer on this surface;
  workbench/html.py            escaping renderer (Bulgarian-first)
  workbench/http.py            stdlib http.server routing + form parsing
  workbench/labels.py          BG labels for stored enums (translation only)
  workbench/__main__.py        `--host/--port/--allow-quit`
          ^
browser                        no build chain, no framework, no JS required
```

**Stack decision:** stdlib `http.server` + hand-rolled HTML rather than
FastAPI/Jinja2/Uvicorn. The repo is deliberately stdlib-only
(`pyproject [project].dependencies = []`); adding a web framework would break
that rule for no benefit on a local, single-user surface. Everything (routing,
HTML escaping, form parsing, atomic writes) is stdlib.

**Single entry point:** the existing workflow CLI gained one subcommand.

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench          # 127.0.0.1:8123
PYTHONPATH=src python3 -m editor_assistant.workflow.workbench --port 9000  # equivalent
```

`--host` defaults to `127.0.0.1` and is opt-in with a printed warning (no auth
on this MVP). `WB_PORT` and `WB_ALLOW_QUIT` env overrides exist. No `.env` is
ever read, and no secret can reach a template, a log line or a response.

## 2. Pages and routes

| Route | Purpose |
|---|---|
| `GET /` (`?filter=…`) | Редакторска опашка — all LIVE cases, plus benchmark cases in a separate section |
| `GET /case/{id}` | Case detail: four surfaces (draft / sources / status / editor) |
| `POST /case/{id}/save` | Save the non-authoritative working copy → 303 back to the case |
| `POST /case/{id}/finalize` | Explicit finalization through `record_editor_final` → 303 |
| `POST /case/{id}/decision` | Record a special-case editor decision (no draft body) → 303 |
| `GET /healthz` | liveness |
| `POST /quit` | test-only; refused unless `WB_ALLOW_QUIT=1` |

Queue filters: **Всички · За редакция · Нужна информация · Нужно решение ·
Без достатъчна новина · Финализирани**. Internal ids (`DRAFT_READY`,
`FACTUAL_GATE_PASS`, `LIV-01`) stay visible next to their Bulgarian label.

### Case page surfaces

- **А. Чернова** — the immutable AI headline, body and alternative headline
  candidates, flagged «AI чернова (неизменима)».
- **Б. Източници** — name, domain, authority (BG label), retrieval date,
  clickable external link, per-source claims, and fact-level locators
  (`t=HH:MM`, no milliseconds) in the packet's `provenance.attached`. Unsafe URL
  schemes render as plain text, never as links. No raw internal JSON.
- **В. Статус и предупреждения** — readiness, factual gate, unsupported-claim
  warnings, research notes, duplicate state, transcript trust level
  (`AUTO_CAPTION → Автоматичен YouTube транскрипт` …) and a stale-edit banner.
  The transcript trust badge is rendered inside the source panel too (§17), and
  locators are shown as human time (`08:42–09:17`), never `seg1@t=08:42.250`.
- **Г. Редакторско работно поле** — headline + body textareas prefilled from the
  working copy or the AI draft, the structured review questions, a deterministic
  diff summary, and separate **Запази работно копие** / **Финализирай
  редакторската версия** actions.

### Special (no-draft) cases

- `NO_PUBLISHABLE_ANGLE` — no article editor at all; states the AI decision
  («Няма достатъчно силен и проверим новинарски ъгъл»), shows what is known /
  missing, and offers the decision form (REJECT_STORY / REQUEST_MORE_RESEARCH).
- `RESEARCH_MORE` / `EDITOR_DECISION_REQUIRED` — what is known, what is missing,
  the research questions already asked, and the sources already checked;
  decision options «Поискай още проучване / Продължи с наличното / Не
  публикувай». M3A only records the decision — no research executor (M3C).

## 3. Canonical state vs. working copy

| | Store | Authority |
|---|---|---|
| AI draft + case + editor final | `var/editorial_workflow/cases.jsonl`, `live_evidence.jsonl` | canonical, written **only** through the frozen contracts |
| Editor working copy | `var/editorial_workflow/editor_working/{CASE}.json` | non-authoritative, disposable, never canonical |
| Audit | `var/editorial_workflow/workbench_actions.jsonl` | append-only `{action, case_id, timestamp}` |

Working-copy schema: `{case_id, base_draft_id, headline, body, review_answers,
updated_at}`. Writes are atomic (`mkstemp` in the same dir + `os.replace`).
`base_draft_id` binds the working copy to the draft generation it started from.

**Saving and finalizing are different endpoints.** `save` never marks a case
final, never publishes, never touches readiness, and never mutates the AI draft
(tested).

**Stale-edit protection (§11).** If `base_draft_id != case.draft_id` at
finalization time, the request is refused with HTTP 409 and the Bulgarian banner
«Междувременно е генерирана по-нова AI версия. Прегледайте разликите преди
финализиране.». No collaborative locking.

**Bypass-proof and not a dead end.** The check evaluates *both* the working
copy's recorded `base_draft_id` and any `base_draft_id` submitted with the
request, so resubmitting the current draft id cannot clear a stale binding.
The way forward is an explicit editor action: the workspace shows
**«Приемам новата AI версия за основа»** when the working copy is stale;
saving with that box ticked adopts the current generation while keeping the
editor's text. A plain save never re-bases. Finalization therefore asks for a
decision rather than dead-ending (§11), and the finalize surface states why it
is currently blocked.

## 4. Validation boundaries

- All canonical writes go through `cases.record_editor_final` +
  `cases.save_cases`; decisions go through `readiness.apply_editor_override` on
  the live evidence row. There is no direct JSONL write anywhere in the UI.
- Invalid editor enums (`editing_weight`, `editor_outcome`, `readiness_outcome`,
  unknown `readiness_answers` keys) are rejected by the contract and surface as
  HTTP 400 with the contract's own message.
- Unknown cases → 404; already-finalized / stale → 409; dry-run benchmark cases
  refuse effort metrics → 400; empty headline/body on finalize → 400 (an article
  final needs text; a no-story case uses the decision endpoint instead).
- A finalized case is immutable on this surface: its page renders the final
  result and the recorded editor metrics, with **no** editor workspace, and a
  working-copy save against it is refused — a save an editor could never apply
  would be a false promise.
- A corrupt/truncated working-copy file is treated as “no working copy” (it is
  non-authoritative state), so damage can never wedge a case page or block every
  future save.
- Malformed requests degrade to a rendered Bulgarian error page; a handler
  exception is turned into an HTTP response rather than killing the server.
- HTML escaping: every dynamic value goes through `html.escape`; URLs are
  scheme-allow-listed (http/https only). `<script>`, `javascript:` and injected
  article text are proven inert by tests.
- Server binds `127.0.0.1` by default (asserted by test).

## 5. Scripted manual smoke (§25)

`PYTHONPATH=src python3 scripts/m3a_smoke.py` (promoted from the untracked
`tmp/m3a_smoke.py` by the M3A stabilization pass) runs the workbench against a **copy** of
the real store (`var/wb_smoke/`), so the editor's pending pilot answers are never
touched. Result: **25/25 checks passed**, including:

```text
1 dashboard loads · 2 LIVE cases visible (LIV-01…06)
3 normal case opens · 4 sources render
5 save → 303 · 6 working copy saved · 7 reload keeps the edit
8 finalize → 303 · 8b final text persisted
9 AI draft unchanged · 9b draft ≠ final
10 final + editor metrics render
11 NO_PUBLISHABLE_ANGLE opens (no case row) · 11b no article editor
11c AI no-story decision stated
12 decision → 303 · 12b no-story decision recorded without body
13 newer AI generation flags the working copy as stale · 13b banner + re-base control
14 stale finalization refused (409) · 14b nothing finalized
15 explicit re-base adopts the new generation · 15b finalization then succeeds
S real store byte-identical (sha256 before == after)
```

## 6. Tests

`tests/test_workbench.py` (+74 tests; suite 394 → **468 passed**, offline).
Covered: queue rendering + filters, BG label mapping (incl. contract-vocabulary
equality), immutable-draft rendering (bytes unchanged), safe source rendering,
working-copy save/load, atomic write, save-never-finalizes, stale-generation
block, validated finalization through `record_editor_final` (diff metrics +
audit row + AI draft untouched), invalid enums, the special no-draft cases,
HTML escaping, and the localhost default. HTTP behaviour is exercised through a
real `127.0.0.1` server on an ephemeral port (routing, 303 redirects, 400/404/409).

Repo hygiene: `ruff check src tests` clean; `ruff format --check` clean on the
workbench files and the new test file.

## 7. Bugs found and fixed while finishing M3A

- **Case routing was dead.** `_route` split the path without dropping the leading
  `/`, so `/case/{id}` and all POST endpoints resolved to 404. Every case page
  would have been unreachable in a browser.
- **Queue filter parsing.** `_first` was called with a `list` instead of a dict →
  500 on `GET /`.
- **Redirects dropped the `Location` header.** Headers were added after
  `end_headers()`, so the 303s had no target and the `?message=` confirmation was
  never rendered.
- **Finalization was impossible from the UI.** The finalize form omitted the
  required `editor_outcome` and `editing_weight` fields.
- **Answer fields were dropped.** The finalize form used an `ans_` prefix while
  the handler read `answer_`.
- **`prefer_ai_start` leaked into `readiness_answers`.** It is a separate
  contract field, so any save that answered that question returned 400.
- **Evidence-only special cases were invisible.** `NO_PUBLISHABLE_ANGLE`
  evidence rows have no case row (e.g. `LIV-06-EVIDENCE`), so the queue never
  listed them and the case page 404'd. They are now derived generically from
  stored readiness status (never hardcoded ids) and can record a decision
  without a draft.
- Missing `import threading` (the `/quit` path would have raised at runtime).

### Found by the adversarial review pass (after the UI first ran)

- **Stale-generation bypass, confirmed through the real UI.** A stale working
  copy (`working_copy_is_stale == True`) could still be finalized over HTTP,
  because only the submitted `base_draft_id` was compared. Fixed as described in
  §3, and proven by `test_rebase_then_finalize_through_the_ui` plus smoke 14/15.
- **The fix had no door.** `save_working_copy(accept_new_base=…)` existed but no
  caller ever passed it, so a stale working copy could never be re-based — a
  permanently blocked finalization with no UI escape. The workspace now exposes
  the re-base control and the handler plumbs it through.
- **A corrupt working copy bricked the case.** `load_working_copy` raised
  `JSONDecodeError`, so one truncated file produced a 500 on every page for that
  case and made every later save fail. Now tolerated.
- **Recording a decision bounced the case back into the wrong queue.**
  `REJECT_STORY` overwrites the readiness `post_loop_decision`, so the case lost
  its special classification and reappeared under «За редакция» asking for the
  finalize the editor had just rejected. Classification now follows the recorded
  decision.
- **Empty finals were possible.** `record_editor_final` only validates
  `editor_outcome` when the text is non-empty (the CLI's published-reference
  path), so the UI could finalize an article with no headline or body. The
  service layer now requires both.
- **A finalized case still offered the editor workspace**, inviting work that no
  endpoint could ever apply. Hidden now, and the save is refused.
- **§16/§17 were only half-built.** `fmt_locator` and `TRUST_LABELS` were dead
  code: the panel printed raw `seg1@t=08:42.250` locators and never stated the
  transcript trust level. Both are now rendered; `WORKING_COPY_KEYS` (unused)
  was removed.
- **Bucket and page could contradict each other.** `queue_filter` re-derived
  the queue from readiness status while the page layout came from
  `special_kind`, so a case with a draft *and* a `RESEARCH_MORE` status landed
  under «Нужно решение» on a page that offered no decision form. Classification
  now has one source of truth, with a test asserting bucket and surfaces agree.
- **Cosmetic honesty fixes.** The time-saved field was labelled «задължително»
  while the contract treats it as optional; the final surface printed the raw
  `prefer_ai_start` enum (`MIXED`) instead of its Bulgarian label; the select
  option lists were duplicated literals instead of the contract tuples
  (`EDITING_WEIGHTS`, `TIME_BUCKETS`), so they could silently drift.

## 8. Known limitations

- **No authentication / multi-user / permissions** — local MVP bound to
  localhost by design.
- No `prefer_ai_start` in the *working copy* (it is an effort/adoption metric
  asked at finalization, and the contract keeps it out of `readiness_answers`).
- Working copies are per-case JSON files; there is no history of intermediate
  editor drafts beyond the latest save.
- `ruff format --check src tests` still reports two **pre-existing** files
  (`workflow/search.py`, `tests/test_tinyfish_adapters.py`) as unformatted. That
  is pre-existing debt, deliberately not touched here (scope lock).
- The stale-edit check compares `base_draft_id` only; there is no line-level
  merge view.
- No research executor, no YouTube adapter, no publishing — those are M3B/M3C
  and are intentionally absent (no placeholder fake functionality).

## 9. Verdict and STOP

`EDITOR_WORKBENCH_ENGINEERING = PROVEN` for what engineering can prove: the UI
is a thin, validated layer over unchanged contracts, and the full editor loop
(queue → case → sources → edit → save → reload → finalize → next; plus the
special no-draft decisions) works end-to-end offline.

`EDITOR_WORKBENCH_EDITORIAL_EFFECTIVENESS` stays **PENDING** until a real
Chernomorie editor actually uses it. **STOP** — no M3B YouTube adapter, no M3C
automatic enrichment, no LIVE 6–10, no CMS publishing, no editorial rule
changes. Awaiting review.
