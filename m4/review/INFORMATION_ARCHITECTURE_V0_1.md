# Workbench Information Architecture v0.1 — frozen

**Date:** 2026-09-24
**Status:** owner-approved Step 2 freeze; specification only
**Scope:** editor-facing V1 information architecture for `chernomorie-bg.com`

This document records the approved Step 2 product structure. It does not
implement or redesign routes, Workbench HTML, frontend code, backend models,
storage, APIs, or existing safety contracts.

## 1. Frozen primary navigation

V1 has exactly five primary areas:

```text
Днес · Истории · Статии · Архив · Настройки
```

There is no sixth primary area. `Работна маса` is not used as a primary area.

## 2. Core product distinction

```text
История = what is happening in the real world.
Статия  = what the newsroom has decided to produce about that story.
```

One Story may produce no Article, one Article, or several Articles over time.
Story and Article must remain distinct product objects. The V1 Story surface
shows a simple `Статии по тази история` section, without a separate
multi-article management experience.

## 3. Responsibility of the five areas

| Area | Its single question |
|---|---|
| **Днес** | Какво изисква вниманието ми сега? |
| **Истории** | Какво се случва? |
| **Статии** | Какво пишем? |
| **Архив** | Какво сме завършили? |
| **Настройки** | Как работи системата? |

### Днес

`Днес` is a command center, not an analytics dashboard. It may link to new
stories, new developments, Articles requiring action, and genuine problems.
Its editor-facing refresh action is `Обнови`.

`Днес` owns no editorial concept or lifecycle state. It only aggregates links
to Stories and Articles whose canonical state says they need attention. Routine
technical health stays in Settings; only a problem with a clear consequence or
action may appear here.

It does not own Publications, Facts and Sources, missing information, research,
Article focus, drafts, or completed work.

### Истории

`Истории` is the persistent newsroom view of real-world events. It owns Stories,
New Developments, Publications, Facts and Sources, `Какво липсва`, and
`Проучване`.

The Story Workspace progressively discloses what happened, what is new, facts
and sources, missing information, publications, chronology/development, related
Articles, and available actions.

Publication review is not a separate workflow. A Publication is inspected and
used as part of a Story; the Story is the single owner of editorial attention.

Primary actions are `Прегледай`, `Следи`, `Игнорирай`, `Проучи още`, and
`Започни статия`.

### Статии

`Статии` contains active editorial work only. An Article is created when the
editor chooses `Започни статия` from a Story. At creation it has:

- a link to its Story;
- a working title;
- an editorial focus;
- no current draft until `Направи чернова` creates one.

A Story may have several Articles, but V1 needs no special management UX beyond
`Статии по тази история`.

V1 has exactly three editor-understandable Article states:

| State | Meaning |
|---|---|
| **Подготовка** | Information is still being collected and/or the editorial focus is being determined. |
| **Чернова** | Text exists and is being edited. |
| **Готова** | The editor considers the text ready to finalize. |

`Какво липсва` and `Редакционен фокус` are content or next-step information
inside `Подготовка`; they are not Article states. The state names are not
navigation destinations.

Primary actions are `Избери фокус / Промени фокуса`, `Проучи още`,
`Направи чернова`, `Редактирай`, `Отбележи като готова`, and `Финализирай`.

The editor continues to experience one workflow. Backend terms such as Idea,
EvidencePacket, Prepared, Case, mode, and voice are not normal editor nouns or
parallel destinations. Mode/voice may remain backend defaults or secondary
advanced behavior.

### Архив

`Архив` contains `Финализирани статии` and simple search/history of completed

### Настройки

`Настройки` is separate from normal editorial work. It contains source registry
management, AI/models/quotas/cost controls, input channels and ingestion, and
System/diagnostics. YouTube is an ingestion mechanism or technical diagnostic,
not a newsroom object.

A normal editor should be able to complete a working day without opening
Settings.

## 4. Concept ownership

| Concept | Primary home |
|---|---|
| История, Ново развитие, Публикация, Факти и източници, Какво липсва, Проучване | **Истории** |
| Редакционен фокус, Статия, Чернова | **Статии** |
| Финализирана статия | **Архив** |
| Source registry management, AI configuration, ingestion diagnostics | **Настройки** |

`Днес` references these concepts but owns none of them. Other screens may link
to a concept but must not duplicate its full management UI.

`Източник` is a publisher/origin referenced by Stories and Article evidence;
its full registry management belongs in `Настройки`.


## 5. Frozen simplification decisions

### Следи

`Следи` is a persistent bookmark flag, not a lifecycle state. A Story may be
both reviewed and followed. A meaningful New Development makes the followed
Story appear again in `Днес` without removing its followed flag. V1 has no
subscription or notification system.

### Редакционен фокус

V1 focus is 1–3 plain-language sentences answering:

> Какво конкретно искаме да разкажем с тази статия?

AI may propose a focus; the editor may change it. Focus is not a complex form
and does not expose separate angle, mode, voice, and focus concepts.

### Manual intake

General manual intake is excluded from V1. V1 does not design or implement
`Paste URL → extract → attach/new Story → resolve duplicate`. Existing ingestion
mechanisms remain unchanged. A future real-use need may open a separately
approved milestone.

### Story grouping correction

Merge and split are exception tools, not normal editorial vocabulary or primary
actions. They live secondarily inside the Story Workspace under
`Коригирай групирането`, with:

- `Отдели публикация`
- `Обедини с друга история`

## 6. Explicit V1 exclusions

No primary destinations for Publications/Materials, New Developments, Research,
Editorial Focus, Drafts, Ideas, EvidencePackets, Prepared, Cases, model roles,
or YouTube. No configurable dashboard, custom queues, analytics, workflow board,
assignment/team management, separate research/drafts/publications/AI workspace,
or elaborate notification system.

`Архив` is not a knowledge-management system. Settings is not normal editorial
work. No automatic publishing is implied by finalization.

## 7. Current-to-target product mapping

- Keep the daily landing concept as `Днес`.
- Keep Stories and Story detail as `Истории`.
- Merge the Publications/Materials destination into Stories.
- Keep Articles as the destination for active Article work.
- Re-house the active case/editor workflow as the Article Workspace without
  exposing Case terminology.
- Do not rename Cases as Archive; Archive is finalized-Article history.
- Move Sources, Models/AI, YouTube/ingestion, and diagnostics under Settings.
- Hide operator/test-only surfaces from the editor mental model.

This is conceptual mapping only and prescribes no technical route changes.

## 8. Step 3 gate

The owner-approved Step 3 workflow specification is frozen in
`m4/review/EDITOR_WORKFLOWS_V0_1.md`. It preserves these five areas, the
Story/Article distinction, the three Article states, and the frozen
`Отбележи като готова → Финализирай` sequence.

After owner review of the Step 3 documentation diff, the next permitted UX
phase is low-fidelity wireframes. No Workbench, frontend, route, backend,
storage, or API implementation is authorized by this freeze.
