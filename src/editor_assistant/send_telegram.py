"""M1.4B manual delivery runner: PENDING outbox -> Telegram TEST chat.

Default is DRY RUN (preview only, no HTTP, no mark_delivered). Real send
requires BOTH --send AND DRY_RUN=false in the environment, plus configured
TELEGRAM_TEST_BOT_TOKEN / TELEGRAM_TEST_CHAT_ID. Limit defaults to 1, max 5.

Delivery semantics: at-least-once. There is an unavoidable crash window
between a successful Telegram send and the local mark_delivered() write —
if the process dies there, the next run re-sends that row. Duplicates in
the TEST chat are expected and acceptable; losing an alert is not.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from editor_assistant.config import load_config
from editor_assistant.notify.outbox import count_all, list_pending, mark_delivered
from editor_assistant.notify.render import render_message
from editor_assistant.notify.telegram import (
    TelegramSendError,
    load_telegram_test_config,
    send_message,
)
from editor_assistant.state.store import DEFAULT_DB_PATH, TELEGRAM_TEST_DESTINATION

DEFAULT_LIMIT = 1
MAX_LIMIT = 5


def _parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.limit < 1 or args.limit > MAX_LIMIT:
        print(f"limit must be 1..{MAX_LIMIT}", file=sys.stderr)
        return 2
    pending = list_pending(args.db, destination=TELEGRAM_TEST_DESTINATION)
    selected = pending[: args.limit]
    settings = load_config(None)
    if not args.send or settings.dry_run:
        reason = "DRY_RUN=true" if args.send and settings.dry_run else "no --send flag"
        print(f"destination: {TELEGRAM_TEST_DESTINATION}")
        print(f"pending_total: {len(pending)}")
        print(f"selected: {len(selected)}")
        print(f"mode: DRY RUN ({reason})")
        for i, row in enumerate(selected, 1):
            print(f"--- message {i} (outbox_id={row.id}, {row.event_type} v{row.version_no}) ---")
            print(render_message(row.payload), end="")
        return 0
    config = load_telegram_test_config()
    if config is None:
        print("telegram-test not configured (need bot token + chat id)", file=sys.stderr)
        return 2
    sent = 0
    for row in selected:
        text = render_message(row.payload)
        try:
            result = send_message(config, text)
        except TelegramSendError as exc:
            print(f"FAILED outbox_id={row.id}: {exc} (stopped, rest stay PENDING)")
            return 1
        mark_delivered(args.db, row.id, datetime.now(timezone.utc))
        sent += 1
        print(f"destination: {TELEGRAM_TEST_DESTINATION}")
        print(f"outbox_id: {row.id}")
        print("status: SENT")
        print(f"telegram_message_id: {result.message_id}")
    _, pending_left, _ = count_all(args.db)
    print(f"remaining_pending: {pending_left} (sent_this_run: {sent})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
