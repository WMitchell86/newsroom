# MILESTONE — M0: Project Bootstrap + Safety Foundation

## Status: DONE (verified 2026-09-12, commit c3c6634 on main)

## Scope (spec §15)
1. Minimal project/package structure ✅
2. `.gitignore` ✅
3. `.env.example` (no real credentials) ✅
4. Config loader (`AUTO_PUBLISH=false`, `DRY_RUN=true` hard defaults) ✅
5. Structured logging skeleton (stdlib JSON) ✅
6. Test runner + smoke/safety tests ✅
7. `BACKLOG.md` + this file ✅
8. `.ai/skills/` starter files (project-bootstrap, source-adapter, verification-gate) ✅
9. Verify: `pytest` green; `pip install -e .` blocked by PEP 668 externally-managed
   env — used `PYTHONPATH=src` instead (documented limitation below).

## Gate checklist
- [x] Clean checkout installs (with PYTHONPATH=src; see limitation)
- [x] Test runner starts, smoke test passes (6 passed)
- [x] Config loads without production credentials
- [x] AUTO_PUBLISH=false / DRY_RUN=true by default
- [x] No network calls in tests
- [x] No external write path
- [x] No secrets in repo
- [x] Structured local log works

## Known limitation
System Python is PEP 668 externally-managed (`pip install -e .` refused without
`--break-system-packages`); M0 code is dependency-free stdlib so `PYTHONPATH=src
pytest` is the verified path. Revisit install story (venv/pipx/uv) in M1.1 if needed.

## STOP rule
After M0 report: **STOP AND WAIT FOR REVIEW**. No M1.1 work starts without approval.
