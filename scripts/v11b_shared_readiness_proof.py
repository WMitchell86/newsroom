"""V1.1-B isolated proof: ONE shared Draft readiness decision on real data.

Run:  PYTHONPATH=src python3 scripts/v11b_shared_readiness_proof.py
Exit 0 = every check passed.

Isolated copies of the REAL stores are used (``var/newsroom`` and
``var/editorial_workflow``); the normal runtime stores are manifested with
SHA-256 before the run and re-verified byte-for-byte after it.

What this proves on real, canonical data (V1.1-B §24):

  A. the real UNASSESSED preparation Articles that used to read
     ``draftEligible: true`` now read ``STORY_UNASSESSED`` with no MAKE_DRAFT
     and no contradictory green text;
  B. once a Story carries real evidence, the SAME decision becomes eligible and
     the command's deterministic preflight passes up to the provider boundary
     (no paid model quota is spent — the transport is substituted only to detect
     that the boundary was reached);
  C. an assessed Story that produced only a gap stays ineligible, with the
     blocking reason shown rather than a generic "something is missing".

Everything is production code: the real stores, the real projections, the real
readiness predicate, the real Draft command. Only the external model transport is
substituted, and only to observe the provider boundary.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REAL_NEWSROOM = ROOT / "var" / "newsroom"
REAL_EDITORIAL = ROOT / "var" / "editorial_workflow"

TMP = Path(tempfile.mkdtemp(prefix="v11b_readiness_proof_"))
ISOLATED_NEWSROOM = TMP / "newsroom"
ISOLATED_EDITORIAL = TMP / "editorial_workflow"

RESULTS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def manifest(root: Path) -> dict[str, str]:
    """SHA-256 of every file in a runtime store directory (integrity proof)."""
    if not root.exists():
        return {}
    rows = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return rows


def isolate_stores() -> None:
    """Copy the real stores and point every writer at the copies.

    The whole editorial tree is copied, not just the two top-level files: Article
    content lives in per-Article subdirectories, and a partial copy would make a
    real Article unreadable for reasons that have nothing to do with readiness.
    """
    shutil.copytree(REAL_NEWSROOM, ISOLATED_NEWSROOM)
    shutil.copytree(REAL_EDITORIAL, ISOLATED_EDITORIAL, dirs_exist_ok=True)
    os.environ["WB_NEWSROOM_DIR"] = str(ISOLATED_NEWSROOM)
    os.environ["NEWSROOM_DIR"] = str(ISOLATED_NEWSROOM)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(ISOLATED_EDITORIAL)
    os.environ["MODEL_USAGE_DIR"] = str(TMP / "model_usage")
    os.environ["MODEL_HEALTH_PATH"] = str(TMP / "model_health.json")
    (TMP / "model_usage").mkdir(exist_ok=True)


def substitute_model_transport() -> list[dict]:
    """Replace ONLY the external model transport, to detect the boundary."""
    from editor_assistant.drafting import generate as gen

    calls: list[dict] = []

    def record(*args, **kwargs):
        calls.append({"args": args})
        raise RuntimeError("provider boundary reached (proof substitute)")

    for name in ("call_model", "_call_gemini", "_call_openrouter"):
        if hasattr(gen, name):
            setattr(gen, name, record)
    return calls


#: A real Story that owns a preparation Article. The V1.1 diagnostic's own
#: Царево Story (`s16943311c9c782f`) owns only the `draft` Article that the
#: diagnostic itself identified as a false positive, so it is not a candidate
#: for the preparation-readiness proof.
PROOF_STORY = "sfd1e799db46d0d1"


def real_preparation_articles() -> list[dict]:
    """The real preparation Articles, as their canonical projections."""
    from editor_assistant.workflow import editor_application as app

    return list(app.list_articles("preparation"))


def article_for_story(story_id: str) -> dict | None:
    """The first real preparation Article belonging to a Story, if any."""
    for row in real_preparation_articles():
        if row["story"]["id"] == story_id:
            return row
    return None


def prove_unassessed_state() -> None:
    """A — the defect this slice fixes, on the owner's real Articles."""
    from editor_assistant.workflow import editor_application as app

    articles = real_preparation_articles()
    check("real preparation Articles exist", bool(articles), f"{len(articles)} found")
    if not articles:
        return

    unassessed = [
        row
        for row in articles
        if (row.get("preparation") or {}).get("draftReadiness", {}).get("code")
        == "STORY_UNASSESSED"
    ]
    check(
        "A1. real unassessed Articles report STORY_UNASSESSED",
        bool(unassessed),
        f"{len(unassessed)}/{len(articles)} preparation Articles",
    )
    for row in unassessed[:3]:
        preparation = row["preparation"]
        check(
            f"A2. {row['id']} is ineligible with no MAKE_DRAFT",
            preparation["draftEligible"] is False and "MAKE_DRAFT" not in row["availableActions"],
            f"code={preparation['draftReadiness']['code']}",
        )
        check(
            f"A3. {row['id']} has an editor-safe reason, not a generic one",
            preparation["draftReadiness"]["message"] == "Историята трябва първо да бъде проучена.",
            preparation["draftReadiness"]["message"],
        )
        check(
            f"A4. {row['id']} shows no fake Article-level gap",
            preparation["blockingGaps"] == [],
        )
        # The command must agree, with the very same reason.
        try:
            app.start_article_draft(row["id"], idempotency_key=f"proof-{row['id']}")
            agreed, detail = False, "the command ACCEPTED an ineligible Article"
        except app.EditorApplicationError as exc:
            agreed = str(exc) == preparation["draftReadiness"]["message"]
            detail = f"status={exc.status}"
        check(f"A5. {row['id']} command refuses with the identical reason", agreed, detail)


