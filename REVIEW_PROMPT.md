# Code review prompt — round 6

Copy everything below into a fresh agent with the repository at `/home/test/media`.
Give it read access to the working tree. Do **not** give it any earlier round's
report; tell it only what is true of the code now.

Five rounds have run. Rounds 1-2 found defects. Round 3 verified and corrected
one of mine. Round 4 found the **cost of my fixes** — all four of its findings
correct, including one where I had pinned a bug as intended behaviour. Round 5
answered the five things I left undecided, and **corrected my framing on all of
them**: the one-line guard is the wrong unit, the full `fetch_page` route is the
wrong shape, and the allow-list I was hesitating over is a bad idea.

**Everything below is fixed, measured, or explicitly decided.** Round 6's question
is the same one rounds 4 and 5 answered well: what has this work cost, and what
have I stopped seeing because I am close to it?

A pattern worth naming, because it is the one thing five rounds have consistently
produced: **almost every finding has been something I had already written down as
"handled", "by design", or "the operator's decision".** Every one of those was
wrong or unexamined. Treat any such sentence in this file as a lead, not a
conclusion.

One standing note before you start: three of the four things round 4 found were
things I had already written down as "handled" or "by design". Round 4's own
disagreement with me was a sentence I had overstated. Treat every claim in this
file — including the ones about what is fixed — as a claim to check, not a
premise to accept.

---

## 0. State at the time you read this

Everything below is **fixed and measured**. Do not re-report any of it.

**The snippet leak and its three residuals — all closed.** Round 1 found a Google
News snippet becoming packet facts via `promote_story_to_idea`; round 2 found the
body fix was insufficient and that a wrapper URL and the same snippet still
reached `source_url` and `what_changed`; round 3 enumerated the function and
confirmed **no fifth route**, and that `workbench://story/<id>` is safe in every
consumer (`_safe_href` is http(s)-only so it renders as text; `needs_angle_review`
returns False; `_transcript_trust` falls through; the frontend has zero
`source_type` consumers).

**F4, critical, rule 6 — fixed in `593039a`.** With neither a fact nor an opened
page, `build_packet` produced an empty `source_url`, `validate_packet` raised a
raw `EvidenceError` instead of a `DraftRefused`, and `_run_draft_generation`'s
catch-all recorded `PROVIDER_UNAVAILABLE` — a Story with nothing to read telling
the editor the provider was down.

**Two stale tests — fixed canonically, no patching.** `04b8374` (the refusal test
that patched a flag the command never reads) and `193ce21` (a parity matrix that
asserted a refusal §A deliberately abolished — it now asserts the *waiver*, which
is a stronger claim). Both files are clean for the first time this session.

**The suite was spending 8 minutes testing nothing — now 0.3s.** `593039a` and
`11fe96c`: the publication-URL resolver cascade, and the router's retry backoff
that a refusal test was paying for. No production timeout was shortened. The
coverage that fix removed is restored in `a952d69`.

### The question round 6 is actually for

Not "what is broken" — **what has this work cost, and what have I stopped seeing
because I am close to it?** Round 4 answered that question well and all four of
its findings were correct. The places below are where I have already been
wrong, so they are where I am most likely to be wrong again.

**Fixed since round 5 (`7d749ac`) — the `transcript` substring.** Both call sites
used `"transcript" in url.lower()`, so `https://example.bg/transcriptome-study`
made a biology article look like a council transcript. `source_type` is now
matched by equality and `source_url` by whole word tokens. The promote bridge
was the higher-stakes of the two: it set `source_type`, which `_transcript_trust`
reads to grant AUTO_CAPTION trust, so the mislabel ELEVATED trust rather than
merely adding a review gate. The transliteration gap (`obshtinski-svet`) is
recorded as unchanged, not closed.

**Verified by round 5, not re-reportable:** the label table (9 keys, producer scan
clean), the merge refilter, and the `_news_lookup` bounds.

**Open, and genuinely undecided — all five of round 5's items, with its verdicts:**

