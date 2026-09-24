"""One shared role router: ordered routes, true cross-provider fallback, budgets.

`call_role(role, prompt, ...)` walks the ordered route list of that role from the
policy store (`drafting/model_policy.py`) and:

```text
for route in role.routes:
    skip if disabled
    skip if paid and paid is not enabled
    skip if the route is public-only and the payload is private
    skip if the route/model budget for today is spent
    skip if the route is temporarily exhausted / unhealthy
    try the route
    on failure: classify, mark health, continue only when it is safe to continue
```

The behaviour this replaces: when `GEMINI_API_KEY` was present, an exhausted
Gemini pool stopped the whole call — OpenRouter was never reached. Here a
provider is a *route*, not the process, so Gemini exhaustion genuinely falls
through to OpenRouter (PART 3).

Failure classes (PART 3):

```text
QUOTA_EXHAUSTED   429 + daily/quota marker  -> route exhausted for the provider
                                              period, continue to the next route
RATE_LIMITED      429 transient             -> bounded retry, then continue
INVALID_MODEL     400/404/422               -> route unhealthy until the policy
                                              changes or `models validate` revalidates
AUTH              401/403                   -> route unhealthy, continue
PAYMENT_REQUIRED  402 (no credits)          -> route unhealthy until the account or
                                              the policy changes (never retried blindly)
TRANSIENT         5xx / network / timeout   -> bounded retry, then continue
EMPTY_OUTPUT      empty or malformed answer -> one bounded retry, then continue
NO_KEY            provider key missing      -> skip, continue
```

Nothing loops indefinitely; every attempt is recorded in the usage ledger, and
the whole routing trace travels with the failure so the operator can see exactly
which routes were tried and why each was skipped.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from editor_assistant.drafting import model_policy, model_usage

ROOT = Path(__file__).resolve().parents[3]

STATUS_EXHAUSTED = "EXHAUSTED"
STATUS_INVALID = "INVALID"
STATUS_RATE_LIMITED = "RATE_LIMITED"

QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
RATE_LIMITED = "RATE_LIMITED"
INVALID_MODEL = "INVALID_MODEL"
AUTH_FAILED = "AUTH_FAILED"
PAYMENT_REQUIRED = "PAYMENT_REQUIRED"
TRANSIENT = "TRANSIENT"
EMPTY_OUTPUT = "EMPTY_OUTPUT"
NO_KEY = "NO_KEY"
PAID_DISABLED = "PAID_DISABLED"
PRIVACY_BLOCKED = "PRIVACY_BLOCKED"
MODEL_LIMIT_REACHED = "MODEL_LIMIT_REACHED"
ROLE_HARD_BUDGET = "ROLE_HARD_BUDGET"
ROUTE_UNHEALTHY = "ROUTE_UNHEALTHY"

#: Categories that mean "this route is not usable for a while".
_UNHEALTHY_FOR_THE_PERIOD = {QUOTA_EXHAUSTED}
_UNHEALTHY_UNTIL_POLICY_CHANGES = {INVALID_MODEL, AUTH_FAILED, PAYMENT_REQUIRED}

#: Marker substrings that mean "daily quota", not "requests per minute".
_DAILY_QUOTA_MARKERS = (
    "current quota",
    "quotafailure",
    "quota_exceeded",
    "per day",
    "daily limit",
    "rpd",
)

_DAILY_QUOTA_CATEGORIES = {QUOTA_EXHAUSTED, MODEL_LIMIT_REACHED, ROLE_HARD_BUDGET}


class RoleUnavailable(RuntimeError):
    """No usable route for a role. A `RuntimeError` so legacy callers still catch it.

    `on_exhausted` carries the role's safe-degradation contract (see
    `model_policy.ON_EXHAUSTED`); callers must honour it rather than inventing an
    answer — e.g. the story role must never merge on this error, and the judge
    role must never treat it as a pass.
    """

    def __init__(self, role, reason, *, on_exhausted="review_required", trace=None):
        super().__init__(f"{role}: {reason}")
        self.role = role
        self.reason = reason
        self.on_exhausted = on_exhausted
        self.trace = list(trace or [])


def health_path() -> Path:
    override = os.environ.get("MODEL_HEALTH_PATH")
    return Path(override) if override else ROOT / "var" / "model_health.json"


def _utc_now(moment=None):
    return moment or datetime.now(timezone.utc)


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_health() -> dict:
    path = health_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_health(state: dict) -> None:
    path = health_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")
    os.replace(tmp, path)


def route_key(route) -> str:
    return f"{route.get('provider')}:{route.get('model')}"


def mark_route(route, status, *, reason="", policy_hash="", now=None) -> dict:
    """Persist a route health decision; returns the stored record."""
    state = read_health()
    key = route_key(route)
    record = {
        "status": status,
        "reason": reason[:300],
        "policy_hash": policy_hash,
        "at": _iso(_utc_now(now)),
        "until": "",
    }
    if status == STATUS_EXHAUSTED:
        record["until"] = _iso(reset_moment(route.get("provider"), now=now))
    if status == STATUS_RATE_LIMITED:
        record["until"] = _iso(_utc_now(now) + timedelta(minutes=2))
    state[key] = record
    write_health(state)
    return record


def clear_route(route) -> None:
    state = read_health()
    state.pop(route_key(route), None)
    write_health(state)


def reset_moment(provider, *, now=None):
    """Provider-appropriate quota reset (never assume Sofia midnight)."""
    moment = _utc_now(now)
    try:
        if provider == "gemini":
            from zoneinfo import ZoneInfo

            pacific = moment.astimezone(ZoneInfo("America/Los_Angeles"))
            nxt = (pacific + timedelta(days=1)).date()
            return datetime.combine(nxt, datetime.min.time(), tzinfo=pacific.tzinfo)
        return datetime.combine(
            (moment.astimezone(timezone.utc) + timedelta(days=1)).date(),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    except Exception:  # noqa: BLE001 - missing tzdata must not break routing
        return moment + timedelta(hours=24)


def route_health(route, *, policy_hash="", now=None) -> dict:
    """Current health of a route; stale entries are treated as healthy.

    EXHAUSTED expires when the provider resets. INVALID/AUTH stay until the
    policy changes or an explicit revalidation clears them (PART 3) — a removed
    model must not burn a request on every call.
    """
    record = read_health().get(route_key(route)) or {}
    status = record.get("status") or ""
    if not status:
        return {"status": "", "reason": ""}
    moment = _utc_now(now)
    if status == STATUS_INVALID:
        # A removed model / bad credential does not fix itself by waiting: it stays
        # unhealthy until the policy changes or `models validate` revalidates it.
        if policy_hash and record.get("policy_hash") == policy_hash:
            return record
        return {"status": "", "reason": ""}
    until = record.get("until") or ""
    if until:
        try:
            if (
                datetime.strptime(until, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                <= moment
            ):
                return {"status": "", "reason": ""}
        except ValueError:
            return {"status": "", "reason": ""}
    return record


def classify_failure(exc) -> str:
    """One failure class per exception, using the provider's own signals."""
    body = getattr(exc, "_chernomorie_body", "") or ""
    if not body and hasattr(exc, "read"):
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            body = ""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        if code in (400, 404, 422):
            return INVALID_MODEL
        if code == 402:
            # The provider refuses for billing reasons (OpenRouter: no credits).
            # That is not a transient failure: retrying wastes time and never fixes it.
            return PAYMENT_REQUIRED
        if code in (401, 403):
            return AUTH_FAILED
        if code == 429:
            lowered = str(body).lower()
            if any(marker in lowered for marker in _DAILY_QUOTA_MARKERS):
                return QUOTA_EXHAUSTED
            return RATE_LIMITED
        if 500 <= code < 600:
            return TRANSIENT
        return TRANSIENT
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return TRANSIENT
    return TRANSIENT


