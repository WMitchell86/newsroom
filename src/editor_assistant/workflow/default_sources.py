"""M4A.1 default source catalogue — the declarative new-install source stack.

One place owns the defaults, so a new install (and `sources defaults --apply`)
gets a useful regional stack instead of a scattering of hard-coded entries in the
CLI/UI. This module is **pure data**: it imports nothing from the registry and
performs no I/O, so it can never create an import cycle.

Rules the catalogue follows (see `m4/M4_DEFAULT_SOURCE_STACK_RESEARCH.md`):

* never guess an RSS endpoint — a source is collected through a generic collector
  that already exists (`rss` for the one verified feed, `google_news_rss` for a
  publisher/locality-constrained monitoring query);
* prefer direct official sources for primary facts, keep broad local media as
  monitoring-only until corroborated;
* `factual_authority=True` means "eligible to support evidence within its remit",
  not "sufficient for every high-risk claim";
* calendars differ from news: upcoming events stay useful even when the page is
  older, so those entries carry `calendar=True`;
* `flagman.bg` is never a source and the user's own site is never a discovery
  input (that is enforced by the blocked-domain policy, not here).
"""

from __future__ import annotations

#: Entry defaults shared by every catalogue row (`added_at`/`updated_at` are
#: filled by the registry so the store stays byte-stable between applies).
_BASE = {
    "collector": "google_news_rss",
    "status": "active",
    "priority": "normal",
    "cadence": "each_run",
    "factual_authority": True,
    "calendar": False,
    "url": "",
}

#: Core, every-run coverage: local government, crime, regional media and the
#: broad monitoring query that catches coverage outside the fixed list.
CORE = (
    {
        "source_id": "burgas-municipal-council",
        "name": "Общински съвет Бургас",
        "kind": "official",
        "collector": "rss",
        "url": "https://burgascouncil.org/last-update.xml",
        "priority": "high",
        "note": "Официалната емисия, вече използвана от системата (sources/live.py).",
    },
    {
        "source_id": "burgas-municipality",
        "name": "Община Бургас",
        "kind": "official",
        "query": "Община Бургас",
        "priority": "high",
        "note": "Наблюдение по име на институцията (няма потвърдена емисия).",
    },
    {
        "source_id": "pomorie-municipality",
        "name": "Община Поморие",
        "kind": "official",
        "query": "Община Поморие",
        "priority": "high",
        "note": "Официален местен източник; събира се като наблюдение.",
    },
    {
        "source_id": "odmvr-burgas",
        "name": "ОДМВР Бургас",
        "kind": "official",
        "query": "ОДМВР Бургас",
        "priority": "high",
        "note": "Престъпления, произшествия, обществена безопасност.",
    },
    {
        "source_id": "bnr-burgas",
        "name": "БНР Бургас",
        "kind": "media",
        "query": "БНР Бургас",
        "priority": "high",
        "note": "Регионална медия: вторичен източник, годен за доказателство.",
    },
    {
        "source_id": "bta-burgas",
        "name": "БТА — област Бургас",
        "kind": "media",
        "query": "БТА Бургас",
        "priority": "high",
        "note": "Национална агенция с регионално покритие: годна за доказателство.",
    },
    {
        "source_id": "google-news-burgas-region",
        "name": "Бургаски регион (наблюдение)",
        "kind": "aggregator",
        "query": "Бургас OR Поморие OR Несебър OR Созопол OR Царево OR Приморско",
        "priority": "high",
        "factual_authority": False,
        "note": "Само за наблюдение: открива покритие извън фиксирания списък.",
    },
    {
        "source_id": "chernomorski-far",
        "name": "Черноморски фар",
        "kind": "regional",
        "query": "Черноморски фар",
        "priority": "normal",
        "factual_authority": False,
        "note": "Регионална медия: само за наблюдение до потвърждение.",
    },
    {
        "source_id": "darik-burgas",
        "name": "DarikNews Бургас",
        "kind": "regional",
        "query": "DarikNews Бургас",
        "priority": "normal",
        "factual_authority": False,
        "note": "Регионална медия: само за наблюдение до потвърждение.",
    },
)

