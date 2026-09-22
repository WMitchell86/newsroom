# Workbench UX/UI Review — 2026-09-21

Reviewed: all 5 live pages (homepage, /sources, /inbox, /stories, /models) via
captured HTML from `http://127.0.0.1:8123/`. The `.env` was loaded; Gemini
routes show "✓ готов".

---

## Severity classification

- **P0 — broken / unusable**: blocks a non-technical editor from working
- **P1 — poor UX**: makes daily use annoying or confusing
- **P2 — polish**: noticeable but not blocking

---

## P0 — Must fix before any editor touch

### 1. Homepage lands on the frozen M3A "Случаи" page, not the newsroom

The root `/` renders the M3A case-editing queue (LIVE + WFX-01…10). An M4
newsroom editor opens the Workbench and sees a page about old case files they
don't use. The nav links "Истории" / "Материали" are buried in the header with
no visual emphasis.

**Fix:** `/` should redirect to `/inbox` (or `/stories`), the actual daily
entry point. The Случаи page should be accessible via nav but not the default.

### 2. Every page loads ~5 KB of duplicate inline CSS in `<head>`

Every single page includes the entire stylesheet as a `<style>` block in
`<head>`. For 5 pages this means 5× the CSS is parsed. The /models page alone
is 58 KB of HTML, most of it repeated form boilerplate.

**Fix:** Extract CSS to a shared `/static/style.css` and reference it with
`<link rel="stylesheet" href="/static/style.css">`. This is a one-file change
in `html.py` and a new route in `http.py`.

### 3. No confirmation on destructive actions

Clicking "премахни" (remove) on a model route, source, or blocked domain
executes immediately with no confirmation dialog. A misclick deletes a
production model route from the policy.

**Fix:** Add `<button onclick="return confirm('Наистина ли?')"` to all
`.btn.danger` buttons. This is a 1-line CSS/JS addition.

### 4. "Добави модел" label says "provider:model" but the form has two separate fields

The label reads `Добави модел (provider:model):` but the form renders two
separate `<input>` fields (provider + model). This is confusing — the editor
doesn't know if they should type "gemini:gemini-3.8-flash" into one field or
fill both.

**Fix:** Change the label to `Добави модел:` or `Provider / Model:` and add
separate placeholder text (`provider` → "gemini", `model` → "gemini-3.8-flash").

---

## P1 — Poor UX, fix soon

### 5. /models page is 58 KB — every route generates 4 separate `<form>` elements

Each model route row has 4 forms (↑, ↓, изключи, премахни), each with 4–6
hidden inputs. For a role with 7 routes, that's 28 forms × ~5 hidden inputs
= 140 hidden inputs. The page is mostly invisible form scaffolding.

**Fix:** Use a single form per role with `<select name="action">` + radio
buttons for route index, or use JavaScript to build the POST body from
clicks. This is the single biggest page-size win.

### 6. Navigation has no visual hierarchy

The nav is pipe-separated links (`Истории | Материали | Източници | ...`) with
the active page indicated only by `font-weight:700` and white color on a
blue header. There's no underline, no background, no tab shape. On a
low-quality monitor the current page is hard to spot.

**Fix:** Add a bottom border or background highlight to the active nav item.
Example: `.nav-active { border-bottom: 2px solid #fff; }`.

### 7. Empty states are unhelpful

`/inbox`: "Няма елементи за този филтър. Пуснете «Събери новините сега»"
`/stories`: "Няма истории за този филтър. Пуснете «Обнови историите»"
`/sources`: "Още няма източници. Добавете първия по-долу."

These are text-only, no visual cue (icon, illustration, prominent button).
A non-technical editor sees a blank page with small gray text.

**Fix:** Render the primary action button prominently inside the empty-state
message, not buried in a separate section below.

### 8. Form inputs have no styling

All `<input>`, `<select>`, and `<textarea>` elements render with browser
defaults — no padding, no border-radius, no focus state. On the /sources
"Добави източник" form (10+ fields), the fields are visually cramped.

**Fix:** Add basic input styling to the shared CSS:
```css
input[type=text], select, textarea {
  padding: .4rem .6rem; border: 1px solid var(--line);
  border-radius: .3rem; font-size: .92rem;
}
input[type=text]:focus, select:focus, textarea:focus {
  outline: 2px solid var(--accent); border-color: var(--accent);
}
```

### 9. Icon-only buttons (↑ ↓) are too small and ambiguous

The reorder buttons render as tiny `↑` and `↓` text buttons. No tooltip, no
aria-label. An editor doesn't know what they do without hovering.

**Fix:** Add `title="Премести нагоре"` / `title="Премести надолу"` attributes,
and increase button padding.

### 10. No loading/feedback on form submission

Clicking "Събери новините сега" submits a POST and the browser navigates
to `/inbox?message=...` after the collection completes. During collection
(which hits the network), the browser shows a blank white page with no
spinner, no progress, nothing. An editor may click again or think it crashed.

**Fix:** Add a simple `<meta http-equiv="refresh">` intermediate page or a
client-side "Събиране..." overlay. Even a "Моля, изчакайте..." text page
is better than blank.

### 11. "M4" version tag in the header is meaningless to editors

The header reads `Редакторски работен плот M4`. An editor doesn't know
what M4 means.

**Fix:** Remove the version tag or replace with the date of last update.

