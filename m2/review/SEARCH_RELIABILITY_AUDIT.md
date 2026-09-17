# Search Reliability Foundation — M2S Track S

Verdict: **SEARCH_EXECUTION_ENGINEERING = PROVEN** — live-proven (2026-09-17) against real providers, no API key required: 14/14 operations, 42/42 pages opened, failure taxonomy held under real network conditions. History: the initial implementation carried PROMISING because no search key existed; the M2S-R2 capability stack (Google News RSS / Serper / DDGS / Wikipedia + Brave as optional) made a keyless live benchmark possible, and it passed.

`EDITORIAL_EFFECTIVENESS` remains **PENDING** human editor review (unchanged).

## What was built

| Piece | File | Harness § |
|---|---|---|
| SearchProvider contract + Brave adapter (stdlib urllib) | `workflow/search.py` | A2, A3 |
| Failure taxonomy (`SEARCH_OK`, `SEARCH_CAPABILITY_UNAVAILABLE`, `SEARCH_PROVIDER_ERROR`, `RATE_LIMITED`, `NO_RESULTS`, `QUERY_EXHAUSTED`) | `workflow/search.py` | A4 |
| Bounded retries: 429 honors `Retry-After`, max 2 provider attempts, 401/403 classified not looped | `workflow/search.py` | A5 |
| Generic HTML/text page fetcher (`sources/web_fetch.py`): SSRF guard, size cap, content-type allowlist, explicit categories | `sources/web_fetch.py` | A6 |
| Semantic editor-request constraints: `make_constraints` / `constraints_satisfied` / `evaluate_operation` → `SEARCH_COMPLETE` vs `SEARCH_INCOMPLETE` | `workflow/search.py` | A7 |
| Gap-driven query planning (1–3 queries from missing dimensions/questions; no entity hardcoding) | `workflow/search.py` | A8 |
| Result → open flow: snippets are `DISCOVERY_ONLY`; only *opened* pages may become evidence via the existing SourceBundle contract | `workflow/search.py` | A9 |
| Append-only search audit (`var/editorial_workflow/search_runs/`), no credentials persisted | `workflow/search.py` | A10 |
| Provider config via env (`SEARCH_PROVIDER`, `BRAVE_SEARCH_API_KEY`) | `.env.example` | A3 |

## What was deliberately NOT built

- No consumer Bing/Google HTML scraping as production discovery (A3).
- No new dependency: Brave adapter uses `urllib` (stdlib only, repo rule).
- No retry scheduler, no vector DB, no crawler (scope exclusions).
- The frozen RSS/Radar fetcher (`sources/fetcher.py`) is untouched.

## Constraints preservation (the A7 regression)

`evaluate_operation` returns `SEARCH_INCOMPLETE` with an explicit reason when no
candidate satisfies the recorded editor-request constraints (e.g. "national
Bulgarian media" + `required_domains=(bta.bg,)`): a municipality-calendar
candidate can never silently replace a failed national-media search. Tested in
`tests/test_search_foundation.py::test_query_constraints_survive_fallback_evaluation`.

## Observability

Every `run_search_operation` appends one JSONL record (provider status per
query, attempts, http status, `Retry-After`, elapsed ms, result counts, opened
page status/failure category, constraint verdict) to
`var/editorial_workflow/search_runs/`. No keys or authorization headers are
ever stored (tested: `test_operation_without_provider_reports_capability`).

## Known-answer benchmark status (A11)

Superseded by the live benchmark below (M2S-R2, 2026-09-17): executed for real,
no API key required.

## Live benchmark (M2S-R2, 2026-09-17) — **executed for real**

Scope: 14 operations (7 known-answer from LIVE-pilot ground truth + 7 unseen
Burgas/Bulgaria topics), 3 pages opened per operation, keyless provider chain,
zero HTTP mocks. Raw records: `var/search_benchmark/benchmark_results.json`.

### Provider stack used (capability routing)

| capability | chain used | keyless? |
|---|---|---|
| NEWS | google_news_rss → ddgs | yes |
| WEB | ddgs | yes (serper/brave join when keys exist) |
| BACKGROUND | wikipedia → ddgs | yes |

### Results

| metric | value |
|---|---|
| known-answer discovered | **7/7** (target entity found in candidates) |
| unseen queries with results | 7/7 (avg ~9 candidates/op) |
| provider ops OK | 14/14 (google_news_rss 5, ddgs 5, wikipedia 4) |
| pages opened FETCH_OK | **42/42** (0 fetch-taxonomy failures) |
| latency | RSS ~0.5 s, Wikipedia ~0.4 s, DDGS ~2.7 s avg |
| infra failures → "no material" | 0 (taxonomy held everywhere) |

Known-answer hits included the previously **undiscoverable** boxing story
("Зала Младост в Бургас става арена на боксови двубои", EraNova.bg — found via
Google News RSS within seconds), the theatre and DOCK cases, and both
background targets. The LIV-03 research gap that stalled the readiness loop is
closed in principle: NEWS discovery now reaches local publishers directly.

### Live-found product bugs (fixed during the benchmark)

1. `web_fetch.fetch_page` crashed with `UnicodeEncodeError` on non-ASCII URLs
   (common for .bg publishers) — urllib requires ASCII request lines. Fixed:
   IRI→URI percent-encoding in `_ascii_url` (scheme/host untouched, SSRF guard
   evaluates the same target), regression test
   `test_fetch_page_encodes_non_ascii_url`.
2. Test fixture used `&quot;` inside an attribute value — invalid XML; real
   Google News RSS emits `&amp;`, fixture corrected to wire truth.

### Verdict

**SEARCH_EXECUTION_ENGINEERING = PROVEN** — the execution layer works live end
to end with real providers: discovery, fetch, constraint preservation, failure
taxonomy and audit under real network conditions, with zero infra-to-semantic
collapses. Caveats recorded honestly:

- `ddgs` scrapes unofficial surfaces (DuckDuckGo/Bing/Google/Brave/Yahoo
  backends) — approved as an explicit scope exception, but positioned as
  fallback, not SLA primary; Serper remains the planned general-web upgrade
  (key-gated adapter already implemented and mocked-tested; activates the
  moment a key is added — no code change, no CC for the free 2,500 queries).
- Google News RSS is an undocumented best-effort endpoint: 0 results means
  "no candidates", never "the news does not exist" (contract-tested).
- Snippets remain DISCOVERY_ONLY; only opened pages can become evidence
  (unchanged, tested at the SourceBundle layer).

## Known limitations

- Brave and Serper are implemented adapters but unkeyed in this environment;
  their live behavior is contract-tested offline only. Provider routing is
  configuration, not code: adding a key to `.env` activates them.
- The live audit's BTA-429 / Bing-consent observations are environment history; the taxonomy names every such state explicitly instead of collapsing them into "no results".
- `ddgs` is the first approved non-stdlib runtime dependency (user-site install; recorded in pyproject as optional extra `search`).
- Snippet→claim promotion remains forbidden at the SourceBundle layer (unchanged, tested there).
