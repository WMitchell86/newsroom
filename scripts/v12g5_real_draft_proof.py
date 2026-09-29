"""One real Draft, end to end, on the real provider. V1.2-G4.5.

The handover's first priority, and the one thing this whole milestone has not
been able to prove: no Draft has been produced end to end since the provider
started refusing. Everything else - the async 202, the truthful errors, the
redaction, the per-minute routing - is verified offline. This is the check that
touches the network, and it either prints a generated article or it prints the
real reason it could not.

Run it with the SAME environment the server uses:

    set -a; . ./.env; set +a
    python3 scripts/v12g5_real_draft_proof.py

(`env $(cat .env)` does NOT strip quotes and is how a probe once reported a
valid key as broken - AGENTS.md rule 7.)

It refuses to run while the daily quota is spent and says so, rather than
burning a call to learn it again.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from editor_assistant.drafting import model_policy, model_router
from editor_assistant.workflow import (
    story_operations,
)

NOW = "2026-09-29T06:00:00Z"
HEADLINE = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата"


def ok(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{f'  ({detail})' if detail else ''}")
    return bool(condition)


def main() -> int:
    print("=" * 72)
    print("V1.2-G4.5 - ONE REAL DRAFT, end to end")
    print("=" * 72)

    key = str(os.environ.get("GEMINI_API_KEY") or "")
    print(f"  GEMINI_API_KEY: {len(key)} chars, quoted={key[:1] in chr(34) + chr(39)}")
    if not key:
        print("  FAIL  no GEMINI_API_KEY in the environment; use `set -a; . ./.env`")
        return 1

    # Say the quota state out loud BEFORE spending anything.
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    reset = (now.replace(hour=0, minute=0, second=0, microsecond=0))
    print(f"  Pacific now: {now:%Y-%m-%d %H:%M} (RPD resets at midnight Pacific)")
    policy = model_policy.load_policy()
    drafts = [r for r in policy["roles"]["draft"]["routes"] if r.get("provider") == "gemini"]
    print("  draft routes:")
    for route in drafts:
        health = model_router.route_health(route)
        status = health.get("status") or "OK"
        limit = route.get("daily_call_limit")
        print(
            f"    - {route.get('model'):28s} rpd_limit={limit}  health={status}"
            f"{' until ' + str(health.get('until')) if health.get('until') else ''}"
        )
    spent = [
        r for r in drafts
        if (model_router.route_health(r).get("status") or "") == "EXHAUSTED"
    ]
    if spent:
        print(f"  {len(spent)} draft route(s) are marked EXHAUSTED. Refusing to spend a call.")
        print("  This is a quota state, not a code defect. Re-run after midnight Pacific.")
        return 2
    _ = reset

    from editor_assistant.workflow import editor_application as app

    article_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not article_id:
        print("\n  No article id given. Press Чернова in the UI, or pass one:")
        print("    python3 scripts/v12g5_real_draft_proof.py art_xxxx")
        return 3

    begin = time.monotonic()
    started = app.start_article_draft(article_id, idempotency_key=f"g45-real-{int(begin)}")
    elapsed = time.monotonic() - begin
    token = started["operationToken"]
    ok("202 returned fast (G4.4)", elapsed < 2.0, f"{elapsed:.3f}s")
    print(f"  token: {token}")

    row = None
    for _ in range(3600):
        row = story_operations.get(token)
        if row and row["status"] in {"succeeded", "failed"}:
            break
        time.sleep(1)
    total = time.monotonic() - begin

    if row and row["status"] == "succeeded":
        article = app.read_article(article_id)
        body = str((article.get("content") or {}).get("body") or "")
        ok("a REAL draft was generated", len(body) > 200, f"{len(body)} chars")
        print(f"  total time: {total:.1f}s")
        print("  " + body[:300].replace("\n", " ") + " ...")
        return 0

    print(f"  FAILED after {total:.1f}s")
    print(f"  error_code: {row.get('error_code') if row else 'no row'}")
    print(f"  raw error : {row.get('error') if row else ''}")
    print("  full envelope the editor would see:")
    print("   ", json.dumps(app.operation_status(token).get("error"), ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
