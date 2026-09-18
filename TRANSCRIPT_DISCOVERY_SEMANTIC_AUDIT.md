# Semantic Audit — Transcript Discovery M2S Track T

## Scope

Independent audit of the current repository and the seven transcript-analysis artifacts.

Reviewed:

- `src/editor_assistant/workflow/discovery.py`
- `src/editor_assistant/workflow/transcripts.py`
- `src/editor_assistant/workflow/angles.py`
- `src/editor_assistant/workflow/readiness.py`
- `tmp/transcript_batch.py`
- `m2/review/TRANSCRIPT_DISCOVERY_BATCH_REPORT.md`
- `var/transcript_analysis/*.json`
- `var/transcript_analysis/MANUAL_AUDIT_SAMPLE.md`
- all seven cleaned transcript previews and raw Bulgarian SRT files.

The archive supplied for this audit does **not** contain the `tests/` directory, so the reported 355-test gate could not be independently rerun from this ZIP. The semantic findings below are based on the implementation and persisted outputs.

---

# Executive verdict

```text
TRANSCRIPT_PARSING / TIMESTAMP PROVENANCE = GOOD
TRANSCRIPT_DISCOVERY SEMANTICS = NOT YET PROVEN
CURRENT BATCH VERDICT = INVALID AS AN EDITORIAL DISCOVERY BENCHMARK
```

The current batch is valuable because it exposed the next problems, but it should not be used to conclude that the system can yet identify the strongest news from arbitrary committee transcripts.

The principal problems are **generic architecture/logic issues**, not case-specific misses:

1. topic segmentation collapses many agenda items together;
2. fact extraction does not provide a strong source-ID-to-text binding to the model;
3. angle proposal and semantic approval are performed by effectively the same model output;
4. explicit `PUBLISHABLE_ANGLE` bypasses the numeric gate;
5. batch `readiness` is actually only angle-gate status — the real readiness orchestrator is not executed;
6. institutional/procedural scope can be elevated from committee action to municipal/council action;
7. repeated routine agenda items are repeatedly treated as independent publishable news.

These mechanisms explain the observed semantic errors and omissions.

---

# 1. Topic segmentation is materially under-segmenting the meetings

The seven transcripts explicitly describe approximately:

```text
Culture                 5 agenda items
Social                  5
Economy/Investment      5
Healthcare              8
Tourism                 4
Science/Innovation      5
Education               6
```

Total approximately:

```text
38 agenda items
```

The generated artifacts contain only:

```text
Culture                 1 topic
Social                  3
Economy/Investment      4
Healthcare              2
Tourism                 2
Science/Innovation      3
Education               1
```

Total:

```text
16 topics
```

This is not simply harmless grouping. Important later agenda items disappear from fact extraction entirely.

## Root cause

`segment_topics()` operates on the output of:

```python
normalize_overlap(doc)
```

`normalize_overlap()` merges any continuously overlapping auto-caption cues into a single large span.

Rolling YouTube captions overlap almost continuously, so hundreds of SRT cues can collapse into only a few long spans.

Then `segment_topics()` looks for an agenda boundary only near:

```python
span["text"][:120]
```

A `"точка пета"` occurring in the middle of one giant normalized span can never create a topic boundary.

### Concrete regression evidence

The healthcare recording contains 8 agenda items.

The pipeline produced only 2 topics.

As a result the final agenda item around:

```text
00:08:58+
учредяване на диагностично-консултативен център
към детската болница
```

was not extracted as a fact or candidate angle at all.

The education recording lists 6 agenda items but became one topic, causing the extractor to miss substantial later material.

## Required generic fix

Detect agenda/topic boundaries **before destructive long-span merging**, preferably on raw SRT segments or on short normalized caption windows.

Then normalize/deduplicate overlap **inside each topic**.

Alternative implementations are acceptable, but topic boundary recognition must not depend on an agenda cue being in the first 120 characters of a giant rolling-caption span.

---

# 2. The current fact extraction does not strongly bind source text to segment IDs

Current prompt structure in `discovery.py` supplies:

```text
ID-та на сегментите: s001, s002, s003, ...

ТРАНСКРИПТ:
<one concatenated text blob>
```

The model is never shown:

```text
s001 -> exact text
s002 -> exact text
...
```

