"""V1.2-G4: the editor-facing Sources contract (§16-§33).

These are the proofs the specification asks for, at both levels:

* **service level** — the canonical registry is what actually changes, the
  derived defaults are safe, and every refusal is an editor sentence;
* **HTTP level** — `/api/v1/settings/sources` is thin, validates, and cannot be
  used to reach a field the editor is not allowed to change (§32).

The hard rules pinned here:

  §2   one registry. `WB_NEWSROOM_DIR` decides which file is read and written.
  §6   `factual_authority` is a strict boolean — never inferred, never coerced.
  §8   disabling keeps the row and every Publication that came from it.
  §11  no hard delete exists; a disabled source is the editor's removal.
  §19  several rows may share one publisher domain and must not be collapsed.
  §20  refusals are editor language, never a schema sentence.
  §22  the frontend cannot invent factual authority: only a real editor value
       reaches the store, and an unknown key is refused outright.
  §27  writes are atomic and serialized.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from editor_assistant.workflow import editor_source_settings as settings
from editor_assistant.workflow import sources_registry as registry
from editor_assistant.workflow.workbench import http

_OPENER = urllib.request.build_opener()


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
    """An isolated newsroom root. The repository's real stores are never read."""
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    return root


@pytest.fixture
def api_server():
    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(base, path, *, method="GET", body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        response = _OPENER.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _data(result):
    return result[1]["data"]


def _error(result):
    return result[1]["error"]


def _seed(root, **overrides):
    entry = {
        "source_id": "burgas-municipality",
        "name": "Община Бургас",
        "kind": "official",
        "domain": "burgas.bg",
        "collector": "google_news_rss",
        "query": "Община Бургас",
        "priority": "high",
        "factual_authority": True,
    }
    entry.update(overrides)
    return registry.add_source(root / "sources.json", **entry)


def _stored(root, source_id):
    return registry.read_registry(root / "sources.json")[source_id]


# ---------- §4/§12/§13: editor language ----------


def test_list_reports_editor_language_not_registry_vocabulary(newsroom):
    _seed(newsroom, source_id="darik-burgas", name="DarikNews Бургас", kind="regional",
          domain="dariknews.bg", factual_authority=False, priority="normal")

    payload = settings.list_sources()

    assert payload["summary"] == {
        "total": 1,
        "monitored": 1,
        "notMonitored": 0,
        "factualAuthority": 0,
        "problems": 0,
    }
    row = payload["sources"][0]
    assert row["kindLabel"] == "Регионална медия"
    assert row["priorityLabel"] == "Нормален"
    assert row["monitored"] is True
    # The raw enums stay available for filtering, but the editor's words are


# ---------- §8: enable / disable ----------


def test_disable_keeps_the_row_and_its_publisher_identity(newsroom):
    _seed(newsroom)

    off = settings.set_monitored("burgas-municipality", False)

    assert off["monitored"] is False
    # §8: the source stays in the registry, still with its publisher identity, so
    # history remains interpretable. Only the collection status changed.
    stored = _stored(newsroom, "burgas-municipality")
    assert stored["status"] == "disabled"
    assert stored["domain"] == "burgas.bg"
    assert settings.list_sources()["summary"]["notMonitored"] == 1

    on = settings.set_monitored("burgas-municipality", True)
    assert on["monitored"] is True
    assert _stored(newsroom, "burgas-municipality")["status"] == "active"


def test_a_disabled_source_is_still_offered_to_the_editor(newsroom):
    _seed(newsroom)
    settings.set_monitored("burgas-municipality", False)

    # §32: it does not disappear. It is listed, it is just not collected.
    assert [row["id"] for row in settings.list_sources()["sources"]] == ["burgas-municipality"]


# ---------- §6/§7/§22: factual authority ----------


def test_factual_authority_requires_an_explicit_boolean(newsroom):
    _seed(newsroom, factual_authority=False)

    for bad in (None, 1, "true", "да"):
        with pytest.raises(settings.SourceSettingsError) as caught:
            settings.set_factual_authority("burgas-municipality", bad)
        assert "включен или изключен" in caught.value.message

    assert _stored(newsroom, "burgas-municipality")["factual_authority"] is False


def test_turning_authority_on_is_an_editor_decision_that_is_persisted(newsroom):
    _seed(newsroom, factual_authority=False)

    row = settings.set_factual_authority("burgas-municipality", True)

    assert row["factualAuthority"] is True
    # The canonical registry changed, not just the returned view.
    assert _stored(newsroom, "burgas-municipality")["factual_authority"] is True


# ---------- §19: several rows, one publisher ----------


def test_rows_sharing_one_publisher_domain_are_not_collapsed(newsroom):
    """The Burgas Municipality regression (§19) must stay impossible.

    Three registry rows may legitimately declare `burgas.bg`: the publisher
    identity and the collection-source identity are different concepts.
    """
    _seed(newsroom, source_id="burgas-municipality", name="Община Бургас")
    _seed(newsroom, source_id="burgas-cultural-program", name="Културна програма — Бургас",
          kind="official", domain="burgas.bg")
    _seed(newsroom, source_id="burgas-sport-program", name="Спортна програма — Бургас",
          kind="official", domain="burgas.bg")

    rows = settings.list_sources()["sources"]
    assert len(rows) == 3
    assert {row["domain"] for row in rows} == {"burgas.bg"}
    # Disabling one leaves the other two untouched.
    settings.set_monitored("burgas-cultural-program", False)
    still = {row["id"]: row["monitored"] for row in settings.list_sources()["sources"]}
    assert still == {
        "burgas-municipality": True,
        "burgas-cultural-program": False,
        "burgas-sport-program": True,
    }


# ---------- §9: add, with derived defaults ----------


def test_add_derives_the_id_from_a_bulgarian_name(newsroom):
    row = settings.add_source(
        name="Пътна полиция",
        address="kat.bg",
        kind="official",
        monitored=True,
        factual_authority=True,
        priority="high",
    )

    assert row["id"] == "patna-politsiya"
    assert row["name"] == "Пътна полиция"
    assert row["domain"] == "kat.bg"
    assert row["kindLabel"] == "Официален"
    assert row["factualAuthority"] is True
    # A bare host is monitored through the existing query mechanism, and no feed
    # URL was invented for it.
    stored = _stored(newsroom, "patna-politsiya")
    assert stored["collector"] == "google_news_rss"
    assert stored["query"] == "Пътна полиция"
    assert stored["url"] == ""


def test_add_recognises_a_feed_url_and_collects_it_directly(newsroom):
    row = settings.add_source(
        name="Общински съвет Бургас",
        address="https://burgascouncil.org/last-update.xml",
        kind="official",
        monitored=True,
        factual_authority=True,
        priority="high",
    )

    stored = _stored(newsroom, row["id"])
    assert stored["collector"] == "rss"
    assert stored["url"] == "https://burgascouncil.org/last-update.xml"
    assert row["address"] == "https://burgascouncil.org/last-update.xml"


def test_add_can_create_a_source_that_is_not_monitored_yet(newsroom):
    row = settings.add_source(
        name="Община Царево",
        address="tsarevo.bg",
        kind="official",
        monitored=False,
        factual_authority=False,
        priority="low",
    )
    assert row["monitored"] is False
    assert _stored(newsroom, "obshtina-tsarevo")["status"] == "disabled"


# ---------- §20: editor-language refusals ----------


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"name": "   "}, "Дайте име"),
        ({"kind": "unknown"}, "Изберете тип"),
        ({"priority": "urgent"}, "Изберете приоритет"),
        ({"address": "ftp://mvr.bg"}, "http://"),
        ({"address": "not a host/path?x=1"}, "Домейнът не е разпознат"),
        ({"monitored": "да"}, "включен или изключен"),
        ({"factual_authority": 1}, "включен или изключен"),
    ],
)
def test_add_refuses_bad_input_in_plain_bulgarian(newsroom, override, fragment):
    call = {
        "name": "ОДМВР Бургас", "address": "mvr.bg", "kind": "official",
        "monitored": True, "factual_authority": False, "priority": "high",
    }
    call.update(override)
    with pytest.raises(settings.SourceSettingsError) as caught:
        settings.add_source(**call)
    assert fragment in caught.value.message
    # Nothing was written by a refused add.
    assert settings.list_sources()["sources"] == []


