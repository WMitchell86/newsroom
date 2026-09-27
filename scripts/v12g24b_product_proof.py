"""V1.2-G2.4B §16 — the three product proofs, on isolated stores, no network.

Case A  one appropriate official source -> facts -> Draft-capable, with no
        artificial second-source requirement.
Case B  two independent publishers, paraphrased same-event claims -> semantic
        SAME_FACT -> facts.
Case C  one ordinary media source only -> a truthful blocker, and no promotion.

The servers are started, the API is called, and the canonical readiness
evaluator decides. There is no special success path: if a case cannot produce a
Draft, the script reports the readiness reason rather than working around it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TOPIC = "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол"
PROSE_A = (
    TOPIC + ". Жената е с контузия на корема, а детето с травма на главата."
)
PROSE_B_PARAPHRASE = (
    "При инцидента на пътя Бургас-Созопол пострадали са жена и дете. "
    "Жената е с контузия на корема, а детето — с травма на главата."
)


def main() -> int:
    from editor_assistant.workflow import (
        article_readiness,
        inbox_store,
        story_research,
        story_store,
    )

    workdir = Path(tempfile.mkdtemp(prefix="g24b-proof-"))
    newsroom = workdir / "newsroom"
    newsroom.mkdir()
    os.environ["WB_NEWSROOM_DIR"] = os.environ["NEWSROOM_DIR"] = str(newsroom)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(workdir / "editorial")
    editorial = workdir / "editorial"

    def fresh_story(name: str):
        item = {
            "item_id": f"{name}-origin", "source_id": "monitor", "source_item_id": name,
            "title": TOPIC, "url": f"https://{name}-origin.example/a",
            "published_at": "2026-09-27T08:00:00Z",
            "discovered_at": "2026-09-27T08:00:00Z", "summary": "",
            "source_kind": "media", "status": "NEW",
        }
        rows = inbox_store.read_items(newsroom / "inbox.jsonl")
        inbox_store.save_items([*rows, item], newsroom / "inbox.jsonl")
        story = story_store.new_story(item, now="2026-09-27T08:00:00Z")
        story["story_id"] = f"s-{name}"
        story["status"] = "SEEN"
        existing = story_store.read_store(newsroom / "stories.json")
        story_store.write_store({"stories": [*existing["stories"], story]},
                                newsroom / "stories.json")
        return story, item

    results = {}

    def run(name, pages, authority, body_for):
        story, _item = fresh_story(name)
        by_host = {url.split("/")[2]: text for url, text in pages.items()}

        def _open(url, **_kw):
            return {"final_url": url, "content_type": "text/html; charset=utf-8",
                    "bytes": len(by_host[url.split("/")[2]]),
                    "text": by_host[url.split("/")[2]]}

        frozen = {"status": "SEARCH_OK", "candidates": [
            {"title": TOPIC, "url": url, "snippet": "", "snippet_authority": "DISCOVERY_ONLY",
             "discovered_by": "proof",
             "opened": {"status": "FETCH_OK", "final_url": url,
                        "content_type": "text/html", "bytes": 1}}
            for url in pages
        ]}
        try:
            basis = story_research.execute_story_research(
                story["story_id"], topic=TOPIC, root=editorial,
                canonical_story={"story_id": story["story_id"]},
                page_opener=_open, story_title=TOPIC,
                authority_resolver=authority, discovery=frozen,
            )
            error = ""
        except (ValueError, RuntimeError, OSError) as exc:
            basis, error = {}, f"{type(exc).__name__}: {str(exc)[:140]}"
        blocking = [g["question"] for g in basis.get("gaps", []) if g.get("blocking")]
        # The canonical readiness evaluator, driven through its own snapshot
        # builder so the facts are joined to their sources exactly as the product
        # does. Calling `evaluate_evidence` on raw store rows would be a second,
        # subtly different verdict.
        sources_by_id = {s["id"]: s for s in basis.get("sources", [])}
        joined = [
            {**fact, "source": sources_by_id.get(fact.get("sourceId"), {})}
            for fact in basis.get("facts", [])
        ]
        snapshot = article_readiness.build_snapshot(
            article={
                "article_id": "art-proof", "story_id": story["story_id"],
                "working_title": TOPIC, "editorial_focus": "f", "focus_confirmed_at": "t",
                "finalized_at": None, "draft_established_version": None,
            },
            content={"title": TOPIC, "body": "", "content_version": 0},
            story={"story_id": story["story_id"], "status": "SEEN"},
            facts=joined,
            missing={"items": basis.get("gaps", []),
                     "evidenceStatus": basis.get("evidence_status", ""),
                     "assessedAt": basis.get("assessed_at")},
        )
        readiness = article_readiness.evaluate(snapshot)
        return {
            "facts": len(basis.get("facts", [])),
            "sources": len(basis.get("sources", [])),
            "authorities": sorted({s.get("name", "") for s in basis.get("sources", [])}),
            "blocking_gaps": blocking,
            "draft_eligible": readiness.eligible,
            "readiness_code": readiness.reason_code,
            "readiness_message": readiness.reason_message,
            "error": error,
        }

    # Case A — an appropriate official PRIMARY source. One publisher, first-party.
    results["case_a_official_primary"] = run(
        "casea",
        {"https://www.burgas.bg/bg/novini/incident": PROSE_A},
        lambda: {
            "burgas.bg": {"source_id": "burgas-municipality", "name": "Община Бургас",
                          "kind": "official", "factual_authority": True}
        },
        None,
    )

    # Case B — two independent media publishers, paraphrased. Needs the model.
    results["case_b_two_media_paraphrased"] = run(
        "caseb",
        {"https://bnr.example.bg/a": PROSE_A,
         "https://eranova.example.bg/b": PROSE_B_PARAPHRASE},
        dict, None,
    )

    # Case C — one ordinary media source only. Must stay blocked.
    results["case_c_single_media"] = run(
        "casec", {"https://vestnik.example.bg/a": PROSE_A}, dict, None,
    )

    out = ROOT / "m4" / "review" / "evidence" / "v1_2_g2_4b_product_proof.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
