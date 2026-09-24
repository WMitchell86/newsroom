"""M3A HTML rendering: Bulgarian-first UI, stdlib only, fully escaped.

All dynamic content goes through esc(); only http/https URLs become links.
"""

from __future__ import annotations

import html as html_mod
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

from editor_assistant.workflow import diff as diff_mod
from editor_assistant.workflow.cases import EDITING_WEIGHTS, TIME_BUCKETS
from editor_assistant.workflow.workbench import labels as lb

CSS = """
:root {
  --ink:#0f172a; --ink-2:#334155; --muted:#64748b; --line:#e4e9f2;
  --bg:#f4f6fb; --card:#ffffff;
  --accent:#2563eb; --accent-dark:#1d4ed8; --accent-soft:#eff6ff;
  --ok:#15803d; --ok-bg:#dcfce7; --warn:#b45309; --warn-bg:#fef3c7;
  --bad:#b91c1c; --bad-bg:#fee2e2; --info:#1d4ed8; --info-bg:#dbeafe;
  --nav-bg:#0b1220; --nav-ink:#c7d2e2; --nav-dim:#8494ac;
  --nav-hover:rgba(255,255,255,.07);
  --rail:82px; --rail-open:258px;
  --radius:14px;
  --shadow:0 1px 2px rgba(15,23,42,.05), 0 12px 28px -24px rgba(15,23,42,.5);
}
* { box-sizing:border-box; }
body {
  margin:0; background:var(--bg); color:var(--ink); line-height:1.5;
  font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    'Helvetica Neue', Arial, sans-serif;
}
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
code { background:#eef1f6; padding:.05rem .32rem; border-radius:6px; font-size:.86em; }

/* ---- shell: collapsible sidebar (works with JavaScript off) ---- */
.nav-toggle { position:absolute; width:1px; height:1px; opacity:0; margin:-1px; }
.nav-toggle:focus-visible ~ .shell .nav-burger { outline:2px solid var(--accent); outline-offset:2px; }
.shell { min-height:100vh; }
.sidenav {
  position:fixed; top:0; left:0; bottom:0; z-index:40;
  width:var(--rail); background:var(--nav-bg); color:var(--nav-ink);
  display:flex; flex-direction:column; padding:.75rem .55rem 1rem;
  overflow-y:auto; transition:width .18s ease, transform .2s ease;
}
.brand { padding:.15rem .1rem .7rem; }
.brand-link { display:flex; align-items:center; justify-content:center; gap:.6rem; color:#fff; }
.brand-link:hover { text-decoration:none; }
.brand-mark {
  flex:0 0 auto; width:2.3rem; height:2.3rem; border-radius:11px;
  background:var(--accent); color:#fff; font-size:1.1rem;
  display:flex; align-items:center; justify-content:center;
}
.brand-text { display:none; font-weight:700; font-size:.92rem; line-height:1.25; }
.brand-tag { display:none; margin:.45rem 0 0; font-size:.72rem; color:var(--nav-dim); }
.nav-group { display:flex; flex-direction:column; gap:.12rem; margin-top:.35rem; }
.nav-heading {
  display:none; margin:.9rem .5rem .3rem; font-size:.66rem; letter-spacing:.09em;
  text-transform:uppercase; color:var(--nav-dim);
}
.nav-item {
  display:flex; flex-direction:column; align-items:center; gap:.12rem;
  padding:.5rem .15rem; border-radius:10px; color:var(--nav-ink);
  text-align:center;
}
.nav-item:hover { background:var(--nav-hover); color:#fff; text-decoration:none; }
.nav-item.nav-active { background:var(--accent); color:#fff; font-weight:600; }
.nav-ico { font-size:1.05rem; line-height:1.2; }
.nav-label { max-width:100%; font-size:.58rem; line-height:1.15; white-space:nowrap; overflow:hidden; }
.nav-sub { display:none; }
.sidenav-backdrop { display:none; }
.content { margin-left:var(--rail); min-height:100vh; transition:margin-left .18s ease; }
.nav-toggle:checked ~ .shell .sidenav { width:var(--rail-open); }
.nav-toggle:checked ~ .shell .content { margin-left:var(--rail-open); }
.nav-toggle:checked ~ .shell .brand-link { justify-content:flex-start; }
.nav-toggle:checked ~ .shell .brand-text,
.nav-toggle:checked ~ .shell .brand-tag { display:block; }
.nav-toggle:checked ~ .shell .nav-heading { display:block; }
.nav-toggle:checked ~ .shell .nav-sub { display:flex; flex-direction:column; gap:.12rem; }
.nav-toggle:checked ~ .shell .nav-item {
  flex-direction:row; gap:.65rem; padding:.5rem .6rem; text-align:left;
}
.nav-toggle:checked ~ .shell .nav-label { font-size:.9rem; }
.topbar {
  position:sticky; top:0; z-index:30; display:flex; align-items:center; gap:.8rem;
  min-height:3.4rem; padding:.5rem 1.2rem; background:rgba(255,255,255,.88);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line);
}
.nav-burger {
  flex:0 0 auto; width:2.25rem; height:2.25rem; border-radius:10px;
  border:1px solid var(--line); background:#fff; color:var(--ink-2);
  display:flex; align-items:center; justify-content:center; cursor:pointer;
  font-size:1rem; line-height:1; user-select:none;
}
.nav-burger:hover { background:var(--accent-soft); border-color:#c9dbff; }
.topbar-title { margin:0; font-size:1.02rem; font-weight:700; letter-spacing:-.01em; }
.topbar-sub { margin-left:auto; color:var(--muted); font-size:.8rem; white-space:nowrap; }
main { max-width:68rem; margin:0 auto; padding:1.2rem 1.2rem 3.5rem; }
main > h2 { margin:0 0 .8rem; }
.cols { display:grid; grid-template-columns:repeat(auto-fit,minmax(19rem,1fr)); gap:1rem; }
.cols > .card { margin:0; }

/* ---- cards, stats, hero ---- */
.card {
  background:var(--card); border:1px solid var(--line); border-radius:var(--radius);
  box-shadow:var(--shadow); padding:1.05rem 1.2rem; margin:1rem 0;
}
.card h2 { font-size:1.03rem; margin:0 0 .5rem; }
.card h3 { font-size:.96rem; margin:1rem 0 .35rem; }
.card h3:first-child { margin-top:0; }
.card.hero {
  border-left:4px solid var(--accent);
  background:linear-gradient(135deg,#ffffff 55%,#f3f8ff);
}
.card.hero h2 { font-size:1.2rem; }
.hero-actions { display:flex; flex-wrap:wrap; gap:.6rem; margin-top:.9rem; align-items:center; }
.hero-actions .btn, .hero-actions button { padding:.62rem 1.15rem; font-size:.95rem; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr)); gap:.7rem; margin:.9rem 0 .3rem; }
.stat { background:#fff; border:1px solid var(--line); border-radius:12px; padding:.7rem .9rem; }
.stat .num { font-size:1.6rem; font-weight:800; letter-spacing:-.02em; }
.stat .lbl { color:var(--muted); font-size:.8rem; line-height:1.3; }
.howto { display:grid; grid-template-columns:repeat(auto-fit,minmax(12.5rem,1fr)); gap:.7rem; margin-top:.6rem; }
.howto div { background:var(--accent-soft); border:1px solid #dbe7ff; border-radius:12px; padding:.65rem .85rem; font-size:.88rem; }
ol.top-stories { margin:.4rem 0 .2rem; padding-left:1.2rem; }
ol.top-stories li { margin:.4rem 0; }

/* ---- tables ---- */
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:12px; background:#fff; }
table { border-collapse:collapse; width:100%; background:transparent; }
th, td { text-align:left; vertical-align:top; font-size:.9rem; padding:.6rem .75rem; border-bottom:1px solid var(--line); }
th {
  background:#f8fafc; color:var(--muted); font-size:.74rem;
  text-transform:uppercase; letter-spacing:.05em; white-space:nowrap;
}
tbody tr:last-child td, tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:#f8fbff; }

/* ---- badges ---- */
.badge { display:inline-block; padding:.17rem .6rem; border-radius:999px; font-size:.78rem; font-weight:600; background:#e9edf3; color:var(--ink-2); }
.badge.ok { background:var(--ok-bg); color:var(--ok); }
.badge.warn { background:var(--warn-bg); color:var(--warn); }
.badge.block { background:var(--bad-bg); color:var(--bad); }
.badge.info { background:var(--info-bg); color:var(--info); }

/* ---- forms ---- */
label { display:block; margin:.7rem 0 .25rem; font-weight:600; font-size:.9rem; }
input[type=text], input:not([type]), input[type=date], select, textarea {
  width:100%; padding:.5rem .65rem; border:1px solid var(--line); border-radius:9px;
  font:inherit; font-size:.92rem; background:#fff; color:var(--ink);
}
input:focus, select:focus, textarea:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:var(--accent); }
textarea { min-height:16rem; resize:vertical; }
input[type=checkbox], input[type=radio] { width:auto; margin-right:.35rem; accent-color:var(--accent); }
fieldset { border:1px solid var(--line); border-radius:12px; padding:.7rem .95rem; margin:.9rem 0; background:#f8fafd; }
fieldset legend { font-weight:700; padding:0 .4rem; }

/* ---- buttons ---- */
button {
  font:inherit; background:var(--accent); color:#fff; border:0; border-radius:9px;
  padding:.55rem 1.1rem; cursor:pointer; transition:background .15s;
}
button:hover { background:var(--accent-dark); }
button:disabled { opacity:.65; cursor:progress; }
button.secondary { background:#e2e8f0; color:var(--ink-2); }
button.secondary:hover { background:#cbd5e1; }
a.btn, button.btn {
  display:inline-block; padding:.34rem .72rem; border-radius:9px; font-size:.86rem;
  font-weight:600; line-height:1.35; white-space:nowrap;
}
a.btn { background:#fff; color:var(--ink-2); border:1px solid var(--line); }
a.btn:hover { background:#f1f5fb; border-color:#c9d4e5; text-decoration:none; }
button.btn { border:0; background:#e2e8f0; color:var(--ink-2); }
button.btn:hover { background:#cbd5e1; }
a.btn.primary, button.btn.primary { background:var(--ok); border-color:var(--ok); color:#fff; }
a.btn.primary:hover, button.btn.primary:hover { background:#166534; }
a.btn.danger, button.btn.danger, button.danger { background:var(--bad); border-color:var(--bad); color:#fff; }
a.btn.danger:hover, button.btn.danger:hover, button.danger:hover { background:#7f1d1d; }
a.btn.secondary, button.btn.secondary { background:#e2e8f0; color:var(--ink-2); }

/* ---- notices, boxes ---- */
.notice { padding:.7rem .95rem; border-radius:11px; margin:.8rem 0; font-size:.93rem; }
.notice.error { background:var(--bad-bg); border:1px solid #fca5a5; color:#7f1d1d; }
.notice.saved { background:var(--ok-bg); border:1px solid #86efac; color:#14532d; }
.warnbox { background:var(--warn-bg); border:1px solid #f59e0b; color:#78350f; padding:.65rem .9rem; border-radius:11px; margin:.55rem 0; font-size:.92rem; }
.infobox { background:#e0f2fe; border:1px solid #7dd3fc; color:#0c4a6e; padding:.65rem .9rem; border-radius:11px; margin:.55rem 0; font-size:.92rem; }

/* ---- filters as pill tabs ---- */
.filters { display:flex; flex-wrap:wrap; gap:.4rem; align-items:center; margin:.9rem 0; }
.filters a { padding:.3rem .78rem; border-radius:999px; background:#fff; border:1px solid var(--line); color:var(--ink-2); font-size:.86rem; }
.filters a:hover { border-color:var(--accent); color:var(--accent); text-decoration:none; }
.filters .active { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
.filters .muted { margin-left:.3rem; }
.muted { color:var(--muted); font-size:.87rem; }

/* ---- long-form content ---- */
pre.draft {
  white-space:pre-wrap; font-family:Georgia, 'Times New Roman', serif;
  background:#fbfcfe; border:1px solid var(--line); border-radius:11px;
  padding:.9rem 1rem; font-size:.98rem; line-height:1.6; overflow-x:auto;
}
.fact { border-bottom:1px solid var(--line); padding:.55rem 0; }
.fact:last-child { border-bottom:0; }
.loc { font-size:.8rem; color:var(--accent); }
dl.meta { margin:.6rem 0; }
dl.meta dt { font-weight:600; margin-top:.45rem; font-size:.88rem; }
dl.meta dd { margin:0 0 .3rem; }

/* ---- details, misc forms ---- */
details { margin:.45rem 0; }
details summary { cursor:pointer; color:var(--accent); font-size:.87rem; }
details[open] summary { margin-bottom:.45rem; }
details form { margin:.35rem 0 .1rem; }
.promote-form { margin-top:.5rem; background:#f8fafd; border:1px solid var(--line); border-radius:11px; padding:.6rem .8rem; }
.promote-form input[type=text] { width:min(28rem,100%); }
.promote-form label { display:inline; margin-right:.3rem; }
.role-manage { margin:.6rem 0; background:#f8fafd; border:1px dashed var(--line); border-radius:11px; padding:.6rem .8rem; }
.force-box { background:#fff7ed; border:1px solid #fdba74; border-radius:11px; padding:.5rem .8rem; margin:.5rem 0; }
.force-box summary { color:#9a3412; }

/* ---- busy overlay ---- */
#busy-overlay {
  display:none; position:fixed; inset:0; z-index:60; background:rgba(2,6,23,.55);
  align-items:center; justify-content:center;
}
#busy-overlay div { background:#fff; border-radius:14px; padding:1.1rem 1.6rem; font-weight:600; box-shadow:0 24px 60px -24px rgba(0,0,0,.6); }

@media (max-width:900px) {
  .sidenav { width:264px; transform:translateX(-104%); box-shadow:0 0 44px rgba(2,6,23,.4); }
  .content { margin-left:0; }
  .nav-toggle:checked ~ .shell .sidenav { width:264px; transform:translateX(0); }
  .nav-toggle:checked ~ .shell .content { margin-left:0; }
  .nav-toggle:checked ~ .shell .sidenav-backdrop { display:block; }
  .sidenav-backdrop { position:fixed; inset:0; z-index:35; background:rgba(2,6,23,.5); }
  .brand-link { justify-content:flex-start; }
  .brand-text, .brand-tag { display:block; }
  .nav-heading { display:block; }
  .nav-sub { display:flex; flex-direction:column; gap:.12rem; }
  .nav-item { flex-direction:row; gap:.65rem; padding:.55rem .6rem; text-align:left; }
  .nav-label { font-size:.92rem; }
  .topbar-sub { display:none; }
  main { padding:.9rem .8rem 3rem; }
  th, td { font-size:.84rem; padding:.45rem .5rem; }
  .hero-actions .btn, .hero-actions button { width:100%; text-align:center; }
  .card { padding:.95rem 1rem; }
}
@media (prefers-reduced-motion:reduce) {
  * { transition:none !important; }
}
"""


