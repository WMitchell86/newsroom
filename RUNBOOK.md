 # Manual Editorial Radar Runbook (M1.6 Step 2)

Operational-verification milestone only. No code changes in this step:
no ingestion, renderer, Telegram transport, state, or polling-code changes.
No scheduling. No automatic delivery.

## 0. Editor Workbench (local browser UI)

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench   # http://127.0.0.1:8123/
```

Binds **127.0.0.1** by default; `--host` is opt-in and there is **no auth** on
this local MVP. `POST /quit` is refused unless `WB_ALLOW_QUIT=1` (test-only).

### 0.1 Frontend serving mode (D2B — SPA is the default)

The Python process serves the compiled React SPA. There is **no Node production
server, no nginx and no second service** — Vite is build-time tooling only, and
the browser talks to `/api/v1` on this same origin.

The build is not committed (`frontend/dist/` is ignored). Produce it
deterministically — this is the whole production build:

```bash
cd frontend && npm ci && npm run build && cd ..
```

Then start the application normally. **No environment variable is required** —
the SPA is the default:

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench
```

Startup prints which editor owns the primary routes, so the running topology is
never a guess:

```text
[workbench] Editor frontend: SPA (serving /home/…/frontend/dist/index.html)
```

| `WB_EDITOR_FRONTEND` | Behavior |
| --- | --- |
| unset (or empty) — **default** | Python serves the compiled SPA on the approved editor routes. |
| `spa` | Identical to the default; stated explicitly. |
| `legacy` | **Rollback.** The server-rendered Workbench owns the current routes. |
| anything else | **Loud startup failure.** The process refuses to start. |

In SPA mode the SPA owns exactly `/`, `/stories`, `/stories/:id`, `/articles`,
`/articles/:id`, `/archive`, `/archive/:id`, `/settings`, `/settings/sources`.
Nothing else changes route owner: `/api/v1/*`, `/healthz`, `/static/style.css` and
the operator surfaces `/cases`, `/inbox`, `/sources`, `/models`, `/intake` stay
backend, and any other URL is a real 404 — the SPA is never a catch-all.

A new client route must be added in **two** places: the React router **and**
`spa.owns_spa_route`. The allowlist is closed on purpose, so a route that exists
only in the SPA works when it is reached by clicking but 404s on a reload or a
pasted URL — and the page then silently falls back to a legacy Workbench page.

- **Cache policy:** hashed `/assets/*` are immutable; `index.html` is `no-cache`;
  `/api/v1` keeps its existing `no-store`.
- **Missing build:** because the SPA is the default, a missing build is a **startup
  failure** with instructions to build. It never silently serves legacy pages,
  which would hide a broken deployment. Editor routes answer a loud plain-text
  `503` in that case; `/api/v1` and `/healthz` keep working.
- **Invalid value:** a typo (`WB_EDITOR_FRONTEND=spaa`) is a configuration error,
  not a fallback. Silently choosing an editor would be worse than failing.
- **Override the build root:** `WB_SPA_DIST=/path/to/dist` (used by tests).

**Rollback is one variable** — no redeploy of code, no rebuild, no migration, no
data conversion:

```bash
WB_EDITOR_FRONTEND=legacy PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench
```

In SPA mode the server-rendered pages also stay reachable under the technical
prefix `/wb-legacy/…` (e.g. `/wb-legacy/stories`) for validation and rollback.
This is operational infrastructure, not product navigation: it is never linked
from the SPA and never shown to editors.

> D2B status: cutover complete. The SPA is the default editor frontend; the
> server-rendered Workbench is **retained and reachable**, not retired. Removing it
> is a separate, later decision after real operational use.

**Rollback period.** `WB_EDITOR_FRONTEND=legacy` and `/wb-legacy/…` stay
supported for at least the whole V1 operational period. Keep them until a
post-V1 review explicitly decides otherwise; there is no announced end date and
no code is scheduled for removal. Until that decision, assume the Workbench is
part of the production surface.

### 0.2 Production deployment sequence

The SPA is the default, so the compiled build is a **required build artifact**.
The whole sequence is:

```bash
cd frontend
npm ci
npm run build
cd ..
PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench
```

`scripts/build_frontend.sh` wraps exactly those three build steps and then
verifies the entry document exists, so a deployment fails here rather than at the
editor's first click:

```bash
scripts/build_frontend.sh
```

It is intentionally just the documented commands plus one existence check — there
is no deployment system, no service manager and no CI pipeline implied by it.
`npm ci` (not `npm install`) is what makes the build reproducible from the
committed lockfile.

### D2A — browser parity proof

D2A proved the same bundle in a **real browser** (hydration, React Router
navigation, deep links, refresh, back/forward), which D1 could not reach. It
does **not** change any product behavior; D2B made the SPA the default.

```bash
python3 -m pip install playwright==1.63.0 && python3 -m playwright install chromium
cd frontend && npm ci && npm run build && cd ..
PYTHONPATH=src python3 -m pytest tests/browser -p no:cacheprovider
```

