"""M1.3 local proof: fixture items -> identity+fingerprint -> SQLite state.

Usage:
  PYTHONPATH=src python3 -m editor_assistant.check_state [--db PATH] [--live URL]
Default: 3-run deterministic proof on the M1.1 fixture (tmp DB unless --db).
--live: one disposable read-only sequence against the council feed (not pytest).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

from editor_assistant.models import SourceDef
from editor_assistant.sources.fetcher import fetch_bytes
from editor_assistant.sources.live import BURGAS_MUNICIPAL_COUNCIL
from editor_assistant.sources.rss import PARSER_ID, item_to_dict, parse_rss_feed
from editor_assistant.state import ItemStatus, process_items

FIXTURE = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "rss_burgas_municipality.xml"
FIXTURE_SOURCE = SourceDef(
    source_id="burgas-municipality-press",
    canonical_url="https://www.burgas.bg/press",
    parser=PARSER_ID,
)


def _summarize(results) -> dict[str, int]:
    out = {"NEW": 0, "UNCHANGED": 0, "UPDATED": 0}
    for res in results:
        out[res.status.value] += 1
    return out


def _run_fixture(db: str) -> int:
    t0 = datetime(2026, 9, 12, 10, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 12, 11, tzinfo=timezone.utc)
    items = parse_rss_feed(FIXTURE.read_bytes(), source=FIXTURE_SOURCE, fetched_at=t0)
    r1 = process_items(items, t0, db_path=db)
    print("RUN 1:", _summarize(r1))
    r2 = process_items(items, t1, db_path=db)
    print("RUN 2:", _summarize(r2))
    changed = [dataclasses.replace(items[0], title=items[0].title + " (обновено)"), items[1]]
    r3 = process_items(changed, t1, db_path=db)
    print("RUN 3:", _summarize(r3))
    for res in r3:
        print(f"  {res.status.value} {res.item_url} version_no={res.version_no}")
    return 0


def _run_live(db: str, url: str) -> int:
    fetched = fetch_bytes(url)
    now = datetime.now(timezone.utc)
    items = parse_rss_feed(fetched.payload, source=BURGAS_MUNICIPAL_COUNCIL, fetched_at=now)
    r1 = process_items(items, now, db_path=db)
    r2 = process_items(items, datetime.now(timezone.utc), db_path=db)
    print(json.dumps({"feed_url": url, "bytes": len(fetched.payload)}, ensure_ascii=False))
    print("LIVE RUN 1:", _summarize(r1))
    print("LIVE RUN 2:", _summarize(r2))
    unexpected = [r for r in r2 if r.status == ItemStatus.UPDATED]
    print(f"unexpected_updated_count: {len(unexpected)}")
    for res in unexpected:
        item = next(i for i in items if i.item_url == res.item_url)
        print(json.dumps(item_to_dict(item), ensure_ascii=False)[:500])
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM item_state").fetchone()[0]
    print(f"rows_in_state: {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    parser.add_argument("--live", default=None)
    args = parser.parse_args(argv)
    if args.live:
        db = args.db or str(pathlib.Path(tempfile.mkdtemp()) / "live.sqlite3")
        return _run_live(db, args.live)
    if args.db:
        return _run_fixture(args.db)
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as tmp:
        return _run_fixture(tmp.name)


if __name__ == "__main__":
    sys.exit(main())
