"""M2.3 generation + lineage + audit helpers - stdlib only (urllib for providers)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

MODEL_ID = "gemini-3.5-flash"
MODEL_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL_ID + ":generateContent"
)
GENERATION_SETTINGS = {"temperature": 0.4, "max_tokens": 8192}
# Gemini 3.x spends output budget on internal "thinking" before emitting text.
# For structured JSON drafting that starved the answer (measured: 1921 thinking
# tokens vs 75 output tokens -> truncated JSON that could not parse). Disable
# thinking by default; set GEMINI_THINKING_BUDGET=-1 to hand control back.
THINKING_BUDGET = int(os.environ.get("GEMINI_THINKING_BUDGET", "0"))
API_PROVIDER = "gemini"  # current active provider for model + endpoint + key
API_KEY_ENV = "GEMINI_API_KEY"
API_KEY_FALLBACK_ENV = "OPENROUTER_API_KEY"

# Give the operator the same knob in one place without editing code, plus the
# per-role Gemini model order and the OpenRouter model selection. OpenAI
# model ids with a `openai/` prefix (e.g. openai/gpt-oss-20b) are resolved
# through OpenRouter's model catalog, not the OpenAI API endpoint.


def _trim_for_model(prompt_text, *, hard_cap_chars=30000):
    """Keep every prompt section intact and only shorten the STYLE_EXAMPLES body
    when the prompt exceeds the cap.

    TASK/FORBIDDEN carry the JSON output contract and MUST survive any trimming;
    the previous version cut the tail after STYLE_EXAMPLES and silently deleted
    them, which made the model answer in prose instead of parseable JSON.
    The default cap is high enough that a normal ~11k-char draft prompt is sent
    unmodified; the trimmer is only a safety valve against pathological input.
    """
    if len(prompt_text) <= hard_cap_chars:
        return prompt_text
    marker = "===== STYLE_EXAMPLES ====="
    head, sep, tail = prompt_text.partition(marker)
    if not sep:
        return prompt_text
    nxt = tail.find("===== ")
    examples_body, rest = (tail, "") if nxt < 0 else (tail[:nxt], tail[nxt:])
    room = hard_cap_chars - len(head) - len(sep) - len(rest) - 200
    room = max(room, 600)
    if len(examples_body) > room:
        examples_body = examples_body[:room] + "\n\n[... style examples shortened ...]\n"
    return head + sep + examples_body + rest


# Fallback chain for M2.3/M2.3B generation:
#   primary  : GEMINI_API_KEY -> gemini-3.5-flash (Gemini provider)
#   fallback : OPENROUTER_API_KEY -> OpenAI-compatible model (OpenRouter provider)
#   free     : if neither key present and the task permits, a free OpenRouter model
#
# Gemini quota (AI Studio + Gemini API share the same quota; snapshot 2026-09-19,
# format `used / limit` per cell).  The 3.x Flash family (draft pool) is RPD-exhausted
# — all four showed 22/20 RPD in the snapshot — which is the direct cause of the 429s
# in the M3D corpus (17 runs classified DISCOVERY_DEGRADED, never editorial zero).
# TPM is never the bottleneck (250K allocated per model, 5-14K used for Flash, 25-67K
# for Lite).  When a model 429s it is added to _GEMINI_EXHAUSTED and skipped by
# _gemini_pool; if the whole pool is exhausted the batch degrades rather than
# fabricating.  The ONLY fresh Gemini text-out quota in the same snapshot is Gemini
# 2.5 Flash (0/20 RPD, 0/5 RPM) and Gemini 2.5 Flash Lite (0/20 RPD, 0/10 RPM) —
# one generation older than 3.x, added below as last-resort fallbacks.  Models with
# 0/0 allocation (Gemini 2 Flash, Gemini 2 Flash Lite) are not usable.  Full
# row-by-row table + pacing notes are in CURRENT_STATE.md.
#
# Model swap is via MODEL_ID + MODEL_ENDPOINT + API_PROVIDER + API_KEY_ENV; no other
# code path (lineage, audit, prompt, retrieval) depends on the provider identity.


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


_GEMINI_LAST_CALL = [0.0]
_GEMINI_EXHAUSTED = set()  # models that returned a daily-quota 429 (this process)

# Free-tier Gemini meters each model separately. Quota snapshot from the Gemini AI
# Studio quota page (2026-09-19, format `used/limit`, AI Studio + Gemini API share the
# same quota).  Columns: RPM / TPM / RPD.  The 3.x Flash family is RPD-exhausted — all
# four showed 22/20 RPD — which is the direct cause of the 429s in the M3D corpus.
# The ONLY fresh Gemini text-out quota in that snapshot is Gemini 3 Flash (10/20 RPD,
# 2/5 RPM), Gemini 2.5 Flash (0/20 RPD, 0/5 RPM) and Gemini 2.5 Flash Lite (0/20 RPD,
# 0/10 RPM).  Gemini 2 Flash / 2 Flash Lite show 0/0 allocation and are unusable.
#   gemini-3.5-flash         3 / 5 RPM   11.07K / 250K TPM   22 / 20 RPD  (EXHAUSTED)
#   gemini-3.6-flash         5 / 5 RPM   5.41K / 250K TPM    22 / 20 RPD  (EXHAUSTED)
#   gemini-3.7-flash         4 / 5 RPM   12.49K / 250K TPM   22 / 20 RPD  (EXHAUSTED)
#   gemini-3.8-flash         3 / 5 RPM   13.63K / 250K TPM   22 / 20 RPD  (EXHAUSTED)
#   gemini-3-flash-preview   (in 3.x family; RPD status not separately listed — treat as
#                             likely shared/exhausted with 3.x family)
#   gemini-3-flash           2 / 5 RPM   9.09K / 250K TPM    10 / 20 RPD  (HALF USED — fallback)
#   gemini-2.5-flash         0 / 5 RPM   0 / 250K TPM       0 / 20 RPD   (FRESH — fallback)
#   gemini-2.5-flash-lite    0 / 10 RPM  0 / 250K TPM       0 / 20 RPD   (FRESH — fallback, judge only)
#   gemini-3.1-flash-lite    20 / 15 RPM 67.33K / 250K TPM  503 / 500 RPD (EXHAUSTED — judge pool)
#   gemini-3.5-flash-lite    15 / 15 RPM 25.28K / 250K TPM  288 / 500 RPD (NEARLY EXHAUSTED — was dropped
#                             from judge pool: rejects generationConfig.thinkingConfig)
#   Models with 0/0 allocation (Gemini 2 Flash, Gemini 2 Flash Lite, Gemini 2.5 Pro,
#   Gemini 3.1 Pro, Gemini 2.5 Flash TTS, etc.): not usable — no quota allocated.
#   NOTE on -preview/-latest suffixes: the Gemini API models.list was not reachable without
#   a valid key (403), so the exact endpoint model ids for "Gemini 3.1 Flash Lite Preview"
#   and "Gemini Flash Lite Latest" could not be verified here. The base-model id pattern is
#   `gemini-3.1-flash-lite`; -preview/-latest are appended the same way (e.g.
#   `gemini-3.1-flash-lite-preview`). Whether those suffixes share the same RPD bucket as
#   the base model or have their own is not confirmed from this snapshot — if they share it
#   they are also exhausted (503/500) and 2.5 Flash Lite is the only fresh judge option.
#   A live key should confirm the exact ids + bucket split before relying on the preview/latest
#   judge entries.  The 2.5 Flash / 2.5 Flash Lite ids follow the same convention and are the
#   same generation naming used elsewhere in the Gemini API, but are likewise UNVERIFIED here
#   (no live key) and should be confirmed with one test call before depending on them.
DRAFT_MODEL_POOL = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_DRAFT_MODELS",
        "gemini-2.5-flash,gemini-3-flash,gemini-3.5-flash,gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-3-flash-preview",
    ).split(",")
    if m.strip()
]
JUDGE_MODEL_POOL = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_JUDGE_MODELS",
        "gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-3.1-flash-lite-preview,gemini-flash-lite-latest",
    ).split(",")
    if m.strip()
]
# NOTE: gemini-3.5-flash-lite was dropped from the judge pool: it rejects
# generationConfig.thinkingConfig with 400 INVALID_ARGUMENT, which burned a
# wasted request on every judge call before rotation rescued it.
# RPM note (from the 2026-09-19 AI Studio quota snapshot): the only fresh
# Gemini text-out buckets are gemini-2.5-flash (0/20 RPD, 0/5 RPM),
# gemini-2.5-flash-lite (0/20 RPD, 0/10 RPM) and gemini-3-flash (10/20 RPD,
# 2/5 RPM) — added to the pools below as fallbacks after the exhausted 3.x family.
# gemini-3-flash is one generation older than 3.x and half-used on RPD, so it is
# placed after 2.5 Flash (fresh).  2.5 Flash / 3 Flash are 5 RPM each — with the
# default 5s pacing that is 12 calls/min, slightly above 5 RPM, so under a heavy
# batch you may see self-inflicted 429s on those two and should bump
# GEMINI_MIN_GAP_SECONDS toward 12 if that shows up.  2.5 Flash Lite (10 RPM) is
# fine at the 5s default for the judge pool.  Lite pools are kept judge-only
# (factual entailment / semantic gate), never drafting.
if MODEL_ID not in DRAFT_MODEL_POOL:
    DRAFT_MODEL_POOL.insert(0, MODEL_ID)


#: M4C story relation (semantic event comparison). This is NOT mechanical
#: entailment, so it must never default to the weak Lite `judge` pool (the M3D
#: lesson). Safe default: reuse the normal/full-capability draft pool. Set
#: `GEMINI_STORY_MODELS` to give the story role its own ordered pool.
STORY_MODEL_POOL = [
    m.strip() for m in os.environ.get("GEMINI_STORY_MODELS", "").split(",") if m.strip()
] or list(DRAFT_MODEL_POOL)


def _gemini_pool(role="draft"):
    """Ordered model list for a role, skipping buckets already known exhausted."""
    if role == "judge":
        pool = JUDGE_MODEL_POOL
    elif role == "story":
        pool = STORY_MODEL_POOL
    else:
        pool = DRAFT_MODEL_POOL
    fresh = [m for m in pool if m not in _GEMINI_EXHAUSTED]
    return fresh or list(pool)  # all known-exhausted -> retry anyway (may have reset)


def _gemini_pace(min_gap_seconds=5.0):
    """Throttle Gemini calls process-wide to respect per-minute rate limits.

    The Lite buckets allow 15 RPM, so a >=5s gap keeps a whole 15-draft batch
    under the per-minute ceiling and avoids self-inflicted 429s.
    """
    import time as _time

    gap = float(os.environ.get("GEMINI_MIN_GAP_SECONDS", min_gap_seconds))
    elapsed = _time.time() - _GEMINI_LAST_CALL[0]
    if elapsed < gap:
        _time.sleep(gap - elapsed)
    _GEMINI_LAST_CALL[0] = _time.time()


def draft_id_for(evidence_id, voice, mode, prompt_version, attempt=0):
    seed = f"m23:{evidence_id}:{voice}:{mode}:{prompt_version}:{attempt}"
    return "d" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:11]


def _http_body(exc):
    """Best-effort read of an HTTP error body (used only for quota diagnostics)."""
    try:
        return exc.read().decode("utf-8", errors="replace")
    except (OSError, ValueError, AttributeError):
        return ""


def _call_gemini(prompt_text, *, api_key, timeout, min_gap=5, max_attempts=4, role="draft"):
    prompt_text = _trim_for_model(prompt_text)
    trimmed_len = len(prompt_text)
    gen_cfg = {
        "temperature": GENERATION_SETTINGS["temperature"],
        "maxOutputTokens": GENERATION_SETTINGS["max_tokens"],
    }
    if THINKING_BUDGET >= 0:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": THINKING_BUDGET}
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": gen_cfg,
        }
    ).encode("utf-8")
    last_err = None
    for model in _gemini_pool(role):
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + model
            + ":generateContent?key="
            + api_key
        )
        for attempt in range(1, max_attempts + 1):
            _gemini_pace(min_gap)
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                cand = (data.get("candidates") or [{}])[0]
                parts = (cand.get("content") or {}).get("parts") or []
                # Never let internal reasoning leak into the draft: skip thought parts.
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                usage = data.get("usageMetadata") or {}
                return text, {
                    "model": model,
                    "usage": usage,
                    "provider": "gemini",
                    "role": role,
                    "prompt_chars": trimmed_len,
                    "finish_reason": cand.get("finishReason"),
                }
            except urllib.error.HTTPError as exc:
                last_err = exc
                body = _http_body(exc)
                # Daily buckets reset at midnight PT and report "exceeded your
                # current quota" / QuotaFailure. RPM/IP-pressure 429s instead say
                # "rate limit" / RESOURCE_EXHAUSTED and MUST be retried, not
                # treated as a dead bucket -- otherwise the whole pool is
                # discarded and the batch crashes.
                daily = (
                    "current quota" in body.lower()
                    or "quotafailure" in body.lower()
                    or "per day" in body.lower()
                )
                if exc.code == 429 and daily:
                    _GEMINI_EXHAUSTED.add(model)
                    break
                wait = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = float(wait) if wait else min_gap * attempt * 2
                except (TypeError, ValueError):
                    wait = min_gap * attempt * 2
                if exc.code in (429, 500, 503) and attempt < max_attempts:
                    import time as _time

                    _time.sleep(max(wait, min_gap))
                    continue
                break  # overloaded / non-retryable: move to the next model in the pool
    raise last_err


def _openrouter_nonstream_text(body_text):
    """Content of a NON-streaming chat-completion body ("" when absent/malformed).

    Used only as a fallback when the streaming parse yielded nothing.
    """
    try:
        data = json.loads(body_text)
    except ValueError:
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content") or ""


def _call_openrouter(prompt_text, *, api_key, timeout, model):
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": GENERATION_SETTINGS["temperature"],
            "max_tokens": GENERATION_SETTINGS["max_tokens"],
            # The parser below reads OpenAI-style SSE frames (`data: {...}`), so
            # streaming MUST be requested explicitly.  Without it OpenRouter
            # answers with ONE json object, no line starts with `data:`, and the
            # caller silently receives an empty completion.
            "stream": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    chunks = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload_text = line[5:].strip()
        if payload_text == "[DONE]":
            break
        try:
            data = json.loads(payload_text)
        except ValueError:
            continue
        choices = data.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta", {}) or {}
        if delta.get("content"):
            chunks.append(delta["content"])
    text = "".join(chunks)
    if not text.strip():
        # Defensive: a provider that ignores/refuses `stream` returns a single
        # JSON completion.  Parse that rather than report an empty generation.
        text = _openrouter_nonstream_text(body)
    return text, {"model": model, "usage": {}, "provider": "openrouter"}


# Paid OpenRouter models that are explicitly forbidden during the test phase.
# Update this set if new paid models are approved for use (e.g. once the test
# phase is passed and a higher-quality paid model is to be used).  The check in
# call_model runs before any network call, so a forbidden model never consumes
# quota and never reaches the provider.
_OPENROUTER_PAID_FORBIDDEN = frozenset(
    {
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    }
)


def _check_openrouter_model_not_paid(model_id):
    """Raise if model_id is a paid OpenRouter model (forbidden during test phase)."""
    if model_id in _OPENROUTER_PAID_FORBIDDEN:
        raise RuntimeError(
            f"OpenRouter model {model_id!r} is a paid model and is explicitly "
            f"forbidden during the test phase. Use a free model instead — see "
            f"OPENROUTER_MODEL in .env.example for the currently available free models."
        )


def call_model(
    prompt_text,
    *,
    api_key=None,
    timeout=240,
    model=None,
    prefer_free_openrouter=False,
    role="draft",
):
    """Generate with the configured provider, falling back across providers.

    role="draft" -> DRAFT_MODEL_POOL (full Flash, quality-critical drafting)
    role="judge" -> JUDGE_MODEL_POOL (Lite, 500/day, mechanical entailment checks)
    role="story" -> STORY_MODEL_POOL (M4C semantic relation; defaults to the draft
                    pool, never the weak judge pool — `GEMINI_STORY_MODELS`
                    / `OPENROUTER_STORY_MODEL` override it; paid guard applies)
    Within a role the pool is walked in order and exhausted buckets are skipped.

    Resolution order:
    1. Explicit api_key -> configured primary provider (Gemini), given role.
    2. GEMINI_API_KEY present -> Gemini, given role.
    3. OPENROUTER_API_KEY present -> OpenAI-compatible fallback model.
       BEFORE the call, the chosen model is checked against the forbidden paid
       models list (_OPENROUTER_PAID_FORBIDDEN).  If it is a paid model, a
       RuntimeError is raised and no network call is made.  During the test phase
       only FREE OpenRouter models are allowed; paid models (openai/gpt-oss-20b,
       openai/gpt-oss-120b, and any future paid model added to the forbidden set)
       are rejected at call time.
    4. Otherwise: RuntimeError.
    """
    key = api_key or ""
    if key:
        return _call_gemini(prompt_text, api_key=key, timeout=timeout, role=role)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        return _call_gemini(prompt_text, api_key=gemini_key, timeout=timeout, role=role)

    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        use = model or OPENROUTER_FALLBACK_MODEL
        free = os.environ.get("OPENROUTER_FREE_MODEL")
        if prefer_free_openrouter or (not os.environ.get("OPENROUTER_MODEL") and not model):
            use = free or use
        if role == "story" and not model:
            # M4C's own OpenRouter arm; still never a paid model by accident
            # (the guard below raises before any network call).
            use = os.environ.get("OPENROUTER_STORY_MODEL") or use
        _check_openrouter_model_not_paid(use)
        return _call_openrouter(prompt_text, api_key=or_key, timeout=timeout, model=use)

    raise RuntimeError("No API key available (GEMINI_API_KEY or OPENROUTER_API_KEY)")


OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b")
# OpenRouter model catalog (current snapshot).  During the test phase ONLY FREE
# models are allowed — paid models are explicitly forbidden at call time by
# _check_openrouter_model_not_paid() (see _OPENROUTER_PAID_FORBIDDEN).
#
# FREE models from the current OpenRouter free-model list that are suitable for
# Bulgarian text drafting (general-purpose text, large context, $0/M input+output):
#   google/gemma-4-31b              262K ctx  $0/M  (DEFAULT — dense 30.7B, 140+ langs,
#                                             document understanding, coding, reasoning)
#   qwen/qwen3.8-27b:free           262K ctx  $0/M  (dense 27B, general, multilingual,
#                                             coding, research — confirmed free tier)
#   nvidia/nemotron-3-super:free     262K ctx  $0/M  (120B hybrid MoE, 12B active —
#                                             very capable but more agentic/coding-oriented)
#   google/gemma-4-26b-a4b:free      262K ctx  $0/M  (MoE 25.2B total / 3.8B active —
#                                             usable but smaller active params than 31B)
#   thinkingmachines/inkling-small:free 1.05M ctx $0/M  (12B active MoE / 276B total —
#                                             general reasoning, coding, RAG, multilingual convo)
#   z-ai/glm-5.2:free                1M ctx    $0/M  (reasoning/coding/agentic focus —
#                                             context is large but drafting is not primary use case)
#
#   FREE models from the same list that are NOT suitable for BG text drafting
#   (specialized / too small context / guardrail / coding-only / knowledge-heavy):
#     inclusionai/ling-3.0-flash-sante:free   262K ctx  $0/M  (medical focus)
#     nvidia/nemotron-3.5-content-safety:free 128K ctx  $0/M  (guardrail/moderation)
#     cohere/north-mini-code:free            256K ctx  $0/M  (coding agent model)
#     nex-agi/nex-n2.5-mini:free             262K ctx  $0/M  (agentic coding model)
#     poolside/laguna-xs-2.1:free            262K ctx  $0/M  (coding agent model)
#     nvidia/nemotron-3-nano-omni:free       256K ctx  $0/M  (multimodal perception)
#     liquid/lfm-2.5-2.6b:free               66K ctx  $0/M  (small — explicitly "not for
#                                             knowledge-heavy tasks")
#
#   Model ID verification note: free-tier models that have a paid tier use the
#   `:free` suffix (e.g. qwen/qwen3.8-27b:free = free tier of qwen/qwen3.8-27b).
#   Models that are always free (no paid tier) use the plain id (e.g. google/gemma-4-31b
#   if no paid tier exists).  VERIFY the exact id in your OpenRouter account before
#   relying on it — especially for Gemma 4 models, which may be google/gemma-4-31b,
#   google/gemma-4-31b:free, or google/gemma-4-31b-instruct depending on whether a
#   paid tier exists.  The `:free` suffix may or may not be needed.
#
#   Paid models that are explicitly forbidden during the test phase (see
#   _OPENROUTER_PAID_FORBIDDEN in call_model — a RuntimeError is raised BEFORE any
#   network call, so a forbidden model never consumes quota):
#     openai/gpt-oss-20b              (the previous default — now forbidden)
#     openai/gpt-oss-120b             (more capable, ~5x cost — now forbidden)
#     openai/gpt-luna-5.6             (referenced as a future paid alternative for drafts —
#                                      add the exact id here once known; forbidden during test phase)
#
#   Set OPENROUTER_MODEL to a FREE model above (or any other FREE OpenRouter id) to
#   override the drafting default; set OPENROUTER_FREE_MODEL to override the
#   free-tier default.  Jev is untouched by these knobs (see workflow/jev.py).
OPENROUTER_FALLBACK_MODEL = OPENROUTER_MODEL
OPENROUTER_FREE_MODEL = os.environ.get(
    "OPENROUTER_FREE_MODEL",
    "qwen/qwen3.8-27b:free",
)


def _balanced_objects(text):
    """Yield each top-level {...} object in text with balanced braces (string-aware),
    robust to leading prose / trailing junk / stray objects."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text).strip()
        text = re.sub(r"\s*```\s*$", "", text).strip()
    start = text.find("{")
    if start < 0:
        return
    i = start
    while i < len(text):
        if text[i] == "{":
            depth = 0
            in_str = False
            esc = False
            end = -1
            for j in range(i, len(text)):
                ch = text[j]
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            if end < 0:
                return
            yield text[i : end + 1]
            i = end + 1
        else:
            i += 1


