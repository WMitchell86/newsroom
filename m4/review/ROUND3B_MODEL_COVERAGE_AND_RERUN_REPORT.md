# ROUND 3B — model coverage and rerun report

- Date: 2026-09-24 (Europe/Sofia)
- Baseline: `75d9add8aad0a0009895e74552c16671a3092854`
- Scope: privacy simplification, eval-only candidate override, corrected story fixture, fresh-quota execution discipline, bounded OpenRouter free qualification, full verification.
- Production policy diff: `config/model_policy.default.json` adds only `global.privacy_gate_enabled: false`; no route was added, removed, reordered, promoted, or made paid. `var/model_policy.json` was not modified.

## 1. Why Gemini 3.5 Flash / Gemini 3 Flash were missed

ROUND 3 sourced candidates from each role's configured production routes.
`gemini-3.5-flash` and `gemini-3-flash` were absent from the story/angle/draft
production routes, so the harness never selected or attempted them. This is a
selection/configuration fact, not provider quota failure.

The current Gemini catalog contains `gemini-3.5-flash` and
`gemini-3-flash-preview`; exact `gemini-3-flash` is not present. ROUND 3B added
an eval-only override so these exact candidates can be compared without policy
mutation. One runtime probe was successful for `gemini-3.5-flash` and one for
`gemini-3-flash-preview`; no broad Gemini benchmark was run in this completion.

## 2. Candidate coverage and availability

### Configured / catalog-valid

