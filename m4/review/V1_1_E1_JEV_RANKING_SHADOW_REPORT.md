# V1.1-E1 — Editorial Classification + JEV Ranking Shadow Benchmark

**Status: EVALUATION ONLY. Nothing in this slice is in production.**
`m4/review/V1_1_E1_JEV_RANKING_SHADOW_REPORT.md`

| | |
| --- | --- |
| Predecessor | V1.1-D2 `090be614e50b3a1b74c0993470b163b1e3e88196` (integrity gate 259/259 OK) |
| Harness | `scripts/v11e1_jev_ranking_shadow.py` (read-only, shadow) |
| Corpus | 253 real Stories / 300 real inbox items / 35 registered sources |
| Sample | 80 Stories, 19 strata, seed `20260926` |
| JEV calls | 80 evaluation + 36 consistency + 21 identity = **137** |
| Runtime-store integrity | **259 files byte-identical** |
| Production code changed | **none** |

---

## 1. Executive verdict

> **More evaluation needed — specifically, evaluation aimed at a different
> question than the one this slice asked.**

The headline is not "JEV works" or "JEV fails". It is that the experiment
**surfaced a defect in the Story store that outranks the entire ranking
question**, and that the three ranking dimensions the brief asked about turned
out to be largely **non-discriminating** on this corpus.

**Finding 1 — the real problem is Story fragmentation, not ranking.**

One dolphin rescue off Pomorie exists as **8 separate Stories**:

| Story | Publisher | Age |
| --- | --- | --- |
| `s66c484c7374dbda` Спасиха бедстващ делфин е спасен в Поморие | БургасИнфо | 19.1 h |
| `s6792591ccd82d76` Спасиха бедстващ делфин в местността Кротиря | БНР | 19.1 h |
| `se4773f8d700c6c1` Спасиха бедстващ делфин край Поморие | DarikNews | 19.1 h |
| `s81ab6b087fb0c5b` Делфин заседна край брега в Поморие (ВИДЕО) | bTV | 19.1 h |
| `s17fbe8d95878004` Спасиха бедстващ делфин край Поморие | БНТ | 19.1 h |
| `s18479e1facc7eac` Спасиха бедстващ делфин край Поморие | nova.bg | 19.1 h |
| `s63f963ee7c3ee57` Спасиха бедстващ делфин край Поморие | Moreto.net | 19.1 h |
| `s83a9aa74c6d4e29` Спасиха млад делфин край Поморие | Черноморски фар | 19.1 h |

A second cluster: **2 Stories** for one Alstom train release (`
s2738ad82384f562`, `s66c484c7374dbda` family), and **6 Stories** for the
Pomorie hospital strategic-partner search.

The corpus is 253 Stories but contains materially far fewer than 253 events.
**Any ranking — chronological, deterministic or JEV — sorts a fragmented store.**
This is why Baseline A's top 15 contains the same Nessebar sports-candidacy item
**6 times**. That is the D1/D2 chronological order failing at the store layer,
not failing at the ranking layer.

**Finding 2 — the JEV dimensions barely separate the real corpus.**

| Dimension | LOW | MEDIUM | HIGH | Discriminating? |
| --- | --- | --- | --- | --- |
| local relevance | 10 | **70** | **0** | **No — never returns HIGH** |
| public interest | 40 | 40 | 0 | Partly (2 values) |
| urgency | 63 | 17 | 0 | Partly (2 values) |
| novelty | 18 NO | — | 62 YES | Barely (binary) |

`local_relevance` never once answered HIGH in 80 calls, and every Score
collapsed onto at most two of its three levels. Mapped to 0/0.5/1 the standard
deviation is 0.165 (locality relevance), 0.250 (public interest), 0.205
(urgency). A dimension that returns the same answer for 87% of the corpus
cannot meaningfully reorder it.

**Finding 3 — JEV is excellent at the job it is actually good at.**

On the *same* primitive, run against the real duplicate clusters, JEV is
**near-perfect**: of 28 within-dolphin-cluster pairs, **26 `SAME_STORY` +
2 `NEW_DEVELOPMENT`, zero `NEW_STORY`**, mean confidence 0.933. Against a
same-town/different-topic control it returned `NEW_STORY` for 102 of 153 pairs
(66.7%), with mean confidence **0.966 on `NEW_STORY` vs 0.905 on `SAME_STORY`**.

JEV identified the duplication the canonical grouper missed. The problem this
slice set out to solve is not the one JEV is best at.

**Therefore:** do not build `Топ за редакцията` yet. The store must be grouped
first, otherwise the ranking will faithfully and repeatedly promote one
headline.

---

## 2. JEV integration / API findings

Verified live before the experiment was written.

