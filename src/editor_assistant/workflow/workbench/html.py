"""M3A HTML rendering: Bulgarian-first UI, stdlib only, fully escaped.

All dynamic content goes through esc(); only http/https URLs become links.
"""

from __future__ import annotations

import html as html_mod
import urllib.parse

from editor_assistant.workflow import diff as diff_mod
from editor_assistant.workflow.cases import EDITING_WEIGHTS, TIME_BUCKETS
from editor_assistant.workflow.workbench import labels as lb

CSS = """
:root { --ink:#1a1a2e; --line:#d8d8e0; --bg:#f7f7fa; --accent:#0b5394; --warn:#b45309; --ok:#15803d; }
* { box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', sans-serif; color: var(--ink); background: var(--bg); margin: 0; }
header { background: var(--accent); color: #fff; padding: .8rem 1.2rem; }
header h1 { font-size: 1.15rem; margin: 0; }
main { max-width: 62rem; margin: 0 auto; padding: 1rem 1.2rem 3rem; }
a { color: var(--accent); }
table { border-collapse: collapse; width: 100%; background: #fff; }
th, td { border: 1px solid var(--line); padding: .45rem .6rem; text-align: left; vertical-align: top; font-size: .92rem; }
th { background: #eef1f6; }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: .7rem; font-size: .78rem; background: #e5e7eb; }
.badge.ok { background: #dcfce7; color: var(--ok); }
.badge.warn { background: #fef3c7; color: var(--warn); }
.badge.block { background: #fee2e2; color: #991b1b; }
.badge.info { background: #dbeafe; color: #1e40af; }
section.card { background: #fff; border: 1px solid var(--line); border-radius: .4rem; padding: 1rem 1.2rem; margin: 1rem 0; }
section.card h2 { font-size: 1.05rem; margin-top: 0; }
textarea { width: 100%; min-height: 16rem; font: inherit; }
input[type=text] { width: 100%; font: inherit; }
label { display: block; margin: .6rem 0 .2rem; font-weight: 600; }
button { font: inherit; background: var(--accent); color: #fff; border: 0; border-radius: .3rem; padding: .5rem 1.1rem; cursor: pointer; }
button.secondary { background: #6b7280; }
.btn { padding: .25rem .6rem; font-size: .82rem; }
.btn.danger { background: #991b1b; }
.btn.primary { background: var(--ok); }
details form { margin: .3rem 0 .1rem; }
.notice { padding: .6rem .9rem; border-radius: .3rem; margin: .6rem 0; }
.notice.error { background: #fee2e2; }
.notice.saved { background: #dcfce7; }
.warnbox { background: #fef3c7; border: 1px solid #f59e0b; padding: .6rem .9rem; border-radius: .3rem; margin: .5rem 0; }
.infobox { background: #e0f2fe; border: 1px solid #7dd3fc; padding: .6rem .9rem; border-radius: .3rem; margin: .5rem 0; }
.filters a { margin-right: .8rem; }
.filters .active { font-weight: 700; text-decoration: underline; }
.muted { color: #6b7280; font-size: .85rem; }
pre.draft { white-space: pre-wrap; font-family: Georgia, serif; background: #fafafa; border: 1px solid var(--line); padding: .8rem; }
.fact { border-bottom: 1px dotted var(--line); padding: .3rem 0; }
.loc { font-size: .8rem; color: var(--accent); }
dl.meta dt { font-weight: 600; margin-top: .4rem; }
dl.meta dd { margin: 0 0 .3rem; }
"""


def esc(value):
    return html_mod.escape(str(value if value is not None else ""), quote=True)


NAV = (
    ("queue", "/", "Случаи"),
    ("inbox", "/inbox", "Входящи"),
    ("sources", "/sources", "Източници"),
    ("intake", "/intake", "YouTube"),
)


def nav(active=""):
    parts = []
    for key, href, label in NAV:
        cls = ' style="color:#fff;font-weight:700"' if key == active else ""
        parts.append(f'<a href="{href}"{cls}>{esc(label)}</a>')
    return '<nav class="filters" style="color:#cbd5e1">' + " | ".join(parts) + "</nav>"


