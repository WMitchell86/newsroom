# Editor Wireframes v0.1 — frozen, Rounds 1 and 2

**Date:** 2026-09-24
**Status:** owner-approved Step 4 low-fidelity freeze; specification only
**Scope:** complete V1 UX skeleton: centerpiece and supporting surfaces

## 1. Purpose and authority

This document freezes the complete Step 4 interaction structure. Sections 4–11
preserve the owner-approved Round 1 centerpiece surfaces without redesign.
Round 2 supporting surfaces are added after the fulfilled Round 1 gate. This
document is subordinate to:

- `m4/review/EDITOR_VOCABULARY_V0_1.md`
- `m4/review/INFORMATION_ARCHITECTURE_V0_1.md`
- `m4/review/EDITOR_WORKFLOWS_V0_1.md`

It defines no visual design, components, routes, APIs, backend architecture, or
runtime behavior. Plain text blocks represent information and action hierarchy
only.

Round 1 covers:

1. `Днес`
2. Story Workspace
3. Article Workspace in `Подготовка`, `Чернова`, and `Готова`

The five-area navigation remains:

```text
Днес / Истории / Статии / Архив / Настройки
```

## 2. Resolved interaction decisions

### Multiple New Developments

A followed Story with several unreviewed meaningful developments has one
`Днес` entry. It shows `2 нови развития` or the equivalent count plus the
newest/relevant delta summary. `Днес` is not an event stream.

The Story Workspace shows all unreviewed developments from the last review.
One `Прегледай` completes the current visible development set. `Следи` remains
unchanged.

### Inline research

`Проучи още` executes inline. A temporary loading indication is an interaction
state, not a workflow state. Success updates `Факти и източници` and/or
`Какво липсва` in the same Story. Failure shows a short plain-language message
and leaves the gaps unchanged. There is no research queue, progress center, or
research state.

### Autosave

Draft editing uses autosave. `Запазване…` and `Запазено` are passive interaction
feedback, not editor actions. No `Запази` action is introduced. `Редактирай`
means working on the text, not a separate save lifecycle.

### Reopening a Ready Article

```text
Готова → Редактирай → Чернова
```

The readiness checkpoint is no longer valid when the editor resumes editing.
No confirmation or new action is required.

### Manual continuation after AI failure

Primary remains `Направи чернова` as the retry action. Secondary fallback is
the existing `Редактирай`, which lets the editor begin text manually. When real
text exists:

```text
Подготовка → Чернова
```

No `Напиши ръчно` action, new state, or separate manual workflow is introduced.

## 3. Information hierarchy

For every surface:

- **Primary information** answers what changed, what is known, what is missing,
  or what must happen next.
- **Secondary information** remains available but does not dominate.
- **Exceptional/advanced information** appears only when needed.

Publication details, chronology, provenance, warnings, grouping correction, and
technical failure detail use progressive disclosure. Backend concepts remain
hidden.

## 4. `Днес`

### Purpose

> Какво изисква вниманието ми сега?

`Днес` is a derived attention view. It is not an inventory and owns no state.

### Primary information and action

Each entry shows the owning Story or Article, why it needs attention, and the
concrete next action.

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки          [Обнови]     |
+--------------------------------------------------------------------+

НОВИ РАЗВИТИЯ
| Ново развитие · 2 нови развития                                   |
| Общинският съвет промени графика за консултациите                 |
| Най-ново: срещата е отложена; новата дата още не е потвърдена.    |
| Публикация: Официално съобщение на Общинския съвет                 |
| Последна промяна: днес, 10:42                                      |
| [Прегледай]                                                         |
+--------------------------------------------------------------------+

НОВИ ИСТОРИИ
| Нова история                                                        |
| Хотел в Слънчевото отвори общност за деца в риск                  |
| Кратък фактологичен резюме.                                         |
| Защо е тук: непрегледана нова история.                             |
| [Прегледай]                                                         |
+--------------------------------------------------------------------+

СТАТИИ ЗА ДЕЙСТВИЕ
| „Промените в социалните услуги“ — Чернова                          |
| Защо е тук: чака редакция.                                         |
| [Редактирай]                                                        |
+--------------------------------------------------------------------+
| „Новите правила за паркиране“ — Готова                             |
| Защо е тук: чака финализиране.                                     |
| [Финализирай]                                                       |
+--------------------------------------------------------------------+

