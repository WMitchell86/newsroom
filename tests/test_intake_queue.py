"""M3B.1 offline tests: the operational intake queue (no network, no sleeps)."""

import json

from editor_assistant.workflow import intake_queue as Q
from editor_assistant.workflow import youtube_policy as P

VID = "dQw4w9WgXcQ"
OTHER = "abcdefghijk"


def _queue():
    return {"entries": {}}


def test_equivalent_url_forms_queue_as_one_entry(tmp_path):
    queue = _queue()
    first, added_first = Q.add_url(queue, f"https://youtu.be/{VID}", now="2026-01-01T00:00:00Z")
    second, added_second = Q.add_url(
        queue, f"https://www.youtube.com/watch?v={VID}&t=9s", now="2026-01-01T00:01:00Z"
    )
    assert added_first is True and added_second is False
    assert first["key"] == second["key"] == VID
    assert len(queue["entries"]) == 1
    Q.save_queue(queue, root=tmp_path)
    assert Q.read_queue(root=tmp_path)["entries"][VID]["video_id"] == VID


def test_a_non_youtube_url_is_recorded_but_never_becomes_a_request(tmp_path):
    queue = _queue()
    entry, added = Q.add_url(queue, "https://example.com/article", now="2026-01-01T00:00:00Z")
    assert added is True
    assert entry["status"] == Q.STATUS_INVALID_URL
    assert entry["video_id"] is None
    assert Q.due_entries(queue, 10, now="2026-01-01T00:00:00Z") == []


def test_re_adding_a_parked_entry_revives_it():
    queue = _queue()
    entry, _ = Q.add_url(queue, f"https://youtu.be/{VID}")
    Q.record_failure(queue, entry["key"], category="TRANSCRIPTION_FAILED", max_attempts=1)
    assert entry["status"] == Q.STATUS_BLOCKED

    revived, added = Q.add_url(queue, f"https://youtu.be/{VID}")
    assert added is True
    assert revived["status"] == Q.STATUS_PENDING
    assert revived["attempts"] == 0


def test_due_entries_respect_backoff_and_cap():
    queue = _queue()
    one, _ = Q.add_url(queue, f"https://youtu.be/{VID}", now="2026-01-01T00:00:00Z")
    two, _ = Q.add_url(queue, f"https://youtu.be/{OTHER}", now="2026-01-01T00:05:00Z")

    Q.record_failure(queue, one["key"], category="TRANSCRIPTION_FAILED", now="2026-01-01T01:00:00Z")
    # 15 minutes later the first entry is still cooling down.
    due = Q.due_entries(queue, 10, now="2026-01-01T01:10:00Z")
    assert [e["key"] for e in due] == [two["key"]]
    # After the cooldown both are due; the not-yet-ready entry sorts by its
    # readiness time, so the never-attempted one goes first.
    due = Q.due_entries(queue, 10, now="2026-01-01T02:00:00Z")
    assert [e["key"] for e in due] == [two["key"], one["key"]]
    assert len(Q.due_entries(queue, 1, now="2026-01-01T02:00:00Z")) == 1


def test_backoff_grows_with_each_attempt():
    queue = _queue()
    entry, _ = Q.add_url(queue, f"https://youtu.be/{VID}", now="2026-01-01T00:00:00Z")
    seen = []
    for attempt in range(1, 5):
        moment = f"2026-01-01T0{attempt}:00:00Z"
        Q.record_failure(queue, entry["key"], category="TRANSCRIPTION_FAILED", now=moment)
        seen.append(entry["next_attempt_at"])
    assert seen == sorted(seen)  # monotonically later
    assert entry["attempts"] == 4


def test_exhausted_retry_budget_parks_the_entry():
    queue = _queue()
    entry, _ = Q.add_url(queue, f"https://youtu.be/{VID}")
    for _ in range(3):
        status = Q.record_failure(
            queue, entry["key"], category="TRANSCRIPTION_FAILED", max_attempts=3
        )
    assert status == Q.STATUS_BLOCKED
    assert entry["next_attempt_at"] is None
    assert Q.due_entries(queue, 10) == []


def test_permanent_categories_are_parked_without_burning_retries():
    queue = _queue()
    entry, _ = Q.add_url(queue, f"https://youtu.be/{VID}")
    Q.record_failure(queue, entry["key"], category="TRANSCRIPT_EMPTY", permanent=True)
    assert entry["status"] == Q.STATUS_NO_CAPTIONS
    assert entry["next_attempt_at"] is None

    other, _ = Q.add_url(queue, f"https://youtu.be/{OTHER}")
    Q.record_failure(queue, other["key"], category="TRANSCRIPT_UNAVAILABLE", permanent=True)
    assert other["status"] == Q.STATUS_UNAVAILABLE