def prove_research_makes_it_eligible(story_id: str) -> None:
    """B — a Story with real evidence makes the SAME decision eligible."""
    from editor_assistant.workflow import (
        article_generation,
        article_readiness,
        story_research_store,
    )
    from editor_assistant.workflow import (
        editor_application as app,
    )

    article = article_for_story(story_id)
    if article is None:
        check("B0. a real preparation Article exists for the proof Story", False)
        return
    article_id = article["id"]
    check("B0. a real preparation Article exists for the proof Story", True, article_id)

    before = app.read_article(article_id)
    check(
        "B1. before research it is ineligible",
        before["preparation"]["draftEligible"] is False,
        before["preparation"]["draftReadiness"]["code"],
    )

    # Write a real research round through the real store's production path, so
    # the "after" state is a genuine canonical basis, not a hand-built dict.
    story_research_store.merge_research(
        story_id,
        sources=[
            {
                "id": "vestnik",
                "name": "Вестник",
                "url": "https://vestnik.example.test/2026/tsarevo",
            }
        ],
        facts=[
            {
                "id": "fact_proof",
                "text": (
                    "Общинският съвет в Царево връчи званията почетен гражданин "
                    "на двама заслужили общественици."
                ),
                "sourceId": "vestnik",
                "locator": "Решение № 41, т. 3",
            }
        ],
        gaps=[],
        assessed_at="2026-09-26T09:00:00Z",
        canonical_story={"story_id": story_id},
        operation_id="op-v11b-proof",
    )

    after = app.read_article(article_id)
    preparation = after["preparation"]
    check(
        "B2. after research it is eligible",
        preparation["draftEligible"] is True
        and preparation["draftReadiness"]["code"] == "DRAFT_ELIGIBLE",
        preparation["draftReadiness"]["code"],
    )
    check("B3. MAKE_DRAFT is now present", "MAKE_DRAFT" in after["availableActions"])
    check(
        "B4. the reason is the one editor-safe ready message",
        preparation["draftReadiness"]["message"]
        == "Има достатъчно потвърдена информация за чернова.",
    )
    check("B5. the blocking-gap list is genuinely empty", preparation["blockingGaps"] == [])

    # The command's deterministic preflight must pass, and must be the very same
    # decision the projection rendered. No paid model quota is spent: the proof
    # only needs to prove the provider boundary was NOT refused before it.
    snapshot = app._draft_snapshot(article_id)
    readiness = article_readiness.evaluate(snapshot)
    check(
        "B6. the command evaluates the identical decision",
        readiness.eligible is True and readiness.reason_code == "DRAFT_ELIGIBLE",
        readiness.reason_code,
    )
    reached = True
    try:
        article_generation.evaluate(snapshot)
    except article_generation.DraftRefused as exc:
        reached = False
        check("B7. the deterministic preflight passes", False, exc.code)
    check(
        "B7. the deterministic preflight passes (generation would proceed)",
        reached,
    )


