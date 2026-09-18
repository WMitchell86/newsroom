# TinyFish Provider Evaluation — M2S-R3 Parts A + B

Verdict (keyed re-run, same day): **ADAPTERS_LANDED_AND_TESTED ·
TINYFISH_INTEGRATION = READY · TINYFISH_EFFECTIVENESS = MEASURED (favored on
search: hit-rate + latency) · ROUTING_CHANGE = DEFERRED (PROVIDER_ORDER
unchanged; the routing decision moves to the editor, now with data).**

The first run below was keyless — recorded honestly as capability-unavailable
(no numbers fabricated); §2b holds the measured comparison.

Data: `var/search_benchmark/tinyfish_eval.json` (final live run, 2026-09-18) +
`var/search_benchmark/benchmark_results.json` (M2S-R2 reference baseline).
Harness: `tmp/tinyfish_benchmark.py`; adapters: `src/editor_assistant/workflow/search.py`;
tests: `tests/test_tinyfish_adapters.py` (23, offline, urlopen mocked at the
module boundary per repo convention).

## 1. Part A — what landed (all design constraints enforced in code)

| harness point | implementation |
|---|---|
| stdlib direct REST, no Monid/broker in runtime path | `TinyFishSearchProvider` / `TinyFishFetchProvider` over `urllib`, `TINYFISH_SEARCH_ENDPOINT` / `TINYFISH_FETCH_ENDPOINT` |
| same `SearchProvider` contract | `_empty()` skeleton, normalized results (rank/title/url/snippet/published_at/source_name/publisher) |
| failure taxonomy (A4) | 429 → `RATE_LIMITED` (bounded `MAX_PROVIDER_ATTEMPTS`, Retry-After respected); 402/403/outage/bad-JSON → `SEARCH_PROVIDER_ERROR` (never `NO_RESULTS`); provider error code extracted from body |
| no `count` param (A3) | `page`-based API honored; client-side truncation to `count`; `count_param_ignored=True` recorded on every record |
| request mapping (A3) | `country→location` (upper-cased), `search_language→language` (upper-cased), `freshness∈{pd,pw,pm,py}→recency_minutes{1440,10080,43200,525600}`, `domain_types→domain_type` (WEB→`web`, NEWS→`news`), `include_domains`/`exclude_domains` CSV-serialized, unknown freshness dropped with note |
| privacy guard A6 | `guard_public_query` (≤`PUBLIC_TEXT_LIMIT=400` chars + caption/transcript markers: cue clocks, `[музика]`, субтитри, auto-caption, транскрипт) → `PrivacyGuardError`; `guard_public_url` reuses `web_fetch.guard_target` (SSRF); fetch `purpose` guarded |
| source taxonomy | `SOURCE_ACCESS_BLOCKED` / `SOURCE_FETCH_FAILED` / `SOURCE_PARSE_FAILED` via `source_failure_category()` over existing `web_fetch` categories |
| narrow fallback (A5) | `fetch_with_fallback`: local opener first; TinyFish only on HTTP_ERROR/UNSUPPORTED/PARSE/TIMEOUT/UNREACHABLE or near-empty text (<`MIN_USABLE_TEXT=200`); `FETCH_BLOCKED_TARGET` → `SOURCE_ACCESS_BLOCKED`, **never forwarded**; failures keep the product taxonomy |
| registered-not-default (A8) | `"tinyfish": [CAP_WEB, CAP_NEWS]` in `PROVIDER_CAPABILITIES`; NOT in any `PROVIDER_ORDER`; reachable via explicit `SEARCH_PROVIDER=tinyfish` pin (missing key → `SEARCH_CAPABILITY_UNAVAILABLE`, not failure) |
| no secrets | key read from `TINYFISH_API_KEY` only; never logged/persisted |
| benchmark helpers (B1/B2) | identical cell shape for every provider incl. unavailable: status/latency/results_total/results_used/count_param_ignored/top3_domains/official_domain_share/dup_ratio/error_code/snippet_authority |

DISCOVERY_ONLY is structural: TinyFish returns snippets; the SourceBundle
provenance rule (promotion requires opened sources) lives in research.py and is
untouched.

## 2. Part B — live cells

**TinyFish: capability-unavailable (honest state, not zeros).** No
`TINYFISH_API_KEY` in env/`.env`. Evidence probe without credentials: search
endpoint **HTTP 401** (749 ms), fetch endpoint **HTTP 401** (739 ms) — endpoints
live, contract reachable, authorization missing. No TinyFish search/fetch
numbers are reported; unavailable ≠ provider-error ≠ 0-results.

