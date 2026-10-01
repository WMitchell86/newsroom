# Code review prompt — cron self-healing + debugging trails (2026-10-01)

Copy everything below into a fresh agent with the repository at `/home/test/media`.
Give it read access to the working tree. Do **not** give it my earlier reports or
commit messages as premises — tell it only what is true of the code now, and let
it check the rest.

> **Note on this file.** `REVIEW_PROMPT.md` is a rolling slot: rounds 4, 5 and 6
> each replaced it (`2228f4a`, `cfdc4e2`, `7b7852f`, `c670754`). The previous
> occupant targeted a different line of work — the research/promote path — and its
> §0 "State at the time you read this" is now **stale** against this tree. It was
> replaced, not deleted: `git show c670754:REVIEW_PROMPT.md`.

**Range under review:** `0fd9544..HEAD` — three commits, 16 files, +1954/−33.

```
66d4cf1  fix(cron): the log directory is opened before the script that creates it
21c59ea  feat(debug): what was sent to a model, and which pages research actually tried
8fd784a  docs: the working report for the cron + debugging-trails session
```

The owner question that started this was *"check the cron job behavior, fix it"*.
It turned into four defects and two missing audit trails. **I expect the highest
value you can add is not re-confirming that the four defects were real — it is
finding what the fixes cost, and what I wrote down as "by design".**

Three facts about how I worked that should shape where you look:

1. **Most findings came from measuring, not reading.** The cron bug, the missing
   `angle` substitute, and the "34 drafts" figure were each wrong in a way that
   reading the code did not reveal.
2. **I have already been wrong in writing in this very session** — four times, all
   recorded in `m4/review/V1_2_G4_19_CRON_AND_DEBUG_TRAILS_REPORT.md` §6. Treat any
   sentence of mine that says "fixed", "by design", or "the operator's decision" as
   a **lead, not a conclusion**.
3. **This is dev mode and the numbers move.** Every counter quoted below is a
   snapshot of 2026-10-01. Re-measure; do not treat a stale number as a finding.

---

## 0. State at the time you read this

Measured and verified. **Do not re-report any of it** — it is here so you do not
have to rediscover it, and so you can spot it if it is no longer true.

**D1 — the cron jobs were dead on any fresh checkout.** `scripts/newsroom_cron.sh`
had `mkdir -p var/cron`, but a shell opens a crontab's `>> file.log` redirect
*before* running the command, so that line could never help. `var/` is gitignored
(`git ls-files var` → 0), so a fresh checkout has no `var/cron/`: all four jobs
died at the redirect, exit 2, writing nothing — while `cron_status()` only
string-matched the crontab and `doctor` answered "РАЗПИС: на място (4 задачи)".
Fixed by generating each line with `mkdir -p` before the redirect via one
`cron_line()`, and by making `cron_status()` **measure** the directory
(`logDirOk`). Verified both directions: the old line shape still dies at the
redirect; the new shape self-heals; live cron fired `14:43:01` and wrote its log.

**D2 — `angle` had no free substitute.** Its chain went from the three Gemini Flash
routes straight to two `billing: paid` OpenRouter routes. A paid route is *skipped*
when `paid_enabled: false`, so a spent Gemini budget left the role with zero
eligible routes and silent `degraded` behaviour. Added
`nvidia/nemotron-3-ultra-550b-a55b:free` and `nvidia/nemotron-3.5-lightning:free`.
`doctor` angle **0/5 → 3/7**, exit **1 → 0**, all 7 roles routable. The paid gate
was **not** loosened: 11 paid rows today, every one `SKIPPED`/`PAID_DISABLED`,
0 attempts, $0.00.

**D3 — the sent-prompt log.** `lineage.model` already recorded which model wrote a
draft; the prompt text was stored nowhere. New store
`var/editorial_workflow/model_prompts.jsonl` (mode `0600`), written in
`model_router._try_route` at the transport boundary, *before* the call. Verified on
a real Workbench rewrite: 3 draft attempts logged (gemini-3.5 → 3.8 → 3.6), the
13 024-character prompt retrievable verbatim, and the last row's model matches
`lineage.model` (`gemini-3.6-flash`).

**D4 — the research trace.** `story_research.json` records only what survived, and
the round has five drop points, each a silent `continue`. New store
`var/editorial_workflow/research_trace.jsonl` (mode `0600`) plus
`newsroom stories research-trace`. Verified on a real round: 3 `news.google.com`
wrappers dropped, `bnrnews.bg` dropped by the claim gate, story produced 0 facts
with the reason now legible.

**Gates:** full suite **27 failed / 2019 passed**, failure set **identical** to the
pre-change 27 (`diff` of the two `FAILED` lists is empty), 0 errors. `ruff check`
clean on every file touched. `newsroom doctor` exit 0. Server 200 on `/`,
`/inbox`, `/stories`, `/sources`, `/models`, `/api/v1/today`.

