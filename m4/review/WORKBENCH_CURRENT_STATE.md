# Workbench Current State — Honest Assessment

## What the editor sees today

When the editor opens `http://127.0.0.1:8123/`, they land on a page titled
**"Опашка — Редакторски работен плот"** with a table of 16 M3A case files
(LIV-01 through LIV-06, WFX-01 through WFX-10) — a frozen editorial workflow
from a previous milestone that has nothing to do with their daily newsroom work.

The top navigation bar shows 6 links as pipe-separated text on a blue header:

```
Истории | Материали | Източници | AI модели | Случаи | YouTube
```

There is no sidebar. There is no visual hierarchy. Every page has the same
dense, developer-oriented layout. There is no "today's dashboard" — no "what
do I need to do right now" view.

## How this happened

This is the result of an AI agent (me) building features spec-by-spec from
milestone plans without ever stepping back to ask: **"What does the editor's
morning look like?"**

The plans said:
- M3A: case editing workbench → built
- M4A: source registry → added to the same nav bar
- M4B: inbox → added to the same nav bar
- M4C: stories → added to the same nav bar
- M4D: model routing → added to the same nav bar

Each feature was implemented in isolation. The result is a flat list of 6
equally-weighted tabs where every page is equally accessible and equally
overwhelming. The agent never redesigned the navigation to reflect the
actual editorial workflow.

## What the editor actually needs daily

An editor at a municipal news desk opens the system once or twice a day.
Their workflow is:

1. **"What's new?"** → see new stories/materials that arrived since last visit
2. **"Read and assess"** → scan story summaries, read related articles
3. **"Decide"** → accept, reject, merge, split, or defer a story
4. **"Write"** → take a story and turn it into an article (future)

They do NOT need daily:
- Source registry management (setup, not daily)
- Model routing configuration (setup, not daily)
- YouTube intake results (secondary source, rarely)
- M3A case queue (frozen, different workflow)

## Current page inventory vs. editor value

| Page | What it shows | Editor needs this daily? |
|------|--------------|------------------------|
| `/` (Случаи) | Frozen M3A case queue — 16 old cases | **No** — this is a different workflow |
| `/stories` (Истории) | Grouped stories from collected materials | **Yes** — this is the main view |
| `/inbox` (Материали) | Raw collected articles | **Sometimes** — to check individual items |
| `/sources` (Източници) | Source registry + blocked domains | **No** — setup, not daily |
| `/models` (AI модели) | 7 model roles × 4-7 routes each, with ↑↓ toggle remove | **No** — operator config, not editorial |
| `/intake` (YouTube) | YouTube intake results | **No** — secondary source |

## The core problem

**The system has no concept of "today."**

There is no page that answers: "What happened since I last opened this?"
The `/stories` page shows all stories, not "new since yesterday."
The `/inbox` page defaults to NEW items but has no timestamp-aware landing.

An editor opens the app and sees either:
- A table of old case files they don't use (the default `/` page)
- A list of 6 equally-weighted nav links they have to understand

There is no guided path. No "start here." No visual priority.

## What the nav actually communicates

The current nav (Истории | Материали | Източници | AI модели | Случаи | YouTube)
tells the editor: "These 6 pages are equally important. Figure out which one
to open."

A non-technical editor will:
1. Click the first link (Истории) — OK, this is useful
2. See "Няма истории" — give up
3. Not know that they need to click "Обнови историите" first
4. Not know that "Материали" has the raw collected items
5. Never touch "AI модели" or "Източници" — correctly, these are admin

## What modern editorial tools look like

Every professional editorial tool (WordPress, Ghost, Notion, Google Docs for
newsrooms) uses:

1. **Left sidebar** with 2-3 items max:
   - Dashboard / Inbox (what needs attention)
   - Stories / Posts (the work)
   - Settings (admin, collapsed or behind a gear icon)

2. **"Today" view** as the landing page — not a list of all items ever

3. **Progressive disclosure** — admin features hidden behind settings, not
   in the primary nav

4. **Visual hierarchy** — the main action ("review new stories") is a big
   button, not a link in a pipe-separated list

## What should change (architecture, not CSS)

### 1. The landing page should be "today's stories"

`/` should redirect to a "Днес" view that shows:
- New stories since last visit (or today in Europe/Sofia)
- New materials count
- One-click "Събери новите сега" button

### 2. Navigation should be a left sidebar with 2-3 items

```
┌─────────────┐
│ Новини      │  ← stories + inbox combined
│ Източници   │  ← source management (collapsed section)
│ Настройки   │  ← model routing, blocked domains (collapsed)
└─────────────┘
```

"Случаи" and "YouTube" should not be in the primary nav at all. They are
reachable via URL but not promoted.

### 3. Admin pages should be visually distinct

The `/models` page should look like a settings panel, not an editorial page.
Different background color, smaller font, "Settings" label in the header.

### 4. Empty states should guide action

"Няма истории" should be followed by a prominent button: "Обнови историите
сега" — not a separate section below the fold.

### 5. The CSS should be extracted to a shared file

5 pages × 5 KB inline CSS = 25 KB of duplicated stylesheets. This is a
trivial fix but it also means every page reload re-parses the same CSS.

## What I (the AI) should have done differently

1. **Designed the navigation first** before building any page — asked "what
   does the editor see when they open the app?" and worked backward.

2. **Not added every new feature to the top nav** — each milestone should
   have considered where its feature fits in the information hierarchy.

3. **Built a "today" dashboard** as the first M4 deliverable, before any
   individual page.

4. **Treated the M3A case queue as a separate app** — it was frozen, so it
   should not pollute the M4 newsroom navigation.

5. **Asked the user** "how should the editor navigate this?" before building
   6 equally-weighted tabs.

The technical implementation is solid — the backend works, the data model is
correct, the forms function. But the UX was never designed; it was accreted.
