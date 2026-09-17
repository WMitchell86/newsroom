# Good Enough / Value-First Development Policy

## Purpose

The project goal is a useful editorial assistant, not perfect infrastructure.

Before any fix, refactor, additional review cycle, or new abstraction, ask:

> If we do not fix this now, will it materially reduce the quality, trustworthiness, or usefulness of the next product experiment?

If no:

```text
document → backlog → move forward
```

## A defect is a BLOCKER only if it creates one of these

1. **Factual risk** — false/mixed facts, or loss of critical source content.
2. **Identity/state corruption** — distinct records can merge/overwrite or lineage becomes unreliable.
3. **Systemic prevalence** — roughly >5% of representative real-world data, or concentrated in an important target group.
4. **Material evaluation bias** — it can significantly distort the next milestone's conclusion.
5. **Operational instability** — recurrent crashes, unreproducible runs, repeated fetch/data failures.
6. **Safety/publishing risk** — secrets, human-review bypass, autonomous publication, provenance weakening.

Otherwise it is normally a known limitation.

## Edge cases

Rare historical/malformed/unusual cases do not justify another implementation cycle merely because they exist.

Examples:

```text
1 / 150 legacy article has imperfect DOM ordering
some old captions are filenames
an author has only a handful of articles
rare punctuation/HTML oddities
```

Handle them when later evidence shows they matter.

## Review budget

Normal milestone rhythm:

```text
implement
→ automated verification
→ one meaningful human review
→ fix systematic/high-impact problems
→ one corrective verification
→ move forward
```

A third corrective loop requires explicit downstream justification.

## Good Enough definition

A milestone is `PASS — GOOD ENOUGH` when:

- its downstream purpose is supported;
- representative real data works;
- remaining defects are understood;
- no unresolved issue threatens facts, identity, safety, reproducibility, or major evaluation validity;
- further polishing has lower value than testing the next capability.

## Known-limitations register

Record:

```yaml
description:
observed_frequency:
impact:
why_not_blocking:
revisit_trigger:
```

A backlog issue becomes active only if it grows in frequency, becomes editor-visible, blocks a new capability, or threatens facts/identity/safety.

## Architecture

Preserve architecture unless demonstrated evidence requires change.

Do not redesign for hypothetical future needs or elegance alone.

## Repo ZIP

Request a full repo ZIP only for genuine cross-module questions, major refactors, frozen-Radar interaction, state/identity coupling, or unexplained test/runtime disagreement.

## Current project decision

The existing 150-article corpus is accepted as:

```text
M2.1 — STYLE CORPUS DONE
STATUS: PASS — GOOD ENOUGH FOR STYLE DISCOVERY
```

Known rare legacy imperfections do not block M2.2 unless M2.2 proves they materially bias a target style group.

## Default priority

Prefer:

```text
working editorial capability
→ editor evaluation
→ observed pain
→ targeted improvement
```

over:

```text
perfect component
→ more edge cases
→ more polishing
→ no usable product
```
