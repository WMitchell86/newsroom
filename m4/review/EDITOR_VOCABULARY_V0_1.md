# Editor Vocabulary v0.1 — frozen semantic contract

**Status:** corrected spec, frozen for the editor-facing Workbench language.
This document is the source of truth for the terms below. It does not rename
backend fields, storage keys, URLs, or model/provider contracts.

## Editor concepts

| Term | Meaning |
|---|---|
| **История** | A real-world event/topic that can evolve over time and contain multiple publications and developments. |
| **Ново развитие** | New information belonging to an existing story. |
| **Публикация** | One individual incoming item: official announcement, news article, URL, transcript, etc. |
| **Източник** | The publisher/origin of information. |
| **Факти и източници** | The current factual basis for a story/article. |
| **Какво липсва** | Missing facts, unresolved questions, conflicts, or information still needed. |
| **Проучване** | Work done to fill those gaps; manual or AI-assisted later. |
| **Редакционен фокус** | What the article will focus on and how the story will be framed editorially. In compact interface copy: **Фокус**. |
| **Статия** | A piece of editorial work the editor decided to produce from a story. |
| **Чернова** | A draft of that article; AI-generated, manually written, or heavily edited. |
| **Финализирана статия** | An article finished inside the editorial system; not automatically published. |

**Terminology decision:** `Редакционен фокус` is the canonical editor-facing term.
`Редакционен ъгъл` is retired from the normal editor vocabulary. The word
`ъгъл` may remain only in backend contracts, historical reports, or technical
diagnostics where it names an internal field or model concept.

## Non-editor concepts

`Idea · EvidencePacket · Prepared · Case · SourceItem ·
publication_identity · lineage · model role · provider attempt` remain backend
terms. They must not be used as the primary noun in normal editor copy.

## Frozen actions

The editor action vocabulary is:

```text
Прегледай → Следи → Игнорирай → Проучи още → Започни статия
→ Избери фокус / Промени фокуса → Направи чернова → Редактирай
→ Отбележи като готова → Финализирай
```

The important distinctions are:

```text
Започни статия         = the editor decides to produce an article from a story
Направи чернова        = a draft is created for that article
Отбележи като готова   = the editor declares the draft ready for finalization
Финализирай            = the article becomes a Финализирана статия
```

`Отбележи като готова` is a deliberate editorial checkpoint. It does not
finalize the Article and does not publish it.

## Invariants

- **История ≠ Статия.** One story may produce no article, one article, or several
  articles as it develops.
- **Източник ≠ Публикация.** Burgas Municipality is a source; its specific
  press release is a publication.
- **Факти и източници ≠ архивен стил.** Current sources establish facts;
  historical Chernomorie articles influence style only.
- Nothing in this vocabulary creates a publication, finalizes an article, or
  changes the existing safety and backend contracts.

## Implementation boundary

This freeze is a **specification only**. No Workbench, frontend, route,
storage, or backend implementation is part of this correction. UI changes
require a separately reviewed and approved implementation step.

The owner-approved Step 2 Information Architecture is frozen in
`m4/review/INFORMATION_ARCHITECTURE_V0_1.md` and uses:

```text
Днес / Истории / Статии / Архив / Настройки
```

The owner-approved Step 3 workflow specification is frozen in
`m4/review/EDITOR_WORKFLOWS_V0_1.md`. It preserves the approved five-area IA,
the three Article states, and the explicit
`Отбележи като готова → Финализирай` sequence.

After owner review of the Step 3 documentation diff, the next permitted UX
phase is low-fidelity wireframes. No implementation is authorized by this
vocabulary freeze.
