# Harness Instructions — M3A Stabilization + M3J Jev Shadow Evaluation

## Mission

Start from the current repository after M3A Editor Workbench and M2S-R4.

Perform two bounded tasks:

```text
PART A — stabilize repository/test/handoff hygiene
PART B — add Jev as a SHADOW semantic-decision evaluator
```

Then STOP.

Do not continue into M3B YouTube intake or M3C automatic research enrichment.

Do not change production editorial behavior.

---

# Frozen state

Treat these as frozen unless a regression is required to preserve existing behavior:

```text
EDITOR_WORKBENCH_ENGINEERING        = PROVEN
SEARCH_EXECUTION_ENGINEERING        = PROVEN
TINYFISH_SEARCH                     = ADOPTED
TINYFISH_FETCH                      = AVAILABLE / NOT_YET_PROVEN
TRANSCRIPT_DISCOVERY_ENGINEERING    = PROMISING+
TRANSCRIPT_RESEARCH_ENRICHMENT      = PROMISING
EDITORIAL_EFFECTIVENESS             = PENDING
```

Do NOT change:
- SITE DNA;
- VOICE/MODE profiles;
- newsworthiness thresholds;
- readiness thresholds;
- hook guidance;
- factual gate semantics;
- provider routing;
- transcript discovery semantics;
- deterministic-vs-model authority;
- current editor-pilot results.

No drafting.
No publishing.
No LIVE 6–10.

---

# PART A — Repository stabilization

## A1. Reproduce the current baseline first

Run:

```bash
PYTHONPATH=src pytest -q
```

The supplied snapshot currently collects 481 tests.

A DNS-isolated environment may reproduce approximately 8 failures in:

```text
tests/test_search_foundation.py
tests/test_tinyfish_adapters.py
```

because mocked HTTP tests still let `web_fetch.guard_target()` call real
`socket.getaddrinfo()`.

This is test-hygiene debt.

Do not weaken the SSRF guard.

---

## A2. Make search/fetch tests hermetic

Fix only the tests/test seams necessary to guarantee:

```text
offline test run
→ no real DNS
→ no real HTTP
```

Recommended:
- create an explicit test resolver fixture/helper;
- map public fixture hostnames to a known public IP;
- preserve explicit private/localhost rejection tests;
- tests for unresolvable hosts should use an explicit fake resolver/error;
- do not globally disable `guard_target`.

The production security behavior must remain unchanged.

Acceptance:

```text
full suite passes with network/DNS unavailable
```

---

## A3. One canonical live-evidence store

Before future M3C work, eliminate the duplicate persistence implementations:

```text
workflow/cli.py::_live_rows / _save_live_row
workflow/workbench/state.py::_live_evidence_rows / _live_evidence_save
```

Extract a small shared persistence module or public helper, for example:

```text
workflow/live_store.py
```

with:

```text
read_live_evidence(path)
save_live_evidence_row(row, path)
```

Requirements:
- exact same JSON schema;
- deterministic row ordering;
- atomic same-directory temp + `os.replace`;
- no editorial logic;
- caller-selectable path for tests;
- CLI and Workbench use the same implementation;
- preserve current output semantics.

Do not create a generic database/repository abstraction.

This is one file-store seam only.

Add regression tests:
- update existing row;
- add new row;
- failed serialization does not truncate store;
- CLI and Workbench use the shared writer;
- deterministic bytes/order.

---

## A4. Add `CURRENT_STATE.md`

Create a concise root-level:

```text
CURRENT_STATE.md
```

This becomes the first state document for future harness runs.

Include:
- current commit;
- current verdicts;
- frozen boundaries;
- active Search routing;
- current test count after A1/A2/A3;
- M3A run command;
- current editor-feedback state;
- allowed next work;
- required optional env vars:
  - TINYFISH_API_KEY
  - TYPESAFE_API_KEY
  - JEV_MODEL
- current authoritative reports.

Clearly state:

```text
handoff.md and MILESTONE.md are chronological history.
Older HARNESS_PROMPT_*.md files are historical, not current instructions.
```

Update `agents.md` read order so a new harness reads:

```text
1. CURRENT_STATE.md
2. agents.md
3. current milestone/report
4. handoff.md / MILESTONE.md only for history
```

Do not delete old reports/prompts.

---

## A5. Promote enduring M3A smoke verification

`tmp/` is scratch/untracked, but the M3A report depends on:

```text
tmp/m3a_smoke.py
```

Promote the enduring smoke verifier to a tracked path:

```text
scripts/m3a_smoke.py
```

Update README/RUNBOOK/M3A report references.

The script must still:
- operate on a copied store;
- never mutate the pending editor pilot;
- verify the real store hash remains unchanged.

Do not promote every old tmp experiment.

---

## A6. Do not refactor M3A for style

Do NOT split/rewrite:
- `workbench/state.py`;
- `workbench/html.py`;
- stdlib HTTP server;

