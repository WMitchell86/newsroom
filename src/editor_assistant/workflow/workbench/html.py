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
:root {
  --ink:#17202b; --line:#d9dee6; --bg:#f4f6f9; --card:#ffffff;
  --accent:#0f5aa8; --accent-dark:#0b447f; --ok:#15803d; --ok-bg:#dcfce7;
  --warn:#b45309; --warn-bg:#fef3c7; --bad:#991b1b; --bad-bg:#fee2e2;
  --info:#1e40af; --info-bg:#dbeafe; --muted:#5b6572;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; }
body { color: var(--ink); background: var(--bg); margin: 0; line-height: 1.45; }
header.top { background: linear-gradient(180deg, var(--accent), var(--accent-dark)); }
header.top { color: #fff; padding: .9rem 1.2rem .7rem; }
header.top h1 { font-size: 1.2rem; margin: 0; }
header.top a { color: #fff; text-decoration: none; }
header.top nav a { display: inline-block; padding: .35rem .85rem; margin: .15rem .1rem 0 0; }
header.top nav a { border-radius: 999px; opacity: .82; transition: background .15s, opacity .15s; }
header.top nav a:hover { opacity: 1; background: rgba(255, 255, 255, .14); }
header.top nav a.nav-active { background: #fff; color: var(--accent-dark); opacity: 1; font-weight: 700; }
.admin-label { color: rgba(255, 255, 255, .65); font-size: .78rem; margin-right: .3rem; }
main { max-width: 62rem; margin: 0 auto; padding: 1rem 1.2rem 3rem; }
a { color: var(--accent); }
table { border-collapse: collapse; width: 100%; background: var(--card); }
th, td { border: 1px solid var(--line); padding: .5rem .65rem; }
th, td { text-align: left; vertical-align: top; font-size: .92rem; }
th { background: #eef1f6; }
.badge { display: inline-block; padding: .2rem .65rem; border-radius: 999px; }
.badge { font-size: .82rem; font-weight: 600; background: #e5e7eb; }
.badge.ok { background: var(--ok-bg); color: var(--ok); }
.badge.warn { background: var(--warn-bg); color: var(--warn); }
.badge.block { background: var(--bad-bg); color: var(--bad); }
.badge.info { background: var(--info-bg); color: var(--info); }
section.card { background: var(--card); border: 1px solid var(--line); }
section.card { border-radius: .6rem; padding: 1rem 1.2rem; margin: 1rem 0; }
section.card h2 { font-size: 1.08rem; margin-top: 0; }
section.card.hero { border-left: 5px solid var(--accent); }
.hero-actions { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: .8rem; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); }
.stats { gap: .7rem; margin: .8rem 0; }
.stat { background: var(--card); border: 1px solid var(--line); border-radius: .6rem; }
.stat { padding: .7rem .9rem; }
.stat .num { font-size: 1.5rem; font-weight: 800; }
.stat .lbl { color: var(--muted); font-size: .85rem; }
.howto { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); }
.howto { gap: .7rem; margin-top: .6rem; }
.howto div { background: #f8fafc; border: 1px solid var(--line); border-radius: .5rem; }
.howto div { padding: .6rem .8rem; font-size: .9rem; }
textarea { width: 100%; min-height: 16rem; font: inherit; }
textarea { padding: .5rem .65rem; border: 1px solid var(--line); border-radius: .35rem; }
input[type=text], input:not([type]), select { padding: .45rem .6rem; }
input[type=text], input:not([type]), select { border: 1px solid var(--line); }
input[type=text], input:not([type]), select { border-radius: .35rem; font-size: .92rem; }
input[type=text]:focus, input:not([type]):focus, select:focus, textarea:focus { outline: 2px solid var(--accent); }
label { display: block; margin: .6rem 0 .2rem; font-weight: 600; }
fieldset { border: 1px solid var(--line); border-radius: .5rem; padding: .7rem .9rem; }
fieldset { margin: .8rem 0; background: #fcfdff; }
fieldset legend { font-weight: 700; padding: 0 .4rem; }
button { font: inherit; background: var(--accent); color: #fff; border: 0; }
button { border-radius: .35rem; padding: .55rem 1.2rem; cursor: pointer; }
button.secondary { background: #6b7280; }
button:hover { background: var(--accent-dark); }
button:disabled { opacity: .6; cursor: wait; }
.btn { padding: .3rem .7rem; font-size: .85rem; border-radius: .35rem; }
.btn.danger { background: var(--bad); }
.btn.primary { background: var(--ok); }
details form { margin: .3rem 0 .1rem; }
.notice { padding: .6rem .9rem; border-radius: .35rem; margin: .6rem 0; }
.notice.error { background: var(--bad-bg); border: 1px solid #fca5a5; }
.notice.saved { background: var(--ok-bg); border: 1px solid #86efac; }
.warnbox { background: #fef3c7; border: 1px solid #f59e0b; padding: .6rem .9rem; border-radius: .3rem; margin: .5rem 0; }
.infobox { background: #e0f2fe; border: 1px solid #7dd3fc; padding: .6rem .9rem; border-radius: .3rem; margin: .5rem 0; }
.filters a { margin-right: .8rem; }
.filters .active { font-weight: 700; text-decoration: underline; }
.muted { color: var(--muted); font-size: .85rem; }
pre.draft { white-space: pre-wrap; font-family: Georgia, serif; }
pre.draft { background: #fafafa; border: 1px solid var(--line); padding: .8rem; }
pre.draft { border-radius: .35rem; }
.fact { border-bottom: 1px dotted var(--line); padding: .3rem 0; }
.loc { font-size: .8rem; color: var(--accent); }
dl.meta dt { font-weight: 600; margin-top: .4rem; }
dl.meta dd { margin: 0 0 .3rem; }
.table-wrap { overflow-x: auto; }
#busy-overlay { display: none; position: fixed; inset: 0; z-index: 50; }
#busy-overlay { background: rgba(15,30,50,.55); align-items: center; }
#busy-overlay { justify-content: center; }
#busy-overlay div { background: #fff; border-radius: .6rem; padding: 1.2rem 1.6rem; }
@media (max-width: 768px) {
  main { padding: .8rem .7rem 2.5rem; }
  th, td { font-size: .85rem; padding: .4rem .45rem; }
  .hero-actions button { width: 100%; }
  section.card { padding: .85rem .9rem; }
}
"""


def esc(value):
    return html_mod.escape(str(value if value is not None else ""), quote=True)


#: Daily workflow first (what the editor opens every morning), then setup and
#: archive surfaces. «Случаи» is the frozen M3A queue — kept reachable but not
#: promoted; «YouTube» is a secondary source view.
NAV_DAILY = (
    ("home", "/", "Начало"),
    ("stories", "/stories", "Истории"),
    ("inbox", "/inbox", "Материали"),
    ("sources", "/sources", "Източници"),
)
NAV_ADMIN = (
    ("models", "/models", "AI модели"),
    ("queue", "/cases", "Случаи"),
    ("intake", "/intake", "YouTube"),
)
#: Back-compat alias table: every key ever used as ``active=`` still resolves.
NAV = (
    ("home", "/", "Начало"),
    ("stories", "/stories", "Истории"),
    ("inbox", "/inbox", "Материали"),
    ("sources", "/sources", "Източници"),
    ("models", "/models", "AI модели"),
    ("queue", "/cases", "Случаи"),
    ("intake", "/intake", "YouTube"),
)


def _nav_link(key, href, label, active=""):
    cls = ' class="nav-active"' if key == active else ""
    extra = ""
    if key in ("home", "stories", "inbox"):
        extra = ' data-daily="1"'
    return f'<a href="{href}"{cls}{extra}>{esc(label)}</a>'


def nav(active=""):
    daily = "".join(_nav_link(k, h, label, active) for k, h, label in NAV_DAILY)
    admin = "".join(_nav_link(k, h, label, active) for k, h, label in NAV_ADMIN)
    return (
        '<nav class="primary" aria-label="Ежедневна работа">' + daily + "</nav>"
        '<nav class="admin" aria-label="Настройки и архив">'
        '<span class="admin-label">Настройки и архив:</span>' + admin + "</nav>"
    )


def page(title, body, active=""):
    return (
        '<!doctype html>\n<html lang="bg">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)} — Дневен новинарски помощник</title>\n"
        f'<link rel="stylesheet" href="/static/style.css">\n<style>{CSS}</style>\n</head>\n<body>\n'
        '<header class="top"><h1><a href="/">Дневен новинарски помощник</a></h1>\n'
        '<p class="tagline">Какво е ново от вашите източници · прочетете · '
        "отбележете · напишете</p>\n"
        f"{nav(active)}</header>\n"
        f"<main>\n{body}\n</main>\n"
        '<div id="busy-overlay" role="status"><div>Събиране… моля, изчакайте.</div></div>\n'
        "<script>"
        "document.addEventListener('submit',function(e){"
        "var f=e.target;if(f.method&&f.method.toLowerCase()!=='post')return;"
        "var b=f.querySelector('button[type=submit]');"
        "if(!b||!b.dataset)return;"
        "if(b.dataset.danger){"
        "if(!confirm('Наистина ли?')){e.preventDefault();return;}}"
        "if(b.dataset.confirmRoute){"
        "var op=f.querySelector('select[name=op]');"
        "if(op&&op.value==='remove'&&!confirm('Наистина ли да премахна?')){e.preventDefault();return;}}"
        "if(b.dataset.busy){"
        "b.disabled=true;var o=document.getElementById('busy-overlay');"
        "if(o){o.style.display='flex';}"
        "}});</script>\n"
        "</body>\n</html>\n"
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


def filter_nav(active, base="/cases"):
    parts = []
    for key, label in lb.FILTERS:
        cls = ' class="active"' if key == active else ""
        href = f"{base}?filter={urllib.parse.quote(key)}"
        parts.append(f'<a{cls} href="{href}">{esc(label)}</a>')
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
    return f'<div class="table-wrap"><table>{head}{"".join(body)}</table></div>'


def render_home(stories, inbox, sources):
    """Daily landing page: «what is new, what do I do next».

    Read-only aggregation over the views the dedicated pages already compute.
    Keeps the editor's morning in one place: unreviewed counts, today's
    arrivals, the top new stories and the next step.
    """
    summary = (sources or {}).get("summary") or {}
    story_cards = (stories or {}).get("stories") or []
    counts = (stories or {}).get("counts") or {}
    new_stories = int(counts.get("NEW") or 0)
    total_stories = int((stories or {}).get("total_stories") or 0)
    today = ((inbox or {}).get("today") or {}).get("by_status") or {}
    new_materials = int((inbox or {}).get("unreviewed") or 0)
    today_new = int(today.get("NEW") or 0)
    today_date = ((inbox or {}).get("today") or {}).get("date") or "—"
    active_sources = summary.get("active", "—")
    top = story_cards[:5]
    if top:
        top_rows = "".join(
            "<li>"
            f'<a href="/stories/{esc(card.get("story_id", ""))}">'
            f"<strong>{esc(card.get('title') or card.get('story_id', ''))}</strong></a>"
            f' <span class="muted">· {esc(" · ".join(card.get("publishers") or []))}</span>'
            "</li>"
            for card in top
        )
        top_block = f"<ol>{top_rows}</ol>"
    else:
        top_block = (
            '<p class="muted">Още няма групирани истории. Ако материалите са събрани, '
            "натиснете „Обнови историите“.</p>"
        )
    hero = (
        '<section class="card hero"><h2>Добро утро — ето какво е ново</h2>'
        '<p class="muted">Дневен новинарски помощник: събира материали от вашите '
        "източници, групира ги в истории и ви оставя решението. "
        "Нищо не се публикува автоматично.</p>"
        '<div class="stats">'
        f'<div class="stat"><div class="num">{new_stories}</div>'
        '<div class="lbl">нови истории за преглед</div></div>'
        f'<div class="stat"><div class="num">{new_materials}</div>'
        '<div class="lbl">непрегледани материали</div></div>'
        f'<div class="stat"><div class="num">{today_new}</div>'
        f'<div class="lbl">пристигнали днес ({esc(today_date)})</div></div>'
        f'<div class="stat"><div class="num">{esc(active_sources)}</div>'
        '<div class="lbl">активни източници</div></div>'
        "</div>"
        '<div class="hero-actions">'
        f'<a href="/stories"><button class="btn primary" type="button">'
        f"Прегледай историите ({new_stories})</button></a> "
        f'<a href="/inbox"><button class="btn" type="button">'
        f"Към материалите ({new_materials})</button></a> "
        "</div></section>"
    )
    latest = (
        '<section class="card"><h2>Най-нови истории</h2>'
        f"{top_block}"
        f'<p class="muted">Общо истории: {total_stories} · '
        '<a href="/stories">всички истории</a></p></section>'
    )
    howto = (
        '<section class="card"><h2>Как се работи (3 стъпки)</h2>'
        '<div class="howto">'
        "<div><strong>1. Събери</strong><br>Натисни „Събери новините сега“ "
        'в <a href="/inbox">Материали</a>.</div>'
        "<div><strong>2. Прегледай</strong><br>Отвори история в "
        '<a href="/stories">Истории</a> и прочети материалите.</div>'
        "<div><strong>3. Отбележи</strong><br>Маркирай като прегледана, "
        "игнорирай или върни за още информация.</div>"
        "</div>"
        '<p class="muted"><a href="/sources">Източници</a> и '
        '<a href="/models">AI модели</a> са настройки — отварят се рядко.</p>'
        "</section>"
    )
    return page("Начало", f"{hero}\n{latest}\n{howto}", active="home")


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
    body.append(
        '<p class="muted">Това е архивната опашка от по-ранен етап. '
        + 'Ежедневната работа започва от <a href="/">Начало</a>.</p>'
    )
    return page("Случаи (архив)", "\n".join(body), active="queue")


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
        '<p><a href="/cases">← Случаи (архив)</a></p>'
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
            f"{esc(lb.collection_mode_label(row['collector']))}"
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
    return f'<div class="table-wrap"><table>{head}{"".join(body)}</table></div>'


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
        '<section class="card"><h2>Добави източник</h2>'
        '<p class="muted">За директен канал попълнете адрес (URL); за търсене — заявка.</p>'
        '<form method="post" action="/sources">'
        '<input type="hidden" name="action" value="add">'
        "<fieldset><legend>Основно</legend>"
        f'<label>Идентификатор (латиница, тирета) <input name="source_id" value="{esc(values.get("source_id", ""))}" required></label>'
        f'<label>Име <input name="name" value="{esc(values.get("name", ""))}" required></label>'
        f'<label>Тип <select name="kind">{kinds}</select></label>'
        f'<label>Начин на събиране <select name="collector">{collectors}</select></label>'
        "</fieldset><fieldset><legend>Адрес</legend>"
        f'<label>Домейн на издателя <input name="domain" value="{esc(values.get("domain", ""))}"></label>'
        f'<label>URL <input name="url" value="{esc(values.get("url", ""))}"></label>'
        f'<label>Заявка (за търсене) <input name="query" value="{esc(values.get("query", ""))}"></label>'
        "</fieldset><fieldset><legend>Настройки</legend>"
        f'<label>Приоритет <select name="priority">{priorities}</select></label>'
        f'<label>Ритъм <select name="cadence">{cadences}</select></label>'
        f'<label>Бележка <input name="note" value="{esc(values.get("note", ""))}"></label>'
        + (
            '<label><input type="checkbox" name="calendar" value="1"> календарен източник '
            "(предстоящи събития са стойността)</label>"
            '<label><input type="checkbox" name="monitoring_only" value="1"> само наблюдение '
            "(не се използва като фактологичен авторитет)</label>"
            '</fieldset><button class="btn primary" type="submit">Добави</button></form></section>'
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
            '<p class="muted">Тук се управлява кои източници се проверяват и колко често. '
            "Събирането върви автоматично по график; ръчно пускане има в "
            '<a href="/inbox">Материали</a> («Събери новините сега»). '
            "Редовете по-долу показват и кога източникът е работил за последно.</p>"
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
        + '<button class="btn danger" type="submit" data-danger="1">Премахни</button></form></li>'
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
        (
            '<section class="card" id="collect"><h2>Събиране</h2>'
            '<p class="muted">Проверява всички активни източници за нови материали. '
            "Може да отнеме минута — не затваряйте страницата.</p>"
        ),
        info,
        (
            '<div class="hero-actions"><form method="post" action="/inbox">'
            '<input type="hidden" name="action" value="collect">'
            '<button class="btn primary" type="submit" data-busy="1">Събери новините сега</button></form> '
        ),
        (
            '<form method="post" action="/inbox">'
            '<input type="hidden" name="action" value="collect_preview">'
            '<button class="btn" type="submit">Пробен преглед (без мрежа)</button></form></div>'
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
            f'<button class="btn {cls}" type="submit"'
            + (' data-danger="1"' if cls == "danger" else "")
            + f">{esc(label)}</button></form>"
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


# ---------- M4C: stories ----------


def _story_qs(filters, **overrides):
    params = {
        "status": filters.get("status") or "all",
        "review": "1" if filters.get("review") else "",
    }
    params.update({key: value for key, value in overrides.items() if value is not None})
    return urllib.parse.urlencode({key: value for key, value in params.items() if value})


def story_status_nav(view):
    filters = view["filters"]
    parts = []
    for key, label in lb.STORY_STATUS_FILTERS:
        cls = ' class="active"' if filters["status"] == key else ""
        parts.append(f'<a{cls} href="/stories?{_story_qs(filters, status=key)}">{esc(label)}</a>')
    marker = " ✓" if filters.get("review") else ""
    parts.append(
        f'<a href="/stories?{_story_qs(filters, review="1" if not filters.get("review") else "")}">'
        f"Само за преглед{marker}</a>"
    )
    return '<nav class="filters">' + " | ".join(parts) + "</nav>"


def _story_actions(story, *, detail=False):
    forms = []
    for action, label, cls in (
        ("SEEN", "Прегледана", ""),
        ("IGNORED", "Игнорирай", "danger"),
        ("NEW", "Върни като нова", ""),
    ):
        if action == story["status"]:
            continue
        forms.append(
            '<form method="post" action="/stories" style="display:inline">'
            '<input type="hidden" name="action" value="status">'
            f'<input type="hidden" name="story" value="{esc(story["story_id"])}">'
            f'<input type="hidden" name="status" value="{esc(action)}">'
            f'<button class="btn {cls}" type="submit"'
            + (' data-danger="1"' if cls == "danger" else "")
            + f">{esc(label)}</button></form>"
        )
    link = (
        f'<a class="btn" href="/stories/{esc(story["story_id"])}">Отвори историята</a>'
        if not detail
        else '<a class="btn" href="/inbox?status=all">Материали</a>'
    )
    return f"<p>{' '.join(forms)} {link}</p>"


def _count_label(count, singular, plural):
    """«1 издател» / «3 издателя» — the editor should not read broken BG."""
    return f"{count} {singular if count == 1 else plural}"


def _story_when(card):
    def _short(value):
        text = str(value or "")
        return text[11:16] if len(text) >= 16 else "—"

    bits = [f"открито {esc(_short(card['first_seen_at']))}"]
    if card["latest_material_change_at"]:
        bits.append(f"обновено {esc(_short(card['latest_material_change_at']))}")
    return " · ".join(bits)


def _story_card(card):
    badge = (
        _badge(lb.STORY_DEVELOPMENT_LABEL, "warn")
        if card.get("new_development")
        else _badge(lb.STORY_NEW_LABEL, "info")
    )
    if card.get("needs_review"):
        badge += " " + _badge("за преглед", "block")
    if card.get("blocked_publisher"):
        badge += " " + _badge("забранен издател", "block")
    metrics = card["metrics"]
    publishers = " · ".join(card["publishers"]) or "неизвестни издатели"
    return (
        '<section class="card">'
        f"<p>{badge} {_badge(lb.story_status_label(card['status']))}</p>"
        f'<h3><a href="/stories/{esc(card["story_id"])}">{esc(card["title"])}</a></h3>'
        f'<p class="muted">{_count_label(metrics["publisher_count"], "издател", "издателя")} · '
        f"{_count_label(metrics['publication_count'], 'публикация', 'публикации')} · "
        f"{_count_label(metrics['discovery_count'], 'откриване', 'откривания')} · "
        f"{_story_when(card)}</p>"
        f'<p class="muted">{esc(publishers)}</p>'
        + (f"<p>{esc(card['summary'])}</p>" if card["summary"] else "")
        + _story_actions(card)
        + "</section>"
    )


def render_stories(view, message="", error=""):
    counts = view["counts"]
    body = [
        (
            f"<p><strong>Истории:</strong> {view['total_stories']} · "
            f"нови {counts.get('NEW', 0)} · прегледани {counts.get('SEEN', 0)} · "
            f"игнорирани {counts.get('IGNORED', 0)} · "
            f"за преглед {view['needs_review']}"
            f' <span class="muted">(показани {view["total"]} от филтъра)</span></p>'
        ),
        (
            '<p class="muted">История = нови материали, групирани като едно събитие. '
            "Броим отделно материалите и издателите.</p>"
        ),
        story_status_nav(view),
        (
            '<section class="card"><h2>Обновяване на историите</h2>'
            '<p class="muted">Групира вече събраните материали. Пробният преглед не записва.</p>'
            '<div class="hero-actions"><form method="post" action="/stories">'
            '<input type="hidden" name="action" value="update">'
            '<button class="btn primary" type="submit" data-busy="1">Обнови историите</button></form> '
            '<form method="post" action="/stories">'
            '<input type="hidden" name="action" value="update_preview">'
            '<button class="btn" type="submit">Пробен преглед</button></form></div></section>'
        ),
    ]
    if message:
        body.append(f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.append(f'<div class="notice error">{esc(error)}</div>')
    stories = view["stories"]
    if not stories:
        body.append(
            '<section class="card hero"><h2>Няма истории за този филтър</h2>'
            '<p class="muted">Стъпки: 1) съберете материалите, 2) обновете историите, '
            "3) отворете история и маркирайте като прегледана.</p>"
            '<div class="hero-actions"><form method="post" action="/stories">'
            '<input type="hidden" name="action" value="update">'
            '<button class="btn primary" type="submit" data-busy="1">Обнови историите сега</button>'
            '</form><a href="/inbox"><button class="btn secondary" type="button">Към материалите</button></a></div></section>'
        )
        return page("Истории", "\n".join(body), active="stories")
    body.extend(_story_card(card) for card in stories)
    if view["page_count"] > 1:
        filters = view["filters"]
        parts = []
        if view["page"] > 1:
            parts.append(
                f'<a href="/stories?{_story_qs(filters, page=view["page"] - 1)}">← Предишна</a>'
            )
        parts.append(f'<span class="muted">Страница {view["page"]} / {view["page_count"]}</span>')
        if view["page"] < view["page_count"]:
            parts.append(
                f'<a href="/stories?{_story_qs(filters, page=view["page"] + 1)}">Следваща →</a>'
            )
        body.append('<nav class="filters">' + " | ".join(parts) + "</nav>")
    return page("Истории", "\n".join(body), active="stories")


def render_story(detail, message="", error=""):
    metrics = detail["metrics"]
    badge = (
        _badge(lb.STORY_DEVELOPMENT_LABEL, "warn")
        if any(m["relation"] == "NEW_DEVELOPMENT" for m in detail["timeline"])
        else _badge(lb.STORY_NEW_LABEL, "info")
    )
    body = [
        '<p><a href="/stories">← Всички истории</a></p>',
        f"<h2>{esc(detail['title'])}</h2>",
        f"<p>{badge} {_badge(lb.story_status_label(detail['status']))}"
        + (_badge("за преглед", "block") if detail.get("needs_review") else "")
        + "</p>",
        (
            f'<p class="muted">първо откриване: {esc(detail["first_seen_at"] or "—")} · '
            f"първа публикация: {esc(detail['first_public_at'] or '—')} · "
            f"последна съществена промяна: {esc(detail['latest_material_change_at'] or '—')}</p>"
        ),
        (
            f'<p class="muted">{_count_label(metrics["publisher_count"], "издател", "издателя")} · '
            f"{_count_label(metrics['publication_count'], 'уникална публикация', 'уникални публикации')} · "
            f"{_count_label(metrics['discovery_count'], 'откриване', 'откривания')}</p>"
        ),
        _story_actions(detail, detail=True),
        "<h3>Хронология</h3>",
    ]
    if message:
        body.insert(0, f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.insert(0, f'<div class="notice error">{esc(error)}</div>')
    for row in detail["timeline"]:
        blocked = _badge("забранен издател", "block") if row.get("blocked_publisher") else ""
        body.append(
            '<div class="fact">'
            f'<p class="muted">{esc(str(row["at"])[:16].replace("T", " "))} — '
            f"{esc(lb.story_relation_label(row['relation']))} {blocked}</p>"
            f'<p><a href="/inbox?status=all">{esc(row["title"])}</a>'
            f' <span class="muted">({esc(row["publisher_domain"] or "неизвестен издател")})</span></p>'
            '<form method="post" action="/stories" style="display:inline">'
            '<input type="hidden" name="action" value="split">'
            f'<input type="hidden" name="story" value="{esc(detail["story_id"])}">'
            f'<input type="hidden" name="item" value="{esc(row["item_id"])}">'
            '<button class="btn danger" type="submit" data-danger="1">Този материал не е част от историята</button>'
            "</form></div>"
        )
    body.append("<h3>Материали</h3>")
    body.append(
        '<p class="muted">Уникални публикации, групирани по издател. Различните наблюдения на '
        "един и същ материал са откривания, не независими източници.</p>"
    )
    for pub in detail["publications"]:
        blocked = _badge("забранен издател", "block") if pub.get("blocked_publisher") else ""
        provenance = "".join(
            f"<li>{esc(d['item_id'])} · {esc(d['source_id'])} · "
            f"{esc(str(d['discovered_at'])[:16].replace('T', ' '))}</li>"
            for d in pub["discoveries"]
        )
        body.append(
            '<div class="fact">'
            f"<p><strong>{esc(pub['title'])}</strong> {blocked}</p>"
            f'<p class="muted">{esc(pub["publisher_domain"] or "неизвестен издател")} · '
            f"публикувано {esc(str(pub['published_at'])[:16].replace('T', ' ') or '—')} · "
            f"{len(pub['discoveries'])} откриване(я)</p>"
            f"<details><summary>Откривания</summary><ul>{provenance}</ul></details></div>"
        )
    options = "".join(
        f'<option value="{esc(o["story_id"])}">{esc(o["title"])}</option>'
        for o in detail["recent_stories"]
    )
    if options:
        body.append(
            '<section class="card"><h3>Обедини с друга скорошна история</h3>'
            '<p class="muted">Ако историята е разделена погрешно, обединете я с истинската.</p>'
            '<form method="post" action="/stories">'
            '<input type="hidden" name="action" value="merge">'
            f'<input type="hidden" name="source" value="{esc(detail["story_id"])}">'
            f'<select name="target">{options}</select>'
            '<button class="btn" type="submit">Обедини</button></form></section>'
        )
    return page("История", "\n".join(body), active="stories")


MODEL_STATUS_LABELS = {
    "OK": "наличен",
    "INVALID": "НЕВАЛИДЕН",
    "MISMATCH": "НЕСЪОТВЕТСТВИЕ",
    "UNCHECKED": "непроверен",
}


def _policy_action(role, action, **hidden):
    """One small POST form for a route/role control (no JS framework).

    ``_role_manager_form`` below renders the compact single-form manager; this
    helper stays for the global/budget/validate forms and for tests.
    """
    fields = "".join(
        f'<input type="hidden" name="{esc(key)}" value="{esc(value)}">'
        for key, value in ({"action": action, "role": role, **hidden}).items()
    )
    return f'<form method="post" action="/models">{fields}'


def _role_manager_form(role):
    """Compact single-form manager for one role (P1 page-size fix).

    One ``<form>`` per role instead of four per route: the editor picks a route
    and an operation, then submits once. Field names (``op``/``index``) are
    translated to the legacy ``action`` vocabulary in ``http._post_models`` so
    the POST contract the CLI and the tests use never changes.
    """
    options = (
        "".join(
            f'<option value="{r["index"]}">#{r["index"]} — {esc(r["provider"])}:'
            f"{esc(r['model'])} ({('вкл.' if r['enabled'] else 'изкл.')})</option>"
            for r in role["routes"]
        )
        or '<option value="">— няма маршрути —</option>'
    )
    return (
        f'<form method="post" action="/models" class="role-manage">'
        f'<input type="hidden" name="role" value="{esc(role["role"])}">'
        '<label>Маршрут <select name="index">' + options + "</select></label> "
        '<label>Действие <select name="op">'
        '<option value="up">Премести нагоре</option>'
        '<option value="down">Премести надолу</option>'
        '<option value="toggle">Включи / изключи</option>'
        '<option value="remove">Премахни</option>'
        "</select></label> "
        '<button class="btn" type="submit" data-confirm-route="1">Приложи</button></form>'
    )


def render_models(view, message="", error="", values=None):
    """«AI модели» — operator configuration for the role-based routing policy.

    Deliberately plain: an ordered list per role, the free/paid label, today's
    calls against the declared model limit, enable/disable, add/remove and
    reorder. No API key is ever shown — only whether a key is present.
    """
    keys = view.get("keys") or {}
    body = [
        (
            '<p class="muted">Настройки за напреднали: кои модели задвижват отделните стъпки. '
            "Не е нужно за ежедневната работа.</p>"
        ),
        (
            "<p>"
            f"<strong>Ключове:</strong> Gemini — {'наличен' if keys.get('gemini') else 'ЛИПСВА'} · "
            f"OpenRouter — {'наличен' if keys.get('openrouter') else 'ЛИПСВА'}"
            "<br><strong>Политика:</strong> "
            f"{'собствена' if view.get('override_exists') else 'по подразбиране'}"
            f" · ден {esc(view.get('day'))}</p>"
            '<details class="muted"><summary>Технически детайли</summary>'
            f"<code>{esc(view.get('override_path'))}</code> · версия {esc(view.get('policy_hash'))}"
            "</details>"
        ),
    ]
    if message:
        body.append(f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.append(f'<div class="notice error">{esc(error)}</div>')

    validation = view.get("validation")
    if validation:
        rows = "".join(
            "<tr>"
            f"<td>{esc(r['role'])}</td><td>{esc(r['provider'])}:{esc(r['model'])}</td>"
            f"<td>{esc(MODEL_STATUS_LABELS.get(r['status'], r['status']))}</td>"
            f'<td class="muted">{esc(r.get("detail") or "")}</td></tr>'
            for r in validation.get("rows") or []
        )
        body.append(
            '<section class="card"><h2>Последна проверка в живите каталози</h2>'
            f'<p class="muted">Gemini: {esc(validation.get("gemini_catalog"))} модела · '
            f"OpenRouter: {esc(validation.get('openrouter_catalog'))} модела · "
            f"невалидни {len(validation.get('invalid') or [])} · "
            f"несъответствия {len(validation.get('mismatches') or [])}</p>"
            "<table><tr><th>Роля</th><th>Модел</th><th>Статус</th><th>Бележка</th></tr>"
            f"{rows}</table></section>"
        )

    for role in view.get("roles") or []:
        rows = []
        for route in role["routes"]:
            limit = f"/{route['daily_call_limit']}" if route.get("daily_call_limit") else ""
            note = route.get("reason") or ""
            rows.append(
                "<tr>"
                f"<td>{route['index']}</td>"
                f"<td>{esc(route['provider'])}:{esc(route['model'])}"
                + (
                    '<br><span class="muted">само публични материали</span>'
                    if route.get("public_only")
                    else ""
                )
                + "</td>"
                f"<td>{esc(lb.route_billing_label(route))}</td>"
                f"<td>{route['calls_today']}{esc(limit)}</td>"
                f"<td>{_badge('✓ готов', 'ok') if route['eligible'] else _badge('× пропуснат', 'block')}"
                + (f'<br><span class="muted">{esc(note)}</span>' if note else "")
                + "</td>"
                "</tr>"
            )
        body.append(
            '<section class="card">'
            f'<h2>{esc(role["label"])} <span class="muted">({esc(role["role"])})</span></h2>'
            f'<p class="muted">{esc(role["purpose"])}</p>'
            f"<p>днес {role['calls_today']} заявки · soft {role['soft_calls_day']} / "
            f"hard {role['hard_calls_day']} · "
            + (
                "публични материали"
                if role["payload_class"] == "public"
                else "непубликувани материали"
            )
            + f" · при изчерпване: {esc(role['on_exhausted'])}"
            + (" · <strong>SOFT ЛИМИТ ПРЕВИШЕН</strong>" if role["soft_exceeded"] else "")
            + "</p>"
            f'<div class="table-wrap"><table><tr><th>#</th><th>Модел</th><th>Тип</th>'
            f"<th>Днес</th><th>Състояние</th></tr>{''.join(rows)}</table></div>"
            + _role_manager_form(role)
            + _policy_action(role["role"], "add")
            + '<p class="muted">Добави нов модел към тази роля:</p>'
            + "<label>Доставчик (provider) "
            '<input type="text" name="provider" placeholder="gemini"></label>'
            + "<label>Модел (model) "
            '<input type="text" name="model" placeholder="gemini-3.7-flash"></label>'
            '<label><input type="checkbox" name="public_only" value="1"> '
            "само публични материали</label>"
            '<button class="btn primary" type="submit">Добави</button></form>'
            + _policy_action(role["role"], "role_budget")
            + '<p class="muted">Дневни граници на ролята:</p>'
            f'<input type="text" name="soft_calls_day" value="{role["soft_calls_day"]}">'
            f'<input type="text" name="hard_calls_day" value="{role["hard_calls_day"]}">'
            '<button class="btn secondary" type="submit">Запази границите</button></form>'
            "</section>"
        )

    body.append(
        '<section class="card"><h2>Глобални настройки</h2>'
        + _policy_action("", "global")
        + '<label><input type="checkbox" name="paid_enabled" value="1"'
        + (" checked" if view.get("paid_enabled") else "")
        + "> Разреши платени модели</label>"
        + '<p class="muted">Платен софт бюджет на ден (USD):</p>'
        + f'<input type="text" name="soft_paid_budget_usd_day" '
        f'value="{view.get("soft_paid_budget_usd_day", 0.0)}">'
        + "<button class="
        + '"btn" type="submit">Запази</button></form>'
        + (
            f"<p>платено днес: ${view['paid_cost_today_usd']:.4f} · "
            f"заявки днес: {view['usage']['calls']} · "
            f"успешни {view['usage']['successes']} · паднали {view['usage']['failures']} · "
            f"пропуснати {view['usage']['skipped']} · "
            f"лимитни откази {view['usage']['quota_failures']} · "
            f"невалидни модели {view['usage']['invalid_model_failures']}</p>"
        )
        + _policy_action("", "validate")
        + '<p class="muted">Проверява всеки конфигуриран модел в живите каталози на '
        "доставчиците. Не изпраща никакъв текст — само заявка за списъка с модели.</p>"
        '<button class="btn" type="submit">Провери моделите сега</button></form>'
        "</section>"
    )
    return page("AI модели", "\n".join(body), active="models")


def render_inbox(view, message="", error=""):
    problems = view.get("problems") or []
    # "Днес" is the Europe/Sofia arrival day, not the lifetime inbox total
    # (M4B.1 F3). Unfinished NEW work is reported separately so the editor never
    # loses an item that arrived earlier and was not looked at.
    today = view.get("today") or {}
    today_status = today.get("by_status") or {}
    body = [
        (
            f"<p><strong>Днес ({esc(today.get('date') or '—')}):</strong> "
            f"нови {today_status.get('NEW', 0)} · "
            f"прегледани {today_status.get('SEEN', 0)} · "
            f"игнорирани {today_status.get('IGNORED', 0)}</p>"
        ),
        (
            f"<p><strong>Непрегледани общо:</strong> {int(view.get('unreviewed') or 0)} · "
            f"източници с проблем {len(problems)}"
            f' <span class="muted">(показани {view["total"]} от филтъра)</span></p>'
        ),
        (
            '<p class="muted">Нови материали от вашите източници. '
            "Това са събрани кандидати, не доказателства — нищо тук не е проверено "
            "и не е готово за публикуване.</p>"
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
            '<section class="card hero"><h2>Няма нови материали за този филтър</h2>'
            '<p class="muted">Стъпки: 1) натиснете «Събери новините сега», '
            "2) изчакайте събирането, 3) отворете първия материал.</p>"
            '<div class="hero-actions"><form method="post" action="/inbox">'
            '<input type="hidden" name="action" value="collect">'
            '<button class="btn primary" type="submit" data-busy="1">Събери новините сега</button>'
            '</form><a href="/sources"><button class="btn secondary" type="button">Провери източниците</button></a></div></section>'
        )
        return page("Материали", "\n".join(body), active="inbox")
    body.extend(_inbox_item(item) for item in items)
    body.append(_pager(view))
    return page("Материали", "\n".join(body), active="inbox")
