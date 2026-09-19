# M3B.1 — YouTube intake operational hardening (anti-ban, pacing, queue)

Scope asked for by the owner: study the sibling project **`youtube scripts
downloader` / `ytvault`** (one level above this repo, at `../youtube scripts
downloader`) and bring over whatever is genuinely usable here — *"so we can have
crons, anti bans etc."*

Answers to the two scope questions asked before coding:

| Question | Decision |
|---|---|
| How far should it go? | **Hardening + cron-ready batch + Invidious fallback** |
| `curl-cffi` TLS impersonation? | **Optional extra, OFF by default** |

Base commit at start: `c12ce2b` (M3B complete).

**Post-review changes (final state).** After the code review the owner closed all
ten open questions; four became small behaviour changes, applied here and
reflected in `RUNBOOK.md` §0d and `BACKLOG.md`:

| Change | Effect |
|---|---|
| `YOUTUBE_FALLBACK` default `on` → **`off`** | The bypass now requires an explicit `YOUTUBE_FALLBACK=on`. It contacts an unrelated third party and sends it the video id, and the live probe found 0/9 usable instances. |
| Interactive `youtube-intake` → **takes the shared run lock** | Editor intake and the nightly run can no longer touch YouTube at the same time; the interactive path exits `3` while the lock is held. It deliberately does not enter the retry/backoff lifecycle. |
| Clamped `YOUTUBE_*` values → **reported** | A hand-edited value outside its safety bound still clamps, but the run now prints `policy warning: … is above the safety maximum N -> clamped to N`. |
| Discovery nondeterminism → **promoted to the next milestone, M3D** | See §7 and `BACKLOG.md`. Not a code change. |

Unchanged by the review: the two-store split, stop-on-block, the rotation budget,
`CONSECUTIVE_FAILURE_FUSE = 5`, and the historical origin strings.

---

## 1. What the sibling project actually does

`ytvault.py` is a 1,902-line single-file, stdlib+`yt-dlp`+`rich` transcript
archiver. Read end to end. Its value here is not the code but four hard-won
operational lessons, each of which is documented in its own comments after
evidently being learned the hard way:

1. **Pacing is not optional.** One video at a time, a random 90–300 s pause
   between videos, a small nightly cap, and a random 10–40 min startup delay in
   `--cron` mode, so the job has no fixed request signature.
2. **Stopping is the feature.** The first `429` / `IpBlocked` trips a *circuit
   breaker*: the whole run stops and the IP cools down for 12 h. Pushing through
   a soft block is what turns it into a ban.
3. **Identity matters more than rate.** Cookies (browser identity) +
   `curl-cffi` TLS impersonation + rotating `player_client`s
   (`tv_simply` / `web_safari`) are what actually clear YouTube's bot check — a
   bare Python TLS fingerprint gets flagged regardless of request rate.
4. **A blocked IP should stop talking to YouTube.** An Invidious instance
   proxies the request, so the flagged IP is not re-poked 15–45 times a night.

Also worth keeping: a lock file against overlapping cron runs, an exponential
backoff ladder (15 m → 1 h → 6 h → 24 h → parked), exit codes
`0` ok / `2` breaker / `3` locked, and `_fmt_exc()` ("never lose an exception's
identity — `str(exc)` alone can be empty").

## 2. What was adopted, adapted and rejected

**Adopted (as behaviour):** pacing, nightly cap, startup jitter, lock file,
circuit breaker + cooldown, exponential backoff with parking, player-client
rotation, cookies/proxy flags, optional TLS impersonation, Invidious fallback,
run-level "bypass latch", explicit exit codes, and the observability rule that a
failure must always carry its own reason.

**Adapted, not copied:**

- *Not a scheduler.* `ytvault` is a channel archiver that catalogs and backfills
  a queue forever. Here the run is a **one-shot process over an explicit URL
  queue**; the repository still contains no scheduler, no daemon and no timer.
  Cron is documented, not installed.
- *Not `rich`.* No new required dependency, and no second CLI framework.
- *yt-dlp CLI, not the Python API.* `ytvault` uses `process=False` +
  `ydl.urlopen()` to escape format selection. The CLI equivalent
  (`--ignore-no-formats-error`) achieves the same thing and keeps the existing
  subprocess seam — see §5, where this turned out to be the single most
  important line of the milestone.
- *Trust mapping.* `ytvault`'s `manual` vs `asr` caption kinds are mapped onto
  this repo's existing trust vocabulary, capped at `HUMAN_TRANSCRIPT` (never
  `HUMAN_VERIFIED`).

