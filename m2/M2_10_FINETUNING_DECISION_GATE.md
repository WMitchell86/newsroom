# M2.10 — Fine-Tuning Decision Gate

## Goal

Decide whether fine-tuning is necessary at all.

Fine-tuning is optional and should be rejected unless evidence shows clear benefit.

## Preconditions

Require enough real pairs:

```text
EvidencePacket
→ AI draft
→ editor-approved final
```

## Fine-tuning is justified only if

1. factual grounding is reliable;
2. style retrieval is proven;
3. prompt/profile improvements plateau;
4. repeated corrections remain systematic;
5. corrections are stylistic rather than source-specific facts;
6. enough paired training data exists;
7. a held-out evaluation set exists.

## Do NOT fine-tune because

- model doesn't sound perfect
- one author is unusual
- retrieval is poor
- corpus parser is noisy
- prompt is badly structured
- evidence packet is incomplete

## Decision

Return one:

```text
NO_FINETUNING_NEEDED
```

or

```text
FINETUNING_JUSTIFIED
```

No training begins inside this milestone.

Then STOP.