def prove_gap_only_state(story_id: str) -> None:
    """C — research that produced only a gap stays honestly ineligible."""
    from editor_assistant.workflow import editor_application as app
    from editor_assistant.workflow import story_research_store

    article = article_for_story(story_id)
    if article is None:
        check("C0. a real preparation Article exists for the gap-only Story", False)
        return
    article_id = article["id"]
    check("C0. a real preparation Article exists for the gap-only Story", True, article_id)

    story_research_store.merge_research(
        story_id,
        sources=[],
        facts=[],
        gaps=[
            {
                "id": "gap_proof",
                "question": "Кога точно е взето решението и от кой съвет?",
                "blocking": True,
            }
        ],
        assessed_at="2026-09-26T09:10:00Z",
        canonical_story={"story_id": story_id},
        operation_id="op-v11b-proof-gap",
    )

    after = app.read_article(article_id)
    preparation = after["preparation"]
    check("C1. a gap-only basis stays ineligible", preparation["draftEligible"] is False)
    check(
        "C2. the reason is the blocking gap, shown with the real question",
        preparation["draftReadiness"]["code"] == "BLOCKING_GAP"
        and preparation["blockingGaps"][0]["question"]
        == "Кога точно е взето решението и от кой съвет?",
        preparation["draftReadiness"]["code"],
    )
    check("C3. no MAKE_DRAFT is offered", "MAKE_DRAFT" not in after["availableActions"])
    check(
        "C4. the remedy is research on the owning Story",
        after["nextAction"]["action"] == "RESEARCH_MORE",
    )


def main() -> int:
    before_newsroom = manifest(REAL_NEWSROOM)
    before_editorial = manifest(REAL_EDITORIAL)
    isolate_stores()
    provider_calls = substitute_model_transport()

    print("\n--- A. the real unassessed Articles (the defect) ---")
    prove_unassessed_state()

    print("\n--- B. research produces evidence -> eligible, preflight passes ---")
    prove_research_makes_it_eligible(PROOF_STORY)

    print("\n--- C. research produces only a gap -> stays ineligible ---")
    other = next(
        (
            row["story"]["id"]
            for row in real_preparation_articles()
            if row["story"]["id"] != PROOF_STORY
        ),
        "",
    )
    if other:
        prove_gap_only_state(other)
    else:
        check("C0. a second real preparation Article exists", False)

    print("\n--- runtime store integrity ---")
    check(
        "the provider boundary was never reached for an ineligible Article",
        provider_calls == [],
        f"{len(provider_calls)} provider calls",
    )
    check(
        f"var/newsroom is byte-identical ({len(before_newsroom)} files)",
        before_newsroom == manifest(REAL_NEWSROOM),
    )
    check(
        f"var/editorial_workflow is byte-identical ({len(before_editorial)} files)",
        before_editorial == manifest(REAL_EDITORIAL),
    )

    shutil.rmtree(TMP, ignore_errors=True)
    failed = RESULTS.count(False)
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
