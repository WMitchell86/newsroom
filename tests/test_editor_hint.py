"""V1.2-G4.20 — the editor's hint is a search query, never evidence.

The editor asked to start from their own idea. The cheap way to allow it is
to admit the hint as a Story with a placeholder URL, and it WORKS: the store
only checks the URL's shape, so `https://editor.local/hint/1` is accepted
today. That is the trap. A placeholder would be written into a system whose
entire value is "every claim points at a page that was actually opened", and
it would be cited, chased, and reported as material by every later reader.

So the hint only ever selects. What becomes material is a page that the
search chain really opened. The tests below mostly defend that boundary:

* a snippet alone never becomes material;
* a candidate that could not be opened never becomes material, and keeps the
  provider's own failure category so it is never reported as "no such
  material exists";
* no URL that was not actually opened can appear in the result at all.
"""

import pytest

from editor_assistant.sources import web_fetch
from editor_assistant.workflow import editor_hint, search


class _Provider(search.SearchProvider):
    """A provider that reports results; it never opens anything itself."""

    name = "stub"

    def __init__(self, results):
        self._results = results

    def search(self, query, *, count=10, country="bg", search_language="bg", freshness=None):
        return {
            "provider": self.name,
            "query": query,
            "requested_count": count,
            "started_at": "2026-01-01T00:00:00Z",
            "status": search.SEARCH_OK,
            "attempt": 1,
            "http_status": 200,
            "retry_after": None,
            "elapsed_ms": 1,
            "results": list(self._results),
        }


def _ok(final_url="https://cik.bg/news/2026/machines"):
    return {
        "status": "FETCH_OK",
        "final_url": final_url,
        "content_type": "text/html",
        "bytes": 4200,
    }


def _run(hint, *, results, opener, max_open=3):
    return editor_hint.run_hint_search(
        hint, provider=_Provider(results), page_opener=opener, max_open=max_open
    )


def test_an_opened_page_becomes_usable_material():
    result = _run(
        "проверка на машините за изборите",
        results=[{"url": "https://cik.bg/news/2026/machines", "title": "ЦИК", "snippet": "..."}],
        opener=lambda url: {"final_url": "https://cik.bg/news/2026/machines", "content_type": "text/html", "bytes": 4200},
    )
    assert result.usable is True
    assert result.opened[0]["url"] == "https://cik.bg/news/2026/machines"


def test_a_page_that_will_not_open_never_becomes_material():
    def opener(url):
        raise web_fetch.WebFetchError("FETCH_TIMEOUT", "connected but no body")

    result = _run(
        "проверка на машините за изборите",
        results=[{"url": "https://example.org/a", "title": "A", "snippet": "..."}],
        opener=opener,
    )
    assert result.usable is False
    assert result.opened == []
    assert result.unopened[0]["url"] == "https://example.org/a"


def test_a_failed_open_keeps_the_real_category_not_a_verdict():
    def opener(url):
        raise web_fetch.WebFetchError("FETCH_TIMEOUT", "connected but no body")

    result = _run(
        "проверка на машините за изборите",
        results=[{"url": "https://example.org/a", "title": "A", "snippet": "..."}],
        opener=opener,
    )
    # The point of the rule: a timeout is a fact about the network, never
    # "such material does not exist".
    assert result.unopened[0]["status"] == "FETCH_TIMEOUT"
    assert "no such" not in (result.audit.get("reason") or "").casefold()


def test_a_snippet_alone_is_never_material():
    """Discovery-only snippets must not be promoted by this path."""
    def opener(url):
        raise web_fetch.WebFetchError("FETCH_ERROR", "server said no", status=500)

    result = _run(
        "проверка на машините за изборите",
        results=[
            {"url": "https://example.org/a", "title": "A", "snippet": "ЦИК обяви много неща"},
            {"url": "https://example.org/b", "title": "B", "snippet": "ЦИК обяви още"},
        ],
        opener=opener,
    )
    assert result.opened == []
    assert len(result.unopened) == 2