1. **`_news_lookup` still has no `web_fetch` guard**, and round 5 showed BOTH
   options I offered are wrong. A bare `guard_target(url)` is the wrong unit: its
   own docstring says discarding the address and letting urllib resolve again IS
   the DNS-rebinding hole. And routing through `fetch_page` as-is would break the
   function rather than harden it, because `ALLOWED_CONTENT_TYPES` is
   `('text/html', 'application/xhtml+xml', 'text/plain')` and an RSS feed is
   `application/rss+xml` — it would raise `FETCH_UNSUPPORTED_CONTENT` every time.
   The residual is DNS-rebinding on the redirect chain plus TOCTOU, on the Draft
   path, not SSRF-via-host: the host is constant and the query is quoted.
   Round 5's candidate shapes: a pinned raw-bytes helper (guard + pin + capped
   read, ~10 lines), or `fetch_page` gaining an explicit `allowed_content_types`
   for this one caller. It warns explicitly against extending the GLOBAL
   allow-list for RSS, which would weaken every research fetch. **This is the
   single most substantive open item and I have not started it.**
2. **`Source: workbench://story/<id>` reaches the model prompt verbatim**
   (`drafting/prompt.py:176`). Editor-facing rendering is verified across four
   reviews; whether the model cites it back is **unverified** — round 4 said so,
   round 5 recommended a cheap offline run, and I still have not run it.
3. **That `workbench://` path has never been checked end to end.** Five reviews
   in. Rendering, label, angle gate, transcript trust and the safety guard are
   all individually verified; the whole path in one run is not.
4. **The transliteration gap in transcript matching** is recorded, not closed. A
   slug like `obshtinski-svet` matches nothing — as it did before. Worth closing
   deliberately, or is substring matching on transliterated Bulgarian out of scope?
5. **`needs_angle_review` now matches `{съвет, общински}` as whole tokens in a
   URL.** Round 5 asked for this and I implemented it, but the cue list is mine
   and unexamined: is it right, too broad, or missing shapes?

## 1. What this is

A single-editor newsroom pipeline for the Burgas region of Bulgaria. It finds real
sources, opens them, extracts publisher prose, assembles facts, drafts articles
from those facts, and publishes to Telegram. An editor enters a one-line hint; the
system finds real citable material behind it and reports honestly what it could
not reach.

- **Backend:** Python 3.14, `src/editor_assistant/` — 119 files, ~47k lines.
- **Tests:** `tests/` — 122 files, ~45k lines. **Frontend:** React + TS, 59 files.
- **Stores:** JSON/JSONL under `var/` (gitignored). Not SQLite.
- **Run:** `python3 -m editor_assistant.workflow.cli workbench --port 8123`

### The invariant everything is judged against

> **A hint is never evidence. Only opened publisher prose becomes material.**

A search snippet is `DISCOVERY_ONLY`: it selects and ranks candidate pages and is
never promoted into a Story summary, a fact, or a draft. Nothing is evidence unless
it can be opened — `publication_material.is_readable_publication` refuses social
wrappers for that reason. A path from a snippet or an unopened page into a fact is
a **critical** finding no matter how clean it looks.

---

## 2. How this codebase thinks

`AGENTS.md` is ten working rules, each produced by a recorded failure. Treat them as
constraints, not style:

1. Never report a system state that was not measured. "I do not know" is valid.
2. 429 (quota spent, wait) and 503 (overloaded, clears in minutes) are opposite
   problems.
3. Never invent a limit and present it as external. `daily_call_limit` and
   `hard_calls_day` are local guardrails; one tighter than the provider allows is a
   bug in the guardrail.
4. Check the whole documented set before computing a total.
5. A frozen contract is a contract: five left-rail destinations, one Settings entry.
   Do not propose a sixth rail item to house a feature.
6. Never swallow an exception into a confident sentence. A catch-all reporting
   `Source unavailable` for an exhausted quota is **critical**.
7. Never verify a claim with the tool that might be the problem. If a hand-written
   probe contradicts the product, suspect the probe. Load config as the process
   does: `set -a; . ./.env`, not `env $(cat .env)`.
8. State counts exactly, and check case.
9. A destructive action gets a backup and a stated scope first.
10. Record the real cause in the commit message.

A finding violating rule 6, 1 or 3 outranks everything else. If you cannot verify
something, **mark it unverified** — an unmarked guess is worse than no finding.

---

## 3. What must NOT be re-litigate

