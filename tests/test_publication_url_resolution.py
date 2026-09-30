"""The publication-URL resolver cascade, with the network replaced by canned answers.

V1.2-G4.34. `publication_urls` merges three sources — the newsroom's own
discovery record, a keyless provider lookup and a Google News RSS lookup — then
orders the result by how strongly each URL names the Story. The last two reach the
real internet, and neither goes through `web_fetch`, so the hermetic DNS shim
never covered them.

That is why `tests/conftest.py` now substitutes both to empty lists in every
test. It removed 391 seconds of unintended network calls, and in doing so it
removed the ONLY exercise this code path had: 391 seconds in which nobody was
testing anything, and a merge-and-order function with no test at all.

These tests put the coverage back without the network. The product function runs
for real; only the two lookups are canned.
"""

import pytest

from editor_assistant.workflow import publication_material

RECORDED = "https://vestnik.example.test/2026/remont"
KEYLESS = "https://dnesnik.example.org/2026/remont-na-ulitsata"
NEWS = "https://vestnik.example.test/2026/remont-detali"


@pytest.fixture(autouse=True)
def clear_resolver_cache():
    """The cache is process-wide, so a cached title would hide a later test."""
    publication_material._RESOLVED.clear()
    yield
    publication_material._RESOLVED.clear()


def test_merges_all_three_sources_and_ranks_the_story_first(monkeypatch):
    """Every source contributes, and the most Story-like URL comes first.

    The ordering is not cosmetic: the reader tries them in order, so an unstable
    order would make the same Story resolve to a different publisher on a second
    run. `RECORDED` and `NEWS` share a host and `KEYLESS` names the Story less
    directly, so a correct ranking puts the recorded page first.
    """
    monkeypatch.setattr(publication_material, "resolve_publication_urls", lambda *a, **k: [RECORDED])
    monkeypatch.setattr(publication_material, "_keyless_lookup", lambda *a, **k: [KEYLESS])
    monkeypatch.setattr(publication_material, "_news_lookup", lambda *a, **k: [NEWS])

    found = publication_material.publication_urls("Ремонт на улицата")

    assert set(found) == {RECORDED, KEYLESS, NEWS}
    assert found[0] == RECORDED, f"most Story-like URL must lead: {found}"


def test_the_merge_trusts_its_sources_rather_than_refiltering(monkeypatch):
    """A wrapper entering the merge is carried through — by design, and riskily.

    Measured while writing this: `publication_urls` does NOT call
    `is_readable_publication` on what it merges. Each LOOKUP filters its own
    results (see `_keyless_lookup` / `_news_lookup`), and the merge trusts that.

    That is a real contract with a real hazard, so it is pinned here rather than
    left implicit: a source added later without its own filter would smuggle a
    social wrapper straight into the candidate list, and the wrapper is exactly
    what `is_readable_publication` exists to keep out. The single gate is
    asserted directly, so the safety net it represents is at least covered.
    """
    wrapper = "https://www.facebook.com/somepage/posts/1"
    monkeypatch.setattr(publication_material, "resolve_publication_urls", lambda *a, **k: [RECORDED])
    monkeypatch.setattr(publication_material, "_keyless_lookup", lambda *a, **k: [wrapper])
    monkeypatch.setattr(publication_material, "_news_lookup", lambda *a, **k: [NEWS])

    found = publication_material.publication_urls("Ремонт на улицата")

    # The merge does not refilter: documented, not accidental, and a trap for the
    # next source anyone adds.
    assert wrapper in found

    # The gate itself is the defence, and it is asserted here so that if it is
    # ever weakened this file notices.
    assert publication_material.is_readable_publication(wrapper) is False
    assert publication_material.is_readable_publication(RECORDED) is True


def test_a_refresh_bypasses_the_cache(monkeypatch):
    """`refresh=True` re-resolves, so a recorded URL that started failing is retried.

    The two-pass caller in `_draft_snapshot` relies on this: the keyless provider
    rate-limits, and a throttled first answer must not be what decides that a
    Story with a real article has no readable material.
    """
    calls: list[str] = []

    def resolve(title, **kwargs):
        calls.append(title)
        return [RECORDED]

    monkeypatch.setattr(publication_material, "resolve_publication_urls", resolve)
    monkeypatch.setattr(publication_material, "_keyless_lookup", lambda *a, **k: [])
    monkeypatch.setattr(publication_material, "_news_lookup", lambda *a, **k: [])

    publication_material.publication_urls("Ремонт на улицата")
    publication_material.publication_urls("Ремонт на улицата")
    assert len(calls) == 1, "the cache must answer a repeat without re-resolving"

    publication_material.publication_urls("Ремонт на улицата", refresh=True)
    assert len(calls) == 2, "refresh=True must re-resolve despite the cache"
