"""Phase B1: real HTTP contract tests for the editor JSON boundary."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest

from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import editor_article_store as articles
from editor_assistant.workflow import editor_projections as projections
from editor_assistant.workflow import (
    inbox_store,
    live_store,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import story_editor_metadata as metadata
from editor_assistant.workflow.workbench import http

_OPENER = urllib.request.build_opener()


def _item(item_id: str, title: str, *, discovered_at: str = "2026-09-25T08:00:00Z"):
    return {
        "item_id": item_id,
        "source_id": "source-a",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://example.test/{item_id}",
        "published_at": discovered_at,
        "discovered_at": discovered_at,
        "summary": f"Обобщение за {title}",
        "source_kind": "media",
        "status": "NEW",
    }


def _add_article(root, stories_path, story_id="s-one", title="Работа"):
    return articles.create_editor_article(
        story_id=story_id,
        stories_path=stories_path,
        working_title=title,
        now="2026-09-25T09:00:00Z",
        root=root / "editorial",
    )


@pytest.fixture
def api_store(tmp_path, monkeypatch):
    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    origin = _item("origin", "Първоначална")
    developments = [
        _item("dev-a", "Развитие А", discovered_at="2026-09-25T08:01:00Z"),
        _item("dev-b", "Развитие Б", discovered_at="2026-09-25T08:02:00Z"),
        _item("dev-c", "Развитие В", discovered_at="2026-09-25T08:03:00Z"),
    ]
    inbox_store.save_items([origin, *developments], newsroom / "inbox.jsonl")
    story = story_store.new_story(origin, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    for item in developments[:2]:
        story_store.add_member(
            story,
            item,
            relation="NEW_DEVELOPMENT",
            relation_source="determantic",
            now=item["discovered_at"],
        )
    story["status"] = "SEEN"
    stories_path = newsroom / "stories.json"
    story_store.write_store({"stories": [story]}, stories_path)
    metadata.set_story_followed("s-one", True, stories_path=stories_path, root=newsroom)
    article = _add_article(tmp_path, stories_path)
    return {
        "root": tmp_path,
        "newsroom": newsroom,
        "stories": stories_path,
        "inbox": newsroom / "inbox.jsonl",
        "article": article,
        "dev_a": projections.development_id_for("s-one", "dev-a"),
        "dev_b": projections.development_id_for("s-one", "dev-b"),
        "dev_c": projections.development_id_for("s-one", "dev-c"),
    }


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


def request(base, path, *, method="GET", body=None, content_type="application/json", headers=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    if data is not None or content_type:
        req.add_header("Content-Type", content_type)
    try:
        response = _OPENER.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _data(result):
    return result[1]["data"]


def test_general_json_error_method_unknown_and_sanitized_internal(
    api_server, api_store, monkeypatch
):
    status, payload = request(api_server, "/api/v1/today")
    assert status == 200 and set(payload) == {"data"}

    req = urllib.request.Request(
        f"{api_server}/api/v1/stories/s-one/review",
        data=b"{bad",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        _OPENER.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
        assert json.loads(exc.read())["error"]["code"] == "VALIDATION_ERROR"
    else:
        raise AssertionError("malformed JSON must fail")

    assert request(api_server, "/api/v1/today", method="POST")[0] == 405
    assert request(api_server, "/api/v1/missing")[1]["error"]["code"] == "NOT_FOUND"

    def explode():
        raise RuntimeError("/home/secret/provider-token")

    monkeypatch.setattr(app, "read_today", explode)
    status, payload = request(api_server, "/api/v1/today")
    assert status == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in json.dumps(payload)


def test_story_list_filters_search_and_detail_are_explicit_editor_dtos(api_server, api_store):
    status, payload = request(api_server, "/api/v1/stories?filter=followed")
    assert status == 200
    assert [row["id"] for row in payload["data"]["stories"]] == ["s-one"]
    assert request(api_server, "/api/v1/stories?filter=developments")[0] == 200
    assert request(api_server, "/api/v1/stories?filter=ignored")[1]["data"]["stories"] == []
    from urllib.parse import quote

    assert request(api_server, f"/api/v1/stories?query={quote('развитие')}")[0] == 200
    assert (
        request(api_server, f"/api/v1/stories?query={quote('Първоначална')}")[1]["data"]["stories"]
        == []
    )
    assert request(api_server, "/api/v1/stories?filter=bad")[0] == 400

    detail = _data(request(api_server, "/api/v1/stories/s-one"))
    assert detail["title"] == "Развитие Б"
    assert detail["unreviewedDevelopmentCount"] == 2
    assert len(detail["newDevelopments"]) == 2
    assert detail["relatedArticles"][0]["id"] == api_store["article"]["article_id"]
    assert "members" not in detail and "item_id" not in json.dumps(detail)


def test_review_observed_a_b_keeps_c_unreviewed_and_follow(api_server, api_store):
    store = story_store.read_store(api_store["stories"])
    story = story_store.story_by_id(store, "s-one")
    late_c = next(
        item for item in inbox_store.read_items(api_store["inbox"]) if item["item_id"] == "dev-c"
    )
    story_store.add_member(
        story,
        late_c,
        relation="NEW_DEVELOPMENT",
        relation_source="deterministic",
        now="2026-09-25T08:03:00Z",
    )
    story_store.write_store(store, api_store["stories"])

    status, payload = request(
        api_server,
        "/api/v1/stories/s-one/review",
        method="POST",
        body={"observedDevelopmentIds": [api_store["dev_a"], api_store["dev_b"]]},
    )
    assert status == 200
    data = payload["data"]
    assert data["reviewed"] is True
    assert data["followed"] is True
    assert data["unreviewedDevelopmentCount"] == 1
    unreviewed = [item for item in data["newDevelopments"] if item["unreviewed"]]
    assert [item["id"] for item in unreviewed] == [api_store["dev_c"]]
    assert "REVIEW" in data["availableActions"]
    today = _data(request(api_server, "/api/v1/today"))["newDevelopments"]
    assert [item["objectId"] for item in today] == ["s-one"]
    assert metadata.read_story_editor_metadata_store(root=api_store["newsroom"])["stories"][0][
        "reviewed_development_ids"
    ] == sorted([api_store["dev_a"], api_store["dev_b"]])
    assert (
        request(
            api_server,
            "/api/v1/stories/s-one/review",
            method="POST",
            body={"observedDevelopmentIds": [api_store["dev_c"]]},
        )[0]
        == 200
    )
    final = _data(request(api_server, "/api/v1/stories/s-one"))
    assert final["unreviewedDevelopmentCount"] == 0
    assert "REVIEW" not in final["availableActions"]


def test_ignored_story_with_no_unreviewed_development_recovers_through_review(
    api_server, api_store
):
    story_id = "s-one"
    observed = [api_store["dev_a"], api_store["dev_b"]]
    assert (
        _data(
            request(
                api_server,
                f"/api/v1/stories/{story_id}/review",
                method="POST",
                body={"observedDevelopmentIds": observed},
            )
        )["reviewed"]
        is True
    )

    ignored = _data(request(api_server, f"/api/v1/stories/{story_id}/ignore", method="POST"))
    assert ignored["ignored"] is True
    assert ignored["followed"] is True
    assert "REVIEW" in ignored["availableActions"]

    recovered = _data(
        request(
            api_server,
            f"/api/v1/stories/{story_id}/review",
            method="POST",
            body={"observedDevelopmentIds": []},
        )
    )
    assert recovered["ignored"] is False
    assert recovered["reviewed"] is True
    assert recovered["followed"] is True
    assert "REVIEW" not in recovered["availableActions"]
    assert _data(request(api_server, "/api/v1/today"))["newDevelopments"] == []


def test_follow_unfollow_and_ignore_preserve_bookmark_and_revalidate(api_server, api_store):
    assert _data(request(api_server, "/api/v1/stories/s-one/follow", method="PUT"))["followed"]
    assert request(api_server, "/api/v1/stories/s-one/follow", method="PUT")[0] == 200
    assert not _data(request(api_server, "/api/v1/stories/s-one/follow", method="DELETE"))[
        "followed"
    ]
    assert _data(request(api_server, "/api/v1/stories/s-one/follow", method="PUT"))["followed"]
    ignored = _data(request(api_server, "/api/v1/stories/s-one/ignore", method="POST"))
    assert ignored["ignored"] is True and ignored["followed"] is True
    assert request(api_server, "/api/v1/stories/s-one/ignore", method="POST")[0] == 409


def test_article_list_detail_focus_save_conflict_and_readiness_invalidation(api_server, api_store):
    article_id = api_store["article"]["article_id"]
    assert _data(request(api_server, "/api/v1/articles?filter=preparation"))["articles"]
    assert request(api_server, "/api/v1/articles?filter=ready")[1]["data"]["articles"] == []

    focus = _data(
        request(
            api_server,
            f"/api/v1/articles/{article_id}/focus",
            method="PUT",
            body={"focus": "Ясен редакторски фокус"},
        )
    )
    assert focus["editorialFocus"]["confirmedAt"] is not None
    saved = _data(
        request(
            api_server,
            f"/api/v1/articles/{article_id}/content",
            method="PUT",
            body={"expectedVersion": 0, "title": "Чернова", "body": "Текст"},
        )
    )
    assert saved["state"] == "draft" and saved["content"]["version"] == 1
    conflict = request(
        api_server,
        f"/api/v1/articles/{article_id}/content",
        method="PUT",
        body={"expectedVersion": 0, "title": "Загубено", "body": "Няма да се запише"},
    )
    assert conflict[0] == 409
    assert conflict[1]["error"]["code"] == "ARTICLE_VERSION_CONFLICT"
    assert _data(request(api_server, f"/api/v1/articles/{article_id}"))["content"]["version"] == 1

    articles.mark_article_ready(
        article_id,
        expected_version=1,
        validation=articles.ReadinessValidation(content_version=1, digest="digest"),
    )
    articles.save_article_content(article_id, 1, "Чернова", "Променен текст")
    detail = _data(request(api_server, f"/api/v1/articles/{article_id}"))
    assert detail["state"] == "draft" and detail["readiness"]["isCurrent"] is False
    serialized = json.dumps(detail)
    for forbidden in (
        "internal_refs",
        "content_path",
        "idea_id",
        "evidence_id",
        "case_id",
        "draft_id",
    ):
        assert forbidden not in serialized


def test_today_is_derived_and_excludes_ignored_followed_but_keeps_multiple_developments(
    api_server, api_store
):
    watched = {
        path: path.read_bytes()
        for path in (
            api_store["stories"],
            api_store["inbox"],
            metadata.story_editor_metadata_path(root=api_store["newsroom"]),
            articles.editor_articles_path(),
        )
    }
    data = _data(request(api_server, "/api/v1/today"))
    assert data["newDevelopments"][0]["delta"]["unreviewedDevelopmentCount"] == 2
    assert data["newStories"] == []
    assert all(path.read_bytes() == before for path, before in watched.items())

    request(api_server, "/api/v1/stories/s-one/ignore", method="POST")
    data = _data(request(api_server, "/api/v1/today"))
    assert data["newDevelopments"] == [] and data["newStories"] == []


@pytest.mark.parametrize("metadata_case", ["missing", "partial"])
def test_story_get_tolerates_missing_or_partial_metadata_without_writes(
    api_server, api_store, metadata_case
):
    path = metadata.story_editor_metadata_path(root=api_store["newsroom"])
    if metadata_case == "missing":
        path.unlink()
    else:
        other_item = _item("other", "Друга Story")
        inbox_store.save_items(
            [
                *inbox_store.read_items(api_store["inbox"]),
                other_item,
            ],
            api_store["inbox"],
        )
        other_story = story_store.new_story(other_item, now="2026-09-25T09:00:00Z")
        other_story["story_id"] = "s-other"
        other_story["status"] = "SEEN"
        store = story_store.read_store(api_store["stories"])
        story_store.write_store({"stories": [*store["stories"], other_story]}, api_store["stories"])
        metadata.write_story_editor_metadata(
            {
                "version": 1,
                "stories": [
                    {
                        "story_id": "s-other",
                        "followed": True,
                        "last_reviewed_at": "2026-09-25T09:30:00Z",
                        "reviewed_development_ids": [],
                    }
                ],
            },
            root=api_store["newsroom"],
        )
    watched = {
        candidate: candidate.read_bytes()
        for candidate in (
            api_store["stories"],
            api_store["inbox"],
            path,
            articles.editor_articles_path(),
        )
        if candidate.exists()
    }

    detail = _data(request(api_server, "/api/v1/stories/s-one"))
    listed = _data(request(api_server, "/api/v1/stories?filter=followed"))["stories"]
    today = _data(request(api_server, "/api/v1/today"))

    assert detail["id"] == "s-one" and detail["followed"] is False
    assert [row["id"] for row in listed] == (["s-other"] if metadata_case == "partial" else [])
    assert today["newDevelopments"] == []
    assert all(candidate.read_bytes() == before for candidate, before in watched.items())
    assert (path.exists() and path.read_bytes() == watched.get(path)) or (
        metadata_case == "missing" and not path.exists()
    )


def test_article_search_combines_with_filter_and_returns_newest_first(api_server, api_store):
    older = _add_article(api_store["root"], api_store["stories"], title="Профилактика план А")
    newer = _add_article(api_store["root"], api_store["stories"], title="Профилактика план Б")
    articles.save_article_content(
        older["article_id"],
        0,
        older["working_title"],
        "Подробен план А",
        now="2026-09-25T10:01:00Z",
    )
    articles.save_article_content(
        newer["article_id"],
        0,
        newer["working_title"],
        "Подробен план Б",
        now="2026-09-25T10:02:00Z",
    )

    rows = _data(
        request(
            api_server,
            f"/api/v1/articles?filter=draft&query={quote('ПРОФИЛАКТИКА')}",
        )
    )["articles"]

    assert [row["id"] for row in rows] == [newer["article_id"], older["article_id"]]
    assert [row["updatedAt"] for row in rows] == [
        "2026-09-25T10:02:00Z",
        "2026-09-25T10:01:00Z",
    ]
    assert (
        _data(
            request(
                api_server,
                f"/api/v1/articles?filter=preparation&query={quote('Профилактика')}",
            )
        )["articles"]
        == []
    )
    assert request(api_server, "/api/v1/articles?filter=unknown&query=Plan")[0] == 400


def test_active_and_archive_articles_reference_the_canonical_story_title(api_server, api_store):
    article_id = api_store["article"]["article_id"]
    active_list = _data(request(api_server, "/api/v1/articles"))["articles"]
    active_detail = _data(request(api_server, f"/api/v1/articles/{article_id}"))
    canonical = _data(request(api_server, "/api/v1/stories/s-one"))["title"]

    assert canonical == "Развитие Б"
    assert active_list[0]["story"] == {"id": "s-one", "title": canonical}
    assert active_detail["story"] == {"id": "s-one", "title": canonical}

    archive = _add_article(api_store["root"], api_store["stories"], title="Архивна")
    articles.update_editor_focus(archive["article_id"], "Фокус", now="2026-09-25T10:00:00Z")
    articles.save_article_content(
        archive["article_id"], 0, "Архивна", "Готово", now="2026-09-25T10:01:00Z"
    )
    articles.mark_article_ready(
        archive["article_id"],
        expected_version=1,
        validation=articles.ReadinessValidation(content_version=1, digest="digest"),
        now="2026-09-25T10:02:00Z",
    )
    record = articles.get_editor_article(archive["article_id"])
    record["finalized_at"] = "2026-09-25T10:03:00Z"
    articles.save_editor_articles(
        [
            record if row["article_id"] == archive["article_id"] else row
            for row in articles.read_editor_articles()
        ]
    )

    archived = _data(request(api_server, "/api/v1/archive"))["articles"]
    archived_detail = _data(request(api_server, f"/api/v1/archive/{archive['article_id']}"))
    assert archived[0]["story"] == {"id": "s-one", "title": canonical}
    assert archived_detail["story"] == {"id": "s-one", "title": canonical}


def test_story_facts_and_missing_information_are_safe_read_only_projections(api_server, api_store):
    evidence_id = "EV-INTERNAL-DO-NOT-EXPOSE"
    article_id = api_store["article"]["article_id"]
    record = articles.get_editor_article(article_id)
    record["internal_refs"]["evidence_id"] = evidence_id
    articles.save_editor_articles(
        [
            record if row["article_id"] == article_id else row
            for row in articles.read_editor_articles()
        ]
    )
    packet = {
        "evidence_id": evidence_id,
        "source_url": "https://council.example.test/budget",
        "source_type": "official_council",
        "observed_at": "2026-09-25T08:45:00Z",
        "source_headline": "Официален протокол",
        "facts": [
            {
                "id": "RAW-FACT-ID",
                "text": "Съветът одобри бюджета.",
                "source_reference": "source_text",
                "source_refs": [{"source_id": "council", "locator": "Протокол, т. 4"}],
                "scope": "current_event",
            }
        ],
        "people": [],
        "organizations": ["Общински съвет"],
        "places": ["Бургас"],
        "dates": [],
        "numbers": [],
        "quotes": [],
        "unknowns": ["Кога започва изпълнението?"],
        "source_text": "Вътрешен текст, който не трябва да се сериализира.",
    }
    live_store.save_live_evidence_row(
        {
            "evidence_id": evidence_id,
            "idea_id": "I-INTERNAL",
            "case_id": "C-INTERNAL",
            "packet": packet,
            "observed_at": "2026-09-25T08:45:00Z",
            "readiness": {
                "status": "RESEARCH_MORE",
                "sufficiency": {"research_questions": ["Има ли официален график?"]},
            },
        },
        path=api_store["root"] / "editorial" / "live_evidence.jsonl",
    )
    bundle_path = api_store["root"] / "editorial" / "research" / "fixture.json"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text(
        json.dumps(
            {
                "research_id": "RES-FIXTURE",
                "query": "Story evidence fixture",
                "editor_request": "Validate projection",
                "research_type": "today_news",
                "status": "OPEN",
                "candidates": [],
                "selected_candidate": None,
                "sources": [
                    {
                        "source_id": "council",
                        "url": "https://council.example.test/budget",
                        "source_name": "Официален протокол",
                        "source_type": "official_document",
                        "authority": "PRIMARY",
                        "content_reference": "opened",
                        "relevant_claims": ["Съветът одобри бюджета."],
                        "retrieved_at": "2026-09-25T08:45:00Z",
                    }
                ],
                "research_notes": "",
                "warnings": [],
                "duplicate_check": {"status": None},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    watched = {
        candidate: candidate.read_bytes()
        for candidate in (
            api_store["stories"],
            api_store["inbox"],
            metadata.story_editor_metadata_path(root=api_store["newsroom"]),
            articles.editor_articles_path(),
            api_store["root"] / "editorial" / "live_evidence.jsonl",
            bundle_path,
        )
    }
    story_research_store.merge_research(
        "s-one",
        sources=[
            {
                "id": "council",
                "name": "Официален протокол",
                "url": "https://council.example.test/budget",
            }
        ],
        facts=[
            {
                "id": "fact_council",
                "text": "Съветът одобри бюджета.",
                "sourceId": "council",
                "locator": "Протокол, т. 4",
            }
        ],
        gaps=[
            {"id": "gap_schedule", "question": "Кога започва изпълнението?", "blocking": True},
            {"id": "gap_official", "question": "Има ли официален график?", "blocking": True},
        ],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="legacy-fixture",
        count_round=True,
        root=api_store["root"] / "editorial",
    )

    detail = _data(request(api_server, "/api/v1/stories/s-one"))

    assert len(detail["factsAndSources"]) == 1
    fact = detail["factsAndSources"][0]
    assert fact["text"] == "Съветът одобри бюджета."
    assert fact["source"] == {
        "id": "council",
        "name": "Официален протокол",
        "url": "https://council.example.test/budget",
        "domain": "council.example.test",
    }
    assert fact["locator"] == "Протокол, т. 4" and fact["scope"] == "current"
    assert fact["id"].startswith("fact_") and fact["id"] != "RAW-FACT-ID"
    assert [item["question"] for item in detail["missingInformation"]["items"]] == [
        "Кога започва изпълнението?",
        "Има ли официален график?",
    ]
    assert all(item["blocking"] is True for item in detail["missingInformation"]["items"])
    assert detail["missingInformation"]["assessedAt"] == "2026-09-25T08:45:00Z"
    serialized = json.dumps(detail, ensure_ascii=False)
    for forbidden in (
        evidence_id,
        "I-INTERNAL",
        "C-INTERNAL",
        "RAW-FACT-ID",
        "source_text",
        "Вътрешен текст",
        "internal_refs",
        "idea_id",
        "case_id",
        "draft_id",
        "content_path",
    ):
        assert forbidden not in serialized
    assert all(candidate.read_bytes() == before for candidate, before in watched.items())


def test_archive_returns_only_canonical_finalized_articles_newest_first(api_server, api_store):
    assert request(api_server, "/api/v1/archive")[1]["data"]["articles"] == []
    article = _add_article(api_store["root"], api_store["stories"], title="Архивна")
    articles.update_editor_focus(article["article_id"], "Фокус")
    articles.save_article_content(article["article_id"], 0, "Архивна", "Готово")
    articles.mark_article_ready(
        article["article_id"],
        expected_version=1,
        validation=articles.ReadinessValidation(content_version=1, digest="digest"),
    )
    record = articles.get_editor_article(article["article_id"])
    record["finalized_at"] = "2026-09-25T10:00:00Z"
    rows = articles.read_editor_articles()
    articles.save_editor_articles(
        [record if row["article_id"] == article["article_id"] else row for row in rows]
    )
    rows = _data(request(api_server, "/api/v1/archive"))["articles"]
    assert [row["id"] for row in rows] == [article["article_id"]]
    assert _data(request(api_server, f"/api/v1/archive/{article['article_id']}"))["isFinalized"]


def test_legacy_healthz_and_api_namespace_remain_isolated(api_server):
    with _OPENER.open(f"{api_server}/healthz", timeout=5) as response:
        assert response.status == 200 and response.read() == b"OK\n"
    status, payload = request(api_server, "/api/v1/articles/art_missing")
    assert status == 404 and payload["error"]["code"] == "NOT_FOUND"
