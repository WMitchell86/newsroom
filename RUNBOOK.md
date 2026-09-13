 # Manual Editorial Radar Runbook (M1.6 Step 2)

Operational-verification milestone only. No code changes in this step:
no ingestion, renderer, Telegram transport, state, or polling-code changes.
No scheduling. No automatic delivery.

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