---

## 1. What this is

A Bulgarian-language editorial newsroom. The loop the owner cares about:
**news → sources → research/scrape → real draft → article → desk**. Collection is
a one-shot process the operator's cron calls; the repository installs no timer.

This slice is **operations and observability only**. No new editorial capability,
and nothing in the frozen UI contracts (§1 left rail, §3 Settings landing) moved.

## 2. How this codebase thinks

Read `AGENTS.md` first — it is short and every rule in it exists because of a
recorded failure. The four that bear on this slice:

- **Rule 1** — never report a system state you did not measure. A probe result and
  a conclusion are different sentences.
- **Rule 2** — `429 RESOURCE_EXHAUSTED` (quota spent; waiting is the only fix) and
  `503 UNAVAILABLE` (overload; clears in minutes) are different problems needing
  opposite responses.
- **Rule 3** — `daily_call_limit` / `hard_calls_day` are **local guardrails**. Never
  present one as a provider limit.
- **Rule 6** — never let a log line, API response or UI badge state a cause the
  system did not observe.

Two structural constraints I had to design around, and would check first if you
were extending this work:

- `model_usage`'s ledger **must never contain prompt text** —
  `tests/test_model_policy.py::test_usage_ledger_aggregates_and_never_stores_prompts`
  freezes it. D3 deliberately uses a separate store.
- `story_research_store._row()` validates a **closed** field set
  (`req <= set(v) <= req | optional`). D4 deliberately uses a separate store.

## 3. What must NOT be re-litigate

- The **contract** behind D1: a schedule whose log directory is missing cannot run,
  and `doctor` reporting it as installed is the defect. The `mkdir -p` prefix must
  precede the redirect; that is the whole fix.
- The **decision** behind D2: OpenRouter is the *provider*; `billing` is a
  per-*model* property. Free OpenRouter models are legitimate substitutes. This was
  the owner's correction and it is recorded in the commit message.
- The **`0600`** on both new stores, and the reasoning: umask is `0022`, so a plain
  `open("a")` creates `0644` and these files carry unpublished editorial text.
- The **`daily_call_limit` numbers themselves** — an owner decision, recorded, not
  re-tuned. See §5.
## 4. The four places I was wrong, and where I am therefore most likely to be
##    wrong again

This is the section I would read first if I were you.

1. **I asserted free-before-paid route ordering in a test, and it was wrong.** A
   gated paid route is a skip that `continue`s (the skip branch in
   `model_router.call_role`), so `draft` ships paid-then-free and still reaches the
   free routes. I had not read the router. The test now asserts only what the
   router depends on — **check that it is not now too weak.**
2. **I wrote an order-dependent test, then "fixed" it wrongly.** It passed alone and
   failed in a full run, caused by `tests/browser/conftest.py` setting
   `GEMINI_API_KEY` in `os.environ` with no cleanup. My first fix deleted *both*
   keys, which made the test fail alone — with no key, **every** route is skipped
   with `липсва …KEY`, so the test asserted nothing. The version that shipped clears
   only the Gemini keys. Now recorded as `AGENTS.md` rule 11.
3. **I instrumented the wrong drop point in D4.** I added traces to the in-loop
   `continue`s; my own test caught that a `facebook.com` result never appeared.
   `publisher_opened` filters wrapper/social hosts **before** the reading loop, so
   most pages never reach any in-loop point. Fixed by moving instrumentation to the
   filter. **There may be a fifth drop point I still do not trace.**
4. **Two ordering bugs in my own new code**, both caught before commit: the
   `KEPT`/`SKIPPED_CLAIM_GATE` loop read `allowed_source_ids` before
   `_promote_claims` assigned it; and `dropped_pages` was declared *below* the
   filter that increments it, so wrapper drops were traced but not counted
   (`considered` reported 2 for 3 pages). I also nearly shipped a `return` in the
   round-summary `except`, which would have abandoned the round's result.

## 5. Product decisions that are not mine to re-take

1. **`daily_call_limit` is per MODEL per day, shared by every role.**
   `model_usage.model_calls_today` has no role filter. `story` spent
   `gemini-3.8-flash` to 22 today while `story`/`angle` declare `20` and `draft`
   declares `80` for the same model, so `models status` shows the same model as
   `× 0: … днес 22/20` for story and `✓ 1: … днес 22/80` for draft. Per rule 3 the
   `20` is **ours**, not the provider's. Documented in RUNBOOK; **deliberately not
   changed.** If you think the design is wrong, say so — but do not silently retune
   a number.
2. **`qwen/qwen3.8-27b:free` is eligible but 0-for-14 today** (`EMPTY_OUTPUT` /
   `RATE_LIMITED`). Eligibility is decided by limits and health marks, not by
   whether a model has ever produced output. Flagged, not changed.
