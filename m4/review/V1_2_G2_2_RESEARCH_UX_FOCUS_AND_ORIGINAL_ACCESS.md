# V1.2-G2.2 — Research UX + Focus friction + original source access

**Status:** complete, committed, pushed. Awaiting owner review.
**Scope:** editor-facing operational defects only. **No evidence semantics were touched.**

---

## 1. Research operation UX

### The defect

`RESEARCH_POLL_BUDGET` in `frontend/src/api/client.ts` was still
`{ attempts: 8, delayMs: 250 }` — **exactly 2 seconds** — left over from before
the D2B cutover, while Quick Draft had been given `180 × 1000ms`. A real
research round performs a web search and opens pages, so it routinely outran the
budget. The client threw `Проучването все още не е готово. Опитайте отново.`
**while the backend operation was still correctly running**, and the editor was
invited to start a second one.

### The change

| | old | new |
|---|---|---|
| Research | `8 × 250ms` (≈2s) | `180 × 1000ms` — the shared long policy |
| Quick Draft | `180 × 1000ms` | unchanged, now *the same named constant* |
| Draft / Обнови | `60 × 1000ms` | unchanged |

`LONG_OPERATION_POLL_BUDGET` is the single long-operation policy; Quick Draft
aliases it, so Research can no longer drift behind it again. There is still
**one** polling loop, **one** operation registry and **one** research command.

`researchMoreStory` no longer pretends an exhausted budget is a failure. It
returns a real outcome type:

```ts
type ResearchOutcome =
  | { status: "completed"; story: StoryDetail }
  | { status: "continuing"; operationToken: string };
```

- `completed` → the Story is refetched automatically.
- `continuing` → the UI says **`Проучването продължава.`** and exposes
  **`Провери статуса`**, which reattaches to the *same* token via
  `checkResearchStatus()`. It never issues a second `POST …/research`.

A transport timeout is no longer reported as a research failure anywhere.

---

## 2. Quota / provider messaging

Previously one sentence — `Няма наличен източник за проучване.` — covered
three unrelated things, and two of them are not about evidence at all. They are
now three distinct refusals:

| situation | code | HTTP | editor sees |
|---|---|---|---|
| Story not in a researchable state | `INVALID_TRANSITION` | 409 | unchanged state refusal |
| no search provider/route at all | `RESEARCH_UNAVAILABLE` | 503 | `Автоматичното проучване временно не е налично.` |
| bounded research-round budget spent | `RESEARCH_QUOTA_EXHAUSTED` | 429 | `Лимитът за автоматично проучване е изчерпан за момента.` |

Quota wording is used **only** where the backend really knows the cause: the
canonical round counter against `readiness.MAX_RESEARCH_ROUNDS`. It is never a
guess about a provider. No route id, model name, provider name or HTTP status
crosses the boundary — a browser proof asserts the absence of each.

A `default_message` on the error base class guarantees a class-level refusal
always carries its editor-safe sentence (the API boundary sends `str(exc)`, which
would otherwise have been empty).

**A useful side effect:** `RESEARCH_MORE` was already offered only when a
provider exists *and* rounds remain, so with no provider the product does not
offer research at all. The new codes cover the real race — the provider
disappearing between the page being projected and the click.

---

## 3. Unassessed Article behaviour

`STORY_UNASSESSED` is now phrased as the next step, not an error:

- was: `Историята трябва първо да бъде проучена.`
- now: **`За чернова първо е нужно проучване на историята.`**

The Article preparation page renders that one sentence plus
**`Проучи историята`**, which issues the **same canonical
`POST /stories/:id/research`** the Story workspace issues and then refetches
Article + Story. The Story remains the sole owner of research orchestration —
this is a convenience adapter, not a second Article research workflow. A quiet
`Отвори историята` link sits beside it.

The same sentence now lives in one place in each layer (`article_readiness`,
`article_generation._OPERATION_ERRORS`, `workbench/api._MESSAGES`) and a test
pins the agreement so they cannot drift again.

---

## 4. Focus simplification

There is **no** separate confirmation action. The `Избери фокус` /
`Промени фокуса` submit button and the `Фокусът е предложение и очаква
редакторско решение.` note are **removed entirely** — not renamed.

New contract:

```
trimmed Focus non-empty  →  valid/confirmed Focus
Focus empty              →  Draft cannot start
```

- The field saves on blur through the existing canonical `PUT …/focus`.
- `editor_article_store.update_editor_focus` sets `focus_confirmed_at` whenever
  the saved Focus is non-empty, and sets it to `None` when cleared. The
  persistence field is kept and maintained automatically.
- Clearing the Focus is now *possible* (it previously raised
  `editorial_focus is required`) and withdraws the confirmation, so readiness
  and the Draft action follow exactly the text the editor left on the page.
- With an empty Focus the Draft action is absent and the single sentence reads
  **`Добавете редакционен фокус, за да създадете чернова.`** — actionable, and
  with no confirmation concept anywhere.

Quick Draft is untouched: one `Чернова` click still confirms its deterministic
default Focus (`_confirm_quick_focus`), and no Focus screen was introduced.