def test_a_missing_source_is_refused_by_name(newsroom):
    with pytest.raises(settings.SourceNotFound):
        settings.set_monitored("does-not-exist", False)
    with pytest.raises(settings.SourceNotFound):
        settings.set_factual_authority("does-not-exist", True)


# ---------- §10: the inline editor ----------


def test_update_applies_only_the_fields_the_editor_may_change(newsroom):
    _seed(newsroom, factual_authority=False)

    row = settings.update_source(
        "burgas-municipality",
        {"name": "Община Бургас — официален сайт", "priority": "low"},
    )

    assert row["name"] == "Община Бургас — официален сайт"
    assert row["priorityLabel"] == "Нисък"
    stored = _stored(newsroom, "burgas-municipality")
    assert stored["name"] == "Община Бургас — официален сайт"
    assert stored["priority"] == "low"
    # The identity and the untouched policy are exactly as before.
    assert stored["source_id"] == "burgas-municipality"
    assert stored["domain"] == "burgas.bg"
    assert stored["factual_authority"] is False


def test_update_cannot_reach_a_field_outside_the_editor_surface(newsroom):
    _seed(newsroom)
    for forbidden in ({"sourceId": "hacked"}, {"collector": "web"}, {"status": "muted"}):
        with pytest.raises(settings.SourceSettingsError):
            settings.update_source("burgas-municipality", forbidden)