- Gemini: `gemini-3.5-flash`, `gemini-3-flash-preview`, `gemini-3.6-flash`, `gemini-3.7-flash`, `gemini-3.8-flash` — catalog-valid at validation time.
- OpenRouter free: `nvidia/nemotron-3.5-lightning:free`, `google/gemma-4-31b-it:free`, `qwen/qwen3.8-27b:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `thinkingmachines/inkling:free` — catalog-valid at validation time.
- OpenRouter paid references: `openai/gpt-5.6-luna` and `openai/gpt-5.6-luna-pro` — catalog-valid and paid; not called in ROUND 3B.

### ROUND 3B runtime availability

| Model | Catalog | Runtime classification | Consequence |
|---|---|---|---|
| `gemini-3.5-flash` | CATALOG_VALID | RUNTIME_AVAILABLE (one probe) | eligible for follow-up |
| `gemini-3-flash-preview` | CATALOG_VALID | RUNTIME_AVAILABLE (one probe) | eligible for follow-up |
| `gemini-3.6-flash` | CATALOG_VALID | DEFERRED_QUOTA from prior provider response | not retried today |
| `gemini-3.7-flash` | CATALOG_VALID | DEFERRED_QUOTA from prior provider response | not retried today |
| `gemini-3.8-flash` | CATALOG_VALID | DEFERRED_QUOTA from prior provider response | not retried today |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | CATALOG_VALID | RUNTIME_AVAILABLE | qualified candidate below |
| `google/gemma-4-31b-it:free` | CATALOG_VALID | RATE_LIMITED | infra, no repeat |
| `qwen/qwen3.8-27b:free` | CATALOG_VALID | RATE_LIMITED | infra, no repeat |
| `thinkingmachines/inkling:free` | CATALOG_VALID | AUTH_FAILED for this account | infra, no repeat |
| `nvidia/nemotron-3.5-lightning:free` | CATALOG_VALID | TEMP_UNAVAILABLE in bounded probe | infra, no repeat |

### Story

Candidate: `EVAL_ONLY openrouter:nvidia/nemotron-3-ultra-550b-a55b:free`.

- 6 corrected production-shaped cases; 6 answers; 5 valid; 5 correct.
- False merges: **0** (primary safety metric).
- False developments: **0**.
- Median latency: 12,516 ms.
- Verdict: **PROMISING**, not promoted automatically.
- The earlier same-decision fixture issue is corrected: the origin publication now has a bounded summary and the publication title describes the same decision. The fixture relation remains `SAME_STORY`.

### Angle

The bounded Nemotron Ultra run did not complete within the 180-second harness budget. It is therefore **NOT_EVALUATED_INFRA**, not a quality verdict. The harness now reports seed/adjudicated-style metrics separately from the seven M3D disagreement rows, with deterministic labels identified as baselines rather than human-adjudicated ground truth. No angle role is promoted.

### Draft

Candidate: `EVAL_ONLY openrouter:nvidia/nemotron-3-ultra-550b-a55b:free`.

- 3 frozen EvidencePackets; 3 valid JSON answers; 2/3 deterministic factual coverage; 0 invented numbers; 0 invented-name hits; 6 unsupported sentences; 2 originality warnings; median latency 63,416 ms.
- Bulgarian naturalness, headline quality, Chernomorie fit and editing effort remain **PENDING_HUMAN_REVIEW**. The blinded sheet is `m4/review/ROUND3B_draft_human_review.md`.
- Verdict: **PENDING_HUMAN_REVIEW**, not promoted.

## 4. Paid cost / quota honesty

- Paid model calls in ROUND 3B: **0**.
- Paid cost in ROUND 3B: **$0.00** (no paid candidate was run).
- The local ledger is application-local only. Its configured Gemini 20-RPD guard is not the provider's remaining quota; provider 429/exhaustion response is authoritative. 3.6/3.7/3.8 were not retried after exhaustion.
- OpenRouter free endpoint failures are reported as runtime availability, not as model quality.

## 5. Safety and policy result

Implemented:

- `global.privacy_gate_enabled` default `false`; `public_only` remains visible and auditable. ON preserves the old block; OFF permits a free OpenRouter route for private editorial payloads in this project.
- Billing, `paid_enabled`, soft paid budget, usage accounting, route ordering, and production policy routes are unchanged.
- Legacy OpenRouter env substitutions are reclassified paid-safe instead of inheriting stale billing.
- Eval-only exact candidates are in-memory derived routes, marked `EVAL_ONLY`, never write `var/model_policy.json`, require explicit OpenRouter billing, and require `--allow-paid` for paid candidates.
- API keys and credentials remain transport headers/environment secrets and are not inserted into prompts or usage artifacts.

**Policy change:** only the requested project privacy switch was added to the tracked defaults. **No model-route promotion or reorder was evidence-backed.**

## 6. Required final block

```text
JUDGE_PRIMARY = gemini-3.5-flash-lite (accepted ROUND 3 baseline)
JUDGE_CROSS_PROVIDER_FREE_FALLBACK = NOT_QUALIFIED_IN_ROUND3B
STORY_PRIMARY = NOT_FILLED
STORY_FALLBACK = openrouter:nvidia/nemotron-3-ultra-550b-a55b:free (PROMISING, not promoted)
ANGLE_PRIMARY = NOT_FILLED
ANGLE_FALLBACK = NOT_FILLED
DRAFT_MODEL_PROMOTION = PENDING_HUMAN_REVIEW
```

## 7. Verification

- `PYTHONPATH=src python3 -m pytest -q --disable-warnings`: **991 passed**.
- `ruff check src tests scripts`: **PASS**.
- `ruff format --check src tests scripts`: **PASS**.
- `PYTHONPATH=src python3 scripts/m3a_smoke.py`: **25/25 PASS**.
- `PYTHONPATH=src python3 scripts/ui_proof.py`: **56/56 PASS**.
- `PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models validate`: **all configured routes catalog-valid at check time**.
- `PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models status`: **PASS**; privacy gate shown as disabled and paid models remain disabled.
- Live qualification artifacts are under ignored `var/round3b/`; this report intentionally contains no prompt bodies, keys, cookies, or credentials.

STOP — this round is complete. Missing Gemini comparisons may be run as a small follow-up after quota reset; no UX/product redesign was started.
