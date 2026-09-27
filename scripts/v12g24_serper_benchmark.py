"""V1.2-G2.4 §B4/§B5/§B6 — the Serper benchmark on the frozen sample.

Answers, with numbers, on the SAME 24 Stories G2.1 and G2.3 used:

1. **Search vs News.** Which Serper backend has better same-event local-news
   recall? Both are measured; the default is chosen from the measurement.
2. **Combination value.** what each backend finds, by same-event publishers and
   by queries spent.
3. **Budget discipline.** How many Serper queries the bounded round actually
   spends, and what each one buys.

The newsroom is opened READ-ONLY and never written. Snippets are DISCOVERY_ONLY
throughout — this measures discovery and never produces a fact.
"""


from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

G21_EVIDENCE = ROOT / "m4" / "review" / "evidence" / "v1_2_g2_1_open_source_audit.json"


def frozen_sample() -> list[str]:
    """The exact G2.1 sample, so every replay stays comparable."""
    data = json.loads(G21_EVIDENCE.read_text(encoding="utf-8"))
    return [row["story_id"] for row in data["sampled"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--newsroom", default=str(ROOT / "var" / "newsroom"))
    parser.add_argument(
        "--out",
        default=str(ROOT / "m4/review/evidence/v1_2_g2_4_serper_benchmark.json"),
    )
    parser.add_argument("--max-stories", type=int, default=24)
    args = parser.parse_args()

    from urllib.parse import urlsplit

    from editor_assistant.workflow import (
        editor_application as app,
    )
    from editor_assistant.workflow import (
        event_search,
        inbox_store,
        story_store,
    )
    from editor_assistant.workflow import (
        search as search_mod,
    )

    newsroom = Path(args.newsroom)
    stories = {
        row["story_id"]: row
        for row in story_store.read_store(newsroom / "stories.json")["stories"]
    }
    items = {row["item_id"]: row for row in inbox_store.read_items(newsroom / "inbox.jsonl")}

    chain, missing = search_mod.provider_chain(
        capability=search_mod.CAP_NEWS, env=dict(os.environ)
    )
    chain = [p for p in chain if p.name in ("serper", "serper_news")]
    if not chain:
        print(f"SERPER BENCHMARK SKIPPED: no Serper key (unavailable={missing})")
        return 2

    rows = []
    for story_id in frozen_sample()[: max(1, int(args.max_stories))]:
        story = stories.get(story_id)
        if story is None:
            continue
        topic = app._story_title(story, items) or ""
        anchors = event_search.event_anchors(topic)
        ladder = event_search.event_queries(anchors)
        entry = {"story_id": story_id, "topic": topic, "ladder": ladder, "runs": {}}
        for provider in chain:
            used = results = 0
            publishers: set[str] = set()
            for query in ladder:
                if used >= event_search.MAX_SERPER_QUERIES_PER_ROUND:
                    break
                used += 1
                try:
                    attempt = provider.search(query)
                except search_mod.SearchError:
                    continue
                if attempt.get("status") != search_mod.SEARCH_OK:
                    continue
                results += len(attempt.get("results") or [])
                for row in event_search.event_filter(anchors, attempt.get("results") or []):
                    host = (urlsplit(str(row.get("url") or "")).hostname or "").lower()
                    # §B7: the filter already dropped metadata contradictions, so a
                    # surviving result is a same-event candidate.
                    if host:
                        publishers.add(story_store.publisher_identity(host))
            entry["runs"][provider.name] = {
                "queries": used,
                "results": results,
                "same_event_publishers": len(publishers),
                "publishers": sorted(publishers),
            }
        rows.append(entry)
        print(
            story_id
            + " "
            + " | ".join(
                f"{n}: q={r['queries']} res={r['results']} pub={r['same_event_publishers']}"
                for n, r in entry["runs"].items()
            ),
            flush=True,
        )

    totals: dict[str, dict] = {}
    for entry in rows:
        for name, run in entry["runs"].items():
            bucket = totals.setdefault(
                name,
                {
                    "queries": 0,
                    "results": 0,
                    "same_event_publishers": 0,
                    "stories_with_hit": 0,
                },
            )
            bucket["queries"] += run["queries"]
            bucket["results"] += run["results"]
            bucket["same_event_publishers"] += run["same_event_publishers"]
            bucket["stories_with_hit"] += 1 if run["same_event_publishers"] else 0

    report = {
        "sample": [row["story_id"] for row in rows],
        "serper_budget_per_round": event_search.MAX_SERPER_QUERIES_PER_ROUND,
        "totals": totals,
        "stories": rows,
        "note": (
            "Discovery measurement only. No fact is produced here: a Serper result "
            "is a discovery URL, and only an opened page on a real publisher can "
            "later back a claim."
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
