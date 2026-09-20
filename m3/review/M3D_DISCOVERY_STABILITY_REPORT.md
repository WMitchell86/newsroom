# M3D — Discovery Reproducibility & Stability Report

**Date:** 2026-09-19, closed 2026-09-20 · **Base:** frozen `860f582` + M3D harness commits · **Harness:** `scripts/evals/discovery_stability.py`

> ## FREEZE (2026-09-20) — `YOUTUBE_PIPELINE_V1 = FROZEN / GOOD_ENOUGH`
>
> **This milestone is closed.** Verdict: `DISCOVERY_REPRODUCIBILITY = PROVEN`
> (operational, L4 versioned cache), `ANGLE_STABILITY = PROMISING` (measured as
> model-capacity-sensitive in §12), `OPERATIONAL_REPRODUCIBILITY = PROVEN`.
> `OUTCOME_FLIP` stays recorded as **accepted residual risk**, mitigated by the
> cache: an accepted analysis is pinned and replayable, and re-opening it
> (`--force-discovery`) is explicit and non-destructive.
>
> **YouTube is a secondary source. No further optimization without observed
> production pain** — no `player_client` work, no semantic-variance work, no new
> transcript engine, no `ANGLE_STABILITY = PROVEN` chase. New ideas go to
> `BACKLOG.md`; real use is now the source of truth.
>
> Read §11–§13 for the closing measurements (still-blocked corpus, angle-model
> A/B, final verdicts and what was deliberately not built).

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
| OPERATIONAL_REPRODUCIBILITY | **PROVEN** | versioned L4 cache: 6/6 byte-identical replays; §5, §7 |
| ANGLE_STABILITY | **PROMISING** — model-capacity-sensitive | §12 A/B: 0/4 flips with the strongest model vs 22.2–31.6% with the shipped Lite pool |
| JEV_PRODUCTION_AUTHORITY | **NONE** | shadow only, 3 pairs |
| EDITORIAL_EFFECTIVENESS | **PENDING** | provider quota |
| UNSEEN_VALIDATION | **PENDING** (provider) | judge pool unusable 2026-09-20; §11 |

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
fact-id-stable prompt, and a rubric less sensitive to ±1 point are follow-ups in `BACKLOG.md`,
not blockers.

**Implemented at closure (2026-09-20):** this recommendation was accepted and the milestone is
**frozen**. The remaining open items and the optional stronger-model switch for the angle stage
(§12) live in `BACKLOG.md`, not in a new milestone.

## 11. Closing measurements (2026-09-20): the corpus is still provider-blocked

The two blocked recordings were re-attempted the next day. The free Gemini tier
is **still unusable for a 10-run baseline**, >10 h after the M3D measurement:

| attempt | pacing | result |
|---|---|---|
| `b13U-N_Vk9c` run 1 (5 s default) | 5 s | 135 s, 1 fact / 11 `MODEL_CALL_FAILED` → `UNKNOWN` |
| `b13U-N_Vk9c` run 2 | 5 s | 120 s, 0 facts / 12 `MODEL_CALL_FAILED` → `DISCOVERY_DEGRADED` |
| `b13U-N_Vk9c` run 1 (12 s) | 12 s | 300 s, 0 facts / 12 `MODEL_CALL_FAILED` → `DISCOVERY_DEGRADED` |

Pacing is not the fix, so the earlier hypothesis (self-inflicted RPM 429s) is
disproved for this failure mode. Live per-model probe (2026-09-20 05:40 UTC):

```text
judge pool (the discovery chain runs ENTIRELY on it):
  gemini-2.5-flash-lite        HTTP 404 (empty body)
  gemini-3.1-flash-lite        HTTP 429
  gemini-3.1-flash-lite-preview HTTP 429
  gemini-flash-lite-latest     HTTP 400 (empty body)
draft pool: first live bucket = gemini-3.6-flash (2.5 / 3 / 3.5 exhausted)
```

