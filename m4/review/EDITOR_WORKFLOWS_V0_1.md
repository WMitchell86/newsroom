# Editor Workflows v0.1 — frozen

**Date:** 2026-09-24
**Status:** owner-approved Step 3 workflow freeze; specification only
**Scope:** normative V1 editorial workflows for `chernomorie-bg.com`

This document turns the approved Step 3 workflow validation into a concise
product contract. It does not implement or redesign routes, Workbench HTML,
frontend code, backend models, storage, APIs, tests, or safety behavior.

## 1. Workflow principles

The V1 product model is:

```text
История → Статия → Финализирана статия
```

- `История` is what is happening in the real world.
- `Статия` is what the newsroom decided to produce about a Story.
- One Story may produce zero, one, or several Articles.
- `Днес` is a derived attention view. It owns no editorial object or state.
- Publications belong to a Story and have no editor-facing review lifecycle.
- `Следи` is a persistent bookmark, not a lifecycle state.
- Research remains attached to the Story.
- Internal `Idea`, `EvidencePacket`, `Prepared`, and `Case` concepts remain
  invisible to the editor.
- Finalization means completed inside the system, not published to the website.

The only primary areas remain:

```text
Днес / Истории / Статии / Архив / Настройки
```

## 2. Derived attention rules for `Днес`

`Днес` shows only Stories, Articles, or genuine problems that require a
concrete next editorial action. It is not an inventory of active objects.

- An unreviewed new Story appears until `Прегледай` or `Игнорирай`.
- A followed Story reappears when it has a meaningful `Ново развитие`.
- Reviewing that development removes the current attention while `Следи`
  remains.
- An Article in `Подготовка` appears only when it has a concrete next action.
- An Article in `Чернова` may appear when editing is needed.
- An Article in `Готова` may appear when finalization is the next action.
- A technical problem appears only when it has a clear consequence or action.

No separate attention flag, queue object, notification center, or sixth area is
introduced. `Днес` derives attention from the canonical Story, Article, and
operational context.

## 3. Story review workflow

### Normal actions

`Прегледай`, `Следи`, `Игнорирай`, and, when justified, `Започни статия`.

### V1 rules

- The Story is the single owner of editorial attention.
- Publications are inspected as evidence inside the Story.
- Publications have no editor-facing `NEW / SEEN / IGNORED` lifecycle.
- `Следи` persists independently from review status.
- A Story may be reviewed, followed, or both.
- A Story may produce no Article.
- Opening an individual Publication does not change any publication state.

### Outcome

After `Прегледай`, `Следи`, or `Игнорирай`, the Story remains in `Истории`.
No Article or Article state is created.

## 4. New Development workflow

A meaningful `Ново развитие` returns a relevant followed Story to `Днес` as a
delta. The editor must be able to understand:

- what changed;
- when it changed;
- which Publication supports it.

`Ново развитие` is not a separate workspace, object, or lifecycle state. The
Story remains the owner. Earlier background remains available in the Story
context, but the editor must not need to reread the entire Story to understand
the delta.

After `Прегледай`, the current development leaves `Днес`; `Следи` remains
unchanged. The editor may instead choose `Проучи още` or `Започни статия`.

## 5. Research workflow

`Проучи още` stays inside the Story and uses the current `Какво липсва` and
unresolved questions as its basis. It invokes available research behavior when
supported. Results return to the same Story and update `Факти и източници`
and/or the remaining `Какво липсва`.

If research cannot execute successfully:

- no new workflow state is created;
- no Research center or separate research destination is created;
- the existing `Какво липсва` remains visible;
- the editor may continue with available verified information.

The product must not promise a richer research executor than the repository
currently supports. Research does not have an editor-facing status.

## 6. Start Article workflow

`Започни статия` creates an Article immediately in `Подготовка`. It has:

- a link to its Story;
- a prefilled, editable working title;
- an Editorial Focus;
- no Draft until `Направи чернова`.

One Story may have several Articles. V1 requires only
`Статии по тази история`; it introduces no special multi-Article management
workflow.

The working title is prefilled rather than independently approved. Internal
Article-creation stages are not presented as editor steps.

## 7. Editorial Focus and Draft readiness

`Редакционен фокус` remains the canonical editor-facing term. It is 1–3
plain-language sentences answering:

> Какво конкретно искаме да разкажем с тази статия?

AI may propose it; the editor may edit it. Angle, mode, voice, and focus are
not parallel editor concepts.

`Направи чернова` is available when:

- a valid Editorial Focus exists; and
- no blocking gap remains.

A gap may be blocking or non-blocking:

- a blocking gap prevents Draft creation and makes `Проучи още` the
  appropriate next action;
- a non-blocking gap remains visible but does not prevent Draft creation.

This changes the next action only. It does not create another Article state,
and the editor does not manually create a readiness status. The system
determines whether a gap is blocking and must explain why.

## 8. Article states and ready/finalize workflow

V1 has exactly three editor-facing Article states:

1. `Подготовка` — the Article exists, but Draft creation is not complete.
   Work may include refining focus, examining Facts and Sources, resolving
   blocking gaps, or research.