def _category_is_daily(category) -> bool:
    return category in _DAILY_QUOTA_CATEGORIES


def _gemini_key(api_key=None) -> str:
    return str(api_key or os.environ.get("GEMINI_API_KEY", "") or "")


def _openrouter_key() -> str:
    return str(os.environ.get("OPENROUTER_API_KEY", "") or "")


def _keys_available(api_key=None) -> dict:
    """Which providers have a usable key for this call (explicit key wins)."""
    return {
        "gemini": bool(_gemini_key(api_key)),
        "openrouter": bool(_openrouter_key()),
    }


def _default_callers():
    """Lazily resolve the transports (attribute lookup so tests can patch them)."""
    from editor_assistant.drafting import generate

    return generate._call_gemini, generate._call_openrouter


def _tokens_from_meta(meta) -> tuple:
    usage = (meta or {}).get("usage") or {}
    inp = usage.get("promptTokenCount") or usage.get("prompt_tokens") or 0
    out = usage.get("candidatesTokenCount") or usage.get("completion_tokens") or 0
    return int(inp or 0), int(out or 0)


def plan_routes(role, *, policy=None, payload_class=None, model=None, now=None, keys=None) -> dict:
    """What `call_role` would do right now, without calling anything (UI/CLI read).

    Returns `{"role", "payload_class", "on_exhausted", "routes": [...]}` where each
    row carries `eligible`, `reason` and the day's counters.
    """
    policy = policy or model_policy.load_policy()
    role_raw = model_policy.role_policy(policy, role)
    payload = payload_class or role_raw["default_payload_class"]
    digest = model_policy.policy_hash(policy)
    hard = role_raw.get("hard_calls_day") or 0
    role_calls = model_usage.role_calls_today(role)
    rows = []
    routes = [dict(r) for r in role_raw["routes"]]
    if model:
        routes.insert(0, _explicit_route(policy, model))
    for index, route in enumerate(routes):
        candidate = dict(route)
        reasons = _skip_reasons(
            candidate,
            role,
            payload_class=payload,
            policy=policy,
            policy_hash=digest,
            role_calls=role_calls,
            hard=hard,
            now=now,
            keys=keys,
        )
        rows.append(
            {
                "index": index,
                "provider": candidate.get("provider"),
                "model": candidate.get("model"),
                "enabled": bool(candidate.get("enabled", True)),
                "billing": candidate.get("billing"),
                "public_only": bool(candidate.get("public_only")),
                "daily_call_limit": candidate.get("daily_call_limit"),
                "omit_thinking_config": bool(candidate.get("omit_thinking_config")),
                "calls_today": model_usage.model_calls_today(
                    candidate.get("provider"), candidate.get("model")
                ),
                "eligible": not reasons,
                "reason": "; ".join(reasons),
                "health": route_health(candidate, policy_hash=digest, now=now),
            }
        )
    return {
        "role": role,
        "label": role_raw.get("label") or role,
        "purpose": role_raw.get("purpose") or "",
        "on_exhausted": role_raw["on_exhausted"],
        "payload_class": payload,
        "soft_calls_day": role_raw.get("soft_calls_day") or 0,
        "hard_calls_day": hard,
        "calls_today": role_calls,
        "soft_exceeded": bool(role_raw.get("soft_calls_day"))
        and role_calls > int(role_raw["soft_calls_day"]),
        "routes": rows,
    }


