# M2.5 — Chеrnomorie Draft Lab

## Goal

Generate grounded draft articles using:

```text
EvidencePacket
+
StyleProfile
+
3–5 StyleExamples
→ DRAFT
```

No publishing.

## Required input separation

Prompt sections must be clearly separated:

```text
CURRENT EVIDENCE
CURRENT QUOTES
CURRENT UNKNOWN VALUES

STYLE PROFILE
STYLE EXAMPLES

TASK
FORBIDDEN BEHAVIOR
```

## Factual rule

Every factual claim must be supported by EvidencePacket.

Style examples are forbidden as factual sources.

## Unknown handling

If information is absent:
- omit it
- or mark for editor review

Never fill gaps.

## Headline generation

Generate up to 3 candidates, at least one following measured Chеrnomorie headline patterns.

## Draft variants

For initial evaluation:

```text
A = generic grounded news draft
B = Chеrnomorie-style grounded draft
```

Keep evidence identical.

## Archive contamination test

Use style examples containing different names, numbers, places, dates, and quotes. Draft must not import them.

## Claim audit

Classify each claim as:
- SUPPORTED
- STYLE_ONLY
- UNSUPPORTED

Material unsupported factual claim = fail.

## Initial evaluation sample

At least 20 current-story packets across several article types.

Human reviewer scores:
- factual accuracy
- Chеrnomorie resemblance
- headline quality
- lead quality
- editing effort
- publishability after edit

## Verification Gate

PASS only if:
- factual hallucination rate is effectively zero
- style-assisted drafts materially improve style/editing effort
- archive leakage test passes
- prompt frozen during evaluation
- no publishing integration exists

Then STOP.
