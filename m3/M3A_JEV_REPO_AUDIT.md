# Media Project — M3A + Jev Repository Audit

## Snapshot reviewed

Whole-repository snapshot supplied after M3A Editor Workbench implementation and the post-M3A review pass.

This audit is intentionally conservative:
- do not reopen frozen editorial logic;
- distinguish product bugs from test-harness/environment issues;
- introduce Jev only in shadow/evaluation mode first;
- preserve the project's value-first / good-enough rule.

---

# 1. Executive verdict

## M3A

`EDITOR_WORKBENCH_ENGINEERING = PROVEN` remains justified.

Independent checks on the supplied snapshot:

```text
M3A scripted smoke        25/25 PASS
non-search/TinyFish suite 429 PASS
workbench tests           PASS
```

The Workbench is not a fake UI shell. It implements the real editor loop over the existing contracts:

```text
queue
→ case
→ sources/warnings
→ working copy
→ stale-generation protection
→ explicit finalization
→ editor metrics
```

The architecture is sensible for the current local, single-editor stage:
- localhost by default;
- no framework/build-chain dependency;
- canonical AI drafts immutable;
- working copies separate;
- finalization explicit;
- special no-draft states represented;
- no automatic publishing;
- no editorial logic reimplemented in HTML.

Do not redesign M3A now.

---

# 2. Important repository-health finding

The supplied snapshot currently collects **481 tests**, but an independently run full suite is not hermetic in this environment.

Observed:

```text
429 tests PASS when the two search-related test modules are excluded.

8 failures occur inside:
tests/test_search_foundation.py
tests/test_tinyfish_adapters.py
```

The failures are caused by the production SSRF guard calling real:

```python
socket.getaddrinfo(...)
```

even when the HTTP opener is mocked.

In a network-isolated test environment:

```text
example.org
example.com
burgas.bg
a.bg
```

cannot resolve, so the guard correctly fails closed with:

```text
FETCH_BLOCKED_TARGET
```

before the mocked HTTP response is reached.

This is **test-hygiene debt, not a production regression**.

Do not weaken or bypass the production SSRF guard.

Fix the tests so DNS is deterministic and offline.

Recommended pattern:
- explicit fixture/helper that patches the resolver for test-only public hostnames to a known public IP;
- private/localhost target tests remain explicit and still verify rejection;
- no real DNS/network dependency in offline tests.

After the fix the full 481-test baseline should be independently reproducible in a DNS-isolated environment.

---

# 3. M3A quality assessment

## Strong parts

### Canonical vs working state

Good separation:

```text
AI draft / final case      → canonical
editor working copy        → disposable/non-authoritative
workbench action log       → minimal append-only audit
```

The stale-draft contract is especially good:
- working copy records `base_draft_id`;
- newer generation blocks finalization;
- explicit re-base is required;
- editor text is preserved.

### Special-case workflow

The Workbench correctly supports:

```text
DRAFT_READY
RESEARCH_MORE
EDITOR_DECISION_REQUIRED
NO_PUBLISHABLE_ANGLE
```

without forcing every item into an article editor.

This matters because the project is explicitly allowed to decide that there is no story.

### Safety

Good:
- localhost default;
- no publish endpoint;
- no `.env` exposure;
- escaping / URL allow-listing;
- canonical drafts immutable;
- finalized items immutable on the Workbench surface.

### UI implementation choice

The stdlib server is acceptable for this MVP.

`html.py` and `state.py` are large, but not yet a reason for a framework migration or refactor.

Avoid aesthetic refactoring until product use exposes actual pain.

---

# 4. One cross-cutting persistence cleanup worth doing now

There are currently two implementations for writing `live_evidence.jsonl`:

```text
workflow/cli.py
  _live_rows()
  _save_live_row()

workflow/workbench/state.py
  _live_evidence_rows()
  _live_evidence_save()
```

The Workbench writer is atomic; the CLI writer rewrites the file directly.

This is manageable today, but M3C automatic research enrichment will also need to update live evidence.

Do not allow a third writer.

Before M3C, extract one small shared canonical API, e.g.:

```text
workflow/live_store.py

read_live_evidence(path=...)
save_live_evidence_row(row, path=...)
```

Requirements:
- same schema and output ordering as today;
- atomic same-directory temp + `os.replace`;
- no semantic/editorial logic;
- CLI and Workbench both call it;
- output bytes remain deterministic;
- tests assert identical behavior.

This is a reliability cleanup, not an architecture redesign.

---

# 5. Repository guidance / handoff hygiene