#: Official / institutional rubric coverage, normally collected once a day.
DAILY = (
    {
        "source_id": "pomorie-council",
        "name": "Общински съвет Поморие",
        "kind": "official",
        "query": "Общински съвет Поморие",
        "priority": "high",
        "note": "Общински решения.",
    },
    {
        "source_id": "burgas-regional-administration",
        "name": "Областна администрация Бургас",
        "kind": "official",
        "query": "Областна администрация Бургас",
        "note": "Регион, институции, инфраструктура.",
    },
    {
        "source_id": "burgas-prosecution",
        "name": "Прокуратура Бургас",
        "kind": "official",
        "query": "Прокуратура Бургас",
        "priority": "high",
        "note": "Прессъобщения, обвинения, съдебни действия.",
    },
    {
        "source_id": "burgas-district-court",
        "name": "Окръжен съд Бургас",
        "kind": "official",
        "query": "Окръжен съд Бургас",
        "priority": "high",
        "note": "Съдебни решения и мерки.",
    },
    {
        "source_id": "riosv-burgas",
        "name": "РИОСВ Бургас",
        "kind": "official",
        "query": "РИОСВ Бургас",
        "priority": "high",
        "note": "Околна среда, замърсяване, защитени територии.",
    },
    {
        "source_id": "rzi-burgas",
        "name": "РЗИ Бургас",
        "kind": "official",
        "query": "РЗИ Бургас",
        "note": "Здравни сигнали, вода, епидемиология.",
    },
    {
        "source_id": "ruo-burgas",
        "name": "РУО Бургас",
        "kind": "official",
        "query": "РУО Бургас",
        "note": "Училища и образование.",
    },
    {
        "source_id": "umbal-burgas",
        "name": "УМБАЛ Бургас",
        "kind": "official",
        "query": "УМБАЛ Бургас",
        "note": "Болница: авторитет за собствените си съобщения.",
    },
    {
        "source_id": "burgas-state-university",
        "name": "Университет „Проф. д-р Асен Златаров“",
        "kind": "official",
        "query": "Университет Асен Златаров Бургас",
        "note": "Образование, наука, медицина.",
    },
    {
        "source_id": "burgas-free-university",
        "name": "Бургаски свободен университет",
        "kind": "official",
        "query": "Бургаски свободен университет",
        "note": "Образование, бизнес, публични събития.",
    },
    {
        "source_id": "burgas-cultural-program",
        "name": "Културна програма — Бургас",
        "kind": "official",
        "query": "Културна програма Бургас",
        "calendar": True,
        "note": "Календарен източник: предстоящите събития са стойността.",
    },
    {
        "source_id": "burgas-sport-program",
        "name": "Спортна програма — Бургас",
        "kind": "official",
        "query": "Спортна програма Бургас",
        "calendar": True,
        "note": "Календарен източник: предстоящи събития.",
    },
    {
        "source_id": "gotoburgas-events",
        "name": "GoToBurgas — събития",
        "kind": "official",
        "query": "GoToBurgas събития",
        "calendar": True,
        "note": "Туризъм, култура, семейни събития.",
    },
    {
        "source_id": "rim-burgas",
        "name": "Регионален исторически музей Бургас",
        "kind": "official",
        "query": "Регионален исторически музей Бургас",
        "calendar": True,
        "note": "Археология, история, изложби.",
    },
    {
        "source_id": "port-burgas",
        "name": "Пристанище Бургас ЕАД",
        "kind": "official",
        "query": "Пристанище Бургас",
        "note": "Морска икономика, инфраструктура.",
    },
    {
        "source_id": "burgas-airport-fraport",
        "name": "Летище Бургас / Fraport",
        "kind": "official",
        "query": "Летище Бургас Fraport",
        "note": "Авиация, туризъм, маршрути.",
    },
    {
        "source_id": "nessebar-municipality",
        "name": "Община Несебър",
        "kind": "official",
        "query": "Община Несебър",
        "priority": "low",
        "note": "Черноморска община.",
    },
    {
        "source_id": "sozopol-municipality",
        "name": "Община Созопол",
        "kind": "official",
        "query": "Община Созопол",
        "priority": "low",
        "note": "Черноморска община.",
    },
    {
        "source_id": "sozopol-council",
        "name": "Общински съвет Созопол",
        "kind": "official",
        "query": "Общински съвет Созопол",
        "priority": "low",
        "note": "Общински решения.",
    },
    {
        "source_id": "tsarevo-municipality",
        "name": "Община Царево",
        "kind": "official",
        "query": "Община Царево",
        "priority": "low",
        "note": "Черноморска община.",
    },
    {
        "source_id": "primorsko-municipality",
        "name": "Община Приморско",
        "kind": "official",
        "query": "Община Приморско",
        "priority": "low",
        "note": "Черноморска община.",
    },
)