It therefore cannot reliably know which specific segment IDs support its paraphrased fact.

The deterministic post-check only verifies:

```text
the returned segment ID exists
```

It does **not** verify:

```text
the claimed fact is actually entailed by the text of those referenced segments
```

So the report's phrase:

> segment-id binding re-verified

is technically true only for ID existence, not semantic provenance.

## Required generic fix

Prompt source material as labeled evidence units, for example:

```text
[seg:s001 | 00:08:58.360–00:09:03.079]
...

[seg:s002 | ...]
...
```

Fact output references those exact units.

Then add a strict fact-grounding verification:

```text
fact
+ referenced source segments
→ ENTAILED / NOT_ENTAILED
```

Unsupported fact bindings are dropped, not repaired by model memory.

Reuse the project's existing semantic entailment approach where practical rather than inventing a second weaker grounding standard.

---

# 3. The proposer currently approves its own angles

This is the largest angle-gate defect.

`_ANGLES_PROMPT` asks the proposal model itself to return:

```text
semantic_status:
  PUBLISHABLE_ANGLE
  POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH
```

Those returned values are passed to `angles.assess_angles()`.

But `angles._semantic_viability()` explicitly gives an **explicit semantic_status** precedence over:

```text
NOVELTY_CUE
numeric eligibility
```

except for an explicit veto.

### Actual batch result

Across the seven JSON artifacts:

```text
candidate angles                 21
eligible                         19
numeric_eligible                  0
semantic PUBLISHABLE_ANGLE       19
NEEDS_RESEARCH                    2
vetoed                            0
```

So:

```text
19/19 selected publishable angles
were publishable only because the proposal model labeled them publishable.
```

None cleared the numeric threshold.

This contradicts the intended architecture:

```text
model proposes
→ deterministic/independent gate validates
```

The real behavior is effectively:

```text
model proposes + self-approves
→ gate trusts explicit approval
```

## Required generic fix

The proposal stage must not have authority to set:

```text
PUBLISHABLE_ANGLE
NO_PUBLISHABLE_ANGLE
veto
numeric scores
```

It may propose only:

```text
title
new_proposition
fact_ids
reason
possible research gaps/questions
```

A separate assessment stage must make semantic viability and scoring decisions.

This assessment may be:

- deterministic where possible;
- model-assisted via a separate strict judge call;
- or composed from both;

but it must be logically independent from the proposer.

Do not remove the editor's explicit override capability.

---

# 4. Current local scoring does not meaningfully implement the editorial rubric

`tmp/transcript_batch.py::local_assess()` initializes all rubric criteria to zero.

It then only gives:

```text
concrete_change = 2
```

when simple decision verbs appear.

It may also assign an `unexpected_fact` score for a named person.

It does not meaningfully evaluate:

```text
people_impact
money_infrastructure_services
different_positions
strong_quote
burgas_novelty
unexpected_fact
```

Therefore the scoring surface is not actually evaluating the same editorial-value rubric used by the LIVE workflow.

This explains why:

```text
numeric_eligible = 0 for all 21 angles
```

## Required fix

Do not claim the transcript batch is using rubric-v2 ranking until the candidates are assessed through the actual rubric semantics.

Use a separate candidate-assessment step which:

- sees only the selected fact evidence;
- scores every criterion;
- provides supporting fact IDs for every positive score;
- independently determines semantic viability;
- can return NEEDS_RESEARCH or NO_PUBLISHABLE_ANGLE.

The current rubric itself remains frozen while editor review is pending.

---

# 5. The batch does not run the actual Editorial Readiness orchestrator

`tmp/transcript_batch.py` imports:

```python
readiness
```

but never calls it.

The persisted artifact field:

```json
"readiness": {
  "status": "ANGLE_SELECTED"
}
```

is actually:

```text
angles.assess_angles().status
```

not:

```text
workflow/readiness.py::assess_readiness()
```

Therefore the batch report's phrase:

```text
angles → readiness
```

is inaccurate.

The full readiness layer would distinguish:

```text
DRAFT_READY
RESEARCH_MORE
NO_PUBLISHABLE_ANGLE
EDITOR_DECISION_REQUIRED
```

and evaluate evidence sufficiency after angle selection.

## Required fix

