# Editorial AI Track — Master Plan

## Purpose

Build a controlled editorial-assistant capability for `chernomorie-bg.com` that can:

```text
collect ideas
→ build evidence packets
→ retrieve relevant Chеrnomorie style examples
→ create drafts
→ learn from editor corrections
```

This track is developed **in parallel** with the frozen Radar pipeline.

The existing Radar remains observational and must not be modified unless a separately approved integration milestone explicitly allows it.

## Core principle

> Never improve style at the expense of factual grounding.

The system must learn **how Chеrnomorie writes**, while keeping a strict separation between:

```text
FACT SOURCE
and
STYLE SOURCE
```

Archive examples may influence wording, structure, rhythm, headline style, paragraph shape, quote placement, and terminology.

Archive examples must **not silently contribute new facts** to a current story.

## Development model

Each milestone follows:

```text
inspect
→ define scope
→ implement smallest useful slice
→ automated tests
→ manual verification
→ audit
→ STOP
```

No automatic continuation.

Every large milestone ends in one of:

```text
PASS
PASS WITH NOTES
FAIL
```

and the harness must stop.

## Frozen capability rule

The current Radar pipeline is frozen.

Do not modify without explicit approval:

- RSS fetch contract
- RSS parser contract
- SourceItem identity
- fingerprint semantics
- item_state semantics
- notification outbox semantics
- Telegram transport
- frozen renderer
- current runtime SQLite DB
- manual poll workflow

New editorial/style development must live in separate modules and use separate fixtures/state where practical.

## Status — 2026-09-16 (M2.3 style/drafting cycle closed by editor verdict)

M2.3 — PASS WITH NOTES:

- `GROUNDING_PROVEN` — factual gate frozen (10/10 primary semantic PASS,
  zero archive leakage), evidence packets at v1.1 (EV-07 headline
  contradiction annotated, see m2/review/M2_3B_EV07_PACKET_RESOLUTION.json).
- `HOUSE_DRAFTING_PROVEN` — VOICE_HOUSE is the default production voice.
- `MODE_COMPOSITION_GOOD_ENOUGH` — STANDARD_NEWS / BRIEF / EVENT_PREVIEW /
  CULTURE_FEATURE stay; mode is an editorial instruction, not a classifier
  target; no further synthetic separation tests.
- `DESISLAVA_VOICE_PROVISIONAL` — VOICE_DESISLAVA_RECENT stays PROVISIONAL /
  opt-in experimental; validated only by real editor feedback over time.
- `PROCEED_TO_EDITORIAL_WORKFLOW` — next milestone is the real editorial
  loop: idea/source → evidence → VOICE_HOUSE (default) + editor-selected
  MODE → grounded draft → editor edit. Track accepted headline, factual
  corrections, paragraphs removed/added, tone edits, mode changes, time
  saved, publish-after-edit weight. No auto-publishing, no fine-tuning
  (M2.10 gate stays closed), no further lab blind cycles; do not reopen
  M2.2/M2.3 unless real editorial use exposes a repeated failure pattern.

Blind-artifact integrity note: the 2026-09-16 `review.md`/`blind_map.json`
pair was found internally inconsistent after editor review (renderer pinned
A=primary in all pairs; the sealed map disagreed on EV-01, EV-04, EV-02).
The artifact is retired unscored — the decision was made on the editor's
qualitative read. Record: `m2/review/M2_3B_BLIND_ARTIFACT_RETIREMENT.json`.

## Planned milestones

### M2.1 — Chеrnomorie Style Corpus
Build a clean local corpus from published Chеrnomorie articles.

### M2.2 — Style Analysis
Measure the corpus and create explicit style profiles.

### M2.3 — Style Retrieval
Retrieve 3–5 relevant published examples for a new story context.

### M2.4 — Evidence Packet
Create a strict current-story fact packet from source material.

### M2.5 — Draft Lab
Combine EvidencePacket + StyleProfile + retrieved style examples → draft.

### M2.6 — Blind Draft Evaluation
Compare generic draft vs style-assisted draft.

### M2.7 — Idea Intake / Idea Cards
Normalize incoming leads into editor-facing idea cards.

### M2.8 — Idea → Evidence → Draft
Connect the proven layers.

### M2.9 — Editor Feedback Learning
Store AI draft → editor final → diff and derive recurring correction patterns.

### M2.10 — Fine-tuning Decision Gate
Only consider fine-tuning if retrieval + style profiles plateau.

## Repo ZIP audit rule

At any milestone, the AI agent may request a complete repository ZIP when:

- architecture boundaries are unclear;
- multiple interacting modules are involved;
- regression risk becomes non-trivial;
- tests do not explain observed behavior;
- a milestone proposes touching frozen Radar code;
- duplicate abstractions appear;
- state/data contracts are uncertain;
- a large refactor seems necessary;
- security/secret handling needs whole-repo verification.

Use:

```text
REPO ZIP AUDIT RECOMMENDED
Reason: <specific reason>
Files/areas to inspect: <list>
Expected decision after audit: <decision>
```

Do not request the ZIP reflexively for every small task.

## Safety rules

### Fact safety
Never invent names, quotes, dates, locations, numbers, roles, causal claims, or institutional positions.

### Style safety
Archive examples are stylistic references only. Do not copy facts, people, dates, numbers, quotes, events, or claims from them into the current draft unless those facts also exist in the current EvidencePacket.

### Publishing safety
All outputs remain DRAFT until a future separately approved milestone.

## Definition of Done

A milestone is done only when:

- scope is complete
- no unrelated refactor exists
- tests pass
- manual verification passes
- failure cases are demonstrated
- source truth is preserved
- frozen Radar contracts remain untouched
- known limitations are documented
- rollback is documented
- next step is singular and explicit
- harness stops for review

## Current recommended start

Begin with:

```text
M2.1 — Chеrnomorie Style Corpus
```

Do not begin generation before the archive corpus itself is proven clean.
