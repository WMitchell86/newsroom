"""One shared role router: ordered routes, true cross-provider fallback, budgets.

`call_role(role, prompt, ...)` walks the ordered route list of that role from the
policy store (`drafting/model_policy.py`) and:

```text
for route in role.routes:
    skip if disabled
    skip if paid and paid is not enabled
    skip if the project privacy gate is enabled and the route is public-only
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
QUOTA_EXHAUSTED   429 + explicit reset-window wording ("per day", "daily limit",
                                              "RPD", structured quota failure)
                                           -> route exhausted for the provider
                                              period, continue to the next route
QUOTA_AMBIGUOUS   429 whose body only says "quota" -> not provable as a daily
                                              exhaustion: short RATE_LIMITED
                                              health state, no long mark
RATE_LIMITED      429 transient / provider reset metadata -> bounded retry, then continue
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
#: V1.2-G4.5-hardening: the provider said "quota" without saying WHICH window.
#: `You exceeded your current quota` is the wording a per-minute throttle uses
#: just as often as a daily cap, so a 429 carrying only that wording must never
#: buy a route a mark that lasts until the next provider reset (measured
#: 2026-09-28: four working Draft routes were offline for ~14 h by that route).
#: It gets the short RATE_LIMITED health state instead, with no retry.
QUOTA_AMBIGUOUS = "QUOTA_AMBIGUOUS"
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
#: V1.2-G4.5. The measured per-MINUTE budget (RPM 5 for the draft Flash models)
#: is spent while the day is barely touched, and it recovers on its own within a
#: minute. So it is a skip with its own name and NO health mark: it must never
#: join `_UNHEALTHY_FOR_THE_PERIOD`, or a five-per-minute ceiling would take a
#: working route offline for the rest of the day - which is the exact failure
#: AGENTS.md rule 2 records, re-created one dimension down.
RPM_LIMIT_REACHED = "RPM_LIMIT_REACHED"
ROLE_HARD_BUDGET = "ROLE_HARD_BUDGET"
ROUTE_UNHEALTHY = "ROUTE_UNHEALTHY"

#: Categories that mean "this route is not usable for a while".
_UNHEALTHY_FOR_THE_PERIOD = {QUOTA_EXHAUSTED}
_UNHEALTHY_UNTIL_POLICY_CHANGES = {INVALID_MODEL, AUTH_FAILED, PAYMENT_REQUIRED}

#: Marker substrings that PROVE the refusal is a reset-window (daily) exhaustion.
#: A window must be stated in words: "per day", "daily limit", "RPD", or the
#: structured quota-failure status the provider returns. Anything that only says
#: "quota" is ambiguous and is handled separately (see `QUOTA_AMBIGUOUS`).
_DAILY_QUOTA_MARKERS = (
    "quotafailure",
    "quota_exceeded",
    "quota exceeded",
    "per day",
    "daily limit",
    "rpd",
)

#: Markers that say "quota" without naming the window, so they cannot support a
#: daily exhaustion.
#:
#: A correction, because this comment used to claim that this wording "took four
#: working routes offline for a day". That was an unverified causal story. What
#: was actually measured on 2026-09-28: four draft routes were marked EXHAUSTED
#: with `reason: "QUOTA_EXHAUSTED: HTTP Error 429: Too Many Requests"` until
#: 2026-09-29T07:00Z — and that reason string is a LOCAL category label
#: prepended by `reason=f"{category}: ..."`, not the provider's body, so nothing
#: in it shows which wording classified them. Three OpenRouter routes carried
#: the same mark and one of them answered a call immediately afterwards, so at
#: least some of those marks were simply wrong. The reasoning that stands is the
#: conservative one: a body that does not name a window cannot prove one, so it
#: gets the short mark and is re-checked, not a day-long disable.
_AMBIGUOUS_QUOTA_MARKERS = (
    "current quota",
    "quota",
)

#: Provider metadata that states its own short reset window. When the provider
#: itself says "retry in 12s", the router must not claim a longer outage - but
#: this is only allowed to override the AMBIGUOUS wording, never the explicit
#: daily wording above.
_RETRY_RESET_MARKERS = (
    "retrydelay",
    "retry-after",
    "retry_after",
    "retry in",
)

#: Provider wording that means "this model does not exist", as opposed to "this
#: request was malformed". Only a 400 carrying one of these is permanent.
_MODEL_MISSING_MARKERS = (
    "model not found",
    "models.notfound",
    "is not found for api version",
    "unknown model",
    "no such model",
    "does not exist",
)

#: V1.2-G4.5. A `_DAILY_QUOTA_CATEGORIES` set and a `_category_is_daily()` helper
#: used to live here, listing QUOTA_EXHAUSTED / MODEL_LIMIT_REACHED /
#: ROLE_HARD_BUDGET. Both are GONE: nothing ever called the helper, and the set
#: was worse than useless - it grouped a provider exhaustion together with two
#: LOCAL guardrails, so a reader could conclude that a locally-invented limit
#: takes a route offline for the day, which is the exact confusion AGENTS.md
#: rule 3 records. What actually decides a lasting mark is the two sets below,
#: and only QUOTA_EXHAUSTED is in the period one.


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


def role_has_usable_route(role, *, policy=None, now=None):
    """Tri-state: is `role` worth calling?

    `True`  — at least one route is eligible and not currently marked unusable.
    `False` — routes exist and every one of them is currently unusable.
    `None`  — **cannot judge**: the role has no configured routes, or no policy
               could be read.

    The third value exists because the first version answered "no" when it knew
    nothing, which made the newsroom refresh and the Draft preflight refuse
    every call in any environment without a full route table — 13 unit tests
    broke on it. "We have no routes to judge" is not "all your routes are
    dead", and conflating them is how a guardrail becomes an outage.

    V1.2-G4.6. This is the check the newsroom refresh was missing, and its
    absence is what made «Обнови» unusable rather than merely slow.

    The router already refuses to call an exhausted or rate-limited route — but
    it only finds out *by calling it*, and the refusal costs the per-minute wait
    first. With the story role's daily quota spent, a refresh walked 8 semantic
    calls × a 60-second deferral each, for a 429 it already had recorded, and
    the editor's Today list stayed 15 hours old for the whole eight minutes.

    Deciding before spending anything turns that from minutes into a boolean.
    A 429 is separate from a 503 on purpose: an exhausted quota does not clear
    in minutes, so there is nothing to retry and nothing to wait for.
    """
    if policy is None:
        try:
            policy = model_policy.load_policy()
        except Exception:  # noqa: BLE001 - an unreadable policy is "cannot judge"
            return None
    routes = ((policy.get("roles") or {}).get(role) or {}).get("routes") or []
    if not routes:
        return None
    state = read_health()
    moment = _utc_now(now)
    saw_candidate = False
    for route in routes:
        if not route.get("eligible"):
            continue
        if route.get("provider") != "gemini" and not (policy.get("global") or {}).get(
            "paid_enabled", True
        ):
            continue
        saw_candidate = True
        record = state.get(route_key(route))
        if not isinstance(record, dict):
            return True
        if record.get("status") == STATUS_EXHAUSTED:
            until = record.get("until") or ""
            if until and until > _iso(moment):
                continue
            # The window the provider gave us has passed: worth one try again.
            return True
        if record.get("status") == STATUS_RATE_LIMITED:
            until = record.get("until") or ""
            if until and until > _iso(moment):
                continue
            return True
        return True
    # Every route exists but none is a candidate we may call.
    return False if saw_candidate else None


def exhausted_routes_for(role, *, policy=None, now=None) -> list:
    """Which routes of `role` are currently marked unusable, with their reason.

    V1.2-G4.8. A refusal that says only "no route" sends the operator to the
    provider dashboard. Naming the routes and the reason they were skipped is
    the difference between a fact and a shrug.
    """
    if policy is None:
        policy = model_policy.load_policy()
    routes = ((policy.get("roles") or {}).get(role) or {}).get("routes") or []
    state = read_health()
    out = []
    for route in routes:
        record = state.get(route_key(route))
        if isinstance(record, dict) and record.get("status"):
            out.append({"route": route_key(route), "status": record.get("status"),
                        "until": record.get("until") or ""})
    return out


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
        # V1.2-G4.2 §12/§14: a removed model must not disable the product, and a
        # HEALTHY model must not be disabled either. The reliable "this model does
        # not exist" signal is 404 (and 422, a well-formed but unacceptable
        # request for that model). A bare **400 is not** that signal: Gemini
        # answers 400 for a malformed request — an unsupported generation
        # parameter, or an output budget smaller than its own thinking budget —
        # and a single such request was enough to mark the ONLY working Draft
        # route `INVALID_MODEL` until the policy changed. That made the primary
        # product action look permanently broken while the model answered fine.
        #
        # So: 404/422 stay permanent, and 400 is permanent only when the provider
        # actually says the model is unknown. Everything else is retryable.
        if code in (404, 422):
            return INVALID_MODEL
        if code == 400:
            lowered = str(body).lower()
            if any(marker in lowered for marker in _MODEL_MISSING_MARKERS):
                return INVALID_MODEL
            return TRANSIENT
        if code == 402:
            # The provider refuses for billing reasons (OpenRouter: no credits).
            # That is not a transient failure: retrying wastes time and never fixes it.
            return PAYMENT_REQUIRED
        if code in (401, 403):
            return AUTH_FAILED
        if code == 429:
            # V1.2-G4.5-hardening. Order matters and each step is a claim the
            # router is entitled to make:
            #   1. an explicit reset-window wording ("per day", "RPD") -> the
            #      route really is spent for the provider period;
            #   2. provider reset metadata ("retryDelay": "12s") -> a short
            #      throttle, health clears in minutes;
            #   3. only the word "quota" -> AMBIGUOUS: short health state, no
            #      long EXHAUSTED mark, because the router cannot observe which
            #      window the provider meant;
            #   4. anything else -> plain rate limiting.
            lowered = str(body).lower()
            if any(marker in lowered for marker in _DAILY_QUOTA_MARKERS):
                return QUOTA_EXHAUSTED
            if any(marker in lowered for marker in _RETRY_RESET_MARKERS):
                return RATE_LIMITED
            if any(marker in lowered for marker in _AMBIGUOUS_QUOTA_MARKERS):
                return QUOTA_AMBIGUOUS
            return RATE_LIMITED
        if 500 <= code < 600:
            return TRANSIENT
        return TRANSIENT
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return TRANSIENT
    return TRANSIENT


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
    if (
        policy["global"].get("privacy_gate_enabled")
        and route.get("public_only")
        and payload_class == "private"
    ):
        reasons.append("маршрутът е само за публични материали")
    limit = route.get("daily_call_limit")
    if limit and model_usage.model_calls_today(route.get("provider"), route.get("model")) >= int(
        limit
    ):
        reasons.append(f"дневен лимит на модела ({limit}) е достигнат")
    # V1.2-G4.5. The per-minute dimension, measured for this project: RPM 5 for
    # the draft Flash models. It is checked BEFORE the call rather than learned
    # from a 429, because that 429 costs a round trip and then marks the route's
    # health with a failure that was fully predictable. It is a skip, never a
    # long mark: a minute is a minute, and the route is healthy again after it.
    if route.get("provider") == "gemini":
        rpm = model_policy.GEMINI_RPM_LIMITS.get(route.get("model"))
        if rpm and model_usage.model_calls_last_minute(
            route.get("provider"), route.get("model"), now=now
        ) >= int(rpm):
            reasons.append(f"минутен лимит на модела ({rpm}) е достигнат")
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
    # V1.2-G4.16. Every route the router declined, with the actual reason. Kept
    # so the failure can NAME them instead of listing every cause it could
    # imagine. Nothing here is a guess: each entry is a predicate that fired.
    skipped: list[str] = []
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
            skipped.append(f"{route_key(route)}: {', '.join(reasons)}")
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

    # V1.2-G4.16. The editor used to be told "no accessible route (missing key,
    # limit, disabled paid models or policy)" — a guess listing four causes,
    # appended to a message that already carried the real one. When the router
    # never even reached a route it KNOWS why: every skip reason is already
    # computed above. Naming them is both shorter and true, and it is the
    # difference between an operator checking the right thing and guessing.
    if attempts:
        reason = "няма успешен маршрут"
    else:
        reason = "няма достъпен маршрут"
        if skipped:
            reason += f" ({'; '.join(skipped)})"
    raise RoleUnavailable(
        role, reason, on_exhausted=role_raw["on_exhausted"], trace=trace
    )


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
        # The minute marker is checked BEFORE the daily one. Both substrings end
        # in "лимит на модела" but neither contains the other, so the order is
        # not load-bearing today - it is pinned so that adding a second
        # substring relationship later cannot silently reclassify this.
        ("минутен лимит на модела", RPM_LIMIT_REACHED),
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
            elif category == RATE_LIMITED or category == QUOTA_AMBIGUOUS:
                # Both mean "try again shortly": RATE_LIMITED is a plain 429,
                # QUOTA_AMBIGUOUS is a quota-worded 429 whose window the router
                # cannot prove. Neither may mark the route for the whole
                # provider period (that is what QUOTA_EXHAUSTED is for).
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
        "privacy_gate_enabled": bool(policy["global"].get("privacy_gate_enabled")),
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