def esc(value):
    return html_mod.escape(str(value if value is not None else ""), quote=True)


#: Icons for the collapsed sidebar rail (emoji — no asset pipeline, stdlib only).
ICONS = {
    "home": "\U0001f3e0",
    "stories": "\U0001f4f0",
    "inbox": "\U0001f4e5",
    "articles": "✍",
    "settings": "⚙",
    "sources": "\U0001f4e1",
    "models": "\U0001f916",
    "queue": "\U0001f5c2",
    "intake": "\u25b6",
}

#: Daily work only — what the editor opens every morning (M4 redesign):
#: sources/models/archive are advanced and live behind «Настройки».
NAV_DAILY = (
    ("home", "/", "Начало"),
    ("stories", "/stories", "Истории"),
    ("inbox", "/inbox", "Публикации"),
    ("articles", "/articles", "Статии"),
)
#: Advanced surfaces, grouped under the settings hub (/settings).
NAV_ADMIN = (
    ("settings", "/settings", "Настройки"),
    ("sources", "/sources", "Източници"),
    ("models", "/models", "AI модели"),
    ("queue", "/cases", "Архив"),
    ("intake", "/intake", "YouTube"),
)
#: Back-compat alias table: every key ever used as ``active=`` still resolves.
NAV = NAV_DAILY + NAV_ADMIN
#: Pages whose active state belongs to the «Настройки и архив» group.
ADMIN_ACTIVE = frozenset(key for key, _, _ in NAV_ADMIN)


