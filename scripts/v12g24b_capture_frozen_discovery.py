"""V1.2-G2.4B — the ONE-TIME capture of the frozen discovery set.

Authorised once, under a hard ceiling. The purpose is narrow and is NOT
benchmarking: it produces the measurement artifact G2.4 should have kept, so
that every later replay can run the downstream pipeline with ZERO Serper calls.

Hard conditions, enforced in code rather than in a comment:

* **Hard cap.** `SERPER_GLOBAL_QUERY_BUDGET` is set to the authorised ceiling
  before the run and enforced inside `search.run_event_discovery`, so no loop can
  exceed it. There is no automatic increase anywhere.
* **Stop early.** The capture stops as soon as the sample has enough same-event
  publisher candidates, and the reason is recorded.
* **Persist.** Every Story gets its `discovered_urls` plus the query/result
  provenance that produced them, so the set is auditable and reusable.
* **No benchmarking.** This script never compares backends and never records a
  "which provider won" conclusion.

The real executor is driven unmodified. The output is the frozen input that
`v12g24b_extract_capacity_replay.py` consumes with a Serper tripwire.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

G21 = ROOT / "m4" / "review" / "evidence" / "v1_2_g2_1_open_source_audit.json"

#: Hosts that are wrappers, not publishers (§18). They can never be a source and
#: therefore never count towards "enough same-event candidates".
_WRAPPERS = (
    "news.google.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "tiktok.com", "youtube.com", "linkedin.com", "t.me", "reddit.com",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--newsroom", default=str(ROOT / "var" / "newsroom"))
    parser.add_argument(
        "--out", default=str(ROOT / "m4/review/evidence/v1_2_g2_4b_frozen_discovery.json")
    )
    parser.add_argument(
        "--serper-budget", type=int, default=72,
        help="HARD process-wide Serper ceiling. Never increased automatically.",
    )
    parser.add_argument(
        "--target-publishers", type=int, default=2,
        help="Per Story, the number of independent publishers that counts as covered.",
    )
    parser.add_argument(
        "--stop-when-covered", type=int, default=None,
        help="Stop early once this many Stories have the target. Default: all.",
    )
    args = parser.parse_args()

    # The ceiling is declared BEFORE anything can spend, and is read by the
    # provider path itself.
    os.environ["SERPER_GLOBAL_QUERY_BUDGET"] = str(args.serper_budget)

    from editor_assistant.workflow import (
        editor_application as app,
    )
    from editor_assistant.workflow import (
        inbox_store,
        story_research,
        story_research_store,
        story_store,
    )
    from editor_assistant.workflow import (
        search as search_mod,
    )

    newsroom = Path(args.newsroom)
    stories = {
        r["story_id"]: r
        for r in story_store.read_store(newsroom / "stories.json")["stories"]
    }
    items = {r["item_id"]: r for r in inbox_store.read_items(newsroom / "inbox.jsonl")}
    sample = [row["story_id"] for row in json.loads(G21.read_text(encoding="utf-8"))["sampled"]]

    workdir = Path(tempfile.mkdtemp(prefix="g24b-capture-"))
    news, editorial = workdir / "newsroom", workdir / "editorial"
    shutil.copytree(newsroom, news)
    if (ROOT / "var" / "editorial_workflow").exists():
        shutil.copytree(ROOT / "var" / "editorial_workflow", editorial)
    else:
        editorial.mkdir(parents=True)
    os.environ["WB_NEWSROOM_DIR"] = os.environ["NEWSROOM_DIR"] = str(news)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(editorial)

    # Observation only: the real discovery round is wrapped, never replaced.
    real_discovery = search_mod.run_event_discovery
    last_operation: dict = {}

    def _discovery(**kwargs):
        op = real_discovery(**kwargs)
        last_operation.clear()
        last_operation.update(op)
        return op

    search_mod.run_event_discovery = _discovery

    rows, covered = [], 0
    stop_early_at = args.stop_when_covered if args.stop_when_covered is not None else len(sample)
    stop_reason = "sample complete"

    for story_id in sample:
        if search_mod.serper_remaining() is not None and search_mod.serper_remaining() <= 0:
            stop_reason = "serper ceiling reached"
            break
        story = stories.get(story_id)
        if story is None:
            continue
        title = app._story_title(story, items) or ""
        representative = items.get(story.get("representative_item_id")) or {}
        store = editorial / "story_research.json"
        data = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {"stories": []}
        data["stories"] = [r for r in data["stories"] if r["story_id"] != story_id]
        store.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        error = ""
        try:
            story_research.execute_story_research(
                story_id, topic=title, root=editorial,
                canonical_story={"story_id": story_id},
                story_title=title, story_items=[items],
                seed_urls=(representative.get("url") or "",) if representative.get("url") else (),
            )
        except (ValueError, RuntimeError, OSError) as exc:
            error = f"{type(exc).__name__}: {str(exc)[:160]}"

        op = last_operation
        urls = [
            {
                "url": c.get("url"),
                "discovered_by": c.get("discovered_by"),
                "status": (c.get("opened") or {}).get("status"),
                "final_url": (c.get("opened") or {}).get("final_url"),
            }
            for c in (op.get("candidates") or [])
        ]
        publishers = {
            story_store.publisher_identity(urlsplit(str(u.get("url") or "")).hostname or "")
            for u in urls
            if u.get("status") == "FETCH_OK"
            and not any(w in str(u.get("url") or "") for w in _WRAPPERS)
        }
        publishers.discard("")
        basis = story_research_store.get_story_research(story_id, root=editorial)
        covered_now = len(publishers) >= args.target_publishers
        covered += 1 if covered_now else 0
        rows.append({
            "story_id": story_id, "title": title,
            "discovered_urls": urls,
            "independent_publishers": sorted(publishers),
            "covered": covered_now,
            "serper_queries_this_round": op.get("serper_queries", 0),
            "query_ladder": op.get("query_ladder", []),
            "query_provenance": [
                {"query": q.get("query"), "provider": q.get("provider"),
                 "status": q.get("status"), "results": q.get("results")}
                for q in (op.get("queries") or [])
            ],
            "serper_global_budget": op.get("serper_global_budget"),
            "serper_spent_in_process": op.get("serper_spent_in_process"),
            "facts": len(basis["facts"]), "sources": len(basis["sources"]),
            "fact_texts": [f["text"] for f in basis["facts"]],
            "error": error,
        })
        print(
            f"{story_id} pubs={len(publishers)} q={op.get('serper_queries', 0)} "
            f"spent={search_mod.serper_spend()}/{args.serper_budget} facts={len(basis['facts'])}",
            flush=True,
        )
        if covered >= stop_early_at:
            stop_reason = f"early stop: {covered} Stories reached the target"
            break

    report = {
        "authorised_serper_ceiling": args.serper_budget,
        "serper_queries_spent": search_mod.serper_spend(),
        "serper_credits_consumed": search_mod.serper_spend(),
        "target_publishers_per_story": args.target_publishers,
        "stories_attempted": len(rows),
        "stories_covered": covered,
        "stop_reason": stop_reason,
        "frozen": True,
        "note": (
            "Frozen discovery INPUT for every later G2.4B replay. Consuming "
            "replays run with a Serper tripwire and spend nothing."
        ),
        "stories": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "stories"},
                     ensure_ascii=False, indent=2))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
