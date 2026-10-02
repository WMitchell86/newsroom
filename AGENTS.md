# Working rules for this repository

These exist because of specific, recorded failures in this project. Each rule
names the failure that produced it, so it can be deleted if it is ever wrong
rather than becoming folklore.

> **Note on this file's history (2026-10-02).** A second file, `agents.md`, sat
> beside this one — same name, different case, both tracked, neither a superset
> of the other. On a case-insensitive filesystem they are the same path, and an
> agent reading "agents.md" could get the stale one. It was removed and its
> still-true content merged into the Toolchain and rules 12-13 at the end of
> this file. Its project description and repo map were **four weeks stale** —
> they described this as "a deterministic RSS-monitoring assistant" with no
> mention of model routing, research or the workbench UI, which are most of the
> codebase now. Do not restore it from that description; the map is current.
> A copy is kept at `var/backup_pre_agents_merge_1527/agents_lowercase_old.md`
> (git-ignored), and in this file's git history either way.

## 1. Never report a system state that was not measured

A claim about quota, health, capacity or "nothing is working" must be the
output of a probe run at the time of the claim, and the number must be shown.

Failure that produced this rule: the editor was told "няма капацитет за
генериране, точка" after a single probe returned 503, which means overload for
minutes. Two of the four draft models were serving 200 throughout, and one of
them had been blocked by a local limit invented earlier the same day.

- "I do not know" is a valid answer. It is always better than a confident
  guess.
- A probe result and a conclusion are different sentences. Report both.
- If a claim rests on a file, open the file before making it.

## 2. 429 and 503 are different problems and need opposite responses

- `429 RESOURCE_EXHAUSTED` — the quota is spent. It resets on the provider's
  schedule. Waiting is the only fix; retrying now changes nothing.
- `503 UNAVAILABLE` ("high demand") — the provider is overloaded. It clears in
  minutes. A single 503 says nothing about the next minute.

Treating a 503 as a permanent outage is what made an entire model fleet look
dead for an afternoon.

## 3. Do not invent a limit and then present it as an external fact

`daily_call_limit` and `hard_calls_day` are local guardrails. Their values came
from a stale prose note in the policy file, not from the provider.

Failure that produced this rule: a per-model limit of 20 was set from an old
note, silently blocked a model the provider was serving happily, and the block
was reported to the editor as an exhausted quota. The editor's own provider
dashboard disagreed with the system, and the system was wrong.

A local guardrail must never be reported as a provider limit. If a guardrail is
tightening what the provider allows, that is a bug in the guardrail.

## 4. Check the whole set of documented answers before computing

The routing audit already recorded `wired_in_production` per role. The health
sum in the policy note was computed by hand, omitted two roles, and produced a
phantom over-subscription that triggered a real budget cut.

Failure that produced this rule: a role was cut from 50 to 40 to make a wrong
sum fit inside a quota, when the two roles in the sum were never invoked. The
cut was reverted.

## 5. A frozen contract is a contract

§1 freezes the left rail to five destinations. §3 freezes the Settings landing
to one entry. Tests assert these in the test names, not just in bodies.

When a new feature needs a home, look for one. Do not add a sixth rail item and
do not relax the assertion. Two placements were tried and both were reverted in
a single day; the third respected the contract.

## 6. Do not swallow an exception into a confident sentence

`except Exception: raise DraftRefused("", "Source unavailable")` reported an
unreadable source for every possible failure, including an exhausted quota. The
editor saw a red badge with no cause and spent a day being misdirected.

Failure that produced this rule: a quota exhaustion and an unreadable source
produced byte-identical screens.

- A catch-all may exist, but it must report the real exception type and the
  provider's own reason, not a guess about the cause.
- A classified refusal keeps its own code. Pin it with a test.
- Never let a log line, an API response or a UI badge state a cause the system
  did not actually observe.

## 7. Never verify a claim with the tool that might be the problem

Failure that produced this rule: "the API key is invalid" was produced by a
hand-written probe that loaded `.env` without stripping quotes, so it sent a
41-character key with a literal `"` attached. The key was valid the whole time,
and the editor was told to go and check their provider dashboard for a problem
that did not exist.

- Prove a system is broken using the system's own code path, not a side script.
- If a hand-written probe contradicts the product, suspect the probe.
- Load configuration the same way the process does. `env $(cat .env)` does not
  strip quotes; `set -a; . ./.env` does. `scripts/start_workbench.sh` exists
  because this was a real, repeated failure.

## 8. State counts exactly, and check case

Failure that produced this rule: `status == "ok"` matched nothing because the
stored value is `"OK"`. The result was "zero successful calls in the entire
recorded history" for a system that had 170 successful calls the previous day.

When reporting a count, print the distinct values observed before concluding
anything from them.

## 9. A destructive action gets a backup and a stated scope first

Before deleting state, write it somewhere recoverable and say exactly what will
be removed. The `var/` tree is gitignored and a restart has already destroyed
in-flight work once, silently.

## 10. Record the real cause in the commit message

Not the intended design, and not the summary of the diff — the failure that was
actually observed, and what was verified against what. A commit that says
"raises the limit" when the real story is "the limit was invented from a stale
note and blocked a working model" is how the next reader repeats the error.

## Baseline failures

These fail on unmodified `main` and are not regressions. Verify against a
stashed run before blaming a change:

Measured 2026-10-02 on the real tree, `pytest --ignore=tests/browser`:
**19-20 failed / ~1978 passed** (the count varies with one documented
intermittent). By file:

- `tests/test_workbench_newsroom.py` — 5
- `tests/test_workbench_api.py` — 4 (the set varies between runs;
  `test_research_that_finds_nothing_persists_an_explicit_gap` is order-dependent)
