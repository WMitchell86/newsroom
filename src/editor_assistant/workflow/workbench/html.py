"""M3A HTML rendering: Bulgarian-first UI, stdlib only, fully escaped.

All dynamic content goes through esc(); only http/https URLs become links.
"""

from __future__ import annotations

import html as html_mod

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


def page(title, body):
    return (
        '<!doctype html>\n<html lang="bg">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)} — Редакторски работен плот</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n"
        '<header><h1><a style="color:#fff;text-decoration:none" href="/">Редакторски работен плот</a>'
        ' <span class="muted" style="color:#cbd5e1">M3A</span></h1></header>\n'
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
    return page("Опашка", "\n".join(body))


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
    return page(view["case_id"], "\n".join(parts))