def test_reset_revives_parked_entries_only_on_request():
    queue = _queue()
    blocked, _ = Q.add_url(queue, f"https://youtu.be/{VID}")
    nocaps, _ = Q.add_url(queue, f"https://youtu.be/{OTHER}")
    Q.record_failure(queue, blocked["key"], category="TRANSCRIPTION_FAILED", permanent=True)
    Q.record_failure(queue, nocaps["key"], category="TRANSCRIPT_EMPTY", permanent=True)

    assert Q.reset(queue) == [blocked["key"]]
    assert blocked["status"] == Q.STATUS_PENDING
    assert nocaps["status"] == Q.STATUS_NO_CAPTIONS
    # no_captions entries are only revived when explicitly asked for
    assert Q.reset(queue, include_no_captions=True) == [nocaps["key"]]
    assert nocaps["status"] == Q.STATUS_PENDING


def test_success_clears_the_failure_state():
    queue = _queue()
    entry, _ = Q.add_url(queue, f"https://youtu.be/{VID}")
    Q.record_failure(queue, entry["key"], category="TRANSCRIPTION_FAILED")
    Q.record_success(queue, entry["key"], now="2026-01-02T00:00:00Z")
    assert entry["status"] == Q.STATUS_DONE
    assert entry["last_error"] is None and entry["next_attempt_at"] is None


def test_summarize_counts_every_state():
    queue = _queue()
    Q.add_url(queue, f"https://youtu.be/{VID}")
    parked, _ = Q.add_url(queue, f"https://youtu.be/{OTHER}")
    Q.record_failure(queue, parked["key"], category="TRANSCRIPT_EMPTY", permanent=True)
    Q.add_url(queue, "https://example.com/x")
    counts = Q.summarize(queue)
    assert counts["pending"] == 1
    assert counts["no_captions"] == 1
    assert counts["invalid_url"] == 1
    assert counts["total"] == 3


def test_registry_and_queue_share_one_runtime_root(tmp_path):
    assert Q.queue_root(tmp_path) == tmp_path
    assert Q.runs_path(tmp_path).parent == tmp_path


def test_a_corrupt_queue_file_reads_as_empty_instead_of_crashing(tmp_path):
    Q.queue_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert Q.read_queue(root=tmp_path) == {"entries": {}}


def test_run_log_is_append_only_and_bounded_on_read(tmp_path):
    for index in range(7):
        Q.append_run({"exit_code": 0, "note": f"run {index}"}, root=tmp_path)
    records = Q.recent_runs(root=tmp_path, limit=3)
    assert [r["note"] for r in records] == ["run 4", "run 5", "run 6"]
    assert len(Q.runs_path(tmp_path).read_text(encoding="utf-8").splitlines()) == 7


def test_saved_queue_is_deterministic_json(tmp_path):
    queue = _queue()
    Q.add_url(queue, f"https://youtu.be/{VID}")
    Q.save_queue(queue, root=tmp_path)
    first = Q.queue_path(tmp_path).read_text(encoding="utf-8")
    Q.save_queue(Q.read_queue(root=tmp_path), root=tmp_path)
    assert Q.queue_path(tmp_path).read_text(encoding="utf-8") == first
    assert json.loads(first)["entries"][VID]["status"] == "pending"


def test_an_invalid_url_parks_as_invalid_not_as_blocked():
    """An unmapped permanent category would silently become a retryable state."""
    queue = _queue()
    entry, _ = Q.add_url(queue, f"https://youtu.be/{VID}")
    status = Q.record_failure(queue, entry["key"], category="INVALID_YOUTUBE_URL", permanent=True)
    assert status == Q.STATUS_INVALID_URL
    assert entry["status"] == Q.STATUS_INVALID_URL


def test_an_explicit_delay_overrides_the_backoff_ladder():
    """A circuit breaker must wait for the IP cooldown, not 15 minutes."""
    queue = _queue()
    entry, _ = Q.add_url(queue, f"https://youtu.be/{VID}")
    Q.record_failure(
        queue,
        entry["key"],
        category="TRANSCRIBER_BLOCKED",
        now="2026-01-01T00:00:00Z",
        delay_seconds=12 * 3600,
    )
    assert entry["next_attempt_at"] == "2026-01-01T12:00:00Z"
    assert Q.due_entries(queue, 10, now="2026-01-01T11:00:00Z") == []
    assert len(Q.due_entries(queue, 10, now="2026-01-01T13:00:00Z")) == 1


def test_backoff_ladder_comes_from_the_policy_module():
    assert P.backoff_seconds(1) == P.BACKOFF_SECONDS[0]
