# M2.7 — Idea Intake + Idea Cards

## Goal

Turn incoming leads into small editor-facing idea cards.

```text
lead
→ normalize
→ dedupe
→ IdeaCard
→ editor decision
```

No automatic drafting yet.

## Start with one source type

Choose exactly one:
- official source update
- press email
- event listing
- manual lead

## IdeaCard contract

```yaml
idea_id:
source_id:
source_url:
observed_at:
title:
what_changed:
why_now:
location:
possible_angle:
evidence_status:
related_archive_ids:
recommended_action:
```

Keep `possible_angle` clearly separate from facts.

## Recommended actions

```text
DRAFT
FOLLOW_UP
CALENDAR
IGNORE
HUMAN_REVIEW
```

Do not auto-execute.

## Evaluation

Review at least 30 cards.

Score:
- useful
- not useful
- misleading
- duplicate
- wrong angle

## Verification Gate

PASS only if:
- cards are fast to scan
- factual fields grounded
- AI suggestions clearly separated
- dedupe works
- archive background labeled
- no drafting auto-trigger exists

Then STOP.
