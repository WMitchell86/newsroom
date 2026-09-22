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


# Generation entry point. Model *routing* lives in `drafting/model_policy.py`
# (ordered routes per role, day budgets, the paid gate, `public_only` privacy
# flags) and `drafting/model_router.py` (true cross-provider fallback, failure
# classification, route health, usage ledger). `call_model` below is the thin
# entry point every caller keeps using; the pools in this module are the legacy
# direct-call fallback for callers that bypass the router.
#
# Provider catalogs and account quotas are DYNAMIC. Do not trust a list in a
# comment: `newsroom models validate` checks ids against the live Gemini and
# OpenRouter catalogs, and `newsroom models status` reports today's per-model
# usage against the operator-declared limits.
#
# Model swap for direct callers is via MODEL_ID + MODEL_ENDPOINT + API_PROVIDER +
# API_KEY_ENV; no other code path (lineage, audit, prompt, retrieval) depends on
# the provider identity.


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


_GEMINI_LAST_CALL = [0.0]
_GEMINI_EXHAUSTED = set()  # models that returned a daily-quota 429 (this process)

# Legacy direct-call pools (used when `_call_gemini` is called without `model=`).
# The router pins one model per route from the policy file, so these lists only
# matter for direct callers and the M3D eval scripts. Order is meaningful: the
# first entry is tried first, and a model that returns a daily-quota 429 is
# skipped for the rest of the process.
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
# The Lite buckets are the judge/utility workhorses (the operator's own quota).
# `gemini-3.5-flash-lite` rejects generationConfig.thinkingConfig with 400; the
# policy marks that route `omit_thinking_config: true`, which the direct pool
# path here does not do — so a direct `_call_gemini(role="judge")` call may burn
# one request before rotation. Route judge calls through the router.
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


def _call_gemini(
    prompt_text,
    *,
    api_key,
    timeout,
    min_gap=5,
    max_attempts=4,
    role="draft",
    model=None,
    omit_thinking_config=False,
):
    """One Gemini call. `model` pins a single id (the router's per-route call);
    without it the role pool is walked as before (legacy direct callers).

    `omit_thinking_config` exists because one model in the account's Flash-Lite
    quota (gemini-3.5-flash-lite) rejects `generationConfig.thinkingConfig` with
    HTTP 400 — that bucket is otherwise unusable, so the policy can declare
    `omit_thinking_config: true` per route instead of dropping the model.
    """
    prompt_text = _trim_for_model(prompt_text)
    trimmed_len = len(prompt_text)
    gen_cfg = {
        "temperature": GENERATION_SETTINGS["temperature"],
        "maxOutputTokens": GENERATION_SETTINGS["max_tokens"],
    }
    if THINKING_BUDGET >= 0 and not omit_thinking_config:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": THINKING_BUDGET}
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": gen_cfg,
        }
    ).encode("utf-8")
    last_err = None
    for model_id in [model] if model else _gemini_pool(role):
        # M4F F6: the key NEVER enters the URL (URLs leak into logs, proxies
        # and history); Gemini accepts it as the x-goog-api-key header.
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + model_id
            + ":generateContent"
        )
        for attempt in range(1, max_attempts + 1):
            _gemini_pace(min_gap)
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
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
                    "model": model_id,
                    "usage": usage,
                    "provider": "gemini",
                    "role": role,
                    "prompt_chars": trimmed_len,
                    "finish_reason": cand.get("finishReason"),
                }
            except urllib.error.HTTPError as exc:
                last_err = exc
                body = _http_body(exc)
                # The router classifies failures from the provider body, and the
                # body can only be read once — carry it on the exception.
                try:
                    exc._chernomorie_body = body
                except AttributeError:  # pragma: no cover - unusual HTTPError subclass
                    pass
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
                    _GEMINI_EXHAUSTED.add(model_id)
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
    payload_class=None,
):
    """Route one generation through the role policy (`drafting/model_policy.py`).

    One shared router (`drafting/model_router.py`) walks the role's ordered route
    list: disabled routes are skipped, paid routes need `global.paid_enabled`,
    public-only routes never receive private material, spent per-model daily
    limits and unhealthy routes are skipped, and a failure continues to the *next*
    route — including across providers. That last part is the correction: the old
    code returned early whenever `GEMINI_API_KEY` was present, so an exhausted
    Gemini pool never reached OpenRouter at all.

    Failure mode: `model_router.RoleUnavailable` (a `RuntimeError`, so legacy
    callers still catch it). It carries the role's `on_exhausted` contract — e.g.
    the story role must stay separate, the judge role must never report a pass,
    and the draft role must fail visibly rather than drop to an unqualified model.

    `model=` pins an explicit OpenRouter model (legacy callers, eval harness).
    `prefer_free_openrouter` keeps its old meaning: prefer the configured free
    OpenRouter model when no Gemini key is available.
    """
    from editor_assistant.drafting import model_router  # lazy: one-way dependency

    chosen = model
    if (
        chosen is None
        and prefer_free_openrouter
        and not (api_key or os.environ.get("GEMINI_API_KEY"))
    ):
        chosen = os.environ.get("OPENROUTER_FREE_MODEL") or OPENROUTER_FREE_MODEL
    return model_router.call_role(
        role,
        prompt_text,
        api_key=api_key,
        timeout=timeout,
        model=chosen,
        payload_class=payload_class,
    )


OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it")
# Legacy single-model knob. The role policy (`config/model_policy.default.json` +
# `var/model_policy.json`) now owns routing: per role, an ordered list of
# {provider, model, billing, public_only, daily_call_limit}. This variable is only
# the fallback the legacy `call_model(model=...)` path uses, and it is what
# `OPENROUTER_MODEL` overrides for every role that has an OpenRouter route.
#
# Validate ids against the live catalog before relying on them:
#   newsroom models validate     # live Gemini models.list + OpenRouter /models
#   newsroom models status       # today's calls per model vs declared limits
#
# The current free OpenRouter catalog (2026-09-21 probe, 24 free ids) that fits
# Bulgarian text work: google/gemma-4-31b-it:free, google/gemma-4-26b-a4b-it:free,
# qwen/qwen3.8-27b:free, nvidia/nemotron-3-ultra-550b-a55b:free,
# nvidia/nemotron-3-super-120b-a12b:free, nvidia/nemotron-3.5-lightning:free,
# thinkingmachines/inkling:free, z-ai/glm-5.2:free. Free endpoints may train on
# the request, which is why the policy marks them `public_only: true`.
#
# Paid ids seen in the same probe: openai/gpt-5.6-luna and openai/gpt-5.6-luna-pro
# ($0.20/M in, $1.20/M out), openai/gpt-5.4 ($2.50/M in, $15/M out). Paid routes
# are unusable until the operator sets `paid_enabled` in the policy.
#
# `openai/gpt-oss-20b` / `openai/gpt-oss-120b` stay explicitly forbidden at call
# time (`_OPENROUTER_PAID_FORBIDDEN`) regardless of the policy.
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


# M4F F5 (owner requirement): a draft must differ from its source and must not
# look copy-pasted. Verbatim prose runs of this many words (direct quotes
# excluded) are copy-paste and surface as a REVIEW warning on the case.
ORIGINALITY_THRESHOLD_WORDS = 8
_QUOTED_RX = re.compile(r"[«„\"][^«»„“”\"]{4,400}[»”\"]")


def _words(text):
    return re.findall(r"\w+", _norm(text))


def _prose(text):
    """Text minus direct quotes — a quote is *supposed* to match verbatim."""
    return _QUOTED_RX.sub(" ", text or "")


def _share_run(a, b, length):
    """True when both word streams share a contiguous run of `length` words."""
    if length <= 0:
        return True
    if length > len(a) or length > len(b):
        return False
    src = {tuple(b[i : i + length]) for i in range(len(b) - length + 1)}
    return any(tuple(a[i : i + length]) in src for i in range(len(a) - length + 1))


def _longest_common_run(a, b):
    """Length of the longest contiguous word run present in both streams."""
    if not a or not b:
        return 0
    lo, hi, best = 1, min(len(a), len(b)), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if _share_run(a, b, mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def originality_check(draft_text, source_text, *, threshold=ORIGINALITY_THRESHOLD_WORDS):
    """Deterministic no-copy guard (M4F F5): how much of the draft is verbatim
    source prose.

    Returns a factual-gate-style verdict:
      pass               no shared prose run reaches `threshold` words
      checked            False when either side has no prose to compare
      longest_run_words  longest contiguous shared word run
      copied             draft sentences that are mostly covered by a shared run

    Direct quotes («…», „…“, "…") are stripped from BOTH sides first: quoting
    the source verbatim is correct journalism, copying its prose is not.
    """
    segments = [
        s.strip() for s in re.split(r"(?<=[.!?…])\s+", _prose(draft_text or "")) if s.strip()
    ]
    draft_words: list[str] = []
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for seg in segments:
        words = _words(seg)
        spans.append((pos, pos + len(words), seg))
        draft_words.extend(words)
        pos += len(words)
    src_words = _words(_prose(source_text or ""))
    result = {
        "pass": True,
        "checked": bool(draft_words and src_words),
        "threshold": threshold,
        "longest_run_words": 0,
        "copied": [],
    }
    if not result["checked"]:
        return result
    longest = _longest_common_run(draft_words, src_words)
    result["longest_run_words"] = longest
    if longest < threshold:
        return result
    # Fail: mark every word covered by a maximal shared run, then report the
    # sentences where most words are covered (evidence for the editor).
    starts: dict[tuple[str, ...], list[int]] = {}
    for j in range(len(src_words) - threshold + 1):
        starts.setdefault(tuple(src_words[j : j + threshold]), []).append(j)
    covered = [False] * len(draft_words)
    for i in range(len(draft_words) - threshold + 1):
        for j in starts.get(tuple(draft_words[i : i + threshold]), ()):
            s, e, js = i, i + threshold, j
            while s > 0 and js > 0 and draft_words[s - 1] == src_words[js - 1]:
                s -= 1
                js -= 1
            while (
                e < len(draft_words)
                and js + (e - s) < len(src_words)
                and draft_words[e] == src_words[js + (e - s)]
            ):
                e += 1
            covered[s:e] = [True] * (e - s)
    for start, end, seg in spans:
        n = end - start
        hit = sum(1 for k in range(start, end) if covered[k])
        if n and hit * 2 >= n and hit >= threshold // 2:
            result["copied"].append(seg[:160])
    result["pass"] = False
    return result


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
