"""Hermetic tests for the M4D role qualification harness (`scripts/evals`).

The harness must be safe by construction AND honest about production fidelity
(pre-frontend gate I):

* `--list` makes no model call; scoring is deterministic and role-appropriate
  (a false merge rejects `story`, a false positive rejects `judge`/`angle`);
* `judge`/`angle`/`draft` send the REAL production prompt+parser contracts
  (`discovery.render_entail_prompt`/`parse_entail_answer`,
  `discovery.render_assess_prompt`/`parse_assess_answer`,
  `prompt.build_prompt` + `generate.parse_draft_json`/`audit_claims`/
  `originality_check`);
* every report carries its wiring truth (production-faithful / not wired /
  not evaluated) — research must never be presented as production qualified;
* paid candidates refuse to run without the explicit opt-in;
* the final Bulgarian style decision is a HUMAN review sheet, never a model.
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

STATUSES = (
    "PUBLISHABLE_ANGLE",
    "POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH",
    "NO_PUBLISHABLE_ANGLE",
)


def _assess_answer(case, status):
    """A production-valid seven-criterion assessment answer for `case`."""
    ids = [r["fact_id"] for r in ROLE_EVAL._angle_refs(case)]
    scores = {
        crit: {"score": 0, "reason": "—", "fact_ids": []}
        for crit in ROLE_EVAL.discovery._angles_mod.CRITERIA
    }
    if ids:
        scores["concrete_change"] = {"score": 1, "reason": "подкрепено", "fact_ids": ids[:1]}
    return json.dumps(
        {
            "scores": scores,
            "semantic_status": status,
            "semantic_reason": "x",
            "research_questions": [],
        },
        ensure_ascii=False,
    )


def _profile(profile_id):
    """Minimal structurally-valid VOICE/MODE profile for the prompt builder."""
    return {
        "profile_id": profile_id,
        "display_name": profile_id,
        "scope": "",
        "preferred_use": "",
        "headline": {"typical_length": 60, "common_patterns": ["—"], "avoid": []},
        "opening": {"typical_patterns": ["..."]},
        "body": {
            "paragraph_shape": "2-3 short paragraphs",
            "sentence_shape": "simple",
            "pacing": "even",
            "structure": "lede-body",
        },
        "quotes": {"frequency": "rare", "placement": "inline", "integration": "tight"},
        "tone": {
            "factual_vs_descriptive": "factual",
            "narrative_distance": "close",
            "local_specificity": "local",
        },
        "numbers_dates": {"conventions": ["дд.мм.гггг"]},
        "lexical_notes": {"recurring_preferences": ["общината"]},
        "avoidances": ["сензационност"],
    }


def _eval_assets():
    """Injected Site DNA + profiles + three body-bearing style examples (I4/G)."""
    examples = [
        {
            "article_id": f"S{i}",
            "headline": f"Заглавие на пример {i}",
            "author": "Автор",
            "category": "Общество",
            "published_date": "2026-09-01",
            "url": f"https://example.org/style/{i}",
            "body": (
                f"Първи абзац на пример {i} с достатъчно текст.\n\n"
                f"Втори абзац с разяснение.\n\n"
                f"Последен абзац на пример {i}."
            ),
        }
        for i in (1, 2, 3)
    ]
    return {
        "site_dna": {"conventions": {"tone": "factual, local"}},
        "voice_profile": _profile("VOICE_HOUSE"),
        "mode_profile": _profile("MODE_STANDARD_NEWS"),
        "examples": examples,
    }


def _draft_cases(with_assets=True):
    cases = ROLE_EVAL.load_cases("draft")
    if with_assets:
        cases = [{**c, "eval_assets": _eval_assets()} for c in cases]
    return cases


def _raw_draft(headline, body):
    return json.dumps({"headline": headline, "body": body}, ensure_ascii=False)


# ---------------------------------------------------------------- fixtures


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


def test_list_mode_makes_no_model_call_and_reports_wiring_truth(monkeypatch, capsys):
    def explode(*_args, **_kwargs):
        pytest.fail("--list must not call a model")

    monkeypatch.setattr(ROLE_EVAL.model_router, "call_role", explode)
    assert ROLE_EVAL.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "story:" in out and "judge:" in out
    assert "gemini" in out
    # wiring truth is visible even in plan mode (I5/I6)
    assert "wiring: PRODUCTION_FAITHFUL" in out
    assert "RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED" in out
    assert "wiring: NOT_EVALUATED" in out


# ---------------------------------------------------------------- judge (I2)


def test_judge_prompt_is_the_production_entailment_contract():
    # the duplicated harness-local prompt is gone — production owns the contract
    assert not hasattr(ROLE_EVAL, "JUDGE_PROMPT")
    case = {"id": "c", "fact": "ФАКТ_X", "support": ["ОТРЯЗЪК_Y", "ОТРЯЗЪК_Z"], "entailed": True}
    text = ROLE_EVAL.prompt_for("judge", case)
    assert text == ROLE_EVAL.discovery.render_entail_prompt("ФАКТ_X", ["ОТРЯЗЪК_Y", "ОТРЯЗЪК_Z"])
    assert "ФАКТ: ФАКТ_X" in text
    assert "ОТРЯЗЪК_Y" in text and "---" in text


def test_judge_scoring_treats_a_false_positive_as_a_rejection():
    case = {"id": "c", "entailed": False}
    wrong = ROLE_EVAL.score("judge", case, None, '{"entailed": true, "reason": "x"}', 10, True)
    assert wrong["false_positive"] is True and wrong["correct"] is False
    right = ROLE_EVAL.score("judge", case, None, '{"entailed": false, "reason": "x"}', 10, True)
    assert right["correct"] is True and right["false_positive"] is False
    broken = ROLE_EVAL.score("judge", case, None, "не е JSON", 10, True)
    assert broken["valid"] is False
    # production parser rules: JSON without a boolean `entailed` is not an answer
    incomplete = ROLE_EVAL.score("judge", case, None, '{"reason": "без поле"}', 10, True)
    assert incomplete["valid"] is False
    assert ROLE_EVAL.summarize("judge", [wrong], 1)["verdict"] == "REJECT (false positive)"


def test_judge_report_declares_the_draft_semantic_subtype_pending(tmp_path):
    policy = ROLE_EVAL.model_policy.load_policy()
    report = ROLE_EVAL.run_role(
        "judge",
        policy=policy,
        limit=1,
        out_dir=tmp_path,
        call_role=lambda *a, **k: ('{"entailed": true, "reason": "ok"}', {"model": "m"}),
    )
    assert report["wiring"] == "PRODUCTION_FAITHFUL"
    # I2: the draft semantic judge is a SEPARATE fixture subtype — pending,
    # never merged into the fact-entailment metric.
    assert report["fixture_subtypes"] == {
        "fact_entailment": "PRODUCTION_FAITHFUL",
        "draft_semantic": "PENDING_NO_FIXTURE",
    }


# ---------------------------------------------------------------- story (I1 kept)


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


# ---------------------------------------------------------------- angle (I3)


def test_angle_prompt_is_the_production_seven_criterion_assessment():
    case = ROLE_EVAL.load_cases("angle")[0]
    text = ROLE_EVAL.prompt_for("angle", case)
    assert text == ROLE_EVAL.discovery.render_assess_prompt(
        ROLE_EVAL._angle_proposal(case), ROLE_EVAL._angle_refs(case)
    )
    assert "@@" not in text  # fully rendered, no placeholder leaked
    for criterion in ROLE_EVAL.discovery._angles_mod.CRITERIA:
        assert criterion in text
    for status in STATUSES:
        assert status in text


def test_angle_scoring_uses_the_production_parser():
    case = {"id": "a", "facts": ["Факт първи."], "status": "NO_PUBLISHABLE_ANGLE"}

    # status-only answer (the old simplified eval shape) is NOT valid anymore
    status_only = json.dumps(
        {"semantic_status": "PUBLISHABLE_ANGLE", "semantic_reason": "x", "research_questions": []}
    )
    assert ROLE_EVAL.score("angle", case, None, status_only, 10, True)["valid"] is False

    # production validation: all seven criteria must be scored
    incomplete = {
        crit: {"score": 0, "reason": "—", "fact_ids": []}
        for crit in ROLE_EVAL.discovery._angles_mod.CRITERIA
    }
    incomplete.pop("burgas_novelty")
    raw_incomplete = json.dumps(
        {"scores": incomplete, "semantic_status": "NO_PUBLISHABLE_ANGLE"}, ensure_ascii=False
    )
    assert ROLE_EVAL.score("angle", case, None, raw_incomplete, 10, True)["valid"] is False

    good = ROLE_EVAL.score(
        "angle", case, None, _assess_answer(case, "NO_PUBLISHABLE_ANGLE"), 10, True
    )
    assert good["valid"] and good["correct"] and not good["false_positive"]

    # catastrophic error: routine material called publishable → rejection
    bad = ROLE_EVAL.score("angle", case, None, _assess_answer(case, "PUBLISHABLE_ANGLE"), 10, True)
    assert bad["false_positive"] is True and bad["correct"] is False
    assert ROLE_EVAL.summarize("angle", [bad], 1)["verdict"] == "REJECT (false positive)"


def test_angle_fixture_carries_the_seven_m3d_disagreement_cases():
    payload = json.loads((FIXTURES / "angle.json").read_text(encoding="utf-8"))
    for case in payload["cases"]:
        assert case["status"] in STATUSES, case["id"]
        assert case.get("title") and case.get("new_proposition"), case["id"]
        assert case.get("facts"), case["id"]
    m3d = [c for c in payload["cases"] if c.get("m3d_disagreement")]
    assert len(m3d) == 7  # the known M3D shadow disagreements (routine-vs-concrete)
    for case in m3d:
        assert case["shadow_status"] in STATUSES
        assert case["shadow_status"] != case["status"]
        # expected label = deterministic assessment (production-authoritative);
        # shadow/audit labels stay metadata, never ground truth
        assert (
            case.get("audit_hypothesis_label") is None or case["audit_hypothesis_label"] in STATUSES
        )
        for fact in case["facts"]:
            assert fact.get("fact_id") and fact.get("text")


# ---------------------------------------------------------------- draft (I4)


def test_draft_prompt_is_the_real_production_prompt_with_style_prose():
    case = _draft_cases()[0]
    text = ROLE_EVAL.prompt_for("draft", case)
    # the real build_prompt() sectioned contract
    for section in (
        "SYSTEM",
        "CURRENT_EVIDENCE",
        "CURRENT_QUOTES",
        "SITE_DNA",
        "VOICE_PROFILE",
        "MODE_PROFILE",
        "STYLE_EXAMPLES",
        "TASK",
        "FORBIDDEN",
    ):
        assert f"===== {section} =====" in text
    # frozen packet evidence is the factual source
    assert "ДКЦ-1" in text
    # G/I4: the drafting model sees non-empty style prose from ALL three
    # examples (P1 + LAST), and the STYLE ONLY boundary is explicit
    assert "STYLE ONLY" in text
    assert "Първи абзац на пример 1" in text and "Последен абзац на пример 1" in text
    assert "Първи абзац на пример 2" in text
    assert "Последен абзац на пример 3" in text


def test_draft_scoring_flags_invented_numbers_missing_support_and_copying():
    case = _draft_cases(with_assets=False)[0]

    good = ROLE_EVAL.score(
        "draft",
        case,
        None,
        _raw_draft(
            "В ДКЦ-1 отваря безплатен кабинет за деца с диабет",
            "В Бургас отваря безплатен кабинет за деца с диабет. "
            "Приемът в ДКЦ-1 е от 1 октомври, всеки работен ден. "
            "За деца до 18 години услугата остава безплатна.",
        ),
        10,
        True,
    )
    assert good["valid"] and good["correct"] is True
    assert good["invented_numbers"] == [] and good["missing_mentions"] == []
    assert good["unsupported_count"] == 0
    assert good["originality_pass"] is True

    bad = ROLE_EVAL.score(
        "draft",
        case,
        None,
        _raw_draft("Нов кабинет", "Кабинетът приема от 5 ноември, 300 деца."),
        10,
        True,
    )
    assert bad["correct"] is False
    assert "300" in bad["invented_numbers"] and "5" in bad["invented_numbers"]
    assert "1 октомври" in bad["missing_mentions"]

    missing = ROLE_EVAL.score(
        "draft",
        case,
        None,
        _raw_draft("Друго", "Съвсем друго съобщение без нужните факти."),
        10,
        True,
    )
    assert missing["correct"] is False
    assert "кабинет" in missing["missing_mentions"]

    # deterministic audit: sentences with no evidence overlap are UNSUPPORTED
    unsupported = ROLE_EVAL.score(
        "draft",
        case,
        None,
        _raw_draft(
            "Кабинет",
            "Община Бургас открива кабинет. "
            "Общината ще финансира ремонта със собствени средства тази година.",
        ),
        10,
        True,
    )
    assert unsupported["unsupported_count"] >= 1

    # originality guard: verbatim source prose is a REVIEW warning (warns,
    # never blocks — same as production), not a scoring reject
    copying = ROLE_EVAL.score(
        "draft",
        case,
        None,
        _raw_draft(
            "Безплатен кабинет за деца с диабет",
            "Община Бургас открива безплатен кабинет за деца с диабет в ДКЦ-1. "
            "Кабинетът приема от 1 октомври всеки работен ден.",
        ),
        10,
        True,
    )
    assert copying["originality_pass"] is False
    assert copying["originality_longest_run"] >= 8
    assert copying["correct"] is True  # facts covered — warning only

    broken = ROLE_EVAL.score("draft", case, None, "не е JSON", 10, True)
    assert broken["valid"] is False and "parse_draft_json" in broken["detail"]


def test_missing_style_assets_fail_the_case_before_any_model_call(monkeypatch, tmp_path):
    cases = ROLE_EVAL.load_cases("draft")  # real fixture, no injected assets
    monkeypatch.setattr(ROLE_EVAL, "load_cases", lambda role: cases)

    def boom(*_args, **_kwargs):
        raise ROLE_EVAL.EvalAssetsError("липсват стилови активи (тест)")

    monkeypatch.setattr(ROLE_EVAL, "load_draft_assets", boom)

    def explode(*_args, **_kwargs):
        pytest.fail("no model call may happen when style assets are missing")

    policy = ROLE_EVAL.model_policy.load_policy()
    report = ROLE_EVAL.run_role(
        "draft", policy=policy, limit=1, out_dir=tmp_path, call_role=explode
    )
    rows = report["candidates"][0]["rows"]
    assert rows and all(row["ok"] is False for row in rows)
    assert all("липсват стилови активи" in row["detail"] for row in rows)


def test_draft_run_writes_the_human_review_sheet(monkeypatch, tmp_path):
    cases = _draft_cases()
    monkeypatch.setattr(ROLE_EVAL, "load_cases", lambda role: cases)
    prompts_seen = []

    def fake_call_role(role, prompt, **kwargs):
        prompts_seen.append(prompt)
        return (
            _raw_draft(
                "В ДКЦ-1 отваря безплатен кабинет за деца с диабет",
                "В Бургас отваря безплатен кабинет за деца с диабет. "
                "Приемът в ДКЦ-1 е от 1 октомври, всеки работен ден. "
                "За деца до 18 години услугата остава безплатна.",
            ),
            {"model": "m"},
        )

    policy = ROLE_EVAL.model_policy.load_policy()
    report = ROLE_EVAL.run_role(
        "draft", policy=policy, limit=1, out_dir=tmp_path, call_role=fake_call_role
    )
    assert prompts_seen and all("STYLE_EXAMPLES" in p for p in prompts_seen)
    sheet = tmp_path / "draft_human_review.md"
    assert sheet.exists()
    assert report["human_review_sheet"] == str(sheet)
    text = sheet.read_text(encoding="utf-8")
    # the promotion fields are blank ON PURPOSE — a human fills them, never a model
    assert "Bulgarian naturalness: ___" in text
    assert "headline quality: ___" in text
    assert "Chernomorie fit: ___" in text
    assert "editing needed: ___" in text
    assert "notes: ___" in text
    assert "В ДКЦ-1 отваря безплатен кабинет" in text  # the candidate headline
    assert "auto:" in text  # deterministic checks are shown alongside
    rows = report["candidates"][0]["rows"]
    assert all(row.get("headline") for row in rows if row["valid"])
    assert report["candidates"][0]["summary"]["originality_warnings"] == 0


def test_semantic_gate_runs_only_when_explicitly_requested(monkeypatch, tmp_path):
    cases = _draft_cases()
    monkeypatch.setattr(ROLE_EVAL, "load_cases", lambda role: cases)

    def fake_call_role(role, prompt, **kwargs):
        return (
            _raw_draft(
                "Кабинет за деца с диабет",
                "В Бургас отваря безплатен кабинет за деца с диабет. "
                "Приемът в ДКЦ-1 е от 1 октомври, всеки работен ден. "
                "За деца до 18 години услугата остава безплатна.",
            ),
            {"model": "m"},
        )

    def explode_judge(*_args, **_kwargs):
        pytest.fail("the semantic gate must not run by default")

    policy = ROLE_EVAL.model_policy.load_policy()
    report = ROLE_EVAL.run_role(
        "draft",
        policy=policy,
        limit=1,
        out_dir=tmp_path,
        call_role=fake_call_role,
        semantic_judge=explode_judge,
    )
    assert all(
        "semantic_gate" not in row
        for candidate in report["candidates"]
        for row in candidate["rows"]
    )

    calls = []

    def judge(packet, body, **kwargs):
        calls.append(body)
        return {"pass": False}

    report = ROLE_EVAL.run_role(
        "draft",
        policy=policy,
        limit=1,
        out_dir=tmp_path,
        call_role=fake_call_role,
        semantic_gate=True,
        semantic_judge=judge,
    )
    rows = report["candidates"][0]["rows"]
    assert calls and all(row["semantic_gate"] == "FACTUAL_GATE_REVIEW" for row in rows)
    assert report["candidates"][0]["summary"]["semantic_reviews"] == len(rows)


# ---------------------------------------------------------------- research / extract / utility (I5/I6)


def test_research_reports_production_wiring_not_implemented(tmp_path):
    def fake_call_role(role, prompt, **kwargs):
        return json.dumps({"questions": ["Кой ще финансира линията?"]}, ensure_ascii=False), {
            "model": "m"
        }

    policy = ROLE_EVAL.model_policy.load_policy()
    report = ROLE_EVAL.run_role(
        "research", policy=policy, limit=2, out_dir=tmp_path, call_role=fake_call_role
    )
    assert report["wiring"] == ROLE_EVAL.RESEARCH_ROLE_PRODUCTION_WIRING == "NOT_IMPLEMENTED"
    assert report["RESEARCH_ROLE_PRODUCTION_WIRING"] == "NOT_IMPLEMENTED"
    assert "production квалификация" in report["note"]
    rendered = ROLE_EVAL.render(report)
    assert "RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED" in rendered
    assert "wiring: NOT_IMPLEMENTED" in rendered


def test_extract_and_utility_report_not_evaluated(tmp_path):
    policy = ROLE_EVAL.model_policy.load_policy()
    for role in ("extract", "utility"):
        report = ROLE_EVAL.run_role(role, policy=policy, out_dir=tmp_path)
        assert report["wiring"] == "NOT_EVALUATED"
        assert report["candidates"] == []
        assert "няма фикстура" in report["note"]
        assert "NOT_EVALUATED" in ROLE_EVAL.render(report)


# ---------------------------------------------------------------- paid guard (I7)


def test_run_role_refuses_paid_candidates_without_the_explicit_opt_in(tmp_path):
    policy = ROLE_EVAL.model_policy.load_policy()

    def explode(*_args, **_kwargs):
        pytest.fail("no model call without paid opt-in")

    # no --limit: the draft role's paid fallback is among the candidates
    with pytest.raises(ROLE_EVAL.EvalPaidError):
        ROLE_EVAL.run_role("draft", policy=policy, out_dir=tmp_path, call_role=explode)


def test_main_paid_guard_refuses_without_allow_paid_and_runs_with_it(monkeypatch, capsys):
    def explode(*_args, **_kwargs):
        pytest.fail("run must not start without --allow-paid")

    monkeypatch.setattr(ROLE_EVAL, "run_role", explode)
    with pytest.raises(SystemExit) as excinfo:
        ROLE_EVAL.main(["--role", "draft"])
    assert excinfo.value.code == 2
    assert "allow-paid" in capsys.readouterr().err

    calls = []

    def stub(role, **kwargs):
        calls.append(role)
        assert kwargs["allow_paid"] is True  # the opt-in is threaded through
        return {"role": role, "wiring": ROLE_EVAL.WIRING[role], "candidates": []}

    monkeypatch.setattr(ROLE_EVAL, "run_role", stub)
    assert ROLE_EVAL.main(["--role", "draft", "--allow-paid"]) == 0
    assert calls == ["draft"]


# ---------------------------------------------------------------- runner plumbing


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
    assert written["wiring"] == "PRODUCTION_FAITHFUL"
