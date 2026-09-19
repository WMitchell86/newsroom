# M3B.1 — Code review: YouTube intake operational hardening

**For a contributor/reviewer who has not read this branch yet.**
Design rationale and raw live evidence live in
`m3/review/M3B1_INTAKE_HARDENING_REPORT.md`; this file is the *review* document:
what changed, how it works, what was broken, what is still open.

Branch state: uncommitted working tree on top of `c12ce2b` (M3B).
Gate: **646 tests pass** (was 553; +93 new), `ruff check` + `ruff format --check`
clean, M3A smoke **25/25**.

---

## 1. Scope — and what this is explicitly NOT

The owner asked to mine the sibling project `../youtube scripts downloader`
(`ytvault`, single-file, 1,902 lines) for usable ideas — *"crons, anti bans etc."*
Two decisions were taken before coding:

| Question | Decision |
|---|---|
| How far? | hardening **+** cron-ready batch **+** Invidious fallback |
| `curl-cffi` TLS impersonation? | optional extra, **off** by default |

**Not in this change** (verify me on this — it is the most important review lens):

- no scheduler/daemon/timer is added or installed. `youtube-batch run` is a
  one-shot process; cron is *documented* in `RUNBOOK.md` §0d, not installed;
- no drafting, publishing, CMS, monitoring or LIVE 6–10;
- no change to rubric, thresholds, readiness, discovery semantics, profiles or
  Jev authority;
- no new **required** dependency. `curl-cffi` is an optional extra and the
  project runs unchanged without it.

---

## 2. File map

New (1,738 lines incl. the hardened transcriber):

| File | Lines | Responsibility |
|---|---|---|
| `src/editor_assistant/workflow/youtube_policy.py` | 196 | env-tunable pacing/identity/stop knobs; clamping; backoff ladder |
| `src/editor_assistant/workflow/invidious.py` | 212 | second caption engine (public-instance bypass); VTT → canonical SRT |
| `src/editor_assistant/workflow/intake_queue.py` | 318 | operational queue: statuses, dedupe, backoff, parking, run log |
| `src/editor_assistant/workflow/intake_run.py` | 412 | the cron entry point: lock, cooldown, jitter, cap, fuse, exit codes |
| `src/editor_assistant/workflow/transcriber.py` | 600 | yt-dlp adapter — **hardened** in place (M3B Part D boundary kept) |

Modified: `workflow/intake.py` (transcriber kwargs + trust pass-through),
`workflow/cli.py` (`youtube-batch`), `pyproject.toml` (optional `youtube` extra),
`.env.example` (documented knobs).

New tests (+93):

| File | Tests |
|---|---|
| `tests/test_youtube_policy.py` | 8 |
| `tests/test_invidious.py` | 12 |
| `tests/test_transcriber_hardening.py` | 25 |
| `tests/test_intake_queue.py` | 17 |
| `tests/test_intake_run.py` | 21 |
| `tests/test_intake_antiban_guards.py` | 10 |

---

## 3. How it works

### 3.1 Two stores, deliberately separate

```
var/youtube_intake/
  registry.json      EVIDENCE   video_id -> content-addressed transcript + version history
  queue.json         OPERATIONS key -> {status, attempts, next_attempt_at, last_error}
  transcripts/<id>.<sha8>.srt    immutable raw SRT
  artifacts/<id>.json            intake summary (Workbench reads this)
  runs.jsonl                     append-only run log
  run.lock / cooldown.json       run-level operational state
```

The queue can be deleted at any time without losing a transcript. Both share
`intake_store.intake_root()` (env `YOUTUBE_INTAKE_DIR`), so there is one runtime
root, not two. **If you think the two stores should merge, that is open question
Q1 below.**

### 3.2 Queue state machine

```
pending ──success───────> done               (terminal; re-add does NOT revive)
   │                      invalid_url        (terminal; bad URL, never requested)
   ├──failure (transient)─> retry ──(due)──> pending on next run
   │                         │
   │                         └─ attempts >= max_attempts ─> blocked (terminal)
   ├──failure (permanent)─> no_captions | unavailable  (terminal)
   └──block (IP level)────> retry, due at now + block_cooldown_h
```

`reset` revives `blocked`/`retry`; `--include-nocaps` also revives `no_captions`.
Re-adding a `blocked`/`unavailable`/`invalid_url` URL through
`youtube-batch add` revives it to `pending` with a fresh budget.

### 3.3 Failure taxonomy and who trips the breaker