def _extract_first_object(text):
    """Parse the first valid top-level JSON object from messy model output."""
    for frag in _balanced_objects(text):
        try:
            return json.loads(frag)
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object in model output")


def _parse_draft_objs(raw):
    """Yield all top-level JSON objects in raw output (string-aware, balanced)."""
    for frag in _balanced_objects(raw):
        try:
            yield json.loads(frag)
        except json.JSONDecodeError:
            continue


def parse_draft_json(raw):
    """Find the draft JSON object carrying both headline and body, ignoring stray/leading
    objects. Robust to extra model output.
    Returns a draft dict that may optionally include a key 'draft_json' holding the
    matched raw object.
    """
    text = (raw or "").strip()
    for obj in _parse_draft_objs(text):
        if not isinstance(obj, dict):
            continue
        if obj.get("headline") and obj.get("body"):
            headlines = obj.get("headlines") or []
            headline = (obj.get("headline") or "").strip()
            body = (obj.get("body") or "").strip()
            out = {
                "headlines": [h for h in headlines[:3] if isinstance(h, str) and h.strip()][:3],
                "headline": headline,
                "body": body,
                "attention_notes": (obj.get("attention_notes") or "").strip(),
                "draft_json": obj,
            }
            return out
    raise ValueError("draft JSON missing headline/body")


