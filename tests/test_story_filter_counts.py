"""V1.2-G4.7 — the Stories filter counts must never invent a zero.

A zero next to «Следени» is a claim: "there are no followed stories". On a
427-story corpus that is a confident, wrong statement, and the first frontend
test could not see it because its mock omitted the `counts` key entirely
rather than sending the shape the server really sends.

Found by running the real function, not by reasoning about it: the first
request after a restart is frequently a searched one, which never measures
the counts, and the old shared default answered with four confident zeroes.
"""

import pytest

from editor_assistant.workflow import editor_application as app


@pytest.fixture(autouse=True)
def _clear_measurement():
    app.list_story_counts.__globals__  # touch, keeps the import honest
    if hasattr(app.list_stories, "last_counts"):
        delattr(app.list_stories, "last_counts")
    yield
    if hasattr(app.list_stories, "last_counts"):
        delattr(app.list_stories, "last_counts")


def test_no_measurement_reports_nothing_rather_than_zero():
    counts = app.list_story_counts()
    assert counts == {}, counts


def test_a_searched_listing_does_not_claim_counts(monkeypatch):
    """A query narrows the list, so it cannot measure the corpus."""
    called = {}

    def fake_read(path):
        called["path"] = path
        return {"version": 1, "stories": [], "overrides": {}}

    monkeypatch.setattr(app.story_store, "read_store", fake_read)
    monkeypatch.setattr(app, "_story_items", dict)
    app.list_stories("all", "търсене")
    assert app.list_story_counts() == {}


def test_an_unfiltered_listing_measures_all_four(monkeypatch):
    monkeypatch.setattr(app.story_store, "read_store",
                        lambda path: {"version": 1, "stories": [], "overrides": {}})
    monkeypatch.setattr(app, "_story_items", dict)
    app.list_stories("all", "")
    counts = app.list_story_counts()
    assert set(counts) == {"all", "followed", "developments", "ignored"}
    assert counts["all"] == 0  # an EMPTY corpus really is zero — this one is a fact