The suite runs against a real `ThreadingHTTPServer` **in the default mode — with
no `WB_EDITOR_FRONTEND` set at all**, which is the cutover proof — using isolated
store roots, and it hashes the real `var/` runtime stores before and after to
prove nothing leaked. Screenshots for review land in `var/d2a_screenshots/`.
Full details, including exactly which three outbound edges are substituted, are
in `tests/browser/README.md`.

The substituted draft provider deliberately takes ~4s, longer than the ~2s
client polling budget D2A found insufficient, so the suite fails if the Draft
polling hardening is ever reverted.

Verify the real build through the real Python server (not Vite):

```bash
PYTHONPATH=src python3 scripts/d1_spa_proof.py
```

First run (empty `var/newsroom/` — the pages will be empty until you do this
once; verified 2026-09-21: 35 sources applied, 99 real items collected, 0
errors, 88 stories built):

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --apply
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect --force
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom stories update --no-semantic
```

(After that, «Събери новините сега» / «Обнови историите» in the UI do the same
two steps; the buttons can also run in `--dry-run` form «Пробен преглед».)

Where the editor lands (2026-09-21 UI overhaul —
`m4/review/WORKBENCH_UI_OVERHAUL_REPORT.md`):

- **`/` = «Начало»** — read-only daily landing: unreviewed stories / unreviewed
  materials / arrived-today (Europe/Sofia) / active sources, the newest stories
  and a three-step «Как се работи» card. No page here writes anything.
- **Daily pages:** `/stories` (+ `/stories/{id}`), `/inbox` (Материали),
  `/sources`. **Settings/archive row:** `/models` (AI модели), `/cases`
  (the frozen M3A queue), `/intake` (YouTube).
- `/cases?filter=…` is the queue's canonical URL; the older `/?filter=…` links
  still resolve to the same page. The stylesheet is served once at
  `/static/style.css` (an inline copy stays as a no-network fallback).
- Long actions (collect / refresh stories) disable their button and show a
  «Събиране… моля, изчакайте.» overlay; destructive buttons ask
  `Наистина ли?` first.

### M3A case workflow (frozen surface, now under «Случаи»)

For editorial review of LIVE workflow cases (draft → sources → editor final)
without editing Markdown files:

Editor rules:

- **Запази работно копие** stores a non-authoritative working copy only
  (`var/editorial_workflow/editor_working/`); it never finalizes, publishes,
  changes readiness or touches the AI draft.
- **Финализирай редакторската версия** is the explicit, validated finalization
  (`cases.record_editor_final`). It is refused if the case is already final
  (409) or if a newer AI draft was generated since the working copy was started
  (409: „Междувременно е генерирана по-нова AI версия…“). To move past it,
  tick **„Приемам новата AI версия за основа“** in the workspace and save
  (an explicit editor action; a plain save never re-bases).
- A **finalized** case shows the immutable final result and its editor metrics:
  no editor workspace, and saving a working copy against it is refused.
- No-draft cases (`NO_PUBLISHABLE_ANGLE`, `RESEARCH_MORE`,
  `EDITOR_DECISION_REQUIRED`) show no article editor; only a decision can be
  recorded. M3A does not execute research.
- Actions are appended to `var/editorial_workflow/workbench_actions.jsonl`
  (`{action, case_id, timestamp}`).

Smoke check against a copy of the store (never the live one):

```bash
PYTHONPATH=src python3 scripts/m3a_smoke.py   # 25/25, writes only var/wb_smoke/
```

See `m3/review/M3A_EDITOR_WORKBENCH_REPORT.md`.

## 0b. Jev shadow evaluation (M3J, no production authority)

Jev is an **evaluation-only** semantic judge. It does not touch the editorial
workflow, drafts, readiness or any runtime state; it reads frozen public-source
fixtures and appends its own results under the ignored `var/jev_eval/`.

```bash
set -a; . ./.env; set +a                    # only if TYPESAFE_API_KEY lives in .env
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --experiment corroboration
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --all
PYTHONPATH=src python3 scripts/evals/jev_shadow_eval.py --summary --all
```

Without `TYPESAFE_API_KEY` (or the optional `typesafe-sdk` extra) the run
reports `JEV_CAPABILITY_UNAVAILABLE` and changes nothing. The runner is
resumable: re-running skips cases already evaluated. Never edit the fixtures to
make a result look better; add a new fixture version instead.

See `m3/review/M3J_JEV_SHADOW_EVALUATION.md` and `fixtures/evals/jev/README.md`.

## 0c. YouTube intake (M3B)

Add one recording to the transcript pipeline (no drafting):

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-intake \
  "https://www.youtube.com/watch?v=<id>"            # add --skip-jev-shadow to skip Jev
```

Stages print in order (`normalize → metadata → transcription → validate →
persist → discovery → jev_shadow`) with an `outcome`:
`DRAFT_READY` / `RESEARCH_MORE` / `EDITOR_DECISION_REQUIRED` /
`NO_PUBLISHABLE_ANGLE` are **editorial results**; `INVALID_YOUTUBE_URL` /
`TRANSCRIPTION_FAILED` / `DISCOVERY_FAILED` are infrastructure failures.
No-story is not a failed intake.

- Raw timestamped SRT is authoritative and cached under `var/youtube_intake/`;
  re-running the same video reuses it, and a changed transcript is kept as a new
  version (never silently overwritten). Use `--force-retranscribe` to refetch.
