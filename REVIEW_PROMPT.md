# Code review prompt — Burgas-region newsroom pipeline

Copy everything below into a fresh agent that has the repository. Give it read
access to the working tree. Do **not** give it my session history — it does not
need to know what I did today, only what is true about the code.

---

## 1. What this is

A single-editor newsroom pipeline for the Burgas region of Bulgaria. It finds
real sources, opens them, extracts publisher prose, assembles facts, drafts
articles from those facts, and publishes to Telegram. A human editor enters a
one-line hint; the system's job is to find real, citable material behind it and
report honestly what it could and could not reach.

- **Backend:** Python 3.14, `src/editor_assistant/` — 119 files, ~47k lines.
- **Tests:** `tests/` — 122 files, ~45k lines.
- **Frontend:** React + TypeScript, `frontend/src/` — 59 files.
- **Stores:** JSON/JSONL under `var/` (gitignored). Not SQLite.
- **Entry:** `src/editor_assistant/workflow/cli.py` → `workbench --port 8123`.

### The single most important invariant

> **A hint is never evidence. Only opened publisher prose becomes material.**

A search snippet is `DISCOVERY_ONLY`. It selects and ranks candidate pages; it
is never promoted into a Story summary, a fact, or a draft. If you find a path
by which a snippet, a title, or a search result reaches a fact or a draft, that
is a **critical** finding regardless of how clean it looks.

Second invariant: **nothing is evidence unless it can be opened.** A social
wrapper (Facebook/X post) is refused by `publication_material.is_readable_publication`
for exactly this reason.

---

## 2. How this codebase thinks — read before judging anything

`AGENTS.md` at the repo root is a list of working rules, and each exists because
a specific recorded failure produced it. **Treat them as constraints, not style.**
Violating one is how this project repeatedly lied to its editor.

1. **Never report a system state that was not measured.** A claim about quota,
   health or capacity must be the output of a probe run at that moment, with the
   number shown. "I do not know" is a valid and preferred answer.
2. **429 and 503 are opposite problems.** `429` = quota spent, wait. `503` =
   overloaded, clears in minutes. Treating a 503 as permanent is what made a
   healthy model fleet look dead for an afternoon.
3. **Never invent a limit and present it as an external fact.** `daily_call_limit`
   and `hard_calls_day` are *local guardrails*. A guardrail tighter than what the
   provider allows is a **bug in the guardrail** and must be reported as such.
4. **Check the whole set of documented answers before computing.** A hand-computed
   sum that omitted two roles produced a phantom over-subscription and a real,
   reverted budget cut.
5. **A frozen contract is a contract.** The left rail is five destinations; the
   Settings landing is one entry; tests assert both. Do not propose a sixth rail
   item to house a new feature — find it a home that respects the contract.
6. **Never swallow an exception into a confident sentence.** A catch-all that
   reports `Source unavailable` for every possible failure — including an exhausted
   quota — is a **critical** finding. A classified refusal keeps its own code. A log
   line, API response or UI badge must never state a cause the system did not observe.
7. **Never verify a claim with the tool that might be the problem.** Prove a system
   broken through the system's own code path. If a hand-written probe contradicts
   the product, suspect the probe. Load config as the process does:
   `set -a; . ./.env`, not `env $(cat .env)`, which leaves quotes attached.
8. **State counts exactly, and check case.** `status == "ok"` matched nothing
   because the stored value was `"OK"`, producing "zero successful calls ever" for
   a system with 170. Print the distinct values observed before concluding.
9. **A destructive action gets a backup and a stated scope first.**
10. **Record the real cause in the commit message** — the failure actually observed
    and what was verified against what, not the intended design.

### What this means for your review

- A finding violating rule 6, 1 or 3 is **critical** and outranks everything else.
- "This could drift" is low value unless you can show the drift or name the exact
  future edit that causes it.
- If you cannot verify something, **say so and stop.** Do not hand me a confident
  sentence built on an unmeasured assumption — that is the failure mode this repo
  keeps paying for.

