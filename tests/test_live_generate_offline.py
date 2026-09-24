"""Offline end-to-end of the LIVE generate path with a stubbed Gemini client.

Isolates prompt assembly, draft parsing, lexical+semantic audit, lineage and
persistence from network availability. No production store is touched.
"""

from __future__ import annotations

import json

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.drafting import model_policy, model_usage
from editor_assistant.drafting.retrieval import StyleRetrievalError
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


def _ready_case():
    """Build a real rubric-v2 assessment so readiness reaches DRAFT_READY."""
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
    return row


def _draft_json():
    return json.dumps(
        {
            "headlines": ["Заглавие"],
            "headline": "Заглавие",
            "body": "В Бургас отварят безплатен кабинет за деца.",
        },
        ensure_ascii=False,
    )


def _judge_jsonl():
    lines = [
        {
            "sentence": "В Бургас отварят безплатен кабинет за деца.",
            "verdict": "SUPPORTED",
            "issue": "none",
            "supporting_fact_ids": ["EV-M-f01"],
            "note": "ok",
        },
    ]
    return "\n".join(json.dumps(x, ensure_ascii=False) for x in lines)


def test_lineage_reports_the_route_that_actually_drafted(store, monkeypatch):
    """Review G1 / PART D: draft route 0 fails, route 1 succeeds -> the stored
    live_draft lineage, the opened case lineage AND the usage ledger must all
    name route 1 — never the static MODEL_ID."""
    _ready_case()
    cli.main(["live-case", "EV-M", "--idea", store["idea_id"], "--mode", "MODE_BRIEF"])

    routes = model_policy.load_policy()["roles"]["draft"]["routes"]
    first_model, second_model = routes[0]["model"], routes[1]["model"]

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class _DailyQuota429(gen.urllib.error.HTTPError):
        def __init__(self):
            super().__init__("https://example.invalid", 429, "Too Many Requests", None, None)
            self._chernomorie_body = "You exceeded your current quota per day"

        def read(self):  # pragma: no cover - body carried on the exception
            return self._chernomorie_body.encode()

    def fake(prompt_text, *, api_key, timeout, role="draft", model=None, **_kw):
        if role == "draft" and model == first_model:
            raise _DailyQuota429()
        if role == "draft":
            return _draft_json(), {"model": model, "provider": "gemini"}
        return _judge_jsonl(), {"model": model}

    monkeypatch.setattr(gen, "_call_gemini", fake)
    cli.main(["live-generate", "EV-M", "--case-id", "LIV-01"])

    draft = json.loads(cli.LIVE_DRAFTS_PATH.read_text(encoding="utf-8"))
    assert draft["lineage"]["model"] == second_model
    case = cases.read_cases(cli.CASES_PATH)[0]
    assert case["lineage"]["model"] == second_model

    # The ledger agrees with lineage: OK row on route 1, quota failure on route 0.
    calls = model_usage.read_day().get("calls") or []
    ok_models = [c["model"] for c in calls if c["role"] == "draft" and c["status"] == "OK"]
    assert ok_models == [second_model]
    quota_rows = [
        c for c in calls if c["role"] == "draft" and c.get("category") == "QUOTA_EXHAUSTED"
    ]
    assert [c["model"] for c in quota_rows] == [first_model]
    assert model_usage.model_calls_today("gemini", first_model) == 1
    assert model_usage.model_calls_today("gemini", second_model) == 1
    assert model_usage.role_calls_today("draft") == 1


def test_live_prompt_carries_real_style_prose_from_all_three_examples(store, stub_gemini):
    """Review G / PART G: the drafting model must SEE the three style bodies
    (non-empty P1/LAST), while the persisted draft JSON keeps IDs only."""
    _ready_case()
    cli.main(["live-case", "EV-M", "--idea", store["idea_id"], "--mode", "MODE_BRIEF"])
    cli.main(["live-generate", "EV-M", "--case-id", "LIV-01"])

    prompt = next(s["prompt"] for s in stub_gemini if s["role"] == "draft")
    p1_lines = [line[4:].strip() for line in prompt.splitlines() if line.startswith("P1: ")]
    last_lines = [line[6:].strip() for line in prompt.splitlines() if line.startswith("LAST: ")]
    assert len(p1_lines) == 3 and all(p1_lines), p1_lines
    assert len(last_lines) == 3 and all(last_lines), last_lines
    # style prose stays under STYLE_EXAMPLES and explicitly STYLE ONLY
    assert "STYLE EXAMPLE" in prompt and "STYLE ONLY" in prompt
    assert prompt.index("STYLE EXAMPLE") < prompt.index("TASK")

    # G: nothing persisted carries an archive body; F2: fallback metadata honest.
    stored = json.loads(cli.LIVE_DRAFTS_PATH.read_text(encoding="utf-8"))
    assert stored["retrieval_example_ids"] and len(stored["retrieval_example_ids"]) == 3
    retrieval_meta = stored["retrieval"]
    assert "examples" not in retrieval_meta  # IDs only, no bodies anywhere
    assert isinstance(retrieval_meta["fallback_used"], bool)
    assert retrieval_meta["retrieval_reason"]
    assert isinstance(retrieval_meta["fallback_trail"], list)
    assert "body" not in json.dumps(stored["retrieval"], ensure_ascii=False)