def _nav_link(key, href, label, active=""):
    cls = "nav-item"
    if key == active or (key == "settings" and active in ADMIN_ACTIVE):
        cls += " nav-active"
    icon = ICONS.get(key, "\u2022")
    return (
        f'<a class="{cls}" href="{href}">'
        f'<span class="nav-ico" aria-hidden="true">{icon}</span>'
        f'<span class="nav-label">{esc(label)}</span></a>'
    )


def sidenav(active=""):
    """Hidden/collapsible sidebar: rail collapsed by default, toggled by CSS.

    Everything works without JavaScript — the toggle is a checkbox + label,
    so the daily pages stay usable in any browser and in the smoke harness.
    """
    daily = "".join(_nav_link(k, h, label, active) for k, h, label in NAV_DAILY)
    admin = "".join(_nav_link(k, h, label, active) for k, h, label in NAV_ADMIN)
    return (
        '<aside class="sidenav">'
        '<div class="brand"><a class="brand-link" href="/">'
        '<span class="brand-mark" aria-hidden="true">\U0001f4f0</span>'
        '<span class="brand-text">Дневен новинарски помощник</span></a>'
        '<p class="brand-tag">Какво е ново от вашите източници · прочетете · '
        "отбележете · напишете</p></div>"
        '<nav class="nav-group" aria-label="Ежедневна работа">'
        '<p class="nav-heading">Работа</p>'
        f"{daily}</nav>"
        '<nav class="nav-group" aria-label="Настройки и архив">'
        '<p class="nav-heading">Настройки и архив</p>'
        f"{admin}</nav></aside>"
    )


