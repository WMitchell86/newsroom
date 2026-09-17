# M2.7–M2.9 — Real Editorial Workflow Pilot

## Status entering this milestone

The laboratory drafting phase is closed.

Frozen decisions:

```text
M2.1  STYLE CORPUS                  DONE
M2.2  MULTI-STYLE DISCOVERY         DONE
M2.3  GROUNDED MULTI-STYLE DRAFTING PASS WITH NOTES
```

Proven:

```text
GROUNDING                         PROVEN
ARCHIVE LEAKAGE PROTECTION       PROVEN
VOICE_HOUSE                       PROVEN / DEFAULT
MODE COMPOSITION                  GOOD ENOUGH
MODE_BRIEF                        USEFUL
MODE_EVENT_PREVIEW                USEFUL
MODE_CULTURE_FEATURE              AVAILABLE
VOICE_DESISLAVA_RECENT            PROVISIONAL / OPT-IN
```

Do not reopen M2.1–M2.3 unless repeated failures from real editorial use justify it.

---

# Mission

Build the first real editor-facing workflow:

```text
IDEA / SOURCE
      ↓
EVIDENCE
      ↓
VOICE + MODE
      ↓
GROUNDED DRAFT
      ↓
EDITOR EDIT
      ↓
FINAL ARTICLE
      ↓
DIFF + LEARNING SIGNAL
```

The purpose is not to automate publication.

The purpose is to measure whether the assistant saves real editorial effort while preserving factual accuracy.

---

# 1. Good Enough policy is binding

Prefer:

```text
usable real workflow
→ real editor corrections
→ recurring patterns
→ targeted improvement
```

over:

```text
more laboratory scoring
→ more synthetic A/B tests
→ more taxonomy work
```

Do not build infrastructure that is not required for the real workflow.

---

# 2. Pilot size

Run the workflow on:

```text
10–20 real editorial items
```

A minimum of 10 completed editor-reviewed cases is enough for the first decision.

Do not require 50+ articles before evaluating usefulness.

---

# 3. Intake

Support the smallest practical intake surface.

At minimum:

```text
MANUAL SOURCE
```

where the editor can provide:

- source URL;
- pasted source text;
- or an already available source snapshot/reference.

Optional read-only adapter:

```text
existing Radar SourceItem / outbox item
```

only if it can be consumed without modifying frozen Radar contracts.

Do not redesign Radar.

---

# 4. IdeaCard

Create a lightweight `IdeaCard`.

Suggested contract:

```yaml
idea_id:
created_at:
source_type:
source_url:
source_reference:
title:
what_changed:
why_now:
location:
possible_angle:
status:
```

Allowed status:

```text
NEW
DRAFT_REQUESTED
IGNORED
FOLLOW_UP
```

Important:

- `what_changed` should be factual where possible;
- `possible_angle` is editorial suggestion, not source truth;
- AI-generated angle must be clearly labeled as suggestion.

Do not build sophisticated prioritization yet.

---

# 5. EvidencePacket

Reuse the proven M2.3B EvidencePacket contract and safeguards.

The EvidencePacket remains the only factual authority for the draft.

Preserve:

- facts;
- people;
- organizations;
- places;
- dates;
- numbers;
- quotes;
- unknowns;
- source text / source references;
- packet version.

Keep the headline-number conflict annotation introduced in M2.3B.

Do not weaken the factual boundary.

---

# 6. Editor chooses VOICE + MODE

Default:

```text
VOICE_HOUSE
```

Available modes:

```text
STANDARD_NEWS
BRIEF
EVENT_PREVIEW
CULTURE_FEATURE
```

Experimental opt-in:

```text
VOICE_DESISLAVA_RECENT
```

The assistant may suggest a mode, but the editor must be able to override it.

Conceptually:

```text
Suggested:
VOICE_HOUSE + EVENT_PREVIEW

Editor:
[Use] [Change]
```

Do not auto-force the suggested mode.

---

# 7. Mode suggestion

Mode suggestion should remain simple and explainable.

Examples:

```text
future event + dates/program → EVENT_PREVIEW
very small factual item      → BRIEF
culture long-form source     → CULTURE_FEATURE
otherwise                    → STANDARD_NEWS
```

No classifier training is required.