ПРОБЛЕМИ
| Официалната публикация не можа да бъде заредена.                   |
| Въздействие: липсва потвърждение за новата дата.                   |
| [Настройки]                                                         |
+--------------------------------------------------------------------+
```

### Progressive disclosure

The delta and next action are primary. Supporting Publication/source context
is secondary. No lifetime statistics, active-object counts, raw Publications,
technical metrics, model/provider health, Cases, or YouTube appear.

### Supported scenarios

Scenarios 1, 3, and the `Днес` entry points from 5 and 6.

## 5. Story Workspace

### Purpose

> Разбирам какво се случва и решавам какво да направя.

Editorial Focus is owned by Article. Story Workspace may show a related
Article and `Редактирай`, but it contains no focus-management action.

### Primary information and action

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

История: „Общинският съвет обяви нови правила за социалните услуги“

Прегледана: да · Следена: да

[Прегледай] [Следи] [Игнорирай] [Започни статия]

КАКВО СЕ СЛУЧИ
Short factual summary and fuller Story context.

НОВО РАЗВИТИЕ
Какво се промени · кога · supporting Publication
При влизане от Днес всички непрегледани developments са видими.

ФАКТИ И ИЗТОЧНИЦИ
Concise supported facts; details collapsed.

КАКВО ЛИПСВА
Missing facts/questions/conflicts.
[Проучи още]
При изпълнение: временно „Проучването тече…“
При неуспех: кратко съобщение; gaps остават непроменени.

СТАТИИ ПО ТАЗИ ИСТОРИЯ
„Новите правила за социалните услуги“ — Чернова
[Редактирай]

ПУБЛИКАЦИИ
[разгъни] Supporting Publications and source context

ХРОНОЛОГИЯ
[разгъни] Earlier Story development

ИЗКЛЮЧЕНИЕ
[Коригирай групирането]
  [Отдели публикация]
  [Обедини с друга история]
+--------------------------------------------------------------------+
```

### Progressive disclosure

Individual Publications, detailed provenance, and chronology start secondary.
The active New Development is visible immediately. Grouping correction is
secondary and never competes with normal editorial actions.

### Supported scenarios

Scenarios 2, 3, 4, 5, and 7A.

## 6. Article Workspace — `Подготовка`

### Purpose

> Подготвям статията и проверявам дали има достатъчно основа за Draft.

### Primary information and action

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

Статия: Подготовка
Работно заглавие: „Промените в социалните услуги“
Свързана История: „Общинският съвет обяви нови правила“

РЕДАКЦИОНЕН ФОКУС
1–3 plain-language sentences.
[Избери фокус / Промени фокуса]

КАКВО ЛИПСВА
Blocking gap and plain-language reason, or no blocking gap.

ФАКТИ И ИЗТОЧНИЦИ
Relevant facts; detail collapsed.

IF blocking gap:
[Проучи още] е primary
[Направи чернова] не е налично

IF no blocking gap and valid focus:
[Направи чернова] е primary

При неуспех на AI:
Направи чернова remains primary retry.
[Редактирай] е secondary fallback за ръчно начало на текста.
+--------------------------------------------------------------------+
```

The focus action is listed once. Draft readiness changes the next action only;
it creates no state.

### Progressive disclosure

Blocking gaps are primary. Non-blocking gaps remain visible but secondary.
Facts and source details are available on demand. Research errors stay in
context.

### Supported scenarios

Scenarios 4, 5, and 7B.


## 7. Article Workspace — `Чернова`

### Purpose

> Редактирам текста и решавам дали е готов за финализиране.

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

Статия: Чернова
„Промените в социалните услуги“
Свързана История: „Общинският съвет обяви нови правила“

РЕДАКЦИОНЕН ФОКУС
Visible short context.
[Промени фокуса]

ЧЕРНОВА
[Editable Article text]
Passive feedback: Запазване… / Запазено

WARNING AT THE AFFECTED TEXT
Unsupported claim + [разгъни] relevant Facts and Sources.

[Редактирай]
[Отбележи като готова]
+--------------------------------------------------------------------+
```

### Interaction rules