def page(title, body, active=""):
    return (
        '<!doctype html>\n<html lang="bg">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)} — Дневен новинарски помощник</title>\n"
        f'<link rel="stylesheet" href="/static/style.css">\n<style>{CSS}</style>\n</head>\n<body>\n'
        '<input type="checkbox" id="nav-toggle" class="nav-toggle">\n'
        '<div class="shell">\n'
        f"{sidenav(active)}\n"
        '<div class="content">\n'
        '<header class="topbar">\n'
        '<label for="nav-toggle" class="nav-burger" '
        'title="Покажи или скрий менюто">☰</label>\n'
        f'<h1 class="topbar-title">{esc(title)}</h1>\n'
        '<span class="topbar-sub">Дневен новинарски помощник</span>\n'
        "</header>\n"
        f"<main>\n{body}\n</main>\n"
        "</div>\n"
        '<label for="nav-toggle" class="sidenav-backdrop" aria-hidden="true"></label>\n'
        "</div>\n"
        '<div id="busy-overlay" role="status"><div>Моля, изчакайте… обработката тече.</div></div>\n'
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
        "if(b.dataset.busy||f.dataset.busy){"
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
    return '<nav class="filters">' + "".join(parts) + "</nav>"


def queue_table(rows, empty_text):
    if not rows:
        return f'<p class="muted">{esc(empty_text)}</p>'
    head = (
        "<tr><th>Статия</th><th>Заглавие / ъгъл</th><th>Състояние</th>"
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


#: Display-only local timezone: the greeting follows the editor's own day.
_SOFIA_TZ = ZoneInfo("Europe/Sofia")


def _greeting():
    """Time-of-day greeting — a small human touch on the daily landing."""
    hour = datetime.now(_SOFIA_TZ).hour
    if hour < 11:
        return "Добро утро"
    if hour < 18:
        return "Добър ден"
    return "Добър вечер"


def render_home(stories, inbox, sources):
    """Daily landing page: «what is new, what do I do next».

    The morning control panel in one place: unreviewed counts, today's
    arrivals, the top new stories, the one long daily action (collect) and
    the next step. Aggregation is read-only over the views the dedicated
    pages already compute, so it can never drift from the store contract.
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
        top_block = f'<ol class="top-stories">{top_rows}</ol>'
    else:
        top_block = (
            '<p class="muted">Още няма групирани истории. Ако публикациите са събрани, '
            "натиснете „Обнови историите“.</p>"
        )
    hero = (
        '<section class="card hero">'
        f"<h2>{_greeting()} — ето какво е ново</h2>"
        '<p class="muted">Дневен новинарски помощник: събира публикации от вашите '
        "източници, групира ги в истории и ви оставя решението. "
        "Нищо не се публикува автоматично.</p>"
        '<div class="stats">'
        f'<div class="stat"><div class="num">{new_stories}</div>'
        '<div class="lbl">нови истории за преглед</div></div>'
        f'<div class="stat"><div class="num">{new_materials}</div>'
        '<div class="lbl">непрегледани публикации</div></div>'
        f'<div class="stat"><div class="num">{today_new}</div>'
        f'<div class="lbl">пристигнали днес ({esc(today_date)})</div></div>'
        f'<div class="stat"><div class="num">{esc(active_sources)}</div>'
        '<div class="lbl">активни източници</div></div>'
        "</div>"
        '<div class="hero-actions">'
        '<form method="post" action="/inbox">'
        '<input type="hidden" name="action" value="collect">'
        '<button type="submit" data-busy="1">Събери новините сега</button>'
        "</form>"
        f'<a class="btn primary" href="/stories">Прегледай историите ({new_stories})</a>'
        f'<a class="btn" href="/inbox">Към публикациите ({new_materials})</a>'
        "</div>"
        '<p class="muted">Събирането проверява всички активни източници и може '
        "да отнеме минута — изчакайте, страницата ще се върне сама.</p>"
        "</section>"
    )
    latest = (
        '<section class="card"><h2>Най-нови истории</h2>'
        f"{top_block}"
        f'<p class="muted">Общо истории: {total_stories} · '
        '<a href="/stories">всички истории</a></p></section>'
    )
    howto = (
        '<section class="card"><h2>Как се работи</h2>'
        '<div class="howto">'
        "<div><strong>1. Събери</strong><br>Натисни „Събери новините сега“ "
        'тук или в <a href="/inbox">Публикации</a>.</div>'
        "<div><strong>2. Прегледай</strong><br>Отвори история в "
        '<a href="/stories">Истории</a> и прочети публикациите.</div>'
        "<div><strong>3. Избери</strong><br>Продължи, проучи още или избери ъгъл.</div>"
        "<div><strong>4. Започни статия</strong><br>Натисни „Започни статия“, после "
        '<a href="/articles">Статии</a> → «Направи чернова».</div>'
        "</div>"
        '<p class="muted"><a href="/settings">Настройки</a> (източници, AI модели, '
        "архив) се отварят рядко — ежедневната работа е горе.</p>"
        "</section>"
    )
    body = f'{hero}\n<div class="cols">{latest}{howto}</div>'
    return page("Начало", body, active="home")


#: One advanced surface on the /settings hub: (href, title, explanation, CTA).
SETTINGS_CARDS = (
    (
        "/sources",
        "Източници",
        (
            "Кои сайтове и емисии се следят, колко често, тяхното здраве и "
            "забранените домейни. Отваря се, когато искате да добавите, спрете "
            "или заглушите източник."
        ),
        "Отвори източниците",
    ),
    (
        "/models",
        "AI модели",
        (
            "Кой AI модел изпълнява всяка стъпка, дневните лимити и безплатно/"
            "платено. Техническа настройка — не е нужна за ежедневната работа."
        ),
        "Отвори AI моделите",
    ),
    (
        "/intake",
        "YouTube",
        (
            "Готови резултати от вторичния видеоизточник. Нов запис се добавя "
            "от компютъра; тук само се преглежда."
        ),
        "Отвори YouTube",
    ),
    (
        "/cases",
        "Архив",
        ("Архив на по-старата редакторска опашка. Не е част от ежедневния редакционен процес."),
        "Отвори архива",
    ),
)


def render_settings(message="", error=""):
    """«Настройки» — one plain hub for every advanced surface (M4 redesign).

    The editor's morning never needs this page: model routing, the registry,
    the YouTube view and the frozen M3A archive are grouped here with a plain
    sentence each, so the daily navigation stays four items long.
    """
    cards = "".join(
        '<section class="card">'
        f"<h2>{esc(title)}</h2>"
        f"<p>{esc(text)}</p>"
        f'<p><a class="btn primary" href="{href}">{esc(cta)}</a></p>'
        "</section>"
        for href, title, text, cta in SETTINGS_CARDS
    )
    body = [
        (
            '<p class="muted">Тук се променя системата, не днешната работа. Сутрин '
            'се работи от <a href="/">Начало</a>, <a href="/stories">Истории</a>, '
            '<a href="/inbox">Публикации</a> и <a href="/articles">Статии</a> — '
            "тази страница се отваря рядко.</p>"
        )
    ]
    if message:
        body.append(f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.append(f'<div class="notice error">{esc(error)}</div>')
    body.append(f'<div class="cols">{cards}</div>')
    body.append(
        '<section class="card"><h2>Ежедневна работа</h2>'
        '<p class="muted">Тук нищо не се променя — само се отваря.</p>'
        '<p class="hero-actions">'
        '<a class="btn primary" href="/">Начало</a>'
        '<a class="btn" href="/stories">Истории</a>'
        '<a class="btn" href="/inbox">Публикации</a>'
        '<a class="btn" href="/articles">Статии</a>'
        "</p>"
        '<p class="muted">Нищо не се публикува автоматично: всеки финален текст '
        "е изрично решение на редактора.</p>"
        "</section>"
    )
    return page("Настройки", "\n".join(body), active="settings")


def render_intake(rows):
    """«YouTube» — completed intake results (initiation stays CLI-only, M3B Part J).

    Transcription + discovery are long and model-driven, so the local server
    never runs them; this page only displays records written by
    `workflow.cli youtube-intake`. The markup lives here with the rest of the
    UI so every page shares one shell and one stylesheet.
    """
    cards = []
    for row in rows:
        outcome = row.get("outcome") or "—"
        cards.append(
            '<section class="card">'
            f"<h3>{esc(row.get('title') or row.get('video_id') or '')}</h3>"
            f'<p class="muted">{esc(row.get("canonical_url") or "")}</p>'
            f"<p><strong>Резултат:</strong> {esc(outcome)} · "
            f"теми {row.get('topics', 0)} · факти {row.get('facts', 0)} · "
            f"отхвърлени {row.get('dropped_facts', 0)}</p>"
            f'<p class="muted">ъгъл: {esc(row.get("assessment_status") or "—")} · '
            f"готовност: {esc(row.get('readiness_status') or '—')}</p>"
            "</section>"
        )
    body = [
        (
            '<p class="muted">Нов запис се добавя от компютъра с командата '
            "<code>youtube-intake &lt;URL&gt;</code> (транскрипцията е дълга). "
            "Тук се показват готовите резултати. YouTube е вторичен източник — "
            'основната работа е в <a href="/stories">Истории</a>.</p>'
        ),
        "".join(cards) or "<p>Няма добавени YouTube източници.</p>",
    ]
    return page("YouTube източници", "\n".join(body), active="intake")


def render_queue(queue, active_filter="all", message="", error=""):
    sections = []
    if active_filter == "all":
        sections.append(("<h2>Пилотни статии (LIVE)</h2>", queue["live"]))
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
        body.append(queue_table(shown, "Няма статии в тази категория."))
    body.append(
        '<p class="muted">Работният плот не публикува автоматично: финализирането е '
        "изрично действие на редактора и не променя черновите.</p>"
    )
    body.append(
        '<p class="muted">Това е архив на по-стари редакционни записи. '
        + 'Ежедневната работа започва от <a href="/">Начало</a>.</p>'
    )
    return page("Архив", "\n".join(body), active="queue")


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
        '<section class="card" id="final"><h2>Финализирана статия (неизменима)</h2>'
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
        out.append('<p class="muted">Няма записани външни източници за тази статия.</p>')
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
            '<p class="muted">Данните не са достатъчни за уверена статия. '
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
            '<p class="muted">Еталонна статия (сравнителен еталон): няма усилийни показатели '
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
        '<p class="muted">Финализирането записва окончателната статия и е изрично действие. '
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
        '<span class="muted">След финализирането статията е неизменима.</span></p>'
        "</form></section>"
    )


def _draft_surface(view):
    """One article editor surface backed by the existing immutable draft contract.

    Special no-draft cases never get an empty article editor: their draft
    surface only appears when a draft actually exists. Finalized articles get no
    workspace either: no action could apply it.
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
            "промени се пазят отделно като текуща чернова.</div>" + "</section>"
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
        + '<p><button type="submit">Запази текущата чернова</button> '
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
        '<p><a href="/articles">← Статии</a></p>'
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
            '<a href="/inbox">Публикации</a> («Събери новините сега»). '
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
    return '<nav class="filters">' + "".join(parts) + "</nav>"


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
    return '<nav class="filters">' + "".join(parts) + "</nav>"


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
            '<p class="muted">Проверява всички активни източници за нови публикации. '
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
    return '<nav class="filters">' + "".join(parts) + "</nav>"


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
        else '<a class="btn" href="/inbox?status=all">Публикации</a>'
    )
    promote = ""
    if detail:
        promote = (
            '<form method="post" action="/articles" class="promote-form">'
            '<input type="hidden" name="action" value="promote">'
            f'<input type="hidden" name="story" value="{esc(story["story_id"])}">'
            '<label for="angle-' + esc(story["story_id"]) + '">Ъгъл (по избор)</label> '
            '<input type="text" id="angle-' + esc(story["story_id"]) + '" name="angle" '
            'placeholder="напр. какво се променя за читателя">'
            '<button class="btn primary" type="submit">Започни статия</button></form>'
        )
    return f"<p>{' '.join(forms)} {link}</p>{promote}"


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
            '<p class="muted">История = нови публикации, групирани като едно събитие. '
            "Броим отделно публикациите и източниците.</p>"
        ),
        story_status_nav(view),
        (
            '<section class="card"><h2>Обновяване на историите</h2>'
            '<p class="muted">Групира вече събраните публикации. Пробният преглед не записва.</p>'
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
            '<p class="muted">Стъпки: 1) съберете публикациите, 2) обновете историите, '
            "3) отворете история и маркирайте като прегледана.</p>"
            '<div class="hero-actions"><form method="post" action="/stories">'
            '<input type="hidden" name="action" value="update">'
            '<button class="btn primary" type="submit" data-busy="1">Обнови историите сега</button>'
            '</form><a href="/inbox"><button class="btn secondary" type="button">Към публикациите</button></a></div></section>'
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
        body.append('<nav class="filters">' + "".join(parts) + "</nav>")
    return page("Истории", "\n".join(body), active="stories")


def render_articles(view, message="", error=""):
    """«Статии»: editorial decision -> facts and sources -> draft -> article."""
    counts = view["counts"]
    body = ["<h2>Статии</h2>"]
    body.append(
        '<p class="muted">Пътят от история до готова статия: факти и източници → '
        "редакционен ъгъл → чернова с проверка на фактите → редакция. "
        "Черновите са неизменими; финализирането е изрично решение на редактора.</p>"
    )
    if message:
        body.append(f'<div class="notice saved">{esc(message)}</div>')
    if error:
        body.append(f'<div class="notice error">{esc(error)}</div>')
    body.append(
        "<p>"
        f'<span class="badge info">{counts["ideas"]} започнати статии</span> '
        f'<span class="badge ok">{counts["prepared"]} с факти и източници</span> '
        f'<span class="badge">{counts["drafts"]} чернови</span> '
        f'<span class="badge warn">{counts["live_cases"]} редакционни статии</span>'
        "</p>"
    )
    if not view["ideas"]:
        body.append(
            '<div class="howto"><div>Няма започнати статии. Отвори <a href="/stories">Истории</a> '
            "и натисни «Започни статия» за публикация, която си струва статия.</div></div>"
        )
    for row in view["ideas"]:
        body.append(_article_idea_card(row))
    return page("Статии", "".join(body), active="articles")


def _article_idea_card(row):
    """One idea: status, evidence packets, prepare/generate forms, drafts."""
    idea = row["idea"]
    status = idea.get("status") or "NEW"
    out = ['<section class="card">']
    out.append(f"<h3>{esc(idea['title'])}</h3>")
    status_badge = _badge(
        lb.IDEA_STATUS_LABELS.get(status, status),
        "info" if status in ("NEW", "FOLLOW_UP") else "ok",
    )
    src = lb.SOURCE_TYPE_LABELS.get(idea.get("source_type"), idea.get("source_type") or "—")
    out.append(
        f'<p>{status_badge} <span class="muted">'
        f"{esc(str(idea.get('created_at') or '')[:16].replace('T', ' '))} · {esc(src)}</span></p>"
    )
    if idea.get("what_changed"):
        out.append(f"<p>{esc(idea['what_changed'])}</p>")
    if idea.get("possible_angle"):
        out.append(f'<p class="muted">{esc(idea["possible_angle"])}</p>')
    if status in ("NEW", "FOLLOW_UP"):
        out.append(
            '<form method="post" action="/articles">'
            '<input type="hidden" name="action" value="request_draft">'
            f'<input type="hidden" name="idea" value="{esc(idea["idea_id"])}">'
            '<button class="btn primary" type="submit">Направи чернова</button></form>'
        )
    if not row["evidence"]:
        out.append('<p class="muted">Още няма факти и източници за тази статия.</p>')
    for ev in row["evidence"]:
        out.append(_article_evidence_card(idea, ev))
    out.append("</section>")
    return "".join(out)


def _article_evidence_card(idea, ev):
    """One facts-and-sources packet: prepare -> generate -> article, with honest states."""
    out = ['<div class="fact">']
    out.append(
        f"<p><strong>{esc(ev['evidence_id'])}</strong> "
        f'<span class="muted">· {ev["fact_count"]} факта · '
        f"открит {esc(str(ev['observed_at'])[:16].replace('T', ' '))}</span></p>"
    )
    for d in ev["drafts"]:
        gate_badge = (
            '<span class="badge ok">проверена</span>'
            if d["gate"] == "FACTUAL_GATE_PASS"
            else '<span class="badge warn">за проверка</span>'
        )
        out.append(
            f"<p>AI чернова: {esc(d['headline'] or '(без заглавие)')} {gate_badge}"
            f' <span class="muted">{esc(str(d["generated_at"])[:16].replace("T", " "))}'
            + (f" · {esc(d['model'])}" if d.get("model") else "")
            + "</span></p>"
        )
    if ev["case_id"]:
        out.append(
            f'<p><span class="badge ok">статия {esc(ev["case_id"])}</span> '
            f'<a href="/case/{esc(ev["case_id"])}">Редактирай черновата: '
            f"{esc(ev['case_headline'] or '(без заглавие)')}</a></p>"
        )
    if ev["prepared"]:
        mode_line = esc(lb.MODE_LABELS.get(ev["mode"], ev["mode"] or "—"))
        if ev["suggested_mode"] and ev["suggested_mode"] != ev["mode"]:
            mode_line += (
                f' <span class="muted">(предложение: '
                f"{esc(lb.MODE_LABELS.get(ev['suggested_mode'], ev['suggested_mode']))} — "
                f"{esc(ev['suggestion_reason'])})</span>"
            )
        out.append(f"<p>Режим: {mode_line}</p>")
        if not ev["case_id"]:
            out.append(
                '<form method="post" action="/articles" data-busy="1">'
                '<input type="hidden" name="action" value="generate">'
                f'<input type="hidden" name="idea" value="{esc(idea["idea_id"])}">'
                f'<input type="hidden" name="evidence" value="{esc(ev["evidence_id"])}">'
                '<button class="btn primary" type="submit">Направи чернова</button> '
                '<span class="muted">използва AI модел; резултатът минава през '
                "лексикална и семантична проверка на фактите.</span></form>"
            )
            if ev.get("last_refusal") == "RESEARCH_MORE":
                out.append(
                    '<details class="force-box"><summary>Принудителна генерация въпреки '
                    "недостатъчни факти и източници (записва се причина)</summary>"
                    '<form method="post" action="/articles">'
                    '<input type="hidden" name="action" value="generate">'
                    f'<input type="hidden" name="idea" value="{esc(idea["idea_id"])}">'
                    f'<input type="hidden" name="evidence" value="{esc(ev["evidence_id"])}">'
                    '<input type="hidden" name="force" value="1">'
                    '<label for="fr-' + esc(ev["evidence_id"]) + '">Причина</label> '
                    '<input type="text" id="fr-' + esc(ev["evidence_id"]) + '" name="force_reason" '
                    'placeholder="напр. редакторът преценява дали фактите са достатъчни">'
                    '<button class="btn danger" type="submit">Генерирай въпреки отказа</button></form></details>'
                )
    elif idea.get("status") in ("NEW", "FOLLOW_UP", "DRAFT_REQUESTED"):
        options = "".join(
            f'<option value="{m}">{esc(lb.MODE_LABELS.get(m, m))}</option>'
            for m in (
                "MODE_BRIEF",
                "MODE_STANDARD_NEWS",
                "MODE_EVENT_PREVIEW",
                "MODE_CULTURE_FEATURE",
            )
        )
        eid = esc(ev["evidence_id"])
        out.append(
            '<form method="post" action="/articles">'
            '<input type="hidden" name="action" value="prepare">'
            f'<input type="hidden" name="idea" value="{esc(idea["idea_id"])}">'
            f'<input type="hidden" name="evidence" value="{eid}">'
            f'<label for="mode-{eid}">Режим на статията</label> '
            f'<select id="mode-{eid}" name="mode">'
            f'<option value="">— каквото предложи инструментът —</option>{options}</select> '
            '<button class="btn" type="submit">Подготви</button></form>'
        )
    out.append("</div>")
    return "".join(out)


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
            '<button class="btn danger" type="submit" data-danger="1">Тази публикация не е част от историята</button>'
            "</form></div>"
        )
    body.append("<h3>Публикации</h3>")
    body.append(
        '<p class="muted">Уникални публикации, групирани по издател. Различните наблюдения на '
        "един и съща публикация са откривания, не независими източници.</p>"
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
                    '<br><span class="muted">само публични публикации</span>'
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
                "публични публикации"
                if role["payload_class"] == "public"
                else "непубликувани публикации"
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
            # A4: no blank implicit billing default — the operator must choose.
            # Free OpenRouter can only receive public material (the service
            # forces public_only=true for `billing=free`); Gemini is declared as
            # the operator's own quota (operator_declared) and never as free/paid.
            "<fieldset><legend>Тип (billing) — избира се явно</legend>"
            '<label><input type="radio" name="billing" value="free" required> '
            "Безплатен (OpenRouter) — само публични публикации</label>"
            '<label><input type="radio" name="billing" value="paid"> '
            "Платен (OpenRouter) — изисква разрешен платен режим</label>"
            '<label><input type="radio" name="billing" value="operator_declared"> '
            "Собствена квота (Gemini) — не се пита безплатен/платен</label>"
            "</fieldset>"
            '<label><input type="checkbox" name="public_only" value="1"> '
            "само публични публикации</label>"
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
            f"заявки днес: {view['usage'].get('requests', view['usage']['calls'])} · "
            f"успешни {view['usage']['successes']} · паднали {view['usage']['failures']} · "
            f"пропуснати {view['usage']['skipped']} · "
            f"лимитни откази {view['usage']['quota_failures']} · "
            f"невалидни модели {view['usage']['invalid_model_failures']}</p>"
        )
        + (
            '<div class="notice error">⚠ Платеният софт бюджет за деня е превишен '
            "(${} ≥ ${:.2f}). Роутингът продължава — това е предупреждение, не блокада."
            "</div>".format(view["paid_cost_today_usd"], view.get("soft_paid_budget_usd_day", 0.0))
            if view.get("paid_soft_exceeded")
            else ""
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
            '<p class="muted">Нови публикации от вашите източници. '
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
            '<section class="card hero"><h2>Няма нови публикации за този филтър</h2>'
            '<p class="muted">Стъпки: 1) натиснете «Събери новините сега», '
            "2) изчакайте събирането, 3) отворете първата публикация.</p>"
            '<div class="hero-actions"><form method="post" action="/inbox">'
            '<input type="hidden" name="action" value="collect">'
            '<button class="btn primary" type="submit" data-busy="1">Събери новините сега</button>'
            '</form><a href="/sources"><button class="btn secondary" type="button">Провери източниците</button></a></div></section>'
        )
        return page("Публикации", "\n".join(body), active="inbox")
    body.extend(_inbox_item(item) for item in items)
    body.append(_pager(view))
    return page("Публикации", "\n".join(body), active="inbox")
