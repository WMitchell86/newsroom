"""V1.2-G4.28 — a successful fetch is not an article, and the record says so.

Measured on 32 real URLs from the newsroom's own corpus before this existed.
Fetching succeeds on essentially all of them. Extraction yields usable
article prose on 27:

    burgas.bg 2,214 · cik.bg 5,522 · burgascouncil.org 6,164 · bta.bg 11,065

and on three it yields almost nothing:

    facebook.com/chernomoriebg.news   981,479 bytes ->  31 chars
    facebook.com/capitalbg/posts      862,836 bytes ->  49 chars
    results.cik.bg/.../index.html        1,449 bytes ->   0 chars

None of the three is an article, and that is not an extraction bug. But it
left the caller unable to distinguish "this page has no article" from "the
extractor failed" — both arrived as a successful fetch carrying almost
nothing, and the only way to notice was to measure the body afterwards and
infer. A caller that cannot tell them apart will either trust an empty page
or retry something that will never work.

So the measurement is taken where the extraction happens and travels on the
page record. Research, enrichment and the hint path read the verdict; none of
them re-derives it.

The threshold is set from the measurement, not chosen to look tidy: the
genuine failures sat at 31 and 49 characters, two orders of magnitude below the
smallest real article in the sample.
"""

from editor_assistant.sources import html_desc


def _blocks(*prose):
    return [{"kind": html_desc.PROSE, "text": t} for t in prose]


def test_a_real_article_reads_as_an_article():
    body = "Общинският съвет прие бюджета на Община Бургас за 2027 година. " * 8
    out = html_desc.article_prose(_blocks(body))
    assert out["verdict"] == html_desc.ARTICLE
    assert out["chars"] == len(" ".join(body.split()))


def test_a_social_wrapper_reads_as_thin_not_as_an_article():
    """31 characters out of 978,000 bytes. Not an article, and not a crash."""
    out = html_desc.article_prose(_blocks("Бургас"))
    assert out["verdict"] == html_desc.THIN
    assert out["chars"] > 0


def test_a_page_with_no_prose_reads_as_none():
    """A results table is not a broken extractor. The two are now separable."""
    out = html_desc.article_prose(_blocks())
    assert out["verdict"] == html_desc.NONE
    assert out["chars"] == 0


def test_navigation_is_not_counted_as_article_prose():
    out = html_desc.article_prose(
        [
            {"kind": html_desc.NAV, "text": "Меню Начало Контакти"},
            {"kind": html_desc.LABEL, "text": "Публикувано: днес"},
            {"kind": html_desc.PROSE, "text": "Кратка бележка."},
        ]
    )
    assert out["verdict"] == html_desc.THIN
    assert "Меню" not in out["text"]


def test_the_verdict_survives_being_asked_twice():
    """Measured once, not re-derived, so two callers cannot disagree."""
    blocks = _blocks("Пита." * 40)
    assert html_desc.article_prose(blocks) == html_desc.article_prose(blocks)
