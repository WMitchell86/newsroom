"""Phase B1: real HTTP contract tests for the editor JSON boundary."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote

import pytest

from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import editor_article_store as articles
from editor_assistant.workflow import editor_projections as projections
from editor_assistant.workflow import (
    inbox_store,
    live_store,
    story_operations,
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
    assert article["editorialFocus"]["confirmedAt"] is not None
    assert article["preparation"] == {
        "focusConfirmed": True,
        # §D2: the quiet alternatives travel with the projection, so the page
        # never derives them. They are suggestions, not a wizard step.
        "focusAlternatives": article["preparation"]["focusAlternatives"],
        # V1.1-B: the backend now reports WHY a Draft is unavailable, instead of
        # leaving React to guess. The reason comes from the one shared decision.
        "draftReadiness": {
            "code": "STORY_UNASSESSED",
            "message": "За чернова първо е нужно проучване на историята.",
        },
        "blockingGaps": [],
        "nonBlockingGaps": [],
        "draftEligible": False,
        # V1.1-C: no generation has been attempted, so there is no recovery
        # context and the manual editor is not offered.
        "draftFailure": None,
        "availableActions": ["CHANGE_FOCUS", "RESEARCH_MORE"],
    }
    # V1.2-G4.3 §C3: there are no Focus alternatives any more. The projection
    # still carries the field (so the API shape is unchanged) and it is empty -
    # the deterministic variants were templates rather than real choices, and the
    # approved contract is that zero alternatives is acceptable.
    assert article["preparation"]["focusAlternatives"] == []
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
    # V1.2-G4.1 §B6: with no opened publication behind the title, the honest
    # reason is the absence of material — not the open question, which no longer
    # refuses a Draft at all. Both questions are still shown.
    assert blocked["preparation"]["draftReadiness"]["code"] == "NO_DRAFT_MATERIAL"
    assert (
        blocked["preparation"]["draftReadiness"]["message"]
        == "Няма достатъчно изходен материал за чернова."
    )
    assert blocked["preparation"]["blockingGaps"][0]["question"] == "Кога започва изпълнението?"
    assert (
        blocked["preparation"]["nonBlockingGaps"][0]["question"] == "Кой е основният заинтересован?"
    )
    assert blocked["availableActions"] == ["CHANGE_FOCUS", "RESEARCH_MORE"]
    assert blocked["nextAction"]["action"] == "RESEARCH_MORE"
    assert blocked["nextAction"]["reasonCode"] == "NO_DRAFT_MATERIAL"
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
    assert (
        unconfirmed[1]["error"]["message"] == "Добавете редакционен фокус, за да създадете чернова."
    )
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


def test_an_open_gap_no_longer_refuses_the_draft_command(api_server, api_store, monkeypatch):
    article_id = _ready_article(api_store, monkeypatch)
    # V1.2-G4.1 §B1: an open question on a Story that already has real promoted
    # facts is NO LONGER a refusal — this is the owner's exact screen. The Draft
    # command is accepted and the generation runs.
    story_research_store.merge_research(
        "s-one",
        sources=[],
        facts=[],
        gaps=[{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}],
        assessed_at="2026-09-25T11:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id="api-gap",
    )
    accepted = request(
        api_server,
        f"/api/v1/articles/{article_id}/draft",
        method="POST",
        headers={"Idempotency-Key": "http-gap-open"},
    )
    assert accepted[0] == 202, accepted[1]
    operation = _await(api_server, accepted[1]["data"]["operationToken"])
    assert operation["status"] == "succeeded", operation
    assert operation["result"]["state"] == "draft"
    assert operation["result"]["content"]["body"].strip()
    # §C2: an open question means `Готова` is not available. The Draft exists and
    # is fully editable; what it cannot do yet is be marked Ready.
    current = _data(request(api_server, f"/api/v1/articles/{article_id}"))
    assert current["state"] == "draft"
    assert "EDIT" in current["availableActions"]
    assert "MARK_READY" not in current["availableActions"]


def test_a_stale_draft_action_is_refused_as_a_version_conflict(api_server, api_store, monkeypatch):
    """A stale client action after a real edit never silently overwrites text."""
    article_id = _ready_article(api_store, monkeypatch)
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
        # V1.2-G4.1 §B3: the publications that really were opened, with the
        # authority the editor configured for them. The editor can therefore see
        # what a Draft would be written from, which is the whole point of showing
        # a warning instead of refusing.
        "openedSources": [],
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


# --------------------------------------------------------------------------
# V1.2-G4.5 — per-role health, the cause behind the grouping warning
# --------------------------------------------------------------------------


def test_health_names_the_roles_that_cannot_be_routed_at_all(monkeypatch):
    """The symptom was already on screen; the cause was not.

    Today renders a grouping warning when grouping degrades, which is right. But
    nothing in the product said that a ROLE had no routable path — and a role
    with no route does not fail loudly, it silently does less. This is the one
    surface reporting the route side, and it carries the command that fixes a
    wrong mark, so the editor is never left holding a diagnosis with no remedy.
    """
    from editor_assistant.workflow import editor_application as app

    def plan_for(role, policy=None, **kw):
        if role == "story":
            return {
                "routes": [
                    {"model": "m1", "eligible": False, "reason": "EXHAUSTED"},
                    {"model": "m2", "eligible": False, "reason": "EXHAUSTED"},
                ],
                "on_exhausted": "conservative",
            }
        return {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        }

    from editor_assistant.drafting import model_policy, model_router

    monkeypatch.setattr(model_router, "plan_routes", plan_for)
    monkeypatch.setattr(model_policy, "load_policy", lambda: {"roles": {"story": {}, "draft": {}}})

    health = app.read_health()

    assert health["ok"] is False
    assert health["unroutableRoles"] == ["story"]
    story = next(r for r in health["roles"] if r["role"] == "story")
    assert (story["eligible"], story["total"]) == (0, 2)
    assert story["onExhausted"] == "conservative"
    assert "validate" in health["remedy"]


def test_health_stays_quiet_when_every_role_is_routable(monkeypatch):
    """A permanent warning is a warning the editor learns to ignore."""
    from editor_assistant.drafting import model_policy, model_router
    from editor_assistant.workflow import editor_application as app

    monkeypatch.setattr(
        model_router,
        "plan_routes",
        lambda role, policy=None, **kw: {
            "routes": [{"model": "m0", "eligible": True, "reason": ""}],
            "on_exhausted": "conservative",
        },
    )
    monkeypatch.setattr(model_policy, "load_policy", lambda: {"roles": {"draft": {}}})

    health = app.read_health()
    assert health["ok"] is True
    assert health["unroutableRoles"] == []


# ------------------------------------------------------- PART: `Пренапиши` (G4.18)


@pytest.fixture
def rewrite_calls(monkeypatch):
    """Capture what the boundary forwards, so the test asserts the CONTRACT.

    The rewrite worker itself is exercised end-to-end in
    `tests/test_natural_draft_loop.py`. What is pinned here is the JSON
    boundary: which request bodies are accepted, which are refused, and what
    each accepted body turns into.
    """
    seen: list[dict] = []

    def fake_start(article_id, comment, *, idempotency_key="", mode="", length=""):
        seen.append(
            {
                "article_id": article_id,
                "comment": comment,
                "mode": mode,
                "length": length,
                "idempotency_key": idempotency_key,
            }
        )
        return {"operationToken": f"op-{len(seen)}"}

    monkeypatch.setattr(app, "start_article_rewrite", fake_start)
    return seen


def _rewrite(api_server, article_id, body, *, key="rk-1"):
    return request(
        api_server,
        f"/api/v1/articles/{article_id}/rewrite",
        method="POST",
        body=body,
        headers={"Idempotency-Key": key},
    )


def test_rewrite_accepts_the_comment_alone_because_that_is_what_the_client_sends(
    api_server, api_store, rewrite_calls
):
    """G4.18: an untouched control is OMITTED, so it must not be REQUIRED.

    `client.ts` sends `{comment}` plus only the controls the editor actually
    chose. Measured before the fix: that exact body came back
    `400 VALIDATION_ERROR`, because the endpoint used the exact-match `_body`
    and therefore demanded both new keys be present. The editor who changed
    nothing — the ordinary rewrite — could not rewrite at all.
    """
    article_id = api_store["article"]["article_id"]

    status, payload = _rewrite(api_server, article_id, {"comment": "По-кратко."})

    assert status == 202, payload
    assert payload["data"]["operationToken"] == "op-1"
    assert rewrite_calls == [
        {
            "article_id": article_id,
            "comment": "По-кратко.",
            "mode": "",
            "length": "",
            "idempotency_key": "rk-1",
        }
    ], "an untouched control means the automatic behaviour, not a refusal"


def test_rewrite_accepts_either_control_on_its_own(api_server, api_store, rewrite_calls):
    """G4.18: `Дължина` and `Формат` are independent, so each may travel alone.

    Also a 400 before the fix. They are separate `<select>` elements with
    separate defaults, so "the editor set the length and left the format" is an
    ordinary state, not a malformed request.
    """
    article_id = api_store["article"]["article_id"]

    assert _rewrite(api_server, article_id, {"comment": "Разшири.", "length": "full"})[0] == 202
    assert rewrite_calls[-1]["length"] == "full" and rewrite_calls[-1]["mode"] == ""

    assert (
        _rewrite(
            api_server,
            article_id,
            {"comment": "Разшири.", "mode": "MODE_STANDARD_NEWS"},
            key="rk-2",
        )[0]
        == 202
    )
    assert rewrite_calls[-1]["mode"] == "MODE_STANDARD_NEWS"
    assert rewrite_calls[-1]["length"] == ""


def test_rewrite_forwards_both_controls_together(api_server, api_store, rewrite_calls):
    """G4.18: the case the feature exists for — both controls, both honoured."""
    article_id = api_store["article"]["article_id"]

    status, _ = _rewrite(
        api_server,
        article_id,
        {"comment": "Разшири до пълна статия.", "mode": "MODE_STANDARD_NEWS", "length": "full"},
    )

    assert status == 202
    assert rewrite_calls[-1]["mode"] == "MODE_STANDARD_NEWS"
    assert rewrite_calls[-1]["length"] == "full"
    assert rewrite_calls[-1]["comment"] == "Разшири до пълна статия."


def test_rewrite_still_refuses_an_unknown_control_instead_of_falling_back(
    api_server, api_store, rewrite_calls
):
    """G4.18: a value the product does not offer is a 400, never a guess.

    This is the property the whole feature rests on — the original defect was a
    SILENT fallback to `MODE_BRIEF`. Widening the accepted key set must not have
    widened the accepted VALUE set.
    """
    article_id = api_store["article"]["article_id"]

    for body in (
        {"comment": "Разшири.", "length": "huge"},
        {"comment": "Разшири.", "mode": "MODE_MADE_UP"},
        {"comment": "Разшири.", "length": "Full"},
    ):
        status, payload = _rewrite(api_server, article_id, body)
        assert status == 400, (body, payload)
        assert payload["error"]["code"] == "VALIDATION_ERROR"

    assert rewrite_calls == [], "a refused control must reach no model call"


def test_rewrite_keeps_its_key_set_closed_and_its_comment_required(
    api_server, api_store, rewrite_calls
):
    """G4.18: optional does not mean open. `comment` is still the request."""
    article_id = api_store["article"]["article_id"]

    # An unregistered field is still refused by name.
    status, payload = _rewrite(
        api_server, article_id, {"comment": "Разшири.", "evidence": ["fact_x"]}
    )
    assert status == 400 and payload["error"]["code"] == "VALIDATION_ERROR"

    # An absent or blank comment is still refused: the words ARE the request.
    for body in ({"length": "full"}, {"comment": "   ", "length": "full"}):
        assert _rewrite(api_server, article_id, body)[0] == 400

    # The idempotency key is still required, and an empty body is still a 400.
    assert (
        request(
            api_server,
            f"/api/v1/articles/{article_id}/rewrite",
            method="POST",
            body={"comment": "Разшири."},
        )[0]
        == 400
    )

    assert rewrite_calls == []


# ------------------------------- PART: the Operations index (V1.2-G4.38)


def test_operations_name_their_subject_and_link_to_it(api_server, api_store):
    """G4.38: every row says what it was ABOUT and takes the editor there.

    Measured on the editor's own Operations page before this: a row read
    «Чернова · art_85e69497b45cdbe» — an internal id where a headline belongs —
    and only 2 of the 6 scope shapes the application actually creates produced a
    link at all. `Проучване` and «Чернова по история» had a Story id sitting in
    the scope string the whole time and rendered nothing clickable, because the
    client kept its own partial copy of the scope list.
    """
    article_id = api_store["article"]["article_id"]
    articles.update_article_title(article_id, 0, "Съветът одобри графика за ремонта")
    articles.update_editor_focus(article_id, "Да обясним решението.")

    story_operations.start("article-draft:" + article_id, "", lambda: {"ok": True})
    story_operations.start("article-rewrite:" + article_id, "", lambda: {"ok": True})
    story_operations.start("quick-draft:s-one", "", lambda: {"ok": True})
    story_operations.start("s-one", "", lambda: {"ok": True})  # research
    story_operations.start("today-refresh", "", lambda: {"ok": True})
    story_operations.start("desk-quick-drafts", "", lambda: {"ok": True})
    for token in [r["operationToken"] for r in story_operations.recent()]:
        for _ in range(200):
            if story_operations.get(token)["status"] == "succeeded":
                break
            time.sleep(0.01)

    rows = _data(request(api_server, "/api/v1/operations"))["operations"]
    by_scope = {row["storyId"]: row for row in rows}

    for scope in (
        "article-draft:" + article_id,
        "article-rewrite:" + article_id,
        "quick-draft:s-one",
        "s-one",
    ):
        row = by_scope[scope]
        assert row["topic"], f"{scope} must name its subject, not its id"
        assert article_id not in row["topic"], "a title is never an internal id"
        assert row["topicHref"], f"{scope} must be clickable"
        assert row["topicHref"] in {f"/articles/{article_id}", "/stories/s-one"}
        assert row["kind"], f"{scope} must be named in the editor's words"

    # A Story-scoped operation links to the Story page, which has existed all
    # along — the old comment claiming a Story id "is not a link" was the
    # reason two of these rows had nowhere to go.
    assert by_scope["s-one"]["topicHref"] == "/stories/s-one"
    assert by_scope["quick-draft:s-one"]["topicHref"] == "/stories/s-one"
    assert by_scope["quick-draft:s-one"]["kind"] == "Чернова по история"
    assert by_scope["s-one"]["kind"] == "Проучване"

    # The desk-wide action is NAMED even though it has no single subject to
    # open. Falling through to the generic «Операция» was the other half of the
    # bug: unlinked is honest here, unnamed is not.
    assert by_scope["desk-quick-drafts"]["kind"] == "Чернови по всички истории"
    assert by_scope["desk-quick-drafts"]["topicHref"] == ""
    assert by_scope["today-refresh"]["kind"] == "Обновяване на новините"


def test_operations_report_when_the_work_ran(api_server, api_store, monkeypatch):
    """G4.38: the index carries a wall clock, because none existed to show."""
    rows = _data(request(api_server, "/api/v1/operations"))["operations"]

    token = story_operations.start("s-one", "", lambda: {"ok": True})[0]
    for _ in range(200):
        if story_operations.get(token)["status"] == "succeeded":
            break
        time.sleep(0.01)

    row = next(
        r
        for r in _data(request(api_server, "/api/v1/operations"))["operations"]
        if r["operationToken"] == token
    )
    started = datetime.fromisoformat(row["startedAt"])
    finished = datetime.fromisoformat(row["finishedAt"])
    assert started <= finished
    assert finished <= datetime.now(timezone.utc)
    assert all("startedAt" in r and "finishedAt" in r for r in rows + [row])


def test_operations_do_not_invent_a_topic_for_a_deleted_article(api_server, api_store):
    """G4.38: an unresolvable subject stays empty rather than being decorated.

    The id is right there and would make a convincing-looking row. It is still
    not a headline, and printing it would be the id-as-title lie all over again.
    """
    token = story_operations.start("article-draft:art_gone123", "", lambda: {"ok": True})[0]
    for _ in range(200):
        if story_operations.get(token)["status"] == "succeeded":
            break
        time.sleep(0.01)

    row = next(
        r
        for r in _data(request(api_server, "/api/v1/operations"))["operations"]
        if r["operationToken"] == token
    )
    assert row["topic"] == ""
    assert row["topicHref"] == ""
    assert row["kind"] == "Чернова", "it still says what KIND of work this was"


def test_operations_survive_an_unreadable_story_store(api_server, api_store):
    """G4.38 review: a broken store must not take this page down.

    `/operations` used to read only the in-memory registry and could not fail on
    a store. The topic projection added store reads, and `read_store` raises
    `StoryStoreError` — which surfaced as a generic `500 INTERNAL_ERROR` logged
    as "Unhandled editor API failure", i.e. the server treating its own ordinary
    read path as a crash.

    That is backwards: «Операции» is the page an editor opens BECAUSE something
    else is broken. It must degrade to "what kind of work was this" and keep
    answering.
    """
    token = story_operations.start("s-one", "", lambda: {"ok": True})[0]
    for _ in range(200):
        if story_operations.get(token)["status"] == "succeeded":
            break
        time.sleep(0.01)

    stories_path = api_store["stories"]
    backup = stories_path.read_text(encoding="utf-8")
    stories_path.write_text("{ not json at all", encoding="utf-8")
    try:
        status, payload = request(api_server, "/api/v1/operations")
    finally:
        stories_path.write_text(backup, encoding="utf-8")

    assert status == 200, payload
    row = next(r for r in payload["data"]["operations"] if r["operationToken"] == token)
    assert row["kind"] == "Проучване", "the kind does not depend on any store"
    assert row["topic"] == "" and row["topicHref"] == "", "and nothing is invented"


def test_operations_read_each_store_once_per_page_not_once_per_row(
    api_server, api_store, monkeypatch
):
    """G4.38 review: the topic projection must not scale its reads with the rows.

    Measured on the first version: a 12-row page read the Story store 12 times
    and the whole inbox 12 times — 134 ms, on the one surface that re-polls
    every 5 seconds.
    """
    for index in range(11):
        token = story_operations.start(f"s-bulk{index}", "", lambda: {"ok": True})[0]
        for _ in range(200):
            if story_operations.get(token)["status"] == "succeeded":
                break
            time.sleep(0.01)

    counts = {"stories": 0, "items": 0}
    from editor_assistant.workflow import story_store

    real_read_store = story_store.read_store
    real_items = app._story_items

    def counting_read_store(*args, **kwargs):
        counts["stories"] += 1
        return real_read_store(*args, **kwargs)

    def counting_items(*args, **kwargs):
        counts["items"] += 1
        return real_items(*args, **kwargs)

    monkeypatch.setattr(story_store, "read_store", counting_read_store)
    monkeypatch.setattr(app, "_story_items", counting_items)

    status, payload = request(api_server, "/api/v1/operations")

    assert status == 200
    rows = [r for r in payload["data"]["operations"] if r["storyId"].startswith("s-")]
    assert len(rows) >= 11, "the bulk rows are there; the read count is the point"
    assert counts == {"stories": 1, "items": 1}, f"store reads per page load: {counts}"


# --------------------------------- PART: `AI и модели` — the paid switch (G4.39)


def test_model_settings_report_the_switch_and_what_it_would_unlock(api_server, api_store):
    """G4.39: the editor can read the paid state and see what turning it on means.

    The switch existed only on the server-rendered `/models` page, which the
    editor's own Settings had no link to. BACKLOG recorded `AI и модели` as
    "still unimplemented" — this is the real screen behind that name.
    """
    payload = _data(request(api_server, "/api/v1/settings/models"))

    assert payload["paidEnabled"] is False, "the shipped default is paid OFF"
    assert payload["softPaidBudgetUsdDay"] >= 0
    assert payload["paidCostTodayUsd"] >= 0
    assert {r["role"] for r in payload["roles"]} >= {"draft", "story", "angle"}
    # What ON would unlock is named, so the consequence is visible before the
    # switch is flipped — and it is the real list from the policy, not a copy.
    assert payload["paidRoutes"], "the policy declares paid routes; name them"
    assert all({"role", "provider", "model"} <= set(r) for r in payload["paidRoutes"])


def test_the_operator_can_switch_paid_models_on_and_off(api_server, api_store, monkeypatch):
    """G4.39: the switch persists, and the response is the STORED state.

    Echoing the request back would let the screen claim "on" while the policy
    still said off, so the response is re-read from the policy.
    """
    from editor_assistant.drafting import model_policy

    on = _data(
        request(
            api_server,
            "/api/v1/settings/models",
            method="PUT",
            body={"paidEnabled": True, "softPaidBudgetUsdDay": 3.5},
        )
    )
    assert on["paidEnabled"] is True
    assert on["softPaidBudgetUsdDay"] == 3.5
    # Re-read through the policy the router uses, not through our own response.
    assert model_policy.load_policy()["global"]["paid_enabled"] is True
    assert model_policy.load_policy()["global"]["soft_paid_budget_usd_day"] == 3.5
    # And the screen reflects it on a fresh read.
    assert _data(request(api_server, "/api/v1/settings/models"))["paidEnabled"] is True

    off = _data(
        request(api_server, "/api/v1/settings/models", method="PUT", body={"paidEnabled": False})
    )
    assert off["paidEnabled"] is False
    assert model_policy.load_policy()["global"]["paid_enabled"] is False
    # The budget survives a switch being turned off; it is a separate decision.
    assert off["softPaidBudgetUsdDay"] == 3.5


def test_the_paid_switch_refuses_what_it_cannot_mean(api_server, api_store):
    """G4.39: a word, a missing field and an unbounded budget are all 400s.

    `"false"` is truthy in Python; a screen that read the operator's word as
    "turn paid models ON" is the worst failure this switch can have.
    """
    for body in (
        {"paidEnabled": "false"},  # the dangerous one: truthy string
        {"paidEnabled": 1},  # int is not a decision here
        {},  # no decision at all
        {"paidEnabled": True, "softPaidBudgetUsdDay": "lots"},
        {"paidEnabled": True, "softPaidBudgetUsdDay": -1},
        {"paidEnabled": True, "softPaidBudgetUsdDay": 10_000},
        {"paidEnabled": True, "somethingElse": 1},  # the key set stays closed
    ):
        status, payload = request(api_server, "/api/v1/settings/models", method="PUT", body=body)
        assert status == 400, (body, payload)
        assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_a_refused_switch_does_not_change_the_stored_state(api_server, api_store):
    """G4.39: a rejected edit leaves the policy exactly as it was."""
    from editor_assistant.drafting import model_policy

    before = model_policy.load_policy()["global"].get("paid_enabled")
    request(
        api_server,
        "/api/v1/settings/models",
        method="PUT",
        body={"paidEnabled": True, "softPaidBudgetUsdDay": 99_999},
    )
    assert model_policy.load_policy()["global"].get("paid_enabled") == before


def test_model_settings_is_a_known_path_so_a_wrong_method_is_405(api_server):
    """G4.39: an editor posting here gets "wrong verb", not "no such page"."""
    assert request(api_server, "/api/v1/settings/models", method="POST", body={})[0] == 405