**Fixed in `fdbe938` — the critical one.** `promote_story_to_idea` read `summary`
unconditionally, because the `candidate.get("body")` rung above it never matched:
`inbox_store.FIELDS` has no `body` field, so a collected Story's RSS snippet fell
into `build_packet_from_record` and became verbatim packet facts. Measured before
the fix: one `news.google.com` item gave `fact_count = 2`, with the wrapper URL as
`source_url`. Provenance is now explicit — a summary is material only when
`source_kind == "editor-hint"` (the page was opened and segmented); otherwise it is
refused by name. `full_text` remains a valid basis. Two regression tests added.
Do not re-report it. **Do verify the fix is complete** — see §5.1.

**Fixed in `6380aa9`.** The `if not blocks and text.strip():` rung in
`story_research.py` and `publication_material.py` is removed.

**Fixed earlier:** the browser suite's session-scoped boundary leak;
`test_api_frontend_contract`'s stale `roleHealth` set; the Story filter label read
via `inner_text()`.

Already done, not to be re-reported: the SSRF/DNS-rebinding guard, the inbox write
lock, regional filtering and all 13 municipalities, the `fetch_page()["prose"]`
verdict (27/32 corpus URLs, ~85%).

---

## 4. One early verdict was WRONG — do not inherit it

Round 1 concluded the prose fallback was "unreachable dead code". **It is reachable.**
Measured:

```
normalize_blocks("<html><body><script>var x=1;</script><style>.a{}</style></body></html>")
  -> ()
```

Empty block list, non-empty `text`, so the guard fired and manufactured a PROSE
block out of raw script and CSS. That is why it was removed.

Take this as the working example of the standard: round 1 got the direction right
and the evidence wrong, and one measurement changed the action from "delete dead
code" to "delete a reachable defect". **Measure before you classify.**

---

## 5. Product decisions that are not mine to take

These are real and unaddressed. None is a bug, and none has been silently dropped.

- **Telegram is not implemented.** Legacy Telegram/outbox code is bound to a
  SQLite/state pipeline the newsroom no longer uses. A Story-level bridge is
  needed. Two decisions are still unmade: new Stories only, or new Stories plus
  tracked developments; and bot/channel configuration is unconfirmed.
- **Official sources are mislabelled.** Many entries marked `official` are Google
  News *searches*, not direct feeds. CIK is not registered as a real source. A
  wrong `site:` domain is worse than none, which is why this was left conservative
  and needs corpus verification.
- **No verified gazetteer of villages** for regional coverage.
- **UI Bulgarian strings** (`html.py`, `labels.py`) have not had the corpus-backed
  review the sources and search terms received. This is the largest unreviewed
  surface in the project.
- **The G4.28 prose verdict is advisory-only.** Round 3 established the two call
  sites are the same deterministic call on the same bytes, and that after
  `6380aa9` the `blocks` argument is load-bearing rather than decorative. But
  neither site reads `page["prose"]`. Is the verdict earning its keep, or should
  both consume it?
- **Stored damage, operator decision.** Measured twice: 3 rows in
  `live_evidence.jsonl` carry a news.google.com wrapper `source_url` (1 fact
  each), and `ideas.jsonl` holds 61 rows with pre-fix `source_type` values. Zero
  hits in `cases.jsonl` / `live_drafts.jsonl`, so nothing consumed them. Per rule
  9: annotate, quarantine, or leave — and say what you decided and why. I have
  deliberately done nothing to `var/`.
