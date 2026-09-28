# agents.md — operating guide for AI coding agents

How to work in this repo. The human owner reviews every milestone; never skip the gate.

## What this project is
Deterministic RSS-monitoring assistant for the editor-in-chief of chernomorie-bg.com
(Burgas Municipal Council feed): parse → normalize → fingerprint → SQLite state →
durable notification outbox → Telegram TEST-channel delivery. Milestone-driven,
stdlib-only. Normative harness rules: `AI_HARNESS_EDITOR_ASSISTANT.md` (Bulgarian).
**Current state: `CURRENT_STATE.md`** (authoritative).

## Non-negotiables
- `AUTO_PUBLISH=false`, `DRY_RUN=true` are hard defaults; `config.py` forces
  auto_publish off regardless of env.
- The only external write is the Telegram **TEST** channel, gated behind
  `--send` + `DRY_RUN=false` + env credentials. Dry-run (no HTTP) is the default.
- No new dependencies. Stdlib only (`urllib`, `sqlite3`, `html.parser`, `argparse`, `json`).
- Scope lock: implement the current milestone only; new ideas go to `BACKLOG.md`, never into the change.
- STOP after each milestone: update `MILESTONE.md`, commit, wait for review.
- Never commit secrets (`.env`, tokens) or runtime DBs (`var/`, `*.sqlite3` are git-ignored).
  Never put the Telegram token in URLs, logs, or error messages.

## Toolchain (exact commands)
```bash
PYTHONPATH=src python3 -m pytest -q        # full suite, offline
ruff check src tests && ruff format src tests
PYTHONPATH=src python3 -m editor_assistant.check_state       # state proof (state-only by default)
PYTHONPATH=src python3 -m editor_assistant.send_telegram     # dry-run preview (zero HTTP)
```
- `pip install -e .` is blocked on this machine (PEP 668 externally-managed env) — always run with `PYTHONPATH=src`.
- Commits: author `editor-assistant <editor-assistant@chernomorie-bg.com>`, subject prefix `M<x.y>:` (or `docs:`/`chore:`).

### Long test runs — never let one pin the machine at 100% CPU
This suite is slow enough that a careless launch has already frozen this host
(an agent had to restart it). The offline suite is ~2000 tests, the browser suite
drives real Chrome and a real HTTP server, and individual tests can hold a socket
open for their whole timeout. Four rules, all mandatory:

1. **One run at a time.** Never background a test run (`&`) and then start
   another while the first may still be alive. Check first:
   `pgrep -af 'pytest|vitest|chrome' | wc -l` — if the answer is not `0`, stop
   and clean up before launching anything.
2. **Never re-launch to "check progress."** A run that was started once is either
   running or finished. Read its output file instead of starting it again.
3. **Prefer a bounded, in-foreground run.** Use `timeout 25 ...` and a narrow
   selection (`<file>`, `-k`) so the command returns inside the tool's own limit.
   Reserve background runs for the genuinely long suites (full `pytest`, all of
   `tests/browser/`), and then poll the output file with `sleep` in a *separate*
   command.
4. **`sleep` between polls must never be combined with launching work.** A
   `sleep` that outlives a backgrounded run is what turns "waiting" into
   "relaunching". Poll, read, decide — then act once.

The browser suite serves the **built** frontend from `frontend/dist`, so
`cd frontend && npm run build` is required after any frontend change or the
browser tests silently validate the previous bundle. Symptom: a locator waits for
a control that provably exists in the source. The suite skips with
`production build missing` if `dist/` is absent.

## Repo map
```text
src/editor_assistant/
  sources/      rss.py (RSS 2.0 parser), fetcher.py (read-only HTTP), html_desc.py, live.py
  state/        fingerprint.py (SHA-256 identity), store.py (SQLite item_state + process_items)
  notify/       outbox.py (durable intents), render.py (plain-text renderer), telegram.py (transport)
  check_state.py, fetch_live.py, send_telegram.py    CLI entry points
tests/          offline tests; all HTTP mocked
fixtures/       rss_burgas_municipality.xml (2 items), rss_description_html.xml
.ai/skills/     harness skill files
var/            runtime SQLite (git-ignored, never committed)
```

## Code conventions (keep these — do not "fix" them)
- **Import-cycle pattern is intentional**: `state/store.py` lazily imports
  `notify.outbox` (`init_outbox`, `enqueue_notification`) and `notify.render.build_payload`
  inside functions; `notify/outbox.py` lazily imports `TELEGRAM_TEST_DESTINATION` from
  `state.store` inside functions. Keep lazy; no module-level imports across that pair.
- `TELEGRAM_TEST_DESTINATION = "telegram-test"` lives in `state/store.py`.
- Datetimes: timezone-aware UTC everywhere; naive datetimes raise (`StateError` / `SourceParseError`).
- Fingerprints ignore transport fields (`fetched_at`, `source_url`, URLs).
- `process_items(..., destination=None)`: `None` = state-only (no intents). Pass
  `destination=TELEGRAM_TEST_DESTINATION` explicitly to enqueue. Foreign destinations raise `StateError`.
- Outbox uniqueness `(destination, source_id, item_url, version_no)` + `INSERT OR IGNORE`
  — first intent wins, reprocessing never duplicates.
- Telegram transport: `{chat_id, text}` only, plain text, no parse_mode; success requires
  JSON `ok=true` AND `result.message_id`; all failures → `TelegramSendError` (token redacted);
  >4096 chars rejected locally before HTTP (row stays PENDING); explicit 15 s timeout.
- Delivery is **at-least-once** (crash window between send and `mark_delivered` is documented
  and accepted). No retries, no scheduler, no production channel.

## Guards (tests that protect the rules)
- `tests/test_smoke.py::test_no_publish_or_external_write_paths_exist` forbids
  `publish`/`wordpress`/`n8n`/`requests`/`httpx` tokens in `src/**`. Only exceptions:
  `config.py` `auto_publish`, `fetcher.py` `urllib`, and the two allow-listed telegram
  delivery files (`notify/telegram.py`, `send_telegram.py`). Do not widen without an approved scope change.
- Tests must never touch the network — mock the transport (see `tests/test_telegram*.py`).

## Session workflow
1. Read, in order: **`CURRENT_STATE.md`** → `agents.md` → the current
   milestone/report. Read `handoff.md` / `MILESTONE.md` **only for history** —
   their older sections and any old `HARNESS_PROMPT_*.md` are not current
   instructions.
2. Run the full suite before changing anything; confirm 500+ green.
3. Implement the smallest next step; keep scope locked; keep conventions above.
4. Gate: `ruff check` + full `pytest` + a manual end-to-end proof of the change (CLI or script).
5. Update `MILESTONE.md` and `handoff.md`, commit with the repo identity, STOP for review.
