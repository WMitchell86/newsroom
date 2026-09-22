"""Daily model-usage ledger and aggregation (stdlib only; never stores prompts).

One file per local day, written as an operator-readable JSON document:

```text
var/model_usage/YYYY-MM-DD.json
```

Every recorded call keeps only operational facts:

```json
{"at": "2026-09-21T06:12:03Z", "role": "story", "provider": "gemini",
 "model": "gemini-3.8-flash", "route_index": 0, "status": "OK", "category": "",
 "latency_ms": 812, "input_tokens": 1200, "output_tokens": 180, "cost_usd": 0.0,
 "fallbacks": 0, "payload_class": "public"}
```

**Prompt bodies are never written here** (PART 10 / PART 17) — the ledger is a
counter, not a transcript. Aggregation answers the operator's questions: role
calls, model calls, successes, fallbacks, quota/invalid-model failures, tokens
and paid cost for the current Europe/Sofia day.

Budget semantics: the ledger only *reports*. The router enforces:
soft = warn but continue, hard = stop using that route/role according to the
role's safe degradation. The provider's own signals (429 quota) always win over
the local day boundary, because provider reset times differ from Sofia midnight.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

STATUS_OK = "OK"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"

#: Snapshot of the paid OpenRouter prices used for local cost estimates
#: (USD per 1M tokens, 2026-09-21). Only a hint: a provider-reported cost always
#: wins, and the numbers must be re-checked with `newsroom models validate`.
PRICES_USD_PER_MTOK = {
    "openai/gpt-5.6-luna": (0.20, 1.20),
    "openai/gpt-5.6-luna-pro": (0.20, 1.20),
    "openai/gpt-5.4": (2.50, 15.00),
    "openai/gpt-5.4-mini": (0.75, 4.50),
}


def usage_dir() -> Path:
    override = os.environ.get("MODEL_USAGE_DIR")
    return Path(override) if override else ROOT / "var" / "model_usage"


def sofia_day(moment=None) -> str:
    """Local (Europe/Sofia) day key — what the editor reads in the UI."""
    from editor_assistant.workflow.source_health import sofia_date

    return sofia_date(moment).isoformat()


def _now():
    return datetime.now(timezone.utc)


def _day_path(day=None) -> Path:
    return usage_dir() / f"{day or sofia_day()}.json"


def _empty(day):
    return {
        "version": 1,
        "day": day,
        "updated_at": "",
        "calls": [],
        "by_role": {},
        "by_model": {},
        "paid_cost_usd": 0.0,
    }


def read_day(day=None) -> dict:
    """The day document (an empty shell when nothing was recorded yet)."""
    key = day or sofia_day()
    path = _day_path(key)
    if not path.exists():
        return _empty(key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty(key)
    if not isinstance(payload, dict):
        return _empty(key)
    payload.setdefault("calls", [])
    payload.setdefault("by_role", {})
    payload.setdefault("by_model", {})
    payload.setdefault("paid_cost_usd", 0.0)
    payload["day"] = key
    return payload


def _aggregate(payload: dict) -> dict:
    by_role: dict = {}
    by_model: dict = {}
    paid_cost = 0.0
    for call in payload.get("calls") or []:
        role = call.get("role") or ""
        model = f"{call.get('provider') or ''}:{call.get('model') or ''}"
        for bucket, key in ((by_role, role), (by_model, model)):
            row = bucket.setdefault(
                key,
                {
                    "calls": 0,
                    "ok": 0,
                    "failed": 0,
                    "skipped": 0,
                    "fallbacks": 0,
                    "quota_failures": 0,
                    "invalid_model_failures": 0,
                    "payment_failures": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "last_status": "",
                    "last_at": "",
                    "last_category": "",
                },
            )
            row["calls"] += 1
            status = call.get("status") or ""
            if status == STATUS_OK:
                row["ok"] += 1
            elif status == STATUS_FAILED:
                row["failed"] += 1
            elif status == STATUS_SKIPPED:
                row["skipped"] += 1
            row["fallbacks"] += int(call.get("fallbacks") or 0)
            category = call.get("category") or ""
            if category == "QUOTA_EXHAUSTED":
                row["quota_failures"] += 1
            if category == "INVALID_MODEL":
                row["invalid_model_failures"] += 1
            if category == "PAYMENT_REQUIRED":
                row["payment_failures"] += 1
            row["input_tokens"] += int(call.get("input_tokens") or 0)
            row["output_tokens"] += int(call.get("output_tokens") or 0)
            row["cost_usd"] = round(row["cost_usd"] + float(call.get("cost_usd") or 0.0), 6)
            if call.get("at") and call["at"] >= (row["last_at"] or ""):
                row["last_at"] = call["at"]
                row["last_status"] = status
                row["last_category"] = category
        paid_cost += float(call.get("cost_usd") or 0.0)
    payload["by_role"] = by_role
    payload["by_model"] = by_model
    payload["paid_cost_usd"] = round(paid_cost, 6)
    return payload


def record(entry: dict) -> dict:
    """Append one call to today's ledger and re-aggregate (atomic replace)."""
    day = entry.get("day") or sofia_day()
    payload = read_day(day)
    row = {
        "at": entry.get("at") or _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role": entry.get("role") or "",
        "provider": entry.get("provider") or "",
        "model": entry.get("model") or "",
        "route_index": int(entry.get("route_index") or 0),
        "status": entry.get("status") or STATUS_OK,
        "category": entry.get("category") or "",
        "latency_ms": int(entry.get("latency_ms") or 0),
        "input_tokens": int(entry.get("input_tokens") or 0),
        "output_tokens": int(entry.get("output_tokens") or 0),
        "cost_usd": float(entry.get("cost_usd") or 0.0),
        "fallbacks": int(entry.get("fallbacks") or 0),
        "payload_class": entry.get("payload_class") or "",
    }
    payload["calls"].append(row)
    payload["updated_at"] = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = _aggregate(payload)
    path = _day_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    os.replace(tmp, path)
    return row


