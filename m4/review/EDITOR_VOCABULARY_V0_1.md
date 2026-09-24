# Editor Vocabulary v0.1 — frozen semantic contract

**Status:** frozen for the editor-facing Workbench language. This document is
the source of truth for the terms below. It does not rename backend fields,
storage keys, URLs, or model/provider contracts.

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
| **Редакционен ъгъл** | What the article will focus on and how the story will be framed editorially. |
| **Статия** | A piece of editorial work the editor decided to produce from a story. |
| **Чернова** | A draft of that article; AI-generated, manually written, or heavily edited. |
| **Финализирана статия** | An article finished inside the editorial system; not automatically published. |

## Non-editor concepts

`Idea · EvidencePacket · Prepared · Case · SourceItem ·
publication_identity · lineage · model role · provider attempt` remain backend
terms. They must not be used as the primary noun in normal editor copy.

## Frozen actions

The editor action vocabulary is:

```text
Прегледай → Следи → Игнорирай → Проучи още → Започни статия
→ Избери / промени ъгъл → Направи чернова → Редактирай → Финализирай
```

The important distinction is:

```text
Започни статия  = the editor decides to produce an article from a story
Направи чернова  = a draft is created for that article
```

## Invariants

- **История ≠ Статия.** One story may produce no article, one article, or several
  articles as it develops.
- **Източник ≠ Публикация.** Burgas Municipality is an source; its specific
  press release is a publication.
- **Факти и източници ≠ архивен стил.** Current sources establish facts;
  historical Chernomorie articles influence style only.
- Nothing in this vocabulary creates a publication, finalizes an article, or
  changes the existing safety and backend contracts.

## Implementation boundary

This freeze covers editor-facing labels, headings, helper text, and actions in
`src/editor_assistant/workflow/workbench/`. Backend enum values, internal route
names, storage schemas, and audit keys remain unchanged.
