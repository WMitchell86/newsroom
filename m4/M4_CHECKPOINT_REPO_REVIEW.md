# M4 Checkpoint Repository Review — Source Layer, Inbox, and M4C Readiness

Repository snapshot reviewed from the uploaded archive on 2026-09-21.

Expected checkpoint from project history:

```text
075e81d
```

The archive contains no `.git` directory, so commit identity could not be independently verified from the snapshot itself. The code and reports are consistent with the reported M4A/M4B + publisher-authority correction state.

## Verification performed

Independent checks in this review environment:

```text
PYTHONPATH=src python3 -m pytest -q
→ 805 passed

PYTHONPATH=src python3 scripts/m3a_smoke.py
→ 25/25 passed
```

`ruff` is not installed in this review sandbox, so the reported ruff gate could not be independently rerun here. Nothing in this review contradicts the reported clean result.

---

# Executive verdict

The architecture is ready to proceed to M4C, but I recommend **one short stabilization pass first**.

The strong parts are genuinely strong:

- editor-owned source registry is separate from operational state;
- source failures are isolated;
- publisher authority is now resolved from the real publisher, not the discovery monitor;
- blocked domains are enforced before inbox insertion;
- collection is one-shot, lock-protected, cron-ready, and UI/CLI share one service;
- source items remain candidates, not evidence;
- Workbench is now usable enough to expose the real next problem: too many source items.

However, repository inspection found **two important runtime-semantics defects and several M4C design traps** that the reports do not fully capture.

Do not reopen the general source architecture. Fix the bounded issues below, then build M4C.

---

# What is already good enough and should be frozen

## 1. Registry / operational state split

Good boundary:

```text
sources.json
→ editor-owned configuration

source_health.json / last_run.json
→ operational state

inbox.jsonl
→ collected source items
```

Do not merge them.

## 2. Publisher authority lineage

The correction is conceptually right:

```text
source_id / source_kind
= how the item was discovered

publisher_domain / publisher_kind / factual_authority
= who actually published it
```

An official monitoring definition no longer lends its authority to a third-party article.

This is exactly the boundary M4C must preserve.

## 3. Fail-closed authority

Unknown publisher:

```text
publisher_kind = ""
factual_authority = false
```

is the right default.

Under-attribution is safer than invented authority.

## 4. Blocked publisher filtering

Using Google News `<source url>` rather than the opaque `news.google.com` item URL was an important real-production fix.

Keep it.

## 5. One-shot collection + shared lock

The shared `collect.lock` between cron and Workbench is appropriate at this scale.

Do not add a scheduler daemon or general job framework.

## 6. Source failure isolation

One failed source does not stop the run.

Correct and production-useful.

---

# Findings

## F1 — HIGH: safe bootstrap is only safe for one run

Current logic in `newsroom_run.select_candidates()` applies the 72-hour news lookback only while:

```text
bootstrap == True
```

After the first successful collection, the same source runs with:

```text
bootstrap == False
```

and the recency filter disappears. Only the 20-item cap remains.

This means:

```text
run 1
→ recent <=72h, max 10

run 2
→ any age returned by provider, max 20
```

So the second run can immediately backfill the older results that the first run intentionally excluded.

I reproduced the behavior directly against the uploaded code:

```text
20 candidates
10 recent
10 ten-days old

bootstrap=True  → 10 kept
bootstrap=False → 20 kept
```

This also strongly explains the reported live result:

```text
first run  → 204 items
second run → 100 new + 80 known
```

The second run had only the nine `each_run` sources due; allowing up to 20 results instead of the bootstrap's 10 naturally exposes older rows on the next pass.

### Correction

For ordinary news sources, apply a **rolling recency window on every run**, not only bootstrap.

Recommended simple rule:

```text
every run:
  keep dated news items from the last 72h

first successful run only:
  additionally cap to 10 newest

subsequent runs:
  regular per-source cap remains 20
```

For candidates with unreadable/missing dates:
- do not silently discard all of them;
- retain a bounded number;
- exact identity still prevents repeated insertion.

Do not build watermarks/high-water-mark infrastructure yet. A rolling 72-hour window is sufficient for this product stage and catches late-indexed articles.

