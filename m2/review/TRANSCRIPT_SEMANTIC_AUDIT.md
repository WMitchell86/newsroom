# Transcript Discovery — Semantic Audit (2026-09-17)

This is the checkpoint the editor asked for: **"Намира ли системата истинската новина в 90 минути заседания?"** — a semantic audit of the batch *results*, not of the code. Sources inspected: `TRANSCRIPT_DISCOVERY_BATCH_REPORT.md`, `MANUAL_AUDIT_SAMPLE.md`, all 7 `var/transcript_analysis/*.json`, every extracted fact with its timestamp.

**No code was changed for this audit.** The rubric, thresholds, hook guidance and profiles stay frozen (as directed).

---

## 1. Did it segment meetings sensibly? — Mostly yes; two boundaries were missed

Good: agenda-cue boundaries landed correctly on real agenda items in 5/7 recordings (e.g. `8h51zs_NUbw` split its 2-minute recording into the three actual agenda points; `CIs4AIKuOiw` isolated "Точка три" cleanly; `YsqD4T0D850` caught "Трета точка").

Missed:
- **`xvsdi_j7s5c` (19:53) → 1 topic.** A 20-minute education-committee meeting with six agenda points merged into one giant topic. The cue detector missed the ASR-mangled "поредното състезание" (= *заседание*). The 3 extracted facts still cover three real agenda items, so discovery survived — but topic granularity failed here.
- **`7k-FZXrcmq8` (08:26) → 1 topic.** Same pattern: a full budget-adoption meeting treated as one topic. Facts were still extracted across the meeting (three different agenda points), so the topic layer added little in these two cases.

Verdict: **sensible but not yet reliable at the topic layer for long, ASR-noisy meetings.** The deterministic-cue-first design is right; the fallback currently collapses to one neutral topic, which is honest (no fabricated splits) but coarse.

## 2. Did it identify the real interesting developments? — Yes, consistently

The same genuine story surfaced independently in **five different recordings**: *проектът на бюджета за 2026 е внесен/приет в ресорните комисии*. In `YsqD4T0D850` the discovery even produced the **most reader-relevant angle of the whole batch** on its own:

> „В проекта за бюджет за 2026 година **няма промяна в данъците, таксите и цените** на услугите спрямо бюджет 2025 година." [00:02:53]

That is a real news lead a local editor would use — discovered from raw auto-captions, with a timestamp. Also strong: the two-line property-program story in `b13U-N_Vk9c` (285 objects, 111 for housing + "включването не гарантира продажба" — a responsible two-sided framing) and the morgue-equipment decision in `HB1avBfeiRw` (the same story the LIVE pilot found through a human transcript — here found autonomously).

## 3. Did it miss obvious stories? — Two, both at the angle layer, not the fact layer