#: Verified-active but not core coastal coverage: catalogued, disabled until the
#: editor turns them on (`sources defaults --apply` never re-enables anything).
OPTIONAL = (
    {
        "source_id": "burgasinfo",
        "name": "BurgasInfo",
        "kind": "regional",
        "query": "BurgasInfo",
        "priority": "low",
        "factual_authority": False,
        "status": "disabled",
        "note": "Полезно откриване, но homepage смесва национално/шумно съдържание.",
    },
    {
        "source_id": "burgas-library",
        "name": "Регионална библиотека „Пейо Яворов“",
        "kind": "regional",
        "query": "Регионална библиотека Бургас",
        "priority": "low",
        "factual_authority": False,
        "status": "disabled",
        "note": "Културни събития с голямо застъпване с градския календар.",
    },
    {
        "source_id": "burgas-opera",
        "name": "Държавна опера — Бургас",
        "kind": "regional",
        "query": "Опера Бургас",
        "priority": "low",
        "factual_authority": False,
        "status": "disabled",
        "note": "Програма с голямо застъпване с културния календар.",
    },
    {
        "source_id": "aytos-municipality",
        "name": "Община Айтос",
        "kind": "official",
        "query": "Община Айтос",
        "priority": "low",
        "status": "disabled",
        "note": "Проверен активен източник, но не е част от ядрото крайбрежие.",
    },
    {
        "source_id": "karnobat-municipality",
        "name": "Община Карнобат",
        "kind": "official",
        "query": "Община Карнобат",
        "priority": "low",
        "status": "disabled",
        "note": "Проверен активен източник, но не е част от ядрото крайбрежие.",
    },
)


def _evaluate(rows, cadence):
    entries = []
    for row in rows:
        entry = {**_BASE, "cadence": cadence, **row}
        entries.append(entry)
    return tuple(entries)


#: The whole catalogue in apply order (core, then daily, then optional).
CATALOG = _evaluate(CORE, "each_run") + _evaluate(DAILY, "daily") + _evaluate(OPTIONAL, "daily")

#: New-install seed = only the entries that start active. Optional sources are
#: catalogued but not seeded, so a fresh install never silently watches 30 fires.
DEFAULT_ENTRIES = tuple(e for e in CATALOG if e.get("status", "active") == "active")

#: The disabled optionals, for `sources defaults --preview` reporting.
OPTIONAL_IDS = tuple(e["source_id"] for e in OPTIONAL)


def catalog_by_id():
    return {entry["source_id"]: dict(entry) for entry in CATALOG}


def required_ids():
    """The IDs the milestone contract requires the catalogue to contain."""
    return (
        "burgas-municipal-council",
        "burgas-municipality",
        "pomorie-municipality",
        "odmvr-burgas",
        "bnr-burgas",
        "bta-burgas",
        "google-news-burgas-region",
        "chernomorski-far",
        "darik-burgas",
        "pomorie-council",
        "burgas-regional-administration",
        "burgas-prosecution",
        "burgas-district-court",
        "riosv-burgas",
        "rzi-burgas",
        "ruo-burgas",
        "umbal-burgas",
        "burgas-state-university",
        "burgas-free-university",
        "burgas-cultural-program",
        "burgas-sport-program",
        "gotoburgas-events",
        "rim-burgas",
        "port-burgas",
        "burgas-airport-fraport",
        "nessebar-municipality",
        "sozopol-municipality",
        "sozopol-council",
        "tsarevo-municipality",
        "primorsko-municipality",
    )
