"""Offline tests for the editor-managed source registry (M4A).

The registry is configuration the editor owns: these tests pin the schema, the
time-boxed mute semantics and the "never truncate the store on a bad entry"
guarantee. No network, no collection.
"""

from __future__ import annotations

import json

import pytest

from editor_assistant.workflow import cli
from editor_assistant.workflow import sources_registry as R

OLIVE_DAY = R.date(2026, 9, 20)


@pytest.fixture
def store(tmp_path):
    return tmp_path / "sources.json"


def _official(**overrides):
    entry = {
        "source_id": "burgas-municipal-council",
        "name": "Общински съвет Бургас",
        "kind": "official",
        "collector": "rss",
        "url": "https://burgascouncil.org/last-update.xml",
        "factual_authority": True,
        "priority": "high",
    }
    entry.update(overrides)
    return entry


def test_add_and_read_round_trip_is_sorted_and_deterministic(store):
    R.add_source(path=store, **(_official()))
    R.add_source(
        path=store,
        source_id="flagman",
        name="Флагман",
        kind="regional",
        collector="google_news_rss",
        query="Бургас",
        priority="normal",
    )
    rows = list(R.read_registry(store))
    assert rows == ["burgas-municipal-council", "flagman"]

    first = store.read_text(encoding="utf-8")
    R.save_registry(R.read_registry(store), path=store)
    assert store.read_text(encoding="utf-8") == first  # byte-stable rewrite


def test_re_adding_an_existing_source_is_refused(store):
    R.add_source(path=store, **(_official()))
    with pytest.raises(R.RegistryError, match="already exists"):
        R.add_source(path=store, **(_official(name="Друго име")))


def test_unknown_fields_and_bad_enums_are_refused(store):
    with pytest.raises(R.RegistryError, match="unknown source fields"):
        R.add_source(path=store, **(_official(severity="high")))
    with pytest.raises(R.RegistryError, match="kind must be one of"):
        R.add_source(path=store, **(_official(kind="blog")))
    with pytest.raises(R.RegistryError, match="collector must be one of"):
        R.add_source(path=store, **(_official(collector="scrape")))
    with pytest.raises(R.RegistryError, match="priority must be one of"):
        R.add_source(path=store, **(_official(priority="urgent")))


def test_source_id_must_be_a_slug_and_name_is_required(store):
    with pytest.raises(R.RegistryError, match="lowercase slug"):
        R.add_source(path=store, **(_official(source_id="Община Бургас")))
    with pytest.raises(R.RegistryError, match="name is required"):
        R.add_source(path=store, **(_official(name="   ")))


def test_collector_requirements_are_enforced(store):
    with pytest.raises(R.RegistryError, match="requires an http"):
        R.add_source(path=store, **(_official(collector="web", url="ftp://x")))
    with pytest.raises(R.RegistryError, match="requires a query"):
        R.add_source(
            path=store,
            source_id="news-q",
            name="News query",
            kind="aggregator",
            collector="google_news_rss",
        )
    with pytest.raises(R.RegistryError, match="public-query guard"):
        R.add_source(
            path=store,
            source_id="news-q",
            name="News query",
            kind="aggregator",
            collector="google_news_rss",
            query="x" * (R.MAX_QUERY_CHARS + 1),
        )


def test_factual_authority_must_be_a_real_bool(store):
    with pytest.raises(R.RegistryError, match="factual_authority must be true or false"):
        R.add_source(path=store, **(_official(factual_authority="yes")))


def test_mute_is_time_boxed_and_expires_back_to_active(store):
    R.add_source(path=store, **(_official()))
    with pytest.raises(R.RegistryError, match="requires an end date"):
        R.set_status("burgas-municipal-council", "muted", path=store)
    with pytest.raises(R.RegistryError, match="not a real date"):
        R.set_status("burgas-municipal-council", "muted", muted_until="2026-13-45", path=store)

    entry = R.set_status("burgas-municipal-council", "muted", muted_until="2026-09-25", path=store)
    assert entry["status"] == "muted"

    live = R.describe(entry, today=R.date(2026, 9, 20))
    assert live["effective_status"] == "muted" and live["mute_expired"] is False

    expired = R.describe(entry, today=R.date(2026, 9, 26))
    assert expired["effective_status"] == "active" and expired["mute_expired"] is True
    # the stored window is NOT rewritten — the expiry is computed
    assert R.read_registry(store)["burgas-municipal-council"]["status"] == "muted"


def test_a_mute_without_a_window_cannot_be_stored_and_never_silences(store):
    """Fail closed: an open-ended mute must be refused, not stored as forever."""
    R.add_source(path=store, **(_official()))
    before = store.read_text(encoding="utf-8")
    entry = R.read_registry(store)["burgas-municipal-council"]
    entry["status"], entry["muted_until"] = "muted", ""
    with pytest.raises(R.RegistryError, match="requires muted_until"):
        R.save_registry([entry], path=store)
    assert store.read_text(encoding="utf-8") == before

    # Defensive read path: a hand-edited/corrupt window must resolve to active
    # (a source is never silenced by an unreadable date).
    assert R.effective_status(entry, today=OLIVE_DAY) == "active"
    assert R.effective_status({**entry, "muted_until": "soon"}, today=OLIVE_DAY) == "active"


