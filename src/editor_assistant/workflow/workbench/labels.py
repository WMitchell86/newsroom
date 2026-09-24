"""M3A: Bulgarian UI labels for stored internal statuses.

Storage keeps the existing stable enum vocabulary (harness §9); the UI
translates. Nothing here mutates any stored value.
"""

from __future__ import annotations

import re

READINESS_LABELS = {
    "DRAFT_READY": "Готово за редакторски преглед",
    "RESEARCH_MORE": "Нужна е още информация",
    "NO_PUBLISHABLE_ANGLE": "Няма достатъчно силна новина",
    "EDITOR_DECISION_REQUIRED": "Нужно е редакторско решение",
}

GATE_LABELS = {
    "FACTUAL_GATE_PASS": "Фактологичната проверка е премината",
    "FACTUAL_GATE_REVIEW": "Нужна е проверка на фактите",
}

READINESS_OUTCOME_LABELS = {
    "ANGLE_ACCEPTED": "Ъгълът е приет",
    "ANGLE_CHANGED": "Ъгълът е променен",
    "NO_STORY_CONFIRMED": "Потвърдено: няма новина",
    "RESEARCH_REQUESTED": "Поискано е още проучване",
}

# The four `readiness_answers` keys the canonical contract accepts
# (cases.READINESS_ANSWER_KEYS). `prefer_ai_start` is a separate contract field
# (`record_editor_final(prefer_ai_start=...)`) and must NOT be sent inside
# `readiness_answers`, so it lives in its own label block below.
ANSWER_LABELS = {
    "would_publish": "Бихте ли публикували материал по тази тема?",
    "angle_right": "Правилен ли е избраният ъгъл?",
    "headline_strong": "Достатъчно силно ли е заглавието?",
    "opening_engaging": "Грабва ли началото вниманието?",
}

PREFER_AI_START_LABEL = "Бихте ли предпочели да започнете от AI текста?"

# (stored enum value, Bulgarian label) — YES | MIXED | NO per the contract.
PREFER_AI_START_VALUES = (
    ("YES", "Да"),
    ("MIXED", "Частично"),
    ("NO", "Не"),
)

PREFER_AI_START_LABELS = dict(PREFER_AI_START_VALUES)

VALUE_LABELS = {
    "YES": "Да",
    "NO": "Не",
    "CHANGE": "Друг ъгъл",
}

EDITING_WEIGHT_LABELS = {
    "LIGHT": "Лека",
    "MODERATE": "Умерена",
    "HEAVY": "Сериозна",
    "REWRITE": "Пренаписване",
    "REJECTED": "Отхвърлен материал",
}

TIME_BUCKET_LABELS = {
    "<5 min": "под 5 мин",
    "5-15 min": "5–15 мин",
    "15-30 min": "15–30 мин",
    ">30 min": "над 30 мин",
}

EDITOR_OUTCOME_LABELS = {
    "ACCEPTED_FOR_EDIT": "Приет за редакция",
    "REJECTED": "Отхвърлен",
    "MIXED": "Частично",
}

MODE_LABELS = {
    "MODE_STANDARD_NEWS": "Стандартна новина",
    "MODE_BRIEF": "Кратка бележка",
    "MODE_EVENT_PREVIEW": "Преглед на събитие",
    "MODE_CULTURE_FEATURE": "Културен материал",
}

IDEA_STATUS_LABELS = {
    "NEW": "Нова идея",
    "DRAFT_REQUESTED": "Заявета за чернова",
    "FOLLOW_UP": "За последваща проверка",
    "IGNORED": "Игнорирана",
    "NO_PUBLISHABLE_ANGLE": "Без публикуем ъгъл",
}

SOURCE_TYPE_LABELS = {
    "council_transcript": "Протокол от общинския съвет",
    "upstream_press_release": "Съобщение/публикация",
    "youtube_intake": "YouTube материал",
    "editor_supplied": "Подадена от редактора",
}

