# V1.2-G3 — Article / Draft Workspace Visual Polish

**Status:** complete and proven in a real browser.
**Scope:** presentation and interaction only. No backend behaviour was changed.

---

## 1. The decision this slice records

Research is closed for the prototype. `precision solved, broad recall deferred`.
The G2.4B result stands unchanged: WRONG = 0, CHROME = 0, one official PRIMARY
source can establish its own first-party facts, two independent paraphrased
publishers can corroborate, and the remaining ~5/24 coverage is a real but
deferred shortfall.

No Serper credits were spent in G3. No research algorithm, corroboration rule or
search strategy was touched.

G3 therefore spends the slice on the thing the editor actually touches:
`/articles/:articleId`.

---

## 2. What changed, by contract

### Article header (§7, §8, §16)

```
← Статии                          Статия · Чернова
Ремонтът на булевард „Свобода“ ще започне през октомври
Запазено
История: Ремонтът на булевард „Свобода“ ще започне през октомври
```

The title **is** the `<h1>` and stays directly editable, rendered as a borderless
input that takes a hairline underline on focus — an editable headline that does
not look like a form. The state is a quiet marker, not a badge. The Story stays
one line away.

Removed from this surface: the content version, the readiness/version panel, the
"Версия N" context, concurrency ids and API errors. `Запазва се…` / `Запазено` /
`Неуспешно запазване` are the entire save vocabulary.

### One autosave, two render sites (§13, §14)

The title and the body are **one** save. `useArticleAutosave.ts` was extracted
from the old editor component precisely so the title could be drawn in the header
while remaining a single optimistic-concurrency writer.

Semantics are untouched: 800 ms debounce, blur flush, serialized writes,
optimistic concurrency, navigation flush, truthful conflict handling.

> This extraction caught a real defect. The first G3 attempt let
> `PreparationWorkspace` create its *own* autosave while the page held another.
> On the Preparation → Draft transition that a manual continuation causes, the
> second writer held a stale body and the save status vanished. One owner, one
> version, one status — the C3 defect class, prevented structurally rather than
> by convention.

### The Draft is the centre (§5, §6, §13)

`.deskGrid` is `minmax(0, 900px) minmax(260px, 300px)`. When the Article has no
evidence and no gap, `.deskGridSolo` is used instead: the rail is **absent, not
empty**. The fixed 300 px slab that used to be reserved unconditionally is gone,
and the browser proof measures the widening.

The body is one `<textarea id="article-working-body">` with one label, a
comfortable measure and generous vertical space. Measured in the real page: the
proof asserts 520–1000 px of width, ≥ 400 px of height and ≥ 24 px of line
height.

### Focus (§11, §12)

Preparation: prominent, pre-filled, with the backend's own 2–3 alternatives as
real buttons and `Напиши свой`. One click **replaces and saves** — the browser
proof counts exactly one `PUT /focus` and asserts no `Потвърди` / `Приложи`
control exists.

Draft / Ready: a quiet collapsed block (`Фокус` · the sentence · `Промени`),
rendered only when the backend actually offers `CHANGE_FOCUS` / `SELECT_FOCUS`.
Never a large textarea above every draft.

### Support rail (§17, §18, §19)

Titled `Факти и източници`. Each fact is a statement with its source name as the
link (`Официален портал на Община Бургас ↗`). One collapse control,
`Скрий източниците` / `Покажи източниците`, with real `aria-expanded` and
`aria-controls`. No draggable pane, no resizable layout.

The old generic disclosure `Факти, източници и липсваща информация` is gone. The
rail is the Article's factual support, and it never claims a publication is
evidence.

### Warnings and readiness (§20)

The single large warning panel is replaced by a `Какво да прегледаш` block placed
with the decision it affects. Severity hierarchy is unchanged (info / review /
blocking), and every message is the backend's own text.

The heading deliberately avoids the word `Проверка`: §31 forbids a fake state
named «Проверка», and naming a section that would collide with it would have made
that contract untestable.

### States and actions (§25 – §31)

Exactly `Подготовка` / `Чернова` / `Готова`, plus Finalized in the Archive. At
most one filled forward action at any moment:

| State | Primary | Secondary |
| --- | --- | --- |
| Preparation | `Направи чернова` | `Проучи историята` |
| Draft | `Отбележи като готова` | `Редактирай` |
| Ready | `Финализирай` | `Редактирай` |

`Подготвя се чернова…` while generating; `Опитай отново` after a genuine
retryable generation failure. A readiness blocker and a generation failure stay
different things, with different actions, from backend authority only.

The finalized view carries one plain sentence:
`Статията е финализирана в редакционната система.` No publishing control
anywhere; `Публикувай` does not exist in this product.

---

## 3. Bugs found and fixed while proving it

1. **Nested `<main>` landmark.** The writing column was a second `main` inside
   the shell's `main`. Caught by a Playwright strict-mode violation, fixed by
   making it a labelled `<section>`.
2. **The title was printed twice** on Preparation (heading + «Работно заглавие»
   card) and twice on a read-only Draft (header + body heading). Both removed;
   the title now exists in exactly one place per screen.
3. **Two autosave owners** across the Preparation → Draft transition (described
   above). One hook now serves the whole page.
4. **A missing save status** in manual continuation, found by the pre-existing
   D2A browser test. Restored, with the status sourced from the one autosave.
5. **A section heading that collided with a forbidden state word** — caught by
   the new §31 test, not by a human.

---

## 4. Tests

### Frontend — 212 passed (6 files)

