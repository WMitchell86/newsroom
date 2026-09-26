"""V1.2-G2.1 §B — why the editor so often reads "no opened source".

DIAGNOSTIC ONLY. This script measures the existing canonical research path on
real current Stories. It changes no evidence threshold, no registry row, no
source policy and no product code; it exists to answer one question with numbers
instead of intuition:

    when the editor presses `Чернова` and the workflow says there is no opened
    source, WHICH gate actually failed?

Method (B3/B4):

* the REAL runtime stores are opened **read-only** and copied into a temporary
  root; every run happens in the copy, so the newsroom is never touched;
* a stratified sample of real Stories is drawn (official feeds, regional media,
  national media, Google News discovery, single- and multi-publication, both
  authority settings) — never only failures;
* each sampled UNASSESSED Story runs the real `execute_story_research`, with
  only observational instrumentation: the claim extractor is wrapped to record
  whether it produced a claim, and the page opener is wrapped to record what was
  actually fetched. No product decision is replaced or stubbed;
* the funnel is read back from the canonical stores and the product's own
  search-run audit files: discovered -> opened -> promotable -> claim extracted
  -> fact promoted -> blocking gap.

External calls are the ones the newsroom already makes every day: the free web
search provider and ordinary page fetches. No model route is called and nothing
paid is spent — the bootstrap research path does not generate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: B5 — one dominant category per unsuccessful Story. Ordered by how specific
#: the evidence in the trace is, so a sample is never counted twice.
CATEGORIES = (
    "SEARCH_FOUND_NO_USABLE_SOURCE",
    "PAGE_OPEN_FAILED",
    "NO_FINAL_CANONICAL_URL",
    "BLOCKED_DOMAIN",
    "SOURCE_ALREADY_THE_STORY",
    "NO_RELEVANT_CLAIM_EXTRACTED",
    "CLAIM_NEEDS_CORROBORATION",
    "FACTUAL_AUTHORITY_FALSE",
    "OTHER",
)

#: The one sentence both insufficient-evidence branches persist. Quoted here so
#: B11 can compare the wording against the trace that produced it.
GAP_TEXT = "Не е намерен отворен източник, който потвърждава основното твърдение."


def _stratified_sample(stories, items_by_id, registry, limit):
    """B3: a sample that covers the real corpus, not only its failures."""
    buckets = {
        "official_authority": [],
        "official_discovered_but_third_party": [],
        "regional_no_authority": [],
        "national_authority": [],
        "aggregator_discovery": [],
        "single_publication": [],
        "multi_publication": [],
    }
    for story in stories:
        members = story.get("members") or []
        if not members:
            continue
        item = items_by_id.get(story.get("representative_item_id")) or {}
        source = registry.get(item.get("source_id")) or {}
        publisher = (item.get("publisher_domain") or "").casefold()
        publisher_row = next(
            (
                row
                for row in registry.values()
                if publisher and (row.get("domain") or "").casefold() in publisher
            ),
            None,
        )
        if len(members) == 1:
            buckets["single_publication"].append(story)
        if len(members) > 2:
            buckets["multi_publication"].append(story)
        if source.get("factual_authority"):
            buckets["official_authority"].append(story)
            if publisher_row is None or not publisher_row.get("factual_authority"):
                buckets["official_discovered_but_third_party"].append(story)
        else:
            buckets["regional_no_authority"].append(story)
        if publisher.endswith(("bnr.bg", "bta.bg")):
            buckets["national_authority"].append(story)
        if "news.google.com" in (item.get("url") or ""):
            buckets["aggregator_discovery"].append(story)

    chosen, seen = [], set()
    # A stable round-robin over the buckets keeps the sample balanced instead of
    # letting the largest bucket (official feeds) decide the shape.
    index = 0
    while len(chosen) < limit:
        progressed = False
        for rows in buckets.values():
            if index < len(rows) and rows[index]["story_id"] not in seen:
                seen.add(rows[index]["story_id"])
                chosen.append(rows[index])
                progressed = True
                if len(chosen) >= limit:
                    break
        if not progressed:
            break
        index += 1
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--newsroom", default=str(ROOT / "var" / "newsroom"))
    parser.add_argument("--editorial", default=str(ROOT / "var" / "editorial_workflow"))
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--out", default=str(ROOT / "var" / "g21_audit" / "open_source_audit.json"))
    args = parser.parse_args()

    source_newsroom = Path(args.newsroom)
    source_editorial = Path(args.editorial)

    # ---- read the REAL stores, read-only, before touching anything ----------
    sys.path.insert(0, str(ROOT / "src"))
    from editor_assistant.workflow import inbox_store, story_store

    stories = story_store.read_store(source_newsroom / "stories.json")["stories"]
    items_by_id = {row["item_id"]: row for row in inbox_store.read_items(source_newsroom / "inbox.jsonl")}
    registry = {}
    registry_path = source_newsroom / "sources.json"
    if registry_path.exists():
        registry = {row["source_id"]: row for row in json.loads(registry_path.read_text(encoding="utf-8"))}

    already_assessed = set()
    research_file = source_editorial / "story_research.json"
    if research_file.exists():
        already_assessed = {
            row["story_id"] for row in json.loads(research_file.read_text(encoding="utf-8")).get("stories", [])
        }

    unassessed = [s for s in stories if s["story_id"] not in already_assessed]
    sample = _stratified_sample(unassessed, items_by_id, registry, args.limit)

    workdir = Path(tempfile.mkdtemp(prefix="g21-audit-"))
    newsroom = workdir / "newsroom"
    editorial = workdir / "editorial"
    shutil.copytree(source_newsroom, newsroom)
    if source_editorial.exists():
        shutil.copytree(source_editorial, editorial)
    else:
        editorial.mkdir(parents=True)
    for name in ("WB_NEWSROOM_DIR", "NEWSROOM_DIR"):
        os.environ[name] = str(newsroom)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(editorial)

    # Re-import against the isolated roots.
    for module in [m for m in list(sys.modules) if m.startswith("editor_assistant")]:
        del sys.modules[module]
    from editor_assistant.sources import web_fetch
    from editor_assistant.workflow import (
        editor_application as app,
    )
    from editor_assistant.workflow import (
        newsroom_run,
        story_research,
    )
    from editor_assistant.workflow import story_research_store as research_store

    # ---- observational instrumentation only --------------------------------
    policy = newsroom_run.authority_by_domain(newsroom / "sources.json")
    trace = {"claim_attempts": [], "opens": []}
    original_claim = story_research._claim_for_questions
    original_fetch = web_fetch.fetch_page

    def traced_claim(sentences, questions):
        claim = original_claim(sentences, questions)
        trace["claim_attempts"].append(
            {
                "sentences": len(sentences),
                "chars": sum(len(s) for s in sentences),
                "claim_found": bool(claim),
                "claim": claim[:200],
            }
        )
        return claim

    def traced_fetch(url, **kwargs):
        try:
            page = original_fetch(url, **kwargs)
        except Exception as exc:  # the product's own error taxonomy follows
            trace["opens"].append(
                {
                    "url": url,
                    "ok": False,
                    "error": type(exc).__name__,
                }
            )
            raise
        final = page.get("final_url") or ""
        host = re.sub(r"^www\.", "", (final.split("/")[2] if "//" in final else "").casefold())
        row = policy.get(host) or {}
        trace["opens"].append(
            {
                "url": url,
                "ok": True,
                "final_url": final,
                "bytes": page.get("bytes"),
                # B7: the authority the registry actually resolves for the page
                # that was really reached, not for the feed that found it.
                "final_host": host,
                "in_registry": bool(row),
                "factual_authority": bool(row.get("factual_authority")),
                "registry_kind": row.get("kind"),
                "still_aggregator": host.endswith("news.google.com"),
            }
        )
        return page

    story_research._claim_for_questions = traced_claim
    story_research.web_fetch.fetch_page = traced_fetch
    web_fetch.fetch_page = traced_fetch

    report = {
        "sampled": [],
        "totals": {},
        "categories": {},
        "providers": {},
        "notes": [],
    }

    for story in sample:
        story_id = story["story_id"]
        item = items_by_id.get(story.get("representative_item_id")) or {}
        source = registry.get(item.get("source_id")) or {}
        entry = {
            "story_id": story_id,
            "raw_title": item.get("title"),
            "editorial_title": app._story_title(story, items_by_id),
            "discovered_via": item.get("source_id"),
            "discoverer_kind": source.get("kind"),
            "discoverer_authority": source.get("factual_authority"),
            "publisher_domain": item.get("publisher_domain"),
            "item_host": ((item.get("url") or "").split("/")[2] if "//" in (item.get("url") or "") else ""),
            "member_count": len(story.get("members") or []),
            "existing_research": story_id in already_assessed,
        }
        trace["claim_attempts"].clear()
        trace["opens"].clear()

        outcome = {"error": None}
        try:
            app.research_story(story_id)
            basis = research_store.get_story_research(story_id, root=editorial)
            entry["assessed"] = basis.get("evidence_status")
            entry["facts"] = len(basis.get("facts") or [])
            entry["sources"] = len(basis.get("sources") or [])
            entry["gaps"] = [g.get("question") for g in basis.get("gaps") or []]
            entry["error"] = None
        except (RuntimeError, ValueError, OSError) as exc:
            entry["assessed"] = "unassessed"
            entry["facts"] = entry["sources"] = 0
            entry["gaps"] = []
            outcome["error"] = f"{type(exc).__name__}: {exc}"
            entry["error"] = outcome["error"]
            basis = research_store.get_story_research(story_id, root=editorial)

        entry["opens"] = list(trace["opens"])
        entry["claim_attempts"] = list(trace["claim_attempts"])
        entry["claim_found_count"] = sum(1 for c in trace["claim_attempts"] if c["claim_found"])
        entry["opened_count"] = sum(1 for o in trace["opens"] if o.get("ok"))
        # The exact gap the editor will read, if any.
        entry["editor_gap"] = next(
            (g for g in entry["gaps"] if g == GAP_TEXT),
            None,
        )
        entry["category"] = _classify(entry, policy)
        report["sampled"].append(entry)
        print(
            f"{story_id[:14]:16s} opened={entry['opened_count']} claims={entry['claim_found_count']} "
            f"facts={entry['facts']} -> {entry['category']}",
            flush=True,
        )

    report["totals"] = {
        "stories_sampled": len(report["sampled"]),
        "stories_with_opened_pages": sum(1 for e in report["sampled"] if e["opened_count"] > 0),
        "stories_with_a_claim": sum(1 for e in report["sampled"] if e["claim_found_count"] > 0),
        "stories_with_facts": sum(1 for e in report["sampled"] if e["facts"] > 0),
        "stories_with_the_no_open_source_gap": sum(1 for e in report["sampled"] if e["editor_gap"]),
        "research_errors": sum(1 for e in report["sampled"] if e.get("error")),
        "google_news_discovery": sum(
            1 for e in report["sampled"] if "news.google.com" in (e.get("item_host") or "")
        ),
        "official_discoverer_third_party_publisher": sum(
            1
            for e in report["sampled"]
            if e["discoverer_authority"] and e["publisher_domain"]
            and not _publisher_is_authoritative(e["publisher_domain"], policy)
        ),
    }
    for entry in report["sampled"]:
        report["categories"][entry["category"]] = report["categories"].get(entry["category"], 0) + 1
        hosts = {o.get("final_host") for o in entry["opens"] if o.get("ok")}
        entry["opened_hosts"] = sorted(h for h in hosts if h)
        entry["opened_authoritative_hosts"] = sorted(
            h for h in hosts if h and (policy.get(h) or {}).get("factual_authority")
        )
        entry["opened_unregistered_hosts"] = sorted(h for h in hosts if h and h not in policy)
        entry["unresolved_aggregator_opens"] = sum(
            1 for o in entry["opens"] if o.get("ok") and o.get("still_aggregator")
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    print(json.dumps(report["categories"], ensure_ascii=False, indent=2))
    print(f"written: {out}")
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


def _publisher_is_authoritative(publisher_domain, policy) -> bool:
    host = re.sub(r"^www\.", "", (publisher_domain or "").casefold())
    row = policy.get(host)
    return bool(row and row.get("factual_authority"))


def _classify(entry, policy) -> str:
    """B5/B6: exactly one dominant category, from what the trace actually shows."""
    if entry.get("error"):
        return "SEARCH_FOUND_NO_USABLE_SOURCE"
    if entry["facts"] > 0:
        return "OK"
    if entry["opened_count"] == 0:
        # Nothing was fetched successfully at all.
        return "SEARCH_FOUND_NO_USABLE_SOURCE"
    if entry["claim_found_count"] == 0:
        # Pages opened, but the extractor produced no claim for the questions.
        return "NO_RELEVANT_CLAIM_EXTRACTED"
    # A claim was extracted but no fact survived promotion: the corroboration
    # gate. Whether the publishers also lacked authority is reported separately.
    return "CLAIM_NEEDS_CORROBORATION"


if __name__ == "__main__":
    raise SystemExit(main())