def test_no_url_that_was_not_opened_can_appear_in_the_result():
    """The placeholder-URL trap, pinned shut at the type level."""
    real = "https://cik.bg/news/2026/machines"
    result = _run(
        "проверка на машините за изборите",
        results=[
            {"url": "https://evil.example/x", "title": "X", "snippet": "..."},
            {"url": real, "title": "ЦИК", "snippet": "..."},
        ],
        opener=lambda url: {"final_url": real, "content_type": "text/html", "bytes": 10},
    )
    urls = {c["url"] for c in result.opened} | {c["url"] for c in result.unopened}
    assert all(u.startswith("http") for u in urls)
    assert "editor.local" not in " ".join(urls)
    assert result.opened[0]["url"] == real


def test_empty_and_fragile_hints_are_refused_with_the_reason():
    with pytest.raises(editor_hint.HintRejected) as short:
        editor_hint._clean_hint("ЦИК")
    assert "кратка" in str(short.value)
    with pytest.raises(editor_hint.HintRejected) as blank:
        editor_hint._clean_hint("   ")
    assert "празна" in str(blank.value)


def test_a_pasted_article_is_refused_not_treated_as_a_topic():
    with pytest.raises(editor_hint.HintRejected) as long:
        editor_hint._clean_hint("а" * (editor_hint.HINT_MAX_CHARS + 1))
    assert "дълга" in str(long.value)


def test_the_opened_pages_text_travels_with_the_result():
    """A URL with no body is an empty lead, not material.

    `run_search_operation` records only metadata for an opened candidate, so
    the text has to be kept on the way past by the opener we supply. Without
    this the module would return a perfectly verified link and nothing to
    write from — which is the exact shape of the failure this feature exists
    to prevent.
    """
    body = "ЦИК започна проверката на машините за изборите в цялата страница."
    real = "https://cik.bg/news/2026/machines"
    result = _run(
        "проверка на машините за изборите",
        results=[{"url": real, "title": "ЦИК", "snippet": "..."}],
        opener=lambda url: {
            "final_url": real,
            "content_type": "text/html",
            "bytes": len(body),
            "text": body,
        },
    )
    assert result.opened[0]["text"] == body
    assert "ЦИК" in result.opened[0]["text"]


# --- materialising into the real inbox -------------------------------------
#
# These write to a temp inbox with the real `inbox_store`, because the point
# of the feature is that the output is an ORDINARY story. A fake store would
# prove nothing about the one thing that matters here.


def _result(url="https://cik.bg/news/2026/machines", title="ЦИК"):
    r = editor_hint.HintResult(hint="проверка на машините")
    r.opened = [{"title": title, "url": url, "bytes": 4200, "content_type": "text/html", "text": "body"}]
    return r


def test_a_hint_page_becomes_an_ordinary_inbox_story(tmp_path):
    from editor_assistant.workflow import inbox_store

    saved = editor_hint.materialise_hint_stories(_result(), inbox_path=tmp_path / "inbox.json")
    assert len(saved) == 1
    row = saved[0]
    # It must be indistinguishable from collected material downstream.
    assert row["url"] == "https://cik.bg/news/2026/machines"
    assert row["title"] == "ЦИК"
    assert row["status"] == "NEW"
    assert row["publisher_domain"] == "cik.bg"
    stored = inbox_store.read_items(tmp_path / "inbox.json")
    assert [i["url"] for i in stored] == ["https://cik.bg/news/2026/machines"]


def test_material_found_by_a_search_is_not_claimed_as_an_authority(tmp_path):
    """`cik.bg` reached via a search engine is still not a registered source.

    The registry is what confers authority, and this path does not consult it.
    Claiming otherwise here would let a search result outrank an official
    source that was registered deliberately.
    """
    saved = editor_hint.materialise_hint_stories(_result(), inbox_path=tmp_path / "inbox.json")
    assert saved[0]["factual_authority"] is False
    assert saved[0]["source_id"] == editor_hint.HINT_SOURCE_ID
    assert editor_hint.HINT_SOURCE_ID not in {r["source_id"] for r in []}  # not a publisher row