def make_lineage(
    *,
    draft_id,
    evidence_id,
    voice_id,
    mode_id,
    style_example_ids,
    prompt_version,
    model=MODEL_ID,
    settings=None,
    generated_at=None,
    blind_group=None,
):
    lineage = {
        "draft_id": draft_id,
        "evidence_id": evidence_id,
        "site_dna_version": "CHERNOMORIE_SITE_DNA",
        "profile_version": "m2.2-freeze-1",
        "voice_id": voice_id,
        "mode_id": mode_id,
        "style_example_ids": list(style_example_ids),
        "prompt_version": prompt_version,
        "model": model,
        "generation_settings": settings or dict(GENERATION_SETTINGS),
        "generated_at": generated_at or _utc_now(),
    }
    if blind_group:
        lineage["blind_group"] = blind_group
    for key in (
        "draft_id",
        "evidence_id",
        "site_dna_version",
        "voice_id",
        "mode_id",
        "style_example_ids",
        "prompt_version",
        "model",
        "generation_settings",
        "generated_at",
    ):
        if lineage.get(key) in (None, "", []):
            raise ValueError(f"lineage missing {key}")
    if len(lineage["style_example_ids"]) != 3:
        raise ValueError("lineage needs exactly 3 style_example_ids")
    return lineage


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def audit_claims(draft_text, packet, style_texts=()):
    """Token-level audit: SUPPORTED / UNSUPPORTED / CONTRADICTED + leakage flag."""
    allowed = _norm(
        " ".join(
            [f["text"] for f in packet.get("facts", [])]
            + [q["text"] for q in packet.get("quotes", [])]
            + [packet.get("source_headline", "")]
            + list(packet.get("people", []))
            + list(packet.get("organizations", []))
            + list(packet.get("places", []))
            + list(packet.get("dates", []))
            + list(packet.get("numbers", []))
        )
    )
    allowed_tok = set(re.findall(r"[\w\-]+", allowed))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", draft_text or "") if s.strip()]
    digits = set(re.findall(r"\d[\d.,\s]*", packet.get("source_text", ""))) | set(
        re.findall(r"\d[\d.,\s]*", allowed)
    )
    verdicts, unsupported, contradicted = [], [], []
    for sent in sentences:
        toks = [t for t in re.findall(r"[\w\-]+", _norm(sent)) if len(t) > 2]
        if not toks:
            verdicts.append({"sentence": sent[:160], "verdict": "SUPPORTED"})
            continue
        hit = sum(1 for t in toks if t in allowed_tok) / max(1, len(toks))
        nums = re.findall(r"\d[\d.,\s]*", sent)
        bad_num = [
            n
            for n in nums
            if n.strip() and n.strip() not in " ".join(digits) and _norm(n.strip()) not in allowed
        ]
        if bad_num:
            verdicts.append(
                {
                    "sentence": sent[:160],
                    "verdict": "UNSUPPORTED",
                    "detail": f"numbers not in evidence: {bad_num}".strip(),
                }
            )
            unsupported.append(sent[:160])
        elif hit >= 0.35:
            verdicts.append({"sentence": sent[:160], "verdict": "SUPPORTED"})
        else:
            verdicts.append(
                {
                    "sentence": sent[:160],
                    "verdict": "UNSUPPORTED",
                    "detail": f"token overlap {hit:.2f}",
                }
            )
            unsupported.append(sent[:160])
    leak_hits = []
    for st in style_texts:
        for cand in set(
            re.findall(
                r"[А-Я][а-я]+\s+[А-Я][а-я]+(?:\s+[А-Я][а-я]+)?|\d[\d.,\s]*\s*(?:млн|лева|евро|€)|\"[^\"]{8,120}\"",
                st or "",
            )
        ):
            c = cand.strip().strip('"')
            if len(c) >= 6 and _norm(c) in _norm(draft_text) and _norm(c) not in allowed:
                leak_hits.append(c[:90])
    return {
        "sentences": verdicts,
        "unsupported": unsupported,
        "contradicted": contradicted,
        "leak_hits": sorted(set(leak_hits))[:20],
    }


