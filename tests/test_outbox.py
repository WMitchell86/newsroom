"""M1.4A outbox tests: durable intents, payload, renderer, lifecycle, atomicity."""

from __future__ import annotations

import dataclasses
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from editor_assistant.models import SourceDef
from editor_assistant.notify.outbox import count_all, list_pending, mark_delivered
from editor_assistant.notify.render import (
    BODY_EXCERPT_LIMIT,
    build_payload,
    render_message,
)
from editor_assistant.sources.rss import PARSER_ID, parse_rss_feed
from editor_assistant.state import StateError, process_items
from editor_assistant.state.store import TELEGRAM_TEST_DESTINATION

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "rss_burgas_municipality.xml"
SOURCE = SourceDef(
    source_id="burgas-municipality-press",
    canonical_url="https://www.burgas.bg/press",
    parser=PARSER_ID,
)
T0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)


def _items():
    return parse_rss_feed(FIXTURE.read_bytes(), source=SOURCE, fetched_at=T0)


def _pending(db):
    return list_pending(db, destination=TELEGRAM_TEST_DESTINATION)


def test_new_creates_one_pending_row(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    rows = _pending(db)
    assert len(rows) == 1 and rows[0].pending
    assert (rows[0].event_type, rows[0].version_no) == ("NEW", 1)


def test_unchanged_creates_no_row(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    process_items(_items()[:1], T1, db_path=db)
    assert len(_pending(db)) == 1


def test_updated_creates_second_row(tmp_path):
    db = tmp_path / "o.sqlite3"
    (first,) = _items()[:1]
    process_items([first], T0, db_path=db)
    changed = dataclasses.replace(first, title=first.title + " v2")
    process_items([changed], T1, db_path=db)
    rows = _pending(db)
    assert [(r.event_type, r.version_no) for r in rows] == [("NEW", 1), ("UPDATED", 2)]


def test_repeated_processing_no_duplicates(tmp_path):
    db = tmp_path / "o.sqlite3"
    for _ in range(3):
        process_items(_items()[:1], T1, db_path=db)
    assert len(_pending(db)) == 1


def test_two_items_two_intents(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:2], T0, db_path=db)
    assert len(_pending(db)) == 2


def test_same_url_two_sources_independent(tmp_path):
    db = tmp_path / "o.sqlite3"
    a = _items()[0]
    process_items([a, dataclasses.replace(a, source_id="other")], T0, db_path=db)
    assert len(_pending(db)) == 2


def test_payload_event_type_and_url(tmp_path):
    db = tmp_path / "o.sqlite3"
    (first,) = _items()[:1]
    process_items([first], T0, db_path=db)
    (row,) = _pending(db)
    assert row.payload.event_type == "NEW"
    assert row.payload.item_url == first.item_url


def test_bulgarian_survives_serialization(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    (row,) = _pending(db)
    assert "Александровска" in row.payload.title
    assert "Бургас" in (row.payload.body_excerpt or "")


def test_excerpt_limit_deterministic(tmp_path):
    db = tmp_path / "o.sqlite3"
    long_body = "я" * (BODY_EXCERPT_LIMIT + 100)
    item = dataclasses.replace(_items()[0], body_text=long_body)
    payload = build_payload(item, event_type="NEW", version_no=1)
    assert len(payload.body_excerpt or "") <= BODY_EXCERPT_LIMIT + 1
    assert build_payload(item, event_type="NEW", version_no=1) == payload
    process_items(_items()[:1], T0, db_path=db)  # unrelated run unaffected
    assert len(_pending(db)) == 1


def test_links_preserve_order(tmp_path):
    db = tmp_path / "o.sqlite3"
    item = dataclasses.replace(_items()[0], body_links=("https://e.com/a", "https://e.com/b"))
    assert build_payload(item, event_type="NEW", version_no=1).body_links == (
        "https://e.com/a",
        "https://e.com/b",
    )
    process_items(_items()[:1], T0, db_path=db)
    assert _pending(db)[0].payload.body_links == ()


def test_missing_pubdate_explicit(tmp_path):
    item = dataclasses.replace(_items()[0], published_at=None)
    assert build_payload(item, event_type="NEW", version_no=1).published_at is None
    db = tmp_path / "o.sqlite3"
    process_items([item], T0, db_path=db)
    assert _pending(db)[0].payload.published_at is None


def test_missing_links_ok(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    assert _pending(db)[0].payload.body_links == ()


def test_new_updated_render_differently(tmp_path):
    db = tmp_path / "o.sqlite3"
    (first,) = _items()[:1]
    process_items([first], T0, db_path=db)
    process_items([dataclasses.replace(first, title=first.title + " v2")], T1, db_path=db)
    new_msg, upd_msg = (render_message(r.payload) for r in _pending(db))
    assert new_msg.startswith("[NEW]") and upd_msg.startswith("[UPDATED]")
    assert new_msg != upd_msg


def test_render_contains_url_and_excerpt(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    msg = render_message(_pending(db)[0].payload)
    assert _items()[0].item_url in msg
    assert "Бургас" in msg


def test_render_missing_body_no_crash():
    item = dataclasses.replace(_items()[0], body_text=None, body_links=())
    msg = render_message(build_payload(item, event_type="NEW", version_no=1))
    assert item.item_url in msg and "[NEW]" in msg


def test_render_deterministic(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    payload = _pending(db)[0].payload
    assert render_message(payload) == render_message(payload)


def test_pending_query_and_delivered_lifecycle(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:2], T0, db_path=db)
    assert len(_pending(db)) == 2
    mark_delivered(db, _pending(db)[0].id, T1)
    assert len(_pending(db)) == 1
    assert count_all(db) == (2, 1, 1)


def test_mark_delivered_requires_aware(tmp_path):
    db = tmp_path / "o.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    with pytest.raises(StateError):
        mark_delivered(db, 1, datetime(2026, 9, 12, 12, 0, 0).replace(tzinfo=None))  # noqa: DTZ001


def test_outbox_insert_failure_rolls_back_state(tmp_path):
    import editor_assistant.state.store as store_mod

    db = tmp_path / "o.sqlite3"
    real_enqueue = store_mod._enqueue

    def boom(*a, **k):
        raise sqlite3.OperationalError("simulated outbox failure")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(store_mod, "_enqueue", boom)
    try:
        with pytest.raises(StateError):
            process_items(_items()[:1], T0, db_path=db)
    finally:
        monkeypatch.setattr(store_mod, "_enqueue", real_enqueue)
        monkeypatch.undo()
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM item_state").fetchone()[0]
    assert n == 0


def test_state_failure_creates_no_outbox_row(tmp_path):
    import editor_assistant.state.store as store_mod

    db = tmp_path / "o.sqlite3"
    real_execute = sqlite3.Connection.execute

    class BoomConn(sqlite3.Connection):
        def execute(self, sql, params=()):  # type: ignore[override]
            if isinstance(sql, str) and "UPDATE item_state SET content_hash" in sql:
                raise sqlite3.OperationalError("simulated state failure")
            return super().execute(sql, params)

    real_connect = sqlite3.connect

    def boom_connect(*a, **k):
        k.setdefault("factory", BoomConn)
        return real_connect(*a, **k)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(store_mod.sqlite3, "connect", boom_connect)
    try:
        (first,) = _items()[:1]
        process_items([first], T0, db_path=db)
        with pytest.raises(StateError):
            process_items([dataclasses.replace(first, title="changed")], T1, db_path=db)
    finally:
        monkeypatch.undo()
    with real_connect(db) as conn:
        outbox_n = conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
        version = conn.execute("SELECT version_no FROM item_state").fetchone()[0]
    assert (outbox_n, version) == (1, 1)
    assert real_execute is not None
