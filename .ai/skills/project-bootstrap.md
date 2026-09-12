# Skill: project-bootstrap

Source: `AI_HARNESS_EDITOR_ASSISTANT.md` §8 + §15 (M0).

## Purpose
Create the minimal, verifiable foundation of a brand-new repository
without adding editorial capabilities.

## Must do
- Confirm the repository is empty (or holds only starter files).
- Create the minimal directory + package structure.
- Add `.gitignore` and `.env.example` (placeholders only, no real secrets).
- Add a local config loader with no secrets required.
- Add a structured logging skeleton (local output only).
- Add a test runner and one smoke test.
- Add `BACKLOG.md` and the current milestone/status file.
- Keep `AUTO_PUBLISH=false` as hard default.
- Keep dry-run as default for all future external writes.

## Must not do
- Add WordPress integration.
- Add Telegram integration.
- Add a database server.
- Add n8n.
- Add a scraper.
- Add an LLM provider.
- Build business logic.
- Build premature abstractions.

## Done when (M0 gate)
Clean checkout installs; test runner green; config loads without production
credentials; `AUTO_PUBLISH=false`, `DRY_RUN=true`; no network calls in tests;
no external write path; no secrets in repo; structured local log works.
Then STOP AND WAIT FOR REVIEW.
