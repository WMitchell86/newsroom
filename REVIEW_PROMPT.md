# Code review prompt — round 2

Copy everything below into a fresh agent with the repository at `/home/test/media`.
Give it read access to the working tree. Do **not** give it round 1's report; tell
it only what is true of the code now.

Round 1 produced one critical finding, one wrong verdict, and one thing neither of
us closed. This prompt reflects all three, so round 2 spends its effort where it is
still unspent.

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

### 5.1 Is the critical fix COMPLETE? (highest priority)

Round 1 proved the snippet reached the packet through `promote_story_to_idea`. It
named one route. I have **not** established that it was the only route.

- Are there other writers of `body`, `summary`, `what_changed`, or a packet field
  that a discovery-time value can reach? `workbench/http.py:798` calls the bridge
  **without** `full_text`, so that live route now always takes the refusal path —
  confirm nothing else feeds it.
- Does the legacy «Кандидатвай като идея» button (`workbench/html.py:1694-1703`) now
  render a button that can only fail? If the story can never be promoted, the button
  is a lie told by omission. Gate it, or say why not.
- `source_type` is still `upstream_press_release` for anything that is not a
  transcript. Now that only opened pages reach here, is that label right, or is it
  the last surviving false claim from the same function?
- Are there Stories **already promoted** on a running instance whose packet facts are
  snippets? That is stored damage, not a code fix, and it needs a decision.

### 5.2 Open item 7 — the stale test, diagnosed but deliberately not fixed

`tests/test_manual_continuation.py::test_a_fact_without_an_opened_source_never_records_a_failure_marker`
fails on unmodified `main`. Round 1's diagnosis, which I read and agree with:

1. **Flag disagreement.** The test patches `app._draft_snapshot`, but the
   synchronous preflight (`editor_application.py:1762`) calls `_draft_readiness_basis`
   (`:1717`), which computes `readable_publication` from the canonical inbox. The
   fixture's URL is readable, so readiness returns `DRAFT_FROM_UNREAD_SOURCE`, which
   preflight **deliberately waives** per V1.2-G4.3 §A. No raise.
2. **The test predates the async split.** Since V1.2-G4.4 `start_article_draft` is
   transport-only: it returns a token and runs the worker in a daemon thread
   (`story_operations.py:129`). The `NO_DRAFT_MATERIAL` refusal now happens inside
   the worker as an operation-failure row, so `pytest.raises` around
   `start_article_draft` can only ever catch preflight refusals.

So the test is stale twice over. The honest repair is to arrange the sourceless basis
canonically (as `_degrade_to` does, not by patching `_draft_snapshot`) and assert on
the **operation row's** code rather than a synchronous raise.

I attempted the narrower fix twice and reverted both times, because fixing the flag
leaves the async assumption wrong and the result is a test that passes for the wrong
reason. **This is the clearest place to start, and it is deliberately untouched
rather than half-done.**

Worth deciding: does the production behaviour the test feared — a durable failure
marker written on a material refusal — still not occur? Round 1 says
`NO_DRAFT_MATERIAL` is in the non-qualifying allow-list. Confirm or refute it.

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
  possible — but neither reads `page["prose"]`. Is the verdict earning its keep?

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