**Incumbent chain baseline (same 20 cases, real network, no mocks):**
7 KNOWN + 7 UNSEEN (M2S-R2 cases, same needles) + 6 HARD (long-tail local
entities, numbers, procedural language).

- Operation status: 17/20 `SEARCH_COMPLETE`, 3 `SEARCH_INCOMPLETE`
  (DDGS degraded under repeated same-day runs — this was the 4th full run
  today; the R2 reference baseline holds 14/14 complete).
- Known-answer: **6/7** hits (miss: `Община Бургас бюджет 2026` — the degraded
  chain returned no candidates and recorded `SEARCH_INCOMPLETE` instead of
  pretending success).
- Latency: avg 2.8 s / median 2.4 s / min 1.3 s (RSS+Wikipedia) / max 9.4 s
  (DDGS web).
- Snippet authority held everywhere: candidates stayed discovery-only.

**Fetch challenge (10 URLs, local opener only):** 6/10 OK (22k–51k chars).
Misses, by category — exactly the cells where a robust third-party fetch
fallback would be evaluated once a key exists:

- `FETCH_HTTP_ERROR` ×2 — `burgas.bg/bg/priority-projects/`, NSI press PDF
- `FETCH_BLOCKED_TARGET` ×2 — `council.burgas.bg`, `mrrb.gov.bg`
  (unresolvable/protected targets; the SSRF guard refuses them, and a blocked
  target would equally never be forwarded to TinyFish)
- 6 opened OK incl. `grao.bg`, `brra.bg` (query-string ASPX state), `fsc.bg`,
  `e-gov.bg`, `moreto.net`

## 2b. Keyed re-run — measured cells (same day)

`TINYFISH_API_KEY` provided; same 20 cases + 10-URL fetch challenge, both
providers live in one run.

| metric | TinyFish | incumbent chain (same run) |
|---|---|---|
| search ops | **20/20 `SEARCH_OK`** | 18/20 `SEARCH_COMPLETE` |
| known-answer hits | **7/7** | 6/7 |
| latency avg / med / max | **0.3 s / 0.3 s / 0.9 s** | 3.2 s / 3.1 s / 5.1 s |
| stability | clean | DDGS degraded on its 5th same-day run (2 honest `SEARCH_INCOMPLETE`) |

TinyFish hit the known answer the degraded chain dropped
(`Община Бургас бюджет 2026`, needle `бюджет`). Snippets stay DISCOVERY_ONLY —
nothing is promoted from search output.

Fetch challenge: the fallback was exercised exactly where the design says —
only the 2 local `FETCH_HTTP_ERROR` cells (narrow triggers held; blocked
targets never forwarded). TinyFish fetch also failed both (`page_not_found` →
honest `SOURCE_FETCH_FAILED`), 0/2 opened; the local opener alone was 6/10.
The fetch column is measured as attempted 2/2, opened 0/2 — not
capability-unavailable.

## 3. Routing verdict

Measured state after the keyed re-run:

```
TINYFISH_INTEGRATION   = READY
TINYFISH_EFFECTIVENESS = MEASURED (favored on search: 7/7 vs 6/7 known hits, ~10x latency advantage)
ROUTING_CHANGE         = DEFERRED (PROVIDER_ORDER unchanged; editor decides with this data)
```

The keyless-run caveat (`NOT_EVALUATED` — the 401 probes prove failure
handling, not search quality) is resolved by §2b. `DEFERRED`, not
`NOT_JUSTIFIED`: TinyFish measured better on every search cell of this run,
but default routing is an editor decision; the adapter stays registered and
pin-addressable. What WOULD change the verdict back: a degraded TinyFish run
on these same cells, or an editor preference for the keyless chain. No
threshold, profile, or default-routing change was made.

## 4. Test coverage (23, all offline)

Capability-not-fabrication (missing key → unavailable; pin → single-provider
chain; registered-not-default), request shape (locale upper-casing, news
domain_type, freshness→recency_minutes, include/exclude domains, client-side
count + `count_param_ignored`), failure mapping (429→RATE_LIMITED with
Retry-After, 402/403→PROVIDER_ERROR with error_code, outage/bad-JSON→
PROVIDER_ERROR never NO_RESULTS), privacy guard (cue clocks, caption
vocabulary, length, purpose field, URL SSRF), fetch contract (record shape,
batch limit, per-URL error category), fallback routing (no trigger when local
sufficient, trigger on HTTP-error/parse-empty, blocked target never forwarded,
missing key explicit, fallback failure → source taxonomy), benchmark helpers
(cell shape, dup ratio, empty payload).

