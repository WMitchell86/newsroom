# MILESTONE — M0: Project Bootstrap + Safety Foundation

## Status: IN PROGRESS (awaiting verification run)

## Scope (spec §15)
1. Minimal project/package structure
2. `.gitignore`
3. `.env.example` (no real credentials)
4. Config loader (`AUTO_PUBLISH=false`, `DRY_RUN=true` hard defaults)
5. Structured logging skeleton (stdlib JSON)
6. Test runner + smoke/safety tests
7. `BACKLOG.md` + this file
8. `.ai/skills/` starter files (project-bootstrap, source-adapter, verification-gate)
9. Verify: `pip install -e ".[dev]"` + `pytest` green on clean checkout

## Gate checklist
- [ ] Clean checkout installs
- [ ] Test runner starts, smoke test passes
- [ ] Config loads without production credentials
- [ ] AUTO_PUBLISH=false / DRY_RUN=true by default
- [ ] No network calls in tests
- [ ] No external write path
- [ ] No secrets in repo
- [ ] Structured local log works

## STOP rule
After M0 report: **STOP AND WAIT FOR REVIEW**. No M1.1 work starts without approval.
