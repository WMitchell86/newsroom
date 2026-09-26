"""Phase B1: real HTTP contract tests for the editor JSON boundary."""

from __future__ import annotations

import json
import threading
import time
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


def test_start_article_creates_canonical_preparation_article_and_retry_is_idempotent(
    api_server, api_store
):
    before = len(_data(request(api_server, "/api/v1/articles?filter=preparation"))["articles"])
    status, payload = request(
        api_server,
        "/api/v1/stories/s-one/articles",
        method="POST",
        headers={"Idempotency-Key": "start-article-1"},
    )
    assert status == 201
    article = payload["data"]
    assert article["id"].startswith("art_")
    assert article["story"] == {"id": "s-one", "title": "Развитие Б"}
    assert article["state"] == "preparation"
    assert article["title"] == "Развитие Б"
    assert article["content"]["body"] == ""
    assert article["editorialFocus"]["text"]
    assert article["editorialFocus"]["confirmedAt"] is None
    assert article["preparation"] == {
        "focusConfirmed": False,
        # V1.1-B: the backend now reports WHY a Draft is unavailable, instead of
        # leaving React to guess. The reason comes from the one shared decision.
        "draftReadiness": {
            "code": "FOCUS_NOT_CONFIRMED",
            "message": "Потвърдете фокуса, преди да правите чернова.",
        },
        "blockingGaps": [],
        "nonBlockingGaps": [],
        "draftEligible": False,
        # V1.1-C: no generation has been attempted, so there is no recovery
        # context and the manual editor is not offered.
        "draftFailure": None,
        "availableActions": ["SELECT_FOCUS"],
    }
    serialized = json.dumps(article, ensure_ascii=False)
    assert not any(
        value in serialized for value in ("Case", "Idea", "idea_id", "case_id", "draft_id")
    )

    retry_status, retry_payload = request(
        api_server,
        "/api/v1/stories/s-one/articles",
        method="POST",
        headers={"Idempotency-Key": "start-article-1"},
    )
    assert retry_status == 201 and retry_payload["data"]["id"] == article["id"]
    assert (
        len(_data(request(api_server, "/api/v1/articles?filter=preparation"))["articles"])
        == before + 1
    )
    assert article["id"] in {
        row["id"] for row in _data(request(api_server, "/api/v1/stories/s-one"))["relatedArticles"]
    }

    second_status, second_payload = request(
        api_server,
        "/api/v1/stories/s-one/articles",
        method="POST",
        headers={"Idempotency-Key": "start-article-2"},
    )
    assert second_status == 201 and second_payload["data"]["id"] != article["id"]


def test_start_article_is_unavailable_for_ignored_story_and_rejects_bad_key(api_server, api_store):
    assert (
        "START_ARTICLE" in _data(request(api_server, "/api/v1/stories/s-one"))["availableActions"]
    )
    request(api_server, "/api/v1/stories/s-one/ignore", method="POST")
    ignored = _data(request(api_server, "/api/v1/stories/s-one"))
    assert "START_ARTICLE" not in ignored["availableActions"]
    assert (
        request(
            api_server,
            "/api/v1/stories/s-one/articles",
            method="POST",
            headers={"Idempotency-Key": "bad key"},
        )[0]
        == 400
    )
    assert request(api_server, "/api/v1/stories/s-one/articles", method="POST")[0] == 400
    assert (
        request(
            api_server,
            "/api/v1/stories/s-one/articles",
            method="POST",
            body={"title": "Не се приема преди Article"},
            headers={"Idempotency-Key": "unexpected-body"},
        )[0]
        == 400
    )


