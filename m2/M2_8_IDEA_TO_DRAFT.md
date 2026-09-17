# M2.8 — Idea → Evidence → Draft

## Goal

Connect only already-proven components:

```text
IdeaCard
→ editor chooses DRAFT
→ EvidencePacket
→ Style Retrieval
→ Draft Lab
→ editor review
```

No auto-publish.

## Explicit editor trigger

Draft generation requires explicit editor action.

## Evidence first

If evidence is insufficient:

```text
DRAFT_BLOCKED_INSUFFICIENT_EVIDENCE
```

Do not ask the model to fill gaps.

## Style second

Only after evidence passes:
- choose StyleProfile
- retrieve StyleExamples

## Audit trail

Store:
- IdeaCard ID
- EvidencePacket ID
- StyleProfile ID
- StyleExample IDs
- Draft ID

## Manual evaluation

Run 10 real stories and record:
- idea usefulness
- evidence completeness
- draft correctness
- style quality
- editing effort
- editor action

## Verification Gate

PASS only if:
- editor trigger explicit
- insufficient evidence blocks draft
- lineage complete
- no archive factual leakage
- all drafts remain drafts
- 10-story audit completed

Then STOP.