- **`7k-FZXrcmq8`**: the *museum-initiative letter* was extracted, but its angle ranked below the budget angle with `POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH` + good research questions (amount sought, exhibition theme, deadlines). Acceptable — but a human editor might prefer the citizen-initiative story; the ranking is threshold-driven, not an editorial judgment.
- **`CIs4AIKuOiw`**: the **extended budget regime** („общината работи в условия на удължен бюджет — 1/12 от разходите" [00:10:49]) was extracted as a fact but **no candidate angle was built around it** — arguably the most policy-relevant single fact in the batch (a municipality running on a prolonged budget in September). The angle proposer went with the generic "main decision" instead. This is the clearest "missed obvious story" instance, and it is a *model judgment* miss, not a contract miss.

## 4. Did it hallucinate importance? — Two real problems found (the batch's most valuable findings)

**(a) Contradictory vote tallies for the same vote.** `CIs4AIKuOiw` extracted both:
- f004 [00:00:37]: „приета с **четири** гласа за, един против и един въздържал се"
- f005 [00:02:13] / f006 [00:02:19] / f013 [00:10:10]: „**трима** гласували за, двама въздържали се и един против"

These cannot both be right (they may even be two different votes — the ASR makes it undecidable). Nothing in the pipeline flags the **internal contradiction**; each fact individually looks fine and carries its own timestamp. This is exactly the fragile-claim class the corroboration guard exists for, and it proves the guard's necessity — but a dedicated `internal_contradiction` flag across sibling facts would surface it much earlier. **Flagged, not fixed** (frozen rules).

**(b) Unverifiable but stated-as-fact claims.** `7k-FZXrcmq8` f001: „седем гласа за" при гласуване на *втора* точка — а комисията е със 7 членове и в същия трансkript други гласувания показват по-малки броячки; and `HB1avBfeiRw` f003 is marked **UNCERTAIN** (the only fact using the flag — the mechanism works) precisely because the report attribution differs from the rest of the batch. The batch also proves names mutate: the mayor appears as **„Димитър Николов" (7×)** and **„Димитър Ников" (2×)**. Both spellings survive downstream today. The correct general behavior (flag, never silently correct) is partially in place; the two variants currently just coexist as separate facts.

So: no hallucinated *content* was found (every fact traceable to its timestamp — verified), but **hallucinated confidence** is real: the model states ASR-uncertain tallies as flat facts, and only 1/48 uses the `uncertain` flag.

## 5. Are the NO-STORY decisions reasonable? — Only one, and it is reasonable

The batch produced essentially one no-story outcome: `xvsdi_j7s5c::budget_2026_discussion` → `POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH` with two genuinely useful research questions (education priorities in the draft budget; investments vs cuts vs 2025). Reasonable: the discussion happened, but the excerpt carries no concrete budget content — the honest state is exactly "needs the official докладна". No case shows the **padding path** (fabricated angles to reach 3) — the relaxed floor worked: `xvsdi_j7s5c` shipped 2 real angles, `7k-FZXrcmq8` 3 real ones. **No padding angle was observed anywhere in the batch.**

## 6. Are the research questions useful? — Yes; concrete and actionable

Both NEEDS_RESEARCH candidates produced editor-usable questions (amount sought / theme / deadlines for the citizen initiative; education priorities / investments-or-cuts for the budget). These map directly onto the targeted-research layer's `missing_dimensions` machinery from the LIVE pilot. One gap: most selected angles are `ANGLE_SELECTED` without explicit research-question sets — for auto-caption material the *corroborating-source question* ("кой официален документ потвърждава това?") should accompany every selected angle; currently it is implicit in the corroboration flags rather than an explicit question.

---

## The 47/48 corroboration question — breakdown

The near-100% flag rate is driven overwhelmingly by **names**: `personal_or_org_name` 21, `exact_quote` 14 (mostly the ASR-quoted agenda phrasing), `material_number` 11, `legal_institutional_status` 7, `final_decision` 5, `negation_sensitive` 2 (overlapping combos). Only **1 of 48 facts** carries no risk flag — and that one („критериите за имоти са за вино или жилищно строителство…") is itself almost certainly an ASR mangle of „за вилно **строителство**" (wine → villa!).

**Conclusion: this is the guard working, not overreach** — municipal transcripts are inherently dense in names/numbers/decisions, and the mayor-name mutation (Николов/Ников) plus the wine/villa mangle demonstrate concretely why each class needs a second source. The architecture the editor described is exactly what emerged:

```text
transcript = story discovery engine (48 candidate facts, 19 angles, real leads)
official dokladna/agenda/protocol = publication evidence layer
```

Transcripts as publication evidence: **almost never** (by design). Transcripts as discovery: **proven by this batch**.

## Cross-cutting themes (for the record, not for rules yet)

The recordings are seven committee sessions from the same council day (2026-09-16) processing the same council-wide agenda items (budget 2026, EU-funds report, property program). Any eventual article production needs **cross-committee deduplication** — the same "бюджетът е внесен" fact appears in 5+ recordings and must not become five articles. This is a discovery-layer concern to raise with the editor, not something to code now.

## Answers to the six questions (one line each)

1. Segmentation: mostly sensible; missed boundaries on 2 long ASR-noisy meetings (honest fallback, coarse).
2. Real developments: yes — the budget-2026 thread surfaced independently in 5/7; tax-freeze lead is genuinely good.
3. Missed stories: two, at the angle layer — the museum initiative under-ranked, the prolonged-budget fact got no angle at all.
4. Hallucinated importance: content is timestamp-traceable (no phantom facts), but ASR confidence is overstated — contradictory tallies co-exist, name variants co-exist, 1/48 flagged uncertain.
5. NO-STORY decisions: the single NEEDS_RESEARCH outcome is reasonable; no padding angles anywhere.
6. Research questions: concrete and usable; missing only an explicit corroborating-source question on selected angles.

## Recommendation to the editor

- **Track S → PROVEN** remains gated on the live Brave benchmark (needs `BRAVE_SEARCH_API_KEY`; the harness point is ready, zero code needed).
- For Track T, the audit found **no reason to change code or rules**; the follow-ups worth considering *after* editor feedback: internal-contradiction flagging between sibling facts, explicit corroborating-source research questions on selected angles, and cross-committee dedup before any article production.
- The six questions above are the semantic record; `facts_audit_dump.txt` (tmp/) holds the full fact/timestamp listing backing them.
