"""V1.1-C isolated proof: manual continuation is EARNED by a real failure.

Run:  PYTHONPATH=src python3 scripts/v11c_manual_continuation_proof.py
Exit 0 = every check passed.

Isolated copies of the REAL stores are used (``var/newsroom`` and
``var/editorial_workflow``); the normal runtime stores are manifested with
SHA-256 before the run and re-verified byte-for-byte after it.

What this proves on real, canonical data (V1.1-C §24/§30):

  A. every real preparation Article with a confirmed Focus and no genuine
     generation failure offers generation and NO manual editor — the exact
     always-on `Редактирай` defect, on the owner's own Articles;
  B. a real eligible Article whose generation genuinely fails (only the model
     transport is substituted) stays in Preparation, gains the durable marker,
     and then offers `Редактирай` alongside a working retry;
  C. the marker survives a full process-state wipe — no operation registry, no
     generation lock, no attempt counter — because it is canonical state;
  D. a material change to the generation basis retires the marker, so a stale
     failure cannot keep authorizing the editor;
  E. the manual continuation produces a real Draft on the same Article, with no
     Case, no immutable generated Draft and no fabricated lineage, and the
     marker is retired by the Draft it produced.

Everything is production code: the real stores, the real projections, the real
readiness predicate, the real Draft command. Only the external model transport
is substituted, and only so the provider boundary can be made to fail on demand.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REAL_NEWSROOM = ROOT / "var" / "newsroom"
REAL_EDITORIAL = ROOT / "var" / "editorial_workflow"

TMP = Path(tempfile.mkdtemp(prefix="v11c_manual_continuation_proof_"))
ISOLATED_NEWSROOM = TMP / "newsroom"
ISOLATED_EDITORIAL = TMP / "editorial_workflow"

RESULTS: list[bool] = []

#: The text the manual continuation writes, to prove the editor's own words are
#: what becomes the Draft body.
MANUAL_BODY = "Ръчно написан текст след неуспешно автоматично създаване."


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
    """Copy the real stores and point every writer at the copies."""
    shutil.copytree(REAL_NEWSROOM, ISOLATED_NEWSROOM)
    shutil.copytree(REAL_EDITORIAL, ISOLATED_EDITORIAL, dirs_exist_ok=True)
    os.environ["WB_NEWSROOM_DIR"] = str(ISOLATED_NEWSROOM)
    os.environ["NEWSROOM_DIR"] = str(ISOLATED_NEWSROOM)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(ISOLATED_EDITORIAL)
    os.environ["MODEL_USAGE_DIR"] = str(TMP / "model_usage")
    os.environ["MODEL_HEALTH_PATH"] = str(TMP / "model_health.json")
    (TMP / "model_usage").mkdir(exist_ok=True)


def await_operation(token: str, attempts: int = 900) -> dict:
    from editor_assistant.workflow import story_operations

    for _ in range(attempts):
        row = story_operations.get(token)
        if row and row["status"] in {"succeeded", "failed"}:
            return row
        time.sleep(0.02)
    raise AssertionError("the draft operation did not finish")


def substitute_provider(*, fail: bool) -> list[str]:
    """Substitute ONLY the external model transport.

    With `fail=False` every role answers normally. With `fail=True` only the
    `draft` role raises, so the failure happens exactly where a provider outage
    happens in production — after the angle gate, at the generation boundary.
    """
    from editor_assistant.drafting import generate as gen

    roles: list[str] = []

    def answer(role: str) -> str:
        if role == "draft":
            return json.dumps(
                {
                    "headlines": ["Съветът одобри графика"],
                    "headline": "Съветът одобри графика",
                    "body": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "sentence": "Общинският съвет одобри 1,2 милиона лева.",
                "verdict": "SUPPORTED",
                "issue": "none",
                "supporting_fact_ids": [],
                "note": "ok",
            }
        )

    def call(prompt_text, *, api_key="", timeout=0, role="draft", **_kw):
        roles.append(role)
        if fail and role == "draft":
            raise RuntimeError("provider boundary failed (proof substitute)")
        return answer(role), {"model": "proof-substitute", "provider": "substitute"}

    for name in ("call_model", "_call_gemini", "_call_openrouter"):
        if hasattr(gen, name):
            setattr(gen, name, call)
    os.environ.setdefault("GEMINI_API_KEY", "proof-key")
    os.environ.pop("OPENROUTER_API_KEY", None)
    return roles


def prove_no_editor_on_clean_articles() -> None:
    """A — the always-on `Редактирай` defect, on the owner's real Articles."""
    from editor_assistant.workflow import editor_application as app

    articles = list(app.list_articles("preparation"))
    check("real preparation Articles exist", bool(articles), f"{len(articles)} found")
    confirmed = [
        row
        for row in articles
        if (row.get("preparation") or {}).get("focusConfirmed")
        and "MAKE_DRAFT" in row["availableActions"]
    ]
    check(
        "A1. real focus-confirmed, eligible Articles exist",
        bool(confirmed),
        f"{len(confirmed)}/{len(articles)}",
    )
    for row in confirmed[:4]:
        check(f"A2. {row['id']} offers generation", "MAKE_DRAFT" in row["availableActions"])
        check(
            f"A3. {row['id']} offers NO manual editor",
            "EDIT" not in row["availableActions"],
            f"availableActions={row['availableActions']}",
        )
        check(
            f"A4. {row['id']} has no failure marker",
            row["preparation"]["draftFailure"] is None,
        )
    check(
        "A5. no real preparation Article offers the manual editor",
        all("EDIT" not in row["availableActions"] for row in articles),
        f"{len(articles)} real preparation Articles",
    )


