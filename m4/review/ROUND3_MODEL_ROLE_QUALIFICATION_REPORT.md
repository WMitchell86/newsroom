# ROUND 3 — Live Model Role Qualification (REVIEW → RUN → VERIFY)

- Date: 2026-09-24 (Europe/Sofia)
- Baseline: `9babc4a` (clean; ROUNDS 1–2 accepted; harness engineering PROVEN,
  LIVE_ROLE_QUALIFICATION was PENDING)
- Scope: bounded live qualification of `judge`, `story`, `angle`, `draft`.
  `research` NOT_IMPLEMENTED (no production caller), `extract`/`utility`
  NOT_EVALUATED (no fixture) — reported, not fabricated.
- Operator decisions this round (in-chat): **paid reference candidates
  approved** (GPT-5.6 Luna / Luna Pro); **draft fixture of 3 frozen packets
  accepted** (5–10 suggested; honest fixture-size note below).
- Harness: `scripts/evals/model_role_eval.py` (production contracts; candidates
  from the role's own policy routes; `--allow-paid` guard; human draft-review
  sheet). Bounded subsets were run through the same harness with an
  EVAL-ONLY derived single-route policy per candidate; `var/model_policy.json`
  was never modified (PART K).

## 1. Pre-run inventory (PART A)

Policy `216d8e848f58` · `paid_enabled=false` · local usage at start: 0 rows
today. Catalog validation (PART C): **all 33 configured routes [OK]** against
live catalogs (Gemini models.list 44 ids; OpenRouter /models 458 ids) — no
MODEL_UNAVAILABLE anywhere.

| Role | Route order (provider:model, billing) | public_only | daily limit (local) | Eligible for eval |
|---|---|---|---|---|
| judge (private) | 1. gemini-3.5-flash-lite (op-decl) 2. gemini-3.1-flash-lite 3. nemotron-3.5-lightning:free (free) 4. gemma-4-31b-it:free (free) 5. gpt-5.6-luna (paid) | free=yes | 500/500 per Lite | Lites ✓; free OR routes **POLICY_BLOCKED** (private payload vs public_only — privacy contract, ROUND 1); luna paid-guard |
| story (public) | 1. gemini-3.8-flash 2. gemini-3.7-flash 3. gemini-3.6-flash (op-decl, 20 RPD) 4. nemotron-3-ultra:free 5. qwen3.8-27b:free (free) 6. gpt-5.6-luna-pro 7. gpt-5.6-luna (paid) | free=yes | 20 per Flash | all free routes eligible (public payload) |
| angle (private) | 1. gemini-3.8-flash 2. gemini-3.7-flash 3. gemini-3.6-flash 4. gpt-5.6-luna-pro 5. gpt-5.6-luna | — | 20 per Flash; soft 20/hard 30 role | Flash routes; OR free structurally absent |
| draft (private) | 1. gemini-3.8-flash 2. gemini-3.7-flash (**disabled in var policy**) 3. gemini-3.6-flash 4. gpt-5.6-luna | — | 20 per Flash | 3.8, 3.6 (+3.7 disabled) |

Paid candidates used (operator-approved): `gpt-5.6-luna` (judge, angle, draft),
`gpt-5.6-luna-pro` (story). Free/paid classification sane; Luna ids are priced
in the catalog probe ($0.20/M in, $1.20/M out).

### Quota strategy respected (PART B)

Lite families = high-volume pool (500 RPD), Flash 3.x = small independent
quality pools (20 RPD each), named OpenRouter free ids = second line, Luna =
paid reference. No artificial global Gemini budget imposed; no GPT-5.4; all
OpenRouter candidates are named ids.

## 2. Judge results (PART D)

Fixture: 6 fact-entailment cases (production `render_entail_prompt` +
`parse_entail_answer`); `draft_semantic` subtype stays PENDING_NO_FIXTURE.

| Candidate | Pass | Answers | Valid | Correct | False positives | Median latency |
|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | **PASS** | 6/6 | 6 | 6 | **0** | 24 603 ms |
| gemini-3.1-flash-lite | **PASS** | 6/6 | 6 | 6 | **0** | 6 314 ms |
| gpt-5.6-luna (paid ref) | **PASS** | 6/6 | 6 | 6 | 0 | 2 272 ms |

Stability (hard cases `negation-sensitive`, `actor-swap`, `date-mismatch`,
two extra passes): both Lites **3/3 in both passes** — no flips. Verdict per
PART I: structured output reliable, zero unsafe false positives, no grounding
weakness observed.

## 3. Story results (PART E)

Fixture: 6 cases (production `render_prompt` + `parse_relation`). Primary
metric: **false merges**.

