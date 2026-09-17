# M2.2 — Multi-Style Discovery & Profiles

## Goal

Discover the real writing-style structure inside the Chеrnomorie archive and create a small set of usable style profiles for later draft generation.

Do **not** assume one universal "Chеrnomorie style".

The archive contains:

- house/editorial material;
- recurring named authors;
- paid/freelance contributors;
- category-specific writing;
- different story formats.

Some writers are expected to have genuinely different voices.

Pipeline:

```text
150-article corpus
→ transparent style features
→ author/category/story comparison
→ candidate style families
→ practical StyleProfiles
→ human/editor review
→ freeze approved profiles
```

## Product question

Answer:

> Which distinct writing styles are useful enough that an editor would intentionally choose between them when asking for a draft?

Do not optimize for a statistically perfect clustering solution.

---

## 1. Three-layer model

Analyze:

```text
SITE DNA
    +
STYLE PROFILE
    +
STORY TYPE / CONTEXT
```

### SITE DNA
Only conventions genuinely shared across the publication, e.g. date/number conventions, institutional naming, local specificity, quotation conventions, headline directness, degree of promotional language.

### STYLE PROFILE
A reusable voice/pattern, possibly associated with a house voice, recurring author, or editorial form.

### STORY TYPE
Short news, event preview, culture report, reportage/feature, sports result, etc.

Do not predefine the final taxonomy. Let the corpus show whether variation is mainly author-driven, category-driven, story-type-driven, or mixed.

---

## 2. Important editorial context

Some writers are paid per article and may intentionally have very different styles.

Therefore:

- variation is expected;
- variation is not automatically noise;
- do not force all writers into one house average;
- support several style profiles where evidence and editorial usefulness justify them.

---

## 3. Input / scope lock

Use the existing M2.1 corpus as-is.

Do not reopen corpus ingestion for rare edge cases unless a defect materially biases >5% of a candidate style group or undermines a conclusion.

Do not touch frozen Radar.

---

## 4. Phase A — Corpus profile

Produce basic descriptive coverage:

```text
articles by author
articles by time band
articles by primary category
multi-category memberships
body-length distribution
paragraph-count distribution
headline-length distribution
missing-author records
```

No stylistic conclusions yet.

---

## 5. Author eligibility

Do not create a profile for every author.

Starting guideline:

```text
>=20 articles → eligible for dedicated author profile
10–19        → provisional author signal
<10          → insufficient for dedicated profile
```

Adjust only if corpus evidence strongly supports a better threshold.

---

## 6. Deterministic style features first

Keep features transparent and cheap.

### Headline
- character/word count;
- punctuation patterns;
- colon/dash/question/exclamation usage;
- number presence;
- quotation marks;
- simple location-name signal where practical;
- simple verb-led heuristic where practical;
- headline ↔ first-paragraph overlap.

### Body
- character count;
- paragraph count;
- median paragraph length;
- average sentence length;
- first/last paragraph length;
- paragraph-length variability;
- quote-mark density;
- number/date density.

### Opening
Estimate simple classes such as:
- immediate fact;
- person/institution first;
- place first;
- event/date first;
- scene-setting/descriptive;
- headline repeated in opening.

Do not build a complex Bulgarian NLP stack just to perfect this classification.

### Tone/lexical proxies
Use light signals only:
- first-person use;
- question/exclamation use;
- adjective-density proxy if cheap;
- sentence length;
- numbers/dates density;
- local proper-name density proxy.

These are signals, not style truth.

---

## 7. Phase B — Compare meaningful groups

Compare:

```text
house-signed material
eligible named authors
major categories
recent vs older periods
```

Answer:

1. What appears site-wide?
2. What differs strongly by author?
3. What differs mainly by category/story type?
4. What is likely sample-size noise?
5. Which differences are large/useful enough to become selectable styles?

### Critical rule
Do NOT define house style as `average(all authors)`.

House profile should come primarily from house/editorial material.

---

## 8. Historical drift

Check broad recent-vs-old drift.

Do not create annual styles.

If recent house style differs materially from old archive style, future drafting should normally prefer recent practice.

Do not let historical archaeology dominate this milestone.

---

## 9. Phase C — Candidate style taxonomy

Propose a **small** set:

```text
target: 3–6 useful profiles
```

Examples only:

```text
CHERNOMORIE_SITE_DNA
HOUSE_NEWS
DESISLAVA
CULTURE_FEATURE
SHORT_NEWS
EVENT_PREVIEW
```

The actual result may be smaller or structured differently.

A profile must be:
- supported by enough examples;
- measurably distinguishable;
- editorially meaningful;
- likely to be intentionally selected later.

Avoid profile explosion such as author × category × year × type.

---

## 10. Phase D — Qualitative synthesis

After deterministic metrics exist, an LLM may inspect selected samples to describe things metrics handle poorly:

- opening habits;
- rhythm;
- narrative distance;
- scene-setting;
- quote integration;
- transition style;
- headline feel;
- ending patterns.

