# M2.3 Report — Grounded Multi-Style Draft Experiment

Date: 2026-09-14. Status: complete. Awaiting editor review.

## Experiment configuration

End-to-end pipeline: EvidencePacket → style retrieval (VOICE+MODE fallback) → versioned
draft prompt → single model decode → lineage store (JSONL). Files in `var/draft_experiment/`.

| Input | Value |
|---|---|
| Evidence packets | 10 live Chernomorie current-story packets (`evidence_packets.jsonl`) |
| Style corpus | frozen M2.2 corpus (`var/style_corpus/articles.jsonl`) |
| Site DNA | `CHERNOMORIE_SITE_DNA` (frozen M2.2) |
| Voices | VOICE_HOUSE (proven), VOICE_DESISLAVA_RECENT (provisional, scope 2024–2026) |
| Modes | MODE_STANDARD_NEWS, MODE_BRIEF, MODE_EVENT_PREVIEW, MODE_CULTURE_FEATURE |
| Retrieval | lexical + metadata, 3 examples per draft, frozen fallback chain |
| Draft prompt | version `m2.3-prompt-1`, sectioned SYSTEM/CURRENT EVIDENCE/SITE DNA/VOICE/MODE/3 STYLE EXAMPLES/TASK/FORBIDDEN |
| Scorecard | 6×1–5 fields + would-publish YES/NO + "change first" note |

Primary drafts: EV-01…EV-10 (all VOICE_HOUSE across four modes).
Extras: EV-01B/EV-05B/EV-04B (VOICE_DESISLAVA_RECENT), EV-02B (HOUSE+STANDARD_NEWS for BRIEF-vs-news),
EV-10B (HOUSE+STANDARD_NEWS for preview-vs-news).

## Model

| | |
|---|---|
| Model | openai/gpt-oss-20b |
| Temperature | 0.4 |
| Max tokens | 1500 |
| Reasoning effort | low |
| Total generation time | ~177 s for 15 drafts (≈12 s/draft) |

Single capable model; config frozen at evaluation start (§21).

## Prompt version

`m2.3-prompt-1` — evidence-first, style examples provably separated and labeled STYLE ONLY / NOT facts
(verified by contract tests).

## Evidence packets

10 packets from varied real current material: standard local news (EV-01, EV-05, EV-08), short factual
item (EV-02), event announcement (EV-03, EV-07, EV-10), culture/event story (EV-04), public-institution
announcement (EV-06, EV-09). Covers requested variety without forcing every MODE onto unsuitable evidence.

## Retrieval performance

- 3 examples per draft, all same-VOICE+same-MODE (primary); DESISLAVA retrievals returned only recent
  (≥2024) Desislava articles under the recent-scope lock.
- Fallback chain exercised (e.g. EV-04B) and asserted by tests.
- Lexical/metadata retrieval sufficient; no vector DB needed.

## Factual audit

Deterministic sentence-level audit of every draft against its EvidencePacket (retrieved style texts as
adversarial leakage context). Results in `audits.json`.

| Group | Drafts | Unsupported | Leaks |
|---|---|---|---|
| Primary (EV-01…10) | 10 | **0** | **0** |
| Blind/mode extras | 5 | 4 soft-claim flags* | 0 |

* The 4 flags are connective/attitude phrasings (e.g. "изразиха благодарност…", "подчертава важността
на културния туризъм") — no invented names, numbers, dates, positions, or quotes. Style-level
embellishment on supported facts, not new material facts.

## Archive leakage tests

§19 adversarial gate: PASS. Three cases (EV-05/EV-03/EV-06) retrieved HOUSE articles chosen to maximise
entities **conflicting** with the evidence. Adversarial sets contained 57–58 distinctive names/numbers each.
Zero appeared in any draft; zero leak hits (`adversarial_leakage.json`).

## HOUSE results

Four modes generated and rendered. Routine local-news, brief, preview, and culture items produced readable
grounded drafts. Style examples visibly shaped tone without manufactured facts.

## DESISLAVA results

Three same-facts DESISLAVA-recent drafts (EV-01B/05B/04B). Voice paints a more sentence-longer,
connective, attentive register; fully grounded.

## MODE results

- BRIEF (EV-02) vs STANDARD_NEWS (EV-02B) — same facts, clearly different length/intensity.
- EVENT_PREVIEW (EV-10) vs STANDARD_NEWS (EV-10B) — preview frames what/where/when + why join; news reports the announcement as fact.

## Blind HOUSE vs DESISLAVA test

3 same-facts pairs (EV-01, EV-05, EV-04). Labels hidden; A/B mapping in `blind_map.json`; identity NOT
disclosed in `review.md` (§16). Editor judgement fields blank, awaiting review.

## Blind MODE tests

2 mode pairs (EV-02 BRIEF-vs-news, EV-10 preview-vs-news), sealed mapping in `blind_map.json`.

## Editor scores

Blank scorecards for all primary drafts and blind/mode pairs are in `review.md`. No editor scores yet —
this is the hand-off point.

## Editing-effort findings

Awaiting editor. Pipeline-side: B-side drafts occasionally add connective attitude sentences the editor
would trim (see What failed).

## Publish-after-edit rate

To be filled by the editor from the scorecards.

## What worked

- Factual grounding is a hard blocker met: 0 material unsupported/contradicted/leaked claims across 15 drafts.
- Adversarial archive leakage gate passes under deliberately hostile example selection.
- VOICE and MODE are runtime composition (no combined permanent profile IDs).
- Retrieval respects voice/mode fallback + recent-scope lock deterministically.
- Deterministic lineage, blind order, and config reproducibility verified (10/10 tests pass).

## What failed

- Style-level connective/attitude embellishments in extras are acceptable prose but not strictly
  evidence-derived; a strict editor may ask for a tighter "no attitude not in evidence" pass.
- No editor scores yet — the VOICE/MODE perceptual question is open until the editor scores the blind pairs.

## Dominant remaining problem

Not yet determined (§23). Candidates ranked for the next decision, not fixed now:
- D. prompt (attitude constraints) — leading for the minor embellishment flags;
- C. style profiles — only if blind discrimination is weak (no evidence yet);
- B. retrieval — appears healthy;
- A. fact packet — appears healthy (source-derived).

## Known limitations

- VOICE_DESISLAVA_RECENT remains provisional (n=12, 2024–2026 scope).
- Editor perceptual judgement is the single source of the style verdict — the report cannot self-certify it.
- 10 packets, one model: not a general performance claim.

## Backlog

- Tighten prompt/anti-attitude wording if the editor flags connective embellishment.
- If blind discrimination is weak, refine profiles (never the frozen M2.2 set during eval).
- L4 safe drafts / L5 WordPress remain explicitly out of scope (§24).

## Verdict

Awaiting editor scoring of `review.md`. Tentative verdict conditioned on pending blind results:
- Reliable VOICE/MODE discrimination + publishable-after-edit share → **MULTI_STYLE_DRAFTING_PROVEN**.
- Grounding holds, styles indistinguishable → **GROUNDING_PROVEN_STYLE_WEAK**.
- Styles visible, factual pipeline needs correction → **STYLE_PROVEN_GROUNDING_WEAK**.
- Else → **DRAFT_EXPERIMENT_NOT_PROVEN**.

The factual half is independently proven (0/15 material failures). The style half is the editor's call.

## Recommended next step

Review `var/draft_experiment/review.md`, score all primary drafts and the blind pairs, then confirm the
verdict. Do not begin production integration.

---

STOP AND WAIT FOR EDITOR REVIEW