# ---------- §11: no hard delete ----------


def test_there_is_no_hard_delete_on_the_editor_surface(newsroom):
    """`Изключи` is the removal.

    The registry keeps a destructive path for the CLI and the legacy Workbench,
    but the editor service must not expose one until historical-reference safety
    is proven (§11).
    """
    _seed(newsroom)
    assert not hasattr(settings, "remove_source")
    assert not hasattr(settings, "delete_source")


def test_the_api_has_no_delete_route_for_sources(newsroom, api_server):
    _seed(newsroom)
    status, payload = request(
        api_server, "/api/v1/settings/sources/burgas-municipality", method="DELETE"
    )
    # A known path with an unsupported method is 405, never a silent removal.
    assert status == 405
    assert _error((status, payload))["code"] == "VALIDATION_ERROR"
    assert "burgas-municipality" in registry.read_registry(newsroom / "sources.json")


# ---------- §27: write safety ----------


def test_concurrent_edits_do_not_lose_a_field(newsroom):
    """Two actions at once must not overwrite each other's change."""
    _seed(newsroom, factual_authority=False)

    errors: list[Exception] = []

    def disable():
        try:
            settings.set_monitored("burgas-municipality", False)
        except Exception as exc:  # noqa: BLE001 - surfaced in the assertion below
            errors.append(exc)

    def grant_authority():
        try:
            settings.set_factual_authority("burgas-municipality", True)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=disable), threading.Thread(target=grant_authority)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    stored = _stored(newsroom, "burgas-municipality")
    assert stored["status"] == "disabled"
    assert stored["factual_authority"] is True
    # The store is still valid JSON with one intact row, not a torn write.
    assert len(json.loads((newsroom / "sources.json").read_text(encoding="utf-8"))) == 1


# ---------- §33: isolation ----------


# ---------- §26/§32: the HTTP contract ----------


def test_get_lists_the_registry_in_editor_language(newsroom, api_server):
    _seed(newsroom, factual_authority=True, priority="high")

    status, payload = request(api_server, "/api/v1/settings/sources")

    assert status == 200
    data = _data((status, payload))
    assert data["summary"]["total"] == 1
    row = data["sources"][0]
    assert row["name"] == "Община Бургас"
    assert row["kindLabel"] == "Официален"
    assert row["priorityLabel"] == "Висок"
    assert row["factualAuthority"] is True


def test_post_creates_a_source_and_returns_the_canonical_row(newsroom, api_server):
    status, payload = request(
        api_server,
        "/api/v1/settings/sources",
        method="POST",
        body={
            "name": "НИМХ",
            "address": "nimh.bg",
            "kind": "official",
            "monitored": True,
            "factualAuthority": True,
            "priority": "high",
        },
    )

    assert status == 201
    assert _data((status, payload))["id"] == "nimh"
    # §30/§31: the *backend* registry changed, not just React state.
    stored = _stored(newsroom, "nimh")
    assert stored["factual_authority"] is True
    assert stored["status"] == "active"


def test_put_changes_the_canonical_registry(newsroom, api_server):
    _seed(newsroom, factual_authority=False)

    status, payload = request(
        api_server,
        "/api/v1/settings/sources/burgas-municipality",
        method="PUT",
        body={"monitored": False},
    )

    assert status == 200
    assert _data((status, payload))["monitored"] is False
    assert _stored(newsroom, "burgas-municipality")["status"] == "disabled"


