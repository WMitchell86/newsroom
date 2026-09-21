# M4B.1 — Feed Stabilization Report

Closing the five concrete defects that `m4/M4_CHECKPOINT_REPO_REVIEW.md` found in
the M4A.1/M4B source-feed layer. Corrections only — no new milestone, no new
capability, no scheduler, no watermarks database.

Base: `075e81d` (M4A/M4B + publisher-authority correction). Gate before: 805 passed,
M3A smoke 25/25. Gate after: **859 passed**, ruff check/format clean, M3A smoke 25/25.

| review item | status | evidence |
|---|---|---|
| F1 rolling recency (one-run bootstrap hole) | **FIXED + real re-run proof** | §1 |
| F2 honest calendar semantics | **FIXED** | §2 |
| F3 real «Днес» counts | **FIXED** | §3 |
| F4/F5 authority conflict fails closed | **FIXED** | §4 |
| F6 blocked `entry.domain` refused pre-network | **FIXED** | §5 |
| F7 collection-mode wording | **FIXED** | §6 |

---

## 1. F1 — rolling recency (HIGH, the "run 2 backfills history" hole)

**Was.** `select_candidates(..., bootstrap=...)` applied the 72-hour news window
only while `bootstrap` was true. The second run of the same source had no recency
filter at all, only the 20-item cap, so everything the first run deliberately
excluded could come back as "new".

**Now** (`workflow/newsroom_run.py`):

```text
EVERY RUN     dated news items older than NEWS_LOOKBACK_HOURS (72 h) are excluded
FIRST RUN     additionally capped to BOOTSTRAP_MAX_NEWS (10)
EVERY RUN     per-source cap MAX_ITEMS_PER_SOURCE (20)
```

* the news filter is a **floor only** — a slightly future `published_at` (publisher
  clock skew) must not make a fresh item disappear;
* a candidate with a missing/unreadable date is **kept**, so a source is never
  emptied merely because a collector omitted a timestamp; the existing identity
  check is what prevents repeated insertion;
* no watermark store, no new state.

**Regression test** (`tests/test_newsroom_collect.py::test_rolling_recency_applies_on_every_run`):
a static provider with 10 recent + 10 ten-days-old items yields the 10 recent rows on
run 1 **and** run 2 (no old backfill), plus
`test_a_real_event_date_gets_the_event_window_but_a_publication_time_does_not` and
`test_undated_candidates_never_empty_a_source`.

**Real isolated re-runs** (throwaway `NEWSROOM_DIR`, 30 default sources, one internet
session, 2026-09-21):

```text
run 1  collected 91   · new 91  · duplicate 0
run 2  collected 123  · new 32  · duplicate 91      (--force, immediately after run 1)
        items older than 72 h in the store: 0
        published_at range: 2026-09-18 06:56 → 2026-09-21 06:18
```

The former `+100 new / +80 known` second-run pattern did not reproduce. The 32 new
rows are genuinely fresh items inside the 72-hour window that the provider returned
on the second call (the first corpus is 91, not 204, because the old second-run
backfill no longer exists). **Zero** stored row is older than the lookback window.

## 2. F2 — calendar semantics must be honest

**Was.** `calendar=True` applied a ±45-day window to `published_at`. For Google News
that field is the *article publication time*, so the window only proved that an
article dated in October survived — not that an October event did.

**Now.** A candidate may carry two optional, normalized fields that only a collector
that genuinely knows them may supply:

```text
event_at, event_end_at
```

```text
calendar source AND a real event date present  -> bounded ±45-day event window
otherwise                                      -> ordinary news recency rules
```

An article's `published_at` is never used as an event date. No calendar scraper was
written and no event date is inferred from prose. The two fields are optional string
columns on the inbox row (default `""`); every collector wired today leaves them empty,
which is why calendar sources now behave like news sources — the honest behaviour the
review asked for.

Tests: `test_a_real_event_date_gets_the_event_window_but_a_publication_time_does_not`
(a future `published_at` is **not** treated as an event date; a supplied `event_at`
gets the window even when the announcing article is months old).

## 3. F3 — «Днес» is a real day now

**Was.** The Workbench labelled lifetime inbox totals as «Днес».

