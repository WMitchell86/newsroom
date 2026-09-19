"""Thin TypeSafe Jev adapter (M3J - shadow evaluation only).

Jev returns *typed* semantic decisions (a choice from a fixed set, a yes/no
probability, a score) instead of generated text. In this project it is used
ONLY as a shadow judge over public-source material:

    LLM            -> propose / extract / write
    Jev            -> narrow typed semantic judgements  (this module)
    deterministic  -> enforce policy and safety
    editor         -> final authority

This adapter has deliberately NO editorial authority: it never decides
newsworthiness, readiness, factual validity, angle status or publication, and
nothing outside `scripts/evals/jev_shadow_eval.py` should call it. It only
builds typed questions, submits them, and normalizes the response.

The official SDK is an *optional* dependency
(`pip install 'editor-assistant[jev]'`). A missing package or a missing
`TYPESAFE_API_KEY` yields an explicit `JEV_CAPABILITY_UNAVAILABLE`, leaving
normal project functionality untouched.

Environment:
    TYPESAFE_API_KEY   required for a live call
    JEV_MODEL          optional alias; defaults to ``jev-latest``
"""

from __future__ import annotations

import os
import time

JEV_CAPABILITY_UNAVAILABLE = "JEV_CAPABILITY_UNAVAILABLE"
JEV_PROVIDER_ERROR = "JEV_PROVIDER_ERROR"
JEV_OK = "JEV_OK"

TYPESAFE_API_KEY_ENV = "TYPESAFE_API_KEY"
JEV_MODEL_ENV = "JEV_MODEL"
DEFAULT_MODEL_ALIAS = "jev-latest"

#: Supported TypeSafe System One question primitives.
QUESTION_CHOICE = "choice"
QUESTION_NOUL = "noul"
QUESTION_SCORE = "score"
_QUESTION_KINDS = (QUESTION_CHOICE, QUESTION_NOUL, QUESTION_SCORE)


class JevError(ValueError):
    """Base class for explicit Jev adapter failures."""


class JevCapabilityUnavailable(JevError):
    """SDK or API key is missing; callers must degrade, never fabricate."""

    code = JEV_CAPABILITY_UNAVAILABLE


class JevProviderError(JevError):
    """Transport/provider failure (never carries the API key)."""

    code = JEV_PROVIDER_ERROR


def _redact(text, secret):
    text = str(text)
    if secret:
        text = text.replace(secret, "<redacted>")
    return text


def load_sdk():
    """Return the `typesafe_sdk` module, or None when it is not installed."""
    try:
        import typesafe_sdk
    except ImportError:
        return None
    return typesafe_sdk


def model_alias(env=None):
    environment = env if env is not None else os.environ
    return (environment.get(JEV_MODEL_ENV) or "").strip() or DEFAULT_MODEL_ALIAS


def capability_status(env=None, sdk=None):
    """(available, reason). `reason` is an explicit, inspectable string."""
    environment = env if env is not None else os.environ
    key = (environment.get(TYPESAFE_API_KEY_ENV) or "").strip()
    if sdk is None:
        sdk = load_sdk()
    if sdk is None:
        return False, "typesafe_sdk is not installed (pip install 'editor-assistant[jev]')"
    if not key:
        return False, f"{TYPESAFE_API_KEY_ENV} is not set"
    return True, ""


def question(kind, instructions, criteria=None):
    """Build a plain typed-question spec (translated to SDK objects on submit).

    * `choice`: `criteria` is the fixed set of allowed options;
    * `noul`: binary proposition; `criteria` must be omitted/None;
    * `score`: `criteria` is the ordered list of levels.
    """
    if kind not in _QUESTION_KINDS:
        raise JevError(f"unknown question kind: {kind!r}")
    if kind == QUESTION_NOUL:
        if criteria not in (None, ()):
            raise JevError("noul questions take no criteria")
        return {"kind": kind, "instructions": instructions}
    options = list(criteria or ())
    if kind == QUESTION_CHOICE and len(options) < 2:
        raise JevError("choice questions need at least two options")
    if kind == QUESTION_SCORE and len(options) < 2:
        raise JevError("score questions need at least two levels")
    return {"kind": kind, "instructions": instructions, "criteria": options}


def build_sdk_questions(specs, sdk):
    """Translate `{name: spec}` into the SDK's typed question objects."""
    built = {}
    for name, spec in specs.items():
        kind = spec["kind"]
        if kind == QUESTION_CHOICE:
            built[name] = sdk.Choice(
                instructions=spec["instructions"],
                criteria={option: None for option in spec["criteria"]},
            )
        elif kind == QUESTION_NOUL:
            built[name] = sdk.Noul(instructions=spec["instructions"])
        else:  # score
            built[name] = sdk.Score(
                instructions=spec["instructions"], criteria=list(spec["criteria"])
            )
    return built