Store:

```text
suggested_mode
selected_mode
mode_changed_by_editor: true/false
```

This becomes a useful real-world signal.

---

# 8. Style retrieval

Reuse the existing M2.3 retrieval logic.

For every draft store:

```text
style_example_ids
retrieval_reason
fallback_used
```

Preferred:

```text
same VOICE + same MODE
```

then frozen fallback rules.

Do not introduce vector DB / embeddings unless real workflow demonstrates retrieval failure.

---

# 9. Draft generation

Reuse the grounded M2.3B drafting path.

Prompt remains separated into:

```text
CURRENT EVIDENCE
CURRENT UNKNOWNS
SITE DNA
VOICE
MODE
STYLE EXAMPLES
TASK
FORBIDDEN BEHAVIOR
```

Do not allow style examples to become factual evidence.

---

# 10. Semantic factual gate

Keep the M2.3B semantic factual verification.

A generated draft may be shown to the editor with one of:

```text
FACTUAL_GATE_PASS
FACTUAL_GATE_REVIEW
```

If the semantic judge finds a material unsupported / contradicted / temporally misbound claim:

```text
FACTUAL_GATE_REVIEW
```

Do not present the draft as ready.

Do not silently rewrite repeatedly until it passes without recording attempts.

If one regeneration is used, record it in lineage.

---

# 11. Draft output

Present:

```text
headline options
selected/generated headline
draft body
VOICE
MODE
factual gate status
```

Do not show internal chain-of-thought.

Do not expose raw style examples unless the editor asks.

---

# 12. Editor revision

The editor must be able to provide the final edited article.

Store both:

```text
draft_before
final_after
```

Never overwrite the AI draft.

The pair is the key learning artifact.

---

# 13. Revision metadata

For each completed case capture:

```yaml
case_id:
idea_id:
evidence_id:
draft_id:

voice_selected:
mode_suggested:
mode_selected:
mode_changed:

draft_headline:
final_headline:

draft_text:
final_text:

editor_outcome:
editing_weight:
time_saved_estimate:
published_or_ready:
notes:
```

Suggested `editing_weight`:

```text
LIGHT
MODERATE
HEAVY
REWRITE
REJECTED
```

Do not require precise timing if burdensome.

A rough editor estimate is enough:

```text
<5 min
5–15 min
15–30 min
>30 min
```

---

# 14. Diff

Create a deterministic text diff between:

```text
AI draft
and
editor final
```

At minimum detect:

```text
headline changed
paragraph added
paragraph removed
paragraph reordered
sentence added
sentence removed
```

Then optionally classify corrections into:

```text
FACT
STYLE
STRUCTURE
TONE
HEADLINE
LOCAL_TERMINOLOGY
FORMAT
OTHER
```

Deterministic diff first.

LLM classification may assist, but must not modify the final article.

---

# 15. Important separation

A factual correction is NOT a style preference.

Example:

```text
wrong number corrected
→ FACT
```

not:

```text
HOUSE style prefers another number
```

Likewise:

```text
paragraph moved earlier
→ STRUCTURE
```

and:

```text
generic promotional adjective removed
→ TONE / STYLE
```

---

# 16. Learning signals

Do not automatically update profiles after every article.

Aggregate recurring patterns.

Record examples such as:

```text
HOUSE opening consistently shortened
generic conclusions repeatedly removed
EVENT_PREVIEW practical time moved earlier
headlines consistently made more active
DESISLAVA drafts receive more scene-setting
```

A possible style/profile change requires repeated evidence.

Suggested first threshold:

```text
same correction pattern ≥ 5 real cases
```

before proposing a profile change.

Human approval remains required.

---

# 17. DESISLAVA_RECENT treatment

Keep:

```text
PROVISIONAL
OPT-IN
```

Do not promote it merely because the workflow exists.

Track separately:

```text
number of real uses
editing weight
recurring corrections
editor preference
```

Promotion should come from real editorial feedback, not another synthetic blind test.

---

# 18. No fine-tuning

Fine-tuning remains closed.

Do not fine-tune from the first 10–20 edited drafts.

First use editor diffs to improve:

```text
profiles
prompt
mode guidance
retrieval
```

Fine-tuning is only reconsidered under the existing M2.10 gate.

