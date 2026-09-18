# Focused Audit — Transcript V2 Shadow Disagreements + Enrichment Candidates (2026-09-18)

Scope: read-only audit of checkpoint 55b4f5f, focused on (a) the 7 disagreements
among the 24 Transcript V2 candidate angles, (b) the 7 machine-generated
corroboration candidates from the two RESEARCH_MORE recordings, (c) whether any
disagreement reveals a systemic semantic blind spot worth fixing before editor
feedback. No code, thresholds, profiles, prompts, or runtime states were changed.

## Executive conclusion

There is no evidence for a broad rubric redesign. The 7 disagreements split into
three useful classes:

- A. Deterministic gate too strict on a concrete but incomplete development.
- B. Model judge too permissive on an administrative fact with no demonstrated novelty.
- C. Routine-report candidate should have been vetoed earlier.

The most important finding is not a numeric threshold issue. It is a semantic
distinction:

> A concrete proposal/refusal/action can justify NEEDS_RESEARCH even when its
> parameters are incomplete — while the existence/presentation of a routine
> report does not become a research-worthy news angle merely because it
> concerns money, a mayor, or a formal meeting.

This distinction should be considered only after editor feedback or in a
narrowly scoped regression pass. There is not enough evidence to retune the
global scoring system now. The enrichment pass also behaved safely: the
recorded "7 corroboration candidates" are mostly lexical source leads, not
seven publication-grade confirmations; the readiness layer was correct not to
promote either case.

## 1. Shadow disagreement audit (7 items)

### 1.1 concessions_funding — Deterministic NO_PUBLISHABLE_ANGLE / Model PUBLISHABLE_ANGLE

Evidence establishes only that Appendix 12 contains information on concessions
and funds received from the Ministry of Energy, and that a value of 50% appears
in the table/distribution description. The proposed angle upgrades this into
"the Ministry transfers 50% of concession fees to the municipality" and treats
the mechanism itself as current news.