```
TRANSCRIBER_UNAVAILABLE       yt-dlp missing           retry
TRANSCRIPTION_FAILED          generic yt-dlp error     retry (backoff ladder)
TRANSCRIPT_INVALID            unusable SRT             retry
TRANSCRIPT_EMPTY              no caption track         park -> no_captions
UNSUPPORTED_LANGUAGE          requested lang absent    park -> no_captions
TRANSCRIPT_UNAVAILABLE     *  removed/private/geo      park -> unavailable
TRANSCRIBER_BLOCKED        *  YouTube pushback         BREAKER (exit 2)  <-- only
TRANSCRIBER_FALLBACK_FAILED*  bypass also failed      retry, never the breaker
```

`*` = added in this change (additive; nothing existing changed meaning).

The two rules that matter: **only explicit YouTube pushback may stop a run**, and
**a flaky public instance may never stop a run**. `classify_failure()` matches
permanent per-video patterns *before* block patterns, because geo/removed
messages frequently contain the word "blocked" — see
`test_permanent_video_problems_are_matched_before_block_signals`.

### 3.4 The run loop

`intake_run.run_once()`:

1. `acquire_lock()` — atomic `O_CREAT|O_EXCL`; a lock older than
   `lock_stale_s` (6 h) is taken over. Fails -> `EXIT_LOCKED` (3).
2. `active_cooldown()` still in force -> `EXIT_BLOCKED` (2), no request made.
3. `--cron` -> sleep a random `startup_jitter_min_s..max_s` (10–40 min).
4. `due_entries(queue, cap)`, cap defaults to `nightly_cap` (5).
5. Per entry: `intake_fn(url, policy=…, direct_only=…)` → classify → update queue
   → `save_queue()` (atomic) after **every** entry → pause
   `delay_min_s..delay_max_s` (60–120 s) before the next.
6. Breaker: write `cooldown.json`, stop, `EXIT_BLOCKED`.
7. Fuse: `CONSECUTIVE_FAILURE_FUSE` (5) failures in a row with 0 successes ->
   abort with `EXIT_FAILED` (1), because that means the *setup* is broken.
8. `finally: release_lock()` — the lock is released on every path, including
   exceptions.

**Cache reuse:** a cached transcript makes the whole step seconds instead of a
minute (measured live: 2.5 s vs 91 s).

### 3.5 The bypass latch

Once one video in a run is rescued by the fallback, `direct_only` becomes true
and **every later video skips YouTube entirely** (`transcriber` →
`_try_fallback` directly). Rationale: a flag is on the IP, so re-poking it 5 times
a night is what escalates a soft block. If the latch is active and the bypass
fails, the error is `TRANSCRIBER_FALLBACK_FAILED`, which does **not** trip the
breaker — YouTube was never contacted for that video.

### 3.6 Trust is never silently upgraded

`TranscriptionResult` gained `trust_level`, and `intake_youtube` feeds it into
`load_srt`. yt-dlp ASR → `AUTO_CAPTION`. A non-ASR creator track from the bypass
→ at most `HUMAN_TRANSCRIPT` (still below `STRONG_TRUST`, so high-risk claims
keep needing corroboration). Nothing can reach `HUMAN_VERIFIED`.

---

## 4. Code review findings — bugs found and fixed

I reviewed the branch as if it were someone else's. **Nine issues**, ordered by
severity. Two were caught by live runs (F1, F2) and would otherwise have shipped.

### F1 — Rotated player clients failed on every video (CRITICAL, caught live)

`tv_simply` and `web_safari` fail yt-dlp's format selection even with
`--skip-download`:

```
ERROR: [youtube] <id>: Requested format is not available.
```

