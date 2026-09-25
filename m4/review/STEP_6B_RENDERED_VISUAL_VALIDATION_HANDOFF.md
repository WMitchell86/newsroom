# Step 6B — Rendered Visual Validation Handoff

**Purpose:** handoff for a rendering-capable design tool to produce the final visual proof of the already-approved Editorial Desk direction.

**Status:** design-only; no rendered validation has been performed in the current harness.

**Source of truth:**

- `m4/review/EDITOR_VOCABULARY_V0_1.md`
- `m4/review/INFORMATION_ARCHITECTURE_V0_1.md`
- `m4/review/EDITOR_WORKFLOWS_V0_1.md`
- `m4/review/EDITOR_WIREFRAMES_V0_1.md`

This document does not change product structure, vocabulary, workflows, navigation, Article states, actions, low-fidelity layouts, information hierarchy, or the selected Editorial Desk direction.

## 1. Render objective

Create exactly four static desktop renders:

1. `Днес`
2. `Story Workspace`
3. `Article Workspace — Чернова / Noto Sans Draft body`
4. `Article Workspace — Чернова / Noto Serif Draft body`

The two Article variants must be identical except for the Draft body font family.

## 2. Environment limitation

The current harness does not provide an image-generation, browser-rendering, screenshot, or artifact-attachment mechanism. A further text-only mockup would not add visual evidence.

A rendering-capable tool must use this document as its implementation brief and return the four rendered artifacts for owner review.

## 3. Frozen visual principles

Do not reinterpret or redesign these decisions:

- Editorial Desk visual character;
- warm neutral base;
- top application navigation;
- medium editorial density;
- typography-led hierarchy;
- minimal cards;
- selective rules and whitespace;
- newsroom-note Facts/Sources;
- Draft-first Article Workspace;
- compact state markers;
- restrained petrol accent;
- one primary action per decision context;
- passive autosave feedback;
- no AI-branded visual language;
- minimal radius;
- essentially no decorative shadows.

Forbidden:

- gradients;
- sparkles;
- chat UI;
- copilot branding;
- purple AI aesthetic;
- glowing controls;
- excessive pills;
- card feed;
- dashboard widgets;
- left navigation rail;
- AI persona or assistant branding.

## 4. Provisional values to validate

These values are candidates, not frozen design tokens:

- Noto Serif for Story/Article headings;
- Noto Sans for UI, navigation, metadata, and evidence;
- Noto Sans as preferred Draft-body candidate;
- Noto Serif as the controlled Draft-body comparison;
- warm canvas around `#F6F4EF`;
- primary surface around `#FFFDF8`;
- petrol accent around `#294E54`;
- Article layout around 76% Draft / 24% evidence;
- evidence rail around 300px;
- spacing and type sizes from Step 6.

Do not replace these with a new design system. Render and test them.

## 5. Viewport and output

```text
Viewport: 1440 × 1080 px
Output: PNG, 2× scale where possible
Color mode: sRGB
Safe content margin: 72–80px
Background: full viewport
No browser chrome
No device frame
No mobile variant
```

Actual `Noto Sans` and `Noto Serif` fonts must be loaded with Bulgarian Cyrillic support. If the rendering tool cannot load them correctly, stop rather than substitute another font.

## 6. Candidate typography

### Shared across all artifacts

```text
UI/navigation:       Noto Sans
Metadata:            Noto Sans
Evidence:            Noto Sans
Story title:         Noto Serif
Article title:       Noto Serif
```

### Draft-body comparison

```text
Variant 3: Draft body in Noto Sans
Variant 4: Draft body in Noto Serif
```

Story and Article titles remain Noto Serif in both Article variants.

### Candidate scale

| Role | Candidate |
|---|---|
| Story title | Noto Serif 34/40, weight 600 |
| Article title | Noto Serif 32/38, weight 600 |
| Page title | Noto Sans 26/32, weight 600 |
| Section label | Noto Sans 12/16, weight 600, uppercase |
| Summary | Noto Sans 16/24 |
| Draft Sans | Noto Sans 17/27 |
| Draft Serif | Noto Serif 18/29 |
| Evidence | Noto Sans 13/20 |
| Metadata | Noto Sans 12/17 |
| Actions | Noto Sans 14/20, weight 600 |

