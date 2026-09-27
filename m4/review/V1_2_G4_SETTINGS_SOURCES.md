# V1.2-G4 — Settings / Sources: minimal editor management

Owner-approved G3 → the next slice. Scope was deliberately **small**: one
polished editorial list that answers *"what are we watching, what do we trust,
what matters, and can I change it"* — with no JSON, no Workbench, and no backend
vocabulary.

**Status: complete and proven.** 11/11 browser proofs, 25 backend tests,
15 component tests, 227/227 frontend suite, and **zero** new backend failures
(1572 collected; the same 23 pre-existing failures before and after).

---

## Implemented

| Layer | What |
| --- | --- |
| `workflow/editor_source_settings.py` (new, 559 l.) | Thin application service over the **existing** canonical registry: editor-language DTOs, derived defaults, editor-language refusals, write lock. |
| `workbench/api.py` | `GET/POST /api/v1/settings/sources`, `PUT /api/v1/settings/sources/{id}`. No DELETE. |
| `workbench/spa.py` | `/settings/sources` added to the closed SPA route allowlist (**bug found by the proofs**, see below). |
| `pages/SourcesPage.tsx` + `.module.css` (new) | The screen: dense list, two toggles, inline editor, add form, one authority confirmation. |
| `pages/SettingsLanding.tsx` | `Източници` became a real link; `AI и модели` / `Система` **removed** rather than shipped empty (§3). |

### A real bug the browser proofs caught

`/settings/sources` was **not** in `spa.owns_spa_route`. Clicking through to it
worked, but any **reload or pasted URL** fell through to the legacy dispatcher and
404'd — which also served `/static/style.css`, i.e. the page silently became a
legacy Workbench page. Fixed, and pinned in `tests/test_workbench_spa_serving.py`
by adding the route to `SPA_ROUTES` (which also asserts it serves SPA HTML).

---

## Source management contract

| | |
| --- | --- |
| `GET /api/v1/settings/sources` | `{sources: [...], summary: {...}}` |
| `POST /api/v1/settings/sources` | exactly `{name, address, kind, monitored, factualAuthority, priority}` → **201** + the created row |
| `PUT /api/v1/settings/sources/{id}` | any **non-empty subset** of `{name, monitored, factualAuthority, priority}` → 200 + the updated row |
| `DELETE` | **does not exist.** A known path answers **405** and removes nothing. |

- **One registry.** `registry_path()` resolves through
  `newsroom_refresh.newsroom_paths()` — exactly as the collector resolves it — so
  `WB_NEWSROOM_DIR` moves reads *and* writes. It deliberately does **not** use
  `sources_registry.sources_path()`, which silently falls back to the repo's real
  file.
- **No raw JSON reaches React.** The client receives a purpose-built DTO.
- **Closed key set on write.** An unknown key (`sourceId`, `collector`, `status`)
  is refused **by name** with a 400. `source_id` is never editable, so evidence
  and inbox rows keep pointing at the same source.
- **Strict booleans.** `factualAuthority` and `monitored` accept only `true`/
  `false`. `"true"`, `1`, `null` are all 400 — "absent" can never mean "yes".
- **Derived on add.** The editor never types a `source_id`: it is transliterated
  from the Bulgarian name (`Пътна полиция` → `patna-politsiya`), with a numeric
  suffix on collision. A feed-looking URL is collected as `rss`; a bare host or a
  page URL is monitored through the existing `google_news_rss` mechanism built
  from the name. **No feed URL is ever guessed.**
- **Write safety (§27).** A process lock spans read → validate → write, so two
  concurrent actions cannot lose each other's field; durability is the existing
  `live_store.atomic_write`. Proven by `test_concurrent_edits_do_not_lose_a_field`.

---

## Editor terminology

| Backend | Editor label |
| --- | --- |
| `official` | Официален |
| `media` | Медия |
| `national` | Национална медия |
| `regional` | Регионална медия |
| `aggregator` | Агрегатор |
| `priority: high/normal/low` | Висок / Нормален / Нисък |
| `status: active` | Следи се: **Да** |
| `status: disabled/muted` | Следи се: **Не** |
| `factual_authority` | **Надежден за факти** |
| `health.last_status == FAILED` | Проблем |
| `health.last_status == OK/EMPTY` | Работи |
| `health` missing | *(nothing — a new source must not look broken)* |

§12 is satisfied without inventing taxonomy: every canonical kind is exposed and
there is **no "Друг"**, because the registry has no such kind to map to. The raw
enum is still returned so the client filters on the real vocabulary, never on a
parsed label. §13 shows three words and no numeric score.

---

## Factual-authority semantics

Help text on the screen, above the column it governs (§6):

> Когато източникът публикува информация от собствената си компетентност, тя може да се използва като първична фактическа основа.

