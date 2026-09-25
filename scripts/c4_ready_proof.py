"""Isolated end-to-end proof for C4 (current-content validation + `Отбележи като готова`).

Run:  PYTHONPATH=src python3 scripts/c4_ready_proof.py
Exit 0 = every check passed.

Real HTTP against the real `/api/v1` boundary, isolated stores in a temp
directory: the normal newsroom, editorial and archive stores are never touched.
Three paths are proven:

  A. generated Draft -> edit -> autosave -> current validation -> warnings
     -> Отбележи като готова -> Готова
  B. manual continuation Draft -> validation -> Отбележи като готова -> Готова
  C. Draft -> blocking issue -> Ready attempt -> rejected -> remains Чернова

Only the model transport is stubbed, and only for path A. The audits, the
stores, the projections, the command and the HTTP layer are production code.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

TMP = tempfile.mkdtemp(prefix="c4_ready_proof_")
os.environ["WB_NEWSROOM_DIR"] = os.path.join(TMP, "newsroom")
os.environ["NEWSROOM_DIR"] = os.path.join(TMP, "newsroom")
os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = os.path.join(TMP, "editorial_workflow")
# The model usage ledger is part of the isolated state too: a real quota row
# from the operator's runs must never decide what this proof can prove. The
# recorded route health is isolated for the same reason.
os.environ["MODEL_USAGE_DIR"] = os.path.join(TMP, "model_usage")
os.environ["MODEL_HEALTH_PATH"] = os.path.join(TMP, "model_health.json")
os.makedirs(os.environ["WB_NEWSROOM_DIR"], exist_ok=True)
os.makedirs(os.environ["WB_EDITORIAL_WORKFLOW_DIR"], exist_ok=True)
os.makedirs(os.environ["MODEL_USAGE_DIR"], exist_ok=True)

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import editor_article_store as articles
from editor_assistant.workflow import inbox_store, story_research_store, story_store
from editor_assistant.workflow.workbench import http

RESULTS: list[bool] = []
HEADLINE = "Съветът одобри графика за ремонта"
FACT = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."
SUPPORTED = (
    "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
    "Жителите на квартала ще пътуват с 10 минути повече до работата."
)
REVIEW = FACT + " Във вътрешния двор се събраха граждани, които питат за съдбата на пазара."


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


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


def data(result) -> dict:
    return result[1]["data"]


def seed(*, gaps=()) -> None:
    story_research_store.merge_research(
        "s-one",
        sources=[{"id": "vestnik", "name": "Вестник", "url": "https://vestnik.example.test/b"}],
        facts=[
            {"id": "fact_money", "text": FACT, "sourceId": "vestnik", "locator": "т. 4"},
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "т. 5",
            },
        ],
        gaps=list(gaps),
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="c4-proof",
    )


def new_article(stories_path, title: str) -> str:
    article = articles.create_editor_article(
        story_id="s-one", stories_path=stories_path, working_title=title, now="2026-09-25T09:00:00Z"
    )
    articles.update_editor_focus(article["article_id"], "Да обясним решението и последиците.")
    return article["article_id"]


def main() -> int:
    newsroom = os.environ["WB_NEWSROOM_DIR"]
    stories_path = os.path.join(newsroom, "stories.json")
    origin = {
        "item_id": "origin",
        "source_id": "vestnik",
        "source_item_id": "origin",
        "title": HEADLINE,
        "url": "https://vestnik.example.test/origin",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": "Обобщение",
        "source_kind": "media",
        "status": "NEW",
    }
    inbox_store.save_items([origin], os.path.join(newsroom, "inbox.jsonl"))
    story = story_store.new_story(origin, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, stories_path)
    seed()

    server = http.serve(0, host="127.0.0.1")
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        path_a(base, stories_path)
        path_b(base, stories_path)
        path_c(base, stories_path)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return 0 if all(RESULTS) else 1


def _stub_model() -> None:
    """Only the transport is stubbed; every gate below it is the real one."""
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["GEMINI_API_KEY"] = "c4-proof-key"

    def call(_prompt, *, api_key, timeout, role="draft", **_kw):
        if role == "draft":
            return json.dumps(
                {"headline": HEADLINE, "headlines": [HEADLINE], "body": SUPPORTED},
                ensure_ascii=False,
            ), {"model": "mock"}
        return json.dumps(
            {
                "sentence": SUPPORTED,
                "verdict": "SUPPORTED",
                "issue": "none",
                "supporting_fact_ids": [],
                "note": "ok",
            },
            ensure_ascii=False,
        ), {"model": "mock"}

    gen._call_gemini = call


# ------------------------------------------------------------------- path A


def path_a(base: str, stories_path: str) -> None:
    """generated Draft -> edit -> autosave -> current validation -> Ready."""
    _stub_model()
    article_id = new_article(stories_path, HEADLINE)
    _, payload = request(
        base,
        f"/api/v1/articles/{article_id}/draft",
        method="POST",
        headers={"Idempotency-Key": "c4-proof-a"},
    )
    token = payload["data"]["operationToken"]
    for _ in range(600):
        _, poll = request(base, f"/api/v1/operations/{token}")
        if poll["data"]["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    check(
        "A: the real Draft command publishes generated text", poll["data"]["status"] == "succeeded"
    )

    generated = data(request(base, f"/api/v1/articles/{article_id}"))
    check("A: the generated Draft is Чернова", generated["state"] == "draft", generated["state"])
    check(
        "A: current validation is bound to version 1",
        generated["validation"]
        == {"contentVersion": 1, "current": True, "blocking": False, "readyEligible": True},
        json.dumps(generated["validation"], ensure_ascii=False),
    )
    check("A: MARK_READY is offered by the backend", "MARK_READY" in generated["availableActions"])

    saved = data(
        request(
            base,
            f"/api/v1/articles/{article_id}/content",
            method="PUT",
            body={"expectedVersion": 1, "title": HEADLINE, "body": REVIEW},
        )
    )
    check("A: the editor edit autosaves to version 2", saved["content"]["version"] == 2)
    check(
        "A: the edited text is revalidated, not the generation audit",
        saved["validation"]["contentVersion"] == 2 and bool(saved["warnings"]),
        f"{len(saved['warnings'])} current warnings",
    )
    check(
        "A: the review warnings are visible before the decision",
        all(not row["blocking"] for row in saved["warnings"]),
    )
    check(
        "A: no character range is ever fabricated",
        all("range" not in row for row in saved["warnings"]),
    )

    ready = data(
        request(
            base,
            f"/api/v1/articles/{article_id}/ready",
            method="POST",
            body={"expectedVersion": 2},
        )
    )
    check("A: Отбележи като готова gives Готова", ready["state"] == "ready", ready["state"])
    check(
        "A: the checkpoint is bound to the exact version",
        ready["readiness"]
        == {"isCurrent": True, "readyVersion": 2, "readyAt": ready["readiness"]["readyAt"]},
    )
    check(
        "A: Готова is a read-only surface in C4",
        ready["availableActions"] == [] and ready["nextAction"] is None,
    )
    check("A: nothing is finalized or published", ready["isFinalized"] is False)

    edited = data(
        request(
            base,
            f"/api/v1/articles/{article_id}/content",
            method="PUT",
            body={"expectedVersion": 2, "title": HEADLINE, "body": REVIEW + " Уточнение."},
        )
    )
    check("A: a later edit invalidates the checkpoint", edited["state"] == "draft", edited["state"])


# ------------------------------------------------------------------- path B


def path_b(base: str, stories_path: str) -> None:
    """manual continuation Draft -> validation -> Отбележи като готова -> Готова."""
    article_id = new_article(stories_path, "Ръчна чернова за улицата")
    stored = articles.get_editor_article(article_id)
    check(
        "B: no generated Draft lineage exists",
        all(value is None for value in stored["internal_refs"].values()),
    )

    saved = data(
        request(
            base,
            f"/api/v1/articles/{article_id}/content",
            method="PUT",
            body={"expectedVersion": 0, "title": "Ръчна чернова за улицата", "body": SUPPORTED},
        )
    )
    check("B: the manual Draft is Чернова", saved["state"] == "draft", saved["state"])
    check("B: MARK_READY needs no generated Draft", "MARK_READY" in saved["availableActions"])

    ready = data(
        request(
            base,
            f"/api/v1/articles/{article_id}/ready",
            method="POST",
            body={"expectedVersion": 1},
        )
    )
    check("B: the manual Draft becomes Готова", ready["state"] == "ready", ready["state"])
    check("B: the checkpoint is current", ready["readiness"]["isCurrent"] is True)


# ------------------------------------------------------------------- path C


def path_c(base: str, stories_path: str) -> None:
    """Draft -> blocking issue -> Ready attempt -> rejected -> remains Чернова."""
    article_id = new_article(stories_path, "Чернова с пречка")
    request(
        base,
        f"/api/v1/articles/{article_id}/content",
        method="PUT",
        body={"expectedVersion": 0, "title": "Чернова с пречка", "body": SUPPORTED},
    )
    seed(gaps=[{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}])

    draft = data(request(base, f"/api/v1/articles/{article_id}"))
    check("C: a blocking gap blocks the current content", draft["validation"]["blocking"] is True)
    check("C: MARK_READY is withdrawn", "MARK_READY" not in draft["availableActions"])
    check(
        "C: the blocking warning is explained in the workspace",
        any(row["blocking"] for row in draft["warnings"]),
        draft["warnings"][0]["message"] if draft["warnings"] else "",
    )

    status, payload = request(
        base,
        f"/api/v1/articles/{article_id}/ready",
        method="POST",
        body={"expectedVersion": 1},
    )
    check(
        "C: the readiness command is refused", status == 409, f"{status} {payload['error']['code']}"
    )
    check("C: the refusal is SAFETY_BLOCKED", payload["error"]["code"] == "SAFETY_BLOCKED")
    check(
        "C: the refusal carries editor-facing blocking context",
        [row["rule"] for row in payload["error"].get("warnings", [])] == ["blocking_gap_open"],
    )
    check(
        "C: no checkpoint was created",
        articles.get_editor_article(article_id)["ready_version"] is None,
    )

    after = data(request(base, f"/api/v1/articles/{article_id}"))
    check("C: the Article remains Чернова", after["state"] == "draft", after["state"])

    stale, _ = request(
        base,
        f"/api/v1/articles/{article_id}/ready",
        method="POST",
        body={"expectedVersion": 0},
    )
    check("C: a stale editor version is a version conflict", stale == 409, str(stale))


if __name__ == "__main__":
    sys.exit(main())