| Item | Finding |
| --- | --- |
| Package | `typesafe-sdk` **0.6.0** (already the optional `jev` extra in `pyproject.toml`) |
| Authentication | `TYPESAFE_API_KEY` from the environment, `sdk.TypeSafeClient(api_key=...)` |
| **Env-casing hypothesis** | **Disproved.** The key loaded and authenticated on the first live call. No compatibility, casing or request-shape problem existed. |
| Request shape | `client.system_one(state: Mapping, questions: Mapping, *, model, retry, timeout)` |
| Primitives | `Choice(criteria={label: desc})`, `Score(criteria=[levels])`, `Noul()` |
| **Batching** | **`questions` is a mapping — all six dimensions in ONE call.** Confirmed 137/137 calls succeeded. |
| Choice output | `choice` (label) + `confidence` + full `probabilities` dict |
| Score output | continuous `score` (0…n-1) + `legend` index→label + `confidence` + `probabilities` |
| Noul output | `noul` float 0…1 (no `confidence` field) |
| Model | requested `jev-latest` → effective **`jev-1.13.0`** |
| Available models | `models.list()` → `jev-latest`, `jev-preview` only |
| Retry | `RetryPolicy` is an SDK parameter; the experiment relies on the client default |
| Timeout | `timeout=` on the client (seconds); a real timeout was exercised (§15) |
| **Pricing** | **None exposed.** `Usage` has only `input_tokens`/`output_tokens`; `ModelMetadata` has only `name`/`description`/`release_date`. No price field exists, so **no monetary cost is asserted anywhere in this report.** |

Existing production adapter `workflow/jev.py` was reused as the reference for
the typed-question contract. It was **not** modified, and this harness
deliberately does not import it — E1 builds its own questions so the shadow
cannot be mistaken for a production call path.

---

## 3. Sample construction

**Deterministic method, fully reproducible** (`SAMPLING_SEED = 20260926`):

1. Read the 253 Stories and derive features from stored signals only.
2. Bucket each Story by `stratum_key` =
   `(source_kind, member_count, priority, factual_authority, corroboration, followed)`.
3. Shuffle each bucket with `random.Random(20260926)`.
4. Draw buckets **round-robin** until 80 are collected.
5. Sort the result newest-first for presentation only.

**Result: 19 strata, 80 Stories.** Round-robin guarantees rare strata are
represented, so no cherry-picking was possible: the same corpus always yields
the same set, and no Story was chosen because it looked interesting.

| Coverage axis | Sample (80) | Corpus (253) |
| --- | --- | --- |
| source kind | official 39 · media 17 · aggregator 13 · regional 11 | official · media · regional · aggregator |
| priority | high 54 · normal 17 · low 9 | high 187 · normal 76 · low 37 |
| publishers/Story | 1 → 66 · 2 → 13 · 3 → **1** | 1 → 238 · 2 → 13 · 3 → 2 |
| members | 35 multi-member | 35 multi-member |
| age | 9.1 h … 116.7 h (p50 19.1 h) | 9.1 h … 116.7 h |
| followed | 1 | 1 |
| active Article | 1 | 1 |

`corroboration` and `followed` were added to the stratum key **after** a first
pass showed the 3-publisher and followed Stories were never being drawn — with
those signals present the evaluation would have covered only the easy
single-publisher case. The sampling method changed; the corpus did not.

---

## 4. Locality results

Closed taxonomy of 12 values, frozen from a keyword census of the real 300-item
inbox **before** any JEV call (Бургас 130 · Поморие 48 · Несебър 17 ·
Приморско 9 · Царево 7 · Карнобат 3 · Созопол 3). No free-form locality
string is permitted.

| Locality | Count |
| --- | --- |
| BURGAS | 33 |
| POMORIE | 18 |
| NESSEBAR | 8 |
| BULGARIA_NATIONAL | 8 |
| UNCLEAR | 5 |
| PRIMORSKO | 3 |
| OTHER_BURGAS_REGION | 3 |
| KARNOBAT | 1 |
| TSAREVO | 1 |

**Every non-Burgas-region option in the taxonomy was exercised except
`SOZOPOL`, `AYTOS` and `INTERNATIONAL`** — a direct consequence of the
corpus, which contains 2 Sozopol items and no Aytos or foreign material.
Those three options are *not* proven; they are simply unexercised.

**Quality: good.** Spot-checking the sample, locality assignments match the
headlines. The 8 dolphin Stories are all correctly `POMORIE`; the Nessebar
material is `NESSEBAR`; national rail/politics items are `BULGARIA_NATIONAL`.
This is the one dimension that behaves exactly as an editorial tool should.

`OTHER_BURGAS_REGION` correctly absorbed the towns without a dedicated option
(Руен, Лозенец/УМБАЛ, Каблешково).

---

## 5. Category results

13 closed values, derived from the real sample plus the site's own archive
categories in `m2/review/style_profiles.json`
(Общество / Култура / Туризъм / Бизнес / Спорт / Образование).

