"""M2.2 deterministic style features - stdlib only, no network, no Radar."""

from __future__ import annotations

import re
import statistics

_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)
_SENT_SPLIT_RE = re.compile(r"[.!?…]+")
_QUOTE_CLASS = "\"\u201c\u201e\u201d\u00ab\u00bb'"
_DIGIT_RE = re.compile(r"\d")
LOCATION_TOKENS = (
    "Бургас",
    "Бургаско",
    "Бургазлия",
    "Бургазлийка",
    "Бургаският",
    "Бургаската",
    "Несебър",
    "Созопол",
    "Поморие",
    "Айтос",
    "Карнобат",
    "Средец",
    "Царево",
    "Приморско",
    "Малко Търново",
    "Сунгурларе",
    "Камено",
    "Руен",
    "Странджа",
    "Черноморие",
    "Черноморец",
    "Слънчев бряг",
    "Летния театър",
    "Морската",
)
_BG_MONTHS = (
    "януари",
    "февруари",
    "март",
    "април",
    "май",
    "юни",
    "юли",
    "август",
    "септември",
    "октомври",
    "ноември",
    "декември",
)
_ADJ_SUFFIX_RE = re.compile(
    r"\b[\w\-]+(?:ен|на|ска|ски|ско|кия|ката|кото|ният|ната|ното|ните|ови|ева|ово|ев|ов)\b",
    re.IGNORECASE | re.UNICODE,
)
_FIRST_PERSON_RE = re.compile(
    r"\b(аз|ние|нашият|нашата|нашето|нашите|нашия|наши|моят|моята|моето|моите|мой|моя|мое)\b",
    re.IGNORECASE | re.UNICODE,
)
_VERB_LED_RE = re.compile(r"^(?:[А-ЯA-Z][\w\-]*(?:ха|аха|яха|иха|на|и|а))\b", re.UNICODE)
_INSTITUTION_LEAD_RE = re.compile(
    r"^(Община|Кмет|Кметът|Министър|Директор|Представител|Гост|Организатор|Жури|Екип|Деца|Ученици|Жители|Туристи|Полиция|Областна|Регионална|Съд|Прокуратура|Бургаската|Бургаският)"
)


def _words(text):
    return _WORD_RE.findall(text or "")


def _sentences(text):
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _paragraphs(body):
    return [p.strip() for p in (body or "").split("\n\n") if p.strip()]


def _density(count, total_chars):
    return round(count / max(1, total_chars) * 1000.0, 2)


def headline_features(headline):
    text = headline or ""
    return {
        "chars": len(text),
        "words": len(_words(text)),
        "has_colon": int(":" in text),
        "has_question": int("?" in text),
        "has_exclamation": int("!" in text),
        "has_dash": int(bool(re.search(r"[\-\u2013\u2014]", text))),
        "has_number": int(bool(_DIGIT_RE.search(text))),
        "has_quote": int(bool(re.search(r"[" + re.escape(_QUOTE_CLASS) + r"]", text))),
        "has_location": int(any(t in text for t in LOCATION_TOKENS)),
        "verb_led": int(bool(_VERB_LED_RE.match(text.strip()))),
    }


def body_features(body):
    text = body or ""
    paras = _paragraphs(text)
    lens = [len(p) for p in paras]
    sents = _sentences(text)
    wl = [len(_words(s)) for s in sents]
    qm = len(re.findall(r"[" + re.escape(_QUOTE_CLASS) + r"]", text))
    dg = len(_DIGIT_RE.findall(text))
    loc = sum(text.count(t) for t in LOCATION_TOKENS)
    return {
        "chars": len(text),
        "paragraphs": len(paras),
        "median_para_chars": int(statistics.median(lens)) if lens else 0,
        "first_para_chars": lens[0] if lens else 0,
        "last_para_chars": lens[-1] if lens else 0,
        "para_len_std": round(statistics.pstdev(lens), 1) if len(lens) > 1 else 0.0,
        "sentences": len(sents),
        "avg_sentence_words": round(statistics.mean(wl), 1) if wl else 0.0,
        "quote_mark_density": _density(qm, len(text)),
        "number_density": _density(dg, len(text)),
        "local_name_hits": loc,
        "has_question": int("?" in text),
        "question_in_first_400": int("?" in text[:400]),
        "has_exclamation": int("!" in text),
        "first_person_in_first_500": int(bool(_FIRST_PERSON_RE.search(text[:500]))),
    }


def opening_class(headline, body):
    paras = _paragraphs(body or "")
    first = paras[0] if paras else ""
    if first and _norm(first) == _norm(headline or ""):
        return "headline_repeated"
    head = first[:160]
    if re.search(
        r"\d{1,2}[\s\.,].{0,25}(?:" + "|".join(_BG_MONTHS) + r")|\d\.\d+\.\d+|\d{4}\s*г",
        head,
        re.IGNORECASE,
    ):
        return "event_date_first"
    if any(first.strip().startswith(t) for t in LOCATION_TOKENS) or re.match(
        r"^(В|На|От|До|За|При|Край)\s+[А-Я]", first.strip()
    ):
        return "place_first"
    if re.match(r"^([\"\u201c\u201e\u00ab]).*?[\"\u201d\u00bb]", first.strip()):
        return "quote_first"
    if _INSTITUTION_LEAD_RE.match(first.strip()):
        return "person_institution_first"
    return "immediate_fact"


def lexical_proxy_features(body):
    text = body or ""
    words = _words(text)
    adj = len(_ADJ_SUFFIX_RE.findall(text))
    return {
        "word_count": len(words),
        "adj_proxy_density": _density(adj, max(1, len(words))),
    }


def extract_style_features(record):
    headline = record.headline or ""
    body = record.body or ""
    paras = _paragraphs(body)
    first_para = paras[0] if paras else ""
    overlap = int(bool(first_para) and _norm(first_para) == _norm(headline))
    row = {
        "article_id": record.article_id,
        "url": record.url,
        "author": record.author,
        "category": record.category,
        "categories": list(record.categories or ()),
        "published_date": record.published_date,
        "has_caption": int(bool(record.caption)),
        "tag_count": len(record.tags or ()),
        "structured_quote_count": len(record.quotes or ()),
        "headline_repeat_in_opening": overlap,
        "opening_class": opening_class(record.headline, record.body),
    }
    for k, v in headline_features(record.headline).items():
        row["hl_" + k] = v
    for k, v in body_features(record.body).items():
        row["body_" + k] = v
    for k, v in lexical_proxy_features(record.body).items():
        row["lex_" + k] = v
    return row