- YouTube may rate-limit subtitle bursts (HTTP 429) — retry later; the failure is
  explicit, never an empty transcript.
- Completed intakes are visible in the Workbench at `http://127.0.0.1:8123/intake`
  (transcription itself is CLI-only; there is no scheduler or background worker).
- Jev shadow observations and semantic-rescue candidates go to ignored
  `var/jev_eval/`; **no automatic rescue**.

See `m3/review/M3B_YOUTUBE_INTAKE_REPORT.md`.

## 0d. YouTube intake queue + cron (M3B.1)

`youtube-intake` is the interactive, one-URL path. `youtube-batch` is the slow,
paced path — and it is the **only** cron entry point. Both paths take the *same*
run lock (`var/youtube_intake/run.lock`), so an editor pasting a URL while the
nightly run is working gets exit `3` instead of putting two concurrent requests
on the same IP.

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch add "<URL>" ["<URL>" …]
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch status
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch run --cron
PYTHONPATH=src python3 -m editor_assistant.workflow.cli youtube-batch reset [--include-nocaps]
```

`add` normalizes the URL; equivalent forms (watch/youtu.be/live/shorts/embed)
deduplicate to one entry by video id, and a non-YouTube URL is recorded as
`invalid_url` without ever becoming a request.

### Installing the nightly run (the operator does this, not the repo)

Nothing in the repository schedules anything: `run` is a one-shot process that
works a bounded number of entries and exits. Add this line yourself:

```bash
crontab -e
# 02:30 nightly; `--cron` sleeps a random 10-40 min first, so there is no
# fixed request signature night after night.
30 2 * * * cd /home/test/media && PYTHONPATH=src /usr/bin/python3 -m editor_assistant.workflow.cli youtube-batch run --cron >> var/youtube_intake/cron.log 2>&1
```

Exit codes: `0` ok · `1` systemic abort (many failures in a row with zero
successes — the setup is broken, read the log before retrying) · `2` circuit
breaker tripped **or** a cooldown is still active (do not retry tonight) ·
`3` another run holds the lock.

### Anti-ban guardrails (all defaults live in `workflow/youtube_policy.py`)

| Guard | Default | Why |
|---|---|---|
| One video at a time | always | parallel bursts are the #1 block trigger |
| Random pause between entries | 60–120 s | human-ish pacing |
| Nightly cap | 5 | a backfill is paced over weeks on purpose |
| Random startup jitter (`--cron`) | 10–40 min | no fixed signature |
| Player-client rotation | `tv_simply`, `web_safari`, then yt-dlp default | clears checks the default client fails |
| Circuit breaker | first explicit block stops the run | pushing through a soft block is how it becomes a ban |
| Cooldown after a block | 12 h | the flag is on the IP, not the video |
| Exponential backoff | 15 m → 1 h → 6 h → 24 h, then parked | retrying a dead video is just extra requests |
| Lock file | 6 h stale window | overlapping cron runs (and interactive intake) would double the request rate |
| Invidious bypass | **off** — set `YOUTUBE_FALLBACK=on` to opt in | it contacts an unrelated third party and sends it the video id; enable only if you accept that trade |
| TLS impersonation + cookies | **off** | needs the optional `curl-cffi` extra; cookies must be a *logged-out* export |

Operational rules:

- **Never lower the cap or the delays to "catch up".** If a run trips the
  breaker, stop for the cooldown and halve the cap before retrying.
- A hand-edited `YOUTUBE_*` value outside its safety bound is **clamped, not
  applied**. The run prints `policy warning: YOUTUBE_NIGHTLY_CAP=99999 is above
  the safety maximum 50 -> clamped to 50`; if you see no warning, your value was
  used as written.
- A `TRANSCRIBER_BLOCKED` result writes `var/youtube_intake/cooldown.json`; every
  later run exits `2` until it expires. `youtube-batch status` shows it.
- `INVIDIOUS_FALLBACK` is currently `NOT_AVAILABLE` (0/9 public instances served
  captions when probed). `TRANSCRIBER_FALLBACK_FAILED` carries the per-instance
  reason; do not treat it as a YouTube block.
- `youtube-batch reset` revives `blocked`/`retry` entries only. `no_captions` and
  `unavailable` need `--include-nocaps`; those are deliberately not retried.
- Keep `yt-dlp` current (`pip install -U yt-dlp`): an outdated extractor produces
  errors that look like blocks.

Shows: queue counts, active cooldown, the effective policy line
(cookies/proxy/clients/impersonate/fallback — never credentials), any
`policy warning:` clamp, and the last 5 runs from `var/youtube_intake/runs.jsonl`.

See `m3/review/M3B1_INTAKE_HARDENING_REPORT.md`.

## 0e. Daily newsroom collection + stories (M4A.1/M4B/M4B.1/M4C)

The editor manages sources in the Workbench (`/sources`), reads real stories in
`/stories` and the raw collected material in `/inbox`. Collection is a **one-shot
process** the operator's cron calls; the repository still installs no timer, and
story building is a second one-shot step with no daemon and no polling loop.

```bash
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --preview   # no write
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources defaults --apply
PYTHONPATH=src python3 -m editor_assistant.workflow.cli sources list
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect --dry-run   # zero network
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect             # cron calls this
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom collect --force     # ignore cadence
# M4C story identity
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom stories update --dry-run   # plan only
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom stories update             # assign
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom stories update --no-semantic  # deterministic only
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom stories rebuild --preview  # full rebuild, no write
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom refresh             # collect -> stories -> summary
# M4D model routing
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models status      # per-role model view
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models validate    # check model IDs live
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models prompts            # what was SENT to a model
PYTHONPATH=src python3 -m editor_assistant.workflow.cli newsroom models show         # full policy dump
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list                     # qualification plan
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role judge               # qualify one role
```

`newsroom refresh` is the recommended cron command: it collects, assigns the newly
collected items to stories and prints one summary (`източници / нови материали /
нови истории / нови развития / добавени към съществуващи / за преглед / грешки`). A
story failure is reported but never rolls back a successful collection.

### Installing the daily runs (the operator does this)

Four light runs a day in `Europe/Sofia` (07:00 / 12:00 / 16:00 / 20:00). Daily
sources are collected once per local day; the core sources run every time, so the
later runs are cheap.

```bash
crontab -e
0 7,12,16,20 * * * cd /home/test/media && PYTHONPATH=src /usr/bin/python3 -m editor_assistant.workflow.cli newsroom refresh >> var/newsroom/cron.log 2>&1
```

The `>>` target directory must already exist. **A shell opens a cron job's
output redirect *before* it runs the command**, so a `mkdir` inside the command
is too late — the job dies at the redirect, exits `2`, and writes nothing. This
is why the installed newsroom schedule uses the `newsroom_cron.sh` wrapper, whose
crontab lines create the log directory first:

```bash
crontab -e
17 * * * * mkdir -p /home/test/media/var/cron && /home/test/media/scripts/newsroom_cron.sh newsroom refresh >> /home/test/media/var/cron/collect.log 2>&1
```

`var/` is gitignored, so a fresh checkout has no `var/cron/` at all — without the
`mkdir -p` every scheduled job is dead on arrival while the crontab still looks
correct. `newsroom doctor` checks this (`РАЗПИС:` line, exit `1`) rather than
reporting the schedule as installed.

`NEWSROOM_CRONS` in `src/editor_assistant/workflow/cli.py` is the single source of
truth for these lines: `newsroom doctor` matches the installed crontab against the
exact line built from it, so the crontab and that constant must be changed
together. `newsroom_cron.sh` loads `.env` in the shell (`set -a; . ./.env`) — never
`env $(cat .env)`, which leaves quotes attached to the keys and makes every
provider call fail while the summary claims the work was done.

Exit codes: `0` ok · `1` at least one source failed (successful sources keep
their items — read the summary) · `3` another run holds the collection lock
(cron overlapping the Workbench «Събери новите сега» button; harmless).

### Every role needs a free substitute

A role whose only fallbacks are `billing: paid` has **no fallback at all** while
`paid_enabled` is false — a paid route is *skipped*, so once the Gemini
per-model daily limits are spent such a role has nothing left and quietly does
less. That is exactly the failure each role's `on_exhausted` contract exists to
prevent (`angle: degraded`, `draft: fail_visible`, `story: conservative`).

`angle` shipped that way until 2026-10-01: its chain went straight from the
three Gemini Flash routes to two **paid** OpenRouter models, so
`newsroom doctor` reported `✗ angle 0/5` and, once Gemini was spent, `angle`
would have had zero eligible routes. It now carries
`nvidia/nemotron-3-ultra-550b-a55b:free` and `nvidia/nemotron-3.5-lightning:free`
(0/5 → 3/7).

**OpenRouter is the provider, not a billing class.** The same provider serves
free and paid models, and its free endpoints are the ones that keep the desk
running when Gemini is spent. `newsroom models validate` lists which of the
configured ids are free endpoints today.

Order note: the free route must simply be *in* the chain. A gated paid route is
a skip that continues to the next route, so `draft` legitimately lists its paid
route ahead of the free ones and still reaches them.

Two rules when adding a substitute:

- **`openrouter` + `billing: free` implies `public_only: true`** (rejected
  otherwise). The route is only usable for a public payload — check the role's
  `default_payload_class` and what the call site actually passes. `angle`'s
  default is `private`, but both real callers (`discovery.propose_angles`,
  the assessment path) pass `payload_class="public"` explicitly.
- **A free model that cannot answer is worse than no model.** On 2026-10-01
  `qwen/qwen3.8-27b:free` was 0-for-14 (`EMPTY_OUTPUT` / `RATE_LIMITED`) while
  `models status` still showed it ✓ eligible, because eligibility is decided by
  limits and health marks, not by whether the model has ever produced output.
  Check the ledger (`var/model_usage/<sofia-day>.json`) before trusting a route.

### Streaming guards (V1.2-G4.28, 2026-10-02)

The OpenRouter transport parses the SSE stream **incrementally**, so a generation
that has stopped making progress is abandoned while it is happening rather than
after. Two guards can stop one early; both write the reason into the attempt's
`stopped_because`:

| `stopped_because` | Meaning | Measured effect |
|---|---|---|
| *(empty)* | the stream ended on the provider's terms | normal |
| `repetition_loop` | the model emitted no new character for 1 000 chars — it is cycling | 144 366 ms → 39 492 ms on the same prompt |
| `deadline_exceeded` | it passed `OPENROUTER_DEADLINE_S` (default 180) | — |

The loop guard asks **"has any character appeared lately that we had not already
seen?"**, not "have I seen this text before?". Two earlier detectors that asked
the latter were tried and both stayed silent on the live failure, because two
samples only collide at the same *phase* of a repeating cycle. Do not "simplify"
this back to a repeated-window comparison — it will look equivalent and stop
working, with no test failure to warn you. The one that catches it
(`test_a_model_that_repeats_itself_is_stopped_early`) streams ~20-char chunks
around a ~129-char cycle, the shape the live model actually produced.

`stopped_because` reaches the operator through the router as a named cause
(`REPETITION_LOOP`, `DEADLINE_EXCEEDED`) with its own wording and next step,
rather than a bare "empty output".

**`SPENT_BUDGET_ON_REASONING` is legacy.** It claimed a model spent its whole
token ceiling on reasoning, which no observation supports. It is no longer
produced; rows already written keep it. If you see it in the log, it predates
2026-10-02 and the label itself was never trustworthy — re-read the row as
"empty output, cause unknown" rather than as a budget diagnosis.

### Reading the usage ledger

`var/model_usage/<Europe/Sofia day>.json` is the only record of what was asked of
each model. The file is keyed by the **Sofia** day, so its rows can start as early
as `21:00Z` the previous calendar day: `2026-10-01.json` opened at
`2026-09-30T22:17:21Z` (= 01:17 Sofia). `by_role`/`by_model` are aggregates,
`calls` is the row list.

Count rows **carefully** — a row is not a call:

- `provider_attempts > 0` → a real transport call. This is the number the daily
  limits read, so it is the one to compare against a `daily_call_limit`.
- `provider_attempts == 0` with `status: SKIPPED` → the router never called out
  (`MODEL_LIMIT_REACHED`, `PAID_DISABLED`, `NO_KEY`, `ROUTE_UNHEALTHY`,
  `RPM_LIMIT_REACHED`, `ROLE_HARD_BUDGET`). Nothing was spent.
- Rows in a burst sharing one `request_id` are a **single logical request**
  walking its fallback chain, not many requests. 32 of the 34 `draft` rows on
  2026-10-01 were two real drafts plus their fallbacks.
- **Only rows with `input_tokens`/`output_tokens` are real work.** A `draft` call
  with `in=0, out=0` produced nothing — that day there were 34 draft-role calls
  and 2 drafts (1007 output tokens).

Per-role budgets (`soft_calls_day`/`hard_calls_day`) count *logical requests*;
`daily_call_limit` counts *provider attempts*. Two different controls.

**`daily_call_limit` is per MODEL per day, shared by every role.** There is no
role filter in `model_usage.model_calls_today`. On 2026-10-01 the `story` role
spent `gemini-3.8-flash` to 22 attempts on its own, and because `story`/`angle`
declare `daily_call_limit: 20` for that model while `draft` declares `80` for
the same one, `models status` showed the same model as

```
× 0: gemini-3.8-flash · днес 22/20 · дневен лимит на модела (20) е достигнат   ← story
✓ 1: gemini-3.8-flash · днес 22/80                                              ← draft
```

The `20` is **our own declared guardrail, not a measured provider limit** — the
message reads like the provider's quota, and it is not one. Treat a
`дневен лимит … е достигнат` line as "our number", and do not report it to the
editor as an exhausted quota (AGENTS.md rule 3).

### Seeing what was sent to a model

Two questions the ledger cannot answer: *what exactly did you ask the model?*
and *which model actually wrote this?*

```bash
newsroom models prompts                      # every recorded attempt, with the text
newsroom models prompts --role draft         # one role
newsroom models prompts --limit 3            # only the last N
newsroom models prompts --no-text            # headers only — safe to paste into a report
newsroom models prompts --request-id <id>    # one logical request, every route it tried
newsroom models prompts --json
```

Store: `var/editorial_workflow/model_prompts.jsonl`, **mode `0600`** like the
other private editorial stores — a draft prompt carries unpublished source text.

**A failed row's `error` field is the provider's own message, not a category.**
Since 2026-10-02 (V1.2-G4.29) a failed attempt records
`"<ExceptionType>: <what the provider said>"`, truncated to 200 chars. Rows
written before that date have **no `error` field at all** — if you are diagnosing
an old failure, the cause is not recoverable from this file and you must re-run
the call. The `outcome` prefix (`FAILED:TRANSIENT`, `FAILED:RATE_LIMITED`, …) is
the router's *verdict*, not the cause, and has never been sufficient on its own.

A row whose `outcome` is `FAILED:QUOTA_EXHAUSTED` means waiting — the quota resets
on the provider's schedule. `FAILED:TRANSIENT` means overload and clears in
minutes. Do not read either as a permanent outage, and do not act on one without
a fresh `models status` (AGENTS.md rule 2).

**The prompt text is NOT in the usage ledger, and must never be.** The ledger is
aggregated and diffed while investigating a provider failure;
`test_usage_ledger_aggregates_and_never_stores_prompts` freezes that. The prompt
log is a separate store for that reason, not an oversight.

One row per **transport attempt**, so a request that fell back leaves the whole
chain. A real rewrite on 2026-10-01, where three Gemini routes failed before the
fourth answered:

```
16:38:30  draft route#0  gemini:gemini-3.5-flash  13024 симв.  payload=private
16:38:30  draft route#1  gemini:gemini-3.8-flash  13024 симв.  payload=private
16:39:15  draft route#3  gemini:gemini-3.6-flash  13024 симв.  payload=private   ← answered
```

The **last** row of a `request_id` is the model that answered, and it matches
`lineage.model` in `live_drafts.jsonl` (`gemini-3.6-flash`). Rows sharing a
`request_id` are one logical request.

Logged at the transport boundary, not by the caller: `_trim_for_model` runs
inside `generate._call_gemini`, so a prompt captured before the call would be the
pre-trim text and would differ from what the provider received whenever the
30 000-char safety valve fires. Logging happens per attempt **before** the call,
so the failures are recorded too — those are the rows that explain why the
expected model was not used.

Logging is best effort: a broken prompt log never fails a generation.

### Which pages research tried, and what happened to them

`story_research.json` records only what **survived** — promoted sources, their
claims, the fact ids. It says nothing about the pages that were dropped, and the
round has several drop points: a wrapper/social host, a blocked domain, a
duplicate publication, a page with no usable prose, and the claim gate. So
"did it look anywhere else?" had no answer in the product.

```bash
newsroom stories research-trace                     # every page considered
newsroom stories research-trace --story-id s-abc123 # one story
newsroom stories research-trace --outcome KEPT      # only what survived
newsroom stories research-trace --outcome SKIPPED_NO_PROSE
newsroom stories research-trace --limit 20
newsroom stories research-trace --json
```

Store: `var/editorial_workflow/research_trace.jsonl`, mode `0600`. It reads the
trace — it never re-runs research and never spends a credit.

```
КРЪГ 2026-10-01T17:16:39Z  story=s-one  разгледани=3  запазени=2  факти=2  отхвърлени от claim gate=0
    въпрос: Кога изтича срокът за кандидатурите?

