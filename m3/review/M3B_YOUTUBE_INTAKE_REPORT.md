# M3B — YouTube URL Intake + Real-World Jev Shadow Collection — 2026-09-19

Starting commit `1de6652`. M3J frozen.

```text
YOUTUBE_INTAKE_ENGINEERING          = PROVEN
TRANSCRIBER_INTEGRATION             = PROVEN
REAL_TRANSCRIPT_DISCOVERY           = PROMISING
JEV_REAL_WORLD_SHADOW_COLLECTION    = ACTIVE
JEV_PRODUCTION_AUTHORITY            = NONE
EDITORIAL_EFFECTIVENESS             = PENDING
```

## Part A — Repository reconnaissance

- **No transcriber existed in the repo.** Only post-processing scratch scripts
  (`var/youtube_transcripts/clean_subs.py`, `tmp/transcript_batch_v2.py`); the 7
  known SRTs were fetched outside the repo. So this milestone adds an *adapter
  over the actually available transcriber* — `yt-dlp` 2026.07.04 (+ `yt_dlp`
  module, ffmpeg) — not a new transcription implementation.
- **Existing components reused unchanged**: `transcripts.load_srt` /
  `parse_srt` (authoritative raw SRT + trust levels), `discovery` V2
  (`segment_topics → extract_facts → propose_angles → assess_candidates`),
  `angles.assess_angles`, `discovery.build_evidence_packet` + `run_readiness`.
  No semantic edit to discovery or the rubric.
- CLI convention = argparse subcommands in `workflow/cli.py`; Workbench extension
  point = stdlib router in `workflow/workbench/http.py`.
- The 7 known recordings are `AUTO_CAPTION`, `https://www.youtube.com/watch?v=<id>`.

## Part B/C — canonical identity + metadata

`workflow/youtube.py`

- `parse_video_id` normalizes `watch?v=`, `youtu.be/`, `/live/`, `/shorts/`,
  `/embed/`, `/v/`, `m.`/`music.`/`nocookie` hosts, optional scheme, extra query
  params; rejects anything it cannot normalize confidently.
- Identity is the **11-char video id**; `canonical_url` is deterministic
  (`https://www.youtube.com/watch?v=<id>`); `original_url` is preserved
  separately; equivalent forms deduplicate.
- `resolve_metadata` uses yt-dlp's extractor (`download=False`) — the least
  fragile available path. Failures are explicit (`origin` says why) and never
  block intake; missing fields stay `None` (never invented).

## Part D/E — transcriber adapter + raw SRT authority

`workflow/transcriber.py`

- `transcribe_youtube(source, *, language, workdir, runner, timeout)` →
  `TranscriptionResult(status, video_id, raw_srt, language, origin,
  provider_or_command, generated_at, warnings)`.
- Failure taxonomy: `TRANSCRIBER_UNAVAILABLE`, `TRANSCRIPTION_FAILED`,
  `TRANSCRIPT_EMPTY`, `TRANSCRIPT_INVALID`, `UNSUPPORTED_LANGUAGE`. Infrastructure
  failure is never "no useful story".
- **yt-dlp quirk handled**: its VTT→SRT conversion emits blank lines *inside*
  cues, which the frozen parser rejects. `canonicalize_srt` fixes only the line
  structure (drops blank/sequence/header lines, renumbers); every timestamp and
  text line is preserved, so raw SRT stays authoritative.
- Default subtitle request is deliberately narrow (`bg-orig,bg`) — each extra
  language is another request and YouTube 429s bursts.
- Trust stays `AUTO_CAPTION`; never silently upgraded.

## Part F — idempotence / cache

`workflow/intake_store.py` (small file store, not a database)

- transcripts are content-addressed `<video_id>.<sha256[:8]>.srt`, so a changed
  transcript **never overwrites** an earlier one;
- registry keeps per-video `versions` history + a current pointer;
- atomic writes (shared `live_store.atomic_write`) and the registry is written
  **only after** a transcript is validated → an interrupted transcription leaves
  no success row (tested).

## Part G/H/L/N — pipeline

`workflow/intake.py`: `intake_youtube(url, ...)` with per-stage statuses.

```
normalize → metadata → transcription(OK|REUSED) → validate
→ persist(raw SRT + registry) → discovery V2 → optional Jev shadow → outcome
```

