# AI Harness Prompt — Transcript Discovery V2 Corrective Pass

## Context

Continue the current Chеrnomorie Editorial AI repository.

Frozen while editor feedback is pending:

```text
SEARCH_EXECUTION_ENGINEERING = PROVEN
EDITORIAL_READINESS_ENGINEERING = PROVEN
EDITORIAL_READINESS_EDITORIAL_EFFECTIVENESS = PENDING
```

Do NOT change:

```text
SITE DNA
VOICE profiles
MODE profiles
editorial-value rubric criteria/threshold
reader-interest / hook rules
search-provider stack
editor feedback interpretation
```

Do NOT start LIVE editorial cases 6–10.

This phase fixes only generic transcript-discovery defects found by semantic audit.

The current 7-transcript batch remains diagnostic V1.

Do not overwrite it without preserving the original artifacts.

---

# 1. Problem statement

The V1 batch is technically grounded but not yet a valid editorial-discovery benchmark.

Audit findings:

```text
A. agenda/topic segmentation under-segments rolling YouTube captions
B. fact extraction has weak semantic ID→source-text binding
C. angle proposer can self-label PUBLISHABLE_ANGLE
D. explicit proposer status bypasses numeric/semantic validation
E. local batch scoring does not actually implement rubric-v2 semantics
F. batch calls angle status "readiness" without invoking readiness.assess_readiness()
G. committee-stage actions can be promoted to council/municipality actions
H. repeated routine agenda items are over-selected
```

Fix these mechanisms generically.

Do not encode any of the seven committee answers into `src/`.

---

# 2. Preserve V1 artifacts

Before rerun, preserve:

```text
var/transcript_analysis/*.json
var/transcript_analysis/MANUAL_AUDIT_SAMPLE.md
m2/review/TRANSCRIPT_DISCOVERY_BATCH_REPORT.md
```

under a clear V1/superseded snapshot or versioned directory.

V2 outputs must be comparable to V1.

---

# 3. Fix topic segmentation BEFORE fact extraction

## Current problem

`normalize_overlap()` can merge continuously overlapping rolling captions into huge spans.

`segment_topics()` then only looks near the beginning of each span for an agenda cue.

Result:

```text
8 agenda items -> 2 topics
6 agenda items -> 1 topic
5 agenda items -> 1 topic
```

Important later topics are never independently fact-extracted.

## Required behavior

Topic boundary recognition must operate before long rolling-caption merging destroys the boundary surface.

Preferred conceptual flow:

```text
raw SRT segments
→ boundary detection / coarse agenda segmentation
→ overlap normalization inside each topic
→ topic text
```

Equivalent implementations are acceptable.

Boundary detection should use generic signals such as:

```text
точка първа / първа точка
точка 1
втора / трета / четвърта ...
следваща точка
преминаваме към ...
последна точка
```

plus optional model-assisted fallback when deterministic cues are absent.

Do not depend on the cue being in the first N characters of a giant merged span.

---

# 4. Segmentation tests must be semantic and generic

Add synthetic fixtures covering:

### Fixture S1 — rolling captions with 6 agenda items

All captions overlap in time as normal auto-captions do.

Expected:

```text
six agenda topics remain distinguishable
```

not one giant topic.

### Fixture S2 — agenda wording varies

Examples:

```text
"Първа точка..."
"Продължаваме по второ..."
"Следва..."
"Последната точка..."
```

Expected: boundaries remain recoverable.

### Fixture S3 — no formal numbering

A meeting changes subject without agenda-number language.

A neutral fallback may use model-assisted segmentation, but all resulting topics remain source-bound.

Do not hardcode any real committee name.

---

# 5. Strong fact-to-source binding

## Current problem

The model receives:

```text
list of segment IDs
+
one unlabeled text blob
```

and can return any valid ID without actually knowing which ID supports which text.

Existence validation is not semantic grounding.

## Required prompt format

Present source units explicitly:

```text
[segment_id=s001 | 00:01:20.000–00:01:24.000]
actual source text

[segment_id=s002 | ...]
actual source text
```

or equivalent labeled blocks.

A fact must reference the exact evidence units that support it.

---

# 6. Add fact entailment verification

After candidate fact extraction:

```text
fact
+ referenced transcript units
→ semantic entailment check
```

Use a strict source-only judge.

Reuse/adapt the existing factual semantic-entailment approach from drafting where practical.