Confirmation on turning it **ON** (§21):

> Този източник ще може да служи като първична фактическа основа за информация от собствената му компетентност.

**The toggle does NOT mean** "everything on this site is true". It is the
newsroom's own claim-appropriateness policy: the publisher is accepted as PRIMARY
**for information from its own competence** (municipality → its decisions;
police → its incident statements; NIMH → its alerts; utility → its outages).
Ordinary media keep needing corroboration. The existing PRIMARY path is
untouched, so the Burgas Municipality regression is unaffected.

The confirmation is **one-directional**: granting asks once, revoking is
immediate — a dialog to *lose* a restriction would only train click-through.

**No AI may set it** (§22). The value reaches the registry only from an explicit
editor boolean; the screen contains no trust score, and
`test_put_cannot_invent_factual_authority_or_reach_registry_fields` proves a
client cannot manufacture one.


---

## Current source audit

Audited against the **real** `var/newsroom/sources.json` (35 rows), not assumed.

### Burgas municipalities

| Municipality | Status | Row | Domain | Authority |
| --- | --- | --- | --- | --- |
| Община Бургас | ✅ | `burgas-municipality` | `burgas.bg` | yes |
| Община Поморие | ✅ | `pomorie-municipality` | `pomorie.bg` | yes |
| Община Несебър | ✅ | `nessebar-municipality` | `nesebar.bg` | yes |
| Община Созопол | ✅ | `sozopol-municipality` | `sozopol.org` | yes |
| Община Царево | ✅ | `tsarevo-municipality` | `tsarevo.bg` | yes |

**Three rows legitimately share `burgas.bg`** — `burgas-municipality`,
`burgas-cultural-program`, `burgas-sport-program`. The screen lists all three and
disabling one leaves the others untouched (§19, proven in both the service and
the browser).

### Requested high-value sources

| Source | Status | Detail |
| --- | --- | --- |
| **ОДМВР Бургас** | ✅ **PRESENT** | `odmvr-burgas`, `mvr.bg`, official, high, authority ✅ |
| **Пътна полиция / КАТ** | ❌ **ABSENT** | no registry row (see below) |
| **НИМХ** | ❌ **ABSENT** | no registry row |
| **ВиК Бургас** | ❌ **ABSENT** | no registry row |
| **EVN** | ❌ **ABSENT** | no registry row |
| **БНР** | ⚠️ **PARTIAL** | `bnr-burgas` declares `bnr.bg`; the real host is `bnrnews.bg` (below) |
| **БТА** | ✅ **PRESENT** | `bta-burgas`, `bta.bg`, media, high, authority ✅ |

Also present and relevant: Областна администрация Бургас, Прокуратура Бургас,
Окръжен съд Бургас, РИОСВ, РЗИ, РУО, УМБАЛ, Общински съвет Бургас (the only
direct `rss` feed), Община Карнобат (disabled), Община Айтос (disabled),
Община Приморско.

**Answer to the owner's question: да, МВР Бургас се следи** (`odmvr-burgas`,
high priority, trusted for facts). **Не, КАТ/Пътна полиция не се следи.**

### §17 — MVR / Traffic Police: recorded, not built

Per §17 **no MVR scraper was built**. What the audit established:

1. **ОДМВР Бургас needs no adapter.** It is already covered by the generic
   `google_news_rss` mechanism. Nothing to do.
2. **КАТ/Пътна полиция has no canonical publication identity in project data.**
   I did *not* invent a `kat.bg` entry. Doing so would mean guessing a feed for
   an institution the registry has never declared — exactly what §17 forbids
   ("no outlet is invented and no feed URL is guessed").
3. **The screen now makes this fixable by the owner in ~20 seconds**:
   `+ Добави източник` → `Пътна полиция` → `mvr.bg` → Официален → Надежден за
   факти. The backend derives the id, the collector and the query, and validates
   the result. That is the G4 answer: the *capability* landed, the *decision*
   stays with the editor.

**Backlog, not built:** НИМХ, ВиК Бургас, EVN — all three need an owner decision

---

## BNR domain result — reported, unchanged

**Finding: `bnrnews.bg` is a real BNR publication host; the registry declares
`bnr.bg`.** Project evidence:

- `v1_2_g2_4b_frozen_discovery.json` — **16** discovered URLs, all
  `https://bnrnews.bg/burgas/...`, plus `starazagora` and list pages.
- `v1_2_g2_1_open_source_audit.json` — an item whose `discovered_via` is
  `bnr-burgas` and whose `publisher_domain` is `bnr.bg` **opens and resolves to**
  `final_host: bnrnews.bg`, `in_registry: false`, `factual_authority: false`.
- `var/newsroom/inbox.jsonl` — real collected rows carry
  `publisher_domain: bnrnews.bg`.