After independent angle assessment:

```text
selected angle
→ selected_angle_packet
→ mode suggestion
→ assess_readiness()
```

No drafting is needed.

Persist angle status and article-readiness status separately:

```yaml
angle_assessment_status:
article_readiness_status:
```

Never call `ANGLE_SELECTED` a readiness verdict.

---

# 6. Procedural actor/status preservation is insufficient

Several generated propositions elevate a committee-stage action into a stronger institutional statement.

Examples:

### Healthcare

Extracted fact:

> „Общинският съвет единодушно подкрепя финансирането...“

The source is a **healthcare committee meeting**, not a plenary council decision.

### Tourism

Angle:

> „Община Бургас прие бюджет 2026...“

The transcript shows the **Tourism Committee voting on the budget proposal**, not final adoption by the municipality/council.

### Healthcare

Angle:

> „Община Бургас прие бюджета си за 2026 г.“

Again, committee support is promoted to final municipal adoption.

This is precisely the kind of relationship/institutional rebinding the factual system was designed to prevent later.

It should be prevented earlier during discovery.

## Required generic guard

Carry procedural status explicitly:

```text
PROPOSED
DISCUSSED
COMMITTEE_SUPPORTED
COMMITTEE_REJECTED
COUNCIL_ADOPTED
ADMINISTRATIVE_ACTION
UNKNOWN
```

or an equivalent compact vocabulary.

Facts and angles must preserve:

```text
actor
body
stage
action
```

A committee vote cannot be normalized into:

```text
municipality adopted
council decided
```

without corroborating evidence for that stronger status.

Add a semantic relationship check on angle title + proposition against supporting facts.

---

# 7. The batch overvalues recurring routine agenda items

The same agenda surfaces recur across committees:

```text
annual budget execution report
mid-year cash execution
municipal-property program
2026 budget proposal
```

The system repeatedly proposes them as independent publishable stories merely because:

```text
a committee voted on them
```

That is not necessarily new reader value.

The clearest regression is the Social Committee recording.

Earlier M2R analysis correctly reached:

```text
NO_PUBLISHABLE_ANGLE
```

because the useful aid topic lacks amount/recipients/outcome and the remaining agenda is routine.

The new autonomous batch instead produces four `PUBLISHABLE_ANGLE` candidates from the same transcript.

This is a semantic regression created by the self-approval issue.

## Required generic improvement

Within a batch/session, detect repeated institutional agenda subjects across committees.

Do not automatically reject them.

Mark:

```text
REPEATED_AGENDA_ITEM
```

or equivalent and require a **committee-specific new fact** for a new story, such as:

```text
new number
new opposition/position
new modification
new consequence
new implementation detail
strong new quote
```

Routine progression through another committee should not itself be treated as strong local novelty.

This is batch-level duplicate/news-value context, not a hardcoded budget rule.

---

# 8. Case-by-case semantic audit

## Social activities — 8h51zs_NUbw

### Current batch
4 angles, all marked publishable.

### Audit
Weak.

The transcript mostly enumerates routine agenda items and cuts off just as the potentially useful financial-aid point begins.

Earlier readiness work correctly classified this material as:

```text
NO_PUBLISHABLE_ANGLE
```

The new result is a regression.

The aid topic is potentially important but needs:

```text
amount
recipients
conditions
decision/outcome
```

Routine budget/property agenda items are not enough merely because they were placed on a committee agenda.

### Better expected behavior
Likely:

```text
aid angle -> NEEDS_RESEARCH
other routine items -> NO_PUBLISHABLE_ANGLE / low priority
```

depending on available official documents.

---

## Healthcare — HB1avBfeiRw

### Current batch
Selected/strong angles include:

- budget approval;
- mayor budget report;
- morgue equipment.

### Audit
Major discovery miss.

The transcript contains a highly specific final agenda item around 00:08:58:

```text
proposal to establish a diagnostic-consultative center
as a subsidiary/related company of the children's hospital
```

This is not extracted at all.

The transcript also contains substantive healthcare-budget context:

- children's hospital development;
- telemedicine;
- innovation;
- mental-health-center renovation;
- preventive programs.

The morgue-equipment angle is legitimate discovery, but the extracted wording incorrectly promotes the committee vote to `Общинският съвет`.