| Candidate | Verdict | Answers | Valid | Correct | False merges | False developments | Median |
|---|---|---|---|---|---|---|---|
| gemini-3.8-flash | **DAILY_QUOTA_EXHAUSTED (infra)** | 2/6 | 2 | 1 | 0 | 1 | 15 893 ms |
| gemini-3.7-flash | REJECT (false development) | 1/6 | 1 | 0 | 0 | 1 | 38 178 ms |
| gemini-3.6-flash | REJECT (false development) | 6/6 | 5 | 4 | 0 | 1 | 5 044 ms |
| nemotron-3-ultra:free | WEAK (validity-unstable) | 6/6 | 4 · 2 (rerun) | 4 · 2 | **0** | 0 | 27 851 ms |
| qwen3.8-27b:free | **NOT_EVALUATED (RATE_LIMITED)** | 0/6 | 0 | 0 | 0 | 0 | — |
| gpt-5.6-luna-pro (paid ref) | REJECT (false development) | 6/6 | 5 | 4 | 0 | 1 | 5 597 ms |

Zero false merges across every candidate. The recurring error is the same on
3.6-flash, Luna Pro and (first case) 3.8-flash:
`same-decision-two-outlets` → NEW_DEVELOPMENT instead of SAME_STORY. Fixture
note: this row and `related-background-same-program` carry publication
**titles only** (no summaries), harder than the production `build_context`
shape that normally feeds relation prompts. Nemotron never merged and never
invented developments — the safe direction — but its relation-JSON validity is
unreliable (4/6 → 2/6 across passes).

**Role outcome: no candidate passes cleanly on this fixture.** 3.6-flash is
the best available (5/6 valid, 4/6 correct, fast, safe direction), but the
single false development + the fixture ambiguity means story primary/fallback
cannot be declared on today's evidence.

## 4. Angle results (PART F)

Fixture: 11 cases (4 seed + 7 M3D transcript disagreements; production
seven-criterion assess prompt + production parser/validation).

| Candidate | Verdict | Answers | Valid | Correct | False positives (routine→PUBLISHABLE) | Median |
|---|---|---|---|---|---|---|
| gemini-3.6-flash | WEAK (incomplete run) | 8/11 | 8 | 4 | **0** | 5 428 ms |
| gemini-3.7-flash | **NOT_EVALUATED (pool exhausted)** | 0/11 | 0 | 0 | 0 | — |
| gpt-5.6-luna (paid ref) | WEAK (incomplete run) | 8/11 | 7 | 3 | **0** | 6 784 ms |

- **Zero false positives** for both: no routine material was ever called
  publishable; all four seed cases read correctly by 3.6-flash.
- Transcript (m3d) cases: both models over-call NEEDS_RESEARCH on
  NO_PUBLISHABLE_ANGLE transcripts (3.6: 2 of 5 wrong there; Luna: 3 of 5
  wrong, plus 1 parser-rejected answer). Adjudication on transcripts is weak
  for both — matches the M3D lesson.
- Runs incomplete (3 cases each unanswered): role hard cap (30) and Flash pool
  exhaustion — infrastructure, not quality.
- Hard-case stability repeats were **not** spendable: by the time both Flash
  pools were exhausted (shared per-model, per-key buckets), the remaining
  eligible candidate was the paid one; burning paid calls on repeats was not
  justified by an already-inconclusive free picture.

**Role outcome: no pass.** 3.6-flash is the strongest available candidate
(zero FP, correct seed judgments) but the transcript instability and the
incomplete run block a PRIMARY/FALLBACK claim today.

## 5. Draft — automatic results (PART G)

Fixture: 3 frozen EvidencePackets (accepted size), real Site DNA / VOICE_HOUSE /
MODE_STANDARD_NEWS / 3 hydrated style examples, production
`build_prompt`/`parse_draft_json`/`audit_claims`/`originality_check`.

| Candidate | Answers | Valid JSON | Invented numbers | Originality warnings | Semantic gate (paid judge) |
|---|---|---|---|---|---|
| gemini-3.6-flash | 0/3 — **health-skipped** (pool exhausted) | — | — | — | NOT_RUN |
| gpt-5.6-luna (paid ref) | 3/3 | 3 | **0** | 2 of 3 (REVIEW) | 1 PASS / 2 not better |

Per-case (Luna): `free-medical-cabinet` — no invented numbers, 0 unsupported,
originality REVIEW, "1 октомври" written as "1-ви октомври" (checker inflection
limit, not a fact error); `tax-increase` — all required facts, 1 unsupported
sentence; `budget-adopted` — "18 милиона" written as "18 млн." (same checker
inflection limit), 1 unsupported sentence, originality REVIEW. Zero style-leak
hits anywhere.

**The Gemini draft pool was already provider-exhausted when the draft run
started (the same 20-RPD pools consumed by story/angle evals + operator's
direct AI Studio usage), so no free draft quality signal exists this round.**
The one eligible current-policy free candidate could not be tested.

## 6. Human review artifact (PART G)

- Location: `m4/review/ROUND3_draft_human_review.md`
  (copy of `var/model_role_eval/round3/draft__r1/openai_gpt-5.6-luna/draft_human_review.md`).
- Contains the 3 Luna drafts with automatic checks printed and the fields
  `Bulgarian naturalness / headline quality / Chernomorie fit / editing needed /
  notes` **blank on purpose**.
- No ratings were filled by the assistant and no LLM was used to judge the
  Bulgarian prose. Human verdict pending → see §7.

## 7. Qualification verdict (PART H/I)

