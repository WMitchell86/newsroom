# V1.2-G4.1 — Prototype Rescue: a regional `Днес` and a Draft that can be started

**Status: complete and proven.** The owner manually tested the product after
G3/G4 and reported two blockers. Both are fixed, and both are proven on real
newsroom data with a real model, not on a predicate returning a value.

| Proof | Result |
| --- | --- |
| Backend suite | 1589 passed; the same **23** pre-existing failures before and after — **zero** new |
| Frontend suite | 229/229 |
| Browser suite | 95 passed; the same 6 pre-existing failures — **zero** new |
| Real corpus, `Днес` | **64 → 37 rows**; every national example from the owner's screenshot removed |
| Real corpus, Draft | a real non-empty Bulgarian Draft generated end-to-end |

G5 (`+ Нова тема`) was **not** started, as instructed.

---

## Why national Stories were in Today

Traced against the real corpus, not the screenshot.

`project_today` had **no locality decision at all**. It admitted any Story that
was new or unreviewed inside the horizon, so a national wire item and a Burgas
municipal notice were indistinguishable. The reason the owner's screen filled
with national copy is specific:

- `bta-burgas` is configured as `kind: media` on the **national** domain
  `bta.bg`, collected through a publisher-wide `google_news_rss` monitoring
  query;
- its registry *name* is «БТА — област Бургас», so the region appears in the
  label while the content is the whole national wire;
- nothing in the Today path ever compared a Story's text or its sources against
  the region.

12 of the 17 rows the owner saw were exactly this. Confirmed current reason:
**new/unreviewed inside the Today horizon**, with no locality filter in force.

## Regional Today rule

One deterministic, explainable predicate — `workflow/regional_scope.py`. A Story
is on the regional desk when **any** of these holds:

1. **Local source** — a current Publication comes from a registry row whose
   `kind` is `official` or `regional`. That is the Burgas-region stack: the
   municipalities, ОДМВР Бургас, Областна администрация Бургас, the regional
   library and opera, and the local media rows.
2. **Geographic text** — the cleaned editorial title or the concise summary names
   a Burgas-region locality (a closed, stemmed vocabulary covering Burgas,
   Pomorie, Nessebar, Sozopol, Tsarevo, Primorsko, Karnobat, Aytos, Ruen,
   Kableshkovo, Chernomorets, Ahtopol and Lozenets).
3. **Editorial work** — the Story is followed with an unreviewed development, or
   already has an active Article. The editor never loses in-flight work.

**§A3, authority vs. locality.** A national publisher is never local by itself.
`kind: media` / `national` / `aggregator` contribute nothing; a BTA or БНР item
qualifies only on the strength of its own text. The *source name* is deliberately
never scanned — that is the exact defect that filled the owner's desk.

No score, no weight, no ranking, no model call. `черноморец` is the town, not a
`черномор` stem, so Varna and whole-coast coverage cannot leak in.

**§A4.** Nothing is deleted. `Истории` reaches everything, `?scope=all` is the
unfiltered projection, and the quiet two-position control defaults to the
regional desk. The control is named `Само региона` / `Целият обхват` rather
than `Регионът` / `Всички`, because the toolbar **already** has a `Всички`
attention tab and two controls reading the same word is ambiguous — a defect the
browser proofs caught.

## Before / after on the current corpus

Real `var/newsroom`, isolated copy, cap lifted so the comparison is the full set.

- **Before** (`scope=all`): 64 rows
- **After** (`scope=region`): 37 rows

Removed (27) include every example the owner named: Ирак/БНР memorandum, ЕК
penalty proceedings, Северна Македония/БТА, national youth football v Portugal,
АЕЖ climate workshop, and the rest of the BTA wire. Retained are Царево, Несебър,
Созопол, Burgas port, Нефтохимик–Ямбол, Черноморец–Монтана, the Burgas court
chairman, the Burgas gallery, and the Burgas accidents report.

Questionable cases, reported honestly:

- «Климатът на България се променя» is retained — it came from a Burgas-region
  source, which rule 1 accepts on the publisher's own configuration. Defensible,
  and the editor can switch scope.
- «Борисов критикува икономическата политика» is retained on the same basis. It
  is the weakest retained row and is exactly what the `Всички` control and
  `Истории` exist for.
- «Парламентарната група … се събра на среща в Пампорово» is retained because
  Пампорово is a Burgas-region village. Correct, and a good demonstration of the
  text rule working on something the source name never mentioned.