---

## 3. Test-suite facts you must not get wrong

I burned a full day on this, so I am handing you the trap already defused.

**The failure count is order-dependent, and the baseline in `AGENTS.md` is stale.**
`AGENTS.md` says `17 failed`. That does not reproduce. Do not treat it as truth,
and do not treat a different number as a regression until you have a stashed
comparison.

For calibration, the last **complete** full-suite run I measured, at commit
`cc74a97`, was **`31 failed, 1918 passed`** with no collection errors. Treat that
as a data point, not as a target: the single commit after it (`f7ce75d`) fixed one
of those failures in isolation, so the current HEAD number is expected to be lower
but I have not re-measured it. Establish your own before drawing any conclusion.

Why it drifted, because it will bite you too:
`tests/browser/conftest.py::boundary_substitutes` is `scope="session"` and replaces
the three outbound edges **in place on the imported modules**
(`search.provider_chain`, `web_fetch.fetch_page`, `fetcher.fetch_bytes`,
`newsroom_run._now`, both drafting transports). Session fixtures tear down at the
end of the *session*, not the browser suite, and pytest collects `tests/browser/`
**before** `tests/test_*.py`. So the substitutes leaked into every non-browser test
that ran afterwards, and a 53-failure run was mostly that one effect.

It is now contained by `real_boundaries_outside_browser` in `tests/conftest.py`.
Note that fixture captures its "pristine" callables at conftest **import** time,
because a lazy capture records the substitutes as the baseline — I got that wrong
first and the leak survived the fix. If you touch it, keep the capture eager.

**Always reproduce a failure in isolation before believing it.**
`pytest -p no:randomly tests/<file>::<test>` takes under a second for most files and
separates a real defect from an ordering effect instantly. Two failures I fixed this
way were invisible in the suite and obvious alone.

### Commands

```bash
# the product
python3 -m editor_assistant.workflow.cli workbench --port 8123

# one file / one test — fastest way to tell real from noise
python3 -m pytest -q -p no:randomly tests/test_x.py
python3 -m pytest -q -p no:randomly tests/test_x.py::test_y

# two files in BOTH orders — this is how the leak above was proven
python3 -m pytest -q -p no:randomly tests/browser/test_d2a_stories.py tests/test_search_foundation.py
python3 -m pytest -q -p no:randomly tests/test_search_foundation.py tests/browser/test_d2a_stories.py

# full suite (~20 min)
python3 -m pytest -q -p no:randomly tests/

# a stashed comparison — the ONLY valid way to call something a regression
git stash push -q && python3 -m pytest -q -p no:randomly tests/test_x.py; git stash pop -q

# frontend
cd frontend && npm run typecheck && npm run build && npm test
```

A `git worktree` of an older commit is **not** a valid baseline here — it has no
`node_modules`, so browser tests skip and the counts are not comparable. I lost time
to exactly that. Run the baseline in the same working directory with a stash.

---

## 4. Already fixed — do not re-report these

- `web_fetch` DNS-rebinding/SSRF hole, closed with a thread-local pinned resolver.
- Inbox lost updates, via a per-path lock.
- Regional filtering: `official` sources self-scope; regional media alone does not
  qualify; national wire republished locally is excluded; all 13 municipalities
  covered; false positives like `Каменол` and `Велико Търново` corrected.
- `fetch_page()["prose"]` verdict (`article` / `thin` / `none`), with measured scraper
  behaviour: 27/32 real corpus URLs produce usable prose (~85%). The remainder are
  wrappers and results pages, not extraction failures.
- Test-harness fixes: stale calendar fixtures, a replay-corpus fingerprint that could
  never pass again, and the browser boundary leak above.

---

## 5. Open items, with what I already know

Ordered roughly by how much I trust my own understanding of them.