### Acceptance test

Two immediate runs over a static provider fixture containing 10 recent + 10 old rows must produce:

```text
run 1 → only recent rows
run 2 → 0 old backfill
```

A real immediate live rerun should be close to zero new items unless the provider genuinely changed.

---

## F2 — HIGH/MEDIUM: `calendar=True` currently has false semantics

The code treats `published_at` as if it were the event date:

```text
calendar source
→ keep published_at within ±45 days
```

But almost every calendar entry in the current source catalogue uses:

```text
collector = google_news_rss
```

For Google News, `published_at` is the **publication timestamp of the article/result**, not the date when the event occurs.

Therefore a test like:

```text
published_at = 2026-10-20
```

does not prove that an October event survives. It only proves that an article dated October 20 survives.

Likewise, a concert scheduled next month but announced three months ago cannot be recognized as future calendar content from the fields the current collector provides.

### Correction

Do not pretend calendar semantics exist where the collector has no `event_at`.

Use:

```text
if candidate has real event_at:
    use bounded event window

else:
    treat it as ordinary news recency
```

Do not add bespoke calendar scrapers in this correction.

Keep `calendar=True` as source intent if useful, but make the runtime behavior honest.

A future direct calendar collector may add:

```text
event_at
event_end_at
```

and then the 45-day window becomes meaningful.

---

## F3 — MEDIUM: the Workbench label “Днес” shows lifetime counts

`render_inbox()` renders:

```text
Днес: нови N · прегледани N · игнорирани N
```

but those counts come from:

```text
inbox_store.counts()
```

which counts the entire inbox file, not the current Europe/Sofia day.

As the store grows, the UI will say “Днес: 700 нови” even when only 12 arrived today.

### Correction

Either:

```text
A. compute real today counts using Europe/Sofia
```

or rename the lifetime block.

Recommended UI:

```text
Днес:
  нови X
  прегледани Y
  игнорирани Z

Непрегледани общо:
  N
```

The default story/inbox view can still include older NEW items so the editor does not lose unfinished work.

---

## F4 — MEDIUM, IMPORTANT FOR M4C: inbox identity is discovery-path identity, not publication identity

Current item identity:

```text
item_id = hash(source_id + source_item_id + url)
```

This is fine for preserving provenance, but it means the same published article discovered by:

```text
burgas-municipality monitor
google-news-burgas-region monitor
burgas-prosecution monitor
```

becomes three different source items.

Do NOT rewrite or migrate this store now.

M4C should introduce a separate:

```text
publication_key
```

that is independent of `source_id`.

Then:

```text
3 discovery rows
1 publication
1 story membership
```

can all coexist.

This distinction is essential for accurate UI counts.

Do not display:

```text
5 sources
```

when five rows are actually two unique publications found through five monitors.

Recommended story metrics:

```text
discovery_count
publication_count
publisher_count
```

---

## F5 — MEDIUM: authority conflict on a shared publisher domain is silently resolved by alphabetical source ID

`authority_by_domain()` currently uses:

```python
out.setdefault(domain, row)
```

over registry rows ordered by source ID.

If an editor later creates two registry definitions for the same publisher domain with conflicting settings:

```text
example.bg
source A → factual_authority=true
source B → factual_authority=false
```

the winner depends on which source ID sorts first.

Authority should never depend on alphabetical accident.

### Correction

When building publisher authority policy:

```text
same canonical domain
+ same kind/authority
→ fine

same canonical domain
+ conflicting kind/authority
→ fail closed and report configuration conflict
```

Do not silently choose the stronger authority.

---

## F6 — LOW/MEDIUM: blocked-source refusal ignores the registry `domain` field

`blocked_reason()` checks:
- direct `url`;
- query text.

It does not directly check:

```text
entry["domain"]
```

A query-based registry source can therefore declare:

```text
domain = flagman.bg
query = some text not containing "flagman"
```

and the source itself will not be marked BLOCKED, although its returned Flagman rows will later be filtered.

That is safe for inbox insertion but misleading operationally.

### Correction

If an entry declares a domain and that domain is blocked:

```text
source status for run = BLOCKED
```

before network access.

---

