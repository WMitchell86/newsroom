"""V1.2-G4.24 — the research ladder could not reach the authority.

The editor asked for the research pipeline to be in good shape, and named the
order: find the right SOURCES first, scraping second. This is that.

MEASURED BEFORE. For «Общински съвет прие бюджета на Община Бургас за 2027
година» the ladder research and enrichment both use was:

    1. "Общински съвет прие бюджета на Община Бургас за 2027 година"
    2. "Общински съвет прие бюджета на Община Бургас за 2027 година"
       Какво точно се променя.

Both ask for COVERAGE. Neither names the one source that settles a municipal
decision — the municipality's own site — although the editor has already
registered it, and 32 of the 35 registry entries carry a usable domain. The
second rung is worse than useless: the editorial questions are pasted in as
keyword soup, and a search engine handed «Какво точно се променя» matches
nothing.

AFTER, when the Story names a registered official publisher:

    1. "<subject>"
    2. "<subject>" site:burgas.bg
    3. "<subject>" <question>

The corroboration rung is KEPT. Finding other publishers is what the round is
for; this adds the one source the ladder was structurally unable to reach.

PRECISION IS THE WHOLE POINT, because `site:` excludes everything else. A
loose token match on «Бургас» would aim a budget story at
burgas-os.justice.bg and lock the municipality out, so matching is on the
head of the registered name and only for entries the editor marked official.
A Story that names no registered official source is left exactly as it was.
"""

from editor_assistant.workflow import event_search


def _ladder(title: str) -> list[str]:
    return event_search.event_queries(
        event_search.event_anchors(title), missing_dimensions=["Какво точно се променя."]
    )


def test_a_registered_official_publisher_is_named_in_the_query():
    ladder = _ladder("Общински съвет прие бюджета на Община Бургас за 2027 година")
    assert any("site:burgas.bg" in q for q in ladder), ladder


def test_the_coverage_rung_survives_because_corroboration_needs_it():
    """The fix adds the authority; it does not replace other publishers."""
    ladder = _ladder("Общински съвет прие бюджета на Община Бургас за 2027 година")
    assert any("site:" not in q for q in ladder), "every rung is now pinned to one domain"


def test_matching_is_on_the_head_of_the_registered_name():
    """Entries carry qualifiers the Story will not have."""
    ladder = _ladder("Летище Бургас откри нов терминал")
    assert any("site:fraport-bulgaria.com" in q for q in ladder), ladder


def test_a_story_naming_no_official_source_is_left_alone():
    """No guess. A wrong domain is worse than none, because it excludes."""
    ladder = _ladder("Дядо Коледа минава през Бургас")
    assert not any("site:" in q for q in ladder), ladder


def test_an_unregistered_institution_is_not_invented():
    """ЦИК is not in the registry, so nothing may be made up for it."""
    assert event_search._registered_official_domain("ЦИК обяви жребий за бюлетина") is None
