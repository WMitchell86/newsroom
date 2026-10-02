"""Two days, then gone — the retention bound on both audit stores.

Owner decision (dev mode, 2026-10-01): keep the prompt log and the research
trace for **two days max**. These tests pin the three rules the module
docstring claims, because the routine is destructive: a rule that fails here
is a rule that silently deletes an operator's debugging trail.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from editor_assistant import store_retention
from editor_assistant.drafting import model_prompt_log
from editor_assistant.workflow import research_trace

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _stamped(stamp: str, **extra) -> str:
    return json.dumps({"at": stamp, "role": "draft", **extra}, ensure_ascii=False)


def _write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _counts(path):
    # Tolerates an unparseable line on purpose: one test writes a deliberately
    # corrupt row to prove it is KEPT, and a strict json.loads here would fail
    # on the very row under test instead of counting it.
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append(line)
    return rows


def test_rows_older_than_two_days_are_dropped_and_recent_ones_survive(tmp_path):
    path = tmp_path / "store.jsonl"
    _write_lines(
        path,
        [
            _stamped((NOW - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), keep="old"),
            _stamped((NOW - timedelta(days=1, hours=23)).strftime("%Y-%m-%dT%H:%M:%SZ"), keep="fresh"),
            _stamped(NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), keep="now"),
        ],
    )

    dropped = store_retention.prune(path, now=NOW)

    assert dropped == 1, "only the 3-day-old row is outside the window"
    assert [row["keep"] for row in _counts(path)] == ["fresh", "now"]
    assert oct(path.stat().st_mode)[-3:] == "600", "the rewrite must keep the private mode"


def test_a_row_we_cannot_date_is_never_deleted(tmp_path):
    """Unknown age is not old age — deleting it would be an invented claim."""
    path = tmp_path / "store.jsonl"
    _write_lines(
        path,
        [
            json.dumps({"role": "draft", "prompt": "no at field"}),
            _stamped("not-a-timestamp"),
            "{this is not json at all",
            _stamped((NOW - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ],
    )

    dropped = store_retention.prune(path, now=NOW)

    assert dropped == 1, "only the row we could actually date is removed"
    assert len(_counts(path)) == 3


def test_a_failed_prune_never_loses_the_appended_row(tmp_path, monkeypatch):
    """Rule 2: append first, prune second — a prune crash must not eat the row.

    Sabotaged at the real rewrite helper, not at `maybe_prune`, so the guard
    under test is the one that runs in production.
    """
    monkeypatch.delenv("MODEL_PROMPT_LOG", raising=False)
    path = tmp_path / "editorial_workflow" / model_prompt_log.FILENAME
    # An expired row guarantees `prune` reaches the rewrite; without it the
    # file would already be inside the window, `dropped` would be 0 and the
    # sabotage would never run — the test would pass for the wrong reason.
    _write_lines(path, [_stamped((NOW - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ"))])
    monkeypatch.setattr(store_retention, "_atomic_write_private", _boom)

    record = model_prompt_log.record_sent_prompt(
        role="draft", provider="gemini", model="m", prompt_text="текст", root=tmp_path
    )

    assert record is not None, "the row was written; only the prune failed"
    prompts = [r.get("prompt") for r in model_prompt_log.read_sent_prompts(root=tmp_path)]
    assert "текст" in prompts, prompts


def test_the_prompt_log_write_path_prunes_its_own_old_rows(tmp_path, monkeypatch):
    """Integration: the store prunes itself without a caller asking."""
    monkeypatch.delenv("MODEL_PROMPT_LOG", raising=False)
    path = tmp_path / "editorial_workflow" / model_prompt_log.FILENAME
    _write_lines(
        path,
        [
            _stamped((NOW - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")),
            _stamped((NOW - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ],
    )
    assert store_retention.marker_path(path).exists() is False

    model_prompt_log.record_sent_prompt(
        role="draft", provider="gemini", model="m", prompt_text="нов ред", root=tmp_path
    )

    rows = model_prompt_log.read_sent_prompts(root=tmp_path)
    assert [r["prompt"] for r in rows] == ["нов ред"], rows
    assert oct(path.stat().st_mode)[-3:] == "600"
    assert oct(store_retention.marker_path(path).stat().st_mode)[-3:] == "600"


def test_the_research_trace_write_path_prunes_its_own_old_rows(tmp_path, monkeypatch):
    monkeypatch.delenv("RESEARCH_TRACE_PATH", raising=False)
    path = tmp_path / "editorial_workflow" / research_trace.FILENAME
    _write_lines(
        path,
        [_stamped((NOW - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ"))],
    )

    research_trace.record_page(
        story_id="s-one", url="https://x.test/a", outcome=research_trace.KEPT, root=tmp_path
    )

    rows = research_trace.read_trace(root=tmp_path)
    assert len(rows) == 1, "the 9-day-old row is gone, the fresh one stays"
    assert rows[0]["url"] == "https://x.test/a"
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_a_prune_runs_at_most_once_per_interval(tmp_path):
    """The throttle: a busy store must not rewrite on every single append."""
    path = tmp_path / "store.jsonl"
    old = _stamped((NOW - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _write_lines(path, [old])

    marker = store_retention.marker_path(path)
    marker.write_text("", encoding="utf-8")
    os.utime(marker, (NOW.timestamp(), NOW.timestamp()))  # pruned a minute ago

    assert store_retention.maybe_prune(path, now=NOW) == 0, "inside the interval: no rewrite"
    assert _counts(path), "the throttle must not have rewritten anything"

    os.utime(marker, (NOW.timestamp() - 7200, NOW.timestamp() - 7200))  # last prune 2 h ago
    assert store_retention.maybe_prune(path, now=NOW) == 1, "outside the interval: prune runs"
    assert _counts(path) == []


def test_retention_defaults_to_two_days():
    """The owner's number, asserted so it cannot drift without a test change."""
    assert store_retention.RETENTION_DAYS == 2


def _boom(*_args, **_kwargs):
    raise OSError("rewrite on fire")
