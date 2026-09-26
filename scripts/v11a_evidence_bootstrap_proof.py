"""V1.1-A isolated proof: first research round for a real, UNASSESSED Story.

Run:  PYTHONPATH=src python3 scripts/v11a_evidence_bootstrap_proof.py
Exit 0 = every check passed.

Isolated copies of the REAL stores are used (``var/newsroom`` and
``var/editorial_workflow``); the normal runtime stores are manifested before and
re-verified byte-for-byte after the run.

Only the two genuinely external network edges are substituted (the search
provider and the page opener). Everything else is production code: the real
``POST /api/v1/stories/{id}/research`` command, the real operation registry and
worker thread, the real research store, the real readiness assessment and the
real Story projection.

The proof uses the real Царево Story from
``m4/review/V1_1_EDITORIAL_USABILITY_DIAGNOSTIC.md`` (``s16943311c9c782f``),
which the diagnostic measured as ``facts: 0, gaps: 0, research_rounds: 0``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_NEWSROOM = ROOT / "var" / "newsroom"
REAL_EDITORIAL = ROOT / "var" / "editorial_workflow"

TMP = Path(tempfile.mkdtemp(prefix="v11a_bootstrap_proof_"))
ISOLATED_NEWSROOM = TMP / "newsroom"
ISOLATED_EDITORIAL = TMP / "editorial_workflow"

DIAGNOSTIC_STORY = "s16943311c9c782f"

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


def request(base: str, path: str, *, method: str = "GET", body=None, headers=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as err:
        response = err
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def await_operation(base: str, token: str, *, budget_seconds: float = 30.0) -> dict:
    deadline = time.monotonic() + budget_seconds
    while time.monotonic() < deadline:
        payload = request(base, f"/api/v1/operations/{token}")[1]["data"]
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("the research operation did not settle inside the proof budget")


def isolate_stores() -> None:
    """Copy the real stores and point every writer at the copies."""
    shutil.copytree(REAL_NEWSROOM, ISOLATED_NEWSROOM)
    ISOLATED_EDITORIAL.mkdir(parents=True, exist_ok=True)
    for name in ("story_research.json", "editor_articles.jsonl"):
        source = REAL_EDITORIAL / name
        if source.exists():
            shutil.copy2(source, ISOLATED_EDITORIAL / name)
    os.environ["WB_NEWSROOM_DIR"] = str(ISOLATED_NEWSROOM)
    os.environ["NEWSROOM_DIR"] = str(ISOLATED_NEWSROOM)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(ISOLATED_EDITORIAL)
    os.environ["MODEL_USAGE_DIR"] = str(TMP / "model_usage")
    os.environ["MODEL_HEALTH_PATH"] = str(TMP / "model_health.json")
    (TMP / "model_usage").mkdir(exist_ok=True)


def substitute_network(*, usable: bool):
    """Replace ONLY the search provider and the page opener (both external)."""
    from editor_assistant.sources import web_fetch
    from editor_assistant.workflow import search as search_mod

    page_text = (
        "Общинският съвет в Царево връчи званията почетен гражданин на двама "
        "заслужили общественици от Ахтопол. Решението е взето на 25 септември 2026 г."
    )

    class Provider:
        name = "proof-provider"

        def search(self, query):
            if not usable:
                return {
                    "provider": "proof-provider",
                    "query": query,
                    "status": "NO_RESULTS",
                    "results": [],
                }
            return {
                "provider": "proof-provider",
                "query": query,
                "status": "SEARCH_OK",
                "results": [
                    {
                        "rank": 1,
                        "title": "Царево: почетни граждани",
                        "url": "https://publisher-one.example/tsarevo",
                        "snippet": "Почетни граждани",
                    },
                    {
                        "rank": 2,
                        "title": "Ахтопол: почетни граждани",
                        "url": "https://publisher-two.example/ahtopol",
                        "snippet": "Почетни граждани",
                    },
                ],
            }

    def fetch_page(url, **_kwargs):
        if not usable:
            raise web_fetch.WebFetchError(web_fetch.FETCH_UNREACHABLE, f"no route: {url}")
        return {
            "url": url,
            "final_url": url,
            "status": 200,
            "content_type": "text/html; charset=utf-8",
            "bytes": len(page_text),
            "text": page_text,
        }

    search_mod.provider_chain = lambda capability=None, env=None: ([Provider()], [])
    web_fetch.fetch_page = fetch_page


def unassessed_real_stories() -> list[str]:
    from editor_assistant.workflow import editor_application as app
    from editor_assistant.workflow import story_store

    out = []
    for story in story_store.read_store().get("stories", []):
        detail = app._story_detail(story["story_id"])
        missing = detail["missingInformation"]
        if (
            missing["evidenceStatus"] == "unassessed"
            and "RESEARCH_MORE" in detail["availableActions"]
        ):
            out.append(story["story_id"])
    return out


def run_round(base: str, story_id: str, *, tag: str) -> dict:
    status, payload = request(
        base,
        f"/api/v1/stories/{story_id}/research",
        method="POST",
        headers={"Idempotency-Key": f"v11a-proof-{tag}"},
    )
    assert status == 202, (status, payload)
    operation = await_operation(base, payload["data"]["operationToken"])
    assert operation["status"] == "succeeded", operation
    return request(base, f"/api/v1/stories/{story_id}")[1]["data"]


def main() -> int:
    before = manifest(REAL_NEWSROOM)
    before_editorial = manifest(REAL_EDITORIAL)

    from editor_assistant.workflow import story_research_store
    from editor_assistant.workflow.workbench import http

    isolate_stores()
    candidates = unassessed_real_stories()
    check(
        "real Stories are UNASSESSED with RESEARCH_MORE available",
        len(candidates) >= 2,
        f"{len(candidates)} of the real Stories are unassessed",
    )
    check("the diagnostic Story is unassessed", DIAGNOSTIC_STORY in candidates, DIAGNOSTIC_STORY)

    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        # A. an UNASSESSED Story gains evidence with no pre-existing gaps.
        substitute_network(usable=True)
        story_id = DIAGNOSTIC_STORY if DIAGNOSTIC_STORY in candidates else candidates[0]
        detail = request(base, f"/api/v1/stories/{story_id}")[1]["data"]
        check(
            "before: no facts, no gaps, no assessment timestamp",
            detail["factsAndSources"] == []
            and detail["missingInformation"]["items"] == []
            and detail["missingInformation"]["assessedAt"] is None,
            f"evidenceStatus={detail['missingInformation']['evidenceStatus']}",
        )
        after = run_round(base, story_id, tag="evidence")
        missing = after["missingInformation"]
        check(
            "after: ASSESSED with real facts from an opened source",
            missing["evidenceStatus"] == "assessed"
            and len(after["factsAndSources"]) >= 1
            and all(
                row["source"]["url"].startswith("https://") for row in after["factsAndSources"]
            ),
            f"facts={len(after['factsAndSources'])} gaps={len(missing['items'])}",
        )
        check("after: a real assessment timestamp is present", bool(missing["assessedAt"]))
        row = story_research_store.get_story_research(story_id)
        check(
            "after: the canonical research row is persisted and counted",
            row["story_id"] == story_id
            and row["research_rounds"] == 1
            and bool(row["operation_ids"]),
            f"rounds={row['research_rounds']} operations={len(row['operation_ids'])}",
        )

        # B. a completed round with no usable opened source is ASSESSED with a gap.
        empty_story = next(sid for sid in candidates if sid != story_id)
        substitute_network(usable=False)
        empty = run_round(base, empty_story, tag="insufficient")
        empty_missing = empty["missingInformation"]
        check(
            "insufficient evidence: ASSESSED with an explicit gap",
            empty_missing["evidenceStatus"] == "assessed"
            and empty["factsAndSources"] == []
            and len(empty_missing["items"]) >= 1,
            f"facts=0 gaps={len(empty_missing['items'])}",
        )
        check(
            "insufficient evidence never reads as a clean assessment",
            not (empty["factsAndSources"] == [] and empty_missing["items"] == []),
            empty_missing["items"][0]["question"][:60] if empty_missing["items"] else "",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    check(
        "normal runtime stores are byte-identical",
        before == manifest(REAL_NEWSROOM) and before_editorial == manifest(REAL_EDITORIAL),
        f"{len(before)} newsroom files, {len(before_editorial)} editorial files",
    )
    print(f"\nisolated copy: {TMP}")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