def test_a_discovery_only_snippet_never_reaches_the_summary(tmp_path):
    """`search.py` marks snippets DISCOVERY_ONLY; the summary field must stay empty.

    Every other reader of `summary` treats it as collected material, so
    pouring a search snippet in there would launder a discovery string into
    something that reads as verified.
    """
    r = editor_hint.HintResult(hint="проверка на машините")
    r.opened = [{
        "title": "ЦИК", "url": "https://cik.bg/x", "bytes": 10,
        "content_type": "text/html", "text": "b", "snippet": "ЦИК обяви много неща",
    }]
    saved = editor_hint.materialise_hint_stories(r, inbox_path=tmp_path / "inbox.json")
    assert saved[0]["summary"] == ""


def test_two_hints_finding_one_page_produce_one_story(tmp_path):
    """Deterministic ids: a re-hint must not duplicate an article."""
    path = tmp_path / "inbox.json"
    editor_hint.materialise_hint_stories(_result(), inbox_path=path)
    editor_hint.materialise_hint_stories(_result(), inbox_path=path)
    from editor_assistant.workflow import inbox_store

    assert len(inbox_store.read_items(path)) == 1


def test_a_hint_that_opened_nothing_writes_nothing(tmp_path):
    from editor_assistant.workflow import inbox_store

    empty = editor_hint.HintResult(hint="тема без резултат")
    assert editor_hint.materialise_hint_stories(empty, inbox_path=tmp_path / "inbox.json") == []
    assert not (tmp_path / "inbox.json").exists() or inbox_store.read_items(tmp_path / "inbox.json") == []


# --- the bug this file's history earned -----------------------------------
#
# Measured on a live run: three inbox rows were written, the endpoint reported
# three opened pages, and NOTHING was visible to the editor. Writing inbox
# rows is only half of becoming a Story — `story_identity` is what assigns
# items to stories, and an unassigned item sits in the inbox forever. The
# editor was told material had been found, and the Stories list did not grow.


def _isolate_newsroom(tmp_path, monkeypatch):
    """Point the newsroom at tmp_path, the way production points it at var/.

    Grouping runs through the newsroom's own `refresh_stories`, which reads the
    newsroom directory from the environment rather than from an argument. A
    test that passed a tmp inbox but left the environment pointing at the live
    corpus would group against the WRONG store — and would still have passed
    the old assertions, because nothing was grouping at all.
    """
    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    return newsroom / "inbox.jsonl", newsroom / "stories.json"


def test_material_actually_joins_a_story_and_not_just_the_inbox(tmp_path, monkeypatch):
    from editor_assistant.workflow import story_store

    inbox, stories = _isolate_newsroom(tmp_path, monkeypatch)
    saved = editor_hint.materialise_hint_stories(
        _result(), inbox_path=inbox, stories_path=stories
    )
    assert len(saved) == 1
    # The row knows which story it landed in...
    assert saved[0]["story_id"], "material was written but attached to no story"
    # ...and that story really exists on disk.
    assert story_store.story_by_id(story_store.read_store(stories), saved[0]["story_id"])


def test_a_story_id_is_never_an_inbox_item_id(tmp_path, monkeypatch):
    """`/stories/:id` rejects an item id, so the two must not be confused.

    The endpoint used to return `item_id` as the thing to navigate to. Every
    click landed on 400 «Невалиден Story.» — verified against the live server,
    where GET /api/v1/stories/ia1ca72ccba86788 answered 400 while a real
    story id answered 200.
    """
    inbox, stories = _isolate_newsroom(tmp_path, monkeypatch)
    saved = editor_hint.materialise_hint_stories(
        _result(), inbox_path=inbox, stories_path=stories
    )
    row = saved[0]
    assert row["item_id"].startswith("i")
    assert row["story_id"].startswith("s")
    assert row["story_id"] != row["item_id"]