· SKIPPED_NON_PUBLISHER  facebook.com   host facebook.com is a wrapper/social page (§18)
✓ KEPT                   official.test  source_id: src_1e26c1ea02dac218
✓ KEPT                   second.test    source_id: src_206cf44033f87669
```

| outcome | meaning |
|---|---|
| `KEPT` | read, yielded claims, and the claim gate promoted it |
| `SKIPPED_NON_PUBLISHER` | wrapper/social host (§18) — **the most common drop**, and it happens *before* the reading loop |
| `SKIPPED_BLOCKED` | blocked domain |
| `SKIPPED_DUPLICATE` | same publisher page already used this round or an earlier one |
| `SKIPPED_NO_PROSE` | opened fine, but no candidate claims — from outside this looks identical to a page never fetched |
| `SKIPPED_CLAIM_GATE` | claims existed but no independent publisher corroborated them |

Separate store because `story_research_store._row()` validates a **closed** field
set (`req <= set(v) <= req | optional`) — adding a trace field to the research row
would break that contract. The row is the canonical assessment the editor reads.

Dropped pages record the url, host and reason, **not** the scraped text: this
store answers "what happened", and keeping page bodies would duplicate the
private evidence stores at a size nobody asked for.

### Joining research to the prompt

The chain is complete and greppable, which is what makes the two commands one
investigation rather than two:

```
research_trace row (source_id)
  → story_research.json  sources[].id            + claims[].text
  → facts[].sourceId / .locator
  → draft prompt         - [fact_…] (current_event) …
  → model_prompts.jsonl  request_id + model      ← which model got it
