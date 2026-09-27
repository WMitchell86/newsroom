"""V1.2-G2.4 §C — the EFFECTIVE model-routing audit, from the live policy.

§C1 asks for a table of every editor workflow to its role, its model routes in
order, its billing class, its daily cap, its typical calls per Story and its
fallback — and §C1 also insists on distinguishing CONFIGURED from ACTUALLY
PRODUCTION-WIRED. That distinction is the whole point of this script: it reads
the effective policy (defaults merged with the operator override) AND greps the
production call sites for `role=` usage, so a role that is configured but never
called cannot be reported as if it were doing work.

§C2 measures the G2.3 cost shape: claim comparison is the high-volume role, and
§C2 asks what it actually cost. The ledger under `var/model_usage/` is read if
present; the report says so plainly when it is not, rather than inventing usage.

§C5: nothing here changes `paid_enabled`. The script only REPORTS whether a
paid route is reachable. Any paid change is a separate owner decision.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = ROOT / "src" / "editor_assistant"

#: Every editor workflow §C1 asks about, and the role that is SUPPOSED to carry
#: it. `wired_roles` below is measured from the call sites, never assumed.
WORKFLOWS = (
    ("Story identity / SAME_STORY", "story"),
    ("research query/planning", "research"),
    ("claim extraction (replay only)", "extract"),
    ("claim equivalence / corroboration", "extract"),
    ("evidence judgement", "judge"),
    ("angle / style", "angle"),
    ("Draft generation", "draft"),
    ("Draft validation", "judge"),
    ("editorial Focus suggestion", None),
    ("low-risk helper tasks", "utility"),
)

#: The CONFIGURED-vs-WIRED distinction of §C1: a role with routes but no
#: `role=` call site is reported as configured-only, never as doing work.
#: Deliberately a simple literal search rather than one clever regex: a call site
#: is a line of source containing `role="<name>"`, and that is the whole test.
_ROLE_TOKEN = 'role="'


def _roles_in(text: str) -> list[str]:
    import re as _re

    return _re.findall("role=[\"']([a-z_]+)[\"']", text)


def wired_roles() -> dict[str, list[str]]:
    """Roles actually referenced by a production `role=` call site.

    This is the CONFIGURED-vs-WIRED distinction of §C1, measured rather than
    asserted: a role with routes but no call site is reported as configured-only.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        # Relative to SRC, NOT the absolute path: this repository can live under
        # a directory whose own name contains "test", and an absolute-parts check
        # would then silently skip every production file.
        relative = path.relative_to(SRC)
        if "test" in relative.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for role in _roles_in(text):
            found.setdefault(role, []).append(str(relative))
    return found


def main() -> int:
    from editor_assistant.drafting import model_policy

    policy = model_policy.load_policy()
    live = wired_roles()

    roles = []
    for name, spec in policy["roles"].items():
        routes = []
        for route in spec.get("routes") or []:
            routes.append(
                {
                    "provider": route.get("provider"),
                    "model": route.get("model"),
                    "billing": route.get("billing"),
                    "enabled": route.get("enabled", True),
                    "daily_call_limit": route.get("daily_call_limit"),
                }
            )
        roles.append(
            {
                "role": name,
                "soft_calls_day": spec.get("soft_calls_day"),
                "hard_calls_day": spec.get("hard_calls_day"),
                "on_exhausted": spec.get("on_exhausted"),
                "routes": routes,
                "wired_in_production": bool(live.get(name)),
                "wired_at": sorted(set(live.get(name) or [])),
                "paid_route_reachable": any(
                    r.get("billing") == "paid" and r.get("enabled", True) for r in routes
                ),
                "first_route": (routes[0] if routes else None),
            }
        )

    table = []
    for workflow, role in WORKFLOWS:
        spec = next((r for r in roles if r["role"] == role), None) if role else None
        table.append(
            {
                "workflow": workflow,
                "role": role or "(none — deterministic)",
                "configured": bool(spec),
                "wired_in_production": bool(spec and spec["wired_in_production"]),
                "first_route": spec["first_route"] if spec else None,
                "routes_in_order": [f"{r['provider']}:{r['model']} ({r['billing']})"
                                    for r in (spec["routes"] if spec else [])],
                "hard_calls_day": spec["hard_calls_day"] if spec else 0,
                "fallback": spec["on_exhausted"] if spec else "n/a",
                "paid_route_reachable": spec["paid_route_reachable"] if spec else False,
            }
        )

    ledger = sorted((ROOT / "var" / "model_usage").glob("*.json")) if (
        ROOT / "var" / "model_usage"
    ).exists() else []
    usage = {}
    for path in ledger:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for model, row in (payload.get("by_model") or {}).items():
            bucket = usage.setdefault(model, {"calls": 0, "ok": 0, "failed": 0,
                                              "skipped": 0, "input_tokens": 0,
                                              "output_tokens": 0})
            for key in bucket:
                bucket[key] += int(row.get(key) or 0)

    report = {
        "global_paid_enabled": policy["global"].get("paid_enabled"),
        "roles": roles,
        "workflow_table": table,
        "observed_usage_by_model": usage,
        "usage_ledger_days": [p.name for p in ledger],
        "note": (
            "READ-ONLY audit. No policy file was modified and paid_enabled was "
            "not changed (§C5)."
        ),
    }
    out = ROOT / "m4" / "review" / "evidence" / "v1_2_g2_4_model_routing_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["workflow_table"], ensure_ascii=False, indent=2)[:4000])
    print("paid_enabled:", report["global_paid_enabled"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