---

## P2 — Polish

### 12. /models shows raw file paths and policy hashes

`Политика: /home/test/media/var/model_policy.json (по подразбиране) · ден
2026-09-21 · версия 9d258f6c67cd`

This is developer debugging info, not editor-facing.

**Fix:** Show only "Политика: по подразбиране · ден 2026-09-21" and put the
path + hash in a `<details>` collapsible.

### 13. /sources "Добави източник" form is 10+ fields vertically stacked

The form has: source_id, name, kind, collector, domain, url, query, priority,
cadence, note, calendar checkbox, monitoring_only checkbox. This is
intimidating for a first-time user.

**Fix:** Group into sections: "Основно" (id, name, kind, collector),
"Адрес" (domain, url, query), "Настройки" (priority, cadence, flags).
Use `<fieldset>` + `<legend>` or visual section dividers.

### 14. Color palette is too muted

The primary accent (`#0b5394`), success (`#15803d`), and warning (`#b45309`)
are all low-saturation. On a standard monitor the page looks "washed out".
The "✓ готов" and "× пропуснат" badges are small and hard to scan.

**Fix:** Increase saturation slightly; make status badges larger with more
padding.

### 15. No responsive design / mobile support

The layout is `max-width: 62rem` with no breakpoints. On a phone or tablet
the tables overflow horizontally and form labels stack poorly.

**Fix:** Add `@media (max-width: 768px)` rules for tables (horizontal scroll
wrapper) and form labels (full-width). Not urgent for a desktop-first
editor tool, but should be noted.

### 16. "Истории" / "Материали" descriptions use technical Bulgarian

Stories page: "История = реално събитие, сглобено от запазените материали.
Откриванията, публикациите и издателите се броят отделно..."
Inbox page: "Това са събрани кандидати, не доказателства и не готови
материали. Нищо тук не е проверено фактологично."

These are accurate but read like developer documentation, not a friendly
editorial tool.

**Fix:** Simplify: "Нови материали от вашите източници" / "Истории,
формирани от материалите"

---

## What works well

- **All pages return 200** — no crashes, no 500 errors.
- **Bulgarian-first UI** — every label, button, message is in Bulgarian.
- **Consistent layout** — header + nav + main is the same on every page.
- **Functional forms** — add/edit/toggle/remove all work via POST + redirect.
- **Badge system** — ok/warn/block badges convey status at a glance.
- **Muted disclaimer** — "Това са събрани кандидати, не доказателства" is
  the right safety message.
- **Source health and cadence** are shown operationally (not just config).

---

## Priority order for fixes

1. Redirect `/` to `/inbox` (P0, 2 lines)
2. Confirmation on destructive buttons (P0, 1 line per button class)
3. Fix "provider:model" label (P0, 1 line)
4. Extract CSS to shared file (P0–P1, ~20 lines)
5. Collapse /models forms into single-form-per-role (P1, biggest page-size win)
6. Add input styling (P1, 5 lines of CSS)
7. Add loading feedback on collect/refresh (P1, intermediate page)
8. Add nav active indicator (P1, 1 CSS rule)

---

## Resolution (2026-09-21, same day — `m4/review/WORKBENCH_UI_OVERHAUL_REPORT.md`)

All P0s and P1s are fixed; P2s 12–16 are fixed. Evidence: live isolated HTTP proof
`ALL CHECKS PASSED`, 914 tests, M3A smoke 25/25.

| Finding | Status | How |
|---|---|---|
| 1. `/` was the frozen queue | **fixed** | `/` = «Начало» daily dashboard; queue moved to `/cases`, old `/?filter=` links still work |
| 2. 5 KB CSS per page | **fixed** | served once at `/static/style.css` (inline kept only as fallback) |
| 3. No confirm on destructive actions | **fixed** | `data-danger` / `data-confirm-route` → `confirm()` |
| 4. `provider:model` label | **fixed** | «Добави нов модел към тази роля» + separate provider/model labels |
| 5. 58 KB `/models` | **fixed** | one manager form per role (op + route select): 58 KB → 27.6 KB |
| 6. Nav has no hierarchy | **fixed** | two nav rows (daily vs «Настройки и архив») + filled active pill |
| 7. Empty states unhelpful | **fixed** | hero card with the 3 steps and the button that performs step 1 |
| 8. No input styling | **fixed** | shared field/select/textarea styling + focus ring |
| 9. Blank screen while collecting | **fixed** | `data-busy` disables the button and shows a «Събиране…» overlay |
| 10. Long POST feedback | **fixed** | same busy overlay (no intermediate page needed) |
| 11. `M4` tag in the header | **fixed** | replaced with the product name + one-line purpose |
| 12. Raw paths/hashes on `/models` | **fixed** | moved into `<details>Технически детайли` |
| 13. 10+ field source form | **fixed** | three fieldsets: Основно · Адрес · Настройки |
| 14. Muted palette, small badges | **fixed** | higher-saturation tokens, larger badges, card shadows |
| 15. No responsive rules | **fixed** | `.table-wrap` scroll containers + `@media (max-width: 768px)` |
| 16. Technical Bulgarian on daily pages | **fixed** | rewritten; the candidate-not-evidence warning is preserved |

Not changed on purpose: the M3A case flow, the finalization guards and the
immutable-draft contract; `/intake`; no new dependency and no JS framework.
