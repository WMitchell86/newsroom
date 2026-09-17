# M2.9 — Editor Feedback Learning

## Goal

Learn from real editorial corrections without immediately fine-tuning.

```text
AI draft
→ editor final
→ deterministic diff
→ correction patterns
→ reviewed profile updates
```

## Store paired artifacts

Store:
- draft_before
- final_after
- article_type
- style_profile
- evidence_packet
- timestamp

## Diff categories

Examples:
- headline rewrite
- lead shortening
- paragraph reorder
- quote movement
- removed adjective
- removed repetition
- fact correction
- tone correction
- local terminology
- date/number formatting

## Separate style from fact

Classify edits:
```text
STYLE
FACT
STRUCTURE
EDITORIAL_JUDGMENT
```

Do not teach factual correction as style preference.

## Minimum evidence before profile update

Suggested threshold:
```text
same correction pattern observed >= 5 times
```

Human approves any new style rule.

## Profile versioning

Example:
```text
chernomorie_house_v1
chernomorie_house_v2
```

## Verification Gate

PASS only if:
- paired artifacts exist
- factual vs stylistic edits separated
- repeated patterns measurable
- profile updates require human approval
- no automatic self-training
- no fine-tuning

Then STOP.
