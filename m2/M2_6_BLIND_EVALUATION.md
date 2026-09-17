# M2.6 — Blind Draft Evaluation

## Goal

Determine whether style retrieval actually improves drafts enough to justify the added complexity.

## Freeze before evaluation

Freeze:
- corpus snapshot
- style profile
- retrieval method
- prompt
- model
- decoding settings
- EvidencePackets

No tuning during session.

## Blind pairs

For each story:
```text
Draft A
Draft B
```

Reviewer must not know which is generic vs style-assisted.

## Scorecard

Score 1–5:
- Chеrnomorie resemblance
- headline quality
- lead quality
- structure
- natural Bulgarian
- editing effort
- overall preference

Also:
- factual_error yes/no
- unsupported_claim yes/no
- would_publish_after_edit yes/no

## Decision

Return:
```text
STYLE_RETRIEVAL_PROVEN
```
or
```text
STYLE_RETRIEVAL_NOT_PROVEN
```

Then STOP.