def estimate_cost(model, input_tokens, output_tokens, *, reported=None):
    """Cost estimate in USD. A provider-reported value always wins."""
    if reported is not None:
        try:
            return round(float(reported), 6)
        except (TypeError, ValueError):
            pass
    price = PRICES_USD_PER_MTOK.get(str(model or ""))
    if not price:
        return 0.0
    inp, out = price
    return round(
        (int(input_tokens or 0) / 1_000_000) * inp + (int(output_tokens or 0) / 1_000_000) * out, 6
    )


def model_calls_today(provider, model, day=None) -> int:
    row = (read_day(day).get("by_model") or {}).get(f"{provider}:{model}")
    return int((row or {}).get("calls") or 0)


def successful_model_calls_today(provider, model, day=None) -> int:
    """Counted separately from attempts: a spent quota is attempts, not calls."""
    payload = read_day(day)
    return sum(
        1
        for call in payload.get("calls") or []
        if call.get("provider") == provider
        and call.get("model") == model
        and call.get("status") == STATUS_OK
    )


def role_calls_today(role, day=None) -> int:
    row = (read_day(day).get("by_role") or {}).get(role)
    return int((row or {}).get("calls") or 0)


def role_successful_today(role, day=None) -> int:
    payload = read_day(day)
    return sum(
        1
        for call in payload.get("calls") or []
        if call.get("role") == role and call.get("status") == STATUS_OK
    )


def paid_cost_today(day=None) -> float:
    return float(read_day(day).get("paid_cost_usd") or 0.0)


def daily_summary(day=None) -> dict:
    """Operator-facing aggregation for one local day."""
    payload = read_day(day)
    by_role = payload.get("by_role") or {}
    by_model = payload.get("by_model") or {}
    return {
        "day": payload["day"],
        "calls": len(payload.get("calls") or []),
        "role_calls": {role: row["calls"] for role, row in sorted(by_role.items())},
        "role_successes": {role: row["ok"] for role, row in sorted(by_role.items())},
        "model_calls": {model: row["calls"] for model, row in sorted(by_model.items())},
        "successes": sum(row["ok"] for row in by_model.values()),
        "failures": sum(row["failed"] for row in by_model.values()),
        "skipped": sum(row["skipped"] for row in by_model.values()),
        "fallbacks": sum(row["fallbacks"] for row in by_model.values()),
        "quota_failures": sum(row["quota_failures"] for row in by_model.values()),
        "invalid_model_failures": sum(row["invalid_model_failures"] for row in by_model.values()),
        "payment_failures": sum(row["payment_failures"] for row in by_model.values()),
        "input_tokens": sum(row["input_tokens"] for row in by_model.values()),
        "output_tokens": sum(row["output_tokens"] for row in by_model.values()),
        "paid_cost_usd": round(float(payload.get("paid_cost_usd") or 0.0), 6),
        "updated_at": payload.get("updated_at") or "",
    }


def last_status(provider, model, day=None) -> dict:
    payload = read_day(day)
    row = (payload.get("by_model") or {}).get(f"{provider}:{model}") or {}
    return {
        "last_status": row.get("last_status") or "",
        "last_category": row.get("last_category") or "",
        "last_at": row.get("last_at") or "",
    }