```

`fact_ids` are `sha256(story_id \0 source_id \0 text)`, so a fact in the prompt
identifies its source without guessing. Note that a **live** evidence packet's
facts carry `source_reference: "source_text"` and a single packet-level
`source_url` — per-fact source attribution exists on the RESEARCH path, not on
the live-evidence path.

### Operational rules

- **Cadence is real.** An `each_run` source is always collected; a `daily` source
  only if it has not *succeeded* on the current Sofia date; `weekly` needs 7 local
  days; muted/disabled are never collected. The dry-run lists who was skipped and
  why. `--force` overrides cadence deliberately.
- **Health is separate from settings** (`var/newsroom/source_health.json`):
  `OK` / `EMPTY` / `FAILED` / `NEVER_RUN`. `EMPTY` means the collector worked and
  found nothing; `FAILED` means the collector is broken — the Workbench shows both.
- **Rolling recency, every run.** Dated news items older than 72 h are excluded on
  run 1 **and** on every later run, so a second run cannot backfill what the first
  deliberately dropped. The *first* successful run of a source additionally caps to
  the 10 newest items (safe bootstrap) and every run keeps the 20-per-source cap. A
  candidate without a readable date is kept, so a source is never emptied over a
  missing timestamp. Real measurement: 0 stored rows older than 72 h after two
  immediate runs.
- **Calendar semantics are honest.** The ±45-day window is applied only when the
  collector supplies a real `event_at`/`event_end_at`. A Google News result's
  `published_at` is the *article* time, so a `calendar=True` source without real event
  dates behaves like ordinary news — the system never pretends to know the event date.
- **Blocked domains** (`/sources` → «Забранени домейни»): `flagman.bg` is blocked
  by default. Broad monitoring results are filtered before they reach the inbox and
  a direct source on a blocked domain is refused. The filter uses the publisher
  domain from the Google News `<source url>` attribute, because the item link is an
  opaque `news.google.com` redirect.
- **One shared lock** (`var/newsroom/collect.lock`, 1 h stale window) prevents two
  concurrent runs from interleaving inbox/health writes.

Workbench pages: `http://127.0.0.1:8123/stories`, `…/inbox` (Материали) and
`…/sources`. Reports: `m4/review/M4A1_DEFAULT_SOURCE_PACK_REPORT.md`,
`m4/review/M4B_DAILY_INBOX_REPORT.md`, `m4/review/M4B1_FEED_STABILIZATION_REPORT.md`,
`m4/review/M4C_STORY_IDENTITY_REPORT.md`, `m4/review/M4C_STORY_REVIEW_PACK.md`.