1. **Two consumers re-derive prose instead of reading the shared verdict.**
   `story_research.py:671` and `publication_material.py:381` contain the identical
   fallback `if not blocks and text.strip(): blocks = ({"kind": html_desc.PROSE,
   "text": text},)`. I have **not** established whether this is a legitimate second
   derivation or a second source of truth that can disagree with
   `fetch_page()["prose"]`. Highest-value unfinished thread.

2. **Telegram is not implemented.** Legacy Telegram/outbox code is bound to an
   SQLite/state pipeline the newsroom no longer uses. A Story-level bridge is needed.
   Two decisions are open and I have not made them: new Stories only, or new Stories
   plus tracked developments; and bot/channel configuration is unconfirmed.

3. **Official sources are mislabelled.** Many entries marked `official` are Google
   News *searches*, not direct feeds. CIK is not registered as a real source at all.
   A wrong `site:` domain is worse than no domain, which is why this was left
   conservative.

4. **Regional coverage has no verified gazetteer of villages.**

5. **UI Bulgarian strings have not had the corpus-backed review the source and search
   terms received** — `html.py` and `labels.py` in particular.

6. **A runtime store was modified during one full-suite run and I could not attribute
   it.** `var/newsroom/stories.json` was written 4 seconds before the run ended, which
   tripped `assert_runtime_stores_untouched` (`tests/browser/conftest.py:64`). It did
   **not** reproduce on a later run with the same tree. Ruled out: the live dev server
   on 8123 does not rewrite it on demand, and `/api/v1/newsroom/refresh` returns 404. I
   did not find a timed writer. **Treat this as unresolved.** Do not silence that guard
   to make the suite green — it is the signal, and the point of rule 9.

7. **One stale expectation survives.**
   `test_manual_continuation.py::test_a_fact_without_an_opened_source_never_records_a_failure_marker`
   fails on unmodified `main`, confirmed by stashed comparison. Since `V1.2-G4.3 §A`, a
   Story whose publication *can* be read is always worth a Draft, so that test's refusal
   is reachable only when there is genuinely nothing to read — yet it empties
   `snapshot["sources"]` and leaves the Story's own inbox publication intact. I made the
   publication unreadable via the shared seam; the readiness assertion then passed, but
   the command still did not raise. So the command and the readiness evaluator reach
   that decision by different paths. I reverted my edit rather than ship a
   half-understood change. **Clearest place to start.**

---

## 6. Where to look first

Read in this order; it front-loads the load-bearing decisions.

- `AGENTS.md` — the rules and the failures behind them.
- `src/editor_assistant/workflow/editor_hint.py` — hint → search → open → Story.
- `src/editor_assistant/sources/web_fetch.py` — SSRF guard and the prose verdict.
- `src/editor_assistant/sources/html_desc.py` — publisher prose extraction.
- `src/editor_assistant/workflow/publication_material.py` — what counts as evidence.
- `src/editor_assistant/workflow/article_readiness.py` — eligibility, and the
  `DID NOT RAISE` territory in open item 7.
- `src/editor_assistant/workflow/regional_scope.py` — the regional/national split.
- `src/editor_assistant/workflow/workbench/api.py` — the HTTP surface.

---

## 7. What I want back

Ordered by how much it would actually change something.

1. **Critical findings first:** any path where a non-opened source, a caught exception,
   or a swallowed error becomes a confident claim the editor sees.
2. **A verdict on open item 1** — is the duplicated prose fallback a bug or a legitimate
   second derivation? This needs reading, not guessing.
3. **A verdict on open item 7** — why does the command not raise where readiness says
   it should? Trace both paths and say where they diverge.
4. **Open item 5** — the unattributed `stories.json` writer. If you find it, that closes
   a question I could not.
5. Anything violating rules 6, 1 or 3, with the exact line and the exact failure it
   would produce.
6. Everything else, clearly marked as confirmed or as a suspicion.

For each finding give me: file and line, what is actually wrong, the concrete input or
sequence that makes it fail, and what you ran to establish that. If you ran nothing,
say so — a marked-unverified finding is useful to me; an unmarked one is worse than
nothing.

