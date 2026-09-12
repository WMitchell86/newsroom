# MILESTONE — M1.3: Local State + Identity + Version Detection

## Status: DONE (verified 2026-09-12)

## Scope
`SourceItem[] → stable identity → SHA-256 version fingerprint → SQLite state
→ NEW / UNCHANGED / UPDATED`. Stdlib `hashlib` + `sqlite3` only, no ORM.
Runtime DB default `var/editor_assistant.sqlite3` (gitignored); tests use tmp DBs.

## Gate checklist
- [x] all existing tests green (57 passed: 19 state + 38 prior)
- [x] ruff check + format clean
- [x] same item never NEW twice; fetched_at changes don't trigger UPDATED
- [x] content changes trigger UPDATED with version_no += 1
- [x] batch failure rolls back fully (simulated mid-batch INSERT failure → 0 rows)
- [x] no external write system; no scheduling; no Telegram
- [x] no runtime DB committed (var/ + *.sqlite3 gitignored)

## STOP rule
**STOP AND WAIT FOR REVIEW.** No Telegram/scheduling/history/next milestone.

---

# MILESTONE HISTORY — M1.2.1: RSS Description Normalization

---

# MILESTONE HISTORY — M1.2: One Real Source, Read-Only

---

# MILESTONE HISTORY — M1.1: Source Contract + Fixture Only

## Status: DONE (verified 2026-09-12, commits fb84a57 + corrective 344dbf1)
One RSS 2.0 fixture → rss20 parser → SourceItem → local JSON. Corrective patch:
naive pubDate raises SourceParseError (no UTC/Sofia/local guess); timezone matrix tests.

---

# MILESTONE HISTORY — M0: Project Bootstrap + Safety Foundation

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