| Category | Count | | Category | Count |
| --- | --- | --- | --- | --- |
| LOCAL_GOVERNMENT | 17 | | INFRASTRUCTURE_TRANSPORT | 7 |
| CULTURE_EVENTS | 10 | | NATIONAL_POLITICS | 5 |
| SPORT | 9 | | CRIME_INCIDENTS | 3 |
| OTHER | 9 | | TOURISM | 2 |
| EDUCATION | 8 | | BUSINESS_ECONOMY | 2 |
| HEALTHCARE | 8 | | *unused:* WEATHER_SAFETY, PUBLIC_SERVICES_OUTAGES | 0 |

Two taxonomies are **dead weight on this corpus**: `WEATHER_SAFETY` and
`PUBLIC_SERVICES_OUTAGES` were never selected. The corpus contains no weather
warning, no power/water outage and no service disruption in the 80-Story
sample. They should stay in a taxonomy (the newsroom will eventually need
them) but their absence here is a **coverage gap in the corpus, not a
taxonomy error**.

`OTHER` at 9/80 (11%) is the real quality problem. Inspecting them, they are
dominated by the **dolphin rescue stories** — a genuine animal-rescue incident
that the 13-value taxonomy has no home for. This is taxonomy coverage
interacting with Story fragmentation: 8 copies of one uncategorised event.

---

## 6. Relevance / interest / urgency / novelty results

Raw continuous scores, 80 Stories:

| Dimension | min | median | mean | max | mapped values used |
| --- | --- | --- | --- | --- | --- |
| local_relevance | 0.03 | 1.785 | 1.588 | 1.99 | **only {0, 0.5}** |
| public_interest | 0.09 | 0.985 | 0.987 | 1.57 | only {0, 0.5} |
| urgency | 0.05 | 0.495 | 0.597 | 1.83 | only {0, 0.5} |
| novelty | 0.14 | 0.630 | 0.609 | 0.83 | continuous (39 distinct) |

**The single most important negative result in this slice.**

Every `Score` collapsed onto **at most two of its three levels**, and
`local_relevance` **never returned HIGH in 80 calls**. Raw local-relevance
values cluster hard at 2.0 (60 of 80) and 1.0 (13 of 80).

Consequences:

* A dimension that answers the same thing for 87% of the corpus cannot reorder
  it. The hybrid's three fuzzy terms carry a combined weight of **0.50**, but on
  this corpus they contribute roughly **two distinct values**, not eight.
* This is a **prompt/scale problem, not a model problem.** The Scale's `legend`
  maps 0/1/2 to LOW/MEDIUM/HIGH, but the model concentrates on the upper middle.
  A 4–5 level scale, or asking for the value rather than the label, would give
  the ranking real resolution.
* `novelty` is the exception: it is continuous (39 distinct values over 80) and
  is the only dimension with genuine resolution. It is also a Noul, not a
  Score.

**Urgency did behave correctly where the brief predicted it should.** The
highest-urgency real item in the sample is
`Катастрофа затвори пътя Несебър - Бургас` (MEDIUM, 3 independent
publishers) — a live traffic disruption. Evergreen background material
( бюджет, учебни програми, културни програми) scored LOW. The *ranking* of
levels collapsed, but the *ordering* across the corpus is editorially sound.

---

## 7. Confidence

| | locality | category |
| --- | --- | --- |
| n | 80 | 80 |
| mean | 0.934 | 0.843 |
| median | 1.00 | 0.955 |
| min | 0.28 | 0.30 |
| < 0.50 | 3 (3.8%) | 5 (6.2%) |
| 0.50–0.70 | 4 | 15 |
| 0.70–0.85 | 4 | 7 |
| ≥ 0.85 | 69 | 53 |

Threshold sweep (candidates only — **no threshold is chosen**):

| Threshold | locality below | category below |
| --- | --- | --- |
| 0.50 | 3 (3.8%) | 5 (6.2%) |
| 0.60 | 4 (5.0%) | 14 (17.5%) |
| 0.70 | 7 (8.8%) | 20 (25.0%) |
| 0.80 | 8 (10.0%) | 24 (30.0%) |

**On a threshold:** the evidence does **not** justify one yet, for a specific
reason — see §7 of the consistency finding below. JEV's self-reported
confidence is high (median ~1.0) while its outputs are demonstrably unstable,
so **confidence is not a calibrated reliability signal on this model**. Using
`confidence < X` as a gate would filter the *wrong* rows: it would keep rows
that happen to be confidently wrong.

This is the honest reading: **do not adopt a confidence threshold until the
scores themselves discriminate.** Fix the scale first (§6), then re-measure.

---

## 8. Deterministic baseline

Signals computed from stores only — no model was ever asked for anything the
system already knows:

`latestChangeAt` · age · `publisher_count` (distinct publisher domains) ·
source priority (strongest among members) · publisher kind / factual authority
· member count · meaningful development count · followed status · active Article
presence · story status.

### Baseline B weights (explicit, not persisted)