**Now.** `inbox_store.today_counts()` computes the current `Europe/Sofia` calendar day
from `discovered_at` (arrival day, not `published_at`), reusing the existing
`source_health` timezone helper so cadence and "today" can never disagree. The page
shows:

```text
Днес (YYYY-MM-DD): нови X · прегледани Y · игнорирани Z
Непрегледани общо: N · източници с проблем M (показани K от филтъра)
```

`Непрегледани общо` is deliberately lifetime: unfinished `NEW` work must not be lost
just because it arrived yesterday. The default `NEW` view still includes older items.

Tests: `test_today_counts_use_the_sofia_arrival_day`,
`inbox_store.today_counts` / `unreviewed_count`.

## 4. F5 — a shared publisher domain with conflicting policy fails closed

**Was.** `authority_by_domain()` used `out.setdefault(domain, row)` over rows ordered
by `source_id`, so a shared domain silently resolved to whichever source ID sorted
first. Authority could depend on the alphabet.

**Now.** Same canonical domain + same `kind`/`factual_authority` is allowed (the
shipped catalogue does this for `burgas.bg` — three official entries). A differing
policy raises `RegistryError` and the run reports the configuration conflict:

```text
conflicting publisher policy for clash.bg: aaa-publisher (kind=official,
factual_authority=True) vs zzz-publisher (kind=official, factual_authority=False)
— fix the registry; authority must never be decided by source order
```

No "stronger authority wins", no alphabetical tie-break.

Test: `test_a_shared_publisher_domain_with_conflicting_policy_fails_closed` (conflict
on the authority flag **and** on the kind; same-policy sharing still resolves).

## 5. F6 — a declared blocked domain refuses the source before the network

**Was.** `blocked_reason()` checked the source `url` and the query text, but not the
registry `domain` field. A query source could declare `domain = flagman.bg` with a
query that never spells the name, so the source itself was not marked BLOCKED (its
results were still filtered — safe, but operationally misleading).

**Now.** `blocked_reason()` checks, before any network call:

```text
entry.url blocked  OR  entry.domain blocked  OR  query names a blocked domain
-> source status BLOCKED for the run
```

The result-level publisher filter stays as defence in depth.

Test: `test_a_declared_blocked_domain_refuses_an_otherwise_innocent_query` (the source
is refused and its fetcher is never called).

## 6. F7 — collection mode is derived, not implied

The Sources page now derives the collection mode from the existing `collector` field —
no new registry field:

```text
rss              -> Директна емисия
google_news_rss  -> Наблюдение чрез Google News
```

So "Прокуратура Бургас — OK" reads as *the monitoring query ran*, not *the
prosecution's own website was checked*. Labels live in
`workbench/labels.py::COLLECTION_MODE_LABELS` / `collection_mode_label()`.

## 7. Verification

```text
PYTHONPATH=src python3 -m pytest -q            -> 859 passed
ruff check src tests                            -> All checks passed
ruff format --check src tests                   -> formatted
PYTHONPATH=src python3 scripts/m3a_smoke.py     -> 25/25
real isolated runs                              -> see §1
```

Existing tests updated where the old behaviour was the defect:
`test_future_calendar_event_survives_bootstrap` → replaced by the honest-semantics
tests, and the Workbench «Днес» assertion now checks the new daily surface.

## 8. Verdicts

```text
ROLLING_NEWS_RECENCY    = PROVEN (two real immediate runs, 0 rows older than 72 h)
CALENDAR_DATE_SEMANTICS = HONEST (event window only with a real event date)
DAILY_COUNT_SEMANTICS   = PROVEN (Europe/Sofia arrival day, tested + shown)
PUBLISHER_AUTHORITY_CONFLICT = FAILS CLOSED (RegistryError, tested)
BLOCKED_DECLARED_DOMAIN = REFUSED BEFORE NETWORK (tested)
COLLECTION_MODE_LABEL   = DERIVED FROM COLLECTOR (no new field)
```

## 9. Not done (deliberately)

* no watermark/high-water-mark store — a rolling window is enough at this stage;
* no custom calendar scrapers and no event-date inference from prose;
* no new registry field for the collection mode (derived from `collector`);
* the stored-authority snapshot vs current-policy question (review "Deferred") is
  still deferred — recorded in `BACKLOG.md`, not solved here.
