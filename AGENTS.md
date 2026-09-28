# Working rules for this repository

These exist because of specific, recorded failures in this project. Each rule
names the failure that produced it, so it can be deleted if it is ever wrong
rather than becoming folklore.

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

- `tests/test_model_policy.py` — 2 failures
- `tests/test_workbench_api.py` — 12-13, and the set varies between runs
  (`test_research_that_finds_nothing_persists_an_explicit_gap` is order-dependent)
- `tests/test_quick_draft.py` — 7 failures

Never present a failing count as a regression without a stashed comparison.
Never absorb a failure silently to make a number look better.
