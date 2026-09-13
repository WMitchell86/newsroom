"""M1.6 poll tests: orchestration, counts, idempotency, failures. Offline only."""

from __future__ import annotations

import pathlib
import sqlite3
from datetime import datetime, timezone

import pytest

import editor_assistant.poll as poll_mod
from editor_assistant.notify.outbox import list_pending
from editor_assistant.sources.fetcher import FetchError
from editor_assistant.sources.rss import SourceParseError
from editor_assistant.state.store import TELEGRAM_TEST_DESTINATION

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "rss_burgas_municipality.xml"
FIXTURE_BYTES = FIXTURE.read_bytes()
T0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)

EMPTY_CHANNEL = (
    b"<?xml version='1.0' encoding='UTF-8'?>"
    b"<rss version='2.0'><channel><title>empty</title></channel></rss>"
)
BROKEN_XML = b"<rss><channel><item><title>broken"


class _Fetched:
    def __init__(self, payload: bytes):
        self.payload = payload


def test_order_fetch_parse_state(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_fetch(url, **k):
        calls.append("fetch:" + url)
        return _Fetched(FIXTURE_BYTES)

    def fake_parse(payload, *, source, fetched_at):
        calls.append("parse")
        assert payload == FIXTURE_BYTES
        from editor_assistant.sources.rss import parse_rss_feed as real

        return real(payload, source=source, fetched_at=fetched_at)

    def fake_process(items, observed, *, db_path, destination):
        calls.append("state:" + str(destination))
        assert destination == TELEGRAM_TEST_DESTINATION
        from editor_assistant.state.store import process_items as real

        return real(items, observed, db_path=db_path, destination=destination)

    monkeypatch.setattr(poll_mod, "fetch_bytes", fake_fetch)
    monkeypatch.setattr(poll_mod, "parse_rss_feed", fake_parse)
    monkeypatch.setattr(poll_mod, "process_items", fake_process)
    report = poll_mod.poll_once(db_path=tmp_path / "p.sqlite3")
    assert calls[0].startswith("fetch:")
    assert calls[1] == "parse"
    assert calls[2] == "state:telegram-test"
    assert report.status == "OK" and report.fetched == 2 and report.parsed == 2


def test_new_creates_intent(tmp_path, monkeypatch):
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    report = poll_mod.poll_once(db_path=tmp_path / "p.sqlite3")
    assert (report.new_count, report.updated_count, report.unchanged_count) == (2, 0, 0)
    assert report.new_outbox_intents == 2
    assert report.pending_total == 2
    db = tmp_path / "p.sqlite3"
    assert len(list_pending(db, destination=TELEGRAM_TEST_DESTINATION)) == 2


def test_updated_creates_intent(tmp_path, monkeypatch):
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    db = tmp_path / "p.sqlite3"
    poll_mod.poll_once(db_path=db)
    text = FIXTURE.read_text(encoding="utf-8")
    first_title = "Почистване на плажната ивица след летния сезон"
    changed = text.replace(first_title, first_title + " v2", 1).encode("utf-8")
    _patch_fetch(monkeypatch, changed)
    report2 = poll_mod.poll_once(db_path=db)
    assert report2.updated_count == 1 and report2.new_count == 0
    assert report2.new_outbox_intents == 1
    assert report2.pending_total == 3


def test_unchanged_creates_none(tmp_path, monkeypatch):
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    db = tmp_path / "p.sqlite3"
    poll_mod.poll_once(db_path=db)
    report2 = poll_mod.poll_once(db_path=db)
    assert (report2.new_count, report2.updated_count, report2.unchanged_count) == (0, 0, 2)
    assert report2.new_outbox_intents == 0
    assert report2.pending_total == 2


def test_multiple_results_counted(tmp_path, monkeypatch):
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    report = poll_mod.poll_once(db_path=tmp_path / "p.sqlite3")
    assert report.new_count + report.updated_count + report.unchanged_count == 2
    assert report.fetched == report.parsed == 2


def test_report_counts_deterministic(tmp_path, monkeypatch):
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    report = poll_mod.poll_once(db_path=tmp_path / "p.sqlite3")
    text = poll_mod.format_report(report)
    assert "source: burgas-municipal-council" in text
    assert "fetched: 2" in text and "parsed: 2" in text
    assert "NEW: 2" in text and "status: OK" in text
    assert poll_mod.format_report(report) == text


def test_pending_total_reported(tmp_path, monkeypatch):
    from editor_assistant.notify.outbox import mark_delivered

    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    db = tmp_path / "p.sqlite3"
    r1 = poll_mod.poll_once(db_path=db)
    assert r1.pending_total == 2
    rows = list_pending(db, destination=TELEGRAM_TEST_DESTINATION)
    mark_delivered(db, rows[0].id, T0)
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    r2 = poll_mod.poll_once(db_path=db)
    assert r2.pending_total == 1
    assert r2.new_outbox_intents == 0


def test_network_failure_no_state(tmp_path, monkeypatch, capsys):
    def boom(url, **k):
        raise FetchError("simulated timeout")

    monkeypatch.setattr(poll_mod, "fetch_bytes", boom)
    db = tmp_path / "p.sqlite3"
    with pytest.raises(FetchError):
        poll_mod.poll_once(db_path=db)
    assert _state_rows(db) == 0
    assert poll_mod.main(["--db", str(db)]) == 1
    out = capsys.readouterr().out
    assert "status: ERROR" in out and "fetch failed" in out
    assert _state_rows(db) == 0


def test_parse_failure_no_state(tmp_path, monkeypatch, capsys):
    _patch_fetch(monkeypatch, BROKEN_XML)
    db = tmp_path / "p.sqlite3"
    with pytest.raises(SourceParseError):
        poll_mod.poll_once(db_path=db)
    assert _state_rows(db) == 0
    assert poll_mod.main(["--db", str(db)]) == 1
    out = capsys.readouterr().out
    assert "status: ERROR" in out and "parse failed" in out


def test_database_failure_surfaced(tmp_path, monkeypatch, capsys):
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    db = tmp_path / "p.sqlite3"

    def boom(items, observed, *, db_path, destination):
        raise sqlite3.OperationalError("simulated db failure")

    monkeypatch.setattr(poll_mod, "process_items", boom)
    with pytest.raises(sqlite3.OperationalError):
        poll_mod.poll_once(db_path=db)
    assert poll_mod.main(["--db", str(db)]) == 1
    out = capsys.readouterr().out
    assert "status: ERROR" in out and "database failed" in out


def test_empty_valid_feed_ok(tmp_path, monkeypatch):
    _patch_fetch(monkeypatch, EMPTY_CHANNEL)
    db = tmp_path / "p.sqlite3"
    report = poll_mod.poll_once(db_path=db)
    assert (report.fetched, report.parsed) == (0, 0)
    assert (report.new_count, report.updated_count, report.unchanged_count) == (0, 0, 0)
    assert report.new_outbox_intents == 0 and report.status == "OK"
    assert "status: OK" in poll_mod.format_report(report)
    assert _state_rows(db) == 0


def test_telegram_never_called(tmp_path, monkeypatch):
    import editor_assistant.notify.telegram as tg

    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    monkeypatch.setattr(
        tg, "send_message", lambda *a, **k: (_ for _ in ()).throw(AssertionError("x"))
    )
    src = pathlib.Path(poll_mod.__file__).read_text(encoding="utf-8")
    assert "send_message" not in src
    assert "notify.telegram" not in src
    poll_mod.poll_once(db_path=tmp_path / "p.sqlite3")


def test_repeated_unchanged_no_duplicates(tmp_path, monkeypatch):
    _patch_fetch(monkeypatch, FIXTURE_BYTES)
    db = tmp_path / "p.sqlite3"
    r1 = poll_mod.poll_once(db_path=db)
    r2 = poll_mod.poll_once(db_path=db)
    assert (r2.new_count, r2.updated_count, r2.unchanged_count) == (0, 0, 2)
    assert r2.new_outbox_intents == 0
    assert r2.pending_total == r1.pending_total == 2


def test_no_send_flag():
    with pytest.raises(SystemExit):
        poll_mod.main(["--send"])
    src = pathlib.Path(poll_mod.__file__).read_text(encoding="utf-8")
    assert "poll-and-send" not in src
    assert "--feed-url" in src  # only supported flags are --db / --feed-url


def test_uses_live_source_only():
    from editor_assistant.sources.live import BURGAS_MUNICIPAL_COUNCIL, LIVE_FEED_URL

    assert BURGAS_MUNICIPAL_COUNCIL.source_id == "burgas-municipal-council"
    assert LIVE_FEED_URL == "https://burgascouncil.org/last-update.xml"
    src = pathlib.Path(poll_mod.__file__).read_text(encoding="utf-8")
    assert "LIVE_FEED_URL" in src and "BURGAS_MUNICIPAL_COUNCIL" in src


def _patch_fetch(monkeypatch, payload: bytes):
    monkeypatch.setattr(poll_mod, "fetch_bytes", lambda url, **k: _Fetched(payload))


def _state_rows(db):
    with sqlite3.connect(db) as conn:
        try:
            return conn.execute("SELECT COUNT(*) FROM item_state").fetchone()[0]
        except sqlite3.Error:
            return 0
