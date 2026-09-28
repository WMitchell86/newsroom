# Coding Harness — V1.2-G4.4 Async Draft Start

## Starting point

Current clean repository state at `b8d44ea`. Expected gates:

```text
browser suite = 95 passed / 6 pre-existing failures
test_natural_draft_loop = 44 passed
real production proof = Чернова, Пренапиши, Voice, version recovery, feedback
```

**G4.3 is signed off.** Do not add product features and do not start G5.

Fix **one** UX defect. Build no new subsystem.

---

# The defect

`POST /api/v1/articles/{articleId}/draft` performs `_draft_snapshot(...)` and
the automatic bounded enrichment **synchronously, inside the HTTP request**,
before it returns the operation token. Measured on the owner's real runtime: the
browser is frozen for roughly 40–70 seconds, with no feedback of any kind.

The exact shape, in `workflow/editor_application.py::start_article_draft`:

```text
1877  with _COMMAND_LOCK:
1879      snapshot = _draft_snapshot(article_id)     # reads + enrichment, SLOW
1889      readiness = article_readiness.evaluate(snapshot)
1890      dto = _article_dto(...)                    # another full projection
1910      return {"operationToken": token, ...}      # the token arrives LAST
```

Two symptoms, one root cause:

1. the token — and therefore any UI feedback — arrives only after the slow work;
2. **the global `_COMMAND_LOCK` is held for the whole 40–70 s**, because the
   `with` block encloses the snapshot. Every other editor command on the server
   waits behind it.

Quick Draft already does this correctly: `start_quick_draft` returns
`202 {operationToken}` and does its real work inside the operation worker.

## Two things that are ALREADY correct — do not "fix" them

Verified while writing this task:

1. **The UI loading state already exists.** Both
   `frontend/src/pages/today/TodayStoryActions.tsx:5` and
   `frontend/src/pages/PreparationWorkspace.tsx:346` already render
   `Подготвя се чернова…`. It simply never becomes visible, because the token
   that drives it arrives last. **No frontend change should be needed** — if you
   find yourself editing a component, the server-side fix did not work.
2. **The specifications already describe the async pattern.** §15.2 says: "Use a
   bounded operation runner: finish synchronously within the request budget;
   otherwise return `202 { operationToken }` and poll a transport-only endpoint."

So this is a **code-versus-specification** defect, not a design change and not a
documentation change. The implementation is wrong; the spec and the UI are
already right.

---

# Required behavior

```text
click Чернова
  -> request returns 202 {operationToken} quickly
  -> UI immediately shows "Подготвя се чернова…"
  -> worker performs snapshot + bounded enrichment + style retrieval + generation
  -> polling resolves
  -> Article opens/refreshes with the Draft
```

Move **all** potentially slow work out of the request path: source opening,
automatic enrichment, style retrieval, model generation.

The synchronous request may do only this:

- cheap validation;
- Article lookup;
- idempotency / in-flight reattachment;
- operation creation.

**Reuse the existing operation-token infrastructure** already used by Quick
Draft. Do not create a second job system, a second registry, or a second polling
loop.

---

# Semantics that must not change

Every G4.3 guarantee has to survive this change:

- enrichment failure never blocks a Draft from a readable source;
- Focus is not a gate;
- the selected Voice reaches generation;
- warnings survive to the Draft;
- the immutable generated version and the Article working version stay correct;
- a repeated click while an operation is running **reattaches** to the running
  operation rather than starting a second generation;
- **no duplicate model spend**.

## Concurrency rule

The operation uses the Article input state **captured when the editor clicked**.
If the Article's content or state becomes incompatible while generation is
running, fail safely or require an explicit retry — never silently overwrite
newer editor work.

The stale-version revalidation that currently runs at the top of
`_run_draft_generation` is what makes this safe. It must survive, and it must now
run against the state captured at click time.

## Locking rule

**Do not hold a global or per-Article mutation lock across a network call or a
model generation.** Lock only around short canonical reads and writes.

The in-process one-generation-per-Article guard (`article_generation.acquire` /
`release`) is correct and must stay, but it is a *guard*, not a mutex held for
the duration of the work.

---

# Acceptance — on the production server and real runtime

1. Click `Чернова`.
2. Loading feedback becomes visible **immediately**; the page must not appear frozen.
3. Force enrichment or generation to take >10 s and prove the request has
   **already returned** while the work continues.
4. On success, a real Draft appears.
5. A double-click / repeated request produces **one** operation and **one**
   generation.
6. Failure preserves the Article and offers a retry.

# Measure and report

- time from click to `202 {operationToken}`;
- total Draft time;
- number of search/enrichment calls;
- number of Draft model calls;
- proof of exactly one in-flight operation.

Target: the token returns well under 1 second on local runtime, with all long
work after that.

# Specifications

Update the authoritative specs **only if** they still describe Draft generation
as synchronous. Check at least:

```text
m4/review/IMPLEMENTATION_ARCHITECTURE_V0_1.md   §15.2, §16.2
m4/review/EDITOR_WORKFLOWS_V0_1.md
m4/review/EDITOR_WIREFRAMES_V0_1.md             the inline loading state
m4/review/BACKLOG.md
```

**They already do.** §15.2 states the bounded-operation pattern, and the UI
already has the pending label. Expect to change **no** specification and **no**
frontend file. If you find yourself editing either, stop and re-read this
section — it means the server-side fix is incomplete.

# Do not

- add product features;
- start G5 (`+ Нова тема`);
- weaken an assertion to make a scenario pass;
- introduce a second job/operation system;
- change the Draft, enrichment, rewrite, voice or feedback contracts.

**Stop after this fix and the report.**
