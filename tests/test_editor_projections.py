"""Phase A: pure editor projections and derived Today eligibility."""

from __future__ import annotations

from editor_assistant.workflow import editor_projections as projections


def _article(**over):
    base = {
        "article_id": "art-one",
        "story_id": "s-one",
        "working_title": "Заглавие",
        "editorial_focus": "Какво ще разкажем.",
        "focus_confirmed_at": "2026-09-25T08:00:00Z",
        "created_at": "2026-09-25T08:00:00Z",
        "updated_at": "2026-09-25T09:00:00Z",
        "content_version": 1,
        "content_path": "editor_articles/art-one/v00000001.json",
        "internal_refs": {
            "idea_id": "I-1",
            "evidence_id": "E-1",
            "case_id": "C-1",
            "draft_id": "D-1",
        },
        "ready_version": None,
        "ready_validation_digest": None,
        "ready_at": None,
        "finalized_at": None,
        "draft_established_version": None,
        "generated_content_version": None,
    }
    base.update(over)
    return base


def _content(**over):
    base = {
        "article_id": "art-one",
        "title": "Заглавие",
        "body": "",
        "content_version": 1,
        "updated_at": "2026-09-25T09:00:00Z",
    }
    base.update(over)
    return base


def test_article_state_derivation_has_exactly_three_active_states_and_no_fourth():
    assert projections.derive_article_state(_article(), _content(), None) == "preparation"
    assert projections.derive_article_state(_article(), _content(body="Текст"), None) == "draft"
    ready = _article(
        ready_version=1,
        ready_at="2026-09-25T09:01:00Z",
        ready_validation_digest="digest-1",
    )
    assert projections.derive_article_state(ready, _content(body="Текст"), "digest-1") == "ready"
    assert (
        projections.derive_article_state(
            ready, _content(body="Промяна", content_version=2), "digest-1"
        )
        == "draft"
    )
    assert projections.derive_article_state(ready, _content(body="Текст"), "digest-2") == "draft"
    assert (
        projections.derive_article_state(
            {**ready, "finalized_at": "2026-09-25T10:00:00Z"}, _content(body="Текст"), "digest-1"
        )
        is None
    )


def test_article_projection_exposes_editor_contract_and_hides_internal_artifacts():
    ready = _article(
        ready_version=1,
        ready_at="2026-09-25T09:01:00Z",
        ready_validation_digest="digest-1",
    )
    projected = projections.project_editor_article(ready, _content(body="Текст"), "digest-1")
    forbidden = {
        "internal_refs",
        "content_path",
        "idea_id",
        "evidence_id",
        "prepared",
        "case_id",
        "model",
        "provider",
    }
    assert forbidden.isdisjoint(projected)
    assert projected["id"] == "art-one"
    assert projected["story"] == {"id": "s-one"}
    assert projected["state"] == "ready"
    assert projected["focus"] == {
        "text": "Какво ще разкажем.",
        "confirmed_at": "2026-09-25T08:00:00Z",
    }
    assert projected["content"] == {"title": "Заглавие", "body": "Текст", "version": 1}
    assert projected["readiness"]["is_current"] is True
    assert set(projected["content"]) == {"title", "body", "version"}
    assert set(projected["focus"]) == {"text", "confirmed_at"}
    assert set(projected["readiness"]) == {"is_current", "ready_version", "ready_at"}
    assert set(projected["timestamps"]) == {"created_at", "updated_at", "finalized_at"}


def test_focus_proposal_is_unconfirmed_and_editor_change_refreshes_confirmation():
    proposed = _article(editorial_focus="Предложение", focus_confirmed_at=None)
    assert projections.derive_article_state(proposed, _content(body="Текст"), None) == "draft"
    projection = projections.project_editor_article(proposed, _content(body="Текст"), None)
    assert projection["focus"]["confirmed_at"] is None
    assert projections.focus_is_confirmed(proposed) is False


def test_ready_checkpoint_cannot_override_unconfirmed_focus():
    invalid_ready = _article(
        focus_confirmed_at=None,
        ready_version=1,
        ready_at="2026-09-25T09:01:00Z",
        ready_validation_digest="digest-1",
    )
    assert (
        projections.derive_article_state(invalid_ready, _content(body="Текст"), "digest-1")
        == "draft"
    )
    assert projections.focus_is_confirmed(invalid_ready) is False
    assert projections.focus_is_confirmed(_article()) is True


def _story(status="SEEN", developments=(("dev-a", "2026-09-24T08:00:00Z"),)):
    development_rows = [
        {
            "item_id": dev_id,
            "publication_key": f"p-{dev_id}",
            "relation": "NEW_DEVELOPMENT",
            "added_at": at,
        }
        for dev_id, at in developments
    ]
    return {
        "story_id": "s-one",
        "status": status,
        "needs_review": status == "NEW",
        "members": [
            {"item_id": "origin", "relation": "ORIGIN", "added_at": "2026-09-20T08:00:00Z"},
            *development_rows,
        ],
    }