VOICE_LABELS = {
    "VOICE_HOUSE": "Глас на сайта (HOUSE)",
    "VOICE_DESISLAVA_RECENT": "Глас Десислава (експериментален)",
}

TRACK_LABELS = {
    "LIVE_EDITORIAL_PILOT": "LIVE пилотен случай",
    "GROUND_TRUTH_DRYRUN": "Сравнителен еталон (без усилийни показатели)",
}

AUTHORITY_LABELS = {
    "PRIMARY": "Основен източник",
    "CORROBORATING": "Потвърждаващ източник",
    "DISCOVERY_ONLY": "Само за откриване (не доказателство)",
}

TRUST_LABELS = {
    "AUTO_CAPTION": "Автоматичен YouTube транскрипт",
    "HUMAN_TRANSCRIPT": "Човешка транскрипция",
    "HUMAN_VERIFIED": "Проверена транскрипция",
    "OFFICIAL_VERBATIM": "Официален дословен запис",
}

DECISION_LABELS = {
    "FORCE_BRIEF_FROM_VERIFIED": "Продължи с наличното (кратка бележка от проверените данни)",
    "REQUEST_MORE_RESEARCH": "Поискай още проучване",
    "REJECT_STORY": "Не публикувай",
}

FILTERS = (
    ("all", "Всички"),
    ("edit", "За редакция"),
    ("research", "Нужна информация"),
    ("decision", "Нужно решение"),
    ("nostory", "Без достатъчна новина"),
    ("finalized", "Финализирани"),
)


# ---------- M4A: editor-owned sources + story inbox ----------

SOURCE_KIND_LABELS = {
    "official": "Официален",
    "media": "Медия",
    "national": "Национален",
    "regional": "Регионален",
    "aggregator": "Агрегатор",
}

SOURCE_STATUS_LABELS = {
    "active": "Активен",
    "disabled": "Изключен",
    "muted": "Заглушен",
}

SOURCE_PRIORITY_LABELS = {"high": "Висок", "normal": "Нормален", "low": "Нисък"}

SOURCE_CADENCE_LABELS = {
    "each_run": "при всяко събиране",
    "daily": "всеки ден",
    "weekly": "седмично",
}

SOURCE_COLLECTOR_LABELS = {
    "rss": "Директна емисия",
    "google_news_rss": "Наблюдение чрез Google News",
    "youtube": "YouTube (още не се събира)",
    "web": "Уеб страница (още не се събира)",
}

#: Collection mode, derived from the collector — no new registry field (M4B.1 F7).
#: Source health for a monitoring query means the monitor worked, not that the
#: publisher's own website was directly checked.
COLLECTION_MODE_LABELS = {
    "rss": "Директна емисия",
    "google_news_rss": "Наблюдение чрез Google News",
    "youtube": "YouTube (още не се събира)",
    "web": "Уеб страница (още не се събира)",
}


def collection_mode_label(collector):
    """How the material is actually obtained for a source."""
    return COLLECTION_MODE_LABELS.get(collector or "", collector or "—")


INBOX_STATUS_LABELS = {"NEW": "Нов", "SEEN": "Прегледан", "IGNORED": "Игнориран"}

#: Source health as the editor sees it (operational, never an uptime dashboard).
SOURCE_HEALTH_LABELS = {
    "OK": "Успешно",
    "EMPTY": "Празно",
    "FAILED": "Проблем",
    "NEVER_RUN": "Още не е събирано",
}

SOURCE_HEALTH_BADGES = {"OK": "ok", "EMPTY": "", "FAILED": "block", "NEVER_RUN": ""}

#: M4B inbox filters — practical only, no semantic/topic filters before M4C.
INBOX_STATUS_FILTERS = (
    ("NEW", "Нови"),
    ("all", "Всички"),
    ("SEEN", "Прегледани"),
    ("IGNORED", "Игнорирани"),
)