unless required by A3 or a reproduced bug.

Large files alone are not a reason to refactor.

M3A remains frozen after this reliability cleanup.

---

# PART B — M3J Jev Shadow Evaluation

## B1. Purpose

Jev is being evaluated as a narrow semantic-decision model.

It does NOT replace:
- the drafting LLM;
- deterministic policy;
- editor authority.

Architecture:

```text
LLM
→ propose/extract/write

Jev
→ typed semantic judgments

deterministic code
→ enforce

editor
→ decide
```

Jev has **zero production authority** in M3J.

---

## B2. Official SDK as optional dependency

Add:

```toml
[project.optional-dependencies]
jev = ["typesafe-sdk>=0.6,<0.7"]
```

Do not add it to mandatory runtime dependencies.

Environment:

```text
TYPESAFE_API_KEY=
JEV_MODEL=jev-latest
```

Default model alias:
`jev-latest`.

Record the effective returned model/version in evaluation artifacts whenever available.

Missing key/package must produce an explicit:

```text
JEV_CAPABILITY_UNAVAILABLE
```

and leave normal project functionality untouched.

---

## B3. Thin adapter only

Create a small module, preferably:

```text
src/editor_assistant/workflow/jev.py
```

Do not build a generic plugin/model framework.

Responsibilities:
- create client only when configured;
- submit `state + typed questions`;
- normalize answers/probabilities/latency/model metadata;
- map transport/provider failures explicitly;
- never decide editorial status itself.

Offline unit tests mock the SDK client.

---

# PART C — Freeze reproducible evaluation fixtures

Current valuable artifacts live under ignored `var/`.

Before semantic experimentation, create a small tracked evaluation corpus from the existing PUBLIC-source V2 artifacts.

Create:

```text
fixtures/evals/jev/
  README.md
  transcript_angles_v2.jsonl
  transcript_fact_grounding_v2.jsonl
  corroboration_candidates_v2.jsonl
```

No API keys.
No unpublished drafts.
No private editor notes.

---

## C1. `transcript_angles_v2.jsonl`

Freeze all 24 V2 candidate angles with:
- video/source id;
- candidate id;
- title/proposition;
- supporting facts;
- deterministic assessment;
- prior LLM-shadow assessment;
- manual focused-audit conclusion when one exists;
- no mutable `var/` path dependency.

The 7 known disagreements must be identifiable.

Do not encode a new production rule into the fixture.

---

## C2. `transcript_fact_grounding_v2.jsonl`

Freeze transcript fact grounding cases:
- extracted claim;
- exact supporting segment text;
- segment ids/timestamps;
- existing deterministic result;
- existing model-judge result if available;
- risk flags;
- procedural status.

Include both retained and dropped examples.

Treat existing judgments as baselines, not guaranteed ground truth.

---

## C3. `corroboration_candidates_v2.jsonl`

Freeze the R3 enrichment examples:
- claim/fact;
- exact opened public-source excerpt;
- source URL/domain;
- source authority;
- lexical candidate decision;
- manual semantic conclusion where the focused audit already established one.

Important labels should distinguish:

```text
EXACT_SUPPORT
PARTIAL_SUPPORT
NOT_ADDRESSED
CONTRADICTED
```

and when relevant:

```text
SAME_EVENT
RELATED_BACKGROUND
DIFFERENT_EVENT
UNCLEAR
```

Do not infer missing manual labels with another model and then call them ground truth.

Leave unlabeled items explicitly unlabeled.

---

# PART D — Jev experiment 1: semantic corroboration

This is the highest-priority Jev test.

For each corroboration case send state similar to:

```text
claim
source_passage
source_authority
claim_procedural_status
source_context
```

Use typed questions, not an open-ended prompt.

Required decisions:

```text
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
  UNCLEAR
```

Record the full probability distribution, not only the top choice.

Do not alter EvidencePackets or readiness.

Evaluation:
- manual-label accuracy where labels exist;
- lexical false positives corrected;
- cases where Jev is more permissive than lexical/manual audit;
- latency;
- error rate;
- confidence distribution.

---

# PART E — Jev experiment 2: transcript fact entailment

Shadow existing:

```text
verify_fact_entailment()
judge_fact_with_model()
```

For each fact/support pair ask narrow typed questions.

At minimum:

```text
overall_support:
  EXACT_SUPPORT
  PARTIAL_SUPPORT
  NOT_SUPPORTED
  CONTRADICTED

actor_relation:
  SUPPORTED
  WRONG
  NOT_STATED

number_relation:
  SUPPORTED
  CONFLICT
  NOT_APPLICABLE
  NOT_STATED

negation_relation:
  PRESERVED
  REVERSED
  NOT_APPLICABLE
  UNCLEAR

decision_status_relation:
  SUPPORTED
  OVERSTATED
  UNDERSTATED
  NOT_APPLICABLE
  UNCLEAR
```

