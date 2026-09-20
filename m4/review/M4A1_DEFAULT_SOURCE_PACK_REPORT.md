# M4A.1 — Default Source Pack + Source Hardening (report)

**Status 2026-09-20: BUILT, LIVE-PROVEN, awaiting review/freeze.**
Base commit `dd93e89`. Scope: `m4/HARNESS_PROMPT_M4A1_SOURCE_PACK_M4B_INBOX.md`
PART A only (PART B is `M4B_DAILY_INBOX_REPORT.md`).

The milestone's object: the editor opens the Workbench in the morning and a real
regional newsroom is already being watched — without the harness inventing
outlets, guessing feed URLs, or silently overwriting the editor's settings.

## 1. What was built

| Piece | Module |
|---|---|
| Declarative default catalogue (35 entries) | `workflow/default_sources.py` |
| Additive catalogue apply (`preview`/`apply`) | `sources_registry.apply_defaults` + `sources defaults` CLI |
| Editor-owned blocked-domain policy | `workflow/blocked_domains.py` |
| Operational source health + last-run record | `workflow/source_health.py` |
| Real cadence, safe bootstrap, per-source caps, collection lock | `workflow/newsroom_run.py` |
| Health columns, blocked-domain editor, defaults controls | `workflow/workbench/{html,http,newsroom,labels}.py` |

## 2. The default stack (A1/A3)

**Active on a new install: 30 sources · catalogued but disabled: 5.**

```text
CORE (9, each_run)     burgas-municipal-council, burgas-municipality,
                       pomorie-municipality, odmvr-burgas, bnr-burgas,
                       bta-burgas, google-news-burgas-region,
                       chernomorski-far, darik-burgas
DAILY (21, daily)      pomorie-council, burgas-regional-administration,
                       burgas-prosecution, burgas-district-court, riosv-burgas,
                       rzi-burgas, ruo-burgas, umbal-burgas,
                       burgas-state-university, burgas-free-university,
                       burgas-cultural-program, burgas-sport-program,
                       gotoburgas-events, rim-burgas, port-burgas,
                       burgas-airport-fraport, nessebar-municipality,
                       sozopol-municipality, sozopol-council,
                       tsarevo-municipality, primorsko-municipality
DISABLED (5)           burgasinfo, burgas-library, burgas-opera,
                       aytos-municipality, karnobat-municipality
FORBIDDEN              flagman.bg (never a source; blocked as a domain)
NOT A SOURCE           chernomorie-bg.com (archive/style/duplicate only)
```

**Collector assignment (A4) — verified, never guessed.** Only one feed URL is
verified in the repository (`burgascouncil.org/last-update.xml`); every other
entry is a publisher/locality-constrained `google_news_rss` monitoring query
through the already-adopted News provider. No RSS endpoint was invented and no
bespoke scraper was written. Sources that would require scraping are not seeded.

**Trust (A6).** Official/institution and BTA/BNR → `factual_authority=true`,
`monitoring_only=false` (BTA/BNR keep `kind=media`). Darik / Черноморски фар /
BurgasInfo / the broad regional monitor → `monitoring_only=true`,
`factual_authority=false`. `factual_authority=true` means "eligible within its
remit", never "sufficient for a high-risk claim".

**Calendars (A9).** `burgas-cultural-program`, `burgas-sport-program`,
`gotoburgas-events`, `rim-burgas` carry `calendar=true`; their upcoming events
are the value, so the bootstrap uses a ±45-day window instead of a 72-hour one.

## 3. Additive apply (A2)

`sources defaults --preview` writes nothing. `sources defaults --apply` adds only
missing catalogue IDs and reports added/present/optional. It never re-enables a
disabled source and never changes an editor-modified entry. Repeated applies are
byte-idempotent. The same two actions exist on the Workbench «Източници» page.

## 4. Blocked-domain policy (A5)

* stored values are canonical hosts (`example.com`); scheme/`www.`/case/trailing
  dot are normalized away, and a URL carrying a path/query/port/credentials is
  **refused** — a pasted article link is a mistake, not a domain decision;
* matching is host-suffix based (`m.flagman.bg` is covered by `flagman.bg`);
* **the default policy (`flagman.bg`) is in force before any editor action**; the
  first edit materializes the stored list, after which even the default can be
  removed;
* a source whose own URL (or whose query text) targets a blocked domain is
  **refused at collection time** (`status=BLOCKED`);
* broad-monitor candidates are filtered **before** inbox insertion, and the run
  summary reports the filtered count;
* the Workbench has a compact «Забранени домейни» section with add/remove.