The two Draft variants must retain the same visible measure and layout geometry.

## 7. Candidate palette

| Function | Candidate |
|---|---|
| Application background | `#F6F4EF` |
| Primary content surface | `#FFFDF8` |
| Evidence surface | `#F0EEE8` |
| Primary text | `#20211E` |
| Secondary text | `#68665F` |
| Petrol accent | `#294E54` |
| Petrol hover/state | `#1F3F44` |
| Ready/success | `#3F6B4F` |
| Non-blocking warning | `#9A681F` |
| Blocking/error | `#963B33` |
| Default border | `#D8D3C8` |
| Light border | `#E7E2D8` |
| Selected surface | `#E5ECE8` |
| Warning surface | `#F5EBD8` |
| Error surface | `#F4E2DF` |

Use no pure black, no saturated semantic colors, and no decorative gradients.

## 8. Geometry and density

### Global

```text
Top navigation height: 64px
Outer content margin: 72–80px
Maximum content width: 1180–1272px
```

### `Днес`

```text
Content width: 1180px
Major section gap: 40px
Independent item separator: 1px low-contrast rule
No cards
```

### Story Workspace

```text
Content width: 1080px
Title measure: max 920px
New Development left rule: 3px
Fact-note left indent: 24px
Major section gap: 40px
```

### Article Workspace

```text
Total work area: 1272px
Draft column: 940px
Column gap: 32px
Evidence rail: 300px
Approx. ratio: 76% Draft / 24% evidence
Evidence surface: #F0EEE8
Evidence default: visible
Evidence must remain collapsible in the design intent
```

The evidence rail must not divide attention equally with the Draft.

### Spacing, borders, radius

```text
Micro spacing:         4px
Compact metadata:      8px
Control internals:    12px
Local content:        16px
Standard block:       24px
Major separation:     40px

Default border:        1px
Editorial rule:        3px
Radius:                4–6px maximum
Shadow:                none or almost imperceptible
```

Rules are allowed only where they materially improve scanning. Do not place a rule between every section.

## 9. Shared top navigation

All four renders must use:

```text
Chernomorie.bg / Newsroom
Днес
Истории
Статии
Архив
Настройки
```

Use a compact application-navigation treatment:

- subtle active underline or quiet filled surface;
- no marketing CTA;
- no large logo treatment;
- no left rail;
- no extra navigation destination.

## 10. Shared realistic Bulgarian content

### Story title

```text
Общинският съвет отложи ремонта на булевард „Свобода“ за октомври
```

### Current Story summary

```text
Общинският съвет отложи започването на ремонта на булевард „Свобода“
и предвиди срок за приключване на 20 октомври. За временното затваряне
на булеварда са отделени 420 000 лева от предходните предвиждания
за подобряване на градската транспортна инфраструктура.
```

### New Development

```text
Общинският съвет утвърди допълнителни средства и нов краен срок.
Най-важното е, че ремонтът няма да започне преди приключването
на временната организация на движението по булеварда.
```

Metadata:

```text
Днес, 10:42
Публикация: „Отложеният ремонт на булевард „Свобода“ ще струва още
420 000 лева“ — Официален портал на Общинския съвет
```

### Facts and Sources

```text
Съветът е отпуснал 420 000 лева за ремонта и временната организация
на транспортния трафик.
Официално решение на Общинския съвет · 24 септември
```

```text
Булевардът ще остане затворен за автомобили до приключването на ремонта.
Официален портал на Общинския съвет · днес, 10:31
```

```text
Движението по съседните улици ще се пренасочи по временна маршрутна схема.
БНР · днес, 10:36
```

### What is missing

```text
Не е потвърдено точно на коя дата ще започне ремонтът. Решението определя
краен срок, но не конкретна начална дата след приключването на временната
организация на движението.
```

### Related Article

```text
Ремонтът на булевард „Свобода“ ще започне през октомври
Чернова
```

### Editorial Focus

```text
Ще разкажем защо ремонтът е отложен, какво е отделено за него и какво
остава неясно за началната дата на строителните дейности.
```

### Draft title

```text
Ремонтът на булевард „Свобода“ ще започне през октомври
```

### Draft paragraphs

```text
Общинският съвет отложи ремонта на булевард „Свобода“ и предвиди срок
за приключване до 20 октомври. За работата са отделени 420 000 лева
от средствата, предвидени за подобряване на градската транспортна
инфраструктура.
```