- `Редактирай` means working on the text.
- Autosave preserves edits; `Запазено` is not an action.
- Warnings stay at the point where they matter.
- `Отбележи като готова` is available after the current version is reviewed.
- No Case, EvidencePacket, model, provider, route, or lineage information.

### Supported scenarios

Scenarios 1, 6, and 7B.

## 8. Article Workspace — `Готова`

### Purpose

> Преглеждам финалната редакторска версия и решавам дали да я финализирам.

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

Статия: Готова
„Промените в социалните услуги“
Свързана История: „Общинският съвет обяви нови правила“

ФИНАЛЕН ПРЕГЛЕД
[Final review text]

ПРЕДУПРЕЖДЕНИЯ
Remaining non-blocking warnings, if any.
[разгъни] relevant Facts and Sources

[Финализирай]
[Редактирай]

Готова → Редактирай → Чернова

Финализирането означава завършено в системата; не е публикуване.
+--------------------------------------------------------------------+
```

### Progressive disclosure

Final text is primary. Warnings remain visible but do not create a workflow.
Facts and Sources are secondary. Publishing controls are absent.

### Supported scenarios

Scenarios 1 and 6.

## 9. Major transition map

```text
Днес → Story                         Прегледай
Днес → Article in Подготовка        concrete next action
Днес → Article in Чернова            Редактирай
Днес → Article in Готова             Финализирай

Story → Article in Подготовка        Започни статия
Подготовка → Чернова                 Направи чернова
Чернова → Готова                     Отбележи като готова
Готова → Чернова                     Редактирай
Готова → Архив                       Финализирай

Article → related Story              contextual navigation
Story → same Story after research    no new workspace
Failure → Настройки                  only for operator detail/configuration
```

## 10. Progressive disclosure decisions

| Information | Default | Expanded when |
|---|---|---|
| Supporting Publication in `Днес` | concise context | editor verifies delta/support |
| Individual Publications | collapsed | editor inspects original text |
| Detailed facts/provenance | collapsed | editor verifies a claim |
| Current New Development | visible first | entry from `Днес` |
| Earlier chronology | collapsed | editor asks for Story history |
| Grouping correction | secondary | `Коригирай групирането` selected |
| Draft warning | visible at affected text | related evidence inspected |
| Non-blocking gaps | visible but secondary | relevant decision is made |
| Research loading/result/error | inline | action is used |
| Technical failure detail | hidden | operator enters `Настройки` |

## 11. Round 1 consistency gate

- No sixth navigation area.
- No fourth Article state.
- No new normal editor action.
- No raw Publications queue.
- No Research center or research state.
- No Cases, Ideas, EvidencePackets, Prepared, or model internals.
- No analytics/dashboard complexity.
- No publishing workflow.
- No backend architecture change.
- `Промени фокуса` is absent from Story Workspace.
- Autosave feedback is not a new action.

## 12. Round 1 gate — fulfilled by Round 2

Round 1 remains frozen. The approved supporting-screen round below is limited
to:

- `Истории` list
- `Статии` list
- `Архив`
- `Настройки` landing

It defines basic list structure, search/filter entry points, and navigation
into existing surfaces. It does not design Settings subpages, Sources, AI
Models, YouTube, diagnostics, or visual direction.

## 13. Round 2 — `Истории` list

### Purpose

> Намирам история и виждам какво се случва с нея.

`Истории` is a navigation surface into Story Workspace. It is not a second
`Днес` and does not own editorial management actions.

### Minimum list information

- Story title;
- concise current summary;
- latest meaningful change/date;
- `Ново развитие` when relevant;
- followed context;
- compact reviewed/ignored context where useful;
- optional publication/source count only when useful.

The title opens Story Workspace. Row-level `Прегледай`, `Следи`, `Игнорирай`,
`Проучи още`, and `Започни статия` are not duplicated; they remain in Story
Workspace.

### Search and filters

One simple text search may match title, current summary, and known related
terms. Approved filters:

```text
Всички / Следени / Нови развития / Игнорирани
```

`Непрегледани` is not included because immediate unreviewed attention belongs
to `Днес`.

### Low-fidelity structure

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

Истории

Търсене: [........................................................]

Всички · Следени · Нови развития · Игнорирани

----------------------------------------------------------------------
[Общинският съвет обяви нови правила за социалните услуги]
Ново развитие · Следена
Промени в правилата за социалните услуги ще влязат в сила през октомври.
Последна промяна: днес, 10:42
----------------------------------------------------------------------

[Хотел в Слънчевото отвори общност за деца в риск]
Прегледана
Общинският съвет обяви програма за деца в риск.
Последна промяна: днес, 09:15
----------------------------------------------------------------------

[Промените в организацията на ДКМБ]
Игнорирана
Общинският съвет промени състава на управителния съвет.
Последна промяна: 18 септември
----------------------------------------------------------------------
```