def test_preparation_focus_title_readiness_and_today_projection(api_server, api_store):
    created = _data(
        request(
            api_server,
            "/api/v1/stories/s-one/articles",
            method="POST",
            headers={"Idempotency-Key": "readability"},
        )
    )
    article_id = created["id"]
    assert any(
        row["objectId"] == article_id
        for row in _data(request(api_server, "/api/v1/today"))["articlesRequiringAction"]
    )

    title = _data(
        request(
            api_server,
            f"/api/v1/articles/{article_id}/title",
            method="PUT",
            body={"expectedVersion": 0, "title": "Консервативно работно заглавие"},
        )
    )
    assert title["title"] == "Консервативно работно заглавие"
    assert title["content"]["body"] == "" and title["content"]["version"] == 1

    focused = _data(
        request(
            api_server,
            f"/api/v1/articles/{article_id}/focus",
            method="PUT",
            body={"focus": "Да обясним промяната и нейните последици."},
        )
    )
    assert focused["editorialFocus"]["confirmedAt"] is not None
    assert focused["preparation"]["focusConfirmed"] is True
    # V1.1-B: a confirmed Focus is NOT sufficient. This Story has never been
    # researched, so the honest answer is `STORY_UNASSESSED` — before V1.1-B
    # this exact state returned `draftEligible: true` and offered MAKE_DRAFT,
    # which the command then refused. That contradiction is now impossible.
    assert focused["preparation"]["draftEligible"] is False
    assert focused["preparation"]["draftReadiness"]["code"] == "STORY_UNASSESSED"
    assert "MAKE_DRAFT" not in focused["preparation"]["availableActions"]
    assert "MAKE_DRAFT" not in focused["availableActions"]
    assert focused["nextAction"]["action"] == "RESEARCH_MORE"
    assert focused["nextAction"]["reasonCode"] == "STORY_UNASSESSED"

    # Once the Story carries real evidence, the SAME decision becomes eligible.
    story_research_store.merge_research(
        "s-one",
        sources=[{"id": "vestnik", "name": "Вестник", "url": "https://vestnik.test/2026/budget"}],
        facts=[
            {
                "id": "fact_budget",
                "text": "Съветът одобри 1,2 милиона лева за ремонта на булеварда.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            }
        ],
        gaps=[],
        assessed_at="2026-09-25T09:30:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="eligibility-proof",
    )
    researched = _data(request(api_server, f"/api/v1/articles/{article_id}"))
    assert researched["preparation"]["draftEligible"] is True
    assert researched["preparation"]["draftReadiness"]["code"] == "DRAFT_ELIGIBLE"
    # V1.1-C: a clean preparation Article offers generation only. `EDIT` is a
    # recovery path after a genuine generation failure, never an alternative to
    # `Направи чернова` on a clean Article, so it is absent here and
    # `draftFailure` is null.
    assert researched["preparation"]["availableActions"] == ["CHANGE_FOCUS", "MAKE_DRAFT"]
    assert "EDIT" not in researched["availableActions"]
    assert researched["preparation"]["draftFailure"] is None
    assert researched["nextAction"]["action"] == "MAKE_DRAFT"

    story_research_store.save_story_research(
        {
            "story_id": "s-one",
            "sources": [],
            "facts": [],
            "gaps": [
                {
                    "id": "gap_date",
                    "question": "Кога започва изпълнението?",
                    "kind": "unresolved",
                    "blocking": True,
                },
                {
                    "id": "gap_context",
                    "question": "Кой е основният заинтересован?",
                    "kind": "missing_fact",
                    "blocking": False,
                },
            ],
            "assessed_at": "2026-09-25T10:00:00Z",
            "research_rounds": 1,
            "operation_ids": ["op-fixture"],
        }
    )
    blocked = _data(request(api_server, f"/api/v1/articles/{article_id}"))
    assert blocked["preparation"]["draftEligible"] is False
    # V1.1-B: a real blocking gap is explained BY the gap, with its own code.
    assert blocked["preparation"]["draftReadiness"]["code"] == "BLOCKING_GAP"
    assert blocked["preparation"]["blockingGaps"][0]["question"] == "Кога започва изпълнението?"
    assert (
        blocked["preparation"]["nonBlockingGaps"][0]["question"] == "Кой е основният заинтересован?"
    )
    assert blocked["availableActions"] == ["CHANGE_FOCUS", "RESEARCH_MORE"]
    assert blocked["nextAction"]["action"] == "RESEARCH_MORE"
    assert blocked["nextAction"]["reasonCode"] == "BLOCKING_GAP"
    assert "MAKE_DRAFT" not in blocked["availableActions"]
    # V1.1-C: a readiness refusal is not a generation failure, so it never opens
    # the manual editor and never records a durable failure marker.
    assert "EDIT" not in blocked["availableActions"]
    assert blocked["preparation"]["draftFailure"] is None

    empty = request(
        api_server,
        f"/api/v1/articles/{article_id}/focus",
        method="PUT",
        body={"focus": "   "},
    )
    assert empty[0] == 400


def test_draft_endpoint_requires_an_idempotency_key_and_accepts_no_fields(api_server, api_store):
    """C2 transport: the key is required and the body carries no client facts."""
    article_id = api_store["article"]["article_id"]
    path = f"/api/v1/articles/{article_id}/draft"
    assert request(api_server, path, method="POST")[0] == 400
    assert (
        request(api_server, path, method="POST", headers={"Idempotency-Key": "bad key"})[0] == 400
    )
    # The Article is still in preparation with no confirmed focus, so the
    # backend - not the transport - refuses even with a valid key.
    # V1.1-B: it refuses with the exact semantic reason, not a generic
    # invalid transition.
    unconfirmed = request(
        api_server, path, method="POST", headers={"Idempotency-Key": "unconfirmed"}
    )
    assert unconfirmed[0] == 409
    assert unconfirmed[1]["error"]["code"] == "FOCUS_NOT_CONFIRMED"
    assert unconfirmed[1]["error"]["message"] == "Потвърдете фокуса, преди да правите чернова."
    assert (
        request(
            api_server,
            path,
            method="POST",
            body={"body": "текст от клиента"},
            headers={"Idempotency-Key": "with-body"},
        )[0]
        == 400
    )


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


def test_story_projection_skips_malformed_legacy_research_artifacts(api_server, api_store):
    path = articles.editor_articles_path().parent / "research" / "malformed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")

    detail = _data(request(api_server, "/api/v1/stories/s-one"))

    assert detail["id"] == "s-one"
    assert detail["factsAndSources"] == []
    assert path.read_text(encoding="utf-8") == "[]"


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


