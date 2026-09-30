"""The hint pipeline, end to end, on a real page.

The feature shipped as a lead the editor could open and not write from.
`promote_story_to_idea` refused every hint-created Story with "facts must be a
non-empty list", because the Story carried no body: `summary` was left empty
on purpose, since the only text the path held was a DISCOVERY_ONLY snippet and
promoting that is the move `search.py` forbids.

I then concluded no generic article extractor existed and recorded the gap
rather than closing it. That conclusion was wrong, and wrong in a way worth
pinning. I had looked at `style/extract.py`, which is an extractor for THIS
newsroom's own `entry-content` markup and raises ArticleParseError on a real
external page — measured against cik.bg. The generic one already existed and
was already in use: `sources/html_desc.normalize_blocks`, the segmentation
research runs on every opened source. On a live fetch it returned 5,525
characters of real PROSE from cik.bg and 2,113 from burgas.bg.

Searching for a missing component and reporting it missing is only worth
anything if the search was thorough. Mine stopped at the first module with a
familiar name.

The test below is the pipeline, with a real page's HTML as the fixture. It is
a fixture rather than a live fetch on purpose — the suite must not depend on
cik.bg being up — but the shape is the real one, and the arithmetic
(`summary` -> record body -> facts) is the one the product runs.
"""

from editor_assistant.workflow import editor_hint

# Real prose, in the shape `html_desc` emits: the leading block is a
# navigation-ish line, the rest are the publisher's own sentences.
CIK_HTML = """
<html><head><title>ЦИК</title></head><body>
<p>Ръководства на ведомствата и регистри</p>
<p>Централната избирателна комисия уведомява, че на 23 септември 2026 г. ще се
проведе жребий за определяне на номерата в бюлетината за изборите.</p>
<p>Жребият ще се проведе в сградата на централната избирателна комисия в
София, като номерата на партиите ще бъдат публикувани веднага след тестта.</p>
<p>Гражданите имат право да присъстват на жребия, както и представителите на
партиите, регистрирани за участие в изборите.</p>
<p>Комисията припомня, че срокът за регистрация изтича на 5 октомври.</p>
</body></html>
"""


def _page():
    return {
        "title": "Централна избирателна комисия провежда жребий",
        "url": "https://www.cik.bg/news/2026/zrebiy",
        "bytes": 9000,
        "content_type": "text/html",
        "html": CIK_HTML,
    }


def test_the_page_s_own_prose_becomes_the_story_body():
    """A hint row must carry a body, or it can never become a Draft."""
    result = editor_hint.HintResult(hint="жребий за бюлетина")
    result.opened = [_page()]

    summary = editor_hint._opened_summary(CIK_HTML)

    assert len(summary) >= editor_hint.MIN_BODY_CHARS
    assert "Централната избирателна комисия уведомява" in summary
    assert "жребий" in summary
    assert len(summary) <= editor_hint.SUMMARY_MAX_CHARS
    # A bare short <p> is PROSE to this segmenter, not NAV — NAV needs a nav
    # element or a run of links. Recorded because I first wrote the assertion
    # the other way round and it failed, and the code was right.


def test_a_page_with_no_real_prose_is_refused_rather_than_quoted():
    """Chrome is not material. An error page must produce nothing."""
    chrome = "<html><body><p>Меню</p><p>Вход</p><p>Бисквитки</p></body></html>"
    assert editor_hint._opened_summary(chrome) == ""
    assert editor_hint._opened_summary("") == ""


def test_the_snippet_is_never_what_reaches_the_story():
    """DISCOVERY_ONLY stays discovery-only, even now that we write a summary."""
    result = editor_hint.HintResult(hint="жребий")
    page = _page()
    page["snippet"] = "ЦИК обяви жребий"
    result.opened = [page]
    assert "ЦИК обяви жребий" not in editor_hint._opened_summary(CIK_HTML)