def test_story_projection_and_followed_development_attention_are_pure():
    dev_a = projections.development_id_for("s-one", "dev-a")
    dev_b = projections.development_id_for("s-one", "dev-b")
    meta = {
        "story_id": "s-one",
        "followed": True,
        "last_reviewed_at": "2026-09-24T09:00:00Z",
        "reviewed_development_ids": [dev_a],
    }
    story = _story(
        developments=(("dev-a", "2026-09-24T08:00:00Z"), ("dev-b", "2026-09-25T08:00:00Z"))
    )
    items = {
        "dev-b": {
            "item_id": "dev-b",
            "title": "Ново развитие",
            "summary": "Промяна",
            "discovered_at": "2026-09-25T08:00:00Z",
        }
    }
    projected = projections.project_story_editor(story, meta, items, [_article()])

    assert projected["followed"] is True
    assert projected["reviewed"] is True
    assert projected["ignored"] is False
    assert projected["unreviewed_development_ids"] == [dev_b]
    assert projected["unreviewed_development_count"] == 1
    assert projected["latest_development"]["id"] == dev_b
    assert projected["latest_development"]["publication_id"].startswith("pub_")
    assert projected["latest_development"]["publication_id"] != "p-dev-b"
    assert projected["latest_development"]["title"] == "Ново развитие"
    assert projected["latest_development"]["summary"] == "Промяна"
    assert projected["latest_development"]["changed_at"] == "2026-09-25T08:00:00Z"
    assert projected["related_articles"][0]["id"] == "art-one"
    assert projections.followed_story_has_development(story, meta) is True


def test_ignored_followed_story_stays_bookmarked_but_not_in_today():
    meta = {
        "story_id": "s-one",
        "followed": True,
        "last_reviewed_at": None,
        "reviewed_development_ids": [],
    }
    ignored = _story(status="IGNORED", developments=(("dev-new", "2026-09-25T08:00:00Z"),))
    assert projections.followed_story_has_development(ignored, meta) is False
    assert projections.derive_story_attention(ignored, meta) is None
    assert meta["followed"] is True


def test_new_and_reviewed_followed_story_today_rules():
    new_story = _story(status="NEW", developments=())
    new_meta = {
        "story_id": "s-one",
        "followed": False,
        "last_reviewed_at": None,
        "reviewed_development_ids": [],
    }
    assert projections.derive_story_attention(new_story, new_meta) == "NEW_STORY"

    reviewed = _story(developments=(("dev-a", "2026-09-25T08:00:00Z"),))
    reviewed_meta = {
        "story_id": "s-one",
        "followed": True,
        "last_reviewed_at": "2026-09-25T09:00:00Z",
        "reviewed_development_ids": [],
    }
    assert projections.derive_story_attention(reviewed, reviewed_meta) == "FOLLOWED_DEVELOPMENT"
    reviewed_meta["reviewed_development_ids"] = [projections.development_id_for("s-one", "dev-a")]
    assert projections.derive_story_attention(reviewed, reviewed_meta) is None


def test_reopened_new_story_is_not_hidden_by_historical_review_metadata():
    reopened = _story(status="NEW", developments=())
    metadata = {
        "story_id": "s-one",
        "followed": False,
        "last_reviewed_at": "2026-09-24T09:00:00Z",
        "reviewed_development_ids": [],
    }
    projected = projections.project_story_editor(reopened, metadata, {}, [])
    assert projected["reviewed"] is False
    assert projections.derive_story_attention(reopened, metadata) == "NEW_STORY"


def test_unreviewed_development_projection_is_newest_first():
    dev_a = projections.development_id_for("s-one", "dev-a")
    dev_b = projections.development_id_for("s-one", "dev-b")
    story = _story(
        developments=(("dev-a", "2026-09-24T08:00:00Z"), ("dev-b", "2026-09-25T08:00:00Z"))
    )
    metadata = {
        "story_id": "s-one",
        "followed": True,
        "last_reviewed_at": None,
        "reviewed_development_ids": [],
    }
    items = {
        "dev-a": {"item_id": "dev-a", "title": "A", "discovered_at": "2026-09-24T08:00:00Z"},
        "dev-b": {"item_id": "dev-b", "title": "B", "discovered_at": "2026-09-25T08:00:00Z"},
    }
    projected = projections.project_story_editor(story, metadata, items, [])
    assert projected["unreviewed_development_ids"] == [dev_b, dev_a]
    assert projected["latest_development"]["id"] == dev_b
    assert projections.unreviewed_development_ids(story, metadata) == [dev_b, dev_a]


def test_article_today_eligibility_never_persists_attention():
    preparation = _article()
    assert projections.article_today_eligible(
        preparation, _content(), None, concrete_next_action="SELECT_FOCUS"
    )
    assert not projections.article_today_eligible(
        preparation, _content(), None, concrete_next_action=None
    )

    draft = _article(content_version=2)
    body = _content(body="Текст", content_version=2)
    assert projections.article_today_eligible(draft, body, None, concrete_next_action="EDIT")
    finalized = {**draft, "finalized_at": "2026-09-25T10:00:00Z"}
    assert not projections.article_today_eligible(
        finalized, body, None, concrete_next_action="FINALIZE"
    )
