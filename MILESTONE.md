# MILESTONE — M1.2: One Real Source, Read-Only

## Status: DONE (verified 2026-09-12)

## Scope
`live RSS → HTTP fetch (stdlib urllib) → existing rss20 parser → SourceItem[] → JSON stdout`.
No persistence, no Telegram/WordPress/DB/LLM/scheduling/retries/dedupe.
Live source: `burgas-municipal-council`, feed `https://burgascouncil.org/last-update.xml`
(official Municipal Council Burgas "Последно съдържание"; 20 items at verification).

## Gate checklist
- [x] corrective timezone tests pass (naive pubDate → SourceParseError)
- [x] all existing tests pass (25 passed)
- [x] ruff check + format clean
- [x] exactly one external source introduced (`sources/live.py`)
- [x] live endpoint documented (above + README run section)
- [x] manual live fetch succeeds (HTTP 200, application/rss+xml, 66899 bytes, 20/20 parsed)
- [x] output is normalized SourceItem (item_to_dict JSON)
- [x] no network call inside parser (rss.py/models.py clean; urllib isolated in fetcher.py)
- [x] no persistence; no production write integration
- [x] timeout behavior demonstrated (live: timed out → FetchError)
- [x] response-size protection demonstrated (live: max_bytes=100 → FetchError)
- [x] git diff contains only M1.1-corrective + M1.2 scope

## STOP rule
**STOP AND WAIT FOR REVIEW.** No M1.3 (persistence/dedupe) without approval.

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