_SEMANTIC_ISSUES = (
    "none",
    "attribution",
    "relationship",
    "temporal_rebinding",
    "invented_number",
    "invented_entity",
    "other",
)


def _semantic_judge_prompt(packet, draft_text):
    facts = "\n".join(
        f"- [{f['id']}] ({f.get('scope', 'current_event')}) {f['text']}"
        for f in packet.get("facts", [])
    )
    quotes = "\n".join(
        f'- "{q["text"]}" - {q.get("speaker")} ({q.get("role")})' for q in packet.get("quotes", [])
    )
    return (
        "You are a strict factual entailing checker for Bulgarian news. Current evidence (facts tagged "
        "current_event vs historical_background, plus quotes) is the ONLY authority. A draft sentence is "
        "SUPPORTED only if it is logically entailed by some current-event fact(s)/quote - not just token "
        "overlap. Specifically reject:\n"
        "- invented source/institution attribution (attribution)\n"
        "- wrong relationship/role binding (who does/receives/presents what, проф./доц. bindings) (relationship)\n"
        "- moving a number/count/organization/date from historical_background onto the current event (temporal_rebinding)\n"
        "- any number/entity not in evidence (invented_number / invented_entity)\n"
        "- unsupported connective/interpretive claims (other)\n\n"
        "A playful wording or rhetorical question is not itself a factual error. Check EVERY "
        "factual premise it implies against evidence, including synopsis/plot details. Do not "
        "invent plot points, reactions, reviews, audience response or promises of enjoyment. "
        "Do not exempt a sentence merely because it is called an editorial hook.\n\n"
        f"EVIDENCE FACTS:\n{facts}\n\nEVIDENCE QUOTES:\n{quotes or '(none)'}\n\n"
        f"DRAFT TEXT:\n{draft_text}\n\n"
        "For EACH factual sentence in the draft text, output ONE JSON object per line (JSON Lines):\n"
        '{"sentence": "<exact sentence>", "verdict": "SUPPORTED"|"UNSUPPORTED", '
        '"issue": "none"|"attribution"|"relationship"|"temporal_rebinding"|"invented_number"|"invented_entity"|"other", '
        '"supporting_fact_ids": ["id", ...], "note": "<short reason>"}. '
        "One object per line, no prose, no array brackets, no markdown."
    )


