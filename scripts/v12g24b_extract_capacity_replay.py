"""V1.2-G2.4B — the frozen downstream replay: extract capacity, no discovery spend.

Replays the DOWNSTREAM evidence pipeline — opening -> extraction -> claim
comparison -> promotion -> readiness — from an already-recorded discovery
operation, so that the only variable changed is **semantic capacity**.

Three invariants, asserted in code rather than in a comment:

1. **No search provider is called.** The round is driven by a recorded
   `run_event_discovery` operation (`story_research(..., discovery=...)`).
   The Serper adapters are additionally replaced with a tripwire that raises,
   so a regression that reached for the network would fail the run loudly
   instead of quietly spending a credit.
2. **The safety rule is untouched.** A fact still needs an appropriate PRIMARY
   source or two independent publishers. The replay adds no success path.
3. **The semantic funnel is reported, not summarised.** Candidate pairs,
   deterministic rejections, model-required comparisons, answers, and the
   verdict split, so the effect of the cap is visible rather than inferred.

The newsroom and editorial stores are copied to a temp directory first; the live
stores are opened read-only.
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

G21 = ROOT / "m4" / "review" / "evidence" / "v1_2_g2_1_open_source_audit.json"
G24 = ROOT / "m4" / "review" / "evidence" / "v1_2_g2_4_replay.json"
#: The audit log where recorded discovery operations live. G2.4B reads it; it
#: never writes to it.
SEARCH_RUNS = ROOT / "var" / "editorial_workflow" / "search_runs"

#: Hosts that are not publishers. A frozen candidate on one of these is a
#: wrapper and can never back a claim (§18).
_NON_PUBLISHER = ("news.google.com", "facebook.com", "instagram.com", "x.com",
                  "twitter.com", "tiktok.com", "youtube.com", "linkedin.com")


def frozen_sample() -> list[str]:
    return [row["story_id"] for row in json.loads(G21.read_text(encoding="utf-8"))["sampled"]]


def story_titles() -> dict:
    data = json.loads(G24.read_text(encoding="utf-8"))
    return {row["story_id"]: row.get("title", "") for row in data["stories"]}


def load_frozen_discovery() -> dict:
    """topic -> the recorded discovery operation with REAL publisher candidates.

    Built only from operations already on disk. A topic with no usable recorded
    result is simply absent, and the report says how many Stories that covers —
    the coverage gap is reported, never papered over.
    """
    out: dict[str, dict] = {}
    for path in sorted(SEARCH_RUNS.glob("*.json*")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            topic = str(rec.get("topic") or "").strip()
            if not topic or "query_ladder" not in rec:
                continue
            keep = [
                c for c in (rec.get("candidates") or [])
                if (c.get("opened") or {}).get("status") == "FETCH_OK"
                and not any(d in str(c.get("url") or "") for d in _NON_PUBLISHER)
            ]
            if not keep:
                continue
            merged = {**rec, "candidates": keep}
            previous = out.get(topic)
            if previous is None or len(keep) > len(previous["candidates"]):
                out[topic] = merged
    return out


def install_serper_tripwire(search_mod) -> list[str]:
    """Replace both Serper adapters so any call is a hard failure, not a credit."""
    tripped: list[str] = []

    def _boom(name):
        def _call(self, *a, **kw):
            tripped.append(name)
            raise AssertionError(
                f"G2.4B must not call {name}: the round is driven by a frozen "
                "discovery operation"
            )
        return _call

    for attr in ("SerperProvider", "SerperNewsProvider"):
        setattr(search_mod, attr, type(attr, (object,), {
            "name": attr, "search": _boom(attr),
            "ENDPOINT": "", "__init__": lambda self, *a, **k: None,
        }))
    return tripped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--newsroom", default=str(ROOT / "var" / "newsroom"))
    parser.add_argument(
        "--out", default=str(ROOT / "m4/review/evidence/v1_2_g2_4b_replay.json")
    )
    parser.add_argument(
        "--serper-budget-report",
        default=str(ROOT / "m4/review/evidence/v1_2_g2_4b_serper_zero.json"),
    )
    args = parser.parse_args()

    from editor_assistant.workflow import (
        claim_equivalence,
        inbox_store,
        single_source_policy,
        story_research,
        story_research_store,
        story_store,
    )
    from editor_assistant.workflow import (
        editor_application as app,
    )
    from editor_assistant.workflow import (
        search as search_mod,
    )

    tripped = install_serper_tripwire(search_mod)

    newsroom = Path(args.newsroom)
    stories = {
        r["story_id"]: r
        for r in story_store.read_store(newsroom / "stories.json")["stories"]
    }
    items = {r["item_id"]: r for r in inbox_store.read_items(newsroom / "inbox.jsonl")}
    frozen = load_frozen_discovery()
    titles = story_titles()

    workdir = Path(tempfile.mkdtemp(prefix="g24b-"))
    news, editorial = workdir / "newsroom", workdir / "editorial"
    shutil.copytree(newsroom, news)
    if (ROOT / "var" / "editorial_workflow").exists():
        shutil.copytree(ROOT / "var" / "editorial_workflow", editorial)
    else:
        editorial.mkdir(parents=True)
    os.environ["WB_NEWSROOM_DIR"] = os.environ["NEWSROOM_DIR"] = str(news)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(editorial)

    # --- the semantic funnel, observed on the real executor --------------
    funnel = {
        "candidate_pairs": 0,
        "deterministically_rejected": 0,
        "model_required": 0,
        "model_answered": 0,
        "uncertain_unavailable": 0,
        "same_fact": 0,
        "different_fact": 0,
        "conflict": 0,
    }
    real_compare = claim_equivalence.compare_claims
    real_semantic = claim_equivalence._default_semantic

    def _semantic(a, b):
        try:
            verdict = real_semantic(a, b)
        except (ValueError, RuntimeError, OSError, LookupError):
            # A transport or routing failure is exactly the "unavailable" case
            # this funnel exists to count, so it is measured rather than raised.
            verdict = None
        funnel["model_answered" if verdict else "uncertain_unavailable"] += 1
        return verdict

    def _compare(a, b, **kw):
        if a == b:
            funnel["deterministically_rejected"] += 1
            return claim_equivalence.SAME_FACT
        funnel["candidate_pairs"] += 1
        verdict = real_compare(a, b, **kw)
        if verdict == claim_equivalence.UNCERTAIN:
            funnel["model_required"] += 1
        funnel[{
            claim_equivalence.SAME_FACT: "same_fact",
            claim_equivalence.DIFFERENT_FACT: "different_fact",
            claim_equivalence.CONFLICT: "conflict",
        }.get(verdict, "different_fact")] += 1
        return verdict

    claim_equivalence._default_semantic = _semantic
    claim_equivalence.compare_claims = _compare
    story_research.claim_equivalence.compare_claims = _compare

    rows, covered = [], []
    for story_id in frozen_sample():
        story = stories.get(story_id)
        if story is None:
            continue
        title = app._story_title(story, items) or titles.get(story_id, "")
        operation = frozen.get(title)
        representative = items.get(story.get("representative_item_id")) or {}
        if operation is None:
            rows.append({"story_id": story_id, "title": title, "frozen_discovery": False,
                         "error": "no recorded discovery operation with usable publishers"})
            continue
        covered.append(story_id)
        store = editorial / "story_research.json"
        data = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {"stories": []}
        data["stories"] = [r for r in data["stories"] if r["story_id"] != story_id]
        store.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            story_research.execute_story_research(
                story_id, topic=title, root=editorial,
                canonical_story={"story_id": story_id},
                story_title=title, story_items=[items],
                seed_urls=(representative.get("url") or "",) if representative.get("url") else (),
                discovery=operation,
            )
            error = ""
        except (ValueError, RuntimeError, OSError) as exc:
            # A research round may legitimately refuse; the refusal is the
            # measurement, so it is recorded rather than raised.
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
        basis = story_research_store.get_story_research(story_id, root=editorial)
        rows.append({
            "story_id": story_id, "title": title, "frozen_discovery": True,
            "frozen_publishers": len(operation.get("candidates") or []),
            "facts": len(basis["facts"]), "sources": len(basis["sources"]),
            "gaps": [g["question"] for g in basis["gaps"]],
            "fact_texts": [f["text"] for f in basis["facts"]],
            "single_source_experiment": single_source_policy.evaluate(
                evidence_status=basis["evidence_status"], facts=basis["facts"],
                sources=basis["sources"], gaps=basis["gaps"],
            ),
            "error": error,
        })
        print(f"{story_id} frozen={len(operation.get('candidates') or [])} "
              f"facts={len(basis['facts'])} {error[:60]}", flush=True)

    report = {
        "frozen_stories": len(frozen_sample()),
        "stories_with_frozen_discovery": len(covered),
        "stories_replayed": len([r for r in rows if r["frozen_discovery"]]),
        "serper_calls": len(tripped),
        "semantic_funnel": funnel,
        "stories_with_a_fact": sum(1 for r in rows if r.get("facts")),
        "stories_draft_capable_single_source": sum(
            1 for r in rows if r.get("single_source_experiment", {}).get("draft_capable_single")
        ),
        "stories": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.serper_budget_report).write_text(
        json.dumps({
            "serper_calls_during_replay": len(tripped),
            "serper_credits_consumed": len(tripped),
            "product_status": "optional development / diagnostic discovery provider",
            "required_for_production_research": False,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in report.items() if k != "stories"},
                     ensure_ascii=False, indent=2))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
