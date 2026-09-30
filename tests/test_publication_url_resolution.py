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

#: V1.2-G4.35. The conftest fixture `no_live_publication_url_resolution`
#: substitutes these two functions in EVERY test — including this one, so calling
#: `publication_material._news_lookup` directly tests the stub and returns [] for
#: everything. These are captured at IMPORT time, which happens before any
#: autouse fixture runs, so the real implementations are what gets tested.
#:
#: A fixture that prevents a test from testing the thing it names is itself a
#: finding, and this one cost the first two tests in the section below.
_REAL_NEWS_LOOKUP = publication_material._news_lookup
_REAL_KEYLESS_LOOKUP = publication_material._keyless_lookup

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


def test_the_merge_itself_refilters_so_a_new_source_cannot_smuggle_a_wrapper(monkeypatch):
    """The union is filtered at the merge, not merely in each source.

    V1.2-G4.35. This test originally asserted the OPPOSITE — that a wrapper
    reaching the merge is carried through "by design" — and it passed, and it was
    wrong. I wrote that pin after finding that `publication_urls` does not
    refilter, and concluded the absence was intentional. It was not defended
    anywhere; it was just unexercised.

    The cost was concrete: `_original_publication_is_readable` is
    `bool(publication_urls(title))`, so a wrapper smuggled in by a source that
    forgot its own filter makes the quick-draft gate believe a Story with nothing
    readable has material. The merge now filters, and this asserts it.

    A test that pins a discovered gap as correct is worse than no test: it stops
    the next person from fixing it and records the gap as a decision.
    """
    wrapper = "https://www.facebook.com/somepage/posts/1"
    monkeypatch.setattr(publication_material, "resolve_publication_urls", lambda *a, **k: [RECORDED])
    # A source that forgets to filter, which is the only way this can happen.
    monkeypatch.setattr(publication_material, "_keyless_lookup", lambda *a, **k: [wrapper])
    monkeypatch.setattr(publication_material, "_news_lookup", lambda *a, **k: [NEWS])

    found = publication_material.publication_urls("Ремонт на улицата")

    assert wrapper not in found
    assert set(found) == {RECORDED, NEWS}
    assert all(publication_material.is_readable_publication(url) for url in found)


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


# --- the lookups themselves, which a952d69 left with no direct test at all ---


def _feed(*sources: str) -> bytes:
    items = "".join(
        f"<item><title>t</title><source url=\"{url}\"></source></item>" for url in sources
    )
    return f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'.encode()


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _patch_feed(monkeypatch, payload: bytes) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeResponse(payload)
    )


def test_a_good_feed_yields_its_publisher_roots(monkeypatch):
    _patch_feed(monkeypatch, _feed("https://vestnik.example.test", "https://dnesnik.example.org"))
    assert _REAL_NEWS_LOOKUP("Ремонт") == [
        "https://vestnik.example.test",
        "https://dnesnik.example.org",
    ]


def test_a_wrapper_inside_the_feed_is_dropped(monkeypatch):
    _patch_feed(
        monkeypatch,
        _feed("https://www.facebook.com/somepage", "https://vestnik.example.test"),
    )
    found = _REAL_NEWS_LOOKUP("Ремонт")
    assert "https://www.facebook.com/somepage" not in found
    assert found == ["https://vestnik.example.test"]


def test_a_malformed_feed_yields_nothing_rather_than_raising(monkeypatch):
    _patch_feed(monkeypatch, b"<rss><channel><item>")
    assert _REAL_NEWS_LOOKUP("Ремонт") == []


def test_an_entity_expansion_feed_is_refused(monkeypatch):
    """V1.2-G4.35. `ET.fromstring` expands internal entities; this feed would.

    Measured while writing it: 128 bytes expanded to 480 characters, and the
    expansion nests, so three declaration levels are enough to turn a tiny
    response into a large string inside a worker the editor waits on. A search
    feed has no legitimate reason to carry a DTD, so one is refused outright.
    """
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "1234567890">'
        b'<!ENTITY b "&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;">]>'
        b"<rss><channel><item><source url=\"https://vestnik.example.test\"/></item></channel></rss>"
    )
    _patch_feed(monkeypatch, bomb)
    assert _REAL_NEWS_LOOKUP("Ремонт") == []


def test_an_oversized_feed_is_refused(monkeypatch):
    oversized = b"<rss><channel>" + b"x" * (publication_material.MAX_FEED_BYTES + 10) + b"</channel></rss>"
    _patch_feed(monkeypatch, oversized)
    assert _REAL_NEWS_LOOKUP("Ремонт") == []


def test_a_keyless_lookup_error_yields_nothing(monkeypatch):
    """A provider outage must move the reader on, never raise through the Draft."""
    def boom(*_a, **_k):
        raise OSError("provider is down")

    monkeypatch.setattr(publication_material.search_mod, "DDGSProvider", boom)
    assert _REAL_KEYLESS_LOOKUP("Ремонт") == []