3. **Both new stores are append-only JSONL with no rotation.** They grew to 3 MB
   during one suite run before I fixed the isolation gap. There is no retention
   policy. Flagged, not designed.
4. **Dropped pages record url/host/reason but NOT page text.** Deliberate: the
   store answers "what happened", and keeping scraped bodies would duplicate the
   private evidence stores. Check whether you agree with that trade.

## 6. Facts about this environment that will mislead you

1. **The suite's 27 failures are pre-existing.** The `AGENTS.md` baseline list is
   measured but goes stale; it was itself wrong before this session
   (`test_model_policy` 2 and `test_quick_draft` 7 were both clean on 2026-10-01).
   **Always compare failure SETS against a stashed baseline, never counts.**
2. **`tests/browser/` skips entirely in a fresh `git worktree`** (no
   `frontend/node_modules`), so a worktree is *not* a valid baseline for those 6-7
   failures. Compare in the real tree. I used a worktree once and nearly drew the
   wrong conclusion.
3. **`tests/browser/conftest.py:146` leaks `GEMINI_API_KEY`** into `os.environ` for
   every later test file. Any routing test written against ambient state is
   order-dependent. Prove order-independence by running the polluting file **and**
   yours together.
4. **`var/` is gitignored**, so neither new store appears in the diff. To see them:
   `ls -l var/editorial_workflow/{model_prompts,research_trace}.jsonl` — both
   `0600`. Do not `cat` them into a report; they hold unpublished editorial text.
5. **The numbers in this prompt and in the report are a 2026-10-01 snapshot.**
   Re-measure before quoting one.

---

## 7. The open defect — the most useful thing you could finish

**The cron path never records grouping health.** Verified, still true, unfixed:

```
cli.py  _run_newsroom_refresh  ->  story_identity.update(...)        # never records
newsroom_refresh.refresh_newsroom -> record_run_stories / record_run_grouping
```

The CLI path is what `crontab` calls every hour; the recording lives only in the
Workbench path. Measured consequence: after the 16:17 cron run the log reported
`семантично групиране: 10/6 класифицирани`, yet `var/newsroom/last_run.json` has
**no `grouping` key** and `GET /api/v1/today` returns **`groupingHealth: null`**.

`_today_grouping_health()` maps a missing block to `None` = *unknown*, and the
frontend renders unknown as **no warning**. So every cron-refreshed run that
degraded is **silent to the editor** — a rule-6 shape, on a path an editor actually
uses. I stopped because it was outside what was asked and I would rather not change
assessment semantics unasked; that judgement is yours to overturn.

If you take it: the fix is small, but **think about whether the CLI path should
also record `new_stories`** (it has the same gap), and whether a cron run that
*fails* should leave the previous run's record intact.

---

## 8. What I want back

Prioritised, and **specific** — a file:line and a failure mode, not a category.

1. **The cost of the D1 fix.** `cron_line()` is now the single source of the
   crontab line shape. What breaks if someone hand-edits the crontab, adds a fifth
   job, or changes a log filename? Is there any path where `cron_status` and the
   real crontab can still disagree silently?
2. **Whether the two new stores can leak or grow without bound.** Both hold private
   text. Is `0600` maintained on **every** path that creates them (including if
   `os.chmod` fails), and what happens if `var/editorial_workflow/` does not exist
   or is a symlink?
3. **The D3 capture point.** I log in `_try_route` before the transport, on the
   argument that the failed attempts are the interesting ones and that the text is
   unchanged by the call. Check that argument: does any provider path mutate
   `prompt_text` before sending? Is logging once per *retry* (not per request) the
   right granularity, given `attempts_allowed` can be 2?
4. **The D4 completeness claim.** I traced five drop points. Find the sixth — a
   `continue`, an early `return`, or an exception path in `execute_story_research`
   where a considered page leaves no row.
5. **Anything in §4 where I over-corrected.** Especially whether the
   `considered == len(pages_seen)` assertion is now testing the trace rather than
   the behaviour.
6. **Whether my tests are vacuous.** I verified the best-effort guards by sabotaging
   them and watching the tests fail. Do the same for the rest: mutate each new
   assertion and check it actually fails.

## 9. What I got wrong today, so you do not inherit it

The four items in §4, plus one more that is easy to repeat: **I added a private
store and forgot to add it to the autouse isolation fixture**, so one full suite run
wrote 328 rows / 3 MB of test prompts into the operator's own file — silently,
because nothing reads that file automatically. It would have surfaced only as the
editor opening `newsroom models prompts` to a wall of fixture text posing as their
own drafts. Backed up to `var/backup_pre_promptlog_clean_1649/`, cleaned, fixture
fixed, regression tests added. **If you add a store, add its env var to
`tests/conftest.py` in the same commit.**

