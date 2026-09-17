# AI Agent Operating Rules — Editorial AI Track

## Role

You are implementing a controlled editorial-assistant system for Chеrnomorie.

Complete one approved milestone at a time.

## Mandatory task protocol

Before coding, define:

```yaml
goal:
non_goals:
files_expected_to_change:
frozen_areas:
external_systems_touched:
risk_level:
verification_plan:
```

Anything outside scope goes to backlog.

## One capability per milestone

Allowed:
- one new contract
- one new parser
- one new retrieval mechanism
- one new evaluator

Not allowed:
- corpus + retrieval + generation + publishing integration in one milestone

## Inspect before modify

Always inspect relevant modules, tests, config, data contracts, logging, frozen boundaries, and git status.

If the change may affect several existing subsystems, consider a repo ZIP audit before implementation.

## Preserve frozen Radar

Do not touch frozen Radar components unless explicitly authorized.

If implementation appears to require touching frozen Radar: STOP and report why.

## Deterministic first

Use deterministic code for parsing, normalization, metadata extraction, IDs, dates, hashes, statistics, filters, and hard constraints.

Use LLMs only where semantic interpretation is genuinely required.

## Style is not fact

Maintain this split:

```text
EvidencePacket = facts allowed in current draft
StyleExamples = stylistic references only
```

Never merge them into one undifferentiated context blob.

## Prompt discipline

Every draft-generation prompt must clearly separate:

```text
CURRENT EVIDENCE
CURRENT QUOTES
CURRENT LINKS
STYLE PROFILE
STYLE EXAMPLES
WRITING TASK
FORBIDDEN BEHAVIOR
```

## Testing discipline

Each milestone should include:

1. unit tests
2. fixture-based tests
3. negative tests
4. deterministic re-run test
5. manual sample review
6. regression check
7. frozen-area diff check

## STOP rule

After milestone verification:

```text
STOP AND WAIT FOR REVIEW
```

## Report format

```markdown
# <Milestone> Report

## Implemented
## Files changed
## Contracts introduced
## Tests run
## Test result
## Manual verification
## Failure-case verification
## Frozen-area verification
## Known limitations
## Production side effects
## Rollback
## Verdict
## Recommended next smallest step
```

## Repo ZIP deep-audit trigger

Request a full repo ZIP only when it materially improves correctness.

```text
REPO ZIP AUDIT RECOMMENDED

Reason:
<why local context is insufficient>

Inspect:
- ...
- ...

Questions to answer:
1. ...
2. ...

Do not modify code until audit conclusion.
```