**Rejected:** `rich`/`curl-cffi` as hard dependencies; `youtube-transcript-api`;
the `catalog` (channel backfill) concept — this repo is URL-driven by design;
and `ytvault`'s own README advice about cookies, which contradicts its
`config.json` (resolved here by defaulting cookies to *off* and documenting the
logged-out-session rule).

## 3. Architecture

```
youtube-batch add <url>      -> intake_queue.py   (operational queue + backoff)
youtube-batch run [--cron]   -> intake_run.py     (lock, cooldown, jitter, cap)
                                  └─ intake.intake_youtube(...)   [unchanged service]
                                       └─ transcriber.transcribe_youtube(policy=...)
                                            ├─ yt-dlp: rotate player clients
                                            │    (block -> TRANSCRIBER_BLOCKED)
                                            └─ invidious.fetch_captions(...)   [bypass]
youtube-batch status / reset -> queue counts, cooldown, last runs
```

New modules: `workflow/youtube_policy.py`, `workflow/invidious.py`,
`workflow/intake_queue.py`, `workflow/intake_run.py`.
Hardened: `workflow/transcriber.py`, `workflow/intake.py`, `workflow/cli.py`.

### Queue vs registry (deliberate separation)

`intake_store.registry.json` is **evidence** (content-addressed raw transcripts +
version history). `intake_queue.json` is **operational state** (which URL still
needs work, attempts, backoff, status). The queue can be deleted without losing
a single transcript. They share one runtime root (`YOUTUBE_INTAKE_DIR`), not one
file.

### Failure taxonomy (additive, nothing removed)

```
TRANSCRIBER_UNAVAILABLE      existing
TRANSCRIPTION_FAILED         existing   -> retry (backoff)
TRANSCRIPT_EMPTY             existing   -> park as no_captions
TRANSCRIPT_INVALID           existing   -> retry
UNSUPPORTED_LANGUAGE         existing   -> park as no_captions
TRANSCRIBER_BLOCKED          NEW        -> trips the circuit breaker (exit 2)
TRANSCRIBER_FALLBACK_FAILED  NEW        -> retry only; never trips the breaker
TRANSCRIPT_UNAVAILABLE       NEW        -> park as unavailable (removed/geo)
```

The two new *breaker* rules are the whole point: only explicit YouTube pushback
may stop a run, and a flaky public instance may never do so.

### Trust is still never silently upgraded

`TranscriptionResult` now carries `trust_level`, and `intake` feeds it into
`load_srt`. yt-dlp ASR stays `AUTO_CAPTION`. A non-ASR caption track from the
fallback engine becomes at most `HUMAN_TRANSCRIPT` — still below `STRONG_TRUST`,
so high-risk claims keep needing corroboration. Nothing can reach
`HUMAN_VERIFIED`.

## 4. Real validation (live, this machine)

**Queue mechanics — live, real files**

```
youtube-batch add "https://youtu.be/YsqD4T0D850"   -> queued  pending
youtube-batch add "https://example.com/not-youtube" -> queued  invalid_url
youtube-batch add "https://www.youtube.com/watch?v=YsqD4T0D850&t=42s"
                                                    -> known   pending   (dedupe ✓)
youtube-batch run --cap 1 --no-jitter               -> done REUSED, 2.5 s
                                                       outcome=NO_EXTRACTED_FACTS
```

Cache reuse proven live: the second URL form collapsed to one entry by video id,
and the run re-transcribed nothing.

**Fresh transcription path — live**

```text
policy: cookies: not set · proxy: none · clients: tv_simply, web_safari ·
        impersonate: off · fallback: off        # `on` only if opted in
OK 3.1 s | origin: yt-dlp:tv_simply:auto-sub | lang: bg-orig | trust: AUTO_CAPTION
cues: 184 | attempts: 1 ['tv_simply']
first cue: 1\n00:00:02,080 --> 00:00:05,070\nКолеги, добър ден.
```