def _skip_reasons(
    route, role, *, payload_class, policy, policy_hash, role_calls, hard, now=None, keys=None
):
    reasons = []
    keys = keys if keys is not None else _keys_available()
    if not route.get("enabled", True):
        reasons.append("изключен маршрут")
    billing = route.get("billing")
    if billing == "paid" and not policy["global"].get("paid_enabled"):
        reasons.append("платените модели са изключени")
    if route.get("public_only") and payload_class == "private":
        reasons.append("маршрутът е само за публични материали")
    limit = route.get("daily_call_limit")
    if limit and model_usage.model_calls_today(route.get("provider"), route.get("model")) >= int(
        limit
    ):
        reasons.append(f"дневен лимит на модела ({limit}) е достигнат")
    if hard and role_calls >= int(hard):
        reasons.append(f"твърд дневен лимит на ролята ({hard}) е достигнат")
    health = route_health(route, policy_hash=policy_hash, now=now)
    if health.get("status"):
        reasons.append(f"маршрутът е {health['status']}: {health.get('reason') or ''}".strip())
    if route.get("provider") == "gemini" and not keys.get("gemini"):
        reasons.append("липсва GEMINI_API_KEY")
    if route.get("provider") == "openrouter" and not keys.get("openrouter"):
        reasons.append("липсва OPENROUTER_API_KEY")
    return reasons