- `tests/test_bulgarian_forms.py` — 3
- `tests/test_newsroom_refresh.py` — 2
  (`test_new_development_reaches_a_followed_story_once_and_aggregates`,
  `test_duplicate_material_creates_no_false_attention`)
- `tests/test_draft_vs_ready_contract.py` — 2
- `tests/test_v12_g2_4b_contract.py`, `tests/test_sources_registry.py`,
  `tests/test_research_ux_contract.py` — 1 each
- `tests/test_draft_readiness_parity.py` — 1, and it is INTERMITTENT: present in
  most full-suite runs and absent in some. A run reporting 19 rather than 20 has
  not lost coverage, so do not "fix" the count by chasing it.

**Newly observed 2026-10-02, unexplained — do not assume it is harmless.**
`tests/test_search_foundation.py::test_429_is_rate_limited_and_bounded` failed in
one full-suite run and in no other, has never failed before, and passes both
alone (30/30 in that file) and alongside the files the suite orders before it.
It therefore needs a polluter from elsewhere in the ordering, which has not been
identified. Nothing I changed that day could plausibly affect it — the edits were
a dead constant and markdown — but "could not plausibly" is not "verified". If it
reappears, capture the full-suite output and find the polluter rather than
re-reading this line and moving on.

**The failure SET drifts between runs even when the count does not.** Comparing
only counts hides this: the run above also lost
`test_draft_readiness_parity.py::test_a_stale_eligible_projection_is_refused_when_material_disappears`
relative to the previous run. Diff the sorted `FAILED` lists, not the totals.

- `tests/browser/` — 6-7, all in `test_d2a_stories` / `test_v11_d1_today` /
  `test_v11_d2_quick_draft` / `test_v12_g2_2_research_ux`. These skip entirely
  in a fresh `git worktree` (no `frontend/node_modules`), so a worktree is NOT
  a valid baseline for them — compare in the real tree.

**This list is measured, not remembered, and it goes stale.** Entries that used
to be here and no longer fail: `tests/test_model_policy.py` (2) and
`tests/test_quick_draft.py` (7) were both clean on 2026-10-01.
`tests/test_openrouter_transport.py` (3) failed only while the G4.28 streaming
rewrite was mid-edit and is clean now — a reminder that a failure list which
only grows is also lying. Re-measure before trusting it; a stale entry hides a
real regression, and a missing one sends you looking for a failure you caused.

Never present a failing count as a regression without a stashed comparison.
Never absorb a failure silently to make a number look better.

## 11. A test that depends on ambient environment is a test that lies

`tests/browser/conftest.py` sets `GEMINI_API_KEY` in `os.environ` and never
clears it, so every later test file inherits it. A routing test written against
that ambient state passed alone and failed after `tests/browser/` — the same
failure looks like a regression in whatever you just changed.

- A test that reasons about routing must set the keys it depends on, or clear
  the ones it does not. Asserting "route X is eligible" with no key is
  meaningless: the router skips a keyless route with `липсва …KEY`, so the
  route under test is excluded along with the ones you meant to exclude.
- Prove order-independence by running the polluting file **and** your file
  together, not your file alone.
- `git worktree add` gives a clean baseline for pure-Python tests only; browser
  tests skip there, so it silently "passes" work that is not being tested.

---

## Toolchain

Merged from the removed `agents.md` on 2026-10-02. Each line was verified still
true against the tree before being carried over.

```bash
PYTHONPATH=src python3 -m pytest -q        # offline suite; never add --browser by habit
ruff check src tests
```

- **`pip install -e .` is blocked on this machine** (PEP 668 externally-managed
  environment). Always run through `PYTHONPATH=src`.
- **No new dependencies. Stdlib only** (`urllib`, `sqlite3`, `html.parser`,
  `argparse`, `json`). This has held since the first milestone and is the reason
  the transport is hand-rolled rather than a client library — which is also why
  bugs like rule 6's swallowed exceptions are ours to fix by hand.
- Tests must never touch the network. Mock the transport.
- Never commit secrets (`.env`, tokens) or runtime state (`var/`, `*.sqlite3`).
  Never put a provider token in a URL, a log line, or an error message.

## 12. One test run at a time, and never re-launch to "check progress"

Failure that produced this rule: a careless background launch had already frozen
this host and required a restart. The offline suite is ~2000 tests and the
browser suite drives real Chrome against a real HTTP server; a single test can
hold a socket open for its whole timeout.

1. **One run at a time.** Before launching: `pgrep -af 'pytest|vitest|chrome'`
   must return nothing. If it does, clean up before starting anything.
2. **Never re-launch to check progress.** A run is either running or finished.
   Read its output file instead of starting it again.
3. **Prefer a bounded, in-foreground run** — `timeout N` with a narrow selection
   (`<file>`, `-k`). Reserve background runs for genuinely long suites (full
   `pytest`, all of `tests/browser/`), then poll the output file from a
   *separate* command.
4. **Never combine `sleep` with launching work.** A sleep that outlives a
   backgrounded run is what turns waiting into re-launching. Poll, read,
   decide — then act once.

## 13. Do not turn a verdict into a cause

Failure that produced this rule: eight `FAILED:TRANSIENT` rows sat in the prompt
log, six of them inside eleven minutes, with no recorded cause — because the
router logged its own *classification* and dropped the exception it classified.
The detail was one line below, being passed to `mark_route`.

- A category (`TRANSIENT`, `RATE_LIMITED`, `EMPTY_OUTPUT`) is what the system
  decided. A cause is what the provider said. Log the second one.
- When you add a failure path, check that the thing you *learned* is written
  somewhere durable — not only that you learned it.
- Rows written before a logging fix do not retroactively gain the missing field.
  Say so rather than implying the history is now explainable.
