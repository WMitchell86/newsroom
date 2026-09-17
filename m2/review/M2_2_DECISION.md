# M2.2 Editor Decision Record (binding for freeze)

Date: 2026-09-14. Reviewer verdict: **M2.2 PASS - GOOD ENOUGH**. No further mining, no corpus growth before real drafts.

## Architecture decision

```text
CHERNOMORIE SITE DNA
        +
VOICE / AUTHOR STYLE
        +
STORY MODE
```

Flat five-as-equals (HOUSE_NEWS / HOUSE_BRIEF / CULTURE_FEATURE / EVENT_PREVIEW / DESISLAVA_REPORTAGE) is SUPERSEDED.
Future authors compose (AUTHOR_X + MODE) instead of multiplying AUTHOR_X_NEWS / AUTHOR_X_BRIEF / ...

## Per-candidate rulings

| Candidate | Ruling | Frozen as |
|---|---|---|
| HOUSE_NEWS | KEEP | VOICE_HOUSE + MODE_STANDARD_NEWS |
| HOUSE_BRIEF | KEEP as mode | MODE_BRIEF (voice-neutral; default VOICE_HOUSE) |
| CULTURE_FEATURE | KEEP | MODE_CULTURE_FEATURE (not merged with EVENT_PREVIEW: announcement vs report are different tasks) |
| EVENT_PREVIEW | KEEP | MODE_EVENT_PREVIEW |
| DESISLAVA_REPORTAGE | KEEP PROVISIONAL | VOICE_DESISLAVA_RECENT, scope 2024-2026, n=12; reportage traits stay inside this provisional voice |

## Desislava scope lock

Freeze DESISLAVA_RECENT = 2024-2026, PROVISIONAL, n=12. Sufficient for the M2.3 experiment, not a claim of a final learned voice.
Legacy 2009-2014 pattern (headline repetition 64%, headline quoting 24%) is CMS-era drift, excluded. M2.3 decides real usefulness.

## Style-language rule (anti-caricature)

Profiles use often / typically / prefer / common-pattern / avoid-unless-source-supports. Hard-rule phrasings
(celebratory adjectives ONLY here; never compress; P1 must use press-center attribution; requires multi-speaker quotes)
are recorded as observed tendencies, not mechanical grammar. Frozen profiles were softened accordingly and gated by test_soft_style_language_no_hard_rules.

## Frozen verdict

```text
M2.2 - PASS - GOOD ENOUGH
KEEP: SITE DNA
VOICE: HOUSE (PROVEN) + DESISLAVA_RECENT (PROVISIONAL)
MODES: STANDARD_NEWS + BRIEF + EVENT_PREVIEW + CULTURE_FEATURE
```

Unknown authors and Sport/Education micro-patterns stay backlog.

## M2.3 direction (editor)

Next: bold M2.3 Grounded Multi-Style Draft Experiment in one cycle: evidence packet + style composition + example
retrieval + draft + blind editor comparison. Controlled combos (A: HOUSE+STANDARD, B: HOUSE+BRIEF, C: HOUSE+EVENT_PREVIEW,
D: HOUSE+CULTURE_FEATURE, E: DESISLAVA_RECENT+STANDARD/long). Key test: same facts -> HOUSE vs DESISLAVA blind;
if the editor can tell who is who without labels, the profile system works; otherwise fix profile/prompt, not statistics.