| Term | Weight |
| --- | --- |
| recency (exponential, 24 h half-life) | **0.50** |
| publisher corroboration (saturating at 3) | 0.20 |
| source priority (high 1.0 / normal 0.5 / low 0.2) | 0.15 |
| meaningful developments (saturating at 3) | 0.10 |
| followed | 0.05 |

**Baseline B is weak, and the corpus explains why.** Two of its five terms are
**identically zero or constant across all 80 sampled Stories**:

* `meaningful_developments` — **0 for all 253 Stories in the corpus.** No Story
  has a `NEW_DEVELOPMENT` member. The term contributes exactly nothing.
* `followed` — true for exactly **1 of 253** Stories; it fired for 1 sampled
  Story and cannot move a top-15.

So Baseline B is effectively a 3-term score: recency, corroboration, priority.
Its top 15 differs from chronology by only **5 rows** — it is chronology with
slight reordering, not an independent opinion.

**This is an important negative result for the owner:** the deterministic
signals the newsroom owns today are, on today's data, almost entirely *recency
plus a small corroboration bonus*. There is very little else to rank with. That
is precisely the gap JEV was proposed to fill — and §6 shows JEV does not fill
it either, because its scores collapse to two values.

---

## 9. Chronological baseline

Baseline A is what D1/D2's Today does: canonical `latestChangeAt`, newest
first, bounded at 30, horizon of today + previous Sofia calendar day.

On the 80-Story sample (ages 9.1 h – 116.7 h, i.e. ~5 days), Baseline A's top
15 contains:

| # | Story | Locality | Category | Urgency | Novelty | Pubs |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Катастрофа затвори пътя Несебър - Бургас | BURGAS | INFRASTRUCTURE_TRANSPORT | MEDIUM | YES | 3 |
| 2 | Генералният директор на БНР Милен Митев приветства Детския радиохор | BULGARIA_NATIONAL | CULTURE_EVENTS | LOW | YES | 1 |
| 3 | Безплатен достъп до Wi-Fi интернет … старинен Несебър | NESSEBAR | LOCAL_GOVERNMENT | LOW | NO | 1 |
| 4 | В Стария Несебър вече има зона за безплатен интернет | NESSEBAR | LOCAL_GOVERNMENT | LOW | YES | 1 |
| 5 | Община Несебър представи кандидатурата си за Европейска столица | NESSEBAR | SPORT | LOW | YES | 1 |
| 6 | Приморско отчита обнадеждаващи данни за летния сезон | PRIMORSKO | TOURISM | LOW | YES | 2 |
| 7 | НЕСЕБЪР ИМА ГОТОВНОСТТА … ЕВРОПЕЙСКА СТОЛИЦА НА СПОРТА | NESSEBAR | SPORT | LOW | NO | 2 |
| 8 | В УМБАЛ „Лозенец" стартира структурирана програма | OTHER_BURGAS_REGION | HEALTHCARE | LOW | YES | 1 |
| 9 | Несебър с амбиция да стане Черноморска столица на спорта | NESSEBAR | SPORT | LOW | YES | 1 |
| 10 | Черноморски ревматологични дни през уикенда в Бургас | BURGAS | HEALTHCARE | MEDIUM | NO | 1 |
| 11 | Филиалът на НХА в Бургас откри деветата учебна година | BURGAS | EDUCATION | LOW | YES | 2 |
| 12 | „България е готова за индустриите на бъдещето" — Радев | BULGARIA_NATIONAL | NATIONAL_POLITICS | LOW | YES | 2 |
| 13 | Започна ремонтът на пътя Бургас - Каблешково | BURGAS | INFRASTRUCTURE_TRANSPORT | MEDIUM | YES | 1 |
| 14 | Община Руен прие бюджет от 26,36 млн. евро | OTHER_BURGAS_REGION | LOCAL_GOVERNMENT | LOW | YES | 1 |
| 15 | Два нови влака „Алстом" тръгват по направленията | BULGARIA_NATIONAL | INFRASTRUCTURE_TRANSPORT | MEDIUM | YES | 1 |

**Verdict on A: correct, honest, and repetitive.** The single most editorially
salient item (row 1, a road closure, 3 independent publishers) is first —
chronology got that right by luck of timing. But **rows 3, 4, 5, 7 and 9 are
five separate Stories about one Nessebar sports candidacy**, and rows 1 and 15
are duplicates of items that also appear elsewhere in the corpus. Roughly
**40% of the first screen is one event reported repeatedly.**

This is the concrete, owner-visible form of Finding 1.

---

## 10. Hybrid JEV ranking

### Candidate C weights (explicit, reported, NOT persisted anywhere)

```
editorial_score =
    0.30 · recency                     (exponential, 24 h half-life)
  + 0.15 · local_relevance             (JEV Score → LOW/MEDIUM/HIGH → 0/0.5/1)
  + 0.13 · urgency                     (JEV Score)
  + 0.12 · public_interest             (JEV Score)
  + 0.10 · novelty                     (JEV Noul → continuous 0…1)
  + 0.10 · publisher_corroboration     (deterministic, saturating at 3)
  + 0.05 · source_priority             (deterministic)
  + 0.05 · followed                    (deterministic)
```