`frontend/src/test/articleDesk.test.tsx` is new and carries the G3 contract in
20 tests across §35/§36/§37. Most assertions are negative on purpose: the page
must not grow a second body control, a second title field, a second writer, a
manual Save, a fake state, or publishing vocabulary.

Pre-existing expectations were updated only where G3 deliberately changed the
product contract:

| Was | Now | Why |
| --- | --- | --- |
| `Факти, източници и липсваща информация` (closed disclosure) | `Факти и източници` (open, collapsible rail) | §17, §19 |
| `Редакционен фокус` heading on a Draft | `Фокус` collapsed block | §12 |
| `Предупреждения` panel | `Какво да прегледаш` | §20, §31 |
| `Запазване…` | `Запазва се…` | §8 wording |
| `Черновата се създава…` | `Подготвя се чернова…` | §23 wording |

`typecheck` and `lint` are clean.

### Browser — 6/6 new proofs, real Chromium, real server, isolated stores

`tests/browser/test_v12_g3_article_desk.py`, against the Python-served
production bundle over the real `/api/v1`:

- **§38 preparation fast path** — open, Focus already filled, editor touches
  nothing, clicks `Направи чернова`, a non-empty Draft appears. *This is the
  proof the slice exists for.*
- **§39 alternative Focus** — one click, one `PUT /focus`, no confirm step,
  then Draft.
- **§40 research from the Article** — the canonical `POST /stories/:id/research`
  is issued; no `Направи чернова` and no unearned `Редактирай`; the generic
  `Проучването не можа да завърши` is absent.
- **§41 writing** — realistic ~700-word Bulgarian draft, one editor, measured
  measure/height/line-height, autosave on the wire, reload preserves the text,
  and collapsing the rail measurably widens the writing surface.
- **§42 Ready → Finalize** — lands in the real Archive view, the Article leaves
  the active state, no publishing vocabulary in either place.
- **§43 screenshots** — the six owner-review artifacts.

### Regression

`tests/browser/test_d2a_articles.py` — 9/9. Frontend — 212/212.

Pre-existing failures elsewhere in the repository were confirmed pre-existing by
running the identical subsets on a stashed clean tree: the failure sets are
byte-identical (`diff` → identical). They are environment-bound (search
provider, CLI) and untouched by G3.

---

## 5. Screenshots

`var/g3_screenshots/` — 1440×1080 unless noted, realistic Bulgarian content, no
lorem ipsum:

```
a-article-preparation-1440x1080.png   the launchpad: Focus, alternatives, one action
b-article-draft-1440x1080.png         the writing desk, rail open
c-article-draft-evidence-open-1440x1080.png
d-article-draft-warning-1440x1080.png warnings beside the decision
e-article-ready-1440x1080.png         calm, one forward action
f-article-draft-1280x900.png          the narrow laptop width
```

The `d-article-draft-warning` screenshot shows a **real** warning raised by the
production C4 validation engine about real text: the fixture plants one sentence
("Според неофициален източник реалната стойност…") with no support in the
evidence basis, and the engine finds it. No warning row is fabricated.

### Visual self-review (§44)

1. **Does Preparation feel like a launchpad?** Yes. One screen, one decision.
2. **Can the editor reach a Draft without touching the Focus?** Yes — proven in a
   real browser, zero Focus interaction.
3. **Does the text dominate?** Yes. The writing column is the largest element and
   the rail is a small tinted block.
4. **Can evidence be consulted without competing?** Yes, and the rail collapses.
5. **Is the next action obvious in every state?** Yes — one filled button.
6. **Same product as Today and Story?** Yes — same shell, type scale, warm canvas,
   petrol accent, thin dividers.
7. **Could an editor write 30 minutes here?** Yes. One control, no chrome, an
   autosave that never demands attention, and a title that does not trap the
   focus ring.

Honest limitations: the title input cannot wrap, so a very long headline scrolls
inside its field; and the Draft stays read-only until `Редактирай` is pressed,
which is the pre-existing C/V1.1-C contract that G3 deliberately preserved rather
than changed.

---

## 6. Runtime-store integrity

`var/g3_baseline/pre.sha256` (589 files) taken before any work. After the G3
browser proofs:

```
diff → IDENTICAL
```

The G3 proofs write nothing to the real stores. The research-from-Article proof
uses the suite's existing operational-outage substitute, which performs no real
search, so it records no search-run ledger.

A full-suite run does add `var/editorial_workflow/search_runs/run-*.json`, but
those come from the *other* research suites: `search.SEARCH_RUNS_DIR` is a
module-level constant pinned to the repository, so it ignores store
configuration entirely. That is a pre-existing leak — the clean-tree baseline
produces it too — and it is left alone here, because fixing it means changing
product code that §45 puts out of scope. Flagged for the next slice.

No real Article was created during any proof. Every browser test used an
isolated store root, enforced by the existing session-scoped autouse manifest
gate.

---

## 7. Explicitly untouched

- Research quality algorithms and corroboration rules
- Serper benchmarking — no credits spent
- Evidence safety rules (`WRONG` / `CHROME` promotion)
- Story identity and grouping
- Ranking, sorting and categories
- Source management — **not** started; that is G4
- Manual topic intake (`+ Нова тема`) — **not** started; that is G5
- Publishing / CMS — does not exist and was not added
- The frozen three Article states
- Autosave persistence semantics

## 8. Next

`V1.2-G4 — Settings / Sources: minimal editor management`, then
`V1.2-G5 — + Нова тема → Research → Article`.
