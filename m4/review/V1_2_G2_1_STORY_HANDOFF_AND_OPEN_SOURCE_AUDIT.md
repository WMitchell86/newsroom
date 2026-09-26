# V1.2-G2.1 — Story→Draft handoff correctness and the open-source diagnosis

Owner-triggered by two defects found while reviewing the G2 prototype. This
slice implements the first and measures the second. It changes no evidence
threshold, no registry policy, no research semantics and no store.

Raw evidence: `m4/review/evidence/v1_2_g2_1_open_source_audit.json`
(the full per-Story, per-candidate trace; 24 sampled real Stories, 103 fetch
attempts, 49 extracted claims).

---

## Part A — working-title hygiene

### A1 · The measured defect (real stores, 2026-09-26)

| Measure | Value |
|---|---:|
| Stories in the newsroom | 253 |
| raw display titles containing `" - "` | 249 (98.4%) |
| raw titles matching the trailing `" - X"` decoration shape | 246 (97.2%) |
| distinct publisher tails | 37 |
| Articles in the editorial store whose title still carries a `" - X"` suffix | 14 of 14 |

Dominant tails: `БТА` (34), `DarikNews.bg` (26), `БНР` (24), `Община Бургас` (21),
`новини от Бургас и региона` (18), `faragency.bg` (17), `Община Поморие` (14),
`БНР Новини` (12), `bta.bg` (12), `burgas.bg` (10).

**Cause.** A publisher is metadata, and both the feed and the aggregator stamp
it onto the headline. The corpus proves the stamp belongs to the *publisher*,
not to the feed that carried the item: an item discovered through
`nessebar-municipality` (official) and through `google-news-burgas-region`
carries the suffix `Черноморски фар` / `БНР Новини`, because its real
`publisher_domain` is `www.faragency.bg` / `bnrnews.bg`. Every editor-facing
title then inherited it, and `Започни статия` prefills the working title from
that same string, so the defect propagated into every new Article and Draft.

### A3–A4 · The rule, and where it lives

One module, `workflow/editorial_title.py`. A trailing segment is removed **only
when structured identity data proves it is publisher decoration**:

* identity is built from the item's real `publisher_domain`, its registrable
  label, and **every** registry row claiming that host (several rows legitimately
  share a publisher domain — `burgas.bg` is claimed by both
  `burgas-municipality` and `burgas-cultural-program`, and picking one of them
  would make the decision depend on registry order);
* the tail must be 1–2 tokens, must not contain `:` or `/`, and must match the
  identity set by equality, containment, or *brand + a generic section noun*
  (`БНР Новини`);
* at most two segments are stripped (real feeds stack
  `"... - Черноморски фар - faragency.bg"`), and a head shorter than 12
  characters is never left behind;
* the discovery source is never used as publisher identity (M4B.1).

Not implemented, on purpose: `title.rsplit(" - ", 1)`. A blind split passes the
BNR case and destroys `Бургас - Поморие: затварят пътя`, which is asserted
unchanged, together with hyphenated (`Бургас-Созопол`), em-dash (`„Бушидо“ – Несебър`)
and mid-headline publisher names.

### A5 · Where it is applied

| Surface | Path |
|---|---|
| Story workspace + `Истории` list | `_story_summary` → `_story_title` |
| Today row | `editor_queries._story_attention_row` → `story_editorial_title` |
| `Започни статия` (manual) | `start_article` → `_story_title` |
| `Чернова` (Quick Draft) | `_create_quick_article` → `_story_title` |
| research topic / search query | `_research_bootstrap_context` → `_story_title` |
| default Quick Draft Focus | does not reference the Story title — unchanged |

Registry reads are cached per `(path, mtime)`, so a Today projection does not
re-read the registry once per row. The path is resolved through the canonical
newsroom root: `sources_registry.sources_path()` with no argument would read the
**repository's** registry even when the newsroom root is redirected, which
breaks test and browser-fixture isolation.

### A2 · Raw publication integrity