### Default ordering and disclosure

Default order is latest meaningful change. No user-controlled sorting is
introduced. Individual Publications, chronology, provenance, and grouping
correction remain in Story Workspace.

### Deliberately hidden

- raw Publications queue or Publication filter;
- row-level Story management controls;
- full chronology and detailed provenance;
- advanced search or saved views;
- analytics, bulk operations, configurable filters, and dashboards.

## 14. Round 2 — `Статии` list

### Purpose

> Намирам активна статия и продължавам работата по нея.

This list contains active Articles only. Finalized Articles belong to
`Архив`.

### Minimum list information

- working/current title;
- related Story;
- exactly one frozen Article state;
- short next-action reason;
- last relevant update when useful;
- contextual entry into Article Workspace.

### Search and filters

One simple text search. Exactly these filters:

```text
Всички / Подготовка / Чернова / Готова
```

Contextual entries:

- `Подготовка` → title link to Article Workspace;
- `Чернова` → `Редактирай`;
- `Готова` → `Финализирай`.

### Low-fidelity structure

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

Статии

Търсене: [........................................................]

Всички · Подготовка · Чернова · Готова

----------------------------------------------------------------------
[Промените в социалните услуги]
История: „Общинският съвет обяви нови правила“
Подготовка
Следваща стъпка: липсва потвърждение дали промените засягат вече
запазени консултации.
Промяна: днес, 11:05

[Промените в социалните услуги] → Article Workspace — Подготовка
----------------------------------------------------------------------

[Новите правила за социалните услуги]
История: „Общинският съвет обяви нови правила“
Чернова
Чака редакция.
Промяна: вчера, 17:20

[Редактирай]
----------------------------------------------------------------------

[Новите правила за паркиране]
История: „Общинският съвет обяви нови правила“
Готова
Чака финализиране.
Промяна: днес, 08:10

[Финализирай]
----------------------------------------------------------------------
```

### Default ordering and disclosure

Default order is latest relevant update. No user-controlled sorting is
introduced. Editorial Focus, Facts and Sources, missing information, warnings,
research, and full text remain in Article Workspace.

### Deliberately hidden

- Idea, EvidencePacket, Prepared, Case, and backend IDs;
- model/provider, generation route, and lineage;
- workflow board or drag-and-drop state change;
- bulk operations;
- warning or research filters;
- additional Article states or analytics.


## 15. Round 2 — `Архив`

### Purpose

> Намирам завършена статия.

`Архив` contains finalized Articles only. It is not Cases, a Story archive, a
CMS history, a knowledge base, analytics, or publishing history.

### Default list information and ordering

- title;
- related Story;
- finalization date.

Default order is newest finalized first. No user-controlled sorting is
introduced. Editorial Focus and a short excerpt are optional secondary context
only when useful.

### Search and filters

One simple text search across finalized Article content. V1 has no filter,
including no date filter.

### Low-fidelity structure

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

Архив
Финализирани статии

Търсене: [........................................................]

----------------------------------------------------------------------
[Общинският съвет прие бюджета за 2027 година]
История: „Общинският съвет прие бюджета за 2027 година“
Финализирана: 24 септември 2026
----------------------------------------------------------------------

[Новите правила за паркиране в централната зона]
История: „Общинският съвет обяви нови правила“
Финализирана: 22 септември 2026
----------------------------------------------------------------------
```

Opening a title leads to a read-only finalized Article view within `Архив`.
It may provide final text, related Story, and relevant Facts and Sources for
traceability. This is not a new Archive Workspace.

### Deliberately excluded