Since these two were the default rotation and were tried *first*, **every**
transcription failed. This is exactly the failure the sibling project documents
in a comment ("yt-dlp's normal pipeline runs FORMAT SELECTION even with
skip_download, and tv/web clients expose no selectable formats"). Its fix is
Python-API `process=False`; the CLI equivalent is
`--ignore-no-formats-error`, verified live:

```
tv_simply + --ignore-no-formats-error -> bg-orig.srt + bg.srt OK
```

**Fixed** in `_build_command()`. Also: yt-dlp's own **default client is now
always the last attempt**, so rotation can only add options, never remove the
path known to work.

### F2 — The bypass swallowed every diagnostic (HIGH, caught live)

`invidious.fetch_captions()` returned a bare `None` on total failure, discarding
the per-instance reasons — the one case where they matter most. The first probe
returned `None` and gave me nothing to debug with.

**Fixed:** it now always returns `{"status": "ok"| "unavailable", "warnings": …}`,
and `transcriber` folds that trace into the raised error:

```
TRANSCRIBER_FALLBACK_FAILED
fallback engine could not serve captions (https://inv.nadeko.net: empty caption
track (0 chars returned); https://yewtu.be: JSONDecodeError: ...; ...)
```

### F3 — Temp directory leaked on every failed transcription (MEDIUM)

`transcribe_youtube()` created `mkdtemp()` when no `workdir` was supplied but
only cleaned it on the success paths. Each failed video left a directory behind.
**Fixed** with `try/finally` guarded by `own_tmp`; a caller-supplied `workdir` is
still never deleted (both behaviours are tested).

### F4 — Lock acquisition raced (MEDIUM)

`acquire_lock()` did `exists()` then write, so two cron runs starting in the same
second could both win — doubling the request rate, which is the exact thing the
lock exists to prevent. **Fixed** with `os.open(..., O_CREAT|O_EXCL|O_WRONLY)`
plus a single stale-takeover retry.

### F5 — A block burned 3 requests at a flagged IP (MEDIUM)

Rotation continued through all clients on `TRANSCRIBER_BLOCKED`. A block is about
the IP, and more attempts escalate it. **Fixed:** `_STOP_ROTATION` now includes
`TRANSCRIBER_BLOCKED`, so a block stops immediately and goes straight to the
bypass/breaker. Live behaviour confirms it (1 attempt instead of 3).

### F6 — A block consumed the 15-minute backoff rung (MEDIUM, semantic)

After a block, the entry became due in 15 minutes while the *IP* was under a 12 h
cooldown. **Fixed:** `record_failure(delay_seconds=…)` lets the breaker set
`next_attempt_at = now + block_cooldown_h`, so the entry returns exactly when the
cooldown expires.

### F7 — Config warnings vanished on the failure path (MEDIUM, observability)

The "cookies file is not a file" / "curl-cffi not installed" warnings were only
attached to *successful* results — invisible on exactly the path (a block) where
a misconfigured cookies file is the prime suspect. **Fixed** with `_annotate()`;
the notes are appended to the raised error on both the ordinary-failure and block
paths.

### F8 — Unmapped permanent category parked as `blocked` (LOW)

`record_failure(permanent=True, category="INVALID_YOUTUBE_URL")` fell through to
`blocked`, mistranslating a URL problem into a retryable-looking state. **Fixed**
by naming every permanent category in the mapping and documenting that the
default (`blocked`) is the safe parking state for anything unmapped.

### F9 — Dead code and a stale docstring (LOW)

`EXIT_FAILED` was defined but never returned; `last_block` became dead once F5
landed; the module docstring still claimed rotation always happens; and
`"blocked it in your country"` sat in `_BLOCK_SIGNALS` even though the geo
pattern is matched first, making it unreachable. **Fixed:** the fuse now returns
`EXIT_FAILED` meaningfully, dead bookkeeping removed, docstring corrected,
unreachable signal deleted.

### Deliberately reviewed and left alone

- `translate`-style silent `except Exception` in `_try_fallback`: intentional —
  the fallback must never mask the original block error — and it now records the
  exception *type* in the note.
- `DEFAULT_LANGUAGE_PREFERENCE = ("bg-orig", "bg")` short on purpose: each extra
  language is another subtitle request and 429s are burst-triggered.
- `runs.jsonl` unbounded: logged in `BACKLOG.md` rather than pre-optimising.

---

## 5. Verification

Reproduce everything offline:

```bash
PYTHONPATH=src python3 -m pytest -q                     # 646 passed
ruff check src tests scripts && ruff format --check src tests scripts
PYTHONPATH=src python3 scripts/m3a_smoke.py             # 25/25
```

Live (needs network; `.env` supplies model credentials for discovery):

```bash
set -a; . ./.env; set +a
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch add "https://youtu.be/<id>"
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch status
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch run --cap 1 --no-jitter
```

Live results recorded on 2026-09-19 (details in the hardening report):

```text
dedupe + cache reuse            2.5 s   done REUSED
fresh transcription             3.1 s   yt-dlp:tv_simply:auto-sub, 184 cues, bg-orig
rotation rescue (forced failure) 3.0 s  web_safari fails -> default client succeeds
full pipeline, 2nd recording   91.0 s   RESEARCH_MORE, transcript 120 KB
Invidious bypass                 n/a    0 of 9 public instances served captions
```

Hermeticity: all new tests inject `intake_fn`, `runner`, `fallback_fn`, `opener`,
`sleeper`, `rng`. `tests/test_intake_antiban_guards.py` additionally fails if the
intake stack grows a scheduler, an editorial/publishing token, an import of the
discovery/drafting stack, or if the CLI stops going through the shared
`run_once` service.

---

## 6. Risks and trade-offs you should weigh

1. **Invidious compliance.** `YOUTUBE_FALLBACK` is **off** by default; setting it
   to `on` explicitly accepts that the video id is sent to a third party. It is
   reached *only* after a block, so the exposed surface is small — but it is a
   deliberate opt-in, not a default. (Q2, decided)
2. **Stop-on-block instead of rotate-on-block.** Conservative on purpose. The
   rejected alternative (rotate first, as `ytvault` does) might rescue a
   client-specific block at the cost of poking a flagged IP. (Q3, decided)
3. **A caption-less video costs up to 3 requests once**, then parks forever.
   Accepted as cheaper than losing rotation. (Q4, decided)
4. **Interactive `youtube-intake` takes the run lock** and exits `3` while a run
   holds it; it deliberately does **not** enter the queue's retry/backoff
   lifecycle. Two concurrent intakes are impossible, but an editor waits for the
   nightly run to finish instead of queueing behind it. (Q5, decided)
5. **Queue writes are read-modify-write** under the run lock. Fine for one
   operator; not safe for parallel workers. Intentional, documented.
6. **Clamping is reported, not silent**: `YOUTUBE_NIGHTLY_CAP=99999` becomes 50
   and the run prints `policy warning: YOUTUBE_NIGHTLY_CAP=99999 is above the
   safety maximum 50 -> clamped to 50`. An operator who reads only the exit code
   can still miss it. (Q6, decided)

---

## 7. Decisions (closed at review, 2026-09-19)

All ten questions were answered by the repo owner; every decision below is
implemented in this change or recorded in `BACKLOG.md`. Do not re-litigate.

| # | Decision | Reason |
|---|---|---|
| Q1 | **Keep the two stores split.** | `registry.json` is evidence/history; `queue.json` is disposable operational state. Deleting the queue must lose no transcript, and merging them would mix a retry lifecycle with an immutable evidence lifecycle. |
| Q2 | **`YOUTUBE_FALLBACK` defaults `off`** (implemented). | Third-party contact for a 0/9-available service is not worth an implicit default. |
| Q3 | **Keep stop-on-block** (implemented). | A block is an IP-level signal; extra client attempts escalate it. Rotation remains for ordinary client-specific failures. |
| Q4 | **Keep the yt-dlp default client last** (implemented). | Live proof: a rotated client can lack captions while the default client succeeds. One extra request once is acceptable. |
| Q5 | **Interactive intake takes the shared run lock** (implemented; exit `3`) but does **not** enter the queue lifecycle. | One concurrency story without changing the UX. |
| Q6 | **Clamp *and* warn** (implemented: `policy warning:`). | Observability, not a configuration redesign. |
| Q7 | **The fuse stays the constant `5`.** | A safety invariant should not be an env knob. Parameterize only if real use demands it. |
| Q8 | **Discovery nondeterminism promoted to a first-class next milestone, `M3D — Discovery Reproducibility & Stability`** (`BACKLOG.md`), ranked above M3C. | Same cached transcript → `RESEARCH_MORE` once, `NO_EXTRACTED_FACTS` another time: the semantic layer is now the weak link, and it is what keeps `EDITORIAL_EFFECTIVENESS = PENDING`. |
| Q9 | **`youtube-batch doctor` is optional P2/P3**, not a blocker (`BACKLOG.md`). | Useful for yt-dlp version / cookies path / curl-cffi / stale lock / cooldown / fallback state, but nothing depends on it. |
| Q10 | **No origin-string migration.** | The old `origin` stays valid historical evidence; the newer string is more informative, not a correction. |

### Q8 in more detail

This is the one finding that outranks the rest of the intake work. The transport
is now more reliable than the layer above it:

```text
URL -> queue -> pacing -> locking -> transcription -> raw SRT   (proven)
raw SRT -> topics -> facts -> angles -> readiness               (nondeterministic)
```

M3D is scoped as a *measurement* first: same transcript → N repeated runs →
topic / fact / angle / readiness stability, then a decision on which stages to
freeze or cache after the first successful extraction. Discovery semantics,
prompts and thresholds stay frozen until that evidence exists.

---

## 8. Suggested review path (30 minutes)

1. `git diff --stat` then read `youtube_policy.py` — it is the whole knob surface,
   and everything else reads from it.
2. `intake_queue.py` state machine (`add_url` → `due_entries` → `record_failure`
   → `reset`) against §3.2 above.
3. `intake_run.run_once` — specifically the `finally: release_lock()`, the breaker
   branch and the fuse.
4. `transcriber._ytdlp_result` and `transcribe_youtube` — F1/F3/F5/F7 live here;
   the `_STOP_ROTATION` tuple is the single most consequential line in the change.
5. `tests/test_intake_antiban_guards.py` — read it as the spec of what must not
   regress, then try to break it.