def page(title, body, active=""):
    return (
        '<!doctype html>\n<html lang="bg">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)} — Редакторски работен плот</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n"
        '<header><h1><a style="color:#fff;text-decoration:none" href="/">Редакторски работен плот</a>'
        ' <span class="muted" style="color:#cbd5e1">M4</span></h1>\n'
        f"{nav(active)}</header>\n"
        f"<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def _badge(text, cls=""):
    return f'<span class="badge {cls}">{esc(text)}</span>'


def readiness_badge(status):
    if status == "DRAFT_READY":
        return _badge(lb.readiness_label(status), "ok")
    if status in ("EDITOR_DECISION_REQUIRED", "RESEARCH_MORE"):
        return _badge(lb.readiness_label(status), "warn")
    if status == "NO_PUBLISHABLE_ANGLE":
        return _badge(lb.readiness_label(status), "block")
    return _badge(status or "—")


def filter_nav(active):
    parts = []
    for key, label in lb.FILTERS:
        cls = ' class="active"' if key == active else ""
        parts.append(f'<a{cls} href="/?filter={key}">{esc(label)}</a>')
    return '<nav class="filters">' + " | ".join(parts) + "</nav>"


def queue_table(rows, empty_text):
    if not rows:
        return f'<p class="muted">{esc(empty_text)}</p>'
    head = (
        "<tr><th>Случай</th><th>Заглавие / ъгъл</th><th>Състояние</th>"
        "<th>Проверка на фактите</th><th>Последна промяна</th></tr>"
    )
    body = []
    for row in rows:
        status_cell = readiness_badge(row["readiness_status"]) + _id_hint(row["readiness_status"])
        extra = []
        if row["final"]:
            extra.append(_badge("Финализиран", "ok"))
        if row["stale"]:
            extra.append(_badge("По-нова чернова", "warn"))
        if row["decision"]:
            dec = row["decision"].get("decision", "")
            extra.append(_badge("Решение: " + lb.DECISION_LABELS.get(dec, dec), "info"))
        if extra:
            status_cell += " " + " ".join(extra)
        title = row["headline"] or "—"
        gate = row["gate"]
        gate_cls = "ok" if gate == "FACTUAL_GATE_PASS" else "warn"
        body.append(
            "<tr>"
            f'<td><a href="/case/{esc(row["case_id"])}"><strong>{esc(row["case_id"])}</strong></a>'
            f'<br><span class="muted">{esc(lb.MODE_LABELS.get(row["mode"], row["mode"] or "—"))}</span></td>'
            f"<td>{esc(title)}</td>"
            f"<td>{status_cell}</td>"
            f"<td>{_badge(lb.gate_label(gate), gate_cls) if gate else '—'}</td>"
            f'<td class="muted">{esc(row["updated_at"] or "—")}</td>'
            "</tr>"
        )
    return f"<table>{head}{''.join(body)}</table>"


def render_queue(queue, active_filter="all", message="", error=""):
    sections = []
    if active_filter == "all":
        sections.append(("<h2>Пилотни случаи (LIVE)</h2>", queue["live"]))
        sections.append(("<h2>Сравнителен еталон (без усилийни показатели)</h2>", queue["dryrun"]))
    else:
        merged = queue["live"] + queue["dryrun"]
        sections.append(
            (f"<h2>{esc(dict(lb.FILTERS).get(active_filter, active_filter))}</h2>", merged)
        )
    body = [filter_nav(active_filter)]
    if message:
        body.append(f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.append(f'<div class="notice error">{esc(error)}</div>')
    for heading, rows in sections:
        shown = [r for r in rows if active_filter == "all" or r["filter"] == active_filter]
        body.append(heading)
        body.append(queue_table(shown, "Няма случаи в тази категория."))
    body.append(
        '<p class="muted">Работният плот не публикува автоматично: финализирането е '
        "изрично действие на редактора и не променя AI черновите.</p>"
    )
    return page("Опашка", "\n".join(body), active="queue")


def _diff_section(view):
    wc = view["wc"]
    case = view["case"]
    if not wc or view["stale"]:
        return ""
    diff = diff_mod.diff_draft_final(
        case.get("draft_headline", ""),
        case.get("draft_text", ""),
        wc.get("headline", ""),
        wc.get("body", ""),
    )
    cls = diff_mod.classify_diff(diff)
    dom = cls["dominant"]
    dom_label = {
        "FACT": "Променени факти",
        "HEADLINE": "Заглавие",
        "STRUCTURE": "Структура",
        "STYLE": "Стил",
        "TONE": "Тон",
        "OTHER": "Друго",
    }.get(dom, dom)
    counts = cls["counts"]
    if not any(counts.values()) or (
        dom == "OTHER" and all(counts[c] == 0 for c in counts if c != "OTHER")
    ):
        return ""
    items = [
        f'<span class="badge info">Водеща категория: {esc(dom_label)}</span>',
        f'<span class="badge">Изречения: +{int(diff["sentences"]["added_count"])} / −{int(diff["sentences"]["removed_count"])}</span>',
        f'<span class="badge">Думи: {int(diff["word_delta"]):+d}</span>',
    ]
    if diff["headline_changed"]:
        items.insert(0, '<span class="badge warn">Заглавието е променено</span>')
    return (
        '<section class="card" id="diff"><h2>Разлики спрямо AI черновата</h2>'
        "<p>" + " ".join(items) + "</p>"
        '<p class="muted">Структурни: '
        + esc(counts.get("STRUCTURE", 0))
        + " · Факти: "
        + esc(counts.get("FACT", 0))
        + " · Стил: "
        + esc(counts.get("STYLE", 0))
        + " · Заглавие: "
        + esc(counts.get("HEADLINE", 0))
        + "</p></section>"
    )


def _final_surface(view):
    case = view["case"]
    if not case.get("final_text"):
        return ""
    diff = diff_mod.diff_draft_final(
        case.get("draft_headline", ""),
        case.get("draft_text", ""),
        case.get("final_headline", ""),
        case.get("final_text", ""),
    )
    cls = diff_mod.classify_diff(diff)
    dom = cls["dominant"]
    dom_label = {
        "FACT": "Променени факти",
        "HEADLINE": "Заглавие",
        "STRUCTURE": "Структура",
        "STYLE": "Стил",
        "TONE": "Тон",
        "OTHER": "Друго",
    }.get(dom, dom)
    return (
        '<section class="card" id="final"><h2>Финализиран материал (неизменим)</h2>'
        f"<h3>{esc(case.get('final_headline', ''))}</h3>"
        f'<pre class="draft">{esc(case.get("final_text", ""))}</pre>'
        '<dl class="meta">'
        f"<dt>Резултат</dt><dd>{esc(lb.EDITOR_OUTCOME_LABELS.get(case.get('editor_outcome'), case.get('editor_outcome', '—')))}</dd>"
        f"<dt>Тежест на редакцията</dt><dd>{esc(lb.EDITING_WEIGHT_LABELS.get(case.get('editing_weight'), case.get('editing_weight', '—')))}</dd>"
        f"<dt>Спестено време</dt><dd>{esc(lb.TIME_BUCKET_LABELS.get(case.get('time_saved_estimate'), case.get('time_saved_estimate', '')) or '—')}</dd>"
        f"<dt>Водеща категория на корекциите</dt><dd>{esc(dom_label)}</dd>"
        + (
            "<dt>Предпочитание за AI начало</dt><dd>"
            + esc(
                lb.PREFER_AI_START_LABELS.get(
                    case.get("prefer_ai_start"), case.get("prefer_ai_start")
                )
            )
            + "</dd>"
            if case.get("prefer_ai_start")
            else ""
        )
        + (
            "<dt>Оценка на готовността</dt><dd>"
            + esc(
                lb.READINESS_OUTCOME_LABELS.get(
                    case.get("readiness_outcome"), case.get("readiness_outcome", "")
                )
            )
            + "</dd>"
            if case.get("readiness_outcome")
            else ""
        )
        + "</dl>"
        + (
            f'<p class="muted">Бележка на редактора: {esc(case.get("notes"))}</p>'
            if case.get("notes")
            else ""
        )
        + "</section>"
    )


def _id_hint(code):
    """§6: internal enum ids stay visible next to the Bulgarian label."""
    return f' <span class="muted"><code>{esc(code)}</code></span>' if code else ""


def _warn_section(view):
    parts = []
    for warning in view["warnings"]:
        cls = "warnbox" if warning["level"] == "review" else "infobox"
        parts.append(f'<div class="{cls}">{esc(warning["text"])}</div>')
    trust = view.get("trust_note")
    if trust:
        parts.append(f'<div class="warnbox">{esc(trust)}</div>')
    if not parts:
        return ""
    return (
        '<section class="card" id="warnings"><h2>Статус и предупреждения</h2>'
        + "".join(parts)
        + "</section>"
    )


def _source_card(src):
    head = f"<strong>{esc(src['name'])}</strong>"
    chips = []
    if src.get("authority"):
        chips.append(_badge(lb.AUTHORITY_LABELS.get(src["authority"], src["authority"]), "info"))
    if src.get("type"):
        chips.append(_badge(src["type"]))
    meta = []
    if src.get("domain"):
        meta.append(esc(src["domain"]))
    if src.get("retrieved_at"):
        meta.append("достъпен: " + esc(src["retrieved_at"]))
    url_html = ""
    if src.get("url"):
        url_html = f'<div><a href="{esc(src["url"])}" rel="noopener noreferrer">{esc(src["url"])}</a></div>'
    elif src.get("url_raw"):
        url_html = f'<div class="muted">{esc(src["url_raw"])}</div>'
    claims = ""
    if src.get("claims"):
        items = "".join(f"<li>{esc(claim)}</li>" for claim in src["claims"])
        claims = f'<div class="muted">Съответстващи твърдения:</div><ul>{items}</ul>'
    note = f'<div class="muted">{esc(src["note"])}</div>' if src.get("note") else ""
    return (
        '<div class="fact">'
        f"<div>{head} {' '.join(chips)}</div>{url_html}"
        f'<div class="muted">{" · ".join(meta)}</div>{note}{claims}'
        "</div>"
    )


def _sources_surface(view):
    out = []
    out.append('<section class="card" id="sources"><h2>Източници</h2>')
    # §17: a transcript source states its trust level in the source panel.
    trust = view.get("trust")
    if trust:
        out.append(
            f"<p>Транскрипт: {_badge(lb.trust_label(trust), 'info')}"
            f' <span class="muted"><code>{esc(trust)}</code></span></p>'
        )
    if view["sources"]:
        out.extend(_source_card(source) for source in view["sources"])
    else:
        out.append('<p class="muted">Няма записани външни източници за този случай.</p>')
    attached = view["packet"]["attached"]
    if attached:
        out.append("<h3>Места в източниците (проверимо)</h3>")
        rows = []
        for fact_id, locs in sorted(attached.items()):
            fact = view["packet"]["facts"].get(fact_id) or {}
            loc_parts = []
            for loc in locs:
                name = (view["packet"]["names"].get(loc.get("source_id"), {}) or {}).get(
                    "name", loc.get("source_id", "")
                )
                loc_parts.append(
                    f'<span class="loc">{esc(name)} · '
                    f"{esc(lb.fmt_locator(loc.get('locator', '')))}</span>"
                )
            rows.append(
                f'<div class="fact"><div>{esc(fact.get("text") or fact_id)}</div>'
                + " ".join(loc_parts)
                + "</div>"
            )
        out.extend(rows)
    names = view["packet"]["names"]
    if names:
        out.append("<h3>Използвани доказателства</h3>")
        for source_id, info in sorted(names.items()):
            url = (
                f' — <a href="{esc(info["url"])}" rel="noopener noreferrer">{esc(info["domain"] or info["url"])}</a>'
                if info.get("url")
                else ""
            )
            out.append(f'<div class="fact">{esc(source_id)}: {esc(info["name"])}{url}</div>')
    out.append("</section>")
    return "".join(out)


def _decision_surface(view):
    """§14/§15: record an editor decision for a case with no publishable draft."""
    case = view["case"]
    if case.get("final_text"):
        return ""
    kind = view["kind"]
    if kind not in ("nostory", "research", "decision"):
        return ""
    decision = view["decision"]
    prior = ""
    if decision:
        dec = decision.get("decision", "")
        prior = (
            '<div class="infobox">Записано решение: <strong>'
            + esc(lb.DECISION_LABELS.get(dec, dec))
            + "</strong>"
            + (f" — {esc(decision.get('reason'))}" if decision.get("reason") else "")
            + f" ({esc(decision.get('updated_at', ''))})"
            + "</div>"
        )
    if kind == "nostory":
        intro = (
            "<p><strong>AI решението:</strong> Няма достатъчно силен и проверим "
            "новинарски ъгъл.</p>"
            '<p class="muted">Съгласни ли сте? Ако не — посочете пропуснатия ъгъл '
            "и решете дали да се направи още проучване.</p>"
        )
        missed_label = "Ако не: какъв ъгъл е пропуснат?"
        choices = ("NO_STORY_CONFIRMED", "RESEARCH_REQUESTED", "ANGLE_CHANGED")
        decisions = ("REJECT_STORY", "REQUEST_MORE_RESEARCH")
    elif kind == "decision":
        intro = (
            '<p class="muted">Данните не са достатъчни за уверен материал. '
            "Изберете изрично действие.</p>"
        )
        missed_label = "Какъв ъгъл е пропуснат? (по избор)"
        choices = ("RESEARCH_REQUESTED", "NO_STORY_CONFIRMED", "ANGLE_CHANGED")
        decisions = ("REQUEST_MORE_RESEARCH", "REJECT_STORY", "FORCE_BRIEF_FROM_VERIFIED")
    else:
        intro = (
            '<p class="muted">Нужна е още информация. M3A записва решението; '
            "реалното проучване идва с M3C.</p>"
        )
        missed_label = "Каква информация липсва? (по избор)"
        choices = ("RESEARCH_REQUESTED", "NO_STORY_CONFIRMED", "ANGLE_CHANGED")
        decisions = ("REQUEST_MORE_RESEARCH", "FORCE_BRIEF_FROM_VERIFIED", "REJECT_STORY")
    radios = "".join(
        '<label style="font-weight:400"><input type="radio" name="decision" '
        f'value="{esc(v)}"> ' + esc(lb.DECISION_LABELS[v]) + "</label>"
        for v in decisions
    )
    outcome_opts = "".join(
        f'<option value="{esc(v)}">{esc(lb.READINESS_OUTCOME_LABELS.get(v, v))}</option>'
        for v in choices
    )
    form = (
        f'<form method="post" action="/case/{esc(view["case_id"])}/decision">'
        "<label>Решение</label>"
        + radios
        + f'<label for="missed_angle">{esc(missed_label)}</label>'
        + '<input type="text" id="missed_angle" name="missed_angle">'
        + '<label for="reason">Причина (задължително — записва се за проверимост)</label>'
        + '<input type="text" id="reason" name="reason">'
        + '<label for="dec_outcome">Оценка за готовността (LIVE обучение)</label>'
        + f'<select id="dec_outcome" name="readiness_outcome"><option value=""></option>{outcome_opts}</select>'
        + '<p><button type="submit">Запиши решението</button>'
        + ' <span class="muted">Решението се записва без чернова.</span></p></form>'
    )
    return (
        '<section class="card" id="decision"><h2>Редакторско решение</h2>'
        + intro
        + prior
        + form
        + "</section>"
    )


def _finalize_surface(view):
    case = view["case"]
    kind = view["kind"]
    if case.get("final_text"):
        return ""
    if kind in ("nostory", "research", "decision"):
        return ""
    if case.get("track") == "GROUND_TRUTH_DRYRUN":
        return (
            '<section class="card" id="finalize"><h2>Финализиране</h2>'
            '<p class="muted">Еталонен случай (сравнителен еталон): няма усилийни показатели '
            "(време/тежест/резултат). Финализирането става чрез CLI еталона, не от работния плот.</p></section>"
        )
    base_draft_id = case.get("draft_id", "")
    time_opts = "".join(
        f'<option value="{esc(v)}">{esc(lb.TIME_BUCKET_LABELS.get(v, v))}</option>'
        for v in TIME_BUCKETS
    )
    weight_opts = "".join(
        f'<option value="{esc(v)}">{esc(lb.EDITING_WEIGHT_LABELS.get(v, v))}</option>'
        for v in EDITING_WEIGHTS
    )
    editor_outcome_opts = "".join(
        f'<option value="{esc(v)}">{esc(label)}</option>'
        for v, label in lb.EDITOR_OUTCOME_LABELS.items()
    )
    prefer_opts = "".join(
        f'<option value="{esc(v)}">{esc(label)}</option>' for v, label in lb.PREFER_AI_START_VALUES
    )
    wc = view["wc"]
    headline_val = (wc or {}).get("headline") or case.get("draft_headline", "")
    body_val = (wc or {}).get("body") or case.get("draft_text", "")
    ready = case.get("readiness_outcome", "")
    outcome_opts = "".join(
        f'<option value="{esc(v)}"{" selected" if ready == v else ""}>{esc(lb.READINESS_OUTCOME_LABELS[v])}</option>'
        for v in ("ANGLE_ACCEPTED", "ANGLE_CHANGED", "NO_STORY_CONFIRMED", "RESEARCH_REQUESTED")
    )
    stale_block = ""
    if view["stale"]:
        stale_block = (
            '<div class="warnbox">Финализирането е блокирано: работното копие е от '
            "по-стара AI версия. В работното поле по-горе отбележете „Приемам новата "
            "AI версия за основа“ и запазете, преди да финализирате.</div>"
        )
    return (
        '<section class="card" id="finalize"><h2>Финализиране</h2>'
        '<p class="muted">Финализирането записва окончателния материал и е изрично действие. '
        "AI черновата остава неизменима.</p>"
        + stale_block
        + f'<form method="post" action="/case/{esc(view["case_id"])}/finalize">'
        f'<input type="hidden" name="base_draft_id" value="{esc(base_draft_id)}">'
        '<label for="final_headline">Заглавие</label>'
        f'<input type="text" id="final_headline" name="headline" value="{esc(headline_val)}">'
        '<label for="final_body">Текст</label>'
        f'<textarea id="final_body" name="body">{esc(body_val)}</textarea>'
        "<label>Отговори за редакторска оценка (незадължително)</label>"
        + _answer_rows((wc or {}).get("review_answers") or {})
        + '<label for="editor_outcome">Резултат от редакцията (задължително)</label>'
        f'<select id="editor_outcome" name="editor_outcome"><option value=""></option>{editor_outcome_opts}</select>'
        '<label for="editing_weight">Колко редакция беше необходима? (задължително)</label>'
        f'<select id="editing_weight" name="editing_weight"><option value=""></option>{weight_opts}</select>'
        '<label for="time">Ориентировъчно спестено време</label>'
        f'<select id="time" name="time_saved_estimate"><option value=""></option>{time_opts}</select>'
        f'<label for="pref">{esc(lb.PREFER_AI_START_LABEL)}</label>'
        f'<select id="pref" name="prefer_ai_start"><option value=""></option>{prefer_opts}</select>'
        '<label for="outcome">Оценка на готовността (LIVE обучение)</label>'
        f'<select id="outcome" name="readiness_outcome"><option value=""></option>{outcome_opts}</select>'
        '<label for="outcome_note">Бележка към оценката</label>'
        f'<input type="text" id="outcome_note" name="readiness_note">'
        '<label for="final_notes">Бележка на редактора (незадължително)</label>'
        '<textarea id="final_notes" name="notes" style="min-height:5rem"></textarea>'
        '<p><button type="submit">Финализирай редакторската версия</button> '
        '<span class="muted">След финализирането материалът е неизменим.</span></p>'
        "</form></section>"
    )


def _draft_surface(view):
    """А. Immutable AI draft; Д. editor workspace (draft cases only).

    Special no-draft cases (NO_PUBLISHABLE_ANGLE / RESEARCH_MORE /
    EDITOR_DECISION_REQUIRED) never get an empty article editor: their draft
    surface only appears when a draft actually exists (harness §14/§15).
    Finalized cases get no workspace either: no action could apply it.
    """
    case = view["case"]
    draft = view["draft"]
    parts = []
    if draft["headline"] or draft["body"]:
        alt = [h for h in (draft.get("headlines") or []) if h and h != draft["headline"]]
        alt_html = ""
        if alt:
            items = "".join(f"<li>{esc(h)}</li>" for h in alt)
            alt_html = f'<p class="muted">Алтернативни заглавия от AI:</p><ul>{items}</ul>'
        parts.append(
            '<section class="card" id="draft"><h2>AI чернова (неизменима)</h2>'
            f"<h3>{esc(draft['headline'] or '—')}</h3>"
            f'<pre class="draft">{esc(draft["body"] or "")}</pre>'
            + alt_html
            + f'<p class="muted">Чернова: {esc(draft["draft_id"])} · '
            + esc(lb.MODE_LABELS.get(draft["mode"], draft["mode"] or "—"))
            + " · "
            + esc(lb.VOICE_LABELS.get(draft["voice"], draft["voice"] or "—"))
            + "</p>"
            + '<div class="muted">Черновата остава неизменима; всички редакторски '
            "промени се пазят отделно като работно копие.</div>" + "</section>"
        )
    if view["kind"] in ("nostory", "research", "decision"):
        return "".join(parts)
    if case.get("final_text"):
        return "".join(parts)
    wc = view["wc"]
    note = ""
    rebase = ""
    if view["stale"]:
        note = (
            '<div class="warnbox">Междувременно е генерирана по-нова AI версия. '
            "Прегледайте разликите преди финализиране.</div>"
        )
        rebase = (
            '<label style="font-weight:400"><input type="checkbox" name="accept_base" '
            'value="1"> Приемам новата AI версия за основа (изчиства предупреждението и '
            "позволява финализиране; моят текст се запазва)</label>"
        )
    headline_val = (wc or {}).get("headline")
    if headline_val is None:
        headline_val = draft["headline"]
    body_val = (wc or {}).get("body")
    if body_val is None:
        body_val = draft["body"]
    answers = (wc or {}).get("review_answers") or {}
    parts.append(
        '<section class="card" id="workspace"><h2>Редакторско работно поле</h2>'
        + note
        + f'<form method="post" action="/case/{esc(view["case_id"])}/save">'
        + '<label for="headline">Заглавие</label>'
        + f'<input type="text" id="headline" name="headline" value="{esc(headline_val)}">'
        + '<label for="body">Текст</label>'
        + f'<textarea id="body" name="body">{esc(body_val)}</textarea>'
        + "<label>Отговори на редакторските въпроси (незадължително)</label>"
        + _answer_rows(answers)
        + rebase
        + '<p><button type="submit">Запази работно копие</button> '
        + '<span class="muted">Запазването не финализира и не променя AI черновата.</span></p>'
        + "</form></section>"
    )
    return "".join(parts)


def _special_surface(view):
    """§14/§15: for no-draft cases show what is known / missing / asked."""
    kind = view["kind"]
    if kind not in ("nostory", "research", "decision"):
        return ""
    packet = view["packet"]
    rounds = (view.get("research_rounds") or {}).get("research_rounds") or []
    known = [f.get("text", "") for f in packet.get("facts", {}).values() if f.get("text")]
    missing, questions = [], []
    for rec in rounds:
        for dim in rec.get("missing_dimensions") or []:
            if dim not in missing:
                missing.append(dim)
        for question in rec.get("research_questions") or []:
            if question not in questions:
                questions.append(question)
    if not missing:
        missing = [str(u) for u in packet.get("unknowns") or [] if str(u).strip()]
    parts = ['<section class="card" id="known"><h2>Какво е известно и какво липсва</h2>']
    if kind == "nostory":
        reason = (view["readiness"] or {}).get("reason")
        if reason:
            parts.append(f'<p class="muted">Причина от системата: {esc(reason)}</p>')
    if known:
        parts.append("<h3>Какво е известно</h3><ul>")
        parts.extend(f"<li>{esc(t)}</li>" for t in known[:12])
        parts.append("</ul>")
    else:
        parts.append('<p class="muted">Няма записани проверими факти.</p>')
    if missing:
        parts.append("<h3>Какво липсва</h3><ul>")
        parts.extend(f"<li>{esc(str(m))}</li>" for m in missing)
        parts.append("</ul>")
    if questions:
        parts.append("<h3>Въпроси за проучване</h3><ul>")
        parts.extend(f"<li>{esc(str(q))}</li>" for q in questions)
        parts.append("</ul>")
    parts.append("</section>")
    return "".join(parts)


def _answer_rows(answers, prefix="answer_"):
    rows = []
    for key, label in lb.ANSWER_LABELS.items():
        val = answers.get(key, "")
        radios = []
        for opt in ("YES", "NO", "CHANGE"):
            checked = " checked" if val == opt else ""
            radios.append(
                f'<label style="display:inline;font-weight:400;margin-right:1rem">'
                f'<input type="radio" name="{prefix}{key}" value="{opt}"{checked}> {esc(lb.VALUE_LABELS[opt])}</label>'
            )
        rows.append(f"<div><label>{esc(label)}</label>{''.join(radios)}</div>")
    return "".join(rows)


def render_case(view, message="", error=""):
    case = view["case"]
    status = (view["readiness"] or {}).get("status", "")
    head = (
        '<p><a href="/">← Опашка</a></p>'
        f'<h2 id="casehead">{esc(view["case_id"])} — '
        f"{esc(case.get('draft_headline') or case.get('final_headline') or '—')}</h2>"
        "<p>"
        + readiness_badge(status)
        + _id_hint(status)
        + " "
        + (
            _badge(
                lb.gate_label(view["gate"]), "ok" if view["gate"] == "FACTUAL_GATE_PASS" else "warn"
            )
            + _id_hint(view["gate"])
            if view["gate"]
            else ""
        )
        + " "
        + _badge(lb.TRACK_LABELS.get(case.get("track"), case.get("track") or ""))
        + " "
        + _badge(lb.MODE_LABELS.get(case.get("mode_selected"), case.get("mode_selected") or ""))
        + "</p>"
    )
    parts = [
        head,
        _warn_section(view),
        _diff_section(view),
        _draft_surface(view),
        _special_surface(view),
        _sources_surface(view),
        _finalize_surface(view),
        _decision_surface(view),
        _final_surface(view),
    ]
    if message:
        parts.insert(1, f'<div class="notice saved">{esc(message)}</div>')
    if error:
        parts.insert(1, f'<div class="notice error">{esc(error)}</div>')
    return page(view["case_id"], "\n".join(parts), active="queue")


# ---------- M4A: sources + story inbox ----------


def _source_action_form(source_id, action, label, *, cls=""):
    return (
        '<form method="post" action="/sources" style="display:inline">'
        f'<input type="hidden" name="action" value="{esc(action)}">'
        f'<input type="hidden" name="source_id" value="{esc(source_id)}">'
        f'<button class="btn {esc(cls)}" type="submit">{esc(label)}</button></form>'
    )


def sources_table(rows):
    if not rows:
        return '<p class="muted">Още няма източници. Добавете първия по-долу.</p>'
    head = (
        "<tr><th>Източник</th><th>Тип</th><th>Статус</th><th>Приоритет</th>"
        "<th>Здраве</th><th>Следващо събиране</th><th>Действия</th></tr>"
    )
    body = []
    for row in rows:
        status_cls = {"active": "ok", "muted": "warn", "disabled": "block"}.get(
            row["effective_status"], ""
        )
        status_text = lb.source_status_label(row["effective_status"])
        if row.get("mute_expired"):
            status_text += f" (заглушаването изтече {row['muted_until']})"
        elif row["effective_status"] == "muted":
            status_text += f" до {row['muted_until']}"
        flags = []
        if not row["factual_authority"]:
            flags.append(_badge("само наблюдение", "info"))
        if row["factual_authority"]:
            flags.append(_badge("фактологичен авторитет", "ok"))
        if row.get("calendar"):
            flags.append(_badge("календар", "info"))
        if row.get("blocked_reason"):
            flags.append(_badge("забранен домейн", "block"))
        actions = [
            _source_action_form(
                row["source_id"],
                "enable" if row["effective_status"] != "active" else "disable",
                "Активирай" if row["effective_status"] != "active" else "Изключи",
            ),
            _source_action_form(
                row["source_id"],
                "authority" if not row["factual_authority"] else "monitoring_only",
                "Фактологичен авторитет" if not row["factual_authority"] else "Само наблюдение",
            ),
        ]
        if row["status"] == "muted":
            actions.append(_source_action_form(row["source_id"], "unmute", "Отмени заглушаването"))
        actions.append(_source_action_form(row["source_id"], "remove", "Премахни", cls="danger"))
        body.append(
            "<tr>"
            f"<td><strong>{esc(row['name'])}</strong><br>"
            f'<span class="muted">{esc(row["source_id"])} · '
            f"{esc(lb.source_collector_label(row['collector']))}"
            + (f" · {esc(row['url'] or row['query'])}" if (row["url"] or row["query"]) else "")
            + f"</span><br>{' '.join(flags)}"
            + (
                f'<div class="muted">{esc(row["blocked_reason"])}</div>'
                if row.get("blocked_reason")
                else ""
            )
            + "</td>"
            f"<td>{esc(lb.source_kind_label(row['kind']))}</td>"
            f"<td>{_badge(status_text, status_cls)}</td>"
            f"<td>{esc(lb.source_priority_label(row['priority']))}</td>"
            f"<td>{_health_cell(row)}</td>"
            f"<td>{esc(row['next_collection'])}</td>"
            f"<td>{' '.join(actions)}"
            + _source_edit_form(row)
            + _source_priority_form(row)
            + _source_mute_form(row)
            + "</td></tr>"
        )
    return f"<table>{head}{''.join(body)}</table>"


def _health_cell(row):
    """Operational health as a badge + the last success and new-item count."""
    health = row.get("health") or {}
    status = health.get("last_status") or "NEVER_RUN"
    cell = _badge(lb.source_health_label(status), lb.SOURCE_HEALTH_BADGES.get(status, ""))
    if health.get("last_success_at"):
        when = str(health["last_success_at"])[:16].replace("T", " ")
        cell += f'<div class="muted">последно успешно: {esc(when)}</div>'
    if health.get("last_new_count"):
        cell += f'<div class="muted">нови: {int(health["last_new_count"])}</div>'
    if status == "FAILED" and health.get("last_error"):
        cell += f'<div class="muted">{esc(str(health["last_error"])[:140])}</div>'
    return cell


def _source_edit_form(row):
    """Inline edit (no JS): name / url / query / note. `source_id` is immutable."""
    return (
        '<details style="margin-top:.3rem"><summary class="muted">Редактирай</summary>'
        '<form method="post" action="/sources">'
        f'<input type="hidden" name="action" value="edit">'
        f'<input type="hidden" name="source_id" value="{esc(row["source_id"])}">'
        f'<label>Име <input name="name" value="{esc(row["name"])}" required></label>'
        f'<label>Домейн на издателя <input name="domain" value="{esc(row["domain"])}"></label>'
        f'<label>URL <input name="url" value="{esc(row["url"])}"></label>'
        f'<label>Заявка <input name="query" value="{esc(row["query"])}"></label>'
        f'<label>Бележка <input name="note" value="{esc(row["note"])}"></label>'
        '<button class="btn" type="submit">Запази</button></form></details>'
    )


def _source_priority_form(row):
    options = "".join(
        f'<option value="{esc(key)}"{" selected" if key == row["priority"] else ""}>'
        f"{esc(label)}</option>"
        for key, label in lb.SOURCE_PRIORITY_LABELS.items()
    )
    return (
        '<details style="margin-top:.3rem"><summary class="muted">Промени приоритет</summary>'
        '<form method="post" action="/sources">'
        '<input type="hidden" name="action" value="priority">'
        f'<input type="hidden" name="source_id" value="{esc(row["source_id"])}">'
        f'<select name="value">{options}</select>'
        '<button class="btn" type="submit">Запази</button></form></details>'
    )


def _source_mute_form(row):
    return (
        '<details style="margin-top:.3rem"><summary class="muted">Заглуши до...</summary>'
        '<form method="post" action="/sources">'
        '<input type="hidden" name="action" value="mute">'
        f'<input type="hidden" name="source_id" value="{esc(row["source_id"])}">'
        '<label>До (ГГГГ-ММ-ДД) <input name="muted_until" placeholder="2026-09-25" required></label>'
        '<button class="btn" type="submit">Заглуши</button></form></details>'
    )


def add_source_form(values=None):
    """Add-source form. Values are echoed back so a refusal never loses typing."""
    values = values or {}
    kinds = "".join(
        f'<option value="{esc(key)}">{esc(label)}</option>'
        for key, label in lb.SOURCE_KIND_LABELS.items()
    )
    collectors = "".join(
        f'<option value="{esc(key)}">{esc(label)}</option>'
        for key, label in lb.SOURCE_COLLECTOR_LABELS.items()
    )
    priorities = "".join(
        f'<option value="{esc(key)}"{" selected" if key == "normal" else ""}>{esc(label)}</option>'
        for key, label in lb.SOURCE_PRIORITY_LABELS.items()
    )
    cadences = "".join(
        f'<option value="{esc(key)}">{esc(label)}</option>'
        for key, label in lb.SOURCE_CADENCE_LABELS.items()
    )
    return (
        '<h2>Добави източник</h2><form method="post" action="/sources">'
        '<input type="hidden" name="action" value="add">'
        f'<label>Идентификатор (латиница, тирета) <input name="source_id" value="{esc(values.get("source_id", ""))}" required></label>'
        f'<label>Име <input name="name" value="{esc(values.get("name", ""))}" required></label>'
        f'<label>Тип <select name="kind">{kinds}</select></label>'
        f'<label>Начин на събиране <select name="collector">{collectors}</select></label>'
        f'<label>Домейн на издателя <input name="domain" value="{esc(values.get("domain", ""))}"></label>'
        f'<label>URL <input name="url" value="{esc(values.get("url", ""))}"></label>'
        f'<label>Заявка (за търсене) <input name="query" value="{esc(values.get("query", ""))}"></label>'
        f'<label>Приоритет <select name="priority">{priorities}</select></label>'
        f'<label>Ритъм <select name="cadence">{cadences}</select></label>'
        f'<label>Бележка <input name="note" value="{esc(values.get("note", ""))}"></label>'
        + (
            '<label><input type="checkbox" name="calendar" value="1"> календарен източник '
            "(предстоящи събития са стойността)</label>"
            '<label><input type="checkbox" name="monitoring_only" value="1"> само наблюдение '
            "(не се използва като фактологичен авторитет)</label>"
            '<button class="btn primary" type="submit">Добави</button></form>'
        )
    )


def render_sources(view, message="", error="", values=None):
    summary = view["summary"]
    body = [
        (
            f'<p class="muted">Източници: {summary["total"]} · активни {summary["active"]} · '
            f"заглушени {summary['muted']} · изключени {summary['disabled']} · "
            f"само наблюдение {summary['monitoring_only']}</p>"
        ),
        (
            '<p class="muted">Събирането се изпълнява от cron (еднократна команда '
            "<code>newsroom collect</code>); тук се управлява кои източници се събират и как. "
            "Предварителен преглед без мрежа: <code>newsroom collect --dry-run</code>.</p>"
        ),
    ]
    if message:
        body.append(f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.append(f'<div class="notice error">{esc(error)}</div>')
    body.append(sources_table(view["rows"]))
    body.append(add_source_form(values))
    body.append(_domains_section(view["blocked"]))
    body.append(_defaults_section())
    return page("Източници", "\n".join(body), active="sources")


def _defaults_section():
    """Apply the default catalogue additively — never a silent overwrite (A2)."""
    return (
        '<section class="card" id="defaults"><h2>Подразбиращи се източници</h2>'
        '<p class="muted">Добавя само липсващите източници от подразбиращия се набор. '
        "Никога не променя вече наличните ви настройки и не включва изключени източници.</p>"
        '<form method="post" action="/sources" style="display:inline">'
        '<input type="hidden" name="action" value="defaults_preview">'
        '<button class="btn" type="submit">Преглед (без запис)</button></form> '
        '<form method="post" action="/sources" style="display:inline">'
        '<input type="hidden" name="action" value="defaults_apply">'
        '<button class="btn primary" type="submit">Приложи липсващите</button></form>'
        "</section>"
    )


def _domains_section(view):
    """Compact editor-owned blocked-domain policy (A5)."""
    domains = view.get("domains") or []
    rows = "".join(
        "<li><code>"
        + esc(domain)
        + "</code> "
        + '<form method="post" action="/sources" style="display:inline">'
        + '<input type="hidden" name="action" value="domain_remove">'
        + f'<input type="hidden" name="domain" value="{esc(domain)}">'
        + '<button class="btn danger" type="submit">Премахни</button></form></li>'
        for domain in domains
    )
    if not rows:
        rows = '<li class="muted">Няма забранени домейни.</li>'
    return (
        '<section class="card" id="domains"><h2>Забранени домейни</h2>'
        '<p class="muted">Широките заявки (Google News/търсене) никога не внасят елементи от '
        "тези домейни. Директен източник от забранен домейн се отказва.</p>"
        f"<ul>{rows}</ul>"
        '<form method="post" action="/sources">'
        '<input type="hidden" name="action" value="domain_add">'
        '<label>Добави домейн <input name="domain" placeholder="example.bg" required></label>'
        '<button class="btn" type="submit">Забрани</button></form></section>'
    )


def _inbox_qs(filters, **overrides):
    params = {
        "status": filters.get("status") or "all",
        "source": filters.get("source_id") or "",
        "kind": filters.get("kind") or "",
        "priority": filters.get("priority") or "",
        "date": filters.get("date") or "",
        "authority": filters.get("authority") or "",
    }
    params.update({key: value for key, value in overrides.items() if value is not None})
    return urllib.parse.urlencode({key: value for key, value in params.items() if value})


def inbox_status_nav(view):
    """Status filter links; the default view is `NEW` (M4B §B4)."""
    filters = view["filters"]
    parts = []
    for key, label in lb.INBOX_STATUS_FILTERS:
        cls = ' class="active"' if filters["status"] == key else ""
        parts.append(f'<a{cls} href="/inbox?{_inbox_qs(filters, status=key)}">{esc(label)}</a>')
    return '<nav class="filters">' + " | ".join(parts) + "</nav>"


def _inbox_filter_form(view):
    filters = view["filters"]
    source_opts = ['<option value="">Всички източници</option>']
    for option in view.get("source_options") or []:
        selected = " selected" if filters["source_id"] == option["source_id"] else ""
        source_opts.append(
            f'<option value="{esc(option["source_id"])}"{selected}>{esc(option["name"])}</option>'
        )
    kind_opts = ['<option value="">Всички типове</option>'] + [
        f'<option value="{esc(key)}"{" selected" if filters["kind"] == key else ""}>'
        f"{esc(label)}</option>"
        for key, label in lb.SOURCE_KIND_LABELS.items()
    ]
    prio_opts = ['<option value="">Всички приоритети</option>'] + [
        f'<option value="{esc(key)}"{" selected" if filters["priority"] == key else ""}>'
        f"{esc(label)}</option>"
        for key, label in lb.SOURCE_PRIORITY_LABELS.items()
    ]
    auth_opts = "".join(
        f'<option value="{esc(value)}"{" selected" if filters["authority"] == value else ""}>'
        f"{esc(label)}</option>"
        for value, label in lb.INBOX_AUTHORITY_FILTERS
    )
    return (
        '<form method="get" action="/inbox" class="card" style="margin:.6rem 0">'
        '<input type="hidden" name="status" value="' + esc(filters["status"]) + '">'
        '<label>Открит от <select name="source">' + "".join(source_opts) + "</select></label>"
        '<label>Тип <select name="kind">' + "".join(kind_opts) + "</select></label>"
        '<label>Приоритет <select name="priority">' + "".join(prio_opts) + "</select></label>"
        '<label>Авторитет <select name="authority">' + auth_opts + "</select></label>"
        f'<label>Дата <input type="date" name="date" value="{esc(filters["date"])}"></label>'
        '<button class="btn" type="submit">Филтрирай</button></form>'
    )


def _pager(view):
    filters = view["filters"]
    page_no, page_count = view["page"], view["page_count"]
    if page_count <= 1:
        return ""
    parts = []
    if page_no > 1:
        parts.append(f'<a href="/inbox?{_inbox_qs(filters, page=page_no - 1)}">← Предишна</a>')
    parts.append(f'<span class="muted">Страница {page_no} / {page_count}</span>')
    if page_no < page_count:
        parts.append(f'<a href="/inbox?{_inbox_qs(filters, page=page_no + 1)}">Следваща →</a>')
    return '<nav class="filters">' + " | ".join(parts) + "</nav>"


def _collect_section(view):
    """«Събери новините сега» delegates to the same one-shot service as cron."""
    last = view.get("last_run")
    info = ""
    if last:
        when = str(last.get("finished_at") or "—")[:16].replace("T", " ")
        info = (
            f'<p class="muted">Последно събиране: {esc(when)} · '
            f"нови {int(last.get('new') or 0)} · "
            f"вече известни {int(last.get('duplicate') or 0)} · "
            f"източника с проблем {int(last.get('failed') or 0)}</p>"
        )
    parts = [
        '<section class="card" id="collect"><h2>Събиране</h2>',
        info,
        (
            '<form method="post" action="/inbox" style="display:inline">'
            '<input type="hidden" name="action" value="collect">'
            '<button class="btn primary" type="submit">Събери новините сега</button></form> '
        ),
        (
            '<form method="post" action="/inbox" style="display:inline">'
            '<input type="hidden" name="action" value="collect_preview">'
            '<button class="btn" type="submit">Пробен преглед (без мрежа)</button></form>'
        ),
    ]
    problems = view.get("problems") or []
    if problems:
        parts.append("<h3>Източници с проблем</h3><ul>")
        parts.extend(
            f"<li><strong>{esc(p['name'])}</strong> — {esc(p['detail'])}</li>" for p in problems
        )
        parts.append("</ul>")
    parts.append("</section>")
    return "".join(parts)


def _inbox_item(item):
    status_cls = {"NEW": "info", "SEEN": "", "IGNORED": "block"}.get(item["status"], "")
    actions = []
    for action, label, cls in (
        ("SEEN", "Прегледан", ""),
        ("NEW", "Нов", ""),
        ("IGNORED", "Игнорирай", "danger"),
    ):
        if action == item["status"]:
            continue
        actions.append(
            '<form method="post" action="/inbox" style="display:inline">'
            '<input type="hidden" name="action" value="status">'
            f'<input type="hidden" name="item_id" value="{esc(item["item_id"])}">'
            f'<input type="hidden" name="status" value="{esc(action)}">'
            f'<button class="btn {cls}" type="submit">{esc(label)}</button></form>'
        )
    actions.append(
        f'<a class="btn" href="{esc(item["url"])}" target="_blank" '
        'rel="noopener noreferrer">Отвори източника</a>'
    )
    published = (item["published_at"] or "")[:16].replace("T", " ")
    discovered = (item["discovered_at"] or "")[:16].replace("T", " ")
    when = []
    if published:
        when.append(f"публикувано: {esc(published)}")
    if discovered:
        when.append(f"открито: {esc(discovered)}")
    # Publisher identity is shown separately from the discovery definition: an
    # article found by an official source's monitoring query is still published
    # by whoever wrote it.
    publisher_kind = item.get("publisher_kind") or ""
    publisher_badge = _badge(
        lb.publisher_kind_label(publisher_kind),
        "ok" if publisher_kind == "official" else "info" if publisher_kind else "warn",
    )
    if item.get("factual_authority"):
        publisher_badge += " " + _badge("фактологичен авторитет", "ok")
    else:
        publisher_badge += " " + _badge("без авторитет", "warn")
    publisher_line = (
        f'<p>{publisher_badge} <span class="muted">издател: '
        f"{esc(item.get('publisher_domain') or 'неизвестен домейн')}</span></p>"
    )
    return (
        '<section class="card">'
        f'<h3><a href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">'
        f"{esc(item['title'])}</a></h3>"
        f'<p class="muted">открит от: {esc(item["source_name"])} · '
        f"{esc(lb.source_kind_label(item['source_kind']))} · "
        f"{esc(lb.source_priority_label(item['priority']))} приоритет</p>"
        + publisher_line
        + f'<p class="muted">{" · ".join(when)}</p>'
        + (f"<p>{esc(item['summary'][:300])}</p>" if item["summary"] else "")
        + f"<p>{_badge(lb.inbox_status_label(item['status']), status_cls)} "
        + " ".join(actions)
        + "</p></section>"
    )


def render_inbox(view, message="", error=""):
    counts = view["counts"]
    by_status = counts["by_status"]
    problems = view.get("problems") or []
    body = [
        (
            f"<p><strong>Днес:</strong> нови {by_status.get('NEW', 0)} · "
            f"прегледани {by_status.get('SEEN', 0)} · "
            f"игнорирани {by_status.get('IGNORED', 0)} · "
            f"източници с проблем {len(problems)}"
            f' <span class="muted">(показани {view["total"]} от филтъра)</span></p>'
        ),
        (
            '<p class="muted">Това са събрани кандидати, не доказателства и не готови '
            "материали. Нищо тук не е проверено фактологично.</p>"
        ),
        inbox_status_nav(view),
        _collect_section(view),
        _inbox_filter_form(view),
    ]
    if message:
        body.append(f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.append(f'<div class="notice error">{esc(error)}</div>')
    items = view["items"]
    if not items:
        body.append(
            '<p class="muted">Няма елементи за този филтър. Пуснете «Събери новините сега» '
            'или вижте <a href="/sources">източниците</a>.</p>'
        )
        return page("Входящи", "\n".join(body), active="inbox")
    body.extend(_inbox_item(item) for item in items)
    body.append(_pager(view))
    return page("Входящи", "\n".join(body), active="inbox")