### Better expected behavior
At minimum the diagnostic-center proposal should become a candidate angle, probably `NEEDS_RESEARCH` because auto-caption names/legal structure require verification.

---

## Economy / investment — CIs4AIKuOiw

### Current batch
Finds:

- annual budget report;
- extended-budget / 1/12 situation;
- drop in interest in municipal properties.

### Audit
Mixed; some genuinely useful discovery.

The last two are more interesting than the selected routine annual-report vote.

The raw transcript also contains a stronger reader-interest statement that the 2026 budget is already roughly **two-thirds spent** by the time it is being adopted/discussed. The extractor does not surface this.

This is precisely the kind of concrete, unusual, contextual fact that should outrank routine committee approval.

### Better behavior
Prefer the specific unusual development/context over procedural voting.

---

## Culture — 7k-FZXrcmq8

### Current batch
Only 3 facts:

- mid-year budget report vote;
- 2026 budget vote;
- museum letter forwarded.

### Audit
Weak segmentation/extraction.

The transcript contains a potentially notable cultural statement around 00:05:18–00:05:30 concerning Burgas/Bulgaria and Eurovision / next year's cultural focus.

The ASR is noisy, so this should **not** be published from transcript alone.

But it is exactly the kind of material the discovery layer should surface as:

```text
POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH
```

with a targeted verification question.

Instead it is missed completely while routine budget voting is promoted.

---

## Science / innovation — b13U-N_Vk9c

### Current batch
Finds:

- 92% budget execution / 571m vs 618m;
- 285 municipal-property objects, 111 for housing;
- court/legal-regulation issue.

### Audit
This is the strongest discovery result of the seven.

The property-program numbers are concrete and potentially useful.

The budget-execution discussion is also a plausible angle.

The court/legal angle is high-risk because the transcript is garbled and should remain `NEEDS_RESEARCH` until the exact court decision and legal effect are independently verified.

Overall this recording demonstrates that the architecture can find useful material once segmentation/extraction happen to preserve it.

---

## Education — xvsdi_j7s5c

### Current batch
Only 3 facts:

- number of agenda items;
- annual budget report accepted;
- 2026 budget discussed.

### Audit
Major discovery failure.

The transcript contains several substantially stronger items:

1. additional funding for classes below the minimum student threshold;
2. a stated recurring problem attracting enough students to some professional specialties;
3. local policy to redesign recruitment/specialties;
4. protected specialties;
5. new higher-education/specialty development;
6. statement that the first 30 students in a new specialty are from across Bulgaria;
7. a museum-exhibition funding/status issue.

The system misses virtually all of these because six agenda items collapsed into a single topic and fact extraction returned only three generic facts.

---

## Tourism — YsqD4T0D850

### Current batch
Finds:

- no change in taxes, fees and service prices in the 2026 budget proposal;
- property-management program;
- budget reports.

### Audit
The no-tax-change fact is a good reader-oriented discovery.

However the generated angle says:

> „Община Бургас прие бюджет 2026...“

which overstates a committee vote.

A stronger and safer framing is conceptually:

```text
2026 budget proposal keeps local taxes/fees unchanged
```

with exact procedural status preserved.

---

# 9. Current batch conclusion

The batch proves:

```text
raw SRT parsing works
timestamp provenance works
model can extract some relevant facts
model can formulate plausible-looking angles
```

It does **not** yet prove:

```text
the system reliably identifies the strongest story
the system reliably rejects routine material
the system preserves procedural scope in angles
the system has run the full readiness layer
```

Therefore retain:

```text
TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING
```

but do not promote it to PROVEN.

The artifacts should be considered a diagnostic batch, not an editorial benchmark baseline.

---

# 10. Recommended next step

Do one narrow **Transcript Discovery V2 corrective pass**.

Fix only:

```text
topic boundary preservation
fact-to-source semantic binding
independent angle assessment
procedural status preservation
batch-level repeated-agenda context
actual readiness invocation
```

Then rerun the same seven raw SRT files **read-only/no drafting**.

Compare V1 vs V2:

```text
topic coverage
facts
missed strong developments
routine false-positive angles
institutional overclaims
NEEDS_RESEARCH quality
full readiness states
```

Only after that should transcript discovery be connected to automatic search enrichment.