def _record(entry, *, fallbacks=0, payload_class="", latency_ms=0):
    model_usage.record(
        {**entry, "fallbacks": fallbacks, "payload_class": payload_class, "latency_ms": latency_ms}
    )


def _new_request_id() -> str:
    """One id per `call_role()` invocation: the unit role budgets count (B1).
    No prompt content ever enters the ledger — the id is opaque."""
    return uuid.uuid4().hex


def call_role(
    role,
    prompt_text,
    *,
    payload_class=None,
    timeout=240,
    api_key=None,
    policy=None,
    model=None,
    call_map=None,
    sleep=None,
    now=None,
):
    """Call the first eligible route of `role`; return `(text, meta)`.

    Raises `RoleUnavailable` when no route succeeded; the exception carries the
    role's safe-degradation mode and the full routing trace.
    """
    policy = policy or model_policy.load_policy()
    role_raw = model_policy.role_policy(policy, role)
    payload = payload_class or role_raw["default_payload_class"]
    digest = model_policy.policy_hash(policy)
    hard = int(role_raw.get("hard_calls_day") or 0)
    soft = int(role_raw.get("soft_calls_day") or 0)
    sleep = sleep or time.sleep
    callers = call_map or {}
    gemini_key = _gemini_key(api_key)
    keys = _keys_available(api_key)
    trace = []
    # B1: every ledger row of this invocation carries the same request id.
    request_id = _new_request_id()

    routes = [dict(r) for r in role_raw["routes"]]
    if model:
        # An explicit model (legacy callers, eval harness) is tried FIRST, but it
        # may not bypass the paid gate: billing comes from whatever the policy
        # already declares for that id, else it fails paid-safe (A3); a free
        # explicit route is public-only like every other free route (A2).
        routes.insert(0, _explicit_route(policy, model))

    attempts = 0
    fallbacks = 0
    role_calls = model_usage.role_calls_today(role)
    for index, route in enumerate(routes):
        reasons = _skip_reasons(
            route,
            role,
            payload_class=payload,
            policy=policy,
            policy_hash=digest,
            role_calls=role_calls,
            hard=hard,
            now=now,
            keys=keys,
        )
        for reason in reasons:
            trace.append(
                {
                    "route_index": index,
                    "route": route_key(route),
                    "event": "SKIPPED",
                    "reason": reason,
                }
            )
        if reasons:
            # A skipped route still counts as a fallback step: the operator's
            # "how many fallbacks did this answer need" number stays honest.
            # It is NOT a provider call: provider_attempts=0 keeps disabled /
            # privacy / paid / missing-key skips out of every budget (B3/B4).
            fallbacks += 1
            _record(
                {
                    "request_id": request_id,
                    "role": role,
                    "provider": route.get("provider"),
                    "model": route.get("model"),
                    "route_index": index,
                    "status": model_usage.STATUS_SKIPPED,
                    "category": _skip_category(reasons),
                    "provider_attempts": 0,
                },
                fallbacks=fallbacks - 1,
                payload_class=payload,
            )
            continue

        text, meta, category, provider_attempts = _try_route(
            route,
            role,
            prompt_text,
            index=index,
            timeout=timeout,
            gemini_key=gemini_key,
            payload_class=payload,
            policy=policy,
            digest=digest,
            callers=callers,
            sleep=sleep,
            fallbacks=fallbacks,
            reasons=trace,
            now=now,
        )
        if text is not None:
            meta = dict(meta or {})
            meta.update(
                {
                    "role": role,
                    "route_index": index,
                    "fallbacks": fallbacks,
                    "payload_class": payload,
                    "on_exhausted": role_raw["on_exhausted"],
                    "soft_budget_exceeded": bool(soft) and role_calls > soft,
                }
            )
            if bool(soft) and role_calls > soft:
                trace.append(
                    {"route_index": index, "event": "WARNING", "reason": "soft budget exceeded"}
                )
            meta["trace"] = trace
            model_usage.record(
                {
                    "request_id": request_id,
                    "role": role,
                    "provider": route.get("provider"),
                    "model": route.get("model"),
                    "route_index": index,
                    "status": model_usage.STATUS_OK,
                    "category": "",
                    # B2: retries on this route are real provider attempts.
                    "provider_attempts": provider_attempts,
                    "input_tokens": meta.get("input_tokens") or 0,
                    "output_tokens": meta.get("output_tokens") or 0,
                    "cost_usd": meta.get("cost_usd") or 0.0,
                    "fallbacks": fallbacks,
                    "payload_class": payload,
                }
            )
            return text, meta
        attempts += 1
        fallbacks += 1
        _record(
            {
                "request_id": request_id,
                "role": role,
                "provider": route.get("provider"),
                "model": route.get("model"),
                "route_index": index,
                "status": model_usage.STATUS_FAILED,
                "category": category,
                "provider_attempts": provider_attempts,
            },
            fallbacks=fallbacks - 1,
            payload_class=payload,
        )
        trace.append(
            {"route_index": index, "route": route_key(route), "event": "FAILED", "reason": category}
        )

    reason = (
        "няма успешен маршрут"
        if attempts
        else "няма достъпен маршрут (липсващ ключ, лимит, изключени платени модели или политика)"
    )
    raise RoleUnavailable(role, reason, on_exhausted=role_raw["on_exhausted"], trace=trace)