Because fact extraction, angle proposals **and** the grounding judge all sit in
the judge pool, a run needs 12+ judge calls: the free tier cannot carry a
corpus. Recordings C and D therefore still have **no completed baseline** and
`UNSEEN_VALIDATION` stays **PENDING** (§9.1) — a provider limit, not a finding
about the pipeline. All blocked rows are preserved (never deleted) as
`var/discovery_stability_corpus2/runs.blocked_2026-09-20.jsonl` +
`runs.degraded.jsonl`; the corpus runner stays resumable.

**Real bug found and fixed while wiring this (no test existed):**
`generate._call_openrouter` parsed OpenAI-style SSE frames (`data: {...}`) but
never sent `"stream": true`. OpenRouter therefore answered with a single JSON
object, no frame started with `data:`, and **every OpenRouter call — the whole
fallback provider path — silently returned an empty completion**. Fixed by
requesting streaming explicitly plus a non-streaming body fallback;
`tests/test_openrouter_transport.py` (5 offline tests) now covers it.
Suite 695 → **700 passed**, ruff clean.

## 12. Angle-layer model A/B — the only model research admitted

**Question (editor's hypothesis):** divergence starts at angle proposal, not at
parsing/segmentation/grounding, so a stronger model on that one stage should
remove the flips.

**Method** (`scripts/evals/angle_model_ab.py`): the fact set is **pinned** to the
real measured run `YsqD4T0D850__r003` (7 facts, `RESEARCH_MORE`) and passed to the
harness as `facts_override`, so the *only* variable is the model that writes the
propositions. The downstream gate (deterministic `assess_candidates` +
`assess_angles` + `run_readiness`) is the production one, untouched. Same
recording, same evidence, N runs per arm.

| arm | model | usable runs | outcomes | OUTCOME_FLIP vs first | proposition overlap (mean) | cited facts |
|---|---|---|---|---|---|---|
| prod-lite (§3 corpus, same recording, uncached) | Gemini judge pool (Lite) | 39 | `RESEARCH_MORE` / `NO_PUBLISHABLE_ANGLE` | **22.2–31.6%** | 0.741–0.789 | — |
| **luna-5.6** | `openai/gpt-5.6-luna-pro` (paid, authorised) | **5/5** | `RESEARCH_MORE` ×5 | **0/4 (0%)** | **1.00** | 1.6 (1–3) |
| free | `qwen/qwen3.8-27b:free` | **not measurable** | — | — | — | — |

**Answer: yes — on this recording the flip is model-capacity-driven.** The
shipped Lite config flips on ~1 in 4 replays of identical evidence; the strongest
available model produced **zero flips in 5 runs**, with a tighter proposition set
(overlap 1.00 vs 0.74–0.79). The cited-fact counts still vary (1–3), which is the
same mechanism the flip rides on — but the variation stayed on one side of the
threshold.

Caveats, stated up front: **n=5** (a 30-minute diagnostic, not a milestone), and
the arms differ in **provider and capacity**, so this answers *"can a stronger
model eliminate the flips?"*, not *"is model X better than model Y at equal
capacity"*.

**Why there is no free-model arm:** the shared free tier on OpenRouter could not
be measured in the diagnostic window — upstream 429s plus multi-minute stalls
(one run: 293 s, 0 proposals, no exception raised), retried with a 45 s backoff
and still not converging. It is recorded as **not measured**, never as a result.
The low-capacity reference is therefore the **shipped Lite pool over 39 corpus
runs on the same recording** — a stronger reference than 5 free-tier runs would
have been. `var/angle_model_ab/` is git-ignored.

**What this does NOT authorise:** rewiring the pipeline now. The freeze stands.
The measured switch is a one-knob change (run the angle stage on a stronger model
pool), recorded in `BACKLOG.md` and to be pulled **only if real production use
shows the flip hurting the editor**. That is the editor's explicit rule.

**Cost/permission note:** `openai/gpt-5.6-luna-pro` is **paid** and was used once,
explicitly authorised by the repo owner for this diagnostic; the production
guard (`_OPENROUTER_PAID_FORBIDDEN`) is unchanged and the script requires
`--allow-paid`. Also: the id documented earlier as `openai/gpt-luna-5.6` **does
not exist** in the OpenRouter catalog — the real ids are `openai/gpt-5.6-luna`,
`openai/gpt-5.6-luna-pro` and `~openai/gpt-luna-latest`; the docs were corrected.

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
