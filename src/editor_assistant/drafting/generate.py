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
#   primary  : GEMINI_API_KEY -> gemini-3.6-flash (Gemini provider)
#   fallback : OPENROUTER_API_KEY -> OpenAI-compatible model (OpenRouter provider)
#   free     : if neither key present and the task permits, a free OpenRouter model
#
# Model swap is via MODEL_ID + MODEL_ENDPOINT + API_PROVIDER + API_KEY_ENV; no other
# code path (lineage, audit, prompt, retrieval) depends on the provider identity.


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


_GEMINI_LAST_CALL = [0.0]
_GEMINI_EXHAUSTED = set()  # models that returned a daily-quota 429 (this process)

# Free-tier Gemini meters each model separately. Verified buckets for this key:
#   gemini-3.5-flash       ~20/day        -> drafting (primary)
#   gemini-3.7-flash       ~20/day        -> drafting rotation
#   gemini-3.8-flash       ~20/day        -> drafting rotation
#   gemini-3.5-flash-lite  500/day, 15 RPM -> semantic judge
#   gemini-3.1-flash-lite  500/day, 15 RPM -> semantic judge rotation
DRAFT_MODEL_POOL = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_DRAFT_MODELS",
        "gemini-3.5-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-3-flash-preview",
    ).split(",")
    if m.strip()
]
JUDGE_MODEL_POOL = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_JUDGE_MODELS",
        "gemini-3.1-flash-lite,gemini-3.1-flash-lite-preview,gemini-flash-lite-latest",
    ).split(",")
    if m.strip()
]
# NOTE: gemini-3.5-flash-lite was dropped from the judge pool: it rejects
# generationConfig.thinkingConfig with 400 INVALID_ARGUMENT, which burned a
# wasted request on every judge call before rotation rescued it.
if MODEL_ID not in DRAFT_MODEL_POOL:
    DRAFT_MODEL_POOL.insert(0, MODEL_ID)


def _gemini_pool(role="draft"):
    """Ordered model list for a role, skipping buckets already known exhausted."""
    pool = JUDGE_MODEL_POOL if role == "judge" else DRAFT_MODEL_POOL
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


def _call_openrouter(prompt_text, *, api_key, timeout, model):
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": GENERATION_SETTINGS["temperature"],
            "max_tokens": GENERATION_SETTINGS["max_tokens"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    chunks = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
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
    return text, {"model": model, "usage": {}, "provider": "openrouter"}


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
    Within a role the pool is walked in order and exhausted buckets are skipped.

    Resolution order:
    1. Explicit api_key -> configured primary provider (Gemini), given role.
    2. GEMINI_API_KEY present -> Gemini, given role.
    3. OPENROUTER_API_KEY present -> OpenAI-compatible fallback model.
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
        return _call_openrouter(prompt_text, api_key=or_key, timeout=timeout, model=use)

    raise RuntimeError("No API key available (GEMINI_API_KEY or OPENROUTER_API_KEY)")


OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-20b")
# Available OpenRouter models: openai/gpt-oss-20b, stealth/union-alpha
# Configured OpenRouter identity used as the OpenAI-compatible fallback when a
# paid/work OpenRouter key is used. Change in env or here; kept as the m2.3b fallback
# identity for lineage continuity.
OPENROUTER_FALLBACK_MODEL = OPENROUTER_MODEL
OPENROUTER_FREE_MODEL = os.environ.get("OPENROUTER_FREE_MODEL", "meta/llama-3.3-70b-instruct")
# Free OpenRouter model used ONLY when neither Gemini nor a work OpenRouter key is
# present AND the task is explicitly non-Bulgarian / non-editorial-critical. For M2.3
# Bulgarian drafting this should remain unset unless you explicitly opt into free-tier
# experimentation.
# Union Alpha (stealth/union-alpha) is a multimodal model for research, coding,
# and agentic workflows — set OPENROUTER_MODEL=stealth/union-alpha to use it.


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
