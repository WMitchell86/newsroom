# M4 — Default Source Stack Research
Verified against live public pages on 2026-09-20.

## Goal

Replace the current deliberately tiny 3-source seed with a useful regional-news default stack that covers the main Cherno­morie editorial areas without turning the inbox into an uncontrolled firehose.

Explicit exclusion:

```text
flagman.bg
```

Flagman must not be seeded and must also be filtered from broad monitoring/search collectors.

The user's own site `chernomorie-bg.com` must NOT be used as a current factual/discovery source for its own stories. It remains archive/style/duplicate-history only.

## Recommended source policy

1. Prefer direct official sources for primary facts.
2. Use strong media for discovery and secondary reporting.
3. Use broader local media mainly as monitoring/discovery until corroborated.
4. Never guess RSS endpoints.
5. If a direct source cannot be collected safely with existing generic collectors, use a constrained monitoring query or seed it disabled with a clear reason.
6. Do not write one custom scraper per source in this milestone.
7. First-time collection must not backfill months of old content into the inbox.
8. Calendars are different from news feeds: upcoming events may be useful even if their page was published months ago.

## Tier A — Core, frequent collection

| ID | Source | Purpose / rubric | Suggested flags | Preferred collection |
|---|---|---|---|---|
| `burgas-municipal-council` | Общински съвет – Бургас | local government, decisions, agendas | official, high, factual authority, every run | existing verified RSS `https://burgascouncil.org/last-update.xml` |
| `burgas-municipality` | Община Бургас | city, infrastructure, education, health, culture, sport | official, high, factual authority, every run | canonical `https://www.burgas.bg/bg/novini` |
| `pomorie-municipality` | Община Поморие | Pomorie, local government, culture, education | official, high, factual authority, every run | canonical `https://www.pomorie.bg/2026/` |
| `odmvr-burgas` | ОДМВР – Бургас | crime, accidents, public safety | official, high, factual authority, every run | official news page / verified RSS only if discovered |
| `bnr-burgas` | БНР Бургас | regional reporting, interviews, live developments | media, high, evidence-eligible secondary source, every run | publisher-constrained query or direct page |
| `bta-burgas` | БТА – област Бургас | regional/national cross-check, institutions, economy, culture | media, high, evidence-eligible secondary source, every run | regional BTA page / constrained query |
| `google-news-burgas-region` | Google News regional monitor | discover national/regional coverage outside fixed list | monitor, high, monitoring-only, every run | Bulgarian News RSS query; post-filter blocked domains |
| `chernomorski-far` | Черноморски фар | broad regional monitoring incl. Burgas/Pomorie/Nessebar | regional media, normal/high, monitoring-only, every run | direct generic collector or constrained query |
| `darik-burgas` | DarikNews – Бургас | breaking regional news, crime, infrastructure, tourism | regional media, normal, monitoring-only, every run | direct page or constrained query |

Recommended broad regional query concept:

```text
Бургас OR Поморие OR Несебър OR Созопол OR Царево OR Приморско
```

Implementation should use the current query planner/provider syntax rather than assuming a search-engine syntax. Always exclude blocked publishers, including `flagman.bg`.

## Tier B — Official rubric coverage, normally daily

### Government / justice / environment

| ID | Source | Rubrics | Flags | Canonical page |
|---|---|---|---|---|
| `pomorie-council` | Общински съвет – Поморие | municipal decisions | official, high, factual authority, daily | `https://ospomorie.bg/` |
| `burgas-regional-administration` | Областна администрация Бургас | region, infrastructure, institutions | official, normal/high, factual authority, daily | `https://bs.gov.bg/` |
| `burgas-prosecution` | Апелативна/окръжна прокуратура Бургас | crime, prosecutions, courts | official, high, factual authority, daily | `https://prb.bg/apburgas/bg/news/pressobsheniya` |
| `burgas-district-court` | Окръжен съд – Бургас | court decisions / measures | official, high, factual authority, daily | `https://burgas-os.justice.bg/bg/news1` |
| `riosv-burgas` | РИОСВ – Бургас | environment, pollution, protected areas | official, high, factual authority, daily | `https://riosv-burgas.bg/` |
| `rzi-burgas` | РЗИ – Бургас | health alerts, water, epidemiology | official, normal/high, factual authority, daily | `https://rzi-burgas.bg/aktualno/` |

### Education / science / health

| ID | Source | Rubrics | Flags | Canonical page |
|---|---|---|---|---|
| `ruo-burgas` | РУО – Бургас | schools, education | official, normal, factual authority, daily | `https://www.ruoburgas.bg/` |
| `umbal-burgas` | УМБАЛ Бургас | local health services / hospital news | institution, normal, factual authority about own institution, daily | `https://www.mbalburgas.com/bg/novini` |
| `burgas-state-university` | БДУ „Проф. д-р Асен Златаров“ | education, science, medicine, research | institution, normal, factual authority about own institution, daily | `https://www.uniburgas.bg/index.php/bg/novini-m-bg` |
| `burgas-free-university` | Бургаски свободен университет | education, business, public events | institution, normal, factual authority about own institution, daily | `https://www.bfu.bg/` |