2. `Чернова` — text exists and is being reviewed or edited.
3. `Готова` — the editor explicitly considers the Article ready for finalization.

Warnings do not create another state. No fourth Article state is permitted.

The ready/finalize sequence is explicit:

```text
Чернова
→ Редактирай
→ resolve or consciously review warnings
→ Отбележи като готова
→ Готова
→ Финализирай
→ Финализирана статия в Архив
```

`Отбележи като готова` is a deliberate editorial checkpoint. It does not
finalize or publish the Article. `Финализирай` acts only on an Article in
`Готова`, removes it from active production, and makes it available in
`Архив`.

`Финализирана статия` means completed inside the editorial system. It does not
mean automatically published to `chernomorie-bg.com`; V1 adds no publishing
workflow.

Factual warnings, source conflicts, originality warnings, and similar issues
remain visible where they affect the decision. Blocking safety failures
continue to respect existing backend safety behavior; this specification does
not redesign those contracts.

## 9. Exceptional correction and failure handling

### Grouping correction

Inside the Story Workspace, the secondary `Коригирай групирането` action
contains:

- `Отдели публикация`
- `Обедини с друга история`

These are exception tools. They are not normal primary actions and do not
change Article states.

### Source or AI failure

Failures appear at the point where they affect work. In plain language, the
editor needs to know:

- what failed;
- what could not be completed;
- what existing work is preserved;
- what action is available next.

Normal editorial work does not expose model roles, provider routing, internal
error classes, request accounting, or logs. Detailed technical information and
operator correction belong under `Настройки`.

A failure creates no new editorial state. Existing safety and preservation
contracts remain authoritative.

## 10. Approved V1 scenarios

### Scenario 1 — Morning review

```text
Днес → concrete next action → Story or Article requiring action
```

`Днес` shows a new Story, a meaningful New Development, or an Article whose
next action is needed. It does not show all active objects or a Publications
queue.

### Scenario 2 — Review a new Story without writing

```text
Story → Прегледай → optionally Следи / Игнорирай → no Article
```

The editor inspects what happened, Facts and Sources, and any relevant
Publication, then decides that no Article is needed now.

### Scenario 3 — Followed Story receives a New Development

```text
Днес → delta → Story → Прегледай / Проучи още / Започни статия
```

The editor sees what changed, when, and which Publication supports it, without
rereading the entire Story.

### Scenario 4 — Story needs more information

```text
Story → Какво липсва → Проучи още → results remain in the same Story
```

Research updates the Story's Facts and Sources or remaining gaps. Failure
leaves the existing gaps visible and creates no Research center or state.

### Scenario 5 — Start Article → Draft

```text
Story
→ Започни статия
→ Подготовка
→ working title + Редакционен фокус
→ Facts/Sources + missing information
→ Направи чернова
→ Чернова
```

`Направи чернова` requires a valid focus and no blocking gap. Backend
Idea/Evidence/Prepared/Case steps remain invisible.

### Scenario 6 — Edit → Ready → Finalize

```text
Чернова
→ Редактирай
→ resolve/review warnings
→ Отбележи като готова
→ Готова
→ Финализирай
→ Архив
```

Finalization is explicit and is not website publication.

### Scenario 7 — Exceptional correction / failure

```text
Story → Коригирай групирането → correction
or
Story/Article → point-of-work failure → preserve work and show available path
```

Neither exception creates a new area, object, or workflow state.

## 11. Cross-workflow invariants

- Exactly five primary areas: `Днес / Истории / Статии / Архив / Настройки`.
- Exactly three Article states: `Подготовка / Чернова / Готова`.
- `История` and `Статия` remain distinct.
- `Днес` owns no state and creates no attention object.
- Publications have no independent editor-facing review lifecycle.
- `Следи` is an independent persistent bookmark.
- `Ново развитие` is a delta inside a Story, not a separate workspace.
- Research remains inside a Story and has no editor-facing status.
- `Редакционен фокус` remains the canonical term.
- Warnings and failures create no Article state.
- Grouping correction remains secondary and exceptional.
- `Отбележи като готова` and `Финализирай` remain separate actions.
- Finalization is not publication.
- The normal editor actions are those frozen in Step 1; the exceptional
  grouping-correction actions are those frozen in Step 2.

## 12. Explicit V1 exclusions

No sixth primary area and no primary destinations for Publications/Materials,
New Developments, Research, Editorial Focus, Drafts, Ideas, EvidencePackets,
Prepared, Cases, model roles, or YouTube.

No manual intake, notifications, subscriptions, assignments, team roles,
analytics, configurable dashboards or queues, workflow boards, collaboration
systems, separate AI workspace, publishing workflow, or new backend abstraction.

## 13. Gate to the next UX phase

This is a specification-only freeze. The next human step is owner review and
approval of the Step 3 documentation diff.

Only after that approval may the project proceed to low-fidelity wireframes.
Wireframes must use these frozen workflows and must not introduce new objects,
states, actions, primary areas, or unsupported capabilities.

No frontend, Workbench, route, backend, storage, API, test, CSS, or runtime
change is authorized by this document.
