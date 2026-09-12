"""M1.4B delivery-runner tests — all offline, transport mocked (part 2)."""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

from editor_assistant.models import SourceDef
from editor_assistant.notify import telegram as tg
from editor_assistant.notify.outbox import list_pending
from editor_assistant.notify.render import build_payload, render_message
from editor_assistant.send_telegram import main as send_main
from editor_assistant.sources.rss import PARSER_ID, parse_rss_feed
from editor_assistant.state import process_items
from editor_assistant.state.store import TELEGRAM_TEST_DESTINATION

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "rss_burgas_municipality.xml"
SOURCE = SourceDef(
    source_id="burgas-municipality-press",
    canonical_url="https://www.burgas.bg/press",
    parser=PARSER_ID,
)
T0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)


def _items():
    return parse_rss_feed(FIXTURE.read_bytes(), source=SOURCE, fetched_at=T0)


def _seed(db, n=2):
    process_items(_items()[:n], T0, db_path=db, destination=TELEGRAM_TEST_DESTINATION)


def test_dry_run_default_no_http_no_deliver(tmp_path, capsys, monkeypatch):
    db = tmp_path / "t.sqlite3"
    _seed(db, 2)
    monkeypatch.delenv("TELEGRAM_TEST_BOT_TOKEN", raising=False)
    assert send_main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "🆕" in out
    assert len(list_pending(str(db))) == 2


def test_preview_uses_renderer_and_selects_one(tmp_path, capsys):
    db = tmp_path / "t.sqlite3"
    _seed(db, 2)
    assert send_main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "selected: 1" in out
    assert render_message(list_pending(str(db))[0].payload).strip() in out


def test_mock_success_limit1_marks_one(tmp_path, monkeypatch):
    db = tmp_path / "t.sqlite3"
    _seed(db, 2)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TELEGRAM_TEST_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_TEST_CHAT_ID", "C")
    import editor_assistant.send_telegram as sender

    monkeypatch.setattr(sender, "send_message", lambda cfg, text: tg.TelegramSendResult(7))
    assert send_main(["--db", str(db), "--send"]) == 0
    assert len(list_pending(str(db))) == 1


def test_mock_failure_leaves_pending(tmp_path, monkeypatch):
    db = tmp_path / "t.sqlite3"
    _seed(db, 2)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TELEGRAM_TEST_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_TEST_CHAT_ID", "C")
    import editor_assistant.send_telegram as sender

    def boom(cfg, text):
        raise tg.TelegramSendError("Telegram API error (URLError)")

    monkeypatch.setattr(sender, "send_message", boom)
    assert send_main(["--db", str(db), "--send"]) == 1
    assert len(list_pending(str(db))) == 2


def test_ordering_oldest_first_and_limit(tmp_path, monkeypatch, capsys):
    db = tmp_path / "t.sqlite3"
    _seed(db, 2)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TELEGRAM_TEST_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_TEST_CHAT_ID", "C")
    import editor_assistant.send_telegram as sender

    sent = []

    def ok(cfg, text):
        sent.append(text)
        return tg.TelegramSendResult(len(sent))

    monkeypatch.setattr(sender, "send_message", ok)
    assert send_main(["--db", str(db), "--send", "--limit", "2"]) == 0
    assert len(list_pending(str(db))) == 0 and len(sent) == 2
    assert capsys.readouterr().out.count("status: SENT") == 2


def test_limit_above_max_rejected(tmp_path):
    assert send_main(["--db", str(tmp_path / "t.sqlite3"), "--send", "--limit", "6"]) == 2


def test_send_gate_blocked_without_credentials(tmp_path, monkeypatch):
    """--send + DRY_RUN=false but no bot token/chat id -> clean refusal, no HTTP."""
    db = tmp_path / "t.sqlite3"
    _seed(db, 1)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.delenv("TELEGRAM_TEST_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_TEST_CHAT_ID", raising=False)
    assert send_main(["--db", str(db), "--send"]) == 2
    assert len(list_pending(str(db))) == 1


def test_normal_message_within_limit():
    payload = build_payload(_items()[0], event_type="NEW", version_no=1)
    assert 1 <= len(render_message(payload)) <= 4096