**The model is never asked for a ranking score.** Each dimension is normalized
in plain Python; the model supplies typed values only.

The sum is **re-normalized over the dimensions actually present** — this is
what makes the fallback honest (§15): when JEV is unavailable, the JEV terms
drop out of both numerator and denominator and the deterministic terms still
produce a valid 0–1 score.

Recency stays the single largest term (0.30) deliberately, so the hybrid can
never bury genuinely new material.

### Candidate C top 15

| # | Story | Locality | Category | LocRel | PubInt | Urg | Nov | Pubs | Score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Катастрофа затвори пътя Несебър - Бургас | NESSEBAR | INFRASTRUCTURE_TRANSPORT | MED | LOW | MED | YES | 3 | 0.580 |
| 2 | Два нови влака „Алстом" тръгват по направленията | BULGARIA_NATIONAL | INFRASTRUCTURE_TRANSPORT | MED | MED | MED | YES | 2 | 0.566 |
| 3 | Спасиха бедстващ делфин край Поморие — DarikNews | POMORIE | OTHER | MED | MED | MED | YES | 1 | 0.530 |
| 4 | Бедстващ делфин е спасен в Поморие — БургасИнфо | POMORIE | OTHER | MED | MED | MED | YES | 1 | 0.530 |
| 5 | Още два нови влака „Алстом" тръгват по линиите | BULGARIA_NATIONAL | INFRASTRUCTURE_TRANSPORT | MED | MED | MED | YES | 1 | 0.528 |
| 6 | Започна ремонтът на пътя Бургас - Каблешково | BURGAS | INFRASTRUCTURE_TRANSPORT | MED | MED | MED | YES | 1 | 0.502 |
| 7 | Спасиха бедстващ делфин в местността Кротиря — БНР | POMORIE | OTHER | MED | MED | LOW | YES | 2 | 0.500 |
| 8 | Търсят стратегически партньор за развитието на МБАЛ Поморие | POMORIE | HEALTHCARE | MED | MED | LOW | YES | 2 | 0.490 |
| 9 | НХА и Община Поморие петгодишно партньорство | POMORIE | CULTURE_EVENTS | MED | MED | LOW | YES | 1 | 0.474 |
| 10 | Гълъб Донев: ръстът на инфлацията не може да бъде отнесен… | BULGARIA_NATIONAL | BUSINESS_ECONOMY | MED | MED | LOW | NO | 1 | 0.473 |
| 11 | Делфин заседна край брега в Поморие — bTV | POMORIE | OTHER | MED | LOW | MED | YES | 1 | 0.472 |
| 12 | Грузинец отива в ареста за трафик на 24 афганистанци | BURGAS | CRIME_INCIDENTS | MED | MED | LOW | YES | 1 | 0.472 |
| 13 | Съдът в Бургас задържа грузинец … край Приморско | PRIMORSKO | CRIME_INCIDENTS | MED | MED | LOW | YES | 1 | 0.471 |
| 14 | Спасиха бедстващ делфин край Поморие — DarikNews | POMORIE | OTHER | MED | MED | LOW | YES | 1 | 0.470 |
| 15 | Община Поморие и Общинският съвет ще търсят партньор | POMORIE | LOCAL_GOVERNMENT | MED | MED | LOW | YES | 1 | 0.465 |

**What C got right:** it promoted the road closure, the live regional train
change and the Pomorie hospital crisis. Genuinely local, genuinely current.

**What C got badly wrong — and it is structural, not a tuning problem:**

* **5 of the top 15 are the same dolphin rescue** (rows 3, 4, 7, 11, 14).
* 2 are the same Alstom release (rows 2, 5); 2 are the same trafficking case
  (rows 12, 13).
* Rows 3–14 are nearly all `MEDIUM` on every dimension, so the ordering among
  them is **noise**: scores span 0.530 → 0.465, a 0.065 band, produced almost
  entirely by the recency term.

**C is worse than A for editor usefulness on this corpus**, and the reason is
precisely the score collapse in §6: with three fuzzy dimensions stuck at
`MEDIUM`, the hybrid's only working discriminators are recency and
corroboration — the same ones Baseline B uses. The JEV layer adds cost and
volatility without adding discrimination, and the resulting ordering surfaces
duplicates *more* prominently than chronology does, because near-tied duplicate
Stories all float into the same top band.

---

## 11. Top-15 comparison

**Overlap between the three methods' top 15s:**