**Why I did not change it** — §18 permits a data fix only if the *same official
publisher identity* is proven, and the registry has **no alias or
domain-identity field at all**. `FIELDS` is a deliberately closed schema
(`source_id, name, kind, domain, collector, url, query, status, muted_until,
priority, cadence, factual_authority, calendar, note, added_at, updated_at`).
Making `bnrnews.bg` resolve to the БНР policy would therefore require:

1. a **new registry field** (schema change to a closed schema), **plus**
2. a change to `newsroom_run.authority_by_domain` / `rows_by_publisher_domain` —
   the exact publisher-authority resolution that G2.3/G2.4B validated at
   `WRONG=0 / CHROME=0`.

That is a Research/evidence change, which §23 forbids in G4, and it would put a
frozen, measured correctness property at risk for a slice whose job is source
control. §18's own fallback applies: **report and leave unchanged.**

**It is also an editorial decision, not a mechanical one.** `bnrnews.bg` is BNR's
*national* news portal — it also carries Starazagora and Kazanlak material.
Declaring it would grant first-party factual authority across all of Bulgaria,
not just the Burgas regional service. G2.3 said exactly this: *"That entry needs
an owner decision on the institution's policy."*

**Current behaviour is the safe direction:** BNR items on `bnrnews.bg` are
treated as an unknown publisher — **no** authority, never wrong facts. Under-
attribution is the correct failure mode.

**Recommendation (not implemented):** add `publisher_aliases` to the registry in
a dedicated slice, declare `["bnrnews.bg"]` on the БНР row, and re-run the
G2.4B frozen replay to prove `WRONG=0` still holds. That is a Research change
and belongs in its own slice.

---

## Add / edit / disable behaviour

| Action | Behaviour |
| --- | --- |
| **Disable** (`Следи се` → Не) | Sets the registry's own `status="disabled"`. Normal collection stops through the existing collector behaviour. The row **stays**, keeping its publisher domain, so it remains historically identifiable. No Publication, inbox row or Article is touched. |
| **Authority** (→ Да) | One confirmation, then the canonical `factual_authority` flips. Server-verified, survives reload. |
| **Priority** | `set_priority` through the registry. Words only. Affects collection order exactly as it already did — **no new ranking effect invented**. |
| **Add** | Six fields. Id/collector/cadence/timestamps derived and validated. A feed URL is collected directly; anything else is monitored via the existing query mechanism. |
| **Edit** | Inline editor over the same row: name, `Следи се`, `Надежден за факти`, priority. `source_id`, domain and collector are **not** editable — the form cannot offer a control the backend would refuse. |

Every mutation **refetches** from `/api/v1/settings/sources`; nothing is patched
from an optimistic guess.

---

## Hard-delete decision — **not implemented**

`sources_registry.remove_source` exists and the legacy Workbench still calls it.
It is **not** exposed to the editor, because §11 requires proven safety first and
the safety is not there:


---

## Tests

| Suite | Result |
| --- | --- |
| `tests/test_g4_settings_sources.py` (new) | **25 passed** |
| `tests/browser/test_v12_g4_settings_sources.py` (new) | **11 passed** |
| `frontend/src/test/sourcesScreen.test.tsx` (new) | **15 passed** |
| `frontend` full suite | **227 passed** (7 files) |
| `tests` full suite | 1572 collected — **identical 23 pre-existing failures**, 0 new |
| `tsc -b` / `eslint .` / `ruff` (touched files) | clean |

The 23 failures are pre-existing and **unrelated** — confirmed by `git stash`
against a clean tree (`test_f2b2` corpus fingerprint, `test_story_identity`,
`test_quick_draft`, `test_workbench_newsroom`, `test_story_research`,
`test_workbench_api`). I did not touch any of them.

---

## Browser proofs

Real Chromium → real `npm run build` → real Python `ThreadingHTTPServer` → real
`/api/v1` → isolated registry. No mocked API, no Vite dev server.

| § | Proof | Result |
| --- | --- | --- |
| §29 | The five questions answered; editor language; `burgas.bg` ×3 survive; `Проблем` with no HTTP text | ✅ |
| §29 | Disable → **reload** → still off → re-enable; backend file checked | ✅ |
| §30 | Authority OFF → enable → confirmation → nothing written → `Потвърди` → **backend file changed** → reload → ON | ✅ |
| §21 | Revoking asks nothing | ✅ |
| §21 | `Отказ` leaves the registry **byte-identical** | ✅ |
| §31 | Add → row appears → **derived id** `patna-politsiya` → reload → persists; no collection triggered | ✅ |
| §10 | Edit priority; `source_id`/domain/authority untouched | ✅ |
| §32 | No AI trust words, no publishing vocabulary | ✅ |
| §23/§32 | **Zero outbound requests**; editorial dir unchanged; newsroom dir = `{sources.json, source_health.json}` | ✅ |
| §11 | No destructive action; `DELETE` → 405; row intact | ✅ |
| §34 | Five owner-review screenshots | ✅ |

