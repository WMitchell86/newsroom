"""M3A A3: one canonical live-evidence store (`workflow/live_store.py`).

Regression coverage: upsert semantics, deterministic bytes/order, atomic
write behavior on serialization failure, and that both the CLI and the
Workbench read/write the same shared implementation.
"""

import json

import pytest

from editor_assistant.workflow import cli, live_store
from editor_assistant.workflow.workbench import state as wb_state


def _row(evidence_id, **extra):
    return {"evidence_id": evidence_id, "idea_id": f"I-{evidence_id}", **extra}


def test_missing_store_reads_empty(tmp_path):
    assert live_store.read_live_evidence(tmp_path / "nope.jsonl") == {}


def test_add_and_update_rows_keep_schema(tmp_path):
    path = tmp_path / "live.jsonl"
    live_store.save_live_evidence_row(_row("EV-B", facts=["x"]), path)
    live_store.save_live_evidence_row(_row("EV-A"), path)
    live_store.save_live_evidence_row(_row("EV-B", facts=["x", "y"]), path)

    rows = live_store.read_live_evidence(path)
    assert set(rows) == {"EV-A", "EV-B"}
    assert rows["EV-B"]["facts"] == ["x", "y"]  # update wins, no duplicate line
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_output_bytes_are_deterministic_and_sorted(tmp_path):
    path = tmp_path / "live.jsonl"
    for ev in ("EV-C", "EV-A", "EV-B"):
        live_store.save_live_evidence_row(_row(ev, nested={"b": 2, "a": 1}), path)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["evidence_id"] for line in lines] == ["EV-A", "EV-B", "EV-C"]
    assert lines[0] == json.dumps(
        _row("EV-A", nested={"b": 2, "a": 1}), ensure_ascii=False, sort_keys=True
    )


def test_serialization_failure_does_not_truncate_store(tmp_path):
    path = tmp_path / "live.jsonl"
    live_store.save_live_evidence_row(_row("EV-A", facts=["keep"]), path)
    before = path.read_bytes()

    with pytest.raises(TypeError):
        live_store.save_live_evidence_row(_row("EV-B", bad={object()}), path)

    assert path.read_bytes() == before  # untouched, not emptied
    assert live_store.read_live_evidence(path)["EV-A"]["facts"] == ["keep"]


def test_reader_tolerates_missing_file_and_non_row_blank_lines(tmp_path):
    path = tmp_path / "live.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    assert live_store.read_live_evidence(path) == {}


def test_cli_and_workbench_share_one_writer(tmp_path, monkeypatch):
    """Both surfaces must read/write the same store through the shared module."""
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "LIVE_EVIDENCE_PATH", tmp_path / "live_evidence.jsonl")

    # CLI writes -> Workbench sees it
    cli._save_live_row(_row("EV-CLI", who="cli"))
    assert wb_state._live_evidence_rows()["EV-CLI"]["who"] == "cli"

    # Workbench writes -> CLI sees it, one line per row
    wb_state._live_evidence_save(_row("EV-WB", who="workbench"))
    rows = cli._live_rows()
    assert rows["EV-WB"]["who"] == "workbench"
    assert set(rows) == {"EV-CLI", "EV-WB"}
    assert len(cli.LIVE_EVIDENCE_PATH.read_text(encoding="utf-8").strip().splitlines()) == 2
