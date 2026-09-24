"""Offline tests for the OpenRouter transport (`generate._call_openrouter`).

These cover a real would-have-shipped bug: the parser read OpenAI-style SSE
frames but the request never asked for streaming, so every OpenRouter call
returned an empty completion and the whole fallback provider silently produced
nothing. No other test touched this function.

All HTTP is mocked; no network access.
"""

from __future__ import annotations

import json

import pytest

from editor_assistant.drafting import generate as gen


class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _sse(*texts: str) -> str:
    frames = ["data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) for t in texts if t]
    frames.append("data: [DONE]")
    return "\n\n".join(frames) + "\n\n"


def test_openrouter_requests_streaming_and_parses_sse(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["payload"] = json.loads(req.data.decode("utf-8"))
        seen["auth"] = req.headers.get("Authorization")
        return _FakeResp(_sse("Здрав", "ей"))

    monkeypatch.setattr(gen.urllib.request, "urlopen", fake_urlopen)
    text, meta = gen._call_openrouter("ping", api_key="k", timeout=5, model="m/one")

    # the request must actually ask for the stream the parser reads
    assert seen["payload"]["stream"] is True
    assert seen["payload"]["model"] == "m/one"
    assert text == "Здравей"
    assert meta["provider"] == "openrouter"


def test_openrouter_falls_back_to_nonstreaming_body(monkeypatch):
    """A provider that ignores `stream` must not yield an empty generation."""

    def fake_urlopen(req, timeout):
        return _FakeResp(
            json.dumps({"choices": [{"message": {"role": "assistant", "content": "готово"}}]})
        )

    monkeypatch.setattr(gen.urllib.request, "urlopen", fake_urlopen)
    text, _meta = gen._call_openrouter("ping", api_key="k", timeout=5, model="m/one")
    assert text == "готово"


def test_openrouter_malformed_body_is_empty_not_an_exception(monkeypatch):
    monkeypatch.setattr(
        gen.urllib.request, "urlopen", lambda req, timeout: _FakeResp("not json at all")
    )
    text, _meta = gen._call_openrouter("ping", api_key="k", timeout=5, model="m/one")
    assert text == ""


def test_call_model_reaches_openrouter_only_without_gemini_key(monkeypatch):
    """A policy-declared FREE model reaches OpenRouter when Gemini has no key.

    The id is declared `free` in the tracked policy, so it is eligible for a
    public payload (story role) — an UNDECLARED id would fail paid-safe (A3)
    and never reach a transport at all.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    captured = {}

    def fake_openrouter(prompt_text, *, api_key, timeout, model):
        captured.update({"api_key": api_key, "model": model})
        return "ok", {"provider": "openrouter"}

    monkeypatch.setattr(gen, "_call_openrouter", fake_openrouter)
    text, _meta = gen.call_model("ping", model="qwen/qwen3.8-27b:free", role="story")
    assert text == "ok"
    assert captured == {"api_key": "or-key", "model": "qwen/qwen3.8-27b:free"}


def test_paid_openrouter_model_is_refused_before_any_call(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    called = {"n": 0}
    monkeypatch.setattr(
        gen, "_call_openrouter", lambda *a, **k: called.__setitem__("n", called["n"] + 1)
    )
    with pytest.raises(RuntimeError):
        gen.call_model("ping", model="openai/gpt-oss-20b")
    assert called["n"] == 0