def make_one_real_article_eligible() -> dict | None:
    """Bring one REAL preparation Article to genuine eligibility, canonically.

    The real stores currently hold unresearched preparation Articles, which are
    correctly ineligible. To prove the recovery path on real data the Story is
    given one real research round through the store's production write path — the
    same transition V1.1-A introduced — so the Article becomes genuinely
    eligible and a real generation attempt can really be made against it.
    """
    from editor_assistant.workflow import editor_application as app
    from editor_assistant.workflow import story_research_store

    candidates = list(app.list_articles("preparation"))
    for row in candidates:
        if "MAKE_DRAFT" in row["availableActions"]:
            return row
    if not candidates:
        return None
    story_id = candidates[0]["story"]["id"]
    story_research_store.merge_research(
        story_id,
        sources=[
            {
                "id": "vestnik",
                "name": "Вестник",
                "url": "https://vestnik.example.test/2026/proof",
            }
        ],
        facts=[
            {
                "id": "fact_proof_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_proof_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работа.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
            {
                "id": "fact_proof_next",
                "text": "Следващата сесия на съвета ще обсъди графика за следващата улица.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 6",
            },
        ],
        gaps=[],
        assessed_at="2026-09-26T09:00:00Z",
        canonical_story={"story_id": story_id},
        operation_id="v11c-proof-research",
    )
    return eligible_real_article()


def eligible_real_article() -> dict | None:
    """A real Article that is genuinely eligible, or None."""
    from editor_assistant.workflow import editor_application as app

    for row in app.list_articles("preparation"):
        preparation = row.get("preparation") or {}
        if "MAKE_DRAFT" in row["availableActions"] and preparation.get("focusConfirmed"):
            return row
    return None


def wipe_process_state() -> None:
    """Drop every in-process signal the recovery decision must NOT depend on."""
    from editor_assistant.workflow import article_generation, story_operations

    story_operations.clear()
    for token in list(article_generation._ACTIVE):
        article_generation.release(token, article_generation._ACTIVE[token])


def _bytes(name: str) -> bytes:
    path = ISOLATED_EDITORIAL / name
    return path.read_bytes() if path.exists() else b""


def prove_failure_earns_the_editor(article_id: str) -> None:
    """B/C/D — a real failure earns the editor, durably, and only for its basis."""
    from editor_assistant.workflow import (
        article_draft_failure,
        article_generation,
        editor_article_store,
    )
    from editor_assistant.workflow import editor_application as app

    before = app.read_article(article_id)
    check(
        "B1. it starts clean: no marker, no editor",
        before["preparation"]["draftFailure"] is None and "EDIT" not in before["availableActions"],
    )

    roles = substitute_provider(fail=True)
    started = app.start_article_draft(article_id, idempotency_key="v11c-proof-failure")
    row = await_operation(started["operationToken"])
    check(
        "B2. the attempt really reached the provider",
        "draft" in roles,
        f"roles={roles}",
    )
    check(
        "B3. the operation really failed",
        row["status"] == "failed",
        f"code={row.get('error_code')}",
    )

    after = app.read_article(article_id)
    check("B4. the Article is still in Preparation", after["state"] == "preparation")
    check(
        "B5. Редактирай is now offered",
        "EDIT" in after["availableActions"],
        f"{after['availableActions']}",
    )
    check("B6. the retry is still offered", "MAKE_DRAFT" in after["availableActions"])
    failure = after["preparation"]["draftFailure"]
    check(
        "B7. the marker is editor-safe and durable",
        failure is not None and failure["reasonCode"] in article_draft_failure.REASON_CODES,
        json.dumps(failure, ensure_ascii=False),
    )
    serialized = json.dumps(editor_article_store.get_editor_article(article_id), ensure_ascii=False)
    check(
        "B8. no provider text leaked into canonical state",
        not any(
            token in serialized
            for token in ("proof-substitute", "RuntimeError", "provider boundary", "traceback")
        ),
    )

    # C — durability: everything in-process is dropped; only the store remains.
    wipe_process_state()
    reloaded = app.read_article(article_id)
    check(
        "C1. the editor survives a full process-state wipe",
        "EDIT" in reloaded["availableActions"],
        f"_ACTIVE={article_generation._ACTIVE}, token={article_generation.active_token(article_id)!r}",
    )

    # D — a material change retires the marker.
    app.update_focus(article_id, "Друг фокус за същата история.")
    stale = app.read_article(article_id)
    check(
        "D1. a changed Focus retires the failure",
        "EDIT" not in stale["availableActions"] and stale["preparation"]["draftFailure"] is None,
        f"{stale['availableActions']}",
    )


def prove_manual_continuation(article_id: str) -> None:
    """E — the manual Draft, with nothing fabricated."""
    from editor_assistant.workflow import editor_application as app
    from editor_assistant.workflow import editor_article_store

    # Earn the editor again on the NEW basis: a second genuine failure.
    substitute_provider(fail=True)
    started = app.start_article_draft(article_id, idempotency_key="v11c-proof-second")
    await_operation(started["operationToken"])
    wipe_process_state()
    recovered = app.read_article(article_id)
    check(
        "E1. a new failure on the new basis re-enables the editor",
        "EDIT" in recovered["availableActions"],
    )

    drafts_before = _bytes("live_drafts.jsonl")
    cases_before = _bytes("cases.jsonl")
    record = editor_article_store.get_editor_article(article_id)
    saved = app.save_content(
        article_id, recovered["content"]["version"], record["working_title"], MANUAL_BODY
    )

    check(
        "E2. the same Article became a Draft",
        saved["state"] == "draft" and saved["id"] == article_id,
    )
    check("E3. the text is the editor's own", saved["content"]["body"] == MANUAL_BODY)
    check("E4. the Story lineage is unchanged", saved["story"]["id"] == recovered["story"]["id"])
    check("E5. no Case was created", _bytes("cases.jsonl") == cases_before)
    check(
        "E6. no immutable generated Draft was created",
        _bytes("live_drafts.jsonl") == drafts_before,
    )
    stored = editor_article_store.get_editor_article(article_id)
    check(
        "E7. no generation lineage was fabricated",
        stored["internal_refs"]
        == {"idea_id": None, "evidence_id": None, "case_id": None, "draft_id": None}
        and stored["generated_content_version"] is None,
    )
    check(
        "E8. the recovery marker is retired by the Draft",
        stored["draft_generation_failure"] is None,
    )
    check("E9. the Draft surface is the normal one", saved["nextAction"]["action"] == "MARK_READY")


def main() -> int:
    isolate_stores()
    before_newsroom = manifest(REAL_NEWSROOM)
    before_editorial = manifest(REAL_EDITORIAL)

    print("\n--- A. a clean preparation Article offers no manual editor ---")
    # Setup: the real stores hold unresearched preparation Articles, which are
    # correctly ineligible. One real research round makes exactly one of them
    # genuinely eligible, so section A asserts on an Article that really could
    # have offered the manual editor and still must not.
    article = make_one_real_article_eligible()
    prove_no_editor_on_clean_articles()

    print("\n--- B/C/D/E. a real failure earns the editor, durably ---")
    if article is None:
        check("B0. a real eligible preparation Article exists", False)
    else:
        check("B0. a real eligible preparation Article exists", True, article["id"])
        prove_failure_earns_the_editor(article["id"])
        prove_manual_continuation(article["id"])

    print("\n--- runtime store integrity ---")
    check(
        "var/newsroom is byte-identical",
        manifest(REAL_NEWSROOM) == before_newsroom,
        f"{len(before_newsroom)} files",
    )
    check(
        "var/editorial_workflow is byte-identical",
        manifest(REAL_EDITORIAL) == before_editorial,
        f"{len(before_editorial)} files",
    )

    passed = sum(1 for row in RESULTS if row)
    print(f"\n{passed}/{len(RESULTS)} checks passed.")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())


def _bytes(name: str) -> bytes:
    path = ISOLATED_EDITORIAL / name
    return path.read_bytes() if path.exists() else b""