### M4C story stores and recovery

```text
var/newsroom/inbox.jsonl     raw collected rows (never rewritten by story work)
var/newsroom/stories.json    story store: members reference inbox item_ids
var/newsroom/             + collect.lock, source_health.json, last_run.json,
                            blocked_domains.json, newsroom_actions.jsonl (audit)
```

- `NEWSROOM_STORIES_PATH` overrides the story store path (same pattern as the other
  newsroom stores).
- The story role is its own model pool: `GEMINI_STORY_MODELS` (defaults to the draft
  pool, never the Lite judge pool) or `OPENROUTER_STORY_MODEL` for the OpenRouter arm.
  A missing/rate-limited/invalid model **never** merges anything — affected items stay
  separate stories flagged `за преглед`, and the run reports the failure count.
- Editor corrections (split/merge in the story page) are stored as overrides. A
  `stories rebuild --apply` refuses to run while overrides exist unless `--force` is
  passed; the normal path is always the incremental `stories update`/`refresh`.
- Recovery: deleting `stories.json` does **not** lose any collected material — the
  next `stories update` rebuilds stories from the inbox. Deleting `inbox.jsonl` does
  lose raw rows, so back it up if you are debugging.

## 0f. The editor's two surfaces: `Днес` and `Чернова` (V1.2-G4.1)