---

# 19. No auto-publish

This milestone must not:

```text
publish to WordPress
schedule posts
send directly to social media
auto-approve drafts
```

The final decision remains human.

---

# 20. Minimal editor surface

Use the simplest interface already natural to the repository.

Acceptable:

```text
CLI
generated Markdown review file
small local command workflow
simple local web page if already easy
```

Do not spend the milestone building a polished newsroom UI.

The workflow matters more than presentation.

---

# 21. Case lineage

Every completed case must be traceable:

```text
IdeaCard
→ EvidencePacket
→ selected VOICE/MODE
→ retrieved examples
→ generated draft
→ factual audit
→ editor final
→ diff
```

This lineage is more important than UI polish.

---

# 22. Real-world metrics

After 10+ completed cases report:

```text
total cases
drafts accepted for editing
drafts rejected
LIGHT / MODERATE / HEAVY / REWRITE counts
publish/ready-after-edit count

headline accepted unchanged
headline modified
mode changed by editor

factual corrections made by editor
semantic-gate catches

median/typical time saved estimate

HOUSE cases
DESISLAVA experimental cases

top recurring correction patterns
```

Do not invent an elaborate composite score.

---

# 23. Primary success metric

The most important question:

> Does the editor prefer starting from the AI draft rather than writing the article from scratch?

Capture:

```text
YES
NO
MIXED
```

per case if practical.

This is more valuable than another style benchmark.

---

# 24. Good Enough success gate

The workflow is proven enough to continue if, after at least 10 real cases:

- factual mistakes reaching the editor are rare and identifiable;
- most drafts are useful starting points;
- a meaningful share require only LIGHT or MODERATE editing;
- editor reports real time/effort savings;
- mode selection is useful;
- lineage and diffs are stored reliably;
- no safety/publishing boundary is weakened.

Do not require every article to be publish-ready.

---

# 25. Blockers

Block progress only for:

```text
repeated factual hallucinations
broken evidence lineage
draft/final data loss
identity mixing
unsafe publication behavior
systemic workflow unreliability
```

Do not block for:

```text
individual weak headline
rare stylistic miss
one awkward paragraph
provisional Desislava voice
minor formatting differences
```

Those become feedback data.

---

# 26. Expected artifacts

Suggested runtime artifacts:

```text
var/editorial_workflow/
    ideas.jsonl
    evidence_packets.jsonl
    drafts.jsonl
    factual_audits.jsonl
    editor_finals.jsonl
    revisions.jsonl
    workflow_report.json
```

Suggested committed code:

```text
src/editor_assistant/workflow/
```

Only if a dedicated module is cleaner than extending the current drafting layer.

Do not duplicate existing contracts.

---

# 27. Tests

Test only important workflow guarantees:

1. IdeaCard serialization.
2. Idea → Evidence linkage.
3. HOUSE default.
4. mode suggestion + editor override.
5. DESISLAVA remains explicit opt-in.
6. Evidence/style separation preserved.
7. factual gate state persisted.
8. draft is never overwritten by final.
9. deterministic diff works.
10. revision classification schema valid.
11. full lineage reconstructable.
12. no auto-publish action exists.
13. no frozen Radar mutation.

Avoid low-value test proliferation.

---

# 28. Report

After at least 10 real editor-reviewed cases:

```markdown
# Editorial Workflow Pilot Report

## Cases completed
## Source types
## VOICE usage
## MODE usage

## Grounding performance
## Semantic factual-gate catches
## Editor factual corrections

## Editing weight
## Time/effort saved
## Headline acceptance
## Mode overrides

## HOUSE results
## DESISLAVA experimental results

## Top recurring editor corrections
## Proposed profile/prompt changes
## Changes explicitly NOT justified yet

## Workflow reliability
## Known limitations
## Backlog

## Verdict
WORKFLOW_PROVEN
WORKFLOW_PROMISING
WORKFLOW_NOT_PROVEN

## Recommended next step
```

---

# 29. STOP rule

After the first 10–20 real cases and report:

```text
STOP AND WAIT FOR REVIEW
```

Do not automatically add publishing integration.

Do not automatically fine-tune.

Do not reopen the old laboratory milestones unless the real workflow shows a repeated reason.