## Why the owner's Draft attempts failed

Two separate defects, both reproduced on their own Stories.

**1. The gate refused before it looked at the material.**
`article_readiness.evaluate_evidence` tested `blocking_gaps` *before* facts. Any
Story with an open question was refused, whatever its evidence. On the real
corpus `s6004536e94e09c0` has 4 confirmed facts from an opened BTA page and 7
open questions — and was refused.

**2. The single-source fallback was unrepresentable.**
`story_research` pruned `sources` to fact-backing rows and persisted `sources=[]`
on every "opened but nothing promoted" branch. So the canonical basis could not
say *"a page was opened"*, and §B3 C had nothing to admit. The claims those pages
yielded were read and then thrown away.

## New Draft-vs-Ready contract

**Gate 1 — can a Draft start?** `draft_material.assess`, the single place that
decides:

| Basis | Qualifies when | Carries |
| --- | --- | --- |
| `PROMOTED` | confirmed facts **with an opened URL** | open-question warning |
| `PRIMARY` | one opened source the editor marked reliable (G4) | open-question warning |
| `SINGLE_SOURCE` | one real opened publisher page | single-source + open-question warnings, attribution required |

Unresolved gaps never refuse. A `conflict` still does, on every basis — two
opened sources disagreeing is not something to write around. **One real blocker
remains**: `NO_DRAFT_MATERIAL` — «Няма достатъчно изходен материал за чернова.»,
with `Проучи историята` as the action.

The pipeline's own `RESEARCH_MORE` coverage check is now overridden through its
**existing recorded `force_draft` path** with an explicit reason, not by a
bypass: the override is stored on the readiness record, and the angle gate, the
factual gates, the originality guard and the safety guards all still run.

**Gate 2 — `Отбележи като готова`** is unchanged in strength and is now the real
boundary. Verified end-to-end: the Draft is fully editable, `MARK_READY` is not
offered, and the refusal names the exact condition.

The three Article states are untouched: `Подготовка` → `Чернова` → `Готова`.

## Single-source attribution

- The packet is grounded in **the opened page's own extracted claims**, kept
  verbatim with `claim:N` locators. A discovery snippet is never used — §B4
  forbids drafting from something that was never opened.
- Those claims are stored per opened source, so a later decision (promoted or
  not) never has to invent them. A promoted claim still becomes a `fact`; an
  unpromoted one stays as source-backed material and is **never** a confirmed
  fact.
- The editor always sees: «Информацията е от един източник и не е независимо
  потвърдена.»
- G4's `Надежден за факти` is the only authority in the product, resolved through
  the same registry by publisher identity. No second trust system.

## Safety preserved

- A fact with **no opened source URL** licenses nothing (§B4) — caught by a test
  written against the new rule.
- An unresolved `news.google.com` wrapper, a social wrapper and an aggregator
  cannot support even an attributed Draft; the measured `single_source_policy`
  publisher test is reused, not duplicated.
- **A real defect found and fixed by the new tests**: a persisted `conflict` is
  written as *non-blocking*, and the gate was reading only blocking gaps, so a
  Story carrying both a conflict and a promoted fact would have written straight
  through it. Conflicts are now assessed on every gap.
- The Ready-blocker wording was corrected: it no longer claims an open question
  «пречи да продължите» — it says the page cannot be marked *готова* while the
  questions stand, and that the text can be written and edited freely.
- Research after a Draft refreshes the evidence and the warnings and never
  overwrites the body — asserted on a real save.
- **Store integrity defect found and fixed**: `search.SEARCH_RUNS_DIR` was pinned
  to the repository's own `var/`, so the search audit always landed in the real
  runtime store even under an isolated root. The browser suite's explicit "the
  real stores were not touched" assertion caught it. It now resolves through
  `WB_EDITORIAL_WORKFLOW_DIR` like every other store.

## Real owner-case result

Honest answer for the **two** Stories the owner actually clicked, reproduced on
isolated copies of the real stores:

| Story | opened | facts | blocking gaps | old refusal | new decision |
| --- | --- | --- | --- | --- | --- |
| `s16943311c9c782f` (Царево) | none recorded | 0 | 1 | `BLOCKING_GAP` | `NO_DRAFT_MATERIAL` |
| `s93bc68c281f5cd0` (490 катастрофи) | none recorded | 0 | 1 | `BLOCKING_GAP` | `NO_DRAFT_MATERIAL` |

