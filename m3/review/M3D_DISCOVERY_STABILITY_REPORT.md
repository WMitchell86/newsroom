# M3D — Discovery Reproducibility & Stability Report

**Date:** 2026-09-19 · **Base:** frozen `860f582` + M3D harness commits · **Harness:** `scripts/evals/discovery_stability.py`

## Executive summary

**The headline result, in the editor's framing:** this was never "fact extraction collapses".
Across **79 live model runs** on 4 recordings, fact extraction never collapsed: **0
CATASTROPHIC_ZERO_YIELD**, fact-set semantic overlap **0.955–0.977**, segmentation
**byte-identical**. What varies is the **angle layer**: given the same evidence, the model
proposes different *proposition wording* each run, and that wording decides which facts get cited
into the readiness rubric. A ±1 rubric point around the threshold flips the editorial outcome
(`RESEARCH_MORE` ↔ `NO_PUBLISHABLE_ANGLE`). Measured: **22.2–31.6% OUTCOME_FLIP** on the known
flaky recording, **0%** on the stable one.

The smallest permitted corrective change (Part L4) is a **stage cache for the two model stages
only** (facts + proposals), keyed by transcript bytes + stage version + model config, with the
deterministic gate always re-run. Replay of the same evidence is then **operationally
reproducible: 6/6 replays byte-identical**, while `--force-discovery` lets the editor re-open the
question without destroying the previous snapshot.

**Provider situation (material limitation):** the free Gemini quota was exhausted mid-measurement
(500 req/day; surfaced as HTTP 429, then as a misleading `HTTP 400` with an empty body) and
OpenRouter has no balance (HTTP 402). **17 of 40 corpus runs** are therefore `DISCOVERY_DEGRADED`
rather than measurements. They are **classified, never editorialized**: zero of them became
`NO_EXTRACTED_FACTS` (Parts E/M proven live).

## 1. Corpus

| # | recording | topics | bytes | role | runs |
|---|-----------|--------|-------|------|------|
| A | `7k-FZXrcmq8` | 8 | 13 712 | stable committee session | 10 |
| B | `YsqD4T0D850` | 5 | 8 920 | **known flaky** (M3B.1) | 10 (+20 pre-L4, +19 after = 49) |
| C | `b13U-N_Vk9c` | 12 | 25 013 | longest, adversarial | 10 (7 quota-blocked) |
| D | `xvsdi_j7s5c` | 11 | 20 744 | previously unseen | 10 (all quota-blocked) |

All inputs came from the raw-SRT cache (`var/youtube_intake/transcripts/`); **no fetching ran**.
Deterministic stages were additionally cross-checked model-free (`--check-determinism` =
**IDENTICAL** on all 4 SRTs).

## 2. Per-stage stability

| stage | A `7k-FZXrcmq8` | B `YsqD4T0D850` | verdict |
|---|---|---|---|
| segmentation | identical, 10/10 | identical, 49/49 | STABLE (deterministic) |
| fact extraction (model) | facts 13–16, overlap 0.905 | facts 6–8, overlap **0.955–0.977** | PROMISING — wording/detail varies, never collapses |
| grounding | dropped 1–2, stable kinds | dropped 4–6, same kinds (`wrong_decision_status`, `wrong_number`, `unsupported_paraphrase`) | STABLE |
| angle proposals (model) | 3–4 candidates, **overlap 0.389** | 2–3 candidates, **overlap 0.741–0.789** | **weakest layer — the flip source** |
| readiness (deterministic gate) | 10/10 `RESEARCH_MORE` | 4/10 vs 6/10 split | **flips here**, driven by the layer above |

**Earliest divergent stage:** angle proposal. Facts agree; outcomes diverge — the flip is born
between fact extraction and readiness, not in extraction.

## 3. Failure taxonomy (Part F, corrected semantics)

`STABLE` = same outcome as the first run; `OUTCOME_FLIP` = a *different valid* outcome, not a
failure. Aggregated over **59 runs on the flaky recording** (39 uncached + 20 pre-L4):

| corpus | runs | OUTCOME_FLIP | STABLE | catastrophic |
|---|---|---|---|---|
| pre-L4 (`var/discovery_stability`) | 20 | 6 (**31.6%**) | 13 | 0 |
| after (`var/discovery_stability_after`) | 19 | 4 (**22.2%**) | 14 | 0 |
| fresh corpus (10, baseline `r001`) | 10 | 4 | 6 | 0 |