```text
Булевардът ще остане затворен за автомобили, докато автобусните линии
се пренасочат по временна маршрутна схема.
```

```text
Според проекта ремонтът трябва да започне на 12 октомври.
```

```text
Промените в организацията на транспорта ще се публикуват отново след
стартирането на строителните дейности.
```

### Non-blocking warning

```text
Проверете твърдението

Наличните източници определят краен срок, но не потвърждават
12 октомври като начална дата.
```

### Supporting evidence

```text
Отделени са 420 000 лева.
Официално решение на Общинския съвет
```

```text
Краен срок: 20 октомври.
Официален портал на Общинския съвет
```

```text
Временна маршрутна схема.
БНР
```


## 11. Artifact requirements

### Artifact 1 — `Днес`

Include:

- New Development with `2 нови развития`;
- New Story:
  ```text
  Община Поморие отвори център за подкрепа на семействата с деца с диабет
  ```
- Draft Article:
  ```text
  Ремонтът на булевард „Свобода“ ще започне през октомври
  ```
- Ready Article:
  ```text
  Общинският съвет увеличи бюджета за обслужване на детските градини в Слънчево
  ```
- one quiet operational problem:
  ```text
  Официалната страница на транспортната програма не можа да бъде заредена.
  Липсва потвърждение за промяната в маршрута 12.
  ```

Use only:

- `Обнови`
- `Прегледай`
- `Редактирай`
- `Финализирай`

Do not show article inventory, statistics or a card feed.

### Artifact 2 — Story Workspace

Include:

- title;
- `Прегледана`;
- `Следена`;
- primary action area;
- `Какво се случи`;
- New Development;
- Facts and Sources;
- `Какво липсва`;
- `Проучи още`;
- related Article;
- collapsed Publications;
- collapsed chronology;
- tertiary `Коригирай групирането`.

Action hierarchy:

- `Прегледай` is the current primary decision;
- `Започни статия` is a secondary alternative;
- `Следи` / `Игнорирай` are quiet context actions;
- `Проучи още` becomes primary only in the missing-information context.

### Artifacts 3 and 4 — Article Workspace variants

Both must show:

- Article title;
- `Чернова`;
- related Story;
- Editorial Focus;
- Draft editor;
- autosave feedback;
- non-blocking warning;
- supporting evidence;
- action hierarchy.

Required initial action state:

```text
Primary: Редактирай
Secondary: Отбележи като готова
Tertiary: Промени фокуса
Autosave: Запазено
```

The render must make it clear that after reviewing the current Draft version,
`Отбележи като готова` becomes primary and `Редактирай` becomes secondary.

Do not show both actions with equal visual weight.

## 12. What the render must test

### Typography

- Bulgarian Cyrillic quality;
- Noto Serif title character;
- Noto Serif versus Noto Sans Draft body;
- reading versus editing comfort;
- visual fatigue;
- distinction between prose and metadata.

### Layout

- title dominance;
- Draft dominance;
- evidence rail width;
- evidence rail default visibility;
- competition between Draft and warning;
- scanability of `Днес`;
- Story secondary-content density.

### Color

- whether the warm canvas feels modern;
- whether the petrol accent is restrained enough;
- semantic warning prominence;
- border and evidence-surface contrast.

### Product character

- application navigation rather than marketing header;
- newsroom software rather than AI SaaS;
- editorial judgment rather than operational telemetry;
- serious, calm and trustworthy tone.

## 13. Review questions

After receiving the four renders, the owner should classify each item as
`FREEZE` or `ADJUST`:

- heading typography;
- Draft body Sans versus Serif;
- palette;
- type scale;
- density;
- evidence rail width;
- evidence rail default visibility;
- warning styling;
- action styling;
- border/radius treatment.

Do not introduce new product decisions during this review.

## 14. Current decision state

The approved visual principles are already frozen. The following remain
provisional until rendered comparison:

- Draft body font;
- exact palette values;
- exact type scale;
- 300px evidence rail;
- evidence default visibility;
- exact spacing;
- border and radius values.

## 15. Repository boundary

This handoff is documentation only. It is not production HTML/CSS, a React
component, an API contract, a route, or a backend change. No rendered artifact
was created in the current harness.
