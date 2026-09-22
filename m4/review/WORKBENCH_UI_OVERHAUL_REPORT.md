# Workbench UI Overhaul — 2026-09-21

**Trigger:** the editor-in-chief's verdict on the running app: *"the GUI of the
platform is bad … it is nowhere near a usable state for a non-technical person …
the agent working on it had no idea what the app is for."* Two in-repo reviews
agreed: `m4/review/UX_UI_REVIEW.md` (P0–P2 findings) and
`m4/review/WORKBENCH_CURRENT_STATE.md` (no concept of «today», no hierarchy).

**Base:** `6410d77`. **Gate:** `ruff check` + `ruff format --check` clean,
**914 offline tests** (was 913), M3A smoke **25/25**, live isolated UI proof
`ALL CHECKS PASSED`.

---

## PART 1 — What was actually wrong

| # | Finding (from the review) | Severity |
|---|---|---|
| 1 | `/` landed on the frozen M3A case queue, not the newsroom | P0 |
| 2 | ~5 KB of CSS duplicated inline in every page's `<head>` | P0 |
| 3 | Destructive buttons (remove route/source/domain) had no confirmation | P0 |
| 4 | Label read `Добави модел (provider:model):` above two separate inputs | P0 |
| 5 | `/models` was 58 KB — 4 forms per route × ~5 hidden inputs each | P1 |
| 6 | Nav was pipe-separated links with no active-page indicator | P1 |
| 7 | Empty states gave no next action | P1 |
| 9 | Blank screen during «Събери новините сега» | P1 |
| 11 | `Редакторски работен плот M4` — meaningless version tag | P1 |
| 12 | `/models` printed raw paths + policy hashes | P2 |
| 13 | «Добави източник» was 10+ fields in one flat column | P2 |
| 14 | Muted palette, small badges | P2 |
| 15 | No responsive rules | P2 |
| 16 | Developer Bulgarian on /stories and /inbox | P2 |

Root cause (from `WORKBENCH_CURRENT_STATE.md`, kept verbatim there): every
milestone appended a page to the same flat nav; no milestone ever asked *"what
does the editor's morning look like?"*.

---

## PART 2 — What changed

### The app now says what it is (P0-1, P1-11, P2-16)

Header: `Дневен новинарски помощник` + the one-line purpose
*«Какво е ново от вашите източници · прочетете · отбележете · напишете»*.
The `M4` tag is gone.

`/` is now **Начало** — the daily landing page (`html.render_home`), read-only:
four counters (нови истории / непрегледани материали / пристигнали днес
(Europe/Sofia) / активни източници), the five newest stories with their
publishers, two big buttons with counts, and a three-step «Как се работи» card
that names the exact button to press. The frozen M3A queue moved to `/cases`
with an explicit «Това е архивната опашка от по-ранен етап» note; old
`/?filter=…` links still resolve to it (back-compat branch in `_get_root`).

### Navigation has hierarchy (P1-6)

Two rows instead of one pipe-separated list:
primary pills — `Начало · Истории · Материали · Източници`;
secondary row labelled *«Настройки и архив:»* — `AI модели · Случаи · YouTube`.
The active item is a filled pill (`.nav-active`), not a subtle colour change.
*(Same-day follow-up, found by the editor-in-chief on the running app: every
header link inherited the body `a` colour — blue text on the blue gradient
header, including the product title, and `.nav-active` had no CSS at all. The
header now owns its colours: white links, hover wash, and a white
`.nav-active` pill with the accent-dark text.)*

### One stylesheet, not five (P0-2)

`GET /static/style.css` serves `html.CSS` once
(`text/css; charset=utf-8`); pages link it and keep the inline block only as a
no-CSS-server fallback. The stylesheet now also carries `.stats` / `.howto` /
`.hero-actions` / `fieldset` / input focus styling, a `.table-wrap` scroll
container and a single `@media (max-width: 768px)` block (P2-14/15).

### Nothing destructive happens by accident (P0-3)

One small script in `page()`: any button with `data-danger` asks
`confirm('Наистина ли?')`, and the compact route manager additionally asks when
the chosen operation is `Премахни`. Covered: source remove, blocked-domain
remove, story ignore, story «не е част от историята», model route remove.


### /models is a page, not a form dump (P0-4, P1-5, P2-12)

- The 4-forms-per-route scaffolding is replaced by **one manager form per role**:
  a route `<select>`, an operation `<select>` (up / down / toggle / remove) and
  «Приложи». Field names (`op`, `index`) are translated to the legacy
  `action`/`direction`/`enabled` vocabulary in `http._post_models`, so the
  policy contract, the CLI and the existing tests are untouched.
- Label fixed: «Добави нов модел към тази роля» with `Доставчик (provider)` /
  `Модел (model)` labels and placeholders — no more `provider:model`.
- Raw file path + policy hash moved into `<details><summary>Технически детайли`.
- The page headline explains it is advanced settings, not daily work; every role
  and route, billing label, privacy flag and eligibility badge stays visible.
  Route state renders as a real badge (`✓ готов` → `.badge.ok`,
  `× пропуснат` → `.badge.block`) so column scans green-vs-red at a glance.
- Measured: `/models` **58 KB → 27.6 KB** in the live isolated run.

### Empty states are instructions (P1-7)

`/stories` and `/inbox` empty states are now a hero card that states the three
steps and offers the button that performs step 1 in place («Обнови историите
сега» / «Събери новините сега»), instead of a muted sentence pointing at a form
below the fold.