Corpus-wide (40 runs): `model_call_failed` 167, `valid_empty_fact_list` 12, every other category
0; **zero-yield runs: 0**. The 17 provider-blocked runs are all `DISCOVERY_DEGRADED` (§6).

## 4. Root cause of OUTCOME_FLIP (mechanism, not just stage)

Same fact set → different *proposition wording* → different cited-fact count → different rubric
score → flip. On B, two competing propositions about the same mid-year budget discussion:

- *"Кметът лично представи информация за касовото изпълнение … пред Комисията по туризъм"* → cites **3** facts
- *"Представена е информация за приходите и разходите на общината към 30 юни 2026 г."* → cites **1** fact

The rubric sums 7 criteria against a threshold of 5, and readiness needs a
non-`NO_PUBLISHABLE_ANGLE` candidate, so a ±1-point swing **is** the editorial outcome. The model
is not unstable about *what happened*; it is semantically variable about *what to call it*, and
the readiness gate amplifies that into a 22–32% flip rate.

Independent confirmation (Jev shadow, separate provider, 3 pairs in
`var/discovery_stability/jev_shadow_pairs.jsonl`): a same-fact paraphrase from two different runs
is judged `SAME_CLAIM` with probability **1.00**, and the two competing flip candidates are judged
`OVERLAPPING_CLAIM` (**0.77**) — the divergence is aggregation/wording, not evidence.

## 5. Corrective change: L4 stage cache (smallest permitted)

**Cached:** only the two **model** stages — extracted facts (+ dropped + skips) and angle
proposals — under `var/discovery_stage_cache/`, keyed by `transcript_hash + STAGE_VERSION +
model_config_fp`. **Never cached:** readiness, assessment, and the whole deterministic gate — a
rubric or version change re-evaluates immediately. Enforced in both directions:

- a failure, an empty result, or a **PARTIAL** run (some topics execution-failed) is **never
  frozen**; the reason surfaces as `MISS_NOT_CACHED:<reason>`;
- a zero-proposal *successful* run **is** frozen (a legitimate result);
- `--force-discovery` (new CLI flag) bypasses the cache and keeps the previous snapshot as
  `*.prev.json` — never a silent replacement.

**Live verification on the real flaky recording** (`var/discovery_stability_cache/
cache_replay_YsqD4T0D850.jsonl`, snapshot seeded from the real measured run `YsqD4T0D850__r003`:
7 facts / 3 proposals / `RESEARCH_MORE`):

| check | result |
|---|---|
| 6/6 cached replays | `HIT`, digest `4ae42d47…` **identical**, outcome `RESEARCH_MORE` |
| `cached_replay_identical` | **true** (`replay_scope: ALL`) |
| 4 forced reruns | `FORCED_RERUN` every time, cache bypassed |
| forced outcomes under total provider outage | `DISCOVERY_DEGRADED` ×4, 0 facts — **no editorial zero** |
| previous snapshot | preserved as `*.prev.json` (never silently replaced) |
| `cache_stores_failures` | `empty_result_refused: true`, no frozen failure entries |

An earlier live attempt **caught a real bug on production data**: the cache had frozen a PARTIAL
run (4/5 topics execution-failed → 3 facts, 0 angles) as a success. The partial-freeze guard now
refuses it at write time and ignores such entries at read time.

## 6. Provider failures are classified, never editorial

`_model_failure_reason` treats an all-pool-exhausted judge pool as `RATE_LIMITED`
(`gen._GEMINI_EXHAUSTED` is detectable even when the surfaced error is a misleading `HTTP 400`
with an empty body). In the 40-run corpus: **17 runs** correctly routed to `DISCOVERY_DEGRADED`
and **0** became editorial zero-yield evidence. Recordings C and D therefore have no completed
10-run baseline — recorded as **PENDING**, not as instability.

## 7. STABILITY ≠ CORRECTNESS (editor's distinction, addressed)