def build_client(sdk=None, env=None):
    """Construct the SDK client when configured; None when not available."""
    environment = env if env is not None else os.environ
    available, _ = capability_status(env=environment, sdk=sdk)
    if not available:
        return None
    key = (environment.get(TYPESAFE_API_KEY_ENV) or "").strip()
    try:
        return sdk.TypeSafeClient(api_key=key)
    except TypeError:  # older/newer SDK without an explicit api_key kwarg
        return sdk.TypeSafeClient()


def _get(response, key, default=None):
    """Read a field from an SDK object or a plain mapping (tests use dicts)."""
    if isinstance(response, dict):
        return response.get(key, default)
    return getattr(response, key, default)


def _plain(value):
    """Convert an SDK value into plain JSON-serializable data (stdlib only).

    The official SDK returns msgspec structs (e.g. `Usage`); the eval runner
    persists results as JSON, so no non-stdlib object may leak into a record.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    fields = getattr(type(value), "__struct_fields__", None)
    if fields:
        return {name: _plain(getattr(value, name)) for name in fields}
    if hasattr(value, "_asdict"):  # namedtuple fallback
        return {k: _plain(v) for k, v in value._asdict().items()}
    return value if isinstance(value, (int, float)) else str(value)


def _normalize_primitive(kind, name, response):
    """One answer: selected value + full distribution + confidence where given."""
    if kind == QUESTION_CHOICE:
        collection = _get(response, "choices", {}) or {}
    elif kind == QUESTION_NOUL:
        collection = _get(response, "nouls", {}) or {}
    else:  # score
        collection = _get(response, "scores", {}) or {}
    answer = collection.get(name) if hasattr(collection, "get") else None
    normalized = {
        "type": kind,
        "answer": None,
        "probabilities": None,
        "confidence": None,
    }
    if answer is None:
        return normalized
    if kind == QUESTION_CHOICE:
        normalized["answer"] = _plain(_get(answer, "choice"))
    elif kind == QUESTION_NOUL:
        normalized["answer"] = _plain(_get(answer, "noul"))
    else:
        normalized["answer"] = _plain(_get(answer, "score"))
    probabilities = _get(answer, "probabilities")
    if probabilities is not None:
        normalized["probabilities"] = _plain(probabilities)
    confidence = _get(answer, "confidence")
    if confidence is not None:
        normalized["confidence"] = float(confidence)
    return normalized


def normalize_response(response, questions, *, model_requested, latency_ms):
    """Normalize an SDK response into a plain, storable record.

    Probabilities and confidence are preserved in full - the project does not
    (yet) apply any production threshold, and will not until it has enough
    independent human labels to calibrate one.
    """
    effective = _get(response, "model") or model_requested
    usage = _get(response, "usage")
    record = {
        "status": JEV_OK,
        "model_requested": model_requested,
        "model_effective": effective,
        "latency_ms": round(latency_ms),
        "usage": _plain(usage),
        "answers": {
            name: _normalize_primitive(spec["kind"], name, response)
            for name, spec in questions.items()
        },
    }
    return record


def evaluate(
    state,
    question_specs,
    *,
    model=None,
    env=None,
    client=None,
    sdk=None,
    clock=time.monotonic,
):
    """Submit `state` + typed questions; return a normalized record.

    Raises `JevCapabilityUnavailable` when the SDK/key is missing and
    `JevProviderError` on transport/provider failure. Never returns an
    editorial decision - callers own all interpretation.
    """
    environment = env if env is not None else os.environ
    if sdk is None:
        sdk = load_sdk()
    if client is None:
        client = build_client(sdk=sdk, env=environment)
    if client is None:
        _, reason = capability_status(env=environment, sdk=sdk)
        raise JevCapabilityUnavailable(f"{JEV_CAPABILITY_UNAVAILABLE}: {reason}")

    alias = model or model_alias(environment)
    built = build_sdk_questions(question_specs, sdk)
    kwargs = {"state": state, "questions": built}
    if alias:
        kwargs["model"] = alias
    started = clock()
    try:
        response = client.system_one(**kwargs)
    except JevError:
        raise
    except Exception as exc:  # provider/transport failure -> explicit category
        secret = (environment.get(TYPESAFE_API_KEY_ENV) or "").strip()
        raise JevProviderError(
            f"{JEV_PROVIDER_ERROR}: {_redact(type(exc).__name__, secret)}: {_redact(exc, secret)}"
        ) from exc
    return normalize_response(
        response,
        question_specs,
        model_requested=alias,
        latency_ms=(clock() - started) * 1000.0,
    )