def test_legacy_caller_without_model_metadata_gets_the_documented_static_model(store, monkeypatch):
    """Review G1 / A3: the production router always names the model that ran;
    the `or gen.MODEL_ID` fallback in live_generate_draft exists only for
    legacy/mock callers that return no metadata at all — it must never be
    reachable on the router path (see model_router._try_route: meta always
    carries the route's model)."""
    _ready_case()

    def fake_call_model(prompt_text, *, api_key=None, timeout=240, role="draft", **_kw):
        if role == "draft":
            return _draft_json(), {}  # legacy shape: no model key at all
        return _judge_jsonl(), {}

    monkeypatch.setattr(gen, "call_model", fake_call_model)
    cli.main(["live-case", "EV-M", "--idea", store["idea_id"], "--mode", "MODE_BRIEF"])
    cli.main(["live-generate", "EV-M", "--case-id", "LIV-01"])

    draft = json.loads(cli.LIVE_DRAFTS_PATH.read_text(encoding="utf-8"))
    assert draft["lineage"]["model"] == gen.MODEL_ID


def test_style_preflight_failure_refuses_before_any_model_call(store, stub_gemini, monkeypatch):
    """Review G3 / PART F: a retrieval refusal happens BEFORE call_model —
    no draft request, no semantic judge request, no spend."""
    row = _ready_case()

    def boom(*_args, **_kwargs):
        raise StyleRetrievalError("стилови примери: само 0/3 уникални")

    monkeypatch.setattr(live, "retrieve_examples_for_generation", boom)
    with pytest.raises(live.LiveError, match="уникални"):
        live.live_generate_draft(row["packet"], voice=live.DEFAULT_VOICE, mode="MODE_BRIEF")
    assert stub_gemini == []  # not a single provider call happened
    assert not cli.LIVE_DRAFTS_PATH.exists() and not cli.CASES_PATH.exists()


def test_hermetic_idea_to_draft_happy_path_with_stubbed_retrieval(store, stub_gemini, monkeypatch):
    """ROUND 2 PART E: the full idea→draft happy path, hermetic.

    Retrieval is stubbed at the same seam the thin-corpus test fails at, so
    the run needs no real corpus: exactly 3 examples WITH bodies reach the
    prompt, IDs + truthful metadata (body-free) are persisted, and the opened
    case keeps the same lineage as the stored live draft.
    """
    _ready_case()

    def fake_retrieval(packet, *, voice, mode, **_kwargs):
        return {
            "examples": [
                {
                    "article_id": f"m{i}",
                    "url": f"https://archive.example/{i}",
                    "headline": f"Архив {i}",
                    "author": "Черноморие-бг",
                    "category": "Община",
                    "published_date": "2025-06-01",
                    "score": 100.0,
                    "score_parts": {},
                    "why_selected": "style reference only",
                    "body": f"Архивно тяло {i}.",
                }
                for i in (1, 2, 3)
            ],
            "fallback_used": True,
            "fallback_trail": [
                {"voice": voice, "mode": mode, "found": 0},
                {"voice": "VOICE_HOUSE", "mode": "MODE_BRIEF", "found": 3},
            ],
            "retrieval_reason": f"fallback: {voice}+{mode} -> VOICE_HOUSE+MODE_BRIEF",
        }

    monkeypatch.setattr(live, "retrieve_examples_for_generation", fake_retrieval)
    cli.main(["live-case", "EV-M", "--idea", store["idea_id"], "--mode", "MODE_BRIEF"])
    cli.main(["live-generate", "EV-M", "--case-id", "LIV-01"])

    draft = json.loads(cli.LIVE_DRAFTS_PATH.read_text(encoding="utf-8"))
    case = cases.read_cases(cli.CASES_PATH)[0]
    # exactly the three stubbed examples, persisted as IDs only
    assert draft["retrieval_example_ids"] == ["m1", "m2", "m3"]
    # the prompt really saw the archive prose (D1)
    prompt = next(s["prompt"] for s in stub_gemini if s["role"] == "draft")
    assert "Архивно тяло 1." in prompt and "Архивно тяло 3." in prompt
    # persisted metadata is truthful (F2) but body-free (G persistence boundary)
    assert draft["retrieval"]["fallback_used"] is True
    assert draft["retrieval"]["fallback_trail"][0]["found"] == 0
    assert draft["retrieval"]["retrieval_reason"].startswith("fallback:")
    assert "Архивно тяло" not in json.dumps(draft["retrieval"], ensure_ascii=False)
    assert "body" not in json.dumps(draft["retrieval"], ensure_ascii=False)
    # lineage is 1:1 between the live draft and the opened case
    assert draft["lineage"] == case["lineage"]
    assert case["case_id"] == "LIV-01" and case["track"] == cases.TRACK_LIVE


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