# ---------------------------------------------------------------- B4B «Обнови»


def _feed(items):
    body = "".join(
        f"<item><title>{title}</title><link>https://feed.example/{slug}</link>"
        f"<pubDate>Mon, 21 Sep 2026 06:00:00 +0300</pubDate>"
        f"<description>{summary}</description></item>"
        for slug, title, summary in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Емисия</title><link>https://feed.example/</link>{body}</channel></rss>"
    ).encode()


class _Response:
    def __init__(self, payload):
        self.payload = payload


def _await(base, token):
    for _ in range(400):
        payload = _data(request(base, f"/api/v1/operations/{token}"))
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("operation did not finish")


def test_refresh_is_rejected_without_active_sources(api_server, api_store):
    status, payload = request(api_server, "/api/v1/today/refresh", method="POST")
    assert status == 409
    assert payload["error"]["code"] == "INVALID_TRANSITION"
    assert "източници" in payload["error"]["message"]


def test_refresh_returns_202_with_a_bounded_operation_and_refetches_today(
    api_server, api_store, monkeypatch
):
    from datetime import datetime, timezone

    from editor_assistant.sources import fetcher
    from editor_assistant.workflow import newsroom_run, sources_registry, story_operations

    newsroom = api_store["newsroom"]
    sources_registry.add_source(
        path=newsroom / "sources.json",
        source_id="council",
        name="Общински съвет",
        kind="official",
        collector="rss",
        url="https://feed.example/rss",
        priority="high",
        factual_authority=True,
    )
    posts = {
        "https://feed.example/rss": _feed([("a", "Нова сесия", "Общински съвет заседава днес.")])
    }
    monkeypatch.setattr(fetcher, "fetch_bytes", lambda url: _Response(posts[str(url)]))
    # Pin the collector clock: the fixture is dated 2026-09-21 and the 72 h news
    # window must not rotate it out of range as the real date advances.
    monkeypatch.setattr(
        newsroom_run, "_now", lambda: datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    )
    story_operations.clear()

    status, payload = request(
        api_server,
        "/api/v1/today/refresh",
        method="POST",
        headers={"Idempotency-Key": "api-key-1"},
    )
    assert status == 202
    token = payload["data"]["operationToken"]
    assert token.startswith("op_")

    operation = _await(api_server, token)
    assert operation["status"] == "succeeded", operation
    assert operation["result"]["new"] == 1
    # ...and the canonical Today GET is the authority for the new attention.
    today = _data(request(api_server, "/api/v1/today"))
    assert len(today["newStories"]) == 1
    assert today["problems"] == []


