"""V1.2-G4.13 — a headline must not end in a hostname.

The editor reported seeing «24 chasa» and «Kompass» in titles. Measured on
the live Today projection: 3 of 30 rows, and over the whole collected
corpus 155 headlines end in `- DarikNews.bg`, `- burgas.bg`, `- bta.bg`,
`- www.24chasa.bg`. The source name was already rendered on its own row
(G4.5); this is the same fact leaking into the headline as well.

`editorial_story_title` already stripped site tags like
`новини от Бургас и региона` by shape, but a bare hostname is a different
shape and no registry row can name it, so it was left attached.
"""

from editor_assistant.workflow import editorial_title as et


def test_a_trailing_hostname_is_removed():
    assert et.editorial_story_title(
        "Бургас посреща есенните дъждове с 39 км почистени реки - www.24chasa.bg"
    ) == "Бургас посреща есенните дъждове с 39 км почистени реки"


def test_it_needs_no_brand_in_the_headline():
    """A hostname is decoration by shape, unlike a trailing PHRASE."""
    assert et.editorial_story_title(
        "Бургас ще отбележи Световния ден на сърцето - информационна агенция компас"
    ).endswith("информационна агенция компас")  # a phrase needs identity


def test_multiple_stacked_hosts_are_removed():
    assert et.editorial_story_title(
        "Нов проект между България и Корея - DarikNews.bg - www.dariknews.bg"
    ) == "Нов проект между България и Корея"


def test_a_headline_that_merely_mentions_a_host_is_untouched():
    for probe in (
        "Поморие: затварят пътя за ремонт",
        "Д-р Петков: проектът е в.bg страница",
        "Бургас - Поморие: затварят пътя",
    ):
        assert et.editorial_story_title(probe) == probe


def test_a_short_head_is_never_stripped_into_nothing():
    """`_MIN_HEAD_CHARS` still guards the head; decoration removal is not free."""
    assert et.editorial_story_title("Към - www.x.bg") == "Към - www.x.bg"


def test_the_raw_title_is_not_modified_in_place():
    """§A2: the source material keeps exactly what the feed delivered."""
    raw = "Бургас посреща есенните дъждове - www.24chasa.bg"
    et.editorial_story_title(raw)
    assert raw.endswith("- www.24chasa.bg")