184 cues reproduces the M3B baseline exactly, in one request.

**Player-client rotation — live**

```text
clients=('web_safari',) → attempts: ['web_safari', 'default'] → OK, 184 cues
```

`web_safari` reports "no subtitles for the requested languages"; rotation falls
through to yt-dlp's default client and still succeeds. Rotation is therefore not
decorative.

### 4.1 A real bug the live run caught

The first live attempt with clients `tv_simply, web_safari` **failed**:

```
ERROR: [youtube] YsqD4T0D850: Requested format is not available.
```

Both non-default clients fail format selection even with `--skip-download`
(verified manually for `tv_simply` and `web_safari`; the default client
succeeds). This is precisely the failure `ytvault` documents in a comment:

> *"yt-dlp's normal pipeline runs FORMAT SELECTION even with skip_download, and
> tv/web clients expose no selectable formats → 'Requested format is not
> available' on every video."*

Its fix is Python-API `process=False`; the CLI equivalent is
**`--ignore-no-formats-error`**, which was adopted and verified live:

```
tv_simply + --ignore-no-formats-error -> bg-orig.srt + bg.srt ✓
```

Without the live run this would have shipped as a regression that disabled
transcription for every video. Two further hardening consequences follow from
the same evidence:

- yt-dlp's **default client is always kept as the last attempt**, so rotation
  can only add options, never remove the path known to work;
- categories a different client cannot change - a content answer
  (`UNSUPPORTED_LANGUAGE`, `TRANSCRIPT_UNAVAILABLE`, `TRANSCRIPT_INVALID`) or an
  explicit block (`TRANSCRIBER_BLOCKED`) - stop rotation immediately instead of
  spending extra requests on a flagged IP. Only client-specific failures
  (`TRANSCRIPT_EMPTY`, generic `TRANSCRIPTION_FAILED`) rotate.

### 4.2 Invidious fallback — live result is NEGATIVE (and now legible)

Nine public instances probed live, none served captions:

```text
inv.nadeko.net          metadata OK, caption track returned 0 chars
invidious.nerdvpn.de    HTML instead of JSON (dead API)
yewtu.be                HTML instead of JSON (dead API)
invidious.f5.si         HTTP 500
invidious.privacyredirect.com  HTTP 404
iv.melmac.space / id.420129.xyz / invidious.jing.rocks  network unreachable / DNS
inv.tux.pizza           timed out
```

The engine is **correctly integrated** — it ranks tracks, prefers manual over
auto, converts VTT → canonical SRT, caps the instance count and never raises —
but the public fleet is currently unusable. Verdict recorded honestly as
`INVIDIOUS_FALLBACK = NOT_AVAILABLE`.

**This produced a second real bug.** The first probe returned a bare `None` and
threw away every per-instance reason. Fixed: `fetch_captions` now always returns
a dict with `status` and `warnings`, and `transcriber` folds that trace into the
raised error:

```text
TRANSCRIBER_FALLBACK_FAILED
fallback engine could not serve captions (https://inv.nadeko.net: empty caption
track (0 chars returned); https://yewtu.be: JSONDecodeError: ...; ...)
```

A silent `None` is exactly how a dead fallback engine hides for months — which
is the failure mode `ytvault`'s own comments warn about.

## 5. Gate

```text
PYTHONPATH=src python3 -m pytest -q        653 passed (was 553; +100)
ruff check src tests scripts               All checks passed
ruff format --check src tests scripts      clean
scripts/m3a_smoke.py                       25/25
```

(646 at the end of the build; +7 more from the review decisions: the off-by-
default bypass, the interactive lock parity and the policy-warning coverage.)

All new tests are hermetic: `intake_fn`, `runner`, `fallback_fn`, `opener`,
`sleeper` and `rng` are seams, and the suite never sleeps, shells out or opens a
socket. `tests/test_intake_antiban_guards.py` structurally forbids the intake
stack from growing a scheduler, an editorial token, a publishing path, or an
import of the discovery/drafting stack.

### 5.1 Post-review fixes (see `M3B1_CODE_REVIEW.md`)

A review pass over the finished branch found and fixed nine further issues, two
of which were already caught by the live runs (§4.1, §4.2). The behavioural ones:

- `transcriber` no longer rotates player clients on a **block** (a flag is on the
  IP; extra attempts escalate it) - it stops immediately and goes to the bypass;
- a block now defers the queue entry to the **cooldown window** instead of the
  15-minute backoff rung;
- the run lock is created with `O_CREAT|O_EXCL`, closing a race where two cron
  runs could both win;
- an owned temp directory is removed on **every** path, including failures;
- configuration warnings (bad cookies path, missing `curl-cffi`) survive the
  failure path instead of only appearing on success;
- a **consecutive-failure fuse** (`CONSECUTIVE_FAILURE_FUSE = 5` with zero
  successes) aborts the run with the previously-dead exit code `1`, so a broken
  setup cannot burn the whole nightly cap.

Live re-validation after those fixes: a second fresh recording ran the whole
pipeline to `RESEARCH_MORE` (91 s, 120 KB transcript), no per-video temp
residue, and the forced-rotation rescue still succeeds.

## 6. Verdicts

```text
YOUTUBE_INTAKE_ENGINEERING        = PROVEN
ANTIBAN_HARDENING_ENGINEERING     = PROVEN        (latch, breaker, lock, backoff, jitter, fuse)
PLAYER_CLIENT_ROTATION            = PROVEN        (live: rescued a failing client)
TRANSCRIBER_INTEGRATION           = PROVEN
INVIDIOUS_FALLBACK                = NOT_AVAILABLE (integrated; 0/9 instances served)
CRON_ENTRY_POINT                  = PROVEN        (one-shot; no daemon, nothing installed)
YOUTUBE_QUEUE_ENGINEERING         = PROVEN
JEV_PRODUCTION_AUTHORITY          = NONE
EDITORIAL_EFFECTIVENESS           = PENDING
```

`INVIDIOUS_FALLBACK = NOT_AVAILABLE` does **not** mean the bypass is broken; it
means the public service it depends on is not serving right now. The code path
is ready and the failure is now diagnostically legible. Do not read this as
"anti-ban is unproven" — the parts that do not depend on a third party
(client rotation, breaker, pacing, lock, backoff) are all live-proven.

## 7. Deviations and notes

- **Three new failure categories** were added to M3B's taxonomy. The harness
  prompt said *"explicit failure states, for example"*, and all three are
  additive: nothing existing changed meaning, and no existing test changed
  category.
- **Invidious is OFF by default** (`YOUTUBE_FALLBACK=off`, changed at review).
  It is reached *only* after YouTube has pushed back, and it protects the IP, but
  it sends the video id to a third party — so it is an explicit opt-in. The
  engine itself is unchanged and tested.
- **`curl-cffi` stays optional and OFF.** Default `YOUTUBE_IMPERSONATE` is
  empty; with the extra missing the request is made without impersonation and
  `warnings` says so, rather than failing.
- **Discovery remains nondeterministic — now promoted to `M3D Discovery
  Reproducibility & Stability`** (`BACKLOG.md`), the decided next milestone. The
  live batch run reported `NO_EXTRACTED_FACTS` for a transcript that previously
  yielded `RESEARCH_MORE`: pre-existing model-driven property recorded in M3B,
  not a regression from this change, and the reason `EDITORIAL_EFFECTIVENESS`
  stays `PENDING`. M3D measures the variance before anything is cached or frozen.
- **No rubric, threshold, readiness, discovery, profile or Jev-authority
  change.** No drafting, publishing, monitoring or LIVE 6–10.

## 8. Known limitations

- The Invidious instance list is a third-party dependency that can rot silently;
  the new `warnings` trace is what makes that visible in `youtube-batch run`
  output. Re-check with `youtube-batch status` + a probe when a run reports
  `TRANSCRIBER_FALLBACK_FAILED`.
- Cookies default to off, so the strongest identity lever is available but
  unused. Enabling it is an operator decision and requires a **logged-out**
  Netscape cookies export.
- `yt-dlp` must be kept current: an outdated extractor produces errors that look
  like blocks.
- A caption-less video now costs up to three attempts (one per configured client
  plus the default) *once*, then parks as `no_captions` forever. Accepted: the
  one-time cost is cheaper than losing rotation.