def test_refresh_rejects_a_malformed_idempotency_key(api_server, api_store):
    from editor_assistant.workflow import sources_registry

    sources_registry.add_source(
        path=api_store["newsroom"] / "sources.json",
        source_id="council",
        name="Общински съвет",
        kind="official",
        collector="rss",
        url="https://feed.example/rss",
        priority="high",
        factual_authority=True,
    )
    status, payload = request(
        api_server,
        "/api/v1/today/refresh",
        method="POST",
        headers={"Idempotency-Key": "bad key with spaces"},
    )
    assert status == 400
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_refresh_is_a_single_endpoint_with_no_stage_routes(api_server):
    for stage in ("collect", "ingest", "group", "classify"):
        status, payload = request(api_server, f"/api/v1/today/{stage}", method="POST")
        assert status == 404, stage
        assert payload["error"]["code"] == "NOT_FOUND"
    assert request(api_server, "/api/v1/today/refresh")[0] == 405


# ---------------------------------------------------------------- C2 «Направи чернова»


def _draft_stub(monkeypatch, body: str = "Общинският съвет одобри графика за ремонта."):
    """Stub only the model transport; the real readiness/retrieval/gates run."""
    from editor_assistant.drafting import generate as draft_gen

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def call(_prompt, *, api_key, timeout, role="draft", **_kw):
        if role == "draft":
            return (
                json.dumps(
                    {"headlines": ["Заглавие"], "headline": "Заглавие", "body": body},
                    ensure_ascii=False,
                ),
                {"model": "mock"},
            )
        # A real judge verdict: an empty reply is a failed route, not a pass.
        return (
            json.dumps(
                {
                    "sentence": body,
                    "verdict": "SUPPORTED",
                    "issue": "none",
                    "supporting_fact_ids": [],
                    "note": "ok",
                },
                ensure_ascii=False,
            ),
            {"model": "mock"},
        )

    monkeypatch.setattr(draft_gen, "_call_gemini", call)


