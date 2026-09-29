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
    if hasattr(app.list_stories, "last_counts"):
        delattr(app.list_stories, "last_counts")
    yield
    if hasattr(app.list_stories, "last_counts"):
        delattr(app.list_stories, "last_counts")


def test_no_measurement_reports_nothing_rather_than_zero():
    # The counts now travel WITH the page from one call, so there is no
    # module-level slot a second request could overwrite between the two.
    rows, total, counts = app.list_stories_page("all", "търсене")
    assert counts == {}, counts


def test_a_searched_listing_does_not_claim_counts(monkeypatch):
    """A query narrows the list, so it cannot measure the corpus."""
    called = {}

    def fake_read(path):
        called["path"] = path
        return {"version": 1, "stories": [], "overrides": {}}

    monkeypatch.setattr(app.story_store, "read_store", fake_read)
    monkeypatch.setattr(app, "_story_items", dict)
    assert app.list_stories_page("all", "търсене")[2] == {}


def test_an_unfiltered_listing_measures_all_four(monkeypatch):
    monkeypatch.setattr(app.story_store, "read_store",
                        lambda path: {"version": 1, "stories": [], "overrides": {}})
    monkeypatch.setattr(app, "_story_items", dict)
    counts = app.list_stories_page("all", "")[2]
    assert set(counts) == {"all", "followed", "developments", "ignored"}
    assert counts["all"] == 0  # an EMPTY corpus really is zero — this one is a fact