```text
JUDGE_PRIMARY   = gemini-3.1-flash-lite   (6/6 + 3/3 + 3/3, 0 FP, 6.3 s median, 500-RPD pool)
JUDGE_FALLBACK  = gemini-3.5-flash-lite   (identical quality, slower median)
  (gpt-5.6-luna stays the last paid reference in the policy; NOT promoted)

STORY_PRIMARY   = NOT_DECLARED — no candidate passes on today's fixture
STORY_FALLBACK  = NOT_DECLARED — best available: gemini-3.6-flash (safe direction,
                  1 false development, fixture ambiguity unresolved);
                  nemotron-3-ultra:free = JSON-validity-unstable, not promotable

ANGLE_PRIMARY   = NOT_DECLARED — 3.6-flash promising (0 FP, seed-correct) but
                  transcript instability + incomplete run
ANGLE_FALLBACK  = NOT_DECLARED

DRAFT_MODEL_PROMOTION = PENDING_HUMAN_REVIEW
  (only Luna produced drafts; 0 invented numbers, 2 originality REVIEWs;
   the human sheet is unanswered — the promotion rule stays human)

extract  = NOT_EVALUATED (no fixture)
utility  = NOT_EVALUATED (no fixture)
research = NOT_IMPLEMENTED (no production caller)
```

## 8. Cost / usage (PART J/L)

| Metric | Value |
|---|---|
| Ledger rows today (end of round) | 126 (78 OK / 10 failed / 38 skipped) |
| Free provider attempts (OK rows, Gemini+OpenRouter free) | 55 |
| Paid rows (luna / luna-pro) | 32 rows, 23 OK provider attempts |
| Paid cost (ledger-estimated) | **$0.00** (short outputs; far below the $2.00 soft budget; catalog list price cap ≈ $0.01) |
| Fallback steps inside eval calls | 0 (each eval ran a single-route policy) |
| Role hard cap reached | angle (30) — last 3 Luna rows ROLE_HARD_BUDGET |

Failure classification (PART L — infra ≠ quality):

| Class | Who | Consequence |
|---|---|---|
| DAILY_QUOTA_EXHAUSTED | gemini-3.8-flash (after 2 OK), gemini-3.7-flash (before angle), gemini-3.6-flash (mid-angle, mid-draft) | story 3.8 → NOT_EVALUATED for quality; angle 3.7 → NOT_EVALUATED; angle 3.6 = incomplete run; draft free = NOT_RUN |
| RATE_LIMITED | qwen3.8-27b:free (story, twice) | NOT_EVALUATED; no further retries burned |
| ROLE_HARD_BUDGET | angle hard cap 30 | 3 Luna cases unanswered |
| INVALID_JSON | nemotron (2–4 rows/pass), Luna 1 parser reject | counted in quality, not infra |
| MODEL_UNAVAILABLE | none (33/33 catalog-valid) | — |
| POLICY_BLOCKED | judge/angle vs free OR routes (privacy) | structural, documented since ROUND 1 |
| PAID_GUARD | first judge Luna attempt (router paid gate) | resolved: operator approval + eval-only paid_enabled |

**Operator-relevant quota finding:** the 20-RPD local declarations for the
Flash models undercount real consumption — the provider returned 429s while
the local ledger still showed 6–15/20. Bucket usage outside this codebase
(direct AI Studio runs or another checkout sharing the key) is invisible to
the tracker. Reconcile the declared `daily_call_limit` values with real
AI Studio quotas, or expect provider-429 skips before the local guardrail.

## 9. Policy change (PART K)

**NO_POLICY_CHANGE.** Story and angle produced no passing candidate (fixture
ambiguity + infrastructure exhaustion), so no route reorder is
evidence-backed today. Judge order is already correct (Lite first, quality
equal, cheaper pool). Draft waits on the human review sheet and on a day when
the Flash pools have quota. Budgets were not tuned (no eval proved a cap
blocks a valid normal run).

## 10. Verification (PART N)

No production code changed and no policy changed this round (repo stayed at
`9babc4a`; eval artifacts live in git-ignored `var/`). Per PART N:

- targeted eval tests: `tests/test_model_role_eval.py` → **25 passed**
- policy validation: `newsroom models validate` → 33/33 routes OK (live catalogs)
- `newsroom models status` → consistent with the ledger (§8)
- full pytest/ruff/smoke/ui_proof: not required by PART N (nothing changed);
  full suite state at round start: 985 passed, ruff clean, smoke 25/25,
  ui_proof 56/56.

## 11. Next-round candidates (evidence-backed, NOT started)

1. Add summaries to the two ambiguous story fixture rows (or re-adjudicate
   `same-decision-two-outlets`) and rerun story with fresh Flash pools.
2. Complete the angle run (fresh pools; finish the 3 unanswered cases;
   hard-case stability ×3 on `m3d-*`).
3. Run draft on 3.6/3.7 when pools reset; then the human review sheet decides
   DRAFT_MODEL_PROMOTION.
4. Reconcile the declared Flash `daily_call_limit`s with real AI Studio quotas.

STOP — awaiting ROUND 3 review before UX/product redesign.
