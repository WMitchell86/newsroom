"""M1.3 fingerprint + state tests (temporary DBs only, no live net)."""

from __future__ import annotations

import dataclasses
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from editor_assistant.models import SourceDef
from editor_assistant.sources.rss import PARSER_ID, parse_rss_feed
from editor_assistant.state import (
    ItemStatus,
    StateError,
    fingerprint_item,
    init_db,
    process_items,
)

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


def _change(item, **kw):
    return dataclasses.replace(item, **kw)


def test_identical_content_identical_hash():
    a = _items()[0]
    assert fingerprint_item(a) == fingerprint_item(_change(a))
    assert len(fingerprint_item(a)) == 64


def test_changed_title_different_hash():
    a = _items()[0]
    assert fingerprint_item(_change(a, title=a.title + " !")) != fingerprint_item(a)


def test_changed_body_text_different_hash():
    a = _items()[0]
    assert fingerprint_item(_change(a, body_text="съвсем друг текст")) != fingerprint_item(a)


def test_changed_body_links_different_hash():
    a = _items()[0]
    changed = _change(a, body_links=(*a.body_links, "https://example.com/x.pdf"))
    assert fingerprint_item(changed) != fingerprint_item(a)


def test_changed_author_different_hash():
    a = _items()[0]
    assert fingerprint_item(_change(a, author="някой друг")) != fingerprint_item(a)


def test_changed_published_instant_different_hash():
    a = _items()[0]
    assert a.published_at is not None
    changed = _change(a, published_at=a.published_at + timedelta(hours=1))
    assert fingerprint_item(changed) != fingerprint_item(a)


def test_same_instant_different_offset_same_hash():
    a = _items()[0]
    assert a.published_at is not None
    same = a.published_at.astimezone(timezone(timedelta(hours=-4)))
    assert same.utcoffset() != a.published_at.utcoffset()
    assert fingerprint_item(_change(a, published_at=same)) == fingerprint_item(a)


def test_fetched_at_and_source_url_ignored():
    a = _items()[0]
    changed = _change(
        a, fetched_at=a.fetched_at + timedelta(days=1), source_url="https://other.example/p"
    )
    assert fingerprint_item(changed) == fingerprint_item(a)


def test_unicode_fingerprints_deterministically():
    a = _items()[0]
    assert fingerprint_item(a) == fingerprint_item(a)


def test_first_observation_new_version_1(tmp_path):
    (res,) = process_items(_items()[:1], T0, db_path=tmp_path / "s.sqlite3")
    assert (res.status, res.version_no) == (ItemStatus.NEW, 1)


def test_identical_second_observation_unchanged(tmp_path):
    db = tmp_path / "s.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    (res,) = process_items(_items()[:1], T1, db_path=db)
    assert (res.status, res.version_no) == (ItemStatus.UNCHANGED, 1)


def test_changed_content_updated_version_2_then_unchanged(tmp_path):
    db = tmp_path / "s.sqlite3"
    (first,) = _items()[:1]
    process_items([first], T0, db_path=db)
    changed = _change(first, title=first.title + " (обновено)")
    (upd,) = process_items([changed], T1, db_path=db)
    assert (upd.status, upd.version_no) == (ItemStatus.UPDATED, 2)
    (again,) = process_items([changed], T1, db_path=db)
    assert (again.status, again.version_no) == (ItemStatus.UNCHANGED, 2)


def test_first_seen_stable_last_seen_advances(tmp_path):
    db = tmp_path / "s.sqlite3"
    process_items(_items()[:1], T0, db_path=db)
    process_items(_items()[:1], T1, db_path=db)
    row = (
        sqlite3.connect(db).execute("SELECT first_seen_at, last_seen_at FROM item_state").fetchone()
    )
    assert row == (T0.isoformat(), T1.isoformat())


def test_two_urls_two_identities(tmp_path):
    db = tmp_path / "s.sqlite3"
    res = process_items(_items()[:2], T0, db_path=db)
    assert [r.status for r in res] == [ItemStatus.NEW, ItemStatus.NEW]
    assert res[0].version_no == res[1].version_no == 1


def test_same_url_two_sources_two_identities(tmp_path):
    db = tmp_path / "s.sqlite3"
    a = _items()[0]
    res = process_items([a, _change(a, source_id="other-source")], T0, db_path=db)
    assert [r.status for r in res] == [ItemStatus.NEW, ItemStatus.NEW]
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM item_state").fetchone()[0]
    assert n == 2


def test_init_db_idempotent_keeps_state(tmp_path):
    db = tmp_path / "s.sqlite3"
    init_db(db)
    process_items(_items()[:1], T0, db_path=db)
    init_db(db)
    init_db(db)
    (res,) = process_items(_items()[:1], T1, db_path=db)
    assert (res.status, res.version_no) == (ItemStatus.UNCHANGED, 1)


def test_batch_order_preserved(tmp_path):
    db = tmp_path / "s.sqlite3"
    items = _items()[:2]
    res = process_items(list(reversed(items)), T0, db_path=db)
    assert [r.item_url for r in res] == [i.item_url for i in reversed(items)]


def test_naive_observed_at_fails(tmp_path):
    naive = datetime(2026, 9, 12, 10, 0, 0).replace(tzinfo=None)  # noqa: DTZ001
    with pytest.raises(StateError):
        process_items(_items()[:1], naive, db_path=tmp_path / "x.sqlite3")


def test_batch_failure_leaves_no_partial_state(tmp_path):
    """Simulate mid-batch crash: fingerprint ok, storage dies on 2nd row.

    Patch store's sqlite3.connect with a wrapper whose Connection.execute
    raises on the second INSERT — the `with conn:` block must roll back row 1.
    """
    import editor_assistant.state.store as store_mod

    db = tmp_path / "s.sqlite3"
    real_connect = sqlite3.connect
    calls = {"inserts": 0}

    class FlakyConnection(sqlite3.Connection):
        def execute(self, sql, params=()):  # type: ignore[override]
            if isinstance(sql, str) and sql.lstrip().upper().startswith("INSERT"):
                calls["inserts"] += 1
                if calls["inserts"] == 2:
                    raise sqlite3.OperationalError("simulated storage failure")
            return super().execute(sql, params)

    def flaky_connect(*args, **kwargs):
        kwargs.setdefault("factory", FlakyConnection)
        return real_connect(*args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(store_mod.sqlite3, "connect", flaky_connect)
    try:
        with pytest.raises(StateError):
            process_items(_items()[:2], T0, db_path=db)
    finally:
        monkeypatch.undo()
    n = real_connect(db).execute("SELECT COUNT(*) FROM item_state").fetchone()[0]
    assert n == 0