#: Filters on the item's **publisher**, not on the monitoring definition that
#: discovered it (M4A.1 correction).
INBOX_AUTHORITY_FILTERS = (
    ("", "Всички издатели"),
    ("official", "Официален издател"),
    ("authority", "Издател с авторитет"),
    ("monitoring", "Издател без авторитет"),
)


# ---------- M4C: story identity ----------

#: Story *status* (workflow), distinct from the type badge «Нова история» /
#: «Ново развитие», which describes the material.
STORY_STATUS_LABELS = {"NEW": "Непрегледана", "SEEN": "Прегледана", "IGNORED": "Игнорирана"}

STORY_STATUS_FILTERS = (
    ("NEW", "Нови"),
    ("all", "Всички"),
    ("SEEN", "Прегледани"),
    ("IGNORED", "Игнорирани"),
)

#: Membership relations, as the editor reads them on the timeline.
STORY_RELATION_LABELS = {
    "ORIGIN": "начало",
    "SAME_STORY": "същата история",
    "NEW_DEVELOPMENT": "ново развитие",
    "RELATED_BACKGROUND": "свързан контекст",
}

STORY_DEVELOPMENT_LABEL = "Ново развитие"
STORY_NEW_LABEL = "Нова история"


def story_status_label(status):
    return STORY_STATUS_LABELS.get(status or "", status or "—")


def story_relation_label(relation):
    return STORY_RELATION_LABELS.get(relation or "", relation or "—")


PUBLISHER_UNKNOWN_LABEL = "Неизвестен издател"


def publisher_kind_label(kind):
    """Publisher kind label; an empty kind is an unapproved publisher."""
    if not kind:
        return PUBLISHER_UNKNOWN_LABEL
    return SOURCE_KIND_LABELS.get(kind, kind)


def source_health_label(status):
    return SOURCE_HEALTH_LABELS.get(status or "", status or "—")


def source_kind_label(kind):
    return SOURCE_KIND_LABELS.get(kind or "", kind or "—")


def source_status_label(status):
    return SOURCE_STATUS_LABELS.get(status or "", status or "—")


def source_priority_label(priority):
    return SOURCE_PRIORITY_LABELS.get(priority or "", priority or "—")


def source_collector_label(collector):
    return SOURCE_COLLECTOR_LABELS.get(collector or "", collector or "—")


def inbox_status_label(status):
    return INBOX_STATUS_LABELS.get(status or "", status or "—")


def readiness_label(status):
    return READINESS_LABELS.get(status or "", status or "—")


MODEL_BILLING_LABELS = {
    "free": "безплатен",
    "paid": "платен",
    "operator_declared": "собствена квота",
}


def route_billing_label(route):
    """Billing label for a model route on the operator page (free/paid/own quota)."""
    billing = str(route.get("billing") or "")
    return MODEL_BILLING_LABELS.get(billing, billing)


def gate_label(gate):
    return GATE_LABELS.get(gate or "", gate or "—")


def trust_label(trust):
    return TRUST_LABELS.get(trust or "", trust or "")


# ---------- display formatting (harness §16: human time, never milliseconds) ----------

_LOCATOR_TIME = re.compile(
    r"@t=(\d{1,2}:\d{2})(?::\d{2})?(?:\.\d+)?(?:[-\u2013](\d{1,2}:\d{2})(?::\d{2})?(?:\.\d+)?)?"
)


def fmt_locator(locator):
    """'seg1@t=08:42' -> '08:42'; 'seg1@t=08:42.250-09:17' -> '08:42–09:17'.

    Internal `segN@t=` wrappers and millisecond values stay hidden; anything
    unrecognized is returned unchanged.
    """
    text = str(locator if locator is not None else "")
    match = _LOCATOR_TIME.search(text)
    if not match:
        return text
    if match.group(2):
        return f"{match.group(1)}\u2013{match.group(2)}"
    return match.group(1)
