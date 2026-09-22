"""Hermetic tests for the M4D role qualification harness (`scripts/evals`).

The harness must be safe by construction: `--list` makes no model call, scoring is
deterministic and role-appropriate (a false merge is a rejection for `story`, a
false positive is a rejection for `judge`), and fixtures exist for every role.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evals" / "model_role_eval.py"
FIXTURES = ROOT / "fixtures" / "evals" / "model_roles"


def _module():
    spec = importlib.util.spec_from_file_location("model_role_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_EVAL = _module()


@pytest.mark.parametrize("role", ["judge", "story", "angle", "draft", "research"])
def test_every_role_has_a_seed_fixture_with_cases(role):
    payload = json.loads((FIXTURES / f"{role}.json").read_text(encoding="utf-8"))
    assert payload["role"] == role
    assert payload["cases"], role
    for case in payload["cases"]:
        assert case.get("id"), role


def test_story_fixture_covers_all_four_relations_including_near_misses():
    payload = json.loads((FIXTURES / "story.json").read_text(encoding="utf-8"))
    relations = [c["relation"] for c in payload["cases"]]
    for expected in ("SAME_STORY", "NEW_DEVELOPMENT", "RELATED_BACKGROUND", "DIFFERENT_STORY"):
        assert expected in relations
    # near misses: the DIFFERENT_STORY cases share an actor/place/number with the story
    different = [c for c in payload["cases"] if c["relation"] == "DIFFERENT_STORY"]
    assert len(different) >= 3


def test_list_mode_makes_no_model_call(monkeypatch, capsys):
    def explode(*_args, **_kwargs):
        pytest.fail("--list must not call a model")

    monkeypatch.setattr(ROLE_EVAL.model_router, "call_role", explode)
    assert ROLE_EVAL.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "story:" in out and "judge:" in out
    assert "gemini" in out


def test_judge_scoring_treats_a_false_positive_as_a_rejection():
    case = {"id": "c", "entailed": False}
    wrong = ROLE_EVAL.score("judge", case, None, '{"entailed": true, "reason": "x"}', 10, True)
    assert wrong["false_positive"] is True and wrong["correct"] is False
    right = ROLE_EVAL.score("judge", case, None, '{"entailed": false, "reason": "x"}', 10, True)
    assert right["correct"] is True and right["false_positive"] is False
    broken = ROLE_EVAL.score("judge", case, None, "не е JSON", 10, True)
    assert broken["valid"] is False
    assert ROLE_EVAL.summarize("judge", [wrong], 1)["verdict"] == "REJECT (false positive)"


def test_story_scoring_treats_a_false_merge_as_a_rejection():
    case = {"id": "c", "relation": "DIFFERENT_STORY"}
    merged = ROLE_EVAL.score(
        "story",
        case,
        None,
        json.dumps(
            {
                "same_event": True,
                "relation": "SAME_STORY",
                "material_change": False,
                "shared_anchors": ["Бургас"],
                "reason": "изглежда същото",
            },
            ensure_ascii=False,
        ),
        10,
        True,
    )
    assert merged["false_merge"] is True
    assert ROLE_EVAL.summarize("story", [merged], 1)["verdict"] == "REJECT (false merge)"

    # A repeat announced as a new development is its own, separately reported error.
    repeat_case = {"id": "r", "relation": "SAME_STORY"}
    announced = ROLE_EVAL.score(
        "story",
        repeat_case,
        None,
        json.dumps(
            {
                "same_event": True,
                "relation": "NEW_DEVELOPMENT",
                "material_change": True,
                "shared_anchors": ["бюджет"],
                "reason": "ново гласуване",
            },
            ensure_ascii=False,
        ),
        10,
        True,
    )
    assert announced["false_merge"] is False
    assert announced["false_development"] is True
    assert ROLE_EVAL.summarize("story", [announced], 1)["verdict"] == ("REJECT (false development)")

    separate = ROLE_EVAL.score(
        "story",
        case,
        None,
        json.dumps(
            {
                "same_event": False,
                "relation": "DIFFERENT_STORY",
                "material_change": False,
                "shared_anchors": [],
                "reason": "различно събитие",
            },
            ensure_ascii=False,
        ),
        10,
        True,
    )
    assert separate["correct"] is True and separate["false_merge"] is False


def test_draft_scoring_flags_invented_numbers_and_missing_mentions():
    case = {"id": "d", "facts": ["Откриват кабинет на 1 октомври."], "must_mention": ["кабинет"]}
    good = ROLE_EVAL.score(
        "draft",
        case,
        None,
        json.dumps(
            {"headline": "Нов кабинет", "body": "Кабинетът отваря на 1 октомври."},
            ensure_ascii=False,
        ),
        10,
        True,
    )
    assert good["correct"] is True
    bad = ROLE_EVAL.score(
        "draft",
        case,
        None,
        json.dumps(
            {"headline": "Нов кабинет", "body": "Отваря на 5 ноември, 300 деца."},
            ensure_ascii=False,
        ),
        10,
        True,
    )
    assert bad["correct"] is False
    assert "300" in bad["invented_numbers"]
    missing = ROLE_EVAL.score(
        "draft",
        case,
        None,
        json.dumps({"headline": "Ново", "body": "Друго съобщение."}, ensure_ascii=False),
        10,
        True,
    )
    assert "кабинет" in missing["missing_mentions"]


def test_angle_and_research_scoring():
    angle_case = {"id": "a", "status": "NO_PUBLISHABLE_ANGLE"}
    bad = ROLE_EVAL.score(
        "angle",
        angle_case,
        None,
        json.dumps({"semantic_status": "PUBLISHABLE_ANGLE", "semantic_reason": "x"}),
        10,
        True,
    )
    assert bad["false_positive"] is True

    research_case = {"id": "r", "expect_keywords": ["маршрут", "финансиране"], "max_questions": 5}
    good = ROLE_EVAL.score(
        "research",
        research_case,
        None,
        json.dumps(
            {"questions": ["Какъв е маршрутът?", "Кой ще финансира линията?"]},
            ensure_ascii=False,
        ),
        10,
        True,
    )
    assert good["correct"] is True and good["coverage"] == 1.0


def test_unavailable_candidate_is_not_scored_as_correct(tmp_path):
    case = {"id": "c", "entailed": True}
    row = ROLE_EVAL.score("judge", case, None, "", 5, False)
    assert row["ok"] is False and row["correct"] is False
    assert ROLE_EVAL.summarize("judge", [row], 1)["verdict"] == "NO_ANSWER"


def test_run_role_writes_a_report_without_touching_a_provider(monkeypatch, tmp_path):
    calls = []

    def fake_call_role(role, prompt, **kwargs):
        calls.append(role)
        if role == "judge":
            return '{"entailed": true, "reason": "ok"}', {"model": "m"}
        if role == "story":
            return (
                json.dumps(
                    {
                        "same_event": True,
                        "relation": "SAME_STORY",
                        "material_change": False,
                        "shared_anchors": [],
                        "reason": "same",
                    }
                ),
                {"model": "m"},
            )
        if role == "angle":
            return '{"semantic_status": "NO_PUBLISHABLE_ANGLE", "semantic_reason": "x"}', {
                "model": "m"
            }
        if role == "draft":
            return json.dumps({"headline": "h", "body": "b"}), {"model": "m"}
        return json.dumps({"questions": ["Какъв е маршрутът?"]}), {"model": "m"}

    policy = ROLE_EVAL.model_policy.load_policy()
    report = ROLE_EVAL.run_role(
        "judge",
        policy=policy,
        limit=1,
        out_dir=tmp_path,
        call_role=fake_call_role,
    )
    assert calls and set(calls) == {"judge"}
    assert (
        report["candidates"][0]["summary"]["answers"] == report["candidates"][0]["summary"]["cases"]
    )
    written = json.loads((tmp_path / "judge.json").read_text(encoding="utf-8"))
    assert written["role"] == "judge" and written["policy_hash"]