def _ready_article(api_store, monkeypatch):
    """A Story basis with real reader-value depth, so readiness can pass."""
    story_research_store.merge_research(
        "s-one",
        sources=[
            {
                "id": "vestnik",
                "name": "Вестник",
                "url": "https://vestnik.example.test/2026/budget",
            }
        ],
        facts=[
            {
                "id": "fact_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="api-fixture",
    )
    article = _add_article(api_store["root"], api_store["stories"], title="График за ремонта")
    articles.update_editor_focus(article["article_id"], "Да обясним решението и последиците.")
    _draft_stub(monkeypatch)
    return article["article_id"]


def test_draft_returns_202_and_polls_to_the_canonical_article(api_server, api_store, monkeypatch):
    article_id = _ready_article(api_store, monkeypatch)
    status, payload = request(
        api_server,
        f"/api/v1/articles/{article_id}/draft",
        method="POST",
        headers={"Idempotency-Key": "http-draft-1"},
    )
    assert status == 202
    assert list(payload["data"]) == ["operationToken"]
    assert payload["data"]["operationToken"].startswith("op_")

    operation = _await(api_server, payload["data"]["operationToken"])
    assert operation["status"] == "succeeded", operation
    article = operation["result"]
    assert article["id"] == article_id
    assert article["state"] == "draft"
    assert article["content"]["body"].strip()
    assert article["content"]["version"] == 1
    assert "MAKE_DRAFT" not in article["availableActions"]

    # The canonical read agrees with the operation result.
    current = _data(request(api_server, f"/api/v1/articles/{article_id}"))
    assert current["content"] == article["content"]
    assert current["warnings"] == article["warnings"]


def test_draft_is_refused_for_a_blocked_basis_and_a_stale_action(
    api_server, api_store, monkeypatch
):
    article_id = _ready_article(api_store, monkeypatch)
    story_research_store.merge_research(
        "s-one",
        sources=[],
        facts=[],
        gaps=[{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}],
        assessed_at="2026-09-25T11:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="api-gap",
    )
    blocked = request(
        api_server,
        f"/api/v1/articles/{article_id}/draft",
        method="POST",
        headers={"Idempotency-Key": "http-blocked"},
    )
    assert blocked[0] == 409
    assert blocked[1]["error"]["code"] == "BLOCKING_GAP"
    assert blocked[1]["error"]["retryable"] is False

    # A stale client action after a real edit is a version conflict, never a
    # silent overwrite of the editor's text.
    store = story_store.read_store(api_store["stories"])
    story_store.write_store(store, api_store["stories"])
    story_research_store.save_story_research(
        {
            "story_id": "s-one",
            "sources": [
                {
                    "id": "vestnik",
                    "name": "Вестник",
                    "url": "https://vestnik.example.test/2026/budget",
                }
            ],
            "facts": [
                {
                    "id": "fact_money",
                    "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                    "sourceId": "vestnik",
                    "locator": "Протокол, т. 4",
                }
            ],
            "gaps": [],
            "assessed_at": "2026-09-25T12:00:00Z",
            "research_rounds": 1,
            "operation_ids": ["api-fixture"],
        }
    )
    articles.save_article_content(article_id, 0, "График за ремонта", "Ръчен текст")
    stale = request(
        api_server,
        f"/api/v1/articles/{article_id}/draft",
        method="POST",
        headers={"Idempotency-Key": "http-stale"},
    )
    assert stale[0] == 409
    assert stale[1]["error"]["code"] == "INVALID_TRANSITION"
    assert articles.get_article_content(article_id)["body"] == "Ръчен текст"


# --------------------------------------------------- C4 «Отбележи като готова»


def _ready_basis():
    """A Story basis with real reader-value depth, so validation can pass."""
    story_research_store.merge_research(
        "s-one",
        sources=[
            {
                "id": "vestnik",
                "name": "Вестник",
                "url": "https://vestnik.example.test/2026/budget",
            }
        ],
        facts=[
            {
                "id": "fact_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            },
            {
                "id": "fact_people",
                "text": "Жителите на квартала ще пътуват с 10 минути повече до работата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 5",
            },
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="c4-api-fixture",
    )


SUPPORTED_BODY = (
    "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата. "
    "Жителите на квартала ще пътуват с 10 минути повече до работата."
)


def _draft_for_ready(api_store, body: str = SUPPORTED_BODY) -> str:
    _ready_basis()
    article = _add_article(api_store["root"], api_store["stories"], title="График за ремонта")
    articles.update_editor_focus(article["article_id"], "Да обясним решението и последиците.")
    articles.save_article_content(article["article_id"], 0, "График за ремонта", body)
    return article["article_id"]


def test_ready_marks_the_current_version_and_returns_the_canonical_article(api_server, api_store):
    article_id = _draft_for_ready(api_store)
    status, payload = request(
        api_server,
        f"/api/v1/articles/{article_id}/ready",
        method="POST",
        body={"expectedVersion": 1},
    )
    assert status == 200
    article = payload["data"]
    assert article["state"] == "ready"
    assert article["readiness"]["isCurrent"] is True
    assert article["readiness"]["readyVersion"] == 1
    assert article["readiness"]["readyAt"]
    assert article["validation"] == {
        "contentVersion": 1,
        "current": True,
        "blocking": False,
        "readyEligible": False,
    }
    # C5: the Ready surface offers exactly the two editorial decisions.
    assert article["availableActions"] == ["EDIT", "FINALIZE"]
    assert article["nextAction"]["action"] == "FINALIZE"
    stored = articles.get_editor_article(article_id)
    assert stored["ready_validation_digest"].startswith("vd_")
    assert stored["finalized_at"] is None
    # Readiness is still not finalization, and `Финализирай` is not publishing:
    # it needs the idempotency key the transport carries.
    assert (
        request(
            api_server,
            f"/api/v1/articles/{article_id}/finalize",
            method="POST",
            body={"expectedVersion": 1},
        )[0]
        == 400
    )


def test_ready_refuses_a_stale_expected_version(api_server, api_store):
    article_id = _draft_for_ready(api_store)
    articles.save_article_content(
        article_id, 1, "График за ремонта", SUPPORTED_BODY + " Уточнение."
    )

    status, payload = request(
        api_server,
        f"/api/v1/articles/{article_id}/ready",
        method="POST",
        body={"expectedVersion": 1},
    )
    assert status == 409
    assert payload["error"]["code"] == "ARTICLE_VERSION_CONFLICT"
    assert articles.get_editor_article(article_id)["ready_version"] is None


def test_ready_refuses_blocking_content_and_returns_editor_facing_context(api_server, api_store):
    article_id = _draft_for_ready(api_store)
    story_research_store.merge_research(
        "s-one",
        sources=[],
        facts=[],
        gaps=[{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}],
        assessed_at="2026-09-25T11:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="c4-api-gap",
    )

    status, payload = request(
        api_server,
        f"/api/v1/articles/{article_id}/ready",
        method="POST",
        body={"expectedVersion": 1},
    )
    assert status == 409
    assert payload["error"]["code"] == "SAFETY_BLOCKED"
    assert [row["rule"] for row in payload["error"]["warnings"]] == ["blocking_gap_open"]
    assert articles.get_editor_article(article_id)["ready_version"] is None
    assert _data(request(api_server, f"/api/v1/articles/{article_id}"))["state"] == "draft"


def test_ready_accepts_nothing_but_the_observed_version(api_server, api_store):
    article_id = _draft_for_ready(api_store)
    for body in (
        {},
        {"expectedVersion": 1, "warnings": []},
        {"expectedVersion": 1, "acceptWarnings": True},
        {"expectedVersion": 1, "validationDigest": "vd_whatever"},
    ):
        status, payload = request(
            api_server,
            f"/api/v1/articles/{article_id}/ready",
            method="POST",
            body=body,
        )
        assert status == 400, body
        assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert articles.get_editor_article(article_id)["ready_version"] is None


def test_a_ready_article_asks_for_the_final_decision_and_leaves_today_when_finalized(
    api_server, api_store
):
    article_id = _draft_for_ready(api_store)
    before = _data(request(api_server, "/api/v1/today"))["articlesRequiringAction"]
    assert article_id in [row["objectId"] for row in before]
    assert next(row for row in before if row["objectId"] == article_id)["nextAction"]["action"] == (
        "MARK_READY"
    )

    request(
        api_server,
        f"/api/v1/articles/{article_id}/ready",
        method="POST",
        body={"expectedVersion": 1},
    )
    # C5: `Готова` is not a dead end. It asks for the final editorial decision,
    # and it is that decision - not a silent disappearance - that removes the
    # Article from active attention.
    ready_rows = _data(request(api_server, "/api/v1/today"))["articlesRequiringAction"]
    assert (
        next(row for row in ready_rows if row["objectId"] == article_id)["nextAction"]["action"]
        == "FINALIZE"
    )
    assert _data(request(api_server, "/api/v1/articles?filter=ready"))["articles"][0]["id"] == (
        article_id
    )

    status, payload = request(
        api_server,
        f"/api/v1/articles/{article_id}/finalize",
        method="POST",
        body={"expectedVersion": 1},
        headers={"Idempotency-Key": "today-finalize"},
    )
    assert status == 200
    assert payload["data"]["archivePath"] == f"/archive/{article_id}"

    after = _data(request(api_server, "/api/v1/today"))["articlesRequiringAction"]
    assert article_id not in [row["objectId"] for row in after]
    # A finalized Article is not active any more, and there is no fourth filter
    # under Статии: it exists only in Архив.
    active = _data(request(api_server, "/api/v1/articles"))["articles"]
    assert article_id not in [row["id"] for row in active]
    assert _data(request(api_server, "/api/v1/articles?filter=ready"))["articles"] == []
    assert [row["id"] for row in _data(request(api_server, "/api/v1/archive"))["articles"]] == [
        article_id
    ]


# ------------------------------------------- V1.1-A evidence bootstrap over HTTP


def _substitute_research_network(monkeypatch, *, text: str = "", results: bool = True):
    """Substitute ONLY the two external edges: the search provider and the opener.

    Everything else stays real: the operation registry and its token, the real
    worker thread, the real HTTP surface, the research store and the projection.
    """
    from editor_assistant.sources import web_fetch
    from editor_assistant.workflow import search as search_mod

    page_text = text or (
        "Общинският съвет в Царево връчи званията почетен гражданин. "
        "Съобщението е на 25 септември 2026 г."
    )

    class Provider:
        name = "fake"

        def search(self, query):
            if not results:
                return {"provider": "fake", "query": query, "status": "NO_RESULTS", "results": []}
            return {
                "provider": "fake",
                "query": query,
                "status": "SEARCH_OK",
                "results": [
                    {
                        "rank": 1,
                        "title": "Официален",
                        "url": "https://official.example.test/a",
                        "snippet": "s",
                    },
                    {
                        "rank": 2,
                        "title": "Втори",
                        "url": "https://second.example.test/b",
                        "snippet": "s",
                    },
                ],
            }

    def fetch_page(url, **_kwargs):
        return {
            "url": url,
            "final_url": url,
            "status": 200,
            "content_type": "text/html; charset=utf-8",
            "bytes": len(page_text),
            "text": page_text,
        }

    monkeypatch.setattr(
        search_mod, "provider_chain", lambda capability=None, env=None: ([Provider()], [])
    )
    monkeypatch.setattr(web_fetch, "fetch_page", fetch_page)


def test_unassessed_story_dto_is_honest_and_offers_research(api_server, api_store):
    detail = _data(request(api_server, "/api/v1/stories/s-one"))

    assert detail["factsAndSources"] == []
    assert detail["missingInformation"] == {
        "items": [],
        "assessedAt": None,
        "evidenceStatus": "unassessed",
    }
    # V1.1-A §11: the first round must not require a pre-existing gap.
    assert "RESEARCH_MORE" in detail["availableActions"]

    # A malformed idempotency key is still refused before any work starts.
    status, payload = request(
        api_server,
        "/api/v1/stories/s-one/research",
        method="POST",
        headers={"Idempotency-Key": "bad key with spaces"},
    )
    assert status == 400
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_first_research_round_over_http_bootstraps_without_a_preexisting_gap(
    api_server, api_store, monkeypatch
):
    from editor_assistant.workflow import story_operations

    story_operations.clear()
    _substitute_research_network(monkeypatch)

    status, payload = request(
        api_server,
        "/api/v1/stories/s-one/research",
        method="POST",
        headers={"Idempotency-Key": "v11a-bootstrap"},
    )
    assert status == 202
    token = payload["data"]["operationToken"]
    assert token.startswith("op_")

    operation = _await(api_server, token)
    assert operation["status"] == "succeeded", operation

    assessed = _data(request(api_server, "/api/v1/stories/s-one"))
    assert assessed["missingInformation"]["evidenceStatus"] == "assessed"
    assert assessed["missingInformation"]["assessedAt"]
    assert len(assessed["factsAndSources"]) >= 1
    for fact in assessed["factsAndSources"]:
        assert fact["source"]["url"].startswith("https://")
        assert fact["locator"]
    # The internal research vocabulary and provider traces never cross the API.
    serialized = json.dumps(assessed, ensure_ascii=False)
    for forbidden in (
        "search_runs",
        "bundle",
        "operationToken",
        "research_question",
        "provider_chain",
    ):
        assert forbidden not in serialized


def test_research_that_finds_nothing_persists_an_explicit_gap(api_server, api_store, monkeypatch):
    from editor_assistant.workflow import story_operations

    story_operations.clear()
    _substitute_research_network(monkeypatch, results=False)

    status, payload = request(
        api_server,
        "/api/v1/stories/s-one/research",
        method="POST",
        headers={"Idempotency-Key": "v11a-insufficient"},
    )
    assert status == 202
    operation = _await(api_server, payload["data"]["operationToken"])
    assert operation["status"] == "succeeded", operation

    detail = _data(request(api_server, "/api/v1/stories/s-one"))
    assert detail["missingInformation"]["evidenceStatus"] == "assessed"
    assert detail["missingInformation"]["assessedAt"]
    assert detail["missingInformation"]["items"], "a completed round must persist a gap"
    # Never the false clean state: `assessed` with zero facts AND zero gaps.
    assert not (detail["factsAndSources"] == [] and detail["missingInformation"]["items"] == [])


def test_assessed_clean_basis_offers_no_research_and_refuses_the_command(api_server, api_store):
    story_research_store.merge_research(
        "s-one",
        sources=[
            {
                "id": "vestnik",
                "name": "Вестник",
                "url": "https://vestnik.example.test/2026/budget",
            }
        ],
        facts=[
            {
                "id": "fact_money",
                "text": "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
                "sourceId": "vestnik",
                "locator": "Протокол, т. 4",
            }
        ],
        gaps=[],
        assessed_at="2026-09-25T08:45:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="v11a-clean-basis",
    )

    detail = _data(request(api_server, "/api/v1/stories/s-one"))
    assert detail["missingInformation"]["evidenceStatus"] == "assessed"
    assert "RESEARCH_MORE" not in detail["availableActions"]

    status, payload = request(
        api_server,
        "/api/v1/stories/s-one/research",
        method="POST",
        headers={"Idempotency-Key": "v11a-clean-refusal"},
    )
    assert status == 409
    assert payload["error"]["code"] == "INVALID_TRANSITION"


# --------------------------------------------------------------------------
# V1.2-G2: the two narrow Story-projection additions
# --------------------------------------------------------------------------


def test_story_detail_carries_the_independent_publisher_count(api_server, api_store):
    """§3/§39: the count the page shows comes from the existing computation.

    `story_store.metrics` already counts independent publishers for Today. The
    Story detail now surfaces that same number, so React never counts a source
    and never invents one. No new semantics and no new store: the list
    projection is deliberately unchanged, because only the workspace needs it.
    """
    detail = _data(request(api_server, "/api/v1/stories/s-one"))
    store = story_store.read_store(api_store["stories"])
    story = story_store.story_by_id(store, "s-one")
    items = {row["item_id"]: row for row in inbox_store.read_items(api_store["inbox"])}
    assert detail["publisherCount"] == story_store.metrics(story, items)["publisher_count"]
    # The Stories list keeps its own shape; the addition is workspace-only.
    listed = _data(request(api_server, "/api/v1/stories?filter=all"))["stories"][0]
    assert "publisherCount" not in listed


def test_story_detail_reports_each_related_articles_canonical_state(api_server, api_store):
    """§22/§39: the state word is the same decision, not a second one.

    A Preparation Article reads `preparation` here and in its own workspace; a
    finalized Article reads `null`, because it has left the active workflow. The
    projection adds the existing derived value — it does not add a state.
    """
    article_id = api_store["article"]["article_id"]
    detail = _data(request(api_server, "/api/v1/stories/s-one"))
    related = next(row for row in detail["relatedArticles"] if row["id"] == article_id)
    workspace = _data(request(api_server, f"/api/v1/articles/{article_id}"))
    assert related["state"] == workspace["state"] == "preparation"

    articles.save_article_content(
        article_id,
        expected_version=0,
        title="Работа",
        body="Общинският съвет одобри бюджета за ремонта.",
        root=api_store["root"] / "editorial",
    )
    records = articles.read_editor_articles()
    for row in records:
        if row["article_id"] != article_id:
            continue
        row["editorial_focus"] = "Да разкажем какво се е променило в бюджета."
        row["focus_confirmed_at"] = "2026-09-25T09:30:00Z"
        row["draft_established_version"] = 1
        row["ready_version"] = 1
        row["ready_at"] = "2026-09-25T09:59:00Z"
        row["ready_validation_digest"] = "digest-for-the-proof"
        row["finalized_at"] = "2026-09-25T10:00:00Z"
    articles.save_editor_articles(records)
    archived = _data(request(api_server, "/api/v1/stories/s-one"))
    finalized = next(row for row in archived["relatedArticles"] if row["id"] == article_id)
    assert finalized["state"] is None
    assert finalized["finalizedAt"] == "2026-09-25T10:00:00Z"
