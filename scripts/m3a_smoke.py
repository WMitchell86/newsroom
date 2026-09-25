#!/usr/bin/env python3
"""M3A §25 manual smoke test — runs the Editor Workbench end-to-end.

Runs against a COPY of the real editorial workflow store (`var/wb_smoke/`), so
the editor's pending pilot answers and canonical `cases.jsonl` are never
modified. Verifies the browser workflow through real HTTP requests against a
localhost-bound server:

  1. dashboard loads;
  2. current LIVE cases are visible;
  3. a normal draft case opens;
  4. sources render;
  5. headline/body can be edited;
  6. a working copy saves;
  7. a reload keeps the work;
  8. a copy case finalizes through the validated contract;
  9. the AI draft is unchanged afterwards;
 10. final/editor metrics appear;
 11. the NO_PUBLISHABLE_ANGLE case opens without an article editor;
 12. a no-story decision records without an article body;
 13. a newer AI generation flags the working copy as stale;
 14. finalizing a stale working copy is refused (409);
 15. the explicit editor re-base clears staleness and allows finalization.

Promoted from the untracked `tmp/m3a_smoke.py` scratch script (harness M3A A5) so
a clean clone can reproduce the M3A verification contract.

Usage:
  PYTHONPATH=src python3 scripts/m3a_smoke.py

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_STORE = ROOT / "var" / "editorial_workflow"
SMOKE_STORE = ROOT / "var" / "wb_smoke"

RESULTS: list[tuple[bool, str, str]] = []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def get(url: str):
    try:
        return OPENER.open(url, timeout=10)
    except urllib.error.HTTPError as err:
        return err


def post(url: str, data: dict):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        return OPENER.open(req, timeout=10)
    except urllib.error.HTTPError as err:
        return err


def read(resp) -> str:
    return resp.read().decode("utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "<missing>"


def drafts_snapshot(store: Path) -> dict:
    """case_id -> (draft_headline, draft_text) — the immutable AI draft."""
    out = {}
    cases_path = store / "cases.jsonl"
    if not cases_path.exists():
        return out
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = json.loads(line)
            out[case["case_id"]] = (case.get("draft_headline", ""), case.get("draft_text", ""))
    return out


def main() -> int:
    if not SRC_STORE.exists():
        print(f"real store not found: {SRC_STORE}")
        return 2
    if SMOKE_STORE.exists():
        shutil.rmtree(SMOKE_STORE)

    src_hashes = {name: sha(SRC_STORE / name) for name in ("cases.jsonl", "live_evidence.jsonl")}

    shutil.copytree(SRC_STORE, SMOKE_STORE)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(SMOKE_STORE)
    # D2B: this smoke proves the *server-rendered* Workbench (M3A), so it asks for
    # the legacy frontend explicitly. That surface is retained, not retired; the SPA
    # is simply the default editor frontend now.
    os.environ["WB_EDITOR_FRONTEND"] = "legacy"

    from editor_assistant.workflow import cases as cases_mod
    from editor_assistant.workflow.workbench import http, state

    before_drafts = drafts_snapshot(SMOKE_STORE)

    httpd = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"workbench: {base}  (store: {SMOKE_STORE})\n")

    try:
        # 1 + 2 — daily landing loads, archive queue still reachable
        page = read(get(f"{base}/"))
        check("1. Dashboard loads", "Дневен новинарски помощник" in page)
        queue_page = read(get(f"{base}/cases"))
        live_ids = [row["case_id"] for row in state.queue()["live"]]
        check(
            "2. LIVE cases visible",
            "LIV-02" in queue_page and "LIV-06" in queue_page,
            str(live_ids),
        )

        # 3 + 4 — normal case opens, draft + sources render
        case_page = read(get(f"{base}/case/LIV-02"))
        check("3. Normal case opens", "AI чернова (неизменима)" in case_page)
        check("4. Sources surface renders", "Източници" in case_page)

        # 5 + 6 — edit headline/body and save the working copy
        new_headline = "СМОКЕ заглавие (само копие)"
        new_body = "СМОКЕ текст на редактора.\n\nВтори абзац."
        resp = post(
            f"{base}/case/LIV-02/save",
            {"headline": new_headline, "body": new_body, "answer_would_publish": "YES"},
        )
        check("5. Save returns 303 redirect", resp.code == 303, f"code={resp.code}")
        wc = state.load_working_copy("LIV-02")
        check("6. Working copy saved", bool(wc) and wc.get("headline") == new_headline)

        # 7 — reload keeps the work
        reloaded = read(get(f"{base}/case/LIV-02"))
        check("7. Reload keeps the edit", new_headline in reloaded)

        # 8 — finalize the copy case through the validated contract
        case = state.find_case("LIV-02")
        draft_id = case["draft_id"]
        resp = post(
            f"{base}/case/LIV-02/finalize",
            {
                "headline": "СМОКЕ финално заглавие",
                "body": "СМОКЕ финален текст.",
                "editor_outcome": "ACCEPTED_FOR_EDIT",
                "editing_weight": "MODERATE",
                "time_saved_estimate": "5-15 min",
                "prefer_ai_start": "YES",
                "readiness_outcome": "ANGLE_ACCEPTED",
                "answer_would_publish": "YES",
                "base_draft_id": draft_id,
            },
        )
        check("8. Finalize returns 303 redirect", resp.code == 303, f"code={resp.code}")
        finalized = state.find_case("LIV-02")
        check(
            "8b. Final text persisted",
            finalized.get("final_text") == "СМОКЕ финален текст."
            and finalized.get("final_headline") == "СМОКЕ финално заглавие",
        )

        # 9 — the AI draft is unchanged
        after_drafts = drafts_snapshot(SMOKE_STORE)
        check(
            "9. AI draft unchanged",
            after_drafts.get("LIV-02") == before_drafts.get("LIV-02"),
            f"{after_drafts.get('LIV-02')}",
        )
        check("9b. AI draft vs final differ", after_drafts["LIV-02"][1] != finalized["final_text"])

        # 10 — final/editor metrics appear
        final_page = read(get(f"{base}/case/LIV-02"))
        check(
            "10. Final + editor metrics render",
            "Финализиран материал (неизменим)" in final_page
            and "Умерена" in final_page
            and "Ъгълът е приет" in final_page,
        )

        # 11 — NO_PUBLISHABLE_ANGLE case (evidence-only, no case row)
        nostory_page = read(get(f"{base}/case/LIV-06"))
        check("11. NO_PUBLISHABLE_ANGLE opens", "Няма достатъчно силна новина" in nostory_page)
        check("11b. No article editor shown", 'id="workspace"' not in nostory_page)
        check(
            "11c. AI no-story decision stated",
            "Няма достатъчно силен и проверим новинарски ъгъл" in nostory_page,
        )

        # 12 — record a no-story decision without any article body
        resp = post(
            f"{base}/case/LIV-06/decision",
            {
                "decision": "REJECT_STORY",
                "reason": "СМОКЕ: потвърждавам, че няма новина.",
                "readiness_outcome": "NO_STORY_CONFIRMED",
            },
        )
        check("12. Decision returns 303 redirect", resp.code == 303, f"code={resp.code}")
        evidence = state._live_evidence_rows().get("LIV-06-EVIDENCE") or {}
        decision = (evidence.get("workbench_decision") or {}).get("decision")
        check("12b. No-story decision recorded without body", decision == "REJECT_STORY", decision)
        check(
            "12c. No case row created for LIV-06", state.find_case("LIV-06").get("final_text") == ""
        )

        # 13-15 — stale generation: guard + explicit editor re-base
        target = next(
            (
                row["case_id"]
                for row in state.queue()["live"]
                if row["case_id"] != "LIV-02"
                and row["kind"] is None
                and not row["final"]
                and row["case"].get("draft_id")
            ),
            None,
        )
        check("13. Draft case available for the stale check", target is not None, str(target))
        if target:
            post(
                f"{base}/case/{target}/save",
                {"headline": "СМОКЕ чернова", "body": "СМОКЕ текст преди новата AI версия."},
            )
            cases_path = SMOKE_STORE / "cases.jsonl"
            rows = cases_mod.read_cases(cases_path)
            for row in rows:
                if row["case_id"] == target:
                    row["draft_id"] = "smoke-newer-draft"
            cases_mod.save_cases(rows, cases_path)
            stale_page = read(get(f"{base}/case/{target}"))
            check(
                "13b. Stale banner + re-base control render",
                "Междувременно е генерирана по-нова AI версия." in stale_page
                and 'name="accept_base"' in stale_page,
            )
            blocked = post(
                f"{base}/case/{target}/finalize",
                {
                    "headline": "СМОКЕ финал",
                    "body": "СМОКЕ текст.",
                    "editor_outcome": "ACCEPTED_FOR_EDIT",
                    "editing_weight": "LIGHT",
                    "base_draft_id": "smoke-newer-draft",
                },
            )
            check("14. Stale finalization refused", blocked.code == 409, f"code={blocked.code}")
            check("14b. Nothing was finalized", not state.find_case(target).get("final_text"))
            rebase = post(
                f"{base}/case/{target}/save",
                {
                    "headline": "СМОКЕ чернова",
                    "body": "СМОКЕ текст преди новата AI версия.",
                    "accept_base": "1",
                },
            )
            doc = state.load_working_copy(target)
            check(
                "15. Explicit re-base adopts the new generation",
                rebase.code == 303
                and doc["base_draft_id"] == "smoke-newer-draft"
                and state.working_copy_is_stale(state.find_case(target), doc) is False,
                f"code={rebase.code} base={doc.get('base_draft_id')}",
            )
            allowed = post(
                f"{base}/case/{target}/finalize",
                {
                    "headline": "СМОКЕ финал след пребазиране",
                    "body": "СМОКЕ текст след пребазиране.",
                    "editor_outcome": "ACCEPTED_FOR_EDIT",
                    "editing_weight": "LIGHT",
                    "base_draft_id": "smoke-newer-draft",
                },
            )
            check(
                "15b. Finalization succeeds after the re-base",
                allowed.code == 303
                and state.find_case(target)["final_text"] == "СМОКЕ текст след пребазиране.",
                f"code={allowed.code}",
            )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    # Safety: the real store must be byte-identical.
    after_src = {name: sha(SRC_STORE / name) for name in ("cases.jsonl", "live_evidence.jsonl")}
    check(
        "S. Real store untouched",
        src_hashes == after_src,
        "" if src_hashes == after_src else f"{src_hashes} != {after_src}",
    )

    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("M3A smoke: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