---

## Screenshots

`var/g4_screenshots/` (git-ignored, like all `var/`):

```text
a-settings-sources-1440x1080.png                   the list
b-settings-source-edit-1440x1080.png               the inline editor
c-settings-add-source-1440x1080.png                the add form
d-settings-authority-confirmation-1440x1080.png    the §21 confirmation
e-settings-sources-1280x900.png                    the list at laptop width
```

Realistic current source names (Община Бургас, ОДМВР Бургас, БНР Бургас,
DarikNews Бургас, Областна администрация Бургас with a real FAILED health record).

The screen reads as a `редакционен списък`: warm canvas, one dense table, thin
rows, no cards, no dashboard. `Следи се` / `Надежден за факти` are single pills
carrying their own word, so the state is scannable down the column.

---

## Runtime-store integrity

`var/newsroom/sources.json` and `var/editorial_workflow/` are **byte-identical**
to before this slice:

```text
d4feabcbb45a54613dd53bc8baecfd8eb21ae74e107d5d8421294dc78ad9fde4  var/newsroom/sources.json
```

`git diff --stat var/` is empty. Every mutation test runs against an isolated
registry; the session-scoped autouse fixture in `tests/browser/conftest.py`
SHA-256s both real stores before the first browser test and after the last.

**§33 flag, not broadened:** the `search_runs` module-level path leak is **still
present** — `search.py:68` hard-codes
`var/editorial_workflow/search_runs` at import time, and
`story_research.py:444` only redirects it when a `root` is passed. It does not
interfere with G4 isolation, so per §33 it is recorded and left alone.

---

## Explicitly untouched

Confirmed unchanged by this slice:

- **Research algorithms** — no change to `research.py`, `story_research.py`,
  claim extraction, promotion, corroboration or the PRIMARY path.
- **Serper / Search** — no provider call, no benchmark. The browser proof asserts
  **zero outbound requests** from the Sources screen.
- **Story grouping** — untouched.
- **Ranking** — untouched. The list is ordered by the collector's *existing*
  priority rank so the screen matches collection order; no new ranking effect.
- **Categories** — the rail is unchanged.
- **Manual topic intake** — untouched.
- **Publishing** — no publish/approve/export path exists; proven by a
  vocabulary assertion over the rendered page.
- Also untouched: the PRIMARY source policy, `default_sources.py`, the legacy
  Workbench's own `/sources` page, and every runtime store.

---

## Recommended next slice

**`V1.2-G5 — + Нова тема → Research → Article`**

Not started. Per the owner's note: *"Какво искаш да проучим?"* → free text →
optional URL/context → «Проучи и започни статия», composed entirely from the
existing Research → Focus → Article → Draft primitives.

G5 is now unblocked in a way it was not before: the newsroom's source set is
inspectable and editable by a normal editor, so when a manual topic runs
Research, the editor can see and adjust what is feeding it.

### Backlog recorded, not built

- **BNR alias** — `publisher_aliases` on the registry + `["bnrnews.bg"]` on the
  БНР row, re-validated against the G2.4B frozen replay. Needs its own slice.
- **КАТ / Пътна полиция, НИМХ, ВиК Бургас, EVN** — each needs the owner to
  confirm the canonical publisher/feed, then one `+ Добави източник`.
- **Event sources (§24, untouched):** tickets.bg, eventim.bg, grabo.bg,
  Летен театър Бургас, Държавна опера Бургас, ДТ „Адриана Будевска“.
- **`AI и модели` / `Система`** — still unimplemented; deliberately absent from
  the Settings screen rather than shipped empty.
- **`search_runs` path leak** (§33).
- **Registry optimistic versioning** — not needed at prototype scale; the process
  lock is sufficient and is documented as the smallest existing mechanism.

- a removed `source_id` disappears from `newsroom_run.authority_by_domain`, so
  Publications already collected under that publisher **silently lose their
  first-party standing on re-read** — the "historical evidence breaks" condition
  verbatim;
- inbox rows, research bundles and `story_research` evidence keep the `source_id`
  as a dangling reference.

Proven from the other side too: `test_there_is_no_hard_delete_on_the_screen`
asserts the service exposes no removal function, and the API answers **405** on
`DELETE` while leaving the row intact. `Изключи` is the editor's removal, and
§8/§32 prove a disabled source never disappears from the list.

on the exact publisher/feed, exactly like КАТ. NIMH in particular is a §6
authority candidate (weather alerts) once its host is confirmed.
