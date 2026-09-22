"""Offline end-to-end of the LIVE generate path with a stubbed Gemini client.

Isolates prompt assembly, draft parsing, lexical+semantic audit, lineage and
persistence from network availability. No production store is touched.
"""

from __future__ import annotations

import json

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import angles, cases, cli, live
from editor_assistant.workflow.ideas import save_ideas


@pytest.fixture
def store(tmp_path, monkeypatch):
    for name, filename in (
        ("IDEAS_PATH", "ideas.jsonl"),
        ("LIVE_EVIDENCE_PATH", "evidence.jsonl"),
        ("LIVE_DRAFTS_PATH", "drafts.jsonl"),
        ("CASES_PATH", "cases.jsonl"),
    ):
        monkeypatch.setattr(cli, name, tmp_path / filename)
    idea = live.new_idea(
        source_type="council_transcript",
        source_url="transcript://editor-supplied/test",
        title="Комисия",
        what_changed="Тестван lead.",
    )
    save_ideas([idea], cli.IDEAS_PATH)
    packet = live.build_live_packet(
        idea,
        record={
            "url": "transcript://editor-supplied/test",
            "headline": "Комисия по здравеопазване",
            "body": "В Бургас отварят безплатен кабинет за деца. "
            "Единодушно се приема. Втора точка е доклад.",
        },
        evidence_id="EV-M",
        observed_at="2026-09-16",
    )
    cli._save_live_row({"evidence_id": "EV-M", "idea_id": idea["idea_id"], "packet": packet})
    return idea


@pytest.fixture
def stub_gemini(monkeypatch):
    """Fixed _call_gemini: valid draft JSON for role=draft, JSONL judge lines
    for role=judge. Records prompts so the test can inspect assembly."""
    seen = []
    # hermetic routing: no ambient keys may redirect call_model elsewhere
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def fake(prompt_text, *, api_key, timeout, role="draft", **_kw):
        seen.append({"role": role, "prompt": prompt_text})
        if role == "draft":
            return (
                json.dumps(
                    {
                        "headlines": ["Заглавие"],
                        "headline": "Заглавие",
                        "body": "В Бургас отварят безплатен кабинет за деца.",
                    },
                    ensure_ascii=False,
                ),
                {"model": "mock", "provider": "gemini"},
            )
        lines = [
            {
                "sentence": "В Бургас отварят безплатен кабинет за деца.",
                "verdict": "SUPPORTED",
                "issue": "none",
                "supporting_fact_ids": ["EV-M-f01"],
                "note": "ok",
            },
        ]
        return "\n".join(json.dumps(x, ensure_ascii=False) for x in lines), {"model": "mock"}

    monkeypatch.setattr(gen, "_call_gemini", fake)
    return seen


def test_offline_end_to_end_generation_path(store, stub_gemini):
    row = cli._live_rows()["EV-M"]
    facts = row["packet"]["facts"]
    candidates = []
    for n, fact in enumerate(facts):
        scores = {k: {"score": 0} for k in angles.CRITERIA}
        if n == 0:
            for key in ("concrete_change", "people_impact", "burgas_novelty"):
                scores[key] = {
                    "score": 2,
                    "reason": "Нов безплатен кабинет за деца в Бургас.",
                    "fact_ids": [fact["id"]],
                }
        candidates.append(
            {
                "angle_id": f"A{n}",
                "title": fact["text"],
                "fact_ids": [fact["id"]],
                "scores": scores,
                "new_proposition": f"Ново: {fact['text']}",
                "reason": "Нов местен достъп до лечение." if n == 0 else "Процедурна точка.",
            }
        )
    row["packet"]["editorial_assessment"] = angles.assess_angles(row["packet"], candidates)
    cli._save_live_row(row)
    cli.main(["live-case", "EV-M", "--idea", store["idea_id"], "--mode", "MODE_BRIEF"])
    cli.main(["live-generate", "EV-M", "--case-id", "LIV-01"])
    case = cases.read_cases(cli.CASES_PATH)[0]
    draft = json.loads(cli.LIVE_DRAFTS_PATH.read_text(encoding="utf-8"))
    # prompt assembly really ran (sections, evidence, style examples included)
    roles = [s["role"] for s in stub_gemini]
    assert roles == ["draft", "judge"]
    assert "В Бургас отварят безплатен кабинет за деца." in stub_gemini[0]["prompt"]
    assert "Втора точка е доклад." not in stub_gemini[0]["prompt"]
    assert case["case_id"] == "LIV-01" and case["track"] == cases.TRACK_LIVE
    assert case["factual_gate"] == "FACTUAL_GATE_PASS"
    assert case["draft_text"].startswith("В Бургас")
    assert draft["semantic"]["pass"] is True
    assert draft["lineage"]["draft_id"] == case["draft_id"]
    # M4F F5: the deterministic originality verdict rides into both stores.
    assert draft["originality"]["pass"] is True
    assert case["audit"]["originality"]["checked"] is True


def test_gemini_retries_503_then_succeeds(monkeypatch):
    """The frozen backoff: one 503 must be retried, not fatal (no code change)."""
    calls = {"n": 0}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            payload = {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                "usageMetadata": {},
            }
            return json.dumps(payload).encode()

    urls, keys = [], []

    def fake_urlopen(req, timeout):
        urls.append(req.full_url)
        keys.append(req.get_header("X-goog-api-key"))
        calls["n"] += 1
        if calls["n"] == 1:
            raise gen.urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", None, None)
        return FakeResp()

    monkeypatch.setattr(gen.urllib.request, "urlopen", fake_urlopen)
    text, _meta = gen._call_gemini("ping", api_key="k", timeout=5, min_gap=0, role="draft")
    assert calls["n"] == 2
    assert "OK" in text or text  # recovered response reached the caller
    # M4F F6: the key travels as a header; URLs are logged everywhere.
    assert all("?key=" not in u and "key=" not in u for u in urls)
    assert keys == ["k", "k"]
