# Transcript Research Enrichment — gap-driven, bounded, no drafting (M2S-R3 Part D)

Verdict: **ENRICHMENT_EXECUTED — dual provenance candidates recorded for 7 of
15 facts across the 2 RESEARCH_MORE recordings; both stay RESEARCH_MORE after a
real readiness re-run; nothing promoted, nothing drafted.**

Data: `var/transcript_analysis_v2/research_enrichment.json` (written beside the
V2 artifacts; no artifact under `var/transcript_analysis_v2/` other than this
report was created or modified).

## 1. Scope and guarantees

- Only recordings whose REAL readiness orchestrator said `RESEARCH_MORE`
  (CIs4AIKuOiw, YsqD4T0D850) were researched — gap-driven, not blanket.
- Bounded by construction: 5 public-phrase queries × 2 capabilities (NEWS, WEB)
  per recording through the proven `run_search_operation` chain; ≤6 fetch
  targets per recording, one URL per domain, official domains first; every
  miss would be recorded in the source taxonomy, never silently dropped.
- Privacy: queries stay in public-phrase space (`"Община Бургас" бюджет 2026
  приходи отчет`-style); no transcript text, fact text, or draft prose left
  the machine — the outbound surface is queries and public URLs only.
- No drafting. The ONLY recomputation was `readiness.assess_readiness()` on the
  enriched packet, with the recorded candidate passed verbatim and the angles
  assessment rebuilt through the real gate under the recorded floor.

## 2. What was found

Search (10 ops/recording, keyless chain = Google News RSS + DDGS): all
`SEARCH_COMPLETE`. Hit domains per recording (deduped): `www.burgas.bg`
(official municipal), `burgascouncil.org` / `www.burgascouncil.org`
(council-related), `www.bta.bg` (national news agency), `news.google.com`
(aggregator; discovery-only value). One `SEARCH_INCOMPLETE` on
`"Община Бургас"` quoted query (chain honest about partial coverage).

Fetch (this final run): **9 of 9** targeted pages opened successfully
(44k–582k chars extracted). An earlier bounded probe run had recorded the
honest misses that justify this harness (`www.burgas.bg/bg/priority-projects/`
→ `FETCH_HTTP_ERROR`; a JS-walled council page → near-empty extraction) —
kept in `tmp/research_enrichment_live.log` for the audit trail.

Corroboration candidates (machine check: shared material numbers + ≥2
content tokens, over tag-stripped page text):

| recording | facts | with candidates | example domains |
|---|---|---|---|
| CIs4AIKuOiw | 9 | **4** | www.burgas.bg, burgascouncil.org, www.bta.bg |
| YsqD4T0D850 | 6 | **3** | www.burgas.bg, burgascouncil.org |

The name is deliberately cautious: a lexical match against a page we opened is
a *candidate*, not publication-grade corroboration. Per
`research.validate_council_claims`, AUTO_CAPTION decision claims need an
official protocol/decision source or explicit human corroboration — a machine
match can only point the editor to where to look.

## 3. Readiness re-run (the only recomputation)

Both recordings: `RESEARCH_MORE -> RESEARCH_MORE` (unchanged, honestly).

The orchestrator re-verified the same candidate against the enriched evidence
surface and still found it short of specifics — recorded corroboration
candidates are not the official adjudicated facts the rubric wants, and the
sufficiency gate did not bend for lexical overlap. The mechanism under test
("enrichment can only *help* an argument, never declare one ready") behaved
exactly as designed; the pipeline refused to promote on thin provenance.

What the enrichment DID change: the two recordings now carry concrete,
named leads (which municipal/agency pages repeat the budget numbers) so the
editor's research session starts from URLs instead of open questions.

## 4. Non-changes

- `article_readiness_status` totals unchanged: 2 DRAFT_READY / 2 RESEARCH_MORE
  / 3 NO_PUBLISHABLE_ANGLE.
- No threshold, profile, prompt, or routing change; no drafting; no editor
  contact. Enrichment data is advisory context for the next human step.