### Culture / events / sport / tourism

| ID | Source | Rubrics | Flags | Canonical page |
|---|---|---|---|---|
| `burgas-cultural-program` | Културна програма – Община Бургас | culture/events | official, normal/high, factual authority, daily | `https://www.burgas.bg/bg/kultura` |
| `burgas-sport-program` | Спортна програма – Община Бургас | sport/events | official, normal/high, factual authority, daily | `https://www.burgas.bg/bg/sportna-programa` |
| `gotoburgas-events` | GoToBurgas events | tourism, culture, sport, family events | official/tourism portal, normal, factual authority for event listings, daily | `https://info.gotoburgas.com/bg/events` |
| `rim-burgas` | Регионален исторически музей – Бургас | archaeology, history, exhibitions | institution, normal, factual authority about own work, daily | `https://www.burgasmuseums.bg/bg/news` |

### Economy / maritime / tourism infrastructure

| ID | Source | Rubrics | Flags | Canonical page |
|---|---|---|---|---|
| `port-burgas` | Пристанище Бургас ЕАД | maritime, economy, infrastructure | institution, normal, factual authority about own operations, daily | `https://port-burgas.bg/posts` |
| `burgas-airport-fraport` | Fraport / Burgas Airport | aviation, tourism, routes, infrastructure | institution, normal, factual authority about own operations, daily | `https://www.fraport-bulgaria.com/en/press-center/newsreleases.html` |

## Tier C — Coastal municipality coverage, daily / low-normal priority

| ID | Source | Flags | Canonical page |
|---|---|---|---|
| `nessebar-municipality` | official, low/normal, factual authority, daily | `https://nesebar.bg/` |
| `sozopol-municipality` | official, low/normal, factual authority, daily | `https://sozopol.org/` |
| `sozopol-council` | official, low/normal, factual authority, daily | `https://sozopol.obs-savet.eu/` |
| `tsarevo-municipality` | official, low/normal, factual authority, daily | `https://tsarevo.bg/aktualno/novini` |
| `primorsko-municipality` | official, low/normal, factual authority, daily | `https://primorsko.bg/` |

Do not add every municipality in Burgas Province at once. Aytos and Karnobat are verified and active, but are better as optional catalogue entries until editorial demand justifies them.

## Tier D — Useful optional sources, seeded disabled

| ID | Source | Why disabled initially |
|---|---|---|
| `burgasinfo` | BurgasInfo | useful local discovery but homepage mixes substantial national/noisy content |
| `burgas-library` | Регионална библиотека „Пейо Яворов“ | useful culture feed, but event overlap with GoToBurgas is high |
| `burgas-opera` | Държавна опера – Бургас | useful programme/news, high overlap with municipal cultural calendar |
| `aytos-municipality` | Община Айтос | verified active, but not core coastal coverage |
| `karnobat-municipality` | Община Карнобат | verified active, but not core coastal coverage |

## Media trust recommendation

```text
official / institution:
  factual_authority = true
  monitoring_only = false

BTA / BNR:
  factual_authority = true
  monitoring_only = false
  kind remains MEDIA

Darik / Черноморски фар / BurgasInfo:
  factual_authority = false
  monitoring_only = true
```

`factual_authority=true` means "eligible to support evidence within the source's remit", not "automatically sufficient for every high-risk claim".

## Important M4A corrections before scaling source count

### 1. Publisher/domain exclusion

Add an editor-owned blocked-domain policy.

Initial default:

```text
flagman.bg
```

Broad monitoring collectors must filter blocked domains before inbox insertion.

### 2. Cadence must be operational, not decorative

Verify whether `cadence=daily` actually changes collection eligibility. If display-only, add a tiny operational state store with:

```text
source_id
last_attempt_at
last_success_at
last_result
last_item_count
last_error
```

Keep it separate from source configuration.

### 3. Source health in Workbench

Show:
- Последно успешно
- Последен резултат
- Нови материали

Simple states:
`OK / EMPTY / FAILED / NEVER_RUN`.

### 4. Safe bootstrap

Ordinary news:
- max 10 recent items or 72-hour lookback on first collection.

Calendar/event sources:
- bounded future window, about 45 days.

### 5. Per-source caps

Until M4C dedup exists, one noisy source must not dump 50–100 items into one run.

## What not to do

Do not:
- build 25 custom scrapers;
- guess RSS URLs;
- add Flagman;
- use chernomorie-bg.com as current factual input;
- start story clustering;
- add AI ranking;
- start drafting;
- start Telegram;
- add every municipality in Burgas Province.

If a source cannot be collected cleanly using existing generic mechanisms, keep it disabled and document why.

## Recommended scale

```text
8–10 frequent sources
15–20 daily sources
3–5 disabled optional sources
```

This covers:
- Burgas city/council
- Pomorie/council
- coastal municipalities
- crime/accidents
- courts/prosecution
- environment
- health/social
- education/science
- culture/archaeology/events
- sport
- tourism
- airport/port/maritime economy
- regional media
- national/regional cross-check
- broad Bulgarian-news discovery
