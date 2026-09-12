"""M1.2 local runner: live RSS -> fetch -> existing rss20 parser -> JSON stdout.

Read-only: no persistence, no Telegram/WordPress/LLM. Prints HTTP envelope,
then the normalized SourceItem list as JSON.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from editor_assistant.sources.fetcher import fetch_bytes
from editor_assistant.sources.live import BURGAS_MUNICIPAL_COUNCIL, LIVE_FEED_URL
from editor_assistant.sources.rss import item_to_dict, parse_rss_feed


def main(feed_url: str = LIVE_FEED_URL) -> int:
    fetched = fetch_bytes(feed_url)
    fetched_at = datetime.now(timezone.utc)
    items = parse_rss_feed(fetched.payload, source=BURGAS_MUNICIPAL_COUNCIL, fetched_at=fetched_at)
    envelope = {
        "feed_url": feed_url,
        "final_url": fetched.final_url,
        "http_status": fetched.status,
        "content_type": fetched.content_type,
        "bytes": len(fetched.payload),
    }
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    print(json.dumps([item_to_dict(i) for i in items], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else LIVE_FEED_URL))