Jev must never repair or rewrite a fact.

Compare:
- deterministic gate;
- prior LLM judge where present;
- Jev;
- manual review of disagreements.

Do not change `extract_facts()`.

---

# PART F — Jev experiment 3: angle semantic signals

Do NOT ask Jev to be the final editor.

Do not ask only:

```text
is this publishable?
```

Instead ask narrow signals:

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

affected_party:
  PRESENT
  ABSENT
  UNCLEAR

current_change:
  PRESENT
  ABSENT
  UNCLEAR
```

Run over all 24 candidate angles.

Compare against:
- deterministic assessor;
- previous LLM shadow judge;
- 7 focused-audit disagreements;
- manual labels where available.

This is specifically diagnostic for:

```text
CONCRETE_ACTION_NEEDS_RESEARCH
vs
ROUTINE_REPORT_VETO
```

Do not modify the production rubric based on this run.

---

# PART G — No confidence threshold yet

Jev returns probabilities/confidence.

Store them.

Do NOT introduce:

```text
if confidence > 0.8: auto-approve
```

or any other production threshold.

The project does not yet have enough independent human labels to calibrate those thresholds.

`type-safe` means output-schema safety, not factual infallibility.

---

# PART H — Privacy

For M3J send only public-source material:
- public YouTube transcript excerpts;
- public municipal documents;
- public source passages.

Do not send:
- unpublished article drafts;
- editor notes;
- confidential source material;
- private files.

No editor data is required for this evaluation.

---

# PART I — Evaluation runner

Create a tracked runner:

```text
scripts/evals/jev_shadow_eval.py
```

It must:
- load frozen fixtures;
- run one or all three experiments;
- resume safely if interrupted;
- write results under ignored `var/jev_eval/`;
- never mutate fixtures;
- never mutate workflow/runtime case state;
- never draft an article.

Suggested CLI:

```bash
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment corroboration
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment grounding
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment angles
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all
```

Without `TYPESAFE_API_KEY`, live run should report unavailable cleanly.

---

# PART J — Tests

Add offline tests for:

```text
missing SDK/key -> JEV_CAPABILITY_UNAVAILABLE
typed question construction
response normalization
probability preservation
provider failure mapping
no production-state mutation
no unpublished/private data in fixture/eval state
runner resume/idempotence
fixture schema validation
```

Add regression test that Jev cannot become an authority accidentally:
- no call from `assess_readiness`;
- no call from `assess_angles`;
- no call from `extract_facts`;
- no call from `record_editor_final`.

M3J evaluation is invoked only by the eval runner.

---

# PART K — Reports

Create:

```text
m3/review/M3A_STABILIZATION_REPORT.md
m3/review/M3J_JEV_SHADOW_EVALUATION.md
```

Update:

```text
CURRENT_STATE.md
MILESTONE.md
handoff.md
README.md
RUNBOOK.md
agents.md
```

Report separate verdicts:

```text
M3A_STABILIZATION = PROVEN / PROMISING / NOT_PROVEN

JEV_INTEGRATION = READY / NOT_READY
JEV_CORROBORATION = PROMISING / NOT_PROMISING / NOT_EVALUATED
JEV_GROUNDING = PROMISING / NOT_PROMISING / NOT_EVALUATED
JEV_ANGLE_SIGNALS = PROMISING / NOT_PROMISING / NOT_EVALUATED

JEV_PRODUCTION_AUTHORITY = NONE

EDITORIAL_EFFECTIVENESS = PENDING
```

Do not promote Jev to production from one benchmark run.

If no TypeSafe key is available:
- finish all integration/offline work;
- produce `NOT_EVALUATED` effectiveness verdicts;
- STOP honestly.

---

# PART L — Verification

Required before STOP:

```text
PYTHONPATH=src pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
PYTHONPATH=src python3 scripts/m3a_smoke.py
```

The full pytest run must succeed without DNS/network access.

If Jev credentials are available, run the live shadow eval after offline gates.

Record:
- exact test count;
- TypeSafe SDK version;
- Jev model alias/effective version;
- experiment counts;
- latency/cost metadata if returned.

---

# PART M — STOP

After:
- hermetic test fix;
- shared live evidence store;
- CURRENT_STATE;
- tracked M3A smoke;
- Jev adapter;
- frozen eval fixtures;
- offline tests;
- optional live shadow evaluation;
- reports/docs;

STOP.

Do not continue into:
- M3B YouTube URL intake;
- M3C automatic enrichment;
- CMS publishing;
- LIVE 6–10;
- rubric/threshold changes;
- Jev production authority;
- editor-profile learning.

---

# Core rules

> Fix test isolation without weakening runtime security.

> One canonical store writer before adding more workflow automation.

> Historical artifacts are not current instructions.

> Jev judges narrow semantic relations; it does not write the story or make the editor's decision.

> Evaluate before adopting.

> Keep the human editor as final authority.