def test_collectable_excludes_disabled_and_muted_and_orders_by_priority(store):
    R.add_source(path=store, **(_official()))
    R.add_source(
        path=store,
        source_id="bnr-burgas",
        name="БНР Бургас",
        kind="media",
        collector="rss",
        url="https://bnr.bg/burgas/rss",
        priority="normal",
    )
    R.add_source(
        path=store,
        source_id="junk",
        name="Junk",
        kind="media",
        collector="web",
        url="https://junk.example/",
        priority="high",
    )
    R.add_source(
        path=store,
        source_id="paused",
        name="Paused",
        kind="media",
        collector="rss",
        url="https://paused.example/rss",
        priority="high",
    )
    R.set_status("junk", "disabled", path=store)
    R.set_status("paused", "muted", muted_until="2026-12-31", path=store)

    ids = [e["source_id"] for e in R.collectable(store, today=OLIVE_DAY)]
    assert ids == ["burgas-municipal-council", "bnr-burgas"]

    # the window passing brings it straight back
    ids_later = [e["source_id"] for e in R.collectable(store, today=R.date(2027, 1, 1))]
    assert ids_later == ["burgas-municipal-council", "paused", "bnr-burgas"]


def test_setters_and_remove(store):
    R.add_source(path=store, **(_official()))
    assert R.set_priority("burgas-municipal-council", "low", path=store)["priority"] == "low"
    assert R.set_cadence("burgas-municipal-council", "daily", path=store)["cadence"] == "daily"
    assert (
        R.set_factual_authority("burgas-municipal-council", False, path=store)["factual_authority"]
        is False
    )
    with pytest.raises(R.RegistryError, match="unknown source_id"):
        R.set_priority("nope", "high", path=store)
    assert R.remove_source("burgas-municipal-council", path=store)["name"]
    assert R.read_registry(store) == {}


def test_a_bad_entry_never_touches_the_existing_store(store):
    R.add_source(path=store, **(_official()))
    before = store.read_text(encoding="utf-8")
    with pytest.raises(R.RegistryError):
        R.add_source(path=store, **(_official(source_id="bad id", name="x")))
    assert store.read_text(encoding="utf-8") == before


def test_a_corrupt_store_raises_instead_of_looking_empty(store):
    store.write_text("{not json", encoding="utf-8")
    with pytest.raises(R.RegistryError, match="unreadable"):
        R.read_registry(store)


def test_cli_registers_and_manages_the_registry(store, monkeypatch, capsys):
    """The CLI is the same store as the Workbench; the parser must stay wired."""
    monkeypatch.setenv("NEWSROOM_SOURCES_PATH", str(store))
    cli.main(
        [
            "sources",
            "add",
            "--id",
            "flagman",
            "--name",
            "Флагман",
            "--kind",
            "regional",
            "--collector",
            "google_news_rss",
            "--query",
            "Бургас",
            "--monitoring-only",
        ]
    )
    cli.main(
        [
            "sources",
            "add",
            "--id",
            "bnr-burgas",
            "--name",
            "БНР",
            "--kind",
            "media",
            "--collector",
            "rss",
            "--url",
            "https://bnr.bg/burgas/rss",
            "--priority",
            "high",
        ]
    )
    cli.main(["sources", "mute", "bnr-burgas", "--until", "2026-09-25"])
    cli.main(["sources", "authority", "flagman", "no"])
    cli.main(["sources", "list"])
    out = capsys.readouterr().out
    assert "2 total" in out and "1 muted" in out
    assert "monitoring-only" in out and "muted until 2026-09-25" in out

    cli.main(["sources", "disable", "flagman"])
    assert R.read_registry(store)["flagman"]["status"] == "disabled"


def test_cli_reports_a_refused_action_without_a_traceback(store, monkeypatch):
    monkeypatch.setenv("NEWSROOM_SOURCES_PATH", str(store))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["sources", "enable", "nope"])
    assert exit_info.value.code == "sources: unknown source_id: nope"


def test_registry_is_a_list_on_disk_and_summary_counts(store):
    R.add_source(path=store, **(_official()))
    R.add_source(
        path=store,
        source_id="flagman",
        name="Флагман",
        kind="regional",
        collector="google_news_rss",
        query="Бургас",
        factual_authority=False,
    )
    R.set_status("flagman", "disabled", path=store)
    raw = json.loads(store.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and len(raw) == 2

    counts = R.summary(store, today=OLIVE_DAY)
    assert counts == {
        "total": 2,
        "active": 1,
        "disabled": 1,
        "muted": 0,
        "monitoring_only": 1,
    }