Outcomes are distinct: `DRAFT_READY`, `RESEARCH_MORE`,
`EDITOR_DECISION_REQUIRED`, `NO_PUBLISHABLE_ANGLE`, `NO_EXTRACTED_FACTS`,
`INVALID_YOUTUBE_URL`, `TRANSCRIPTION_FAILED`, `DISCOVERY_FAILED`. A failure
names its stage. **No-story is a valid outcome.**

Jev shadow (`workflow/jev_shadow.py`, shared specs with the M3J runner):
shadow grounding over retained **and** dropped facts + narrow angle signals.
`enabled`/`disabled` produces identical analysis/outcome (tested). Rescue
candidates (`DETERMINISTIC_REJECT__JEV_SUPPORTS` /
`DETERMINISTIC_RETAIN__JEV_REJECTS`) are appended to ignored
`var/jev_eval/semantic_rescue_candidates.jsonl` — **no auto-rescue, no
auto-rejection**, human review required before fixture promotion.

## Part I — CLI

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-intake "<URL>" \
  [--language bg] [--force-retranscribe] [--skip-jev-shadow]
```

Prints video identity, per-stage status, topics/facts, angle assessment,
readiness, strongest candidate, Jev shadow counts, artifact paths. No article text.

## Part J — Workbench (minimal, documented trade-off)

Transcription + discovery are long and model-driven, so the local threaded
server does **not** run them synchronously and **no job queue was added**.
Initiation stays CLI-only; the Workbench **displays completed intakes** at
`GET /intake` (`workflow/workbench/state.py::intake_registry/intake_view`), from
the same durable summary artifact the CLI writes. This is the smallest durable
option the harness allows.

## Part M — First real validation

Run on the known recording `YsqD4T0D850` (regression), live, with `yt-dlp` +
Gemini:

```text
normalize OK · metadata OK (title "ПК ТУРИЗЪМ") · transcription OK (language bg-orig)
validate OK (184 segments, AUTO_CAPTION)
discovery OK (12 topics, 10–11 facts, 7 dropped)
readiness RESEARCH_MORE / NO_PUBLISHABLE_ANGLE across runs
```

- URL normalization, metadata, transcription, SRT validity, discovery V2 and
  readiness all exercised end-to-end; no hand-coded facts or angles.
- **Unseen-recording validation is PENDING** — only the known recordings are
  available to this session (no 2 unseen URLs), recorded honestly here.

### Jev real-world shadow (Part N)

A fresh intake run collected **17 grounding + 3 angle** shadow cases and
**7 semantic-rescue candidates** — all `DETERMINISTIC_REJECT__JEV_SUPPORTS`,
e.g. `„Седем души са гласували „за“ дневния ред.“` (damaged by the deterministic
lexical gate). This reproduces the M3J grounding pattern on real new cases.

## Part O — Tests (+39)

`tests/test_youtube_intake.py`: URL normalization/equivalence/rejection,
video-id stability, metadata failure, transcriber unavailable/failed/empty/
invalid/unsupported-language, trust assignment, content-addressed storage,
version history, cache reuse + force, atomic registry / interrupted-run safety,
stage taxonomy, no-story outcome, discovery failure, Jev-on == Jev-off,
semantic-rescue classification, no drafting, CLI uses the same service,
Workbench display path. All hermetic (every boundary injected; no network).

## Known limitations

- `yt-dlp` subtitle fetches can hit YouTube `HTTP 429` on bursts (surfaced as
  `TRANSCRIPTION_FAILED`, never a silent empty transcript).
- **Discovery is model-driven and nondeterministic**: the same transcript can
  yield `RESEARCH_MORE` on one run and `NO_PUBLISHABLE_ANGLE` on another. This is
  a pre-existing property of the LLM extractor, not M3B; it is why editorial
  effectiveness stays `PENDING`.
- The registry caches **transcripts**, not discovery artifacts — re-running an
  intake re-runs discovery.
- Unseen-recording validation is pending (see Part M).

## Gate

- [x] `PYTHONPATH=src pytest -q` → **553 passed**, offline
- [x] `ruff check` + `format --check` clean on `src tests scripts`
- [x] `scripts/m3a_smoke.py` → 25/25
- [x] real end-to-end intake on the known recording (yt-dlp + discovery)
- [x] no article drafted, no rubric/threshold/routing change, Jev no authority

## STOP

No M3C automatic enrichment, no monitoring/scheduler, no drafting, no CMS
publishing, no Jev production authority, no rubric/threshold change, no LIVE 6–10.
Next natural step (editor decision): run intake on 2 genuinely unseen recordings
to complete Part M, then let the semantic-rescue corpus grow before any M3J.1
decision.