The judge must detect at least:

```text
wrong actor
wrong relationship
wrong decision status
wrong number
negation reversal
unsupported paraphrase
```

If the fact is not entailed by its referenced source:

```text
DROP FACT
```

Do not repair it from model memory.

Persist:

```text
fact_grounding_status
supporting_segment_ids
```

---

# 7. Separate ANGLE PROPOSAL from ANGLE ASSESSMENT

This is mandatory.

## Proposal stage may output

```text
angle_id
title
new_proposition
fact_ids
reason
possible_research_questions
```

It must NOT authoritatively output:

```text
PUBLISHABLE_ANGLE
NO_PUBLISHABLE_ANGLE
veto
rubric scores
```

Remove those fields from the proposal prompt or treat them as non-authoritative discarded hints.

---

# 8. Independent candidate assessment

Add a separate assessment pass.

Input:

```text
candidate angle
+
only its supporting grounded facts
+
current rubric-v2 criteria
```

Output:

```text
scores for all rubric criteria
supporting fact IDs for every positive score
semantic viability
semantic reason
research questions if needed
```

This may be model-assisted, but must be a separate judge call from the proposal call.

Keep the existing rubric vocabulary and threshold frozen.

The assessor must distinguish:

```text
topic sounds important
```

from:

```text
there is a concrete new publishable development
```

Do not let a `PUBLISHABLE_ANGLE` label bypass the rubric merely because the proposer emitted it.

---

# 9. Preserve semantic veto behavior

The independent assessor must be able to conclude:

```text
NO_PUBLISHABLE_ANGLE
```

for routine/procedural material even if:

```text
budget
citizens
money
committee vote
```

sound important.

It must also be able to return:

```text
POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH
```

when a potentially meaningful development lacks required specifics or corroboration.

Examples are semantic classes, not hardcoded entities.

---

# 10. Procedural / institutional scope contract

Add a compact source-grounded procedural status to relevant facts.

Conceptually:

```text
PROPOSED
DISCUSSED
COMMITTEE_SUPPORTED
COMMITTEE_REJECTED
COUNCIL_ADOPTED
ADMINISTRATIVE_ACTION
UNKNOWN
```

Names may differ.

Every decision/action fact should preserve:

```text
actor/body
action
procedural stage
```

For AUTO_CAPTION, keep corroboration requirements.

## Hard relationship rule

Evidence that establishes:

```text
committee supported proposal
```

must not become:

```text
municipality adopted
municipal council decided
```

without separate supporting evidence.

Add a title/proposition relationship validator before angle eligibility.

If an angle strengthens the institutional status beyond evidence:

```text
reject or downgrade to NEEDS_RESEARCH
```

Do not wait until article drafting to catch it.

---

# 11. Batch-level repeated-agenda context

The seven recordings show repeated agenda items moving through multiple committees.

Add a generic batch/session fingerprint for agenda subjects.

Conceptual fields:

```text
topic_fingerprint
seen_in_recordings
repeated_agenda_item
unique_new_fact_ids
```

Do NOT automatically reject repeated items.

Instead distinguish:

```text
same routine agenda item repeated
```

from:

```text
same agenda item + genuinely new committee-specific fact/position/number
```

A repeated procedural vote alone should receive low novelty unless a new reader-relevant element exists.

This must remain generic.

---

# 12. Prefer concrete development over procedural wrapper

Within the same transcript, angle ranking should prefer a concrete supported development such as:

```text
new service/entity
specific funding or infrastructure proposal
specific tax/fee change or non-change
new number/scale
new affected group
material disagreement
unusual consequence
```

over a generic wrapper such as:

```text
committee accepted annual report
committee discussed budget
agenda was approved
```

when the concrete development has stronger editorial value.

Do not hardcode examples from the seven files.

---

# 13. Run the REAL readiness orchestrator

After angle assessment:

```text
selected angle
→ selected-angle evidence packet
→ mode suggestion
→ readiness.assess_readiness()
```

No drafting.

Persist two distinct statuses:

```yaml
angle_assessment_status:
article_readiness_status:
```

Allowed readiness output remains the frozen M2R vocabulary:

```text
DRAFT_READY
RESEARCH_MORE
NO_PUBLISHABLE_ANGLE
EDITOR_DECISION_REQUIRED
```

Do not call `ANGLE_SELECTED` a readiness result.

---