### The desk is regional by default

`Днес` (`/`) is a **Burgas-region working desk**, not a national-news list. The
scope is decided on the server by one deterministic rule (`workflow/regional_scope.py`)
and the toolbar has a quiet two-position switch:

| Position | Meaning |
|---|---|
| `Регионът` (default) | local sources, a named Burgas locality, or work in progress |
| `Всички` | the whole horizon, unfiltered |

Nothing is ever deleted. `Истории` (`/stories`) always reaches every collected
Story, and `?scope=all` is the same unfiltered projection. The client never
filters by locality itself — which Stories are regional is a backend decision.

A source is regional when its registry `kind` is `official` or `regional`
(`Надежен` is irrelevant to locality: BTA/BNR are national publishers, and a
national item only qualifies when its own text names a Burgas locality).

```bash
curl -s 'http://127.0.0.1:8123/api/v1/today?scope=region' | head -c 400
curl -s 'http://127.0.0.1:8123/api/v1/today?scope=all'   | head -c 400
```

### A Draft is not a finished article

`Направи чернова` is offered whenever there is **some** source-backed material:

- confirmed facts with an opened source (`PROMOTED`);
- one opened official source the editor marked reliable (`PRIMARY`);
- one real opened publisher page (`SINGLE_SOURCE`) — always attributed and
  always warned: *«Информацията е от един източник и не е независимо
  потвърдена.»*

An open question is a **warning that travels with the Draft**, never a refusal.
The single remaining blocker is `Няма достатъчно изходен материал за чернова.` —
no opened page at all, or only a discovery snippet behind a title.

`Отбележи като готова` is the real boundary. An open question, an unsupported
claim or a known conflict still stops it, so a Draft can be written, edited and
autosaved freely and only declared finished once the evidence holds it up.

The Article states are unchanged: `Подготовка` → `Чернова` → `Готова`.

## 1. Normal manual cycle

```text
poll → inspect result → inspect pending alerts → dry-run preview
→ optional explicit send → stop
```

### A. Poll (one explicit command, runs once and exits)

```bash
PYTHONPATH=src python3 -m editor_assistant.poll
```

Only supported flags: `--db` (default `var/editor_assistant.sqlite3`),
`--feed-url` (default `https://burgascouncil.org/last-update.xml`).
There is no `--send` flag on the poll command by design.

Expected report shape:

```text
source: burgas-municipal-council
fetched: N
parsed: N
NEW: X
UPDATED: Y
UNCHANGED: Z
new_outbox_intents: K
pending_total: P
status: OK
```