## F7 — MEDIUM/PRODUCT: most “official sources” are currently monitoring queries, not direct official collection

This is not a correctness bug after the publisher-authority fix, but it matters for product language.

For almost all default sources:

```text
collector = google_news_rss
query = institution name
```

So:

```text
"Прокуратура Бургас — OK"
```

currently means:

> the monitoring query ran successfully

not:

> the prosecution website itself was successfully checked.

This is acceptable for now and should NOT trigger 25 custom scrapers.

### Required M4C discipline

Never infer publication authority, source diversity, or story origin from:

```text
source_id
source_kind
source health
```

Use:

```text
publisher_domain
publisher_kind
factual_authority
```

for publisher semantics.

### Small UX improvement

Where useful, label a query-based registry row as:

```text
Наблюдение чрез Google News
```

and the RSS source as:

```text
Директна емисия
```

This can be derived from `collector`; no new registry field is required.

---

## F8 — LOW: current structural test intentionally forbids M4C tokens

`tests/test_default_sources.py` currently fails if newsroom modules contain names such as:

```text
clustering
new_development
```

That was correct for M4A/M4B.

M4C must update this guard rather than work around it with obscure naming.

Keep the guard for:
- source registry;
- collection;
- blocked domains;
- source health.

Allow story identity only in new explicit M4C modules.

This is an important architecture boundary.

---

## F9 — LOW: small cleanup / documentation drift

Observed:
- `_collect_errors()` contains a duplicate unreachable `return []`;
- `CURRENT_STATE.md` test count is stale relative to the reported/verified 805;
- the statement that the M3A Workbench is frozen now conflicts with legitimate M4 newsroom UI development.

Suggested wording:

```text
M3A case-editing workflow is frozen.
M4 newsroom surfaces remain active development.
```

Do not turn this into a cleanup project.

---

# Deferred, not a blocker now

## Authority policy changes do not retroactively rewrite stored inbox rows

`factual_authority` is currently stored as a snapshot on each item.

If the editor later changes a publisher policy, old items keep the old value.

This is not currently dangerous because the M4 inbox is explicitly not evidence and no publication workflow should trust it directly.

Do not solve this inside M4C unless story/evidence integration begins to consume the field as current authority.

Record for later:

```text
stored authority snapshot
vs
current publisher policy
```

must be explicit before inbox/story items are promoted into factual evidence.

---

# M4C architectural recommendation

## Preserve all source items

Do not mutate the raw inbox into one row per story.

Use:

```text
SOURCE ITEMS
    ↓
PUBLICATION IDENTITY
    ↓
STORY MEMBERSHIP
    ↓
STORY VIEW
```

Raw collected rows remain auditable.

## Separate discovery identity, publication identity, and story identity

Three different concepts:

```text
DISCOVERY
how did we find it?
source_id

PUBLICATION
who published this exact article?
publication_key + publisher_domain

STORY
what real-world event/topic does it belong to?
story_id
```

Do not collapse them.

## False merge is worse than false split

Policy:

```text
uncertain
→ keep separate

not:
uncertain
→ merge because titles look vaguely similar
```

The editor can merge false splits later.
A false merge hides a distinct story.

## Semantic model is a narrow fallback, not the clustering engine

First:
- exact publication identity;
- time window;
- cheap title/summary token similarity;
- numeric/entity-like token overlap.

Only ambiguous shortlisted candidates reach semantic relation classification.

No all-pairs LLM clustering.
No embeddings/vector DB for M4C.

---

# Recommended next sequence

```text
M4B.1 stabilization
  F1 rolling recency
  F2 honest calendar semantics
  F3 real daily counts
  F5 authority-domain conflict
  F6 blocked declared-domain check
        ↓
M4C.1 publication identity + deterministic story candidate retrieval
        ↓
measure real 150–250 item corpus
        ↓
M4C.2 semantic SAME_STORY / NEW_DEVELOPMENT / RELATED_BACKGROUND only where needed
        ↓
story-first Workbench view + editor correction controls
        ↓
STOP / review
```

This is deliberately value-first.

Do not start Telegram until story grouping is good enough: Telegram should alert on stories/developments, not on raw source items.