- Cases and general Story archive;
- CMS or publishing history;
- knowledge-management features and analytics;
- author, source, AI/manual, model, topic, and performance filters;
- date filter and manual sorting in V1;
- advanced search.

## 16. Round 2 — `Настройки` landing

### Purpose

> Намирам техническата или оперативната настройка, която ми трябва.

This is navigation only. It is not a Settings dashboard.

### Four entry points

1. `Източници` — configure and inspect newsroom sources.
2. `AI и разходи` — models, quotas, paid/free controls, and cost visibility.
3. `Канали за вход` — ingestion mechanisms such as YouTube.
4. `Система` — diagnostics and technical status.

### Low-fidelity structure

```text
+--------------------------------------------------------------------+
| Днес | Истории | Статии | Архив | Настройки                     |
+--------------------------------------------------------------------+

Настройки

Как работи системата. Тук не се редактира днешната редакционска работа.

----------------------------------------------------------------------
Източници
Настройва и проверява newsroom източниците.
----------------------------------------------------------------------

AI и разходи
Модели, квоти, платени/безплатни настройки и видимост на разходите.
----------------------------------------------------------------------

Канали за вход
Ingestion механизми, включително YouTube.
----------------------------------------------------------------------

Система
Диагностика и техническо състояние.
----------------------------------------------------------------------
```

### Problem indicators

Settings landing has no problem badges or indicators. Actionable problems
belong to `Днес`; technical detail belongs in the relevant Settings subpage.

### Deliberately absent

- metrics tables and operational dashboard;
- provider attempts, request hashes, usage tables, and logs;
- route ordering and model-role summaries;
- source registry forms and ingestion queues;
- fully designed Settings subpages.


## 17. Search, filter, and ordering contract

| Surface | Search | Filters/options | Default ordering |
|---|---|---|---|
| `Истории` | title, summary, related terms | `Всички / Следени / Нови развития /Игнорирани` | latest meaningful change |
| `Статии` | title, related Story, visible text | `Всички / Подготовка / Чернова / Готова` | latest relevant update |
| `Архив` | finalized Article content | none | finalization date, newest first |
| `Настройки` | none | four category links | fixed category order |

No user-controlled sorting controls, advanced filters, saved views, or
configurable layouts are introduced.

## 18. Complete V1 navigation skeleton

```text
Днес
└── attention entries
    ├── Story Workspace
    └── Article Workspace

Истории
└── Stories list
    └── Story Workspace

Статии
└── active Articles list
    └── Article Workspace

Архив
└── finalized Articles list
    └── read-only Финализирана статия

Настройки
└── Settings landing
    ├── Източници
    ├── AI и разходи
    ├── Канали за вход
    └── Система
```

The four Settings destinations are placeholders for later subpage design. They
are not expanded in this freeze.

## 19. Round 2 progressive disclosure and list principle

Stories, Articles, and Archive are navigation surfaces, not management
dashboards. Each row answers only:

- What is this?
- What context or frozen state matters?
- Why might I open it?

Full management stays in the owning workspace. Avoid card overload, multiple
row buttons, bulk management, advanced filtering, configurable views, and
dashboard metrics.

- Stories: detailed Publications, chronology, provenance, and correction stay
  in Story Workspace.
- Articles: Focus, Facts and Sources, gaps, warnings, research, and text stay
  in Article Workspace.
- Archive: excerpt, Focus, and traceability stay secondary to title, Story,
  and finalization date.
- Settings: all operational detail stays in later subpages.

## 20. Final low-fidelity consistency gate

- Exactly five primary areas remain.
- No sixth workspace or primary destination is introduced.
- Exactly three Article states remain.
- No new normal editor action is introduced.
- No raw Publications queue is recreated.
- No separate Research center or state is introduced.
- No knowledge-management Archive is created.
- No Settings dashboard is created.
- No manual intake or publishing workflow is added.
- No backend/API concepts are exposed to the editor.
- No visual-design decisions are introduced.

## 21. Gate to Visual Direction

The low-fidelity V1 UX skeleton is complete after owner review of this
specification-only diff. The next product phase may be Visual Direction with
one or two directions, without reopening workflow, terminology, or IA
decisions.

Colors, typography, spacing systems, design systems, visual components,
frontend implementation, routes, APIs, and backend changes are not authorized
by this freeze.