Unchanged and asserted: the inbox item title, the `Publication` title in every
projection, the stored source material, and `story_identity.story_cards` — the
grouping/JEV view still reads the raw collected headline, because grouping
compares real source text and rewriting the value it reads would change
identity semantics to fix a display problem.

A broken or missing registry yields an empty identity set, so titles are shown
exactly as collected rather than guessed.

### A6 · Existing Articles

Left alone, as instructed. 14 of 14 real Articles still carry a decorated title;
they are not migrated, and an editor-modified title can never be overwritten.

### Result on the real corpus

| Measure | Before | After |
|---|---:|---:|
| decorated display titles | 246 | 47 (by design) |
| cleaned | — | 199 (80.8%) |

The 47 residues are segments no structured data can attribute: a site tag
(`новини от Бургас и региона`, 18), a brand whose domain is unregistered
(`БНР Новини` 12, `ФОКУС` 4, `БНТ Новини` 3, `БургасИнфо`, `Утро Русе`,
`Про Нюз Добрич`), a bulletin number (`00 18881 / 25.09.2026 г.`), and one
municipality whose publisher host resolves to a different registry row. They
stay as collected rather than being guessed away; a site-tag dictionary is a
data decision for the owner, not a regex.

---

## Part B — why the editor so often reads "no opened source"

Nothing was weakened. The canonical path ran unchanged; only observation was
added (a wrapper around the claim extractor and the page fetcher).

### B1 · The two concepts are different, and the numbers prove it

| Path | Real count |
|---|---:|
| readiness `NO_OPEN_SOURCE` over the 14 real Articles | **0** |
| research blocking gap `Не е намерен отворен източник…` in the live research store | 3 of 3 Stories |
| `BLOCKING_GAP` readiness over the 14 real Articles | 2 |

`NO_OPEN_SOURCE` requires facts that exist but carry no opened source URL. The
canonical store refuses to persist a fact without a source URL, so in the new
store the branch is effectively unreachable — the owner was right to doubt it.
The editor-visible sentence comes from the **research** gap, not from readiness.

### B6 · The evidence funnel (24 stratified real Stories, 103 fetch attempts)

| Stage | Count | Rate |
|---|---:|---:|
| fetch attempts | 103 | |
| pages opened successfully | 99 | 96% |
| Stories with at least one opened page | 24 of 24 | 100% |
| … still on a `news.google.com` redirect | 30 | 30% |
| … on a host **absent from the registry** | 82 | 83% |
| … on an authoritative (`factual_authority`) host | 15 | 15% |
| claims extracted | 49 | |
| **facts promoted** | **1** | 2% of claims |
| Stories ending in the "no opened source" gap | 23 of 24 | 96% |

Research success rate **1/24 (4%)**, opened-page rate **100%**, fact-promotion
rate **1/49 (2%)**.

**Opening is not the problem.** Every sampled Story opened pages, most of them
several hundred kilobytes of real HTML.

### B5/B7/B10 · One dominant category per Story

| Category | Count |
|---|---:|
| `CLAIM_NEEDS_CORROBORATION` | 22 |
| `NO_RELEVANT_CLAIM_EXTRACTED` | 1 |
| success | 1 |

Authority is resolved from the page actually reached, never from the feed: 4 of
24 sampled Stories were discovered through an official-labelled feed whose real
publisher is not authoritative — the historical pattern holds, and the product
correctly refuses to inherit the discoverer's authority.

The corroboration rule groups claims by **exact normalised text** and accepts a
group only when it is `PRIMARY` (an authoritative host) or when ≥2 independent
domains produced the *identical* string. Measured: **0 of 24** Stories had two
opened pages produce an identical claim. Real publishers write the same event
differently:

```
bnrnews.bg  → "Жена и 3-годишно дете пострадаха при катастрофа на пътя Бургас-Созопол"
eranova.bg  → "Майка и дете пострадаха при катастрофа на пътя Бургас - Созопол"
```

The rule is therefore unreachable in practice, and because 83% of opened hosts
are not in the registry at all, the `PRIMARY` escape hatch is closed too. A fact
is promoted only when the Story's own publisher happens to be an authoritative
registered host.

