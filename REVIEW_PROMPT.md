# Code review prompt — round 2

Copy everything below into a fresh agent with the repository at `/home/test/media`.
Give it read access to the working tree. Do **not** give it round 1's report; tell
it only what is true of the code now.

Round 1 produced one critical finding, one wrong verdict, and one thing neither of
us closed. This prompt reflects all three, so round 2 spends its effort where it is
still unspent.

---

## 0. State at the time you read this

Round 2's findings have been **acted on and measured**. Do not re-report these.

**F4 — CRITICAL, rule 6, FIXED in `593039a`.** `build_packet` refused only for
`not facts and opened`. With neither, it built a packet with `source_url = ""` and
`facts = []`, so `validate_packet` raised a raw `EvidenceError` — not a
`DraftRefused` — which escaped `generate()` into `_run_draft_generation`'s
catch-all and recorded `reason_code = PROVIDER_UNAVAILABLE`. A Story with nothing
to read was told the provider was down, and the projection then offered EDIT.
Reachable precisely because waiving `DRAFT_FROM_UNREAD_SOURCE` is correct; the
branch for "that one read returned nothing" was missing. Now classified
`NO_DRAFT_MATERIAL`, which is already absent from `QUALIFYING_REFUSALS`.

**F1 — FIXED in `c4e1324`.** A collected item is no longer the provenance carrier
at all. With editor text and no opened page, the packet is attributed to
`workbench://story/<id>`. `source_type` is now `opened_publication`, not
`upstream_press_release`.

**F2 — FIXED in `c4e1324`.** Same commit; that was the last false claim in the
function.

**F3 — FIXED in `796cab5`.** The promote form now carries a `full_text` textarea
and `http.py:800` passes it, so the control can succeed rather than only refuse.

**§5.2a's slowness — FIXED in `593039a` and `11fe96c`.** Your sever experiment was
right and my hypothesis was wrong. `test_draft_readiness_parity.py`:
**391.54s → 0.32s**. `test_manual_continuation.py`: **88.94s → 0.96s**. Same
failures either way, so the time was never testing anything. No production
timeout was shortened.

**The coverage that fix removed — RESTORED in `a952d69`.** You pointed out the
conftest fixture left the resolver cascade with no exercise at all. That is now
`tests/test_publication_url_resolution.py`: the real function, canned lookups, no
network. Writing it surfaced a real contract — **`publication_urls` does not
refilter what it merges**, it trusts that each lookup filtered its own results. My
first version of that test asserted the opposite and failed; the failure was the
finding. It is now pinned as expected behaviour with a comment naming the trap,
because "fixing" it by adding a filter would change which candidates a source may
contribute.

**§5.2, the stale refusal test — CLOSED in `04b8374`.** Arranged canonically, real
command, no snapshot patching. `test_manual_continuation.py` is 15 passed / 0
failed for the first time this session.

**§5.1 — CLOSED.** Round 3 enumerated the function and found no fifth route, and
confirmed `workbench://story/<id>` is safe in every consumer.

### What I got wrong, for the record

I patched `_try_route` in `test_manual_continuation.py` when the helper actually
wrapped `call_role`. Ruff caught it as `F821` before the run. I also wrote an
`if detail and (... or True)` condition that was a no-op pretending to be a
guard, and shipped a line of malformed Bulgarian in the same commit; I caught
both by reading the diff back and rewrote them. Neither reached a commit.

The through-line from all of it: **every one of these was caught by measuring or
reading back, not by reasoning harder up front.**

---

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

## 3. What round 2 must NOT re-litigate

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

## 4. One round-1 verdict was WRONG — do not inherit it

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

### 5.1 CLOSED — verified complete by round 3

Round 3 enumerated every discovery-time value in `promote_story_to_idea` and found
**no fifth route**, and confirmed `workbench://story/<id>` is safe downstream
(`_safe_href` allow-lists http(s) only, so it renders as text, never a link;
`needs_angle_review` returns False for it; `_transcript_trust` correctly falls
through; frontend has zero `source_type` consumers). The label gap I predicted
in `d909a37` was real and is fixed. I accept all of it.

Nothing here is open. The one thing that is, and is deliberately not code:

- **Stored damage, operator decision.** Measured again by round 3: 3 rows in
  `var/editorial_workflow/live_evidence.jsonl` carry a news.google.com wrapper
  `source_url` (1 fact each), and `ideas.jsonl` has 61 rows with no `workbench://`
  and only pre-fix `source_type` values. Zero hits in `cases.jsonl` /
  `live_drafts.jsonl`, so nothing consumed them. Per rule 9 this is annotate,
  quarantine, or leave — and it needs a person, not a diff.

### 5.2 CLOSED — repaired canonically in `04b8374`

Round 3's precondition ("do §5.2 after §5.1 is verified") was what unblocked it.
The test is now arranged through the REAL research store and the REAL inbox, the
way `test_article_draft_command.py:557` arranges the same state, and the real
`start_article_draft` runs. No `_draft_snapshot` patching anywhere.

`test_manual_continuation.py`: **15 passed, 0 failed** — the first clean run of
that file in the session. It is faster too, 0.90s, so it is cheap to re-verify.

Two things worth carrying into round 4 rather than treating as closed:

- **The seam's row count is asserted (`> 0`).** A seam that matched nothing would
  leave the Story readable, §A's waiver would fire, and the test would assert a
  refusal the product deliberately does not make — a green test for a false
  reason. That is the exact failure mode I hit twice. Worth checking whether other
  tests arrange state with an unasserted seam.
- **Round 3 corrected my sequencing note and I accepted it:** the F4 fix did NOT
  move this test's expected value, because F4 lives in `build_packet` (post-gate)
  while this refusal is decided at the readiness gate (pre-gate). I told round 3
  the opposite. The repair was not affected, but the reasoning was wrong.

### 5.2a RESOLVED — but the numbers are worth checking

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

1. **§5.1 — is the snippet fix complete?** This is the one that matters. Enumerate
   every remaining route by which a discovery-time value can reach a fact, a packet
   field, or an editor-visible claim, and say plainly whether the function is clean.
2. **§5.2** — the correct shape of that test, and whether the marker invariant it was
   protecting still holds.
3. Anything violating rules 6, 1 or 3, with the exact line and the exact failure.
4. Whether the store guard should stay as-is or become schedule-aware (§5.3).
5. Everything else, marked confirmed or suspected.

For each finding: file and line, what is wrong, the concrete input or sequence that
makes it fail, and what you ran. If you ran nothing, say that.

One standing request: **if you disagree with something above, say so and show the
measurement.** Round 1's one wrong verdict was worth more than its confirmations,
because it is the only part that changed what I did.

---

## 8. What I got wrong today, so you do not inherit it

Recording these because a prompt that only lists successes teaches the wrong lesson.

1. **My first "fix" for the prose fallback did not work.** I captured the
   "pristine" callables lazily, on the fixture's first use — which happens *after*
   the browser suite has already substituted them, so the capture recorded the
   substitutes as the baseline and the leak survived. The comment I wrote above
   the code described exactly this hazard; I then wrote the hazard. The capture is
   eager now.

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

The through-line: **every one of these was caught by measuring rather than by
reading**, and in case 1 the measurement came *after* I was confident. Confidence is
not evidence, and "I already verified that" is the most expensive sentence in this
repository.