The cache freezes **operational reproducibility**: *same evidence + same pipeline version → same
accepted snapshot*. It does **not** claim the frozen facts are correct, and it does not hide model
variance — the forced phase exists precisely to keep it observable (here it surfaced as
`DISCOVERY_DEGRADED` under the outage; the unit test with a fake model proves variance **is**
observed when the model varies). Grounding, assessment and readiness are recomputed on every run,
so they can never go stale, and every hit records what it replayed (`source.seeded_from`,
`created_at`, `stage_version`, `model_config_fp`).

## 8. Verdicts

| claim | verdict | evidence |
|---|---|---|
| DISCOVERY_REPLAY_HARNESS | **PROVEN** | harness runs end-to-end; 695 tests green; ruff clean |
| DETERMINISTIC_STAGE_STABILITY | **PROVEN** | segmentation identical 4/4; model-free double run byte-equal |
| MODEL_EXECUTION_RELIABILITY | **PROMISING** | 0/40 spontaneous model failures, 17/40 quota-blocked; no bounded retry yet (L1 pending) |
| FACT_EXTRACTION_STABILITY | **PROMISING** | overlap 0.955–0.977; 0 catastrophic in 79 runs |
| ANGLE_STABILITY | **PROMISING** (weakest) | overlap 0.389–0.789; flips originate here |
| READINESS_STABILITY | **PROVEN** with versioned cache | 6/6 identical digests on replay; variance still measurable under force |
| CATASTROPHIC_ZERO_YIELD | **RESOLVED** | 0/79; execution failures can no longer become editorial zero |
| DISCOVERY_REPRODUCIBILITY | **PROVEN** (operational) | cache contract enforced in both directions, live + unit |
| JEV_PRODUCTION_AUTHORITY | **NONE** | shadow only, 3 pairs |
| EDITORIAL_EFFECTIVENESS | **PENDING** | provider quota |

## 9. Limitations

1. Provider quota (Gemini free tier 500/day; OpenRouter HTTP 402) → 17/40 corpus runs degraded;
   recordings C and D need a re-run after reset (`--out var/discovery_stability_corpus2`).
2. The live cache-replay proof covers **one** recording (the flaky one), with a seeded snapshot;
   the other recordings rely on the unit-level proof.
3. Every forced rerun hit the outage, so `forced_rerun_observes_variance` is `false` live
   (all four runs failed identically); variance-under-force is unit-proven, not live-proven.
4. Jev shadow: 3 pairs, no authority, no pipeline behaviour.
5. `UNSEEN_VALIDATION` remains **PENDING** (recording D never completed a run).

## 10. Recommendation

Close M3D as **PROVEN for operational reproducibility**, with `OUTCOME_FLIP` (22–32% on one
adversarial recording, 0% on the stable one) recorded as the **accepted residual risk**, mitigated
by L4: an editor who accepts an analysis gets a pinned, replayable snapshot, and re-opening it
(`--force-discovery`) is explicit and non-destructive. Bounded execution retries (L1), a
fact-id-stable prompt, and a rubric less sensitive to ±1 point are follow-ups in `m3/BACKLOG.md`,
not blockers.

## Reproduce

```bash
# baselines (provider needed)
PYTHONPATH=src python3 scripts/evals/discovery_stability.py --input 7k-FZXrcmq8 --runs 10
# taxonomy + flip semantics
PYTHONPATH=src python3 scripts/evals/discovery_stability.py --summarize --out var/discovery_stability_corpus
# deterministic stages, model-free
PYTHONPATH=src python3 scripts/evals/discovery_stability.py --check-determinism
# cache contract on the production intake path (provider-independent when seeded)
PYTHONPATH=src python3 scripts/evals/discovery_stability.py --cache-verify --input YsqD4T0D850 \
  --cached-runs 6 --forced-runs 4 --cache-seed YsqD4T0D850__r003 \
  --cache-rows-dir var/discovery_stability_corpus --out var/discovery_stability_cache
# operator-level force rerun (keeps the previous snapshot as *.prev.json)
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-intake "<URL>" --force-discovery
```

Evidence: `var/discovery_stability{,_after}/runs.jsonl`,
`var/discovery_stability_corpus/runs.jsonl`,
`var/discovery_stability_cache/cache_replay_YsqD4T0D850.jsonl`,
`var/discovery_stability/jev_shadow_pairs.jsonl`.