The project now has a long chronological `handoff.md`, `MILESTONE.md`, old root harness prompts and ignored `var/` artifacts.

That history is valuable, but a new harness can easily read an old state and act on it.

Add one compact authoritative file:

```text
CURRENT_STATE.md
```

It should contain only:
- current checkpoint/commit;
- current verdicts;
- frozen boundaries;
- current provider routing;
- current test baseline;
- editor-feedback state;
- next allowed milestone;
- required environment variables;
- authoritative current reports;
- explicit statement that older handoff sections/prompts are historical.

Update `agents.md` read order:

```text
1. CURRENT_STATE.md
2. agents.md
3. relevant current milestone/report
4. handoff.md / MILESTONE.md for history only
```

Do not delete chronological history.

Do not move historical prompt files if that would break links.

---

# 6. Reproducible verification scripts

`tmp/` is explicitly scratch/untracked, but M3A's verification contract references:

```text
tmp/m3a_smoke.py
```

A clean clone may therefore not contain the smoke tool that supposedly proves M3A.

Promote enduring verification tools, not all scratch experiments.

Recommended:

```text
scripts/
  m3a_smoke.py
  evals/
    jev_shadow_eval.py        # added by M3J
```

Update README/RUNBOOK to use the tracked path.

Historical one-off batch scripts can remain in `tmp/`.

Do not promote every old experiment.

---

# 7. Snapshot hygiene

The uploaded snapshot contains:
- `__pycache__/`
- `.pyc`
- `*.egg-info`
- runtime `var/`
- `tmp/`

The `.gitignore` is already appropriate, so this does not imply these are tracked.

No repository redesign is needed.

For future whole-repo review archives, exclude generated caches if convenient. Keep `var/` only when a semantic audit explicitly needs the current runtime artifacts.

---

# 8. Jev — why it fits this project

Jev is a strong conceptual fit because this project already separates:

```text
generation
from
decision / verification
from
deterministic enforcement
```

The right shape is:

```text
LLM
→ propose / extract / write

Jev
→ narrow typed semantic judgments

deterministic code
→ policy and safety enforcement

editor
→ final authority
```

Do not use Jev as a replacement for the article-writing model.

Do not ask Jev to be the editor-in-chief.

---

# 9. Highest-value Jev seams in the current code

## J1 — semantic corroboration — highest priority

Current enrichment can find:

```text
fact
→ search
→ opened official page
→ lexical candidate match
```

but the audit already proved:

```text
candidate locator != corroboration
```

Examples include names/budget terms matching an official page without that page proving the exact fact.

Jev-shaped task:

```text
STATE:
claim
source passage
source type / authority
claimed procedural stage

QUESTIONS:
support_relation:
  EXACT_SUPPORT
  PARTIAL_SUPPORT
  NOT_ADDRESSED
  CONTRADICTED

event_relation:
  SAME_EVENT
  RELATED_BACKGROUND
  DIFFERENT_EVENT
  UNCLEAR

procedural_relation:
  SAME_STAGE
  DIFFERENT_STAGE
  NOT_STATED
```

This is probably the best first production candidate if evaluation succeeds.

---

## J2 — transcript fact entailment

Current code:

```text
verify_fact_entailment()
→ deterministic lexical/numeric/actor/negation checks
→ borderline cases optionally use judge_fact_with_model()
```

Jev can shadow the expensive model judge.

State:
- extracted fact;
- exact supporting transcript segments.

Questions can independently test:
- overall support relation;
- actor attribution;
- numbers;
- negation;
- decision/procedural status.

Important:
Jev must not repair unsupported facts.
It may only judge.

---

## J3 — angle semantic signals

Do NOT ask:

```text
"Is this publishable?"
```

as the primary Jev integration.

Instead ask narrower questions:

```text
development_type:
  CONCRETE_ACTION
  ROUTINE_PROCESS
  STATIC_BACKGROUND
  UNCLEAR

evidence_completeness:
  SUFFICIENT
  NEEDS_MORE
  INSUFFICIENT

procedural_scope:
  SUPPORTED
  OVERSTATED
  UNCLEAR

affected_party_present:
  YES / NO

current_change_present:
  YES / NO
```

Then compare those decisions against the already identified boundary:

```text
CONCRETE_ACTION_NEEDS_RESEARCH
vs
ROUTINE_REPORT_VETO
```

Do not alter the production rubric until editor feedback supports the pattern.

---

# 10. Lower-priority future Jev uses

Potential later uses:
- same-story vs new-development duplicate relation;
- search-result relevance;
- source-passage relevance;
- current vs historical relation;
- proposal vs discussion vs final decision;
- queue routing.