### B9 · The one "success" is a false success

The single promoted fact is a navigation menu:

```
"НОВИНИ КУЛТУРНА ПРОГРАМА СПОРТНА ПРОГРАМА ОБЯВЛЕНИЯ ЗА КОНКУРСИ ОБЩЕСТВЕНИ
КОНСУЛТАЦИИ WWW.GOTOBURGAS.COM Обяви и съобщения ДНЕВЕН РЕД НА ЗАСЕДАНИЕ №42 …"
```

The extractor takes the first matching sentence of a page; on a municipal site
that is the menu. 2 of 49 claims were navigation chrome outright. So the real
success rate of *usable* facts is closer to zero than 4%.

### B11 · Misleading messages — copy/reason-mapping defect

In **23 of 23** measured failures the page was opened and then reported as
`Не е намерен отворен източник, който потвърждава основното твърдение.` The
sentence is literally false: the page *was* opened. Two distinct branches —
"nothing opened" and "opened, but nothing was promoted" — persist the same
text (`story_research.py`, the `if not opened:` and the `if not facts:` paths).

### Control: the title defect is not the cause

The audit ran with the Part A fix active, so all 24 searches used clean titles,
and 23 still failed. The polluted-title defect degrades search queries (the live
18:02 trace shows `… - Про Нюз Добрич Бургас` in the query) but it is not why the
evidence never lands.

### B13 · Root cause

**MIXED**, dominated by two causes that compound:

1. **`CORROBORATION_POLICY`** — the two-independent-domain rule requires
   byte-identical claim text; measured unreachable in 24/24 samples.
2. **`SOURCE_REGISTRY_AUTHORITY` coverage** — 83% of opened hosts have no
   registry row, so the `PRIMARY` path is closed for them.

With **`MESSAGE_MAPPING`** a certain secondary defect, and
**`CLAIM_EXTRACTION`** quality a serious secondary (first-sentence heuristic, one
claim per page, navigation chrome accepted). Explicitly **not** causes:
`URL_RESOLUTION` and `FETCHING` (96% of pages opened; 70 of 99 resolved to a
real publisher host).

### B14 · Recommended repairs — NOT implemented, owner decision

| Priority | Repair | Size | Why |
|---|---|---|---|
| 1 | `MESSAGE_MAPPING`: persist distinct gap texts for *nothing opened* / *opened but not promoted* / *needs corroboration* | small | the sentence is currently false 23/23 times; no evidence semantics change |
| 2 | `CORROBORATION_POLICY`: corroborate semantically (same entities/date/amount) instead of by identical string | medium | the rule as written can never fire |
| 3 | `SOURCE_REGISTRY_AUTHORITY`: add registry rows for the publishers that actually appear, or resolve authority from the reached publisher rather than a hand-maintained domain list | data + small code | closes 83% of opened hosts |
| 4 | `CLAIM_EXTRACTION`: extract several candidate claims, reject navigation chrome, prefer a sentence that answers the bootstrap question | medium | the one promoted fact is a menu |

Lowering a threshold because 4% is low would be the wrong move: the one fact that
did land was navigation text. The fix is to make promotion *reachable* and
*selective*, not weaker.

### B15 · Untouched, explicitly

`factual_authority`, `PRIMARY` semantics, two-independent-source corroboration,
blocked domains, the final-canonical-URL requirement, the research round cap,
Draft readiness, and Quick Draft orchestration.

---

## Gate

* Python 1408 passed / 2 failed — the same two failures exist at the G1
  checkpoint with this work stashed (a date-dependent registry CLI assertion and
  a live-corpus fingerprint). Zero new failures; 20 new tests.
* Vitest 172/172, typecheck, ESLint, production build unchanged.
* Browser 79/79 against the real production topology on isolated roots.
* Ruff, `compileall`, `git diff --check` clean.
* Runtime stores: the two real stores are byte-identical to the session
  baseline (0 changed, 0 added, 0 removed). Every research round in Part B ran
  in a temporary copy.
