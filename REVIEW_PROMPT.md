# Code review prompt — round 5

Copy everything below into a fresh agent with the repository at `/home/test/media`.
Give it read access to the working tree. Do **not** give it any earlier round's
report; tell it only what is true of the code now.

Four rounds have run, and round 4 is the one that changed the shape of the job.
Rounds 1-2 found real defects. Round 3 verified and corrected. Round 4 stopped
finding defects and started finding the **cost of my fixes** — and every one of
its four findings was correct, including one where I had written a test pinning a
bug as intended behaviour.

**Everything below is fixed and measured.** Round 5's question is the same one
round 4 answered well: what has this work cost, and what have I stopped seeing
because I am close to it?

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

### The question round 5 is actually for

Not "what is broken" — **what has this work cost, and what have I stopped seeing
because I am close to it?** Round 4 answered that question well and all four of
its findings were correct. The places below are where I have already been
wrong, so they are where I am most likely to be wrong again.

**Fixed since round 4 (`1e651d1`, `b4532aa`, `6e1fd3f`):**

- **Three more unlabelled `source_type` values**, found by scanning the operator's
  own `ideas.jsonl` rather than by reading code: `story_research_basis`,
  `municipality_press`, `organizer_and_ticket_platform`, plus a fourth producer
  `chernomorie_archive`. All four were rendering raw in «Статии». Now labelled,
  with `test_source_type_labels.py` walking every producer in `src/` and asserting
  coverage — a COVERAGE check, not a legality check, because the legal set is an
  operator's decision.
- **The merge now refilters.** `publication_urls` filters its union with
  `is_readable_publication`. I had written a test pinning the opposite as "by
  design" in `a952d69`; that pin was wrong and it is now flipped, with the
  reasoning recorded.
- **`_news_lookup` is bounded**: capped read, DTD refused, explicit
  `urllib.parse` import, and six direct tests for a function that had none.

**Open, and genuinely undecided:**

1. **`_news_lookup` still has no `web_fetch` guard.** It is a raw `urlopen` to a
   constant host, bypassing the DNS-rebinding pin every other outbound edge has.
   I bounded the read and refused entity expansion; I did **not** add the guard,
   because routing this through `web_fetch` is a larger change to a function the
   Draft path depends on and deserves its own review. Round 4 agreed the constant
   host makes the SSRF exposure narrow. Is it still worth doing, and is the
   one-line-guard version adequate, or does it need the full `web_fetch` route?
2. **`needs_angle_review` matches `"transcript"` anywhere in a URL.** Measured:
   `https://example.bg/transcriptome-study` fires it. Fail-closed, so harmless in
   effect, but a biology article should not need a council gate. Round 4 called
   this a pre-existing pattern that my `workbench://` change gives one more
   producer. Worth tightening, or is substring matching deliberate?
3. **A `source_type` allow-list in `ideas.validate_idea`.** Round 4 and I both
   reached this and both stopped: it needs a decision about which types are legal,
   and that is not ours to take unilaterally. It is the strict version of what
   `test_source_type_labels.py` now does loosely. What would you propose, and is
   the strict version worth the coupling?
4. **The `SOURCE:` line reaches the model prompt verbatim** (`drafting/prompt.py:176`),
   and it can now be `workbench://story/<id>`. Whether the model cites it back is
   **unverified** — round 4 said so and I have not run it. Worth running?
5. **`Source: workbench://` was never checked end to end.** Four reviews in, the
   editor-facing rendering is verified and the prompt line is not.

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

## 5. Open items

### 5.1 and 5.2 — CLOSED, verified

Both are recorded in §0 with their commits. The stored-damage question below is
the only part of 5.1 that is not code, and it needs a person.

**Stored damage, operator decision.** Measured twice, most recently by round 3:
`var/editorial_workflow/live_evidence.jsonl` has 3 rows with a news.google.com
wrapper `source_url` (1 fact each), and `ideas.jsonl` has 61 rows with no
`workbench://` and only pre-fix `source_type` values. Zero hits in `cases.jsonl`
and `live_drafts.jsonl`, so nothing ever consumed them. Per rule 9: annotate,
quarantine, or leave — and say what you decided and why.