Give the LLM metrics + labeled examples and tell it not to invent unsupported traits.

---

## 11. StyleProfile contract

Use a practical structure suitable for later prompting:

```yaml
profile_id:
display_name:
scope:
status: PROVEN | PROVISIONAL
sample_size:
source_authors:
source_categories:
preferred_use:
site_dna_inherited:

headline:
  typical_length:
  common_patterns:
  avoid:

opening:
  typical_patterns:

body:
  paragraph_shape:
  sentence_shape:
  pacing:
  structure:

quotes:
  frequency:
  placement:
  integration:

tone:
  factual_vs_descriptive:
  narrative_distance:
  local_specificity:

numbers_dates:
  conventions:

lexical_notes:
  recurring_preferences:

avoidances:
  - ...

example_article_ids:
  - ...

evidence_notes:
  - ...
```

No fake numeric confidence scores.

---

## 12. Site DNA

Create a separate:

```text
CHERNOMORIE_SITE_DNA
```

containing only genuinely shared editorial conventions.

Do not put author-specific traits into Site DNA.

Future drafting should conceptually use:

```text
SITE DNA
+
SELECTED STYLE PROFILE
+
CURRENT STORY TYPE
```

---

## 13. Retrieval/fallback recommendation

Do not build a full retrieval engine yet, but recommend a future hierarchy:

```text
requested author/style profile
↓
relevant category/story profile
↓
house profile
```

Do not mix unrelated authors merely to fill context.

---

## 14. Human/editor review artifact

For every candidate profile provide:

```text
profile summary
key metrics
5 representative articles
2 contrasting articles
why it is distinct
what must NOT be treated as a hard rule
```

Ask the editor:

```text
Does this style feel real?
Would I intentionally request this style?
Is it meaningfully different from House?
Is any rule overstated?
Should this profile be merged with another?
```

Do not re-review all 150 extraction records.

Human effort should now evaluate **style usefulness**, not ingestion perfection.

---

## 15. Good Enough acceptance criterion

M2.2 does NOT require:

- perfect clustering;
- perfect POS tagging;
- a profile for every author;
- every story type classified;
- embeddings;
- vector DB;
- fine-tuning;
- exhaustive historical analysis.

It is GOOD ENOUGH when the editor can look at the result and say:

> Yes — these are distinct, useful writing modes I would actually choose between.

That is the primary product gate.

---

## 16. Blockers

Block only if:

- house vs named-author material cannot be separated;
- sample sizes are too small for any useful profiles;
- corpus corruption materially biases a candidate profile;
- deterministic analysis is non-reproducible.

Rare outliers go to backlog.

---

## 17. Optional tiny style smoke test

If abstract profiles are hard to judge, one tiny non-production demonstration is allowed:

```text
same small factual paragraph
→ render in 2–3 candidate styles
```

Only to test whether profiles are meaningfully distinguishable.

Do not turn this into the full drafting milestone.

---

## 18. Expected artifacts

Suggested:

```text
var/style_analysis/
    corpus_profile.json
    feature_matrix.jsonl
    author_summary.json
    category_summary.json
    candidate_profiles.json
    site_dna.json
    review.md
```

Commit analysis code, tests, schemas, and compact review/report artifacts as appropriate.

---

## 19. Tests

Only high-value tests:

1. deterministic feature extraction;
2. grouping by author;
3. grouping by category;
4. house material remains separate from named authors;
5. low-sample authors are not promoted to proven profiles;
6. profile serialization;
7. same corpus snapshot → same deterministic metrics;
8. no dependency on Radar runtime state.

Avoid dozens of micro-tests.

---

## 20. Result report

Return:

```markdown
# M2.2 Report — Multi-Style Discovery

## Corpus used
## Corpus snapshot/hash
## Corpus composition

## Site-wide findings
## House-style findings
## Named-author findings
## Category/story-type findings
## Historical-drift findings

## Candidate style taxonomy

### Profile 1
...
### Profile 2
...

## Profiles rejected/merged
## Why

## Human review artifact
## Editor-relevant questions

## Tests
## Reproducibility
## Known limitations
## Backlog items

## Verdict
PASS — GOOD ENOUGH
PASS WITH NOTES
FAIL

## Recommended next step
```

---

## 21. STOP gate

If profiles are editorially useful:

```text
M2.2 — MULTI-STYLE DISCOVERY DONE
```

Freeze:
- Site DNA;
- approved StyleProfiles;
- profile version;
- corpus snapshot reference.

Then STOP.

Do not automatically begin M2.3.

### Expected next milestone after approval

Prefer a larger product-facing experiment:

```text
M2.3 — First Grounded Multi-Style Draft Experiment
```

Concept:

```text
10 real source/evidence packets
+
selected StyleProfile
+
3 relevant same-profile archive examples
→ drafts
→ editor comparison
```

The purpose is to learn whether profiles actually reduce editorial effort.
