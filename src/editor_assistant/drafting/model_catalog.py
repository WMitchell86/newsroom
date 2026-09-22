"""Live provider catalogs: does the configured model id still exist?

`newsroom models validate` uses this module. It performs exactly two read-only
GETs — the Gemini `models.list` and the OpenRouter `/models` catalog — and never
sends article text, prompts, drafts or notes. Validating an id must cost nothing
editorial.

This is the check that would have caught the invalid default OpenRouter id
(`google/gemma-4-31b`, where the real catalog id is `google/gemma-4-31b-it`), and
it reports the free/paid classification the catalog actually shows instead of
trusting a comment in the source.

Both catalogs are dynamic. A model can disappear, change price, or change its
free tier without any change in this repository — so a route that validated last
week may be invalid today, and `validate` is designed to be re-run.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from editor_assistant.drafting import model_policy

GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

STATUS_OK = "OK"
STATUS_INVALID = "INVALID"
STATUS_MISMATCH = "MISMATCH"
STATUS_UNCHECKED = "UNCHECKED"


def _as_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _get_json(url, *, headers=None, timeout=20):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_gemini_models(api_key, *, timeout=20):
    """Text-out Gemini model ids (`generateContent`) for the account's key."""
    # M4F F6: key travels as a header, never in the URL.
    payload = _get_json(GEMINI_MODELS_URL, headers={"x-goog-api-key": api_key}, timeout=timeout)
    names = []
    for model in payload.get("models") or []:
        methods = model.get("supportedGenerationMethods") or []
        if "generateContent" in methods:
            names.append(str(model.get("name") or "").split("/")[-1])
    return sorted(n for n in names if n)