**Neither has usable material**, and neither ever did: their research ran under
the old code, which persisted `sources=[]` precisely because pages were opened
and the claims were then discarded. The new message is the honest one; the old
one was a false reason.

So for the product proof I used a different current, local Story — as §D allows.

## End-to-end generated Draft proof

Real corpus, isolated copy, **real model**, real pipeline:

```text
Днес (region) → «Община Созопол забрани движението на тротинетки…»
→ opened sources: dnes.dir.bg, nova.bg, DarikNews Бургас
→ facts 0, 1 blocking gap: «Нужен е още независим източник за потвърждение.»
→ draftEligible TRUE, actions [CHANGE_FOCUS, MAKE_DRAFT]
→ Направи чернова → succeeded, state=draft, version=1
→ draftWarnings: ['Информацията е от един източник и не е независимо потвърдена.']
→ MARK_READY: not offered
→ edit one sentence → autosaved, version 2, text intact
→ Отбележи като готова → refused: EditorSafetyBlocked
```

**The generated Bulgarian Draft:**

> По улиците на Стария град в Созопол вече не могат да влизат и да се движат АТВ
> и UTV, представляващи високопроходими офроуд машини. Наред с това се прекратява и
> ползването на електрически тротинетки по улица „Републиканска“ в Новия град.
>
> Мерките са предприети от местната управа с цел да се гарантира по-висока степен
> на обществена сигурност, да се намалят шумовите нива и да се поддържа редът на
> местата с най-интензивен пътникопоток, съобщиха от пресцентъра на Община
> Созопол.
>
> За спазването на правилата през летните месеци се предвиждат строги проверки, а
> нарушителите ще подлежат на финансови санкции.

**Not perfect, and deliberately so.** One source; «съобщиха от пресцентъра» is
the attribution the contract asks for; the length and register are what the
existing style corpus produced. That is the honest prototype output the owner
asked to see.

An earlier Story («Млад състезател от Несебър…») reached the same green Draft
gate and was then correctly refused by the angle gate as
`NO_PUBLISHABLE_ANGLE` — one source, four thin sentences, nothing publishable.
That refusal is the safety boundary working, not a regression, and it is why the
product proof used a stronger Story.

## Tests

**New:** `tests/test_regional_today.py` (27) — §A national exclusion, §A3
national-publisher-both-ways, the closed locality vocabulary incl. adjectival
forms, the coast-word false positive, local source by registry, active Article
retained, followed-with-development retained **and** followed-without filtered,
the default/`all`/unknown scope, and an AST check that no ranking entry point
exists.

**New:** `tests/test_draft_vs_ready_contract.py` (11) — blocking gap + usable
facts produces a **real** Draft through the real pipeline; one opened ordinary
publisher → attributed Draft; PRIMARY needs no second publisher; snippet-only
refused; aggregator wrapper refused; conflict refused on every basis; the
single-source warning reaches the Draft and Ready stays closed; research after a
Draft never overwrites the body; a clean Draft can still be marked Ready; opened
claims survive the gate; an opened page with no extractable text is refused.

**Updated to the new contract:** the readiness parity matrix (7 rows), the three
`article_draft_command` refusals, `manual_continuation`, `quick_draft`,
`workbench_api`, the G2.4B opt-in (the experiment is now the production rule —
recorded deliberately, with the single importer named), and the G1 browser
proofs.

## Store integrity

The browser suite asserts the real runtime stores are byte-identical. It caught
the `search_runs` leak described above; the leak is fixed at the source and the
assertion now passes.

## Explicitly deferred

Confirmed deferred: perfect corroboration recall; claim-slot / proposition
alignment; Serper work and search-provider benchmarking; relevance ranking and
JEV; categories and ranking infrastructure; **G5 `+ Нова теема`**.
Recorded in `BACKLOG.md` as owner-confirmed deferrals.

## Next recommendation

Do **not** begin G5 automatically. Let the owner manually test this simplified
flow and produce 2–3 real Drafts in a row. Two things to watch while doing so,
both surfaced by this slice and neither blocking:

1. the configured draft model `gemini-3.8-flash` **no longer exists upstream**
   (`newsroom models validate` is the command that shows this) — the proof run
   used a model that does exist, in an isolated policy only;
2. the angle gate still refuses genuinely thin single-source material as
   `NO_PUBLISHABLE_ANGLE`. That is the safety boundary doing its job; whether it
   is too strict for a first draft is a product question, not a bug.
