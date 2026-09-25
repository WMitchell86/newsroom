# Editor Visual System v0.1 — frozen

**Date:** 2026-09-24
**Status:** owner-approved Step 7 UX + visual system freeze; specification only
**Direction:** `Editorial Desk`
**Scope:** implementation-ready V1 UX/visual contract for `chernomorie-bg.com`

## 1. Authority and boundary

This document consolidates the approved UX and visual decisions. It is
subordinate to:

- `m4/review/EDITOR_VOCABULARY_V0_1.md`
- `m4/review/INFORMATION_ARCHITECTURE_V0_1.md`
- `m4/review/EDITOR_WORKFLOWS_V0_1.md`
- `m4/review/EDITOR_WIREFRAMES_V0_1.md`
- `m4/review/STEP_6B_RENDERED_VISUAL_VALIDATION_HANDOFF.md`

It defines no frontend architecture, component structure, API, route, backend,
storage, test, or runtime implementation. Those require a separately approved
Implementation Architecture phase.

## 2. Frozen product invariants

The visual system must preserve:

```text
Днес / Истории / Статии / Архив / Настройки
```

- Exactly five primary areas.
- `История` remains what is happening; `Статия` remains newsroom production.
- Exactly three editor-facing Article states: `Подготовка / Чернова / Готова`.
- Frozen editor vocabulary and actions.
- `Днес` remains a derived attention view and owns no state.
- Publications have no independent editor-facing review lifecycle.
- Research remains inside Story and has no separate center or state.
- Finalization is not publication.
- Idea, EvidencePacket, Prepared, Case, model/provider, lineage, and backend IDs
  remain invisible to the editor.
- No sixth area, new object, new state, workflow, or action is introduced.

## 3. Visual direction: Editorial Desk

### Frozen character

- warm neutral application canvas;
- top application navigation;
- restrained petrol accent;
- typography-led hierarchy;
- minimal cards;
- medium editorial density;
- restrained rules plus whitespace;
- newsroom-note Facts/Sources;
- severity-scaled warnings;
- Draft-first Article Workspace;
- compact state markers only where useful;
- AI visually subordinate and infrastructure-only;
- essentially no decorative shadows;
- small radii only.

### Forbidden

- AI purple;
- gradients;
- glow;
- sparkle or copilot treatment;
- chat-like assistant UI;
- left navigation rail;
- card-feed layouts;
- dashboard widgets;
- excessive pills or badge stacks;
- enterprise-control-panel language;
- AI persona or generated-content branding.

AI provenance, when required by an approved workflow, is quiet metadata. It is
not a visual identity or primary interface element.

## 4. Typography freeze

### Editorial headings

Use `Noto Serif` for:

- Story titles;
- Article titles;
- major editorial headline treatment.

### Working and UI typography

Use `Noto Sans` for:

- Draft body;
- navigation and UI;
- metadata;
- buttons and actions;
- evidence;
- warnings;
- summaries;
- forms.

The Draft body is `Noto Sans`. The product is an editing workspace, not a
publication reading surface. Editorial identity remains in the serif heading
hierarchy.

### V1 default type scale

| Role | Default |
|---|---|
| Story title | Noto Serif 34/40, weight 600 |
| Article title | Noto Serif 32/38, weight 600 |
| Page title | Noto Sans 26/32, weight 600 |
| Section label | Noto Sans 12/16, weight 600, uppercase |
| Summary | Noto Sans 16/24 |
| Draft body | Noto Sans 17/27 |
| Evidence | Noto Sans 13/20 |
| Metadata | Noto Sans 12/17 |
| Actions | Noto Sans 14/20, weight 600 |

These defaults implement the rendered validation. They do not authorize a
new font family or a second visual direction.

## 5. Color system freeze

| Function | V1 value |
|---|---|
| Application background | `#F6F4EF` |
| Primary surface | `#FFFDF8` |
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

These are functional colors. No decorative palette family is added. Pure
black, saturated semantic colors, gradients, glow, and AI purple are not part
of V1.

## 6. Desktop layout freeze

### Reference viewport

```text
Reference viewport: 1440 × 1080px
Desktop-first:      yes
Mobile design:      out of scope
```

### Top navigation

```text
Height: 64px
Areas:  Днес / Истории / Статии / Архив / Настройки
```

Navigation is a compact application header, not a marketing masthead. There
is no left rail.

### Page widths

| Surface | V1 guidance |
|---|---|
| `Днес` | approximately 1180px content width |
| Story Workspace | approximately 1080px readable width |
| Article Workspace | approximately 1272px working width |

Outer page margin guidance is approximately 72–80px at the reference
viewport.

### Article Workspace geometry

```text
Draft/editorial region: approximately 940px
Gap:                    approximately 32px
Evidence region:        approximately 300px
Approximate split:      76% / 24%
```

Evidence is secondary and must support collapse/hide behavior. The reference
desktop layout shows it, but it must never achieve equal visual weight with the
Draft.

## 7. Spacing freeze

```text
4px   micro spacing
8px   compact metadata
12px  controls
16px  local spacing
24px  standard block
32px  strong internal separation
40px  major section separation
48px  rare page-level separation
```

The rhythm creates medium editorial density. These values are implementation
defaults, not separate product concepts.

## 8. Borders, radii, and shadows

```text
Standard border:       1px
Editorial/semantic:    3px
Maximum radius:        approximately 4–6px
Shadow:                none or almost imperceptible
```

Horizontal rules are functional. Use them where they materially improve
scanning; do not place a separator between every section. Prefer spacing and
typography when they are sufficient.

## 9. Action hierarchy freeze

### Primary

One clear current editorial action per decision context.

