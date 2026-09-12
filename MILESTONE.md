# MILESTONE — M1.2.1: RSS Description Normalization

## Status: DONE (verified 2026-09-12)

## Scope
Deterministic stdlib HTML normalization for RSS descriptions:
`description string → plain body_text + body_links (resolved, ordered, deduped)`.
No persistence/hashes/dedupe, no fetcher changes, no new dependencies.

## Gate checklist
- [x] all previous tests green (38 passed total)
- [x] 13 new normalization tests green (12 required + inner-HTML recovery)
- [x] ruff check + format clean
- [x] live sample: body_contains_markup_after_normalization = 0/20
- [x] href URLs survive as body_links (20/20 items, 20 PDF links)
- [x] plain-text descriptions unregressed (M1.1 fixture bodies byte-identical)
- [x] parser remains network-free (urllib only in fetcher.py)
- [x] no persistence; no external write capability
- [x] diff scoped to models/rss/html_desc/fixture/tests/MILESTONE

## STOP rule
**STOP AND WAIT FOR REVIEW.** No M1.3 without approval.

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
