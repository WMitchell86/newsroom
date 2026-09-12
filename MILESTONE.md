# MILESTONE — M1.1: Source Contract + Fixture Only

## Status: DONE (verified 2026-09-12)

## Scope
`fixture → parser → normalized SourceItem → local deterministic output → verification`.
One RSS 2.0 fixture, stdlib only, no network, no persistence, no Telegram/WordPress.

## Gate checklist
- [x] pytest passes (15 passed: 9 M1.1 + 6 M0 smoke)
- [x] ruff check + format clean
- [x] no network imports introduced
- [x] no production write path exists
- [x] parser result manually inspectable (`item_to_dict` JSON)
- [x] malformed input behavior demonstrated (SourceParseError, 3 cases)
- [x] git diff contains only M1.1 scope (sources/models/fixture/tests/MILESTONE + smoke guard fix)

## STOP rule
**STOP AND WAIT FOR REVIEW.** No M1.2 work starts without approval.

---

# MILESTONE HISTORY — M0: Project Bootstrap + Safety Foundation

## Status: DONE (verified 2026-09-12, commit c3c6634 on main)

## Scope (spec §15)
1. Minimal project/package structure ✅
2. `.gitignore` ✅
3. `.env.example` (no real credentials) ✅
4. Config loader (`AUTO_PUBLISH=false`, `DRY_RUN=true` hard defaults) ✅
5. Structured logging skeleton (stdlib JSON) ✅
6. Test runner + smoke/safety tests ✅
7. `BACKLOG.md` + milestone file ✅
8. `.ai/skills/` starter files (project-bootstrap, source-adapter, verification-gate) ✅
9. Verify: `pytest` green; `pip install -e .` blocked by PEP 668 externally-managed
   env — used `PYTHONPATH=src` instead.

## Gate checklist
- [x] Test runner starts, smoke test passes
- [x] Config loads without production credentials
- [x] AUTO_PUBLISH=false / DRY_RUN=true by default
- [x] No network calls in tests
- [x] No external write path
- [x] No secrets in repo
- [x] Structured local log works