def _parse_semantic(raw):
    """Parse JSONL judge output. Tolerant of trailing junk / partial lines."""
    out = []
    errors = 0
    for line in (raw or "").strip().splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            m_end = line.rfind("}")
            if m_end >= 0:
                try:
                    item = json.loads(line[: m_end + 1])
                except json.JSONDecodeError:
                    errors += 1
                    continue
            else:
                errors += 1
                continue
        sentence = (item.get("sentence") or "").strip()
        verdict = item.get("verdict")
        if sentence and verdict in ("SUPPORTED", "UNSUPPORTED"):
            issue = item.get("issue") if item.get("issue") in _SEMANTIC_ISSUES else "other"
            out.append(
                {
                    "sentence": sentence[:240],
                    "verdict": verdict,
                    "issue": issue,
                    "supporting_fact_ids": [
                        str(i) for i in (item.get("supporting_fact_ids") or [])
                    ],
                    "note": (item.get("note") or "").strip(),
                }
            )
        else:
            errors += 1
    return out, errors


def verify_claims_semantic(packet, draft_text, *, api_key=None, timeout=240, model=None):
    """M2.3B second-pass semantic claim check. The deterministic audit is lexical and
    can mark a relationally-wrong or mis-attributed sentence SUPPORTED when tokens overlap.
    This asks the model to check entailment, attribution, relationship and temporal binding."""
    prompt_text = _semantic_judge_prompt(packet, draft_text)
    raw, meta = call_model(prompt_text, api_key=api_key, timeout=timeout, role="judge")
    claims, errors = _parse_semantic(raw)
    unsupported = [c for c in claims if c["verdict"] == "UNSUPPORTED"]
    return {
        "claims": claims,
        "unsupported": unsupported,
        "parse_errors": errors,
        # Fail closed: a reply that yielded NO verdict at all (prose, an empty
        # body, a refusal) is not a pass - nothing was actually checked, and
        # reporting FACTUAL_GATE_PASS would claim factual verification that
        # never happened. Tolerant of stray non-JSON lines around real verdicts.
        "pass": bool(claims) and not unsupported and errors == 0,
        "model": (model or meta.get("model", MODEL_ID)),
    }
