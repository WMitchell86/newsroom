"""Role-based model policy: one non-secret place for "which model, in what order".

Secrets stay in environment variables. This module owns only the *policy*:

```text
config/model_policy.default.json   tracked defaults (this repo)
var/model_policy.json              operator override, optional
```

Both files describe the same schema:

```json
{
  "version": 1,
  "global": {"paid_enabled": false, "soft_paid_budget_usd_day": 2.0},
  "roles": {
    "story": {
      "soft_calls_day": 60, "hard_calls_day": 100,
      "on_exhausted": "conservative",
      "default_payload_class": "public",
      "routes": [
        {"provider": "gemini", "model": "gemini-3.8-flash",
         "enabled": true, "billing": "operator_declared",
         "public_only": false, "daily_call_limit": 20},
        {"provider": "openrouter", "model": "openai/gpt-5.6-luna", "billing": "paid"}
      ]
    }
  }
}
```

Contract for a route (enforced by `validate_policy` and by the router):

* **order is authoritative** — the first route that is enabled, allowed by the
  paid gate, within budget, not blocked by the active privacy gate and not known
  unhealthy wins;
* a role may mix providers, and a missing/unavailable provider is a *skip*, not
  a stop (this is what makes Gemini -> OpenRouter fallback real);
* `billing`: `free` (no cost), `paid` (needs `global.paid_enabled`), or
  `operator_declared` (the operator's own quota, e.g. Gemini free tier).
  **OpenRouter routes must state `free` or `paid` explicitly — there is no
  billing default for OpenRouter** (pre-frontend gate A1: an omitted billing
  class must never silently become free and bypass `paid_enabled`);
* **privacy routing**: `public_only: true` is always retained in the policy and
  status report. A private payload is blocked only when the project-level
  `global.privacy_gate_enabled` is true; this project defaults it to false, as
  decided by the owner. This switch does not alter billing or secret hygiene.
  **`openrouter` + `billing=free` always means `public_only=true`** — a policy
  that declares the combination `free + public_only=false` is rejected (A2);
* `daily_call_limit` is the operator-declared per-model quota (Gemini meters
  each model separately). The router counts local *provider attempts* per model
  per Europe/Sofia day and skips a spent route; provider 429 signals win over
  it. The role `soft_calls_day`/`hard_calls_day` caps count *logical requests*
  (one `call_role()` invocation is one request regardless of skips/fallbacks) —
  per-model quotas and role caps are two different controls, both adjustable
  from `/models` or `newsroom models set`.

Legacy env knobs stay supported as policy overrides (`GEMINI_<ROLE>_MODELS`,
`OPENROUTER_<ROLE>_MODEL`), so an existing `.env` keeps working; the policy file
is the new default surface. Nothing here calls the network — live model-id
verification is `newsroom models validate`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: The seven roles the router understands. `judge` is the only mechanical one;
#: `story`/`angle`/`draft` are quality-sensitive and must never inherit the
#: weak judge pool by accident.
ROLES = ("judge", "story", "angle", "draft", "research", "extract", "utility")

PROVIDERS = ("gemini", "openrouter")
BILLING = ("free", "paid", "operator_declared")
PAYLOAD_CLASSES = ("public", "private")
ON_EXHAUSTED = (
    "conservative",  # never merge / never invent (story)
    "review_required",  # availability failure is NOT a pass (judge)
    "degraded",  # explicit degraded state, no fabricated verdict (angle)
    "fail_visible",  # fail loudly, never silently to an unqualified model (draft)
    "deterministic",  # fall back to the deterministic path (research)
    "distinguish_zero",  # execution failure != "zero facts" (extract)
    "cheap_only",  # free/cheap routes only (utility)
)

DEFAULT_POLICY_PATH = ROOT / "config" / "model_policy.default.json"

#: Operator-declared per-model RPD (Gemini AI Studio, 2026-09-21). Used only to
#: fill `daily_call_limit` for routes that come from an env override; the policy
#: file is authoritative for everything else.
GEMINI_DAILY_LIMITS = {
    "gemini-3.5-flash-lite": 500,
    "gemini-3.1-flash-lite": 500,
    "gemini-3-flash-preview": 20,
    "gemini-3.5-flash": 20,
    "gemini-3.6-flash": 20,
    "gemini-3.7-flash": 20,
    "gemini-3.8-flash": 20,
    "gemini-2.5-flash": 20,
    "gemini-2.5-flash-lite": 20,
}

#: Models that reject `generationConfig.thinkingConfig` (HTTP 400). Filled from
#: the env override path; the policy file can also set `omit_thinking_config`.
GEMINI_NO_THINKING_CONFIG = frozenset({"gemini-3.5-flash-lite"})


class PolicyError(ValueError):
    """Invalid policy — fail closed, never guess what the operator meant."""


def policy_path() -> Path:
    """Operator override path (`MODEL_POLICY_PATH` or `var/model_policy.json`)."""
    override = os.environ.get("MODEL_POLICY_PATH")
    return Path(override) if override else ROOT / "var" / "model_policy.json"


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"{path}: невалиден JSON ({exc})") from exc


def load_defaults() -> dict:
    payload = _read_json(DEFAULT_POLICY_PATH)
    if not isinstance(payload, dict):
        raise PolicyError(f"липсва или е невалиден {DEFAULT_POLICY_PATH}")
    return payload


def _merge(base, override):
    """Deep merge; lists are replaced whole (route order is the operator's)."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _normalize_route(route, *, role):
    if not isinstance(route, dict):
        raise PolicyError(f"{role}: route must be an object, got {type(route).__name__}")
    provider = str(route.get("provider") or "").strip().lower()
    model = str(route.get("model") or "").strip()
    if provider not in PROVIDERS:
        raise PolicyError(f"{role}: неизвестен provider {provider!r}")
    if not model:
        raise PolicyError(f"{role}: route без model")
    raw_billing = route.get("billing")
    if provider == "openrouter":
        # A1/A2 (pre-frontend gate): OpenRouter billing is always explicit and
        # free always means public-only — neither is ever defaulted.
        if not raw_billing:
            raise PolicyError(
                f"{role}: OpenRouter маршрут {model!r} трябва да посочи billing "
                "(free | paid) — безплатен не се предполага никога"
            )
        billing = str(raw_billing)
        if billing not in ("free", "paid"):
            raise PolicyError(
                f"{role}: OpenRouter billing трябва да е free или paid, не {billing!r}"
            )
        if billing == "free":
            declared = route.get("public_only")
            if declared is not None and not bool(declared):
                raise PolicyError(
                    f"{role}: free OpenRouter маршрут {model!r} изисква public_only=true — "
                    "безплатните endpoints не получават непубликувани материали"
                )
            public_only = True
        else:
            public_only = bool(route.get("public_only", False))
    else:
        billing = str(raw_billing or "operator_declared")
        if billing not in BILLING:
            raise PolicyError(f"{role}: непознат billing {billing!r}")
        public_only = bool(route.get("public_only", False))
    out = {
        "provider": provider,
        "model": model,
        "enabled": bool(route.get("enabled", True)),
        "billing": billing,
        "public_only": public_only,
    }
    limit = route.get("daily_call_limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise PolicyError(f"{role}: daily_call_limit трябва да е цяло число") from None
        if limit <= 0:
            raise PolicyError(f"{role}: daily_call_limit трябва да е положително число")
        out["daily_call_limit"] = limit
    if route.get("omit_thinking_config") or (
        provider == "gemini" and model in GEMINI_NO_THINKING_CONFIG
    ):
        out["omit_thinking_config"] = True
    note = str(route.get("note") or "").strip()
    if note:
        out["note"] = note
    return out


def normalize(policy: dict) -> dict:
    """Copy-with-normalized-routes; raises `PolicyError` on structural problems."""
    if not isinstance(policy, dict):
        raise PolicyError("policy must be a JSON object")
    raw_roles = policy.get("roles")
    if not isinstance(raw_roles, dict) or not raw_roles:
        raise PolicyError("policy.roles must be a non-empty object")
    unknown = sorted(set(raw_roles) - set(ROLES))
    if unknown:
        raise PolicyError(f"непознати роли: {unknown} (позволени: {list(ROLES)})")
    missing = [role for role in ROLES if role not in raw_roles]
    if missing:
        raise PolicyError(f"липсващи роли в policy: {missing}")
    global_raw = policy.get("global") or {}
    if not isinstance(global_raw, dict):
        raise PolicyError("policy.global must be an object")
    out_global = {
        # Public/private remains auditable on every route.  This project-level
        # switch controls only whether that metadata blocks editorial payloads.
        "privacy_gate_enabled": bool(global_raw.get("privacy_gate_enabled", False)),
        "paid_enabled": bool(global_raw.get("paid_enabled", False)),
        "soft_paid_budget_usd_day": float(global_raw.get("soft_paid_budget_usd_day", 0.0) or 0.0),
        "max_transient_attempts": int(global_raw.get("max_transient_attempts", 2) or 0),
        "max_rate_limited_attempts": int(global_raw.get("max_rate_limited_attempts", 1) or 0),
    }
    roles = {}
    for role in ROLES:
        raw = raw_roles[role]
        if not isinstance(raw, dict):
            raise PolicyError(f"{role}: role must be an object")
        routes_raw = raw.get("routes")
        if not isinstance(routes_raw, list) or not routes_raw:
            raise PolicyError(f"{role}: needs a non-empty routes list")
        routes = [_normalize_route(r, role=role) for r in routes_raw]
        default_payload = str(raw.get("default_payload_class") or "private").strip().lower()
        if default_payload not in PAYLOAD_CLASSES:
            raise PolicyError(f"{role}: default_payload_class must be one of {PAYLOAD_CLASSES}")
        on_exhausted = str(raw.get("on_exhausted") or "review_required").strip().lower()
        if on_exhausted not in ON_EXHAUSTED:
            raise PolicyError(f"{role}: on_exhausted must be one of {ON_EXHAUSTED}")
        soft = int(raw.get("soft_calls_day", 0) or 0)
        hard = int(raw.get("hard_calls_day", 0) or 0)
        if hard and soft and soft > hard:
            raise PolicyError(f"{role}: soft_calls_day ({soft}) > hard_calls_day ({hard})")
        roles[role] = {
            "label": str(raw.get("label") or role),
            "purpose": str(raw.get("purpose") or ""),
            "default_payload_class": default_payload,
            "on_exhausted": on_exhausted,
            "soft_calls_day": soft,
            "hard_calls_day": hard,
            "routes": routes,
        }
    return {"version": int(policy.get("version", 1) or 1), "global": out_global, "roles": roles}


# ---------------------------------------------------------------- env overrides


def _env_gemini_models(role):
    for name in (f"GEMINI_{role.upper()}_MODELS", "GEMINI_DRAFT_MODELS" if role == "draft" else ""):
        if not name:
            continue
        raw = os.environ.get(name, "").strip()
        if raw:
            return [m.strip() for m in raw.split(",") if m.strip()]
    return None


def _env_openrouter_model(role):
    for name in (f"OPENROUTER_{role.upper()}_MODEL", "OPENROUTER_MODEL"):
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return None


def _classify_env_openrouter_model(model: str) -> str:
    """Classify legacy env substitutions without inheriting stale billing."""
    if model in known_free_models():
        return "free"
    # Unknown explicit ids fail paid-safe. This prevents a paid model from
    # inheriting a free slot (and a free private payload from bypassing policy).
    return "paid"


def apply_env_overrides(policy: dict) -> dict:
    """Legacy env knobs override matching routes (documented in `.env.example`).

    Gemini substitutions retain the operator-declared quota class. OpenRouter
    substitutions are reclassified from the exact id: known free ids stay free;
    every other explicit id is paid-safe. The normalized result remains auditable
    and never inherits stale billing from the replaced route slot.
    """
    out = json.loads(json.dumps(policy))
    for role in ROLES:
        routes = out["roles"][role]["routes"]
        gemini_models = _env_gemini_models(role)
        if gemini_models:
            template = next((r for r in routes if r["provider"] == "gemini"), None)
            fresh = []
            for model in gemini_models:
                route = {
                    "provider": "gemini",
                    "model": model,
                    "enabled": True,
                    "billing": (template or {}).get("billing", "operator_declared"),
                    "public_only": False,
                }
                limit = GEMINI_DAILY_LIMITS.get(model)
                if limit:
                    route["daily_call_limit"] = limit
                if model in GEMINI_NO_THINKING_CONFIG:
                    route["omit_thinking_config"] = True
                fresh.append(route)
            routes[:] = fresh + [r for r in routes if r["provider"] != "gemini"]
        model = _env_openrouter_model(role)
        if model:
            for route in routes:
                if route["provider"] == "openrouter":
                    route["model"] = model
                    route["billing"] = _classify_env_openrouter_model(model)
                    route["public_only"] = route["billing"] == "free"
                    break
        free_model = os.environ.get("OPENROUTER_FREE_MODEL", "").strip()
        if free_model:
            route = next(
                (r for r in routes if r["provider"] == "openrouter" and r["billing"] == "free"),
                None,
            )
            if route is not None:
                route["model"] = free_model
                route["billing"] = "free"
                route["public_only"] = True
    return normalize(out)


def load_policy(path=None, *, env_overrides=True) -> dict:
    """Defaults + operator override (if present), normalized. Never raises for a
    *missing* override; a malformed override raises `PolicyError` (fail closed)."""
    override = _read_json(Path(path) if path else policy_path()) or {}
    if not isinstance(override, dict):
        raise PolicyError(f"{Path(path) if path else policy_path()}: политиката трябва да е обект")
    # A saved override is a partial diff (see `save_policy`); merge it per role so
    # a role the operator never touched still follows the tracked defaults.
    merged = _merge(load_defaults(), override)
    policy = normalize(merged)
    return apply_env_overrides(policy) if env_overrides else policy


def _diff(base, new):
    """Minimal override of `base` that produces `new` (lists are replaced whole)."""
    if isinstance(base, dict) and isinstance(new, dict):
        out = {}
        for key, value in new.items():
            if key not in base:
                out[key] = value
                continue
            sub = _diff(base[key], value)
            if sub != {}:
                out[key] = sub
        return out
    if base == new:
        return {}
    return new


def save_policy(policy: dict, path=None) -> Path:
    """Write the operator override as a **diff against the tracked defaults**.

    Persisting the whole merged policy would freeze every default in place: a
    later improvement to `config/model_policy.default.json` would then be silently
    shadowed by the operator's old copy. Only what the operator actually changed
    is stored, so untouched roles keep following the tracked defaults.
    """
    target = Path(path) if path else policy_path()
    payload = _diff(normalize(load_defaults()), normalize(policy))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)
    return target


def policy_hash(policy: dict) -> str:
    """Stable fingerprint of the routing surface (config-change detection)."""
    blob = json.dumps(policy, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def validate_policy(policy: dict) -> list:
    """Offline structural check (no live catalog). Returns problem strings."""
    try:
        normalize(policy)
    except PolicyError as exc:
        return [str(exc)]
    return []


# ---------------------------------------------------------------- read helpers


def role_policy(policy: dict, role: str) -> dict:
    if role not in policy["roles"]:
        raise PolicyError(f"непозната роля: {role!r} (позволени: {list(ROLES)})")
    return policy["roles"][role]


def known_billing(policy: dict, model: str) -> str:
    """Billing class the policy already declares for a model id; `""` when
    the id is undeclared.

    Used when a legacy caller passes an explicit `model=`: the explicit id is
    tried first, but it may not silently bypass the paid gate. An **unknown id
    is NOT free** (A3): the router fails paid-safe until a policy declaration
    or a live catalog validation proves the model free.
    """
    for role in policy.get("roles", {}).values():
        for route in role.get("routes") or []:
            if route.get("model") == model:
                return str(route.get("billing") or "")
    return ""


def route_label(route) -> str:
    return f"{route['provider']}:{route['model']}"


def route_billing_label(route) -> str:
    return {
        "free": "FREE",
        "paid": "PAID",
        "operator_declared": "FREE (собствена квота)",
    }.get(route.get("billing", ""), route.get("billing", ""))


def known_free_models() -> set:
    """Free OpenRouter ids seen in the tracked defaults (offline hint only)."""
    out = set()
    try:
        defaults = load_defaults()
    except PolicyError:
        return out
    for role in (defaults.get("roles") or {}).values():
        for route in role.get("routes") or []:
            if isinstance(route, dict) and route.get("billing") == "free":
                out.add(str(route.get("model") or ""))
    return out


# ---------------------------------------------------------------- editing helpers


def reorder_route(policy: dict, role: str, index: int, *, direction) -> dict:
    """Move one route up/down inside its role (the operator's ✓ reorder control)."""
    routes = role_policy(policy, role)["routes"]
    if not 0 <= index < len(routes):
        raise PolicyError(f"{role}: няма маршрут с индекс {index}")
    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(routes):
        raise PolicyError("маршрутът вече е в края на списъка")
    routes[index], routes[target] = routes[target], routes[index]
    return policy


def set_route_enabled(policy: dict, role: str, index: int, enabled: bool) -> dict:
    routes = role_policy(policy, role)["routes"]
    if not 0 <= index < len(routes):
        raise PolicyError(f"{role}: няма маршрут с индекс {index}")
    routes[index]["enabled"] = bool(enabled)
    return policy


def add_route(policy: dict, role: str, route: dict, *, position=None) -> dict:
    routes = role_policy(policy, role)["routes"]
    normalized = _normalize_route(route, role=role)
    if position is None:
        routes.append(normalized)
    else:
        routes.insert(max(int(position), 0), normalized)
    return policy


def remove_route(policy: dict, role: str, index: int) -> dict:
    routes = role_policy(policy, role)["routes"]
    if not 0 <= index < len(routes):
        raise PolicyError(f"{role}: няма маршрут с индекс {index}")
    if len(routes) == 1:
        raise PolicyError(f"{role}: последният маршрут не може да се премахне")
    routes.pop(index)
    return policy


def set_global(policy: dict, **changes) -> dict:
    allowed = {"privacy_gate_enabled", "paid_enabled", "soft_paid_budget_usd_day"}
    unknown = sorted(set(changes) - allowed)
    if unknown:
        raise PolicyError(f"непознати глобални настройки: {unknown}")
    policy.setdefault("global", {}).update(changes)
    return policy


def set_role_budget(policy: dict, role: str, *, soft_calls_day=None, hard_calls_day=None) -> dict:
    role_raw = role_policy(policy, role)
    if soft_calls_day is not None:
        role_raw["soft_calls_day"] = int(soft_calls_day)
    if hard_calls_day is not None:
        role_raw["hard_calls_day"] = int(hard_calls_day)
    return policy