- **The store guard stays as-is** (`tests/browser/conftest.py`), per round 3. The
  collision is real: `crontab -l` has `:17 */2 refresh` plus `:41 validate`,
  `:13`/`:43 repair, `:47 doctor` — four writers through the same script. Making
  the guard schedule-aware couples the suite to host cron and still races.
  Document the constraint: do not start full runs across an even-hour `:17`.

## 6. Test-suite facts that will mislead you

**The failure count is order-dependent and the `AGENTS.md` baseline of `17 failed`
is stale.** Do not treat it as truth, and do not call a different number a
regression without a comparison.

Two traps cost real time:

- **A `git worktree` is not a valid baseline** — no `node_modules`, so browser tests
  skip and counts are not comparable. Use the same working directory. And a plain
  `git stash` is not a baseline either **if the tree is already clean**: `stash push`
  silently creates nothing, and you will have measured your own changes while
  believing you measured the baseline. I made that mistake. Use
  `git checkout <old> -- src/ tests/`, run, then `git checkout HEAD -- src/ tests/`.
- **The browser suite's session-scoped boundary substitutes** used to leak into every
  non-browser test. Now contained by `real_boundaries_outside_browser` in
  `tests/conftest.py`; that fixture must keep its **eager** capture at conftest
  import, because a lazy one records the substitutes as the baseline.

**Always reproduce in isolation first:** `pytest -p no:randomly tests/<file>::<test>`
takes under a second for most files and separates a real defect from an ordering
effect instantly.

---

## 7. What I want back

1. **§0 points 1-3.** The missing SSRF guard, the merge-does-not-refilter
   contract, and what the global conftest override now hides. These are the three
   places a fix of mine may have cost something.
2. **§0 points 4-5.** Every remaining consumer of `source_type` and
   `source_url` reached by enumeration or substring, and the shape of the
   completeness assertion that would have caught the one I already shipped broken.
3. **Anything violating rules 6, 1 or 3**, with the exact line and the exact failure.
4. Whether the store guard should stay as-is or become schedule-aware (§5.3).
5. Everything else, marked confirmed or suspected.

For each finding: file and line, what is wrong, the concrete input or sequence that
makes it fail, and what you ran. If you ran nothing, say that.

**A standing request, and it is the reason three rounds were worth running:** if you
disagree with something above, say so and show the measurement. Round 1's one wrong
verdict changed what I did. Round 3's one correction was accepted and saved me
repeating a mistake. I would rather be corrected than agreed with, and so should
the next person to read this file.

## 8. What I got wrong today, so you do not inherit it

Recording these because a prompt that only lists successes teaches the wrong lesson.

1. **My first "fix" for the prose fallback did not work.** I captured the
   "pristine" callables lazily, on the fixture's first use — which happens *after*
   the browser suite has already substituted them, so the capture recorded the
   substitutes as the baseline and the leak survived. The comment I wrote above
   the code described exactly this hazard; I then wrote the hazard. The capture is
   eager now.
1b. **A later script-based patch of `test_manual_continuation.py` produced 203
   ruff errors** — I used a string-replacing script on a source file again. Caught
   by ruff immediately, reverted, redone by hand.

2. **My first "baseline" measurement was invalid.** The tree was already clean, so
   `git stash push` silently created nothing and the run measured my own changes
   while I believed it measured the baseline. Use `git checkout <old> -- src/ tests/`.

3. **I ran up to eleven concurrent pytest processes** while investigating, which
   made every timing number I took during that window meaningless and cost more
   time than it saved. **Kill what is running before you measure anything.**

4. **I patched source files with a generated script** and got the indentation wrong
   on every line, leaving the file unparseable. I reverted and did it by hand. Edit
   source with the editor, not with a string-replacing script.

5. **I twice "fixed" a test by patching a flag** and reverted both times, because
   the test's deeper assumption was still wrong and the green result would have been
   for the wrong reason. A test that passes for the wrong reason is worse than a red
   one: it removes the signal without adding the safety.

6. **I claimed the F4 fix changed what the stale test should expect.** Round 3
   corrected it: F4 lives in `build_packet` (post-gate) and the refusal is decided
   at the readiness gate (pre-gate), so it did not move the expected value at all.
   I had reasoned about the failure instead of tracing the two paths.
7. **I shipped a fix I had predicted would break a consumer, and only noticed by
   grepping for my own new string afterwards** — `source_type =
   "opened_publication"` had no entry in `SOURCE_TYPE_LABELS`. I had written the
   prediction into the review prompt, which is not the same as having checked it.
   It was worse than predicted: three more values were already broken in the
   operator's own store and I found them only when round 4 read the store.
8. **I found a real gap and pinned it as intended behaviour.** `publication_urls`
   not refiltering its merge was a genuine smuggling hazard; I wrote a test
   asserting that was "by design" and moved on. A test that pins a discovered gap
   as correct is worse than no test: it stops the next person fixing it and
   records the bug as a decision. Round 4 caught it; I did not.
9. **My own speed fix disabled the tests for the code it made fast.** The conftest
   fixture that removed 391s substitutes `_keyless_lookup` and `_news_lookup` in
   EVERY test, so the first two tests I wrote against those functions exercised
   the stub and passed vacuously. I did not notice for two test runs.

The through-line: **every one of these was caught by measuring, by grepping, or by
being contradicted — never by reasoning harder up front.** In cases 1 and 7 the
measurement and the grep both came *after* I was confident. "I already verified
that" is the most expensive sentence in this repository, and I have now said it
wrongly enough times for that to be a real warning rather than a slogan.
