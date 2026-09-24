"""CLI integration: temporary stores, offline model, no production pilot metrics."""

import json

import pytest

from editor_assistant.workflow import cases, cli, live
from editor_assistant.workflow.ideas import save_ideas


@pytest.fixture
def intake(tmp_path, monkeypatch):
    for name, filename in (
        ("IDEAS_PATH", "ideas.jsonl"),
        ("LIVE_EVIDENCE_PATH", "evidence.jsonl"),
        ("LIVE_DRAFTS_PATH", "drafts.jsonl"),
        ("CASES_PATH", "cases.jsonl"),
    ):
        monkeypatch.setattr(cli, name, tmp_path / filename)
    url = "https://official.example/event"
    idea = live.new_idea(
        source_type="organizer", source_url=url, title="Event", what_changed="New event"
    )
    save_ideas([idea], cli.IDEAS_PATH)
    packet = {
        "evidence_id": "EV-T",
        "source_url": url,
        "source_headline": "Event",
        "source_text": "Event in Burgas.",
        "facts": [{"id": "F1", "text": "Бургас приема ново събитие на 1 октомври в зала Съюз."}],
        "dates": ["2026-10-01"],
        "places": ["Бургас"],
        "quotes": [],
        "unknowns": [],
    }
    cli._save_live_row({"evidence_id": "EV-T", "idea_id": idea["idea_id"], "packet": packet})
    calls = []

    def generate(packet, *, voice, mode, api_key, force_draft=False, editor_override_reason=None):
        calls.append(packet)
        return {
            "draft": {"headline": "Event", "body": "Event in Burgas."},
            "lineage": {
                "draft_id": "test-draft",
                "evidence_id": "EV-T",
                "voice_id": voice,
                "mode_id": mode,
                "prompt_version": "test",
            },
            "lexical": {},
            "semantic": {"pass": False, "n_unsupported": 1},
            "factual_gate": "FACTUAL_GATE_REVIEW",
            "readiness": {"status": "DRAFT_READY"},
            "retrieval": {"examples": []},
        }

    monkeypatch.setattr(live, "live_generate_draft", generate)
    cli.main(["live-case", "EV-T", "--idea", idea["idea_id"], "--mode", "MODE_BRIEF"])
    return calls


def test_live_cli_persists_gate_lineage_and_fixed_case_id(intake):
    cli.main(["live-generate", "EV-T", "--case-id", "LIV-02"])
    stored = cases.read_cases(cli.CASES_PATH)
    draft = json.loads(cli.LIVE_DRAFTS_PATH.read_text(encoding="utf-8"))
    assert len(intake) == 1
    assert stored[0]["case_id"] == "LIV-02"
    assert stored[0]["factual_gate"] == "FACTUAL_GATE_REVIEW"
    assert stored[0]["audit"]["semantic"]["n_unsupported"] == 1
    assert stored[0]["lineage"] == draft["lineage"]
    assert stored[0]["final_text"] == ""


def test_live_cli_duplicate_attempt_is_rejected_before_model_or_writes(intake):
    cli.main(["live-generate", "EV-T", "--case-id", "LIV-02"])
    before = cli.LIVE_DRAFTS_PATH.read_bytes(), cli.CASES_PATH.read_bytes()
    with pytest.raises(SystemExit, match="already"):
        cli.main(["live-generate", "EV-T", "--case-id", "LIV-02"])
    assert len(intake) == 1
    assert (cli.LIVE_DRAFTS_PATH.read_bytes(), cli.CASES_PATH.read_bytes()) == before


def test_live_case_cli_refuses_a_closed_idea_and_changes_nothing(tmp_path, monkeypatch):
    """G2 parity: the CLI runs the SAME canonical guard as the Workbench —
    an editor-rejected idea can no longer be revived by preparing its case."""
    for name, filename in (
        ("IDEAS_PATH", "ideas.jsonl"),
        ("LIVE_EVIDENCE_PATH", "evidence.jsonl"),
        ("LIVE_DRAFTS_PATH", "drafts.jsonl"),
        ("CASES_PATH", "cases.jsonl"),
    ):
        monkeypatch.setattr(cli, name, tmp_path / filename)
    idea = live.new_idea(
        source_type="organizer",
        source_url="https://official.example/event",
        title="Event",
        what_changed="New event",
    )
    idea["status"] = "IGNORED"
    from editor_assistant.workflow.ideas import validate_idea

    validate_idea(idea)
    save_ideas([idea], cli.IDEAS_PATH)
    packet = {
        "evidence_id": "EV-T",
        "source_url": "https://official.example/event",
        "source_headline": "Event",
        "facts": [{"id": "F1", "text": "Бургас приема ново събитие на 1 октомври."}],
        "quotes": [],
        "unknowns": [],
    }
    cli._save_live_row({"evidence_id": "EV-T", "idea_id": idea["idea_id"], "packet": packet})
    before_ideas = cli.IDEAS_PATH.read_bytes()

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["live-case", "EV-T", "--idea", idea["idea_id"]])
    assert "IGNORED" in str(exit_info.value)
    # Refusal leaves every store byte-identical: no prepared row, no rewrite.
    assert cli.IDEAS_PATH.read_bytes() == before_ideas
    assert "prepared" not in cli._live_rows()["EV-T"]
    assert not cli.CASES_PATH.exists() and not cli.LIVE_DRAFTS_PATH.exists()
