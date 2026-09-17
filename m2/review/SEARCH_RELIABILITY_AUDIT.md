# Search Reliability Foundation — M2S Track S

Verdict: **SEARCH_EXECUTION_ENGINEERING = PROMISING** — the execution layer now exists as a stable, tested, stdlib-only contract with explicit failure states and constraint preservation; it is not yet *live-proven* against a real API because no search API key was available in this environment (all live-provider paths are implemented and mocked-tested, and honestly report `SEARCH_CAPABILITY_UNAVAILABLE` without a key).

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

Not executed live: `BRAVE_SEARCH_API_KEY` is not configured in this environment,
and the harness explicitly forbids pretending success. The benchmark harness
point is ready (`run_search_operation` + audit records measure: target found in
top N, usable results, open success, failure type, latency). Running it live is
a one-command step once a key exists in `.env`. All provider behavior is
covered offline by mocked-transport tests (11 in `tests/test_search_foundation.py`).

## Known limitations

- Brave is the only implemented adapter; the interface is provider-generic by construction (A3's "abstraction matters more than the brand").
- The live audit's BTA-429 / Bing-consent observations are environment history, not reproducible here; the taxonomy now names every such state explicitly instead of collapsing them into "no results".
- Snippet→claim promotion remains forbidden at the SourceBundle layer (unchanged, tested there).