# 14. Search enrichment remains a seam in this pass

Search infrastructure is now PROVEN.

Do not yet automatically execute search for every transcript gap.

For V2 batch:

```text
RESEARCH_MORE
```

should produce concrete research questions and source targets/categories, but stop before enrichment.

We first need to validate that transcript discovery finds the right stories.

Automatic:

```text
transcript → search enrichment → drafting
```

comes only after this V2 semantic audit passes.

---

# 15. Rerun all seven raw SRTs

Use:

```text
var/youtube_transcripts/raw/*.bg-orig.srt
```

No manually preselected facts.

No manually preselected angles.

No drafting.

Create V2 artifacts separately, for example:

```text
var/transcript_analysis_v2/
```

---

# 16. V1 vs V2 comparison report

Create:

```text
m2/review/TRANSCRIPT_DISCOVERY_V2_REPORT.md
```

Include:

```text
topic counts V1 vs V2
agenda-boundary recovery
fact counts
fact-grounding rejects
candidate angle counts

angle status totals
real readiness totals

routine repeated-item flags
procedural-scope violations caught
institutional overclaim rejects
NEEDS_RESEARCH questions

per-recording strongest candidates
per-recording rejected/no-story candidates
```

---

# 17. Required semantic regression inspection

The following are audit probes, NOT expected hardcoded answers.

The report should explicitly inspect whether V2 can surface classes of material that V1 missed:

```text
late agenda items
specific service/infrastructure creation proposals
education enrollment/under-capacity issues
specific new numbers / scale
unusual budget timing/context
culture/event statements requiring verification
```

Do not encode specific committee facts in implementation or tests.

Use these only as manual V1-vs-V2 inspection categories.

---

# 18. Manual audit artifact

For each of the seven recordings show:

```text
committee/title if discoverable
topic
candidate proposition
supporting facts
exact timestamps
procedural status
ASR/corroboration risks
angle assessment
article readiness
research questions
```

Also show at least one rejected/routine candidate where available.

---

# 19. Success criteria

Do NOT require all seven recordings to produce a story.

A healthy result may contain:

```text
DRAFT_READY
RESEARCH_MORE
NO_PUBLISHABLE_ANGLE
EDITOR_DECISION_REQUIRED
```

Success means:

```text
strong topics are not systematically missed
routine procedural items are not systematically promoted
committee actions keep committee scope
facts have real timestamp entailment
NEEDS_RESEARCH questions are concrete
full readiness is actually executed
```

Variation is desirable.

A result such as:

```text
7/7 ANGLE_SELECTED
```

should now be treated as suspicious and inspected, not celebrated automatically.

---

# 20. Tests

Add focused tests for:

```text
rolling-caption agenda segmentation
boundary inside continuously overlapping captions
ID→text fact binding
unsupported fact binding rejected
wrong actor relation rejected
committee-supported != council-adopted
proposal model cannot self-approve semantic status
independent assessor scores all rubric criteria
repeated agenda fingerprint
routine repeated item does not gain novelty merely from another committee vote
full readiness orchestrator invoked after angle selection
angle status != readiness status
```

Keep existing tests green.

Run Ruff.

---

# 21. Documentation truthfulness

Update the report/docs so wording distinguishes:

```text
ID exists
```

from:

```text
fact semantically entailed by referenced segments
```

and:

```text
angle selected
```

from:

```text
article is ready
```

Do not overstate engineering evidence.

---

# 22. Verdict

At completion choose:

```text
TRANSCRIPT_DISCOVERY_ENGINEERING = PROVEN
TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING
TRANSCRIPT_DISCOVERY_ENGINEERING = NOT_PROVEN
```

Use PROVEN only if V2 manual semantic inspection supports it.

`EDITORIAL_EFFECTIVENESS` remains pending the real editor.

Then STOP.

Do not connect automatic search enrichment.
Do not generate transcript articles.
Do not change editorial profiles/rubrics.
Do not start LIVE 6–10.

---

# Core principle

The pipeline must be:

```text
TRANSCRIPT
→ correctly segmented source
→ grounded facts
→ proposed stories
→ independent editorial judgment
→ readiness
```

not:

```text
TRANSCRIPT
→ model invents a plausible article angle
→ same model calls it publishable
```

And:

```text
committee supported X
```

must remain:

```text
committee supported X
```

until independent evidence proves a stronger institutional action.
