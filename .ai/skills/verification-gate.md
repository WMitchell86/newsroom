# Skill: verification-gate

Source: `AI_HARNESS_EDITOR_ASSISTANT.md` §8 + §14.

## Purpose
Run after every capability change. Nothing merges while the gate is red.

## Checks
- [ ] Tests green (`pytest`), incl. fixtures, duplicate + failure behavior.
- [ ] No secrets in repo (grep: `secret|token|api_key|password`, real-looking values).
- [ ] No production side effects (dry-run / test destinations only).
- [ ] No forbidden publish paths (`publish`, Telegram/WordPress clients, global auto-publish switch).
- [ ] Scope lock holds (no unrelated refactor in the same change).
- [ ] Audit/structured log path still works.

## Definition of Done reminder (spec §14)
Scope met; no unrelated refactor; tests pass; fixture/reproducible input;
manual end-to-end proof; failure case tested; production side effects described;
rollback described; docs updated; exactly one next smallest step proposed;
harness stopped awaiting review.