Do not implement these in the first Jev milestone.

---

# 11. Jev should NOT be used for

Do not use Jev for:
- article drafting;
- headline generation;
- hooks;
- research-query generation;
- transcript summarization;
- open-ended fact extraction;
- final editorial decision;
- automatic publication.

---

# 12. Jev integration strategy

Create a separate milestone:

```text
M3J — Jev Shadow Evaluation
```

No production authority.

Use the official Python SDK as an optional dependency:

```toml
[project.optional-dependencies]
jev = ["typesafe-sdk>=0.6,<0.7"]
```

Environment:

```text
TYPESAFE_API_KEY=
JEV_MODEL=jev-latest
```

If missing:
- offline tests remain green;
- live Jev evaluation reports capability unavailable;
- no runtime behavior changes.

Record the effective model/version returned by the API in artifacts because `jev-latest` may move.

---

# 13. Preserve evaluation data outside ignored `var/`

A major reproducibility issue for any Jev experiment is that the valuable current shadow/enrichment artifacts live under ignored `var/`.

Before modifying semantic code, freeze a small tracked evaluation pack derived from the existing public-source artifacts.

Recommended:

```text
fixtures/evals/jev/
  transcript_angles_v2.jsonl
  transcript_fact_grounding_v2.jsonl
  corroboration_candidates_v2.jsonl
  README.md
```

### `transcript_angles_v2.jsonl`

Include all 24 V2 candidates:
- candidate;
- supporting facts;
- deterministic assessment;
- prior LLM-shadow decision;
- manual audit label where available;
- no mutable runtime paths.

### `transcript_fact_grounding_v2.jsonl`

Include:
- grounded fact candidates;
- dropped fact candidates;
- exact support segment text;
- current deterministic result.

Treat the current gate as a comparison baseline, not perfect truth.

### `corroboration_candidates_v2.jsonl`

Include:
- transcript fact;
- opened source excerpt;
- source authority;
- lexical candidate result;
- manual semantic label where the focused audit established one.

Do not copy API keys, unpublished content or editor-private data.

---

# 14. Jev evaluation design

Run three shadow experiments.

## Experiment A — corroboration

Primary experiment.

Compare:

```text
lexical candidate matcher
vs
Jev typed relation
vs
manual-audit subset
```

Key metrics:
- false-positive reduction;
- exact/partial/not-addressed separation;
- procedural-stage errors;
- confidence distribution;
- latency;
- cost.

## Experiment B — transcript grounding

Compare:

```text
deterministic gate
LLM borderline judge
Jev
```

Do not use simple agreement as truth.

Manually inspect disagreements involving:
- names;
- numbers;
- negation;
- committee/council status.

## Experiment C — angle semantics

Run on all 24 candidates.

Jev should answer narrow semantic questions, not output the production editorial status.

Compare its signals to:
- deterministic assessor;
- previous LLM shadow;
- the 7 manually audited disagreements;
- eventual editor feedback when available.

---

# 15. Confidence handling

Do not set production confidence thresholds yet.

Store:
- selected typed answer;
- full probabilities;
- provider/model;
- latency;
- error/capability status.

After enough labeled editor data exists, thresholds can be calibrated.

`type-safe` does not mean `always correct`.

---

# 16. Jev privacy scope for first milestone

Use only:
- public YouTube transcript excerpts;
- public municipal documents;
- public news/source passages;
- already-public factual data.

Do not send:
- unpublished drafts;
- editor notes;
- confidential source material;
- private files.

Jev does not need those to prove value here.

---

# 17. Recommended immediate order

```text
Phase 0 — repository stabilization
  1. hermetic DNS tests
  2. shared live-evidence store
  3. CURRENT_STATE.md
  4. promote M3A smoke script

Phase 1 — M3J shadow infrastructure
  5. optional TypeSafe SDK
  6. thin Jev adapter
  7. freeze tracked eval fixtures
  8. offline adapter tests

Phase 2 — Jev live shadow evaluation
  9. corroboration
  10. transcript grounding
  11. angle semantic signals
  12. report
  13. STOP
```

Do not start M3B/M3C in the same milestone.

---

# Final recommendation

M3A is good enough and should be frozen after the small reliability/documentation cleanup.

Jev is worth testing.

The strongest first fit is **semantic corroboration**, followed by transcript fact entailment. The angle classifier is useful as a shadow signal, but should not replace the current editorial gate before editor feedback.

The project does not need a Jev-driven architecture rewrite.

It needs a small, reproducible Jev evaluation layer around semantic decisions the project already knows are difficult.