---

## 5. Original publication access

- `Отвори оригинала ↗` in the Story header, `target="_blank"`
  `rel="noreferrer noopener"`.
- The URL is **not** reconstructed in React. The backend now projects
  `originPublicationId`, computed from the Story's stored
  `representative_item_id` — the ORIGIN member the domain already kept.
- No valid origin → the action is not rendered at all.
- Each publication in `Публикации` gets its own `Отвори ↗` link.

`Публикации ≠ Факти и източници` is preserved: a link is publication
navigation, and a browser proof asserts the section never implies
verification.

---

## 6. Research message mapping

The one sentence that was false in **23 of 23** measured real failures is gone.
`story_research` now names three distinct reasons and persists the true one:

| branch | persisted reason |
|---|---|
| nothing was opened | `Не успяхме да отворим подходящ източник.` |
| pages opened, no claim existed | `Намерени са източници, но информацията още не е достатъчно потвърдена.` |
| a claim existed but did not pass the promotion gate | `Нужен е още независим източник за потвърждение.` |

Only the first branch may claim that opening failed. **Which cases count as
evidence, the authority rules, the corroboration gate and every threshold are
byte-for-byte unchanged** — this slice only stops the product misreporting which
branch it took. The same text is also used for the defensive fallback gap.

No new reliability language was authored anywhere (§11).

---

## 7. Tests

| suite | before | after |
|---|---|---|
| Python | 1467 passed / 22 failed (baseline) | **1479 passed / 22 failed** |
| Vitest | 175 passed | **187 passed** (5 files) |
| Browser (G2.2 file) | — | **5 passed** |

The 22 Python failures are **byte-identical before and after** this slice
(verified by running the whole suite on a stashed tree and diffing the failure
sets: `comm` shows zero entries in either direction). They are pre-existing and
environmental — date-dependent Today fixtures, live-corpus fingerprint, and
network-dependent provider tests. None is caused by G2.2, and none was fixed
here.

New coverage:
- `tests/test_research_ux_contract.py` (12) — focus contract, the three
  operational refusals, message/code agreement, the three honest gap reasons,
  origin publication projection.
- `frontend/src/test/researchUx.test.tsx` (12) — pending past the old budget,
  the continuing state and reattach, both operational codes, the Focus
  contract, the original and publication links.
- `tests/browser/test_v12_g2_2_research_ux.py` (5) — see below.

Existing tests that pinned the retired behaviour were updated to the new
contract, keeping their intent: the focus-confirmation note, the
`Избери фокус` control, the `Подготовка за чернова` heading (now
`Фактическа основа`), and the old `Проучи още` link on the Article page.

---

## 8. Browser proof

Real `npm run build` output, real `ThreadingHTTPServer`, real `/api/v1`,
isolated store root, real Chromium. Only the three outbound edges are
substituted, and the research edge is shaped to the two real conditions.

1. **§14 — a 5-second research round.** The substituted opener is slowed past
   the old ~2s budget. Sampled across the window: the control stays
   `Проучва се…` and enabled-as-pending, `Проучването все още не е готово` and
   `Опитайте отново` never appear. On completion the Story updates **with no
   reload and no navigation**, the URL is unchanged, and the canonical
   `research_rounds` counter reads exactly **1** with exactly one
   `POST …/research` observed.
2. **§15 — the provider disappears after projection.** Operational wording is
   rendered; the alert contains no evidence claim and no internals; the round
   counter is unchanged.
3. **§15 — no provider at all.** Research is not offered, and no false claim
   appears.
4. **§15 — the round budget is spent after projection** (the real counter, not
   a faked reason). `Лимитът за автоматично проучване е изчерпан за момента.`,
   the stored gaps are byte-identical, the alert never mentions a source.
5. **§9/§17 — the original publication** renders as one safe external link, and
   every publication is reachable without the section implying verification.

The harness gained one narrow, explicitly-scoped allowance:
`PageProbe.assert_refusal_clean(status=…)`, used only where the error status
*is* the answer being proven (503/429), following the existing 409 precedent.
It excuses that one status line and nothing else.

---

## 9. Runtime-store integrity

274 real runtime files, SHA-256 before and after every browser run: **0
changed**. The session-scoped autouse gate in `tests/browser/conftest.py`
asserts this for the whole suite. The newest runtime mtime predates this work.

---

## 10. Explicitly untouched

Confirmed unchanged, and still covered by the V1.1-A/B suites that pass:

- corroboration semantics and the two-independent-source requirement;
- source authority / registry coverage;
- claim extraction;
- every evidence threshold and safety invariant;
- Quick Draft behaviour;
- the `Публикации` vs `Факти и източници` distinction.

---

## 11. Recommended next slice

**`V1.2-G2.3 — Research Evidence Promotion Repair`** — *not started.*

The product is now honest, and honest is still not a Draft. G2.1's diagnosis
stands: exact-text corroboration never matched independent publishers in
24/24 samples, 83% of opened hosts are absent from the registry, and the
extractor promoted navigation chrome as its single fact. Repairing only the
message made the experience comprehensible; it did not make it productive.