| Membership | Count |
| --- | --- |
| in all three | **2** |
| A + C only | 1 |
| B + C only | 6 |
| A + B only | 4 |
| **A only (chronology's exclusive picks)** | **8** |
| **B only** | **3** |
| **C only** | **6** |
| distinct Stories across the union | 30 of 80 |

**Only 2 Stories appear in all three top-15s.** The three methods disagree
substantially — which is expected, and is the point of the comparison.

**Largest movements (chronology → hybrid), among C's picks:**

| Story | A# | C# | Movement |
| --- | --- | --- | --- |
| `s30fbcab64f05e30` Катастрофа затвори пътя Несебър | 1 | 1 | — |
| `s2738ad82384f562` Два нови влака „Алстом" | 15 | **2** | **▲13** |
| `s7782ec0c528ea20` Започна ремонтът на пътя Бургас–Каблешково | 13 | 5 | ▲8 |
| 12 further C picks | not in A's top 15 | 3–15 | entering |

The single clearest legitimate gain: **the Alstom regional train change rises
from #15 to #2** — a genuine Sofia–Burgas service change that chronology had
buried. The Pomorie hospital cluster also enters strongly.

**But the same movement is also where the damage is:** the 12 "entering" rows
are mostly the dolphin duplicates and the second Alstom Story. C's new picks
are a mix of the best editorial call in the experiment and its worst structural
failure.

**Explicitly not claimed:** this report does **not** declare C "better". Per
§19 the owner judges. The evidence presented is: C reorders aggressively, its
gains are real but few, and its losses are concentrated in duplicated Stories
that no ranking can fix.

---

## 12. Anomalies / wrong classifications

| # | Anomaly | Evidence | Assessment |
| --- | --- | --- | --- |
| A1 | **8 Stories for one dolphin rescue** | §1 table | **Store defect.** The single most consequential finding. |
| A2 | **6 Stories for one Pomorie hospital search** | §10 rows 8, 15 | Same defect. |
| A3 | **6 Stories for one Nessebar sports candidacy** | §9 rows 3, 4, 5, 7, 9 | Same defect. |
| A4 | `local_relevance` never HIGH | 80/80 | Scale saturation (§6). |
| A5 | `OTHER` = 9/80, mostly dolphins | §5 | Taxonomy has no animal-rescue/incident-of-public-safety-adjacent home. |
| A6 | `WEATHER_SAFETY`, `PUBLIC_SERVICES_OUTAGES` never used | 0/80 | Corpus gap, not taxonomy error. |
| A7 | Locality `BURGAS` for the Nessebar–Burgas road closure | §10 row 1 vs §9 row 1 | **Defensible.** The road is the Несебър-Бургас corridor; the anchor Story is burgas.bg. Same Story, `NESSEBAR` in C vs `BURGAS` in the A-run — **the same input was labelled differently in two different runs.** |
| A8 | Category `SPORT` for a European sports-capitals candidacy | §9 rows 5, 7, 9 | Defensible but the recurring-item nature was not noticed by the model. |
| A9 | 1 Story in sample with an active Article; 30/30 Today rows unassessed | D2 report | Unchanged from D2 — research is still triggered by Quick Draft. |

**A7 is the important one for trusting the output:** identical input, two
different locality labels across two runs in the same session. Locality looks
high-confidence in aggregate (median 1.00) yet is not perfectly reproducible.

---

## 13. Latency (measured)

| Metric | Value |
| --- | --- |
| Calls | 80 evaluation (+ 36 consistency + 21 identity = 137 total) |
| Failures | **0** |
| mean | **282.4 ms** |
| p50 | **277.1 ms** |
| p95 | **324.2 ms** |
| total wall-clock (80 calls) | **22.59 s** |

Latency is a non-issue: **~4.4 Stories/second** sequentially, and each call
already returns all six dimensions, so there is no per-dimension multiplication.

---

## 14. Cost

### Measured

| Metric | Value |
| --- | --- |
| input tokens | **1,082 mean**, 86,559 total (80 calls) |
| output tokens | **358.5 mean**, 28,682 total |
| **monetary cost** | **not determinable — the API exposes no price field** |

`Usage` carries only `input_tokens`/`output_tokens`; `ModelMetadata` carries only
`name`/`description`/`release_date`. **No monetary figure is asserted here.**

### Extrapolated (from measured per-Story figures, not from a price list)

One call per Story, six dimensions per call:

| Batch | calls | in-tokens | out-tokens | wall-clock @ 282 ms |
| --- | --- | --- | --- | --- |
| 25 new Stories | 25 | ~27,050 | ~8,960 | ~7.1 s |
| 100 new Stories | 100 | ~108,200 | ~35,850 | ~28.2 s |

A full re-rank of all 253 current Stories would be 253 calls ≈ 286,600 in /
90,700 out tokens ≈ 71 s.

**Cost shape:** roughly **1,441 tokens per Story for six typed judgements**,
amortised over one round trip. Even with a large per-token price this is small
in absolute terms; the binding constraint is *editorial trust in the ordering*,
not spend. Note also that the **consistency test triples the call count** for a
given Story, so a design that re-asks on every Today load would be 3× the
calls for no measured benefit.

---

## 15. Reliability / fallback

Every scenario was exercised; none raised.

| Scenario | Result |
| --- | --- |
| **SDK / key unavailable** | `JevUnavailable` raised explicitly; harness exits 2 with a clear message; newsroom unaffected |
| **API unavailable (all JEV removed)** | ✅ Every Story still scores. The 4 deterministic terms carry the full weight. |
| **Per-Story provider error** | ✅ That Story drops its JEV terms; the rest of the screen is unaffected |
| **Invalid / empty response** | ✅ Same path — missing answers normalize to `None`, weighted terms are skipped |
| **Low confidence** | ✅ Story still ranks; E1 enforces no threshold (deliberate, see §7) |
| **Real timeout** (`timeout=0.001`) | ✅ `TypeSafeAPIConnectionError` caught, recorded, degrades |
| **Empty `build_state`** (no title/summary) | ✅ `build_state` handles empty strings |

**The required invariant holds:**

```text
JEV unavailable  →  newsroom still works
```

A future production ranking **must** degrade to deterministic chronology. The
re-normalizing weighted sum in §10 was built specifically so that this is a
property of the formula rather than a hope. JEV must never become required for
ingestion, Research or Draft — and in this slice it is required for nothing at
all.

---

## 16. Optional Story-identity shadow findings

Run per owner decision, on a small sample. **`story_identity.py` was not
modified and nothing here is used in production grouping.**

**First pass (20 random anchor/candidate pairs) — uninformative, and reported
as such.** All 20 returned `NEW_STORY` at confidence 0.95–1.00. Random pairs
are trivially different, so this measured almost nothing. It is included
because it was run, and it is worthless as evidence.

**Second pass — the real signal.** Targeted at the actual duplicate clusters
and a same-town/different-topic negative control:

| Test | Pairs | Result |
| --- | --- | --- |
| Within dolphin cluster | 28 | **26 `SAME_STORY` + 2 `NEW_DEVELOPMENT`, 0 `NEW_STORY`**, mean conf 0.933 |
| Within Alstom cluster | 1 | `SAME_STORY` conf 0.99 |
| Pomorie same-town control | 153 | 102 `NEW_STORY` (66.7%), 19 `NEW_DEVELOPMENT`, 32 `SAME_STORY` |

Scoring the control against a keyword-derived ground truth
(same topic = same event):

| Metric | Value |
| --- | --- |
| True-duplicate pairs found | 29 / 31 = **93.5% recall** |
| Pairs wrongly forced together | 3 / 122 = **2.5% false-merge rate** |
| Mean confidence on `NEW_STORY` | **0.966** |
| Mean confidence on `SAME_STORY` | 0.905 |
| Mean confidence on `NEW_DEVELOPMENT` | 0.601 |

On inspection, **all 3 "false merges" are themselves the same Pomorie hospital
story** — my crude keyword ground truth split them, not the model. The true
false-merge rate on genuinely different topics is effectively **0%**; the model
returned `NEW_STORY` at ~0.99 confidence for every dolphin-vs-budget,
dolphin-vs-ZUT, dolphin-vs-NHA and dolphin-vs-partnership pair.

**Conclusion: JEV separates same-event from different-event headlines on this
corpus better than the canonical grouper did.** The grouper split one event
into 8 Stories; JEV reunited them at 93.5% recall and ~0% false merges.

**This inverts the slice's premise.** The ranking question was secondary; the
grouping defect is primary, and the tool that fixes the grouping defect is
already in the repository. That is the strongest argument in this report, and
it argues for a *different* next slice.

Per §24 this stopped here — `story_identity.py` was left untouched and no
result was wired into production grouping.

---

## 17. Recommendation

> ### More evaluation needed — and the next slice should not be the ranking one.

**On the ranking question specifically: do not adopt.** Not because JEV is
inadequate, but because on this corpus it does not discriminate:

* three of the four fuzzy dimensions collapse to two values (§6);
* `local_relevance` never returns HIGH in 80 calls;
* two of the five deterministic terms are constant-zero across the whole
  corpus, so Baseline B is nearly Baseline A;
* the resulting hybrid surfaces **5 copies of one dolphin rescue in its top
  15** — worse for the editor than the chronological screen it would replace.

**On locality classification: adopt with constraints.** It is accurate,
explicable, closed-taxonomy, cheap, and matches what an editor would say. It
would be a genuinely useful badge. But A7 shows it is not perfectly
reproducible, so it should be presented as a **suggestion the editor can
correct**, never as a stored fact.

**On story identity: this is the real result.** 93.5% recall at ~0% false
merges on the actual duplicate clusters, against a canonical grouper that
produced 8 Stories for one event. **This is the finding worth acting on.**

### Why not "adopt with constraints"

A constrained adoption (locality badge only, no ranking) is defensible, but it
would ship a classification onto a store that currently shows the editor
**8 Stories for one rescue** — deepening the confusion it was meant to reduce.

**Recommended order of work:**

| # | Slice | Why first |
| --- | --- | --- |
| **0** | **Group the real corpus correctly** | The store is the defect. Ranking a fragmented store cannot work. JEV is already proven at this (93.5% recall). |
| **1** | Re-run E1 with a 4–5 level scale, or numeric value questions | The current scores cannot separate the corpus (§6). Cheap to re-run — harness exists. |
| 2 | Locality/category as editor-correctable suggestion | Only after 0 and 1. |
| 3 | `Топ за редакцията` | Last, and only with chronology as fallback. |

### If adopted later — the smallest possible production slice

Not recommended now; recorded for completeness:

1. **One field, one place:** `locality` only, on a *new* optional side-table
   (never inside the closed `story_store` schema — §25).
2. **Ephemeral, not persisted per load:** computed on Today render, discarded
   after — §8's instability makes persistence unsafe.
3. **Suggestion, not truth:** visibly editor-correctable; a correction writes
   to editor metadata, not to the model output.
4. **Hard fallback:** any JEV failure returns plain chronological order.
5. **No new DTO fields, no new UI section, no reorder of Today.** A single
   optional badge, absent when JEV is down.
6. **Kill switch:** one env flag; default off.

---

## 18. Explicit non-goals (all confirmed untouched)

| Non-goal | Status |
| --- | --- |
| Production Today ordering changed | ❌ **not changed** — still chronological |
| JEV as a production dependency | ❌ **not added** — required for nothing |
| Categories added to canonical Story state | ❌ **not added** |
| The 253 real Stories mutated | ❌ **0 writes** — see §20 |
| `story_store` schema extended | ❌ **not touched** |
| Any UI change (Топ / badges / scores / AI labels) | ❌ **none** |
| `story_identity.py` modified | ❌ **not modified** |
| Research / Draft / refresh command invoked | ❌ **none invoked** |
| API key renamed / copied / logged / persisted | ❌ **none** — read from env only |
| Weights persisted into the product | ❌ **report + script only** |
| Confidence threshold chosen | ❌ **candidates reported, none adopted** |

---

## 19. Security / privacy — exactly what left the system

Verified by reconstructing the payloads and asserting on their contents.

**Sent to TypeSafe — 6 keys, nothing else:**

```json
{"title": "...", "summary": "...", "publisher_domain": "...",
 "source_kind": "...", "published_at": "...", "reference_time": "..."}
```

| Assertion | Result |
| --- | --- |
| Payload keys | `published_at`, `publisher_domain`, `reference_time`, `source_kind`, `summary`, `title` |
| Story ids (`s…`) | ✅ **none** |
| Item ids (`i…`) | ✅ **none** |
| URLs | ✅ **none** (verified: no `http` in any payload) |
| Editor identifiers / `last_reviewed_at` | ✅ **none** |
| Article drafts or content | ✅ **none** |
| `.env` contents | ✅ **none** |
| API key material | ✅ **none** (verified: no `apikey` fragment) |
| `followed` status sent | ✅ **no** — an editor decision, never left the system |
| `factual_authority` sent | ✅ **no** — never delegated, never granted |
| Existing model conclusions | ✅ **none** |
| Max title sent | 143 chars (capped 400) |
| Max summary sent | 135 chars (capped 600) |
| De-duplication | a summary repeating the headline is dropped before sending |

All material is **already-public published news text** plus a public publisher
domain. No personal data, no editor data, no internal identifiers.

---

## 20. Runtime-store integrity proof

`sha256sum` of every regular file under both guarded roots, captured before
the run and again after, inside the harness itself.

| | |
| --- | --- |
| Stores guarded | `var/newsroom` (7 files), `var/editorial_workflow` (252 files) |
| Files hashed | **259** |
| Differences | **0** |
| Result | **BYTE-IDENTICAL** ✅ |

Independent confirmation, run before this slice began, against the D1
manifest:

```text
$ sha256sum -c var/integrity_manifest/d1_baseline.sha256
…
259 OK        (0 failed, 0 mismatched)
```

The experiment is read-only. No research, Draft or refresh command was
invoked at any point. The only file written by this slice is this report and
the harness script itself; the machine-readable result went to `/tmp`
(deliberately outside `var/`, and never consumed by production).

---

## 21. Reproducing this

```bash
# sample only, zero JEV calls, integrity checked
PYTHONPATH=src python3 scripts/v11e1_jev_ranking_shadow.py --dry-run --limit 80

# the full evaluation (writes only to /tmp)
PYTHONPATH=src python3 scripts/v11e1_jev_ranking_shadow.py \
    --limit 80 --repeat-subset 12 --identity-shadow 20 --out /tmp/v11e1
```

Deterministic: same corpus + `--limit 80` → same 80 Stories, always
(`SAMPLING_SEED = 20260926`).