With changes, a short `NEW:` / `UPDATED:` title+URL list follows
(no article bodies).

### B. Interpret result

Case 1 — nothing new:

```text
NEW = 0 and UPDATED = 0 → STOP
```

No Telegram review is required unless previously pending alerts are
intentionally being processed.

Case 2 — something changed:

```text
NEW > 0 or UPDATED > 0 → review the newly queued alerts first.
```

Do not automatically send.

## 2. Review pending notifications (existing CLI is sufficient)

```bash
PYTHONPATH=src python3 -m editor_assistant.send_telegram
```

Default behavior is and must remain:

```text
preview only / 0 HTTP writes / 0 delivered rows changed
```

It previews the oldest pending alert first (`limit = 1` default,
hard max 5). Do not introduce a new review application.

## 3. Editorial review checklist (before any send)

- source display name is correct;
- headline/subject is understandable;
- no duplicated excerpt;
- date is plausible;
- attachments look reasonable;
- source URL is present;
- no raw HTML;
- no obvious parser noise;
- no source-derived fact appears altered.

If the alert looks suspicious:

```text
DO NOT SEND — record the issue, do not edit source/state data manually.
```

## 4. Explicit send (only after successful dry-run review)

```bash
set -a; . ./.env; set +a   # TEST credentials live only in git-ignored .env
env DRY_RUN=false PYTHONPATH=src python3 -m editor_assistant.send_telegram --send
```

Real sending requires ALL of `--send` + `DRY_RUN=false` + configured
`TELEGRAM_TEST_BOT_TOKEN` / `TELEGRAM_TEST_CHAT_ID`.
Keep `limit = 1` (one-at-a-time) during this manual phase; do not use
the hard-max batch as routine. Never inspect or log credentials.

## 5. After-send verification

Confirm the CLI prints:

```text
status: SENT
telegram_message_id: <id>
remaining_pending: P-1
```

## 6. Failure workflow

Poll failure (`status: ERROR`) is NOT "no news": do not interpret it as
such and do not send anything based on that poll cycle. Typical causes:
network timeout, HTTP error, invalid RSS, parse failure, SQLite failure.
State is untouched when fetch/parse fails; a failed batch leaves no
partial state (atomic guarantees in `state/store.py`).

Telegram failure: the row remains PENDING. Do not manually mark it
delivered. Correct the operational issue and retry explicitly.
Delivery semantics are at-least-once: a rare duplicate is preferable
to silently losing an alert.

## 7. Existing backlog (do not confuse with new content)

The runtime DB currently holds historical queued alerts from the first
live ingestion (18 PENDING at time of writing). Their existence is not
newly detected content. Process or leave them pending deliberately;
do not bulk-send merely to empty the queue.

## 8. Natural-use observation period

Use the manual workflow over several normal real-world cycles. Do not
intentionally manufacture changes (no source/state edits to force
NEW/UPDATED). For each poll record only:

```text
date/time / NEW / UPDATED / UNCHANGED / new intents / pending total
/ operator action
```

If the live source naturally produces a new item, record whether
`NEW → outbox` works; if an existing item naturally changes, record
whether `UPDATED → new version intent` works.

## 9. What to watch for (record actual pain points only)

Duplicate alerts, false UPDATED, missed obvious new item, malformed
subject, unusable attachment list, source outage, confusing operator
workflow, Telegram delivery problem. Do not proactively optimize
anything else.

## 10. No engineering during observation

Do NOT add: scheduler, cron, retries, polling daemon, automatic
Telegram delivery, new sources, AI, classification, priority, or new
renderer features. If a problem appears: observe → document →
continue. Fix only after the pattern is understood.

## 11. Readiness gate for scheduling

Do not begin scheduled polling until manual use demonstrates: repeated
polls are stable; no false duplicate intents; at least one natural NEW
handled correctly (ideally one natural UPDATED, not mandatory if rare);
failures clearly visible; operator understands poll → review → send;
renderer remains useful; no recurring manual workaround required.

## Verification evidence (2026-09-13, this machine)

Poll (live, real feed):

```text
source: burgas-municipal-council
feed_url: https://burgascouncil.org/last-update.xml
fetched: 20
parsed: 20
NEW: 0
UPDATED: 0
UNCHANGED: 20
new_outbox_intents: 0
pending_total: 18
status: OK
```

Action per §1B Case 1: STOP (no Telegram review of new content;
backlog left pending deliberately). No send performed.

Dry-run preview (existing CLI, default path, zero HTTP):

```text
destination: telegram-test
pending_total: 18
selected: 1
mode: DRY RUN (no --send flag)
--- message 1 (outbox_id=3, NEW v1) ---
(oldest pending alert renders: source label, subject headline,
BG local date, attachments, source URL)
```

Review checklist on the previewed alert (outbox_id=3, node 3635):
source name correct; headline understandable; no duplicated excerpt;
date plausible (11.09.2026); attachments reasonable (PDF + DOC);
source URL present; no raw HTML; no parser noise; no altered facts.
State/outbox consistency (read-only audit): 20 state rows, 18 PENDING,
2 delivered — unchanged by poll + dry-run.

Optionally verify visually in the TEST Telegram chat.