### The app answers while it works (P1-9)

`Събери новините сега` and `Обнови историите` are marked `data-busy`: on submit
the button disables and a `Събиране… моля, изчакайте.` overlay appears, so the
long POST no longer looks like a dead page.

### Sources form is grouped (P2-13)

«Добави източник» is one card with three fieldsets — *Основно · Адрес ·
Настройки* — plus a line telling the editor that a direct feed needs a URL and a
search source needs a query.

### Daily copy rewritten (P2-16)

`/stories`: «История = нови материали, групирани като едно събитие. Броим
отделно материалите и издателите.» `/inbox`: «Нови материали от вашите
източници. Това са събрани кандидати, не доказателства — нищо тук не е
проверено и не е готово за публикуване.» (the candidate-not-evidence safety
sentence is preserved in meaning and still asserted by a test). `/sources` no
longer prints CLI commands: it says what the page is for and points to
«Събери новините сега» in Материали for a manual run.

### The add-model form still works

The compact rewrite kept the add-another-route form complete — provider, model,
`public_only` checkbox, «Добави» — and a live check confirms it: add returns 303
and the model is stored, remove returns 303 and the model is gone, an add without
a model and a removal of a non-existent index are refused with 400. Every page is
also parse-checked for unclosed tags (`ALL PAGES WELL-FORMED`).


---

## PART 3 — Proof (live, isolated stores, real HTTP)

Proof run (temp `WB_NEWSROOM_DIR`, temp `WB_EDITORIAL_WORKFLOW_DIR`, one real
source + one real collected item + a real deterministic story build, a real
server on 127.0.0.1 with real GET/POST requests):

```text
[PASS] home 200 / is the daily landing / 3-step howto / counts materials
[PASS] home lists the newest story («Общинският съвет прие бюджета»)
[PASS] no M4 version tag in the header
[PASS] nav has a daily group + an admin group
[PASS] css is external ; /static/style.css served — 5116 bytes
[PASS] /stories /inbox /sources /models /cases 200 + titles
[PASS] models page has the compact manager (name="op") + confirm-on-remove
[PASS] models keeps billing labels ; raw path in <details>
[PASS] no provider:model label confusion
[PASS] op=down 303 ; op=toggle 303 ; unknown op 400 ; legacy remove 400
[PASS] empty-state guidance on inbox ; candidate-not-evidence note kept
[PASS] /cases?filter=edit works ; old /?filter=edit still resolves
[PASS] op=down reordered a real route ; op=toggle really flipped it (True -> False)
[PASS] add model 303 + stored ; op=remove 303 + gone ; bad add/index 400
[PASS] every page parse-checked: ALL PAGES WELL-FORMED (no unclosed tags)
UI verification: ALL CHECKS PASSED
```

Page weight measured in the same run: `/` 9.1 KB · `/stories` 8.7 KB ·
`/inbox` 10.1 KB · `/sources` 13.0 KB · `/models` 27.6 KB · `/cases` 7.5 KB.
(The first render of any page still inlines the same CSS as a fallback; a real
browser fetches `/static/style.css` once for the whole session.)

Suite: **914 passed**; `ruff check src tests` + `ruff format --check src tests`
clean; `PYTHONPATH=src python3 scripts/m3a_smoke.py` **25/25** (checks 1–2 updated
to assert the landing page loads and that the queue stayed reachable at `/cases`).

---

## PART 4 — What was deliberately NOT changed

- **No backend semantics.** Every button still goes through the same service
  functions (`sources_registry`, `blocked_domains`, `inbox_store`, `story_store`,
  `newsroom_run`, `model_policy`) — the UI owns no validation.
- **No new dependency, no JavaScript framework.** One short inline script for
  confirm + busy feedback; every page still works with JavaScript disabled.
- **Routes and stores unchanged** except the new read-only `/` and
  `/static/style.css`; `/cases` is the queue's canonical URL and the old one
  still answers.
- **Frozen surfaces untouched**: M3A case pages, finalization guards, the
  `AI чернова (неизменима)` contract, `/intake`, `/healthz`.
- **Still open (needs the editor):** M4E Telegram alert format, and whether
  `YouTube` should leave the navigation entirely.

---

## PART 5 — Verdict

```text
WORKBENCH_UI_DAILY_ENTRY_POINT      = BUILT (Начало; /cases = archive)
WORKBENCH_UI_NAVIGATION_HIERARCHY   = BUILT (daily vs settings/archive)
WORKBENCH_UI_STYLESHEET             = EXTRACTED (/static/style.css)
WORKBENCH_UI_DESTRUCTIVE_CONFIRM    = BUILT (data-danger / data-confirm-route)
WORKBENCH_UI_MODELS_PAGE            = COMPACTED (58 KB → 27.6 KB, one form/role)
WORKBENCH_UI_EMPTY_STATES           = ACTIONABLE (step + button in place)
WORKBENCH_UI_LONG_ACTION_FEEDBACK   = BUILT (busy overlay)
WORKBENCH_UI_EDITOR_LANGUAGE        = SIMPLIFIED (no dev jargon on daily pages)
EDITORIAL_EFFECTIVENESS             = PENDING (unchanged — still needs a real editor)
```

Next natural step: put this in front of the editor-in-chief, then choose
between M4E (Telegram alerts) and the next round of UI polish from real use.