def fetch_openrouter_catalog(*, api_key=None, timeout=20):
    """`{model_id: {"free": bool, "prompt": $/tok, "completion": $/tok, "context": N}}`."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    payload = _get_json(OPENROUTER_MODELS_URL, headers=headers, timeout=timeout)
    catalog = {}
    for model in payload.get("data") or []:
        model_id = str(model.get("id") or "")
        if not model_id:
            continue
        pricing = model.get("pricing") or {}
        prompt = _as_float(pricing.get("prompt"))
        completion = _as_float(pricing.get("completion"))
        catalog[model_id] = {
            "free": prompt == 0 and completion == 0,
            "prompt": prompt,
            "completion": completion,
            "context": model.get("context_length"),
        }
    return catalog


def validate_policy_models(
    policy=None, *, gemini_key=None, openrouter_key=None, timeout=20, catalog=None
):
    """Check every configured route against the live catalogs.

    Returns a report dict; each row carries `status` plus a human-readable
    `detail`. No row ever fails the run for a *missing provider key* — that is
    reported as UNCHECKED, not as an invalid model.
    """
    policy = policy or model_policy.load_policy()
    gemini_key = gemini_key if gemini_key is not None else os.environ.get("GEMINI_API_KEY", "")
    openrouter_key = (
        openrouter_key if openrouter_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
    )
    report = {
        "gemini_catalog": None,
        "openrouter_catalog": None,
        "gemini_error": "",
        "openrouter_error": "",
        "rows": [],
    }

    gemini_models = None
    if gemini_key:
        try:
            gemini_models = fetch_gemini_models(gemini_key, timeout=timeout)
            report["gemini_catalog"] = len(gemini_models)
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            report["gemini_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    else:
        report["gemini_error"] = "липсва GEMINI_API_KEY (проверката е пропусната)"

    openrouter = catalog
    if openrouter is None:
        try:
            openrouter = fetch_openrouter_catalog(api_key=openrouter_key or None, timeout=timeout)
            report["openrouter_catalog"] = len(openrouter)
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            openrouter = None
            report["openrouter_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    for role in model_policy.ROLES:
        role_raw = policy["roles"][role]
        for index, route in enumerate(role_raw["routes"]):
            row = {
                "role": role,
                "index": index,
                "provider": route["provider"],
                "model": route["model"],
                "billing": route.get("billing"),
                "public_only": bool(route.get("public_only")),
                "enabled": bool(route.get("enabled", True)),
                "status": STATUS_UNCHECKED,
                "detail": "",
            }
            if route["provider"] == "gemini":
                if gemini_models is None:
                    row["detail"] = report["gemini_error"] or "каталогът не е проверен"
                elif route["model"] in gemini_models:
                    row["status"] = STATUS_OK
                    row["detail"] = "наличен в Gemini models.list (generateContent)"
                else:
                    row["status"] = STATUS_INVALID
                    row["detail"] = "моделът липсва в текущия Gemini каталог"
            else:
                if openrouter is None:
                    row["detail"] = report["openrouter_error"] or "каталогът не е проверен"
                elif route["model"] not in openrouter:
                    row["status"] = STATUS_INVALID
                    row["detail"] = "моделът липсва в текущия OpenRouter каталог"
                else:
                    observed = openrouter[route["model"]]
                    row["observed_free"] = observed["free"]
                    row["observed_price_usd_per_mtok"] = [
                        round(observed["prompt"] * 1_000_000, 4),
                        round(observed["completion"] * 1_000_000, 4),
                    ]
                    declared_free = route.get("billing") in ("free", "operator_declared")
                    if declared_free and not observed["free"]:
                        row["status"] = STATUS_MISMATCH
                        row["detail"] = (
                            "конфигуриран като безплатен, но каталогът показва цена "
                            f"{row['observed_price_usd_per_mtok']} USD / 1M токена"
                        )
                    else:
                        row["status"] = STATUS_OK
                        row["detail"] = (
                            "безплатен endpoint" if observed["free"] else "платен модел (потвърден)"
                        )
            report["rows"].append(row)

    # An explicit revalidation clears a route previously marked INVALID/AUTH.
    from editor_assistant.drafting import model_router

    for row in report["rows"]:
        if row["status"] in (STATUS_OK, STATUS_MISMATCH):
            model_router.clear_route({"provider": row["provider"], "model": row["model"]})

    report["invalid"] = [r for r in report["rows"] if r["status"] == STATUS_INVALID]
    report["mismatches"] = [r for r in report["rows"] if r["status"] == STATUS_MISMATCH]
    report["unchecked"] = [r for r in report["rows"] if r["status"] == STATUS_UNCHECKED]
    return report


def render_validation(report) -> str:
    lines = ["Проверка на моделите в политиката (живи каталози, без изпращане на текст):"]
    gemini_seen = (
        f"{report['gemini_catalog']} модела"
        if report.get("gemini_catalog") is not None
        else f"не е проверен — {report.get('gemini_error') or 'няма ключ'}"
    )
    openrouter_seen = (
        f"{report['openrouter_catalog']} модела"
        if report.get("openrouter_catalog") is not None
        else f"не е проверен — {report.get('openrouter_error') or 'няма връзка'}"
    )
    lines.append(f"  Gemini каталог: {gemini_seen}")
    lines.append(f"  OpenRouter каталог: {openrouter_seen}")
    for row in report["rows"]:
        marker = {
            STATUS_OK: "OK",
            STATUS_INVALID: "НЕВАЛИДЕН",
            STATUS_MISMATCH: "НЕСЪОТВЕТСТВИЕ",
            STATUS_UNCHECKED: "НЕПРОВЕРЕН",
        }.get(row["status"], row["status"])
        lines.append(
            f"  [{marker}] {row['role']}#{row['index']} {row['provider']}:{row['model']}"
            + (f" — {row['detail']}" if row["detail"] else "")
        )
    if report["invalid"]:
        lines.append(f"НЕВАЛИДНИ МОДЕЛИ: {len(report['invalid'])} — поправете политиката.")
    if report["mismatches"]:
        lines.append(
            f"НЕСЪОТВЕТСТВИЯ безплатен/платен: {len(report['mismatches'])} — прегледайте ги."
        )
    if not report["invalid"] and not report["mismatches"]:
        lines.append("Всички проверени модели са налични в текущите каталози.")
    lines.append(
        "Каталозите и квотите се променят: пускайте тази проверка преди да разчитате на модел."
    )
    return "\n".join(lines)