Audit verdict: deterministic is closer to correct. There is a concrete
mechanism but no demonstrated new event/change; it may be background inside a
routine financial report. The model also overstates source authority ("official
data from an appendix/document") — the actual evidence is still extracted from
an AUTO_CAPTION transcript. Classification: model over-permissive; no rubric
change required.

### 1.2 social_aid — Deterministic NO_PUBLISHABLE_ANGLE / Model POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH

Fact: a deputy mayor submitted a proposal concerning non-repayable financial
assistance for individuals. Missing: beneficiaries/eligibility, amount, purpose,
whether this is a new scheme vs routine administrative processing, procedural
outcome.

Audit verdict: the model's NEEDS_RESEARCH is more useful. There is a concrete
actor + action + object (proposal → financial assistance → individuals) —
enough to justify targeted research, not enough for publication. The
deterministic gate is probably too strict here. Classification: likely
deterministic blind spot — a concrete but incomplete proposal should be able to
reach NEEDS_RESEARCH.

### 1.3 budget_execution_2026 (CIs4AIKuOiw) — Deterministic NEEDS_RESEARCH / Model NO_PUBLISHABLE_ANGLE

Evidence establishes only that the mayor presented the mid-year cash-execution
report as of 30 June 2026 — no unusual trend, no over/underspending, no
material deviation, no policy change, no consequence for residents.

Audit verdict: model is slightly stronger for the angle as formulated. "Mid-year
budget report was presented" is routine; if the underlying report contains a
surprising deviation, that supports a NEW angle discovered from the report, not
automatic publishability of the procedural angle. Classification: deterministic
path somewhat over-permissive around periodic reports.

### 1.4 financial_management_meeting — Deterministic NEEDS_RESEARCH / Model NO_PUBLISHABLE_ANGLE

Proposed proposition: "the presence of the deputy mayor for finance highlights
the importance of financial oversight."

Audit verdict: clear model win. Presence at a meeting is not a news development
and "highlights the importance" is editorial inference, not a new proposition.
Classification: clear deterministic blind spot — routine participation/presence
should not survive as NEEDS_RESEARCH.

### 1.5 midyear_budget_2026 (YsqD4T0D850) — Deterministic NEEDS_RESEARCH / Model NO_PUBLISHABLE_ANGLE

Same semantic family as 1.3: a mid-year cash-execution report was presented.
Audit verdict: leans model / routine-report veto. The report itself may contain
news; its mere presentation does not. Better workflow: routine report detected →
inspect for concrete deviations/changes → if found, propose a new angle — not
"routine report exists → current angle = NEEDS_RESEARCH". Classification: same
narrow blind spot as 1.3, not a separate rule.

### 1.6 school_funding — Deterministic NO_PUBLISHABLE_ANGLE / Model PUBLISHABLE_ANGLE

Evidence: the mayoral administration proposes additional funding for classes
whose pupil count is below the statutory minimum. Missing: number of affected
classes/schools, total amount, final procedural outcome, practical consequence.

Audit verdict: neither current verdict is ideal — more concrete than the
deterministic NO_PUBLISHABLE_ANGLE, not ready for the model's
PUBLISHABLE_ANGLE. Best semantic state: POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH.
Classification: reinforces the "concrete but incomplete proposal" blind spot
seen in social_aid.

### 1.7 museum_funding_refusal — Deterministic NO_PUBLISHABLE_ANGLE / Model PUBLISHABLE_ANGLE

Evidence: a civic/veterans group requested support to renovate a room and create
a museum exhibition; the municipality currently has no legal basis to fund it
(exhibition status unresolved, non-municipal territory). The proposed angle says
"the municipality refused funding".

Audit verdict: neither side is fully right. Clearly more story-like than a
routine report (request → public initiative → inability/refusal → concrete
legal/property reason), but AUTO_CAPTION + procedural_status=UNKNOWN means
"refused" may overstate what was an administrative/legal position rather than a
final decision. Best current state: POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH.
Research should establish: who formally made the determination; whether there is
an actual refusal/decision; the exact property/status reason. Classification:
same concrete-action blind spot plus procedural-status caution.

## 2. Pattern across the 7 disagreements

The disagreements do not suggest "use the model judge instead". Summary:

- Pattern A — concrete incomplete action (social assistance proposal,
  under-capacity class funding proposal, museum-support refusal/inability):
  real actor + action + affected object, but missing parameters or procedural
  certainty. The useful state is often NEEDS_RESEARCH — not automatic
  NO_PUBLISHABLE_ANGLE and not automatic PUBLISHABLE_ANGLE.
- Pattern B — periodic/routine administrative document (mid-year budget
  execution report, annual financial report, meeting attendance): the
  existence or presentation of the document is not itself sufficient novelty.
  Research may inspect the document for a different concrete proposition, but
  should not automatically preserve the original procedural angle as
  NEEDS_RESEARCH.
- Pattern C — fact vs event: a concrete number/mechanism in an appendix can be
  interesting without being a current news event (concessions_funding).

## 3. Enrichment candidate audit

The report's "7 of 15 facts had machine corroboration candidates" must not be
read as seven verified facts. Manual semantic review:

### CIs4AIKuOiw (4 facts with candidates)

- USEFUL: burgascouncil.org/postoyanni-komisii/1 — highly specific official
  agenda/document entry (Димитър Николов; report on cash execution; revenue
  and expenditure; EU accounts; date 30.06.2026; linked appendices). For
  f008/f009 this meaningfully corroborates author/institutional actor,
  document existence, document subject, reporting date. It does NOT
  corroborate any substantive conclusion about budget performance.
- WEAK/FALSE-POSITIVE: burgas.bg/bg/2026-1 — much of the overlap is global
  page/navigation terms (Димитър Николов, Община Бургас, бюджет); not
  meaningful corroboration of the report itself.
- GENERIC: burgascouncil.org/reshenia — number/date overlaps only; the opened
  excerpt does not prove the relevant decision is on that page.

Audit conclusion: for the selected angle the official commission page confirms
what document was on the agenda, but the missing journalism remains: What
changed? What is above/below plan? What matters to residents? → RESEARCH_MORE
is correct.

### YsqD4T0D850 (3 facts with candidates)

- f002 (Stanimir Apostolov present at meeting): the commission page contains
  his name and finance role in OTHER agenda/document context — does not
  establish attendance at this particular meeting. Lexical false positive as
  corroboration of attendance.
- f004 (annual budget report): the commission page contains the relevant type
  of official report/document; can likely repair the noisy ASR date once the
  exact document entry is bound. Useful source lead.
- f006 (mid-year budget execution report): a very specific matching document
  entry — useful corroboration of report existence, actor, subject, 30.06.2026
  reporting date. burgas.bg/bg/2026/proektobyudzhet-2026-g is not strong
  corroboration merely because it contains the mayor's name and 2026 budget
  language.

Audit conclusion: enrichment found the right official surface, but it does not
prove that attendance of a finance official is news or that presentation of a
routine budget report is publishable. RESEARCH_MORE remains safer than
automatic promotion.

## 4. Enrichment design finding

The lexical candidate matcher is exactly what its name says — a candidate
source locator, not a semantic corroboration engine. That distinction must
stay explicit. A next-generation enrichment step, if ever needed, should bind
fact → exact page/document span → semantic entailment → procedural authority
before a corroboration candidate becomes publication-grade evidence. Do not
simply lower the lexical threshold.

## 5. Recommended decision now

Do not change the global rubric yet — editor review is still pending; the
evidence identifies two hypotheses but does not justify changing production
behavior before human validation.

- Hypothesis 1: a candidate with specific actor + specific
  action/proposal/refusal + concrete affected object/group may deserve
  NEEDS_RESEARCH even when amount/outcome/details are missing.
- Hypothesis 2: a candidate whose only novelty is "report presented / meeting
  held / official attended / agenda item discussed" should usually remain
  NO_PUBLISHABLE_ANGLE unless the extracted evidence already contains a
  concrete delta/consequence.

These are semantic hypotheses, not new hard-coded keyword rules.

## 6. Current verdict

- TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING+ — V2 fixed the major
  structural failures and produces much healthier outputs; this audit finds a
  narrow semantic boundary (concrete incomplete action vs routine
  administrative process) that still needs human calibration. Do not promote
  to PROVEN solely on the 70.8% shadow agreement.
- TRANSCRIPT_RESEARCH_ENRICHMENT = PROMISING — the search layer found relevant
  official surfaces, but machine lexical matches are not yet
  semantic/authoritative corroboration.
- EDITORIAL_EFFECTIVENESS = PENDING — the human editor remains the correct
  next arbiter.

## 7. Recommended next step

No immediate code change. Wait for the current editor feedback. When it
arrives, specifically compare the editor's decisions against these semantic
cases: social aid, school funding, museum support/refusal, routine budget
reports. If editor feedback supports the same pattern, implement one narrow
semantic correction — CONCRETE_ACTION_NEEDS_RESEARCH vs ROUTINE_REPORT_VETO —
using semantic structure, not entity/topic-specific rules. Until then: freeze
V2, freeze thresholds, freeze model/deterministic authority, do not draft
transcript articles.
