# Transcript Discovery Batch Report — M2S Track T

Verdict: **TRANSCRIPT_DISCOVERY_ENGINEERING = PROMISING** — the generic pipeline (raw SRT → timestamped provenance → topics → grounded facts → angle gate → readiness) now exists, runs end-to-end on all 7 recordings with zero hand-authored facts/angles, and every step is inspectable; it is *promising* rather than *proven* because the model-assisted extraction quality (not the deterministic contracts) still needs human editorial inspection before any editor involvement.

This is an **engineering/discovery benchmark only** — readiness totals here are NOT editorial-quality proof, and no articles were generated (harness C/B11).

## Pipeline

```text
raw SRT (authoritative) → TranscriptDocument (ms-provenance, AUTO_CAPTION)
→ time-aware overlap normalization (provenance-preserving)
→ agenda-style topic segmentation (deterministic cues + neutral fallback)
→ model-assisted candidate facts (judge pool; segment-id binding re-verified;
  unknown refs dropped; ASR risk flags)
→ candidate angles → angles.assess_angles (rubric v2 gate unchanged,
  relaxed floor explicit via min_candidates)
→ readiness (no drafting)
```

## Batch results (7/7 parsed)

| video | duration | topics | facts | angles | readiness |
|---|---|---|---|---|---|
| 7k-FZXrcmq8 | 00:08:26 | 1 | 3 | 3 | ANGLE_SELECTED |
| 8h51zs_NUbw | 00:02:20 | 3 | 7 | 4 | ANGLE_SELECTED |
| CIs4AIKuOiw | 00:20:52 | 4 | 13 | 3 | ANGLE_SELECTED |
| HB1avBfeiRw | 00:09:44 | 2 | 6 | 3 | ANGLE_SELECTED |
| YsqD4T0D850 | 00:05:00 | 2 | 6 | 3 | ANGLE_SELECTED |
| b13U-N_Vk9c | 00:23:50 | 3 | 10 | 3 | ANGLE_SELECTED |
| xvsdi_j7s5c | 00:19:53 | 1 | 3 | 2 | ANGLE_SELECTED |

Totals: **48 extracted facts** (47 flagged corroboration-required under AUTO_CAPTION rules), risk surface: personal/org names 21, exact quotes 14, material numbers 11, legal/institutional 7, final decisions 5, negation-sensitive 2. Timestamp provenance coverage: 100% (every fact bound to real segment ids + exact ms span; a fact referencing an unknown segment is dropped, never guessed).

`ANGLE_SELECTED` means the *gate* selected a viable candidate angle — it does not mean an article was produced or that the editor would accept it (B11, C2).

## Timestamp provenance

Standard SRT (`00:01:31,280`) parses to exact ms (`91280`), preserved through overlap merging: each normalized span maps back to one or more original `segment_id/start_ms/end_ms` triples (tested). `00:00:01,000`-style locators are the machine provenance; the human-readable cleaned Markdown previews remain exactly that — previews (`clean_subs.py` kept as a presentation helper, no longer authoritative).

## High-risk ASR claims needing corroboration before publication

Under the new trust-level guard (B6), every `final_decision` / `material_number` / `negation_sensitive` / `exact_quote` / personal-name claim extracted from AUTO_CAPTION material is marked `corroboration_required=True` and `research.validate_council_claims` now refuses publication-grade provenance for decision claims resting on an auto-caption transcript alone (an official protocol/decision source or explicit corroboration marker is required; HUMAN_VERIFIED / OFFICIAL_VERBATIM carry stronger authority). The transcript still legitimately *discovers* the story and its research questions.

## Manual audit sample

`var/transcript_analysis/MANUAL_AUDIT_SAMPLE.md` — for each recording: the strongest candidate proposition, its exact timestamp links, the readiness decision and why, plus a rejected/no-story candidate where the gate produced one. For internal inspection before any editor involvement; this batch was NOT sent to the editor (C3).

## Not encoded

No committee name, agenda item, person, or expected outcome from the 7 recordings appears anywhere in `src/` — the corpus is a test corpus, not a rule book. Deterministic scoring in the batch runner derives only from the extracted facts' own surfaces.

## Known limitations

- Topic segmentation uses deterministic BG agenda cues with a neutral single-topic fallback; strongly disorganized ASR audio can merge distinct topics (visible in the 1-topic recordings).
- Local rubric scoring for angle candidates is intentionally conservative (evidence-surface heuristics only); a richer deterministic scorer is future work after editor feedback.
- Model extraction depends on the judge-pool quota; a failed call degrades to `NO_EXTRACTED_FACTS` for that recording instead of fabricating facts.
- No agenda-document enrichment yet (B10 seam is provided via the new search layer; absence of official documents is exactly the RESEARCH_MORE signal).

## Good Enough backlog

- Live Brave benchmark run once a key exists (A11).
- Agenda/protocol enrichment via official URLs for the flagged decision claims.
- Editor-facing discovery review artifacts only after the pending editorial review lands.