def _explicit_route(policy, model) -> dict:
    # A3: an id the policy never declared is paid-safe — an unknown model may
    # not bypass the paid gate just because nobody wrote it down. The price
    # snapshot still forces `paid` for known-priced ids, and a free explicit
    # route stays public-only (A2) like every other free OpenRouter route.
    billing = model_policy.known_billing(policy, model) or "paid"
    if billing not in ("free", "paid"):
        billing = "paid"
    if model in model_usage.PRICES_USD_PER_MTOK:
        billing = "paid"
    return {
        "provider": "openrouter",
        "model": model,
        "enabled": True,
        "billing": billing,
        "public_only": billing == "free",
        "explicit": True,
    }


def _skip_category(reasons) -> str:
    joined = " ".join(reasons)
    for marker, category in (
        ("платените", PAID_DISABLED),
        ("публични", PRIVACY_BLOCKED),
        ("дневен лимит на модела", MODEL_LIMIT_REACHED),
        ("твърд дневен лимит", ROLE_HARD_BUDGET),
        ("липсва", NO_KEY),
    ):
        if marker in joined:
            return category
    return ROUTE_UNHEALTHY


def _try_route(
    route,
    role,
    prompt_text,
    *,
    index,
    timeout,
    gemini_key,
    payload_class,
    policy,
    digest,
    callers,
    sleep,
    fallbacks,
    reasons,
    now,
):
    """Try one route with bounded retries.

    Returns `(text|None, meta|None, category, provider_attempts)`: the last
    value is how many real transport calls this route made (B2) — a success
    after one 429 retry reports 2, a route never entered reports 0 (the skip
    path never reaches this function).
    """
    gemini_call = callers.get("gemini")
    openrouter_call = callers.get("openrouter")
    if not callers:
        gemini_call, openrouter_call = _default_callers()

    provider = route.get("provider")
    max_transient = int(policy["global"].get("max_transient_attempts", 2) or 0)
    max_rate_limited = int(policy["global"].get("max_rate_limited_attempts", 1) or 0)
    max_empty = 1
    attempts_allowed = {
        TRANSIENT: max(1, max_transient),
        RATE_LIMITED: max(1, max_rate_limited + 1),
        EMPTY_OUTPUT: max_empty + 1,
    }
    attempt = 0
    while True:
        attempt += 1
        started = time.monotonic()
        try:
            if provider == "gemini":
                kwargs = {
                    "api_key": gemini_key,
                    "timeout": timeout,
                    "role": role,
                    "model": route.get("model"),
                }
                if route.get("omit_thinking_config"):
                    kwargs["omit_thinking_config"] = True
                text, meta = gemini_call(prompt_text, **kwargs)
            else:
                from editor_assistant.drafting.generate import _check_openrouter_model_not_paid

                _check_openrouter_model_not_paid(route.get("model"))
                text, meta = openrouter_call(
                    prompt_text,
                    api_key=_openrouter_key(),
                    timeout=timeout,
                    model=route.get("model"),
                )
        except RoleUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - every provider failure is classified
            category = classify_failure(exc)
            if category in _UNHEALTHY_UNTIL_POLICY_CHANGES:
                mark_route(
                    route,
                    STATUS_INVALID,
                    reason=f"{category}: {str(exc)[:200]}",
                    policy_hash=digest,
                    now=now,
                )
            elif category in _UNHEALTHY_FOR_THE_PERIOD:
                mark_route(
                    route,
                    STATUS_EXHAUSTED,
                    reason=f"{category}: {str(exc)[:200]}",
                    policy_hash=digest,
                    now=now,
                )
            elif category == RATE_LIMITED:
                mark_route(
                    route,
                    STATUS_RATE_LIMITED,
                    reason=f"{category}: {str(exc)[:200]}",
                    policy_hash=digest,
                    now=now,
                )
            reasons.append(
                {
                    "route_index": index,
                    "route": route_key(route),
                    "event": "ERROR",
                    "reason": f"{category}: {str(exc)[:200]}",
                }
            )
            allowed = attempts_allowed.get(category, 1)
            if attempt < allowed:
                sleep(min(2**attempt, 5))
                continue
            return None, None, category, attempt
        latency_ms = int((time.monotonic() - started) * 1000)
        if not (text or "").strip():
            allowed = attempts_allowed[EMPTY_OUTPUT]
            if attempt < allowed:
                sleep(1)
                continue
            return None, None, EMPTY_OUTPUT, attempt
        meta = dict(meta or {})
        inp, out = _tokens_from_meta(meta)
        if meta.get("provider") == "openrouter":
            inp = int(meta.get("input_tokens") or inp or 0)
            out = int(meta.get("output_tokens") or out or 0)
        meta.update(
            {
                "provider": provider,
                "model": route.get("model"),
                "route_index": index,
                "latency_ms": latency_ms,
                "input_tokens": inp,
                "output_tokens": out,
                "fallbacks": fallbacks,
            }
        )
        meta["cost_usd"] = model_usage.estimate_cost(
            route.get("model"), inp, out, reported=meta.get("cost_usd")
        )
        return text, meta, "", attempt


def status_report(*, policy=None, now=None) -> dict:
    """Per-role + per-route status for the operator page and `models status`."""
    policy = policy or model_policy.load_policy()
    digest = model_policy.policy_hash(policy)
    paid_cost = model_usage.paid_cost_today()
    soft_paid_budget = float(policy["global"].get("soft_paid_budget_usd_day") or 0.0)
    return {
        "day": model_usage.sofia_day(now),
        "policy_hash": digest,
        "paid_enabled": bool(policy["global"].get("paid_enabled")),
        "soft_paid_budget_usd_day": soft_paid_budget,
        "paid_cost_today_usd": paid_cost,
        # PART C: a SOFT, non-blocking warning — routing continues because the
        # paid gate itself is the operator's explicit `paid_enabled` switch.
        "paid_soft_exceeded": bool(soft_paid_budget) and paid_cost >= soft_paid_budget,
        "roles": [plan_routes(role, policy=policy, now=now) for role in model_policy.ROLES],
        "usage": model_usage.daily_summary(),
        "health": read_health(),
    }