def test_a_retry_after_a_failed_grouping_still_surfaces_the_material(tmp_path, monkeypatch):
    """The retry must not be poisoned by the failure that came before it.

    Measured: with grouping made to fail once, attempt 1 raised and left one
    stored inbox row. Attempt 2 — with grouping healthy again — returned
    NOTHING, because `add_items` reported the row as a duplicate and the code
    reported only the new ones. So the editor was told "0 pages opened" while
    their material sat in the inbox, and no later hint would ever surface it
    again. This is the failure the rules call out: the screen stated something
    the system had not observed, and the material was stranded.
    """
    from editor_assistant.workflow.workbench import newsroom as newsroom_mod

    inbox, stories = _isolate_newsroom(tmp_path, monkeypatch)

    def boom(**_kwargs):
        raise RuntimeError("stories store is locked by another process")

    monkeypatch.setattr(newsroom_mod, "refresh_stories", boom)
    with pytest.raises(RuntimeError):
        editor_hint.materialise_hint_stories(_result(), inbox_path=inbox, stories_path=stories)

    monkeypatch.setattr(
        newsroom_mod,
        "refresh_stories",
        lambda **_kwargs: type("Store", (), {"get": lambda s, k, d=None: {"stories": []}.get(k, d)})(),
    )
    again = editor_hint.materialise_hint_stories(_result(), inbox_path=inbox, stories_path=stories)
    assert len(again) == 1, "a retry reported nothing while the material was sitting in the inbox"
    assert again[0]["url"] == "https://cik.bg/news/2026/machines"


def test_a_blocked_publisher_is_never_written_as_material(tmp_path, monkeypatch):
    """A blocked page must not become an invisible inbox row.

    Measured before the fix: with `example.org` blocked, the row was written,
    `story_id` came back empty because grouping skips blocked publishers, and
    the control said «записана като Story» with nothing to open. The row then
    sat in the inbox forever — reported as material, visible to no one, and
    removable by no retry. A search engine is precisely how a blocked domain
    gets found, so this path cannot skip the check.
    """
    import json as json_mod

    from editor_assistant.workflow import inbox_store

    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    # `blocked_path()` resolves from `NEWSROOM_DIR`, not `WB_NEWSROOM_DIR` like
    # the inbox does. Without this override the first version of this test read
    # the REAL var/newsroom/blocked_domains.json and asserted against the
    # production blocklist while believing it had isolated one.
    blocked_file = newsroom / "blocked.json"
    blocked_file.write_text(json_mod.dumps(["example.org"]))
    monkeypatch.setenv("NEWSROOM_BLOCKED_DOMAINS_PATH", str(blocked_file))

    result = editor_hint.HintResult(hint="тема за проверка")
    result.opened = [
        {
            "title": "Забранен",
            "url": "https://example.org/a",
            "bytes": 10,
            "content_type": "text/html",
            "text": "b",
        }
    ]
    written = editor_hint.materialise_hint_stories(
        result, inbox_path=newsroom / "inbox.jsonl", stories_path=newsroom / "stories.json"
    )
    assert written == [], "a blocked publisher was written as material"
    assert inbox_store.read_items(newsroom / "inbox.jsonl") == []
    # ...and the page is named rather than dropped, so the editor can audit it.
    assert result.opened[0].get("blocked") is True


def test_a_url_with_an_explicit_port_does_not_kill_the_hint(tmp_path, monkeypatch):
    """`.hostname` strips the port; `.netloc` keeps it and `canonical_host` raises.

    An earlier version passed `.netloc` to `canonical_host`, which rejects a
    domain containing a port. Any result URL that carried one would have
    raised out of the whole request instead of being filtered.
    """
    import json as json_mod

    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    # `blocked_path()` resolves from `NEWSROOM_DIR`, not `WB_NEWSROOM_DIR` like
    # the inbox does. Without this override the first version of this test read
    # the REAL var/newsroom/blocked_domains.json and asserted against the
    # production blocklist while believing it had isolated one.
    blocked_file = newsroom / "blocked.json"
    blocked_file.write_text(json_mod.dumps(["example.org"]))
    monkeypatch.setenv("NEWSROOM_BLOCKED_DOMAINS_PATH", str(blocked_file))

    result = editor_hint.HintResult(hint="тема с порт")
    result.opened = [
        {
            "title": "С порт",
            "url": "https://cik.bg:443/news",
            "bytes": 10,
            "content_type": "text/html",
            "text": "b",
        }
    ]
    written = editor_hint.materialise_hint_stories(
        result, inbox_path=newsroom / "inbox.jsonl", stories_path=newsroom / "stories.json"
    )
    # cik.bg is not blocked, so the port must not have broken anything.
    assert len(written) == 1
    assert written[0]["url"] == "https://cik.bg:443/news"
