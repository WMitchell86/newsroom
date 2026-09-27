"""V1.2-G2.3 §25/§27: the same 24 Stories, before and after the repair.

DIAGNOSTIC. Runs the REAL `execute_story_research` over the FROZEN G2.1 sample
(§25: the same Stories, so the funnel is comparable), on a temporary copy of the
real stores. The newsroom itself is opened read-only and never written.

For each Story it records the whole funnel, not a verdict:

    pages opened
    candidate claims extracted
    usable claims after chrome filtering
    PRIMARY-supported facts
    corroborated facts
    conflicts detected
    Stories with >= 1 usable fact
    Stories left with a blocking gap

Semantic comparison uses the project's own model route, exactly as the product
does. Its availability is recorded, because UNCERTAIN is the honest answer when
it is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

G21_EVIDENCE = ROOT / "m4" / "review" / "evidence" / "v1_2_g2_1_open_source_audit.json"


def frozen_sample() -> list[str]:
    """The exact G2.1 sample (§25), in its recorded order."""
    data = json.loads(G21_EVIDENCE.read_text(encoding="utf-8"))
    return [row["story_id"] for row in data["sampled"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--newsroom", default=str(ROOT / "var" / "newsroom"))
    parser.add_argument("--editorial", default=str(ROOT / "var" / "editorial_workflow"))
    parser.add_argument(
        "--out",
        default=str(ROOT / "m4" / "review" / "evidence" / "v1_2_g2_3_replay.json"),
    )
    args = parser.parse_args()

    from editor_assistant.workflow import inbox_store, story_store

    source_newsroom, source_editorial = Path(args.newsroom), Path(args.editorial)
    stories = story_store.read_store(source_newsroom / "stories.json")["stories"]
    by_id = {row["story_id"]: row for row in stories}
    items_by_id = {
        row["item_id"]: row for row in inbox_store.read_items(source_newsroom / "inbox.jsonl")
    }
    workdir = Path(tempfile.mkdtemp(prefix="g23-replay-"))
    newsroom, editorial = workdir / "newsroom", workdir / "editorial"
    shutil.copytree(source_newsroom, newsroom)
    if source_editorial.exists():
        shutil.copytree(source_editorial, editorial)
    else:
        editorial.mkdir(parents=True)
    os.environ["WB_NEWSROOM_DIR"] = os.environ["NEWSROOM_DIR"] = str(newsroom)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(editorial)

    for module in [m for m in list(sys.modules) if m.startswith("editor_assistant")]:
        del sys.modules[module]
    from editor_assistant.sources import web_fetch
    from editor_assistant.workflow import (
        claim_quality,
        single_source_policy,
        story_research,
        story_research_store,
    )
    from editor_assistant.workflow import (
        editor_application as app,
    )
    from editor_assistant.workflow import (
        search as search_mod,
    )

    # Observation only: the extractor and the page opener are WRAPPED, never
    # replaced, so the measured run is the real one.
    #
    # V1.2-G2.4: the wrapper signature follows the new keyword arguments
    # (`blocks`, `anchors`) so the measurement keeps observing the real
    # extraction rather than silently measuring a different call shape.
    stats = {
        "pages_opened": 0,
        "candidates": 0,
        "usable": 0,
        "chrome_rejected": 0,
        "wrong_event_rejected": 0,
        "heading_blocks_skipped": 0,
    }
    # Observation only: the discovery round is WRAPPED, never replaced, so the
    # measured run is the real one and the operation it produced is captured for
    # the G2.4B frozen replay.
    real_discovery = search_mod.run_event_discovery
    last_operation = {}

    def _discovery(**kwargs):
        op = real_discovery(**kwargs)
        last_operation.clear()
        last_operation.update(op)
        return op

    real_fetch = web_fetch.fetch_page
    real_select = claim_quality.select_candidate_claims
    real_compare = story_research.claim_equivalence.compare_claims
    real_agrees = claim_quality.agrees_with_event
    verdicts = {"SAME_FACT": 0, "DIFFERENT_FACT": 0, "CONFLICT": 0, "UNCERTAIN": 0}
    model_calls = [0]

    def _fetch(url, **kw):
        page = real_fetch(url, **kw)
        if isinstance(page, dict) and str(page.get("text") or "").strip():
            stats["pages_opened"] += 1
        return page

    def _select(sentences, questions, *, limit=4, topic="", blocks=None, anchors=None):
        rows = real_select(
            sentences, questions, limit=limit, topic=topic, blocks=blocks, anchors=anchors
        )
        stats["candidates"] += len(rows)
        units = blocks if blocks is not None else sentences
        for block in units or []:
            if isinstance(block, dict):
                if block.get("kind") != "PROSE":
                    stats["heading_blocks_skipped"] += 1
                value = str(block.get("text") or "").strip()
            else:
                value = str(block or "").strip()
            if not value:
                continue
            if not claim_quality.is_factual_candidate(value):
                stats["chrome_rejected"] += 1
            elif anchors is not None and not real_agrees(value, anchors, topic=topic):
                stats["wrong_event_rejected"] += 1
        stats["usable"] += len(rows)
        return rows

    def _compare(a, b, **kw):
        verdict = real_compare(a, b, **kw)
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if verdict != "CONFLICT":
            model_calls[0] += 1
        return verdict

    search_mod.run_event_discovery = _discovery
    web_fetch.fetch_page = _fetch
    claim_quality.select_candidate_claims = _select
    story_research.claim_equivalence.compare_claims = _compare

    # Every sampled Story starts UNASSESSED in the copy, so each one really
    # runs the first round the editor would trigger.
    store_path = editorial / "story_research.json"
    existing = (
        json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {"stories": []}
    )
    sample_ids = frozen_sample()
    existing["stories"] = [row for row in existing["stories"] if row["story_id"] not in sample_ids]
    store_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {"sample": sample_ids, "stories": [], "totals": {}, "verdicts": verdicts}

    for story_id in sample_ids:
        story = by_id.get(story_id)
        if story is None:
            continue
        representative = items_by_id.get(story.get("representative_item_id")) or {}
        # The Story itself carries no title: the product derives it from the
        # representative item, with the G2.1 editorial cleaning. The replay must
        # search for exactly the same topic the editor's click would use.
        title = app._story_title(story, items_by_id)
        row = {
            "story_id": story_id,
            "title": title,
            "item_url": representative.get("url") or "",
            "opens": 0,
            "candidates": 0,
            "usable": 0,
            "facts": 0,
            "primary_facts": 0,
            "corroborated_facts": 0,
            "conflicts": 0,
            "gap": "",
            "error": "",
        }
        before = dict(stats)
        seed_urls = tuple(
            url
            for url in (
                (representative.get("url") or ""),
                *[
                    (items_by_id.get(member.get("item_id")) or {}).get("url") or ""
                    for member in (story.get("members") or [])[:3]
                    if isinstance(member, dict)
                ],
            )
            if url
        )
        try:
            story_research.execute_story_research(
                story_id,
                topic=title,
                root=editorial,
                canonical_story={"story_id": story_id},
                story_title=title,
                story_items=list(items_by_id.values()),
                seed_urls=seed_urls,
            )
        except (
            story_research.StoryResearchError,
            ValueError,
            RuntimeError,
            OSError,
        ) as exc:
            # A real round may legitimately refuse; the refusal is recorded, not
            # hidden, because it is part of the measurement.
            row["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        basis = story_research_store.get_story_research(story_id, root=editorial)
        # §2 G2.4B: persist the DISCOVERED candidates. The earlier version kept
        # only the Story's own `item_url`, which made the frozen downstream
        # replay impossible: the URLs existed only in an audit log written into a
        # temp directory the script deleted on exit. G2.4B replays opening ->
        # extraction -> corroboration from these records, so they must survive.
        row["discovered_urls"] = [
            {
                "url": c.get("url"),
                "discovered_by": c.get("discovered_by"),
                "status": (c.get("opened") or {}).get("status"),
                "final_url": (c.get("opened") or {}).get("final_url"),
            }
            for c in (last_operation.get("candidates") or [])
        ]
        row["opens"] = stats["pages_opened"] - before["pages_opened"]
        row["candidates"] = stats["candidates"] - before["candidates"]
        row["usable"] = stats["usable"] - before["usable"]
        row["facts"] = len(basis["facts"])
        primary_ids = {
            source["id"]
            for source in basis["sources"]
            if source.get("authority") == "PRIMARY"
        }
        row["primary_facts"] = sum(
            1 for fact in basis["facts"] if fact["sourceId"] in primary_ids
        )
        row["corroborated_facts"] = row["facts"] - row["primary_facts"]
        row["conflicts"] = sum(1 for gap in basis["gaps"] if gap.get("kind") == "conflict")
        blocking = [gap["question"] for gap in basis["gaps"] if gap.get("blocking", True)]
        row["gap"] = blocking[0] if blocking else ""
        row["all_gaps"] = [gap["question"] for gap in basis["gaps"]]
        row["fact_texts"] = [fact["text"] for fact in basis["facts"]]
        # §E: what the experimental single-source gate would add, evaluated
        # READ-ONLY against the persisted basis. Nothing is written by it.
        row["single_source_experiment"] = single_source_policy.evaluate(
            evidence_status=basis["evidence_status"],
            facts=basis["facts"],
            sources=basis["sources"],
            gaps=basis["gaps"],
        )
        report["stories"].append(row)
        print(
            f"{story_id}  opens={row['opens']} candidates={row['candidates']} "
            f"facts={row['facts']} conflicts={row['conflicts']} {row['error'][:60]}",
            flush=True,
        )

    rows = report["stories"]
    report["totals"] = {
        "stories": len(rows),
        "pages_opened": sum(r["opens"] for r in rows),
        "candidate_claims": sum(r["candidates"] for r in rows),
        "usable_claims": sum(r["usable"] for r in rows),
        "chrome_rejected": stats["chrome_rejected"],
        # §A2/§A4: how much page furniture and how much wrong-event text the new
        # gates removed BEFORE anything could be promoted.
        "heading_or_furniture_blocks_skipped": stats["heading_blocks_skipped"],
        "wrong_event_sentences_rejected": stats["wrong_event_rejected"],
        "facts": sum(r["facts"] for r in rows),
        "primary_facts": sum(r["primary_facts"] for r in rows),
        "corroborated_facts": sum(r["corroborated_facts"] for r in rows),
        "conflicts": sum(r["conflicts"] for r in rows),
        "stories_with_a_fact": sum(1 for r in rows if r["facts"]),
        "stories_with_blocking_gap": sum(1 for r in rows if r["gap"]),
        "research_errors": sum(1 for r in rows if r["error"]),
        "semantic_decisions": model_calls[0],
        # §E: measured, never imposed.
        "stories_draft_eligible_now": sum(
            1 for r in rows if r["single_source_experiment"]["eligible_now"]
        ),
        "stories_draft_capable_single_source": sum(
            1 for r in rows if r["single_source_experiment"]["draft_capable_single"]
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