**A real finding while proving this live.** Google News RSS item links are
`news.google.com/rss/articles/...` redirects, so host-matching item URLs cannot
block a publisher. The publisher domain is only available on the item's
`<source url="https://…">` attribute. `GoogleNewsRSSProvider` now carries
`source_url` per result and the runner filters on **both** the item URL and the
publisher domain. Live proof: blocking `faragency.bg` (the publisher behind
Черноморски фар results) filtered 20 items from that source alone and 46 in one
run. Without this fix the policy would have looked correct in a fixture and done
nothing in production.

## 5. Real cadence + source health (A7/A8)

Operational state lives in its own store (`var/newsroom/source_health.json`),
**separate from source configuration**, with one record per source
(`last_attempt_at`, `last_success_at`, `last_status`, `last_item_count`,
`last_new_count`, `last_error`). `last_status` ∈ `OK` / `EMPTY` / `FAILED`
(`NEVER_RUN` = no record), so "nothing new" is never confused with "broken".

Cadence is operational:

```text
each_run  -> always due
daily     -> due only if no SUCCESSFUL collection on the current Europe/Sofia date
weekly    -> due only if no successful collection in the last 7 local days
muted/disabled -> never due
```

The Europe/Sofia day is computed with `zoneinfo` when tzdata is present, and with
the EU DST rule otherwise, so it never depends on the machine's clock config.
`newsroom collect --force` ignores cadence.

The Workbench «Източници» page shows **Здраве** (Последно успешно · Последен
резултат · Нови материали) and the «Следващо събиране» column now reports
`не е дължимо (днес вече е събрано)` once a daily source is done.

## 6. Safe bootstrap + caps (A9)

The first successful collection of a source does not backfill history:
news/press gets ≤72 h **or** the 10 newest items; calendars get a ±45-day window
and never lose a future event; every source is capped at 20 items per run.
`bootstrap_capped` is reported in the summary.

## 7. One shared collection lock (A10/B6)

`newsroom collect` and the Workbench «Събери новите сега» button take the same
`var/newsroom/collect.lock` (`O_CREAT|O_EXCL`, 1 h stale window). A second
concurrent run returns `locked=true` and does nothing, so two writers cannot
interleave the inbox or the health store. This is a lock, not a scheduler: the
repository still installs no timer.

## 8. Live proof (2026-09-20, isolated `/tmp/m4a1` runtime)

```text
sources defaults --preview   -> "ПРЕДГЛЕД (без запис): добавени 35 …"  (no file written)
sources defaults --apply     -> 35 added
sources list                 -> 35 total · 30 active · 0 muted · 5 disabled · 6 monitoring-only
newsroom collect --dry-run   -> "ПРОБЕН (без мрежа): 30 източника · заявки: 30"
newsroom collect (run 1)     -> 30 sources: 29 OK, 1 EMPTY, 0 failed
                                204 collected · 204 new · 0 errors
newsroom collect (run 2)     -> 180 collected · 100 new · 80 already-known
                                21 cadence-skipped, 0 errors   (idempotent identity)
newsroom collect --dry-run   -> "9 източника"  (only the each_run core is left due)
source_health.json           -> 30 records; e.g. bnr-burgas OK, 20 items, 10 new
last_run.json                -> new 100 / duplicate 80 / failed 0
GET /sources                 -> 200: health column, «Забранени домейни», flagman.bg pre-blocked
GET /inbox                   -> 200: summary + «Събери новите сега» + «Пробен преглед»
POST domain_add faragency.bg -> 303; next run filtered 20 items from Черноморски фар (EMPTY)
POST add flagman.bg source   -> refused: "домейнът на източника е забранен (flagman.bg)"
```

Not every source succeeded, and that is the honest result: `burgas-sport-program`
returned `EMPTY` (a real empty result, not a failure), and no source failed.

## 9. Verdicts

```text
DEFAULT_SOURCE_PACK     = PROVEN   (30 active / 5 disabled; real isolated run, not schema-only)
SOURCE_EXCLUSION_POLICY = PROVEN   (default in force, suffix match, publisher-domain filter,
                                    direct source refused; live 20+46 filtered)
SOURCE_CADENCE_ENGINEERING = PROVEN (each_run/daily/weekly on the Europe/Sofia day; live 21 skipped)
SAFE_BOOTSTRAP          = PROVEN   (72 h / 10 newest, ±45-day calendar window, 20-item cap)
EDITORIAL_EFFECTIVENESS = PENDING
```

## 10. Deliberate limits

* No custom scraper per source: sources that would need one are not seeded.
* No automatic scheduling: cron is the operator's, documented in `RUNBOOK.md`.
* `flagman.bg` stays out of every source and is blocked as a domain.
* `chernomorie-bg.com` is not used as a discovery/factual input.
* No AI ranking, no story clustering, no Telegram, no drafting.