- solid petrol surface;
- strongest action contrast on the screen;
- never more than one primary in the same decision region.

### Secondary

A genuine alternative within the current context.

- quiet outline or restrained surface treatment;
- readable without competing with the primary action.

### Tertiary

Contextual navigation or exceptional action.

- text-link treatment;
- used for low-priority navigation, disclosure, or exception tools.

Destructive semantics use red only when truly destructive. Several
equal-weight primary actions in one decision region are forbidden.

Frozen examples include `Прегледай`, `Проучи още`, `Направи чернова`,
`Редактирай`, `Отбележи като готова`, and `Финализирай` according to their
existing workflow context. The visual system adds no action.

## 10. Status system freeze

Use compact visual status treatment only for meaningful state:

- `Ново развитие`;
- `Следена`;
- `Подготовка`;
- `Чернова`;
- `Готова`.

Rules:

- do not badge every source;
- do not badge every timestamp;
- do not badge every metadata field;
- do not create badge stacks;
- do not turn a status marker into a new destination.

Status is communicated by restrained text, marker, rule, or selected surface
according to context. `Следена` is bookmark context, not a lifecycle state.

## 11. Facts and Sources freeze

`Факти и източници` use newsroom-note treatment:

- no card per fact;
- quieter typography than main editorial prose;
- subtle indentation;
- narrow rule when useful;
- strong source name;
- quiet supporting metadata;
- expandable provenance.

Main editorial content always remains visually stronger. Evidence supports
editorial judgment; it does not become a telemetry or monitoring panel.

## 12. Warning system freeze

### Informational

Quiet neutral or petrol treatment. No alarm-state UI.

### Non-blocking warning

Muted amber using the frozen warning values. It appears near the affected
content, explains what needs attention, and does not create an alarm dashboard
or workflow state.

### Blocking factual or safety issue

Stronger restrained red treatment with clear consequence and required action.
Avoid page-wide error states unless existing backend safety behavior genuinely
requires them.

Warnings do not become Article states. Existing backend safety and blocking
contracts remain authoritative.

## 13. Autosave and failure feedback

### Autosave

Use passive feedback only:

```text
Запазване…
Запазено
```

There is no `Запази` action. `Редактирай` means working on the text.

### Source or AI failure

Show the problem at the point where it affects work:

- what failed;
- what could not be completed;
- what work is preserved;
- what path is available next.

Technical detail belongs in Settings. Normal editorial UI does not expose
provider routes, model roles, request accounting, internal error classes, or
logs. Failures create no new editorial state.

## 14. Centerpiece screen character

### `Днес`

An editorial attention desk:

- not a dashboard;
- not a task board;
- not a notification feed;
- not a card feed;
- not an Article inventory.

It surfaces only Stories, Articles, or genuine problems with a concrete next
action. `Обнови` remains a quiet utility action.

### Story Workspace

An editorial understanding and decision surface:

- Story title is the dominant typographic anchor;
- New Development is the strongest secondary editorial element;
- Facts and Sources are inspectable but quieter;
- `Какво липсва` is distinct from an application error;
- Publications and chronology remain secondary;
- grouping correction remains tertiary and exceptional.

### Article Workspace

A Draft-first editing surface:

- Draft dominates the visual field;
- Editorial Focus is quiet contextual guidance;
- evidence is secondary and collapsible;
- warnings are local;
- autosave is passive;
- `Отбележи като готова` and `Финализирай` remain separate.

The three frozen Article states continue to use the same workspace with
state-appropriate content and actions; this visual freeze does not create
additional Article views or states.


## 15. Supporting screens

The frozen supporting surfaces inherit this system without structural redesign:

- `Истории` list;
- `Статии` list;
- `Архив`;
- `Настройки` landing.

They use the same typography, palette, density, spacing, list treatment,
status treatment, and action hierarchy. They remain navigation surfaces, not
management dashboards or workspaces.

Their frozen search, filter, ordering, navigation, and ownership contracts in
`EDITOR_WIREFRAMES_V0_1.md` remain unchanged.

## 16. Responsive scope

V1 is desktop-first at the frozen reference geometry. Responsive behavior may
be designed separately after desktop implementation has proven stable. This
document does not define mobile layouts, breakpoints, or mobile navigation.

## 17. Explicit visual exclusions

No:

- left rail;
- gradient;
- glow;
- sparkle or copilot treatment;
- AI purple;
- chat surface;
- card-feed layout;
- dashboard widget;
- enterprise-control-panel treatment;
- excessive pills;
- decorative shadows;
- large radii;
- serif-everywhere treatment;
- rule between every section;
- equal-weight evidence and Draft;
- new product terminology, state, workflow, action, or screen.

## 18. Final consistency gate

This specification preserves:

- exactly five primary areas;
- exactly three Article states;
- frozen editor vocabulary;
- frozen workflows and action vocabulary;
- `История`/`Статия` ownership;
- `Днес` as derived attention view;
- no raw Publications queue;
- no Research center;
- no publishing workflow;
- no Cases, Ideas, EvidencePackets, Prepared, model roles, or backend IDs
  exposed to the editor;
- AI as supporting infrastructure only;
- desktop-first V1 scope;
- no new product concept.

## 19. Gate to Implementation Architecture

This is a specification-only freeze. After owner review and approval of the
documentation diff, the next project phase is `IMPLEMENTATION ARCHITECTURE`.

That future phase may define the target frontend architecture, JSON API
boundary, Vite/React/TypeScript migration plan, mapping of existing backend
behavior to the frozen UX, and implementation sequencing.

No frontend, backend, route, storage, API, test, or runtime implementation is
authorized by this document.