### 5.2a The slowness — RESOLVED, but the coverage question is open

Round 2 refuted my hypothesis with a sever experiment and was right twice. Both
slowdowns are fixed, by substituting the transport rather than shortening any
product number:

- `test_draft_readiness_parity.py`: **391.54s → 0.32s** (`593039a`). The cause
  was the publication-URL resolver cascade — a live `DDGSProvider().search` plus a
  raw `news.google.com` `urlopen`, twice per snapshot, neither covered by the
  hermetic DNS shim because both bypass `web_fetch`.
- `test_manual_continuation.py`: **88.94s → 0.96s** (`11fe96c`). A second, separate
  cause: that file fails the draft role on purpose, so the router's retry backoff
  `sleep(min(2**attempt, 5))` at `model_router.py:910` ran for real. Caught with
  faulthandler — a `story-research-` daemon thread sitting on exactly that line.

Two things I want checked rather than believed:

1. **I have not run a complete suite since either fix.** Every number above is
   per-file. Establish the real total yourself before drawing any conclusion.
2. **The conftest fixture may have removed coverage, not just time.** It substitutes
   `_keyless_lookup` and `_news_lookup` to empty lists in EVERY test, so the
   publication-URL resolution path is now untested anywhere. Round 2 noted the
   same thing about `_news_lookup`'s missing SSRF guard; together these mean the
   whole resolver is now both unguarded and unexercised. Which of those matters
   more, and what is the smallest test that would put it back?

### 5.3 The runtime-store guard — SOLVED, operationally

Round 1 identified the writer: **the host's own newsroom cron** (`crontab -l`:
`17 */2 * * * /home/test/media/scripts/newsroom_cron.sh newsroom refresh`), declared
verbatim in `cli.py:1564-1569`. A full suite spanning an even-hour `:17` catches the
atomic write of `story_identity.update`. It did not reproduce on a later run only
because that run started at a different offset.

**This is a cron collision, not a test defect.** Do not "fix" it by relaxing
`assert_runtime_stores_untouched` (`tests/browser/conftest.py:64`) — that guard is
correct and is the point of rule 9. If you want a robust gate, make it
schedule-aware or document the timing constraint. Worth checking whether the cron
script and the test invocation should coordinate at all; right now they can fight,
and only by luck of timing.

### 5.4 Everything else, still open

- **Telegram not implemented.** Legacy code is bound to a SQLite/state pipeline the
  newsroom no longer uses. Two decisions unmade: new Stories only, or new Stories
  plus tracked developments; bot/channel configuration unconfirmed.
- **Official sources are mislabelled.** Many `official` entries are Google News
  *searches*, not direct feeds. CIK is not registered as a real source. A wrong
  `site:` domain is worse than none, which is why this was left conservative.
- **No verified gazetteer of villages** for regional coverage.
- **UI Bulgarian strings** (`html.py`, `labels.py`) have not had the corpus-backed
  review the sources and search terms received.
- **The G4.28 prose verdict is advisory-only.** Round 1 established the two call
  sites are the same deterministic call on the same bytes, so no disagreement is
  possible — but neither reads `page["prose"]`. Round 3 added that after `6380aa9`
  the `blocks` argument is load-bearing rather than decorative. Is the verdict
  itself earning its keep, or should both consumers consume it?
- **Nothing asserts `SOURCE_TYPE_LABELS` is complete.** `d909a37` fixed the one
  known hole; the gap that let it through is still open. A table-driven
  completeness test is the fix, and the legal-value decision is an operator's.
- **`_news_lookup` has no SSRF guard** and bypasses `web_fetch`, unlike every other
  outbound edge. Round 3 judged the constant host to make the exposure narrow but
  rated the missing guard the larger defect. Unresolved by choice, not oversight.

---

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
