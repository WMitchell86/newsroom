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


# ---------------------------------------------------------------------------
# V1.2-G4.25 — the query the newsroom actually sent, decoded from the audit.
#
#   q=БСУ отваря нови хоризонти с португалски и китайски език
#     - Бургаски свободен университет Бургас
#
# Two defects, one per test below: the outlet name was being sent as a Google
# NOT-term, and the acronym naming the actor was invisible to the extractor.
# ---------------------------------------------------------------------------

_BSU_TITLE = (
    "БСУ отваря нови хоризонти с португалски и китайски език "
    "- Бургаски свободен университет"
)


def test_the_publisher_name_never_reaches_a_query_as_a_not_term():
    """` - Publisher` is DISPLAY data. Google reads ` - ` as EXCLUDE.

    Measured: 98 of 513 recorded queries ended this way, so the round was
    searching for its own story while excluding its own publisher's name.
    """
    stripped = event_search.strip_publisher_suffix(_BSU_TITLE)
    assert stripped == "БСУ отваря нови хоризонти с португалски и китайски език"
    assert " - " not in stripped, stripped

    for query in event_search.event_queries(event_search.event_anchors(_BSU_TITLE)):
        assert " - " not in query, f"query still carries a NOT-term: {query}"
        assert "университет" not in query.casefold(), query


def test_the_actor_is_recognised_when_it_is_an_acronym():
    """`БСУ` has no lowercase tail, so the capitalised-word rule could not see it.

    Before: entities were `['Бургаски']` — a common adjective, not the actor.
    That left Tier 2 (entity + action + locality) with nothing to build on, so
    every tier collapsed onto the raw title.
    """
    anchors = event_search.event_anchors(_BSU_TITLE)
    assert "БСУ" in anchors["entities"], anchors["entities"]

    # And the acronym must survive into a usable query, not just the record.
    assert any("БСУ" in q for q in event_search.event_queries(anchors))


def test_a_headline_with_no_publisher_suffix_is_untouched():
    """The stripper must be safe to call on any title, including short ones."""
    for title in (
        "Пътя Бургас-Созопол затворен за движение",
        "МВР засили патрулите в центъра на града",
        "Велоаллеи по улиците в Бургас отворени",
    ):
        assert event_search.strip_publisher_suffix(title) == title, title


def test_a_road_phrase_is_not_mistaken_for_a_publisher():
    """`пътя Бургас-Созопол` is a LOCALITY PAIR; the stripper must not eat it.

    (`road` is only populated when the road name ends the title - pre-existing
    behaviour of `_ROAD`, verified against unmodified main and deliberately not
    changed here. What this test guards is that the NEW stripper leaves such a
    title alone.)
    """
    title = "Затворен е пътя Бургас-Созопол"
    assert event_search.strip_publisher_suffix(title) == title, title
    assert event_search.event_anchors(title)["road"] == "Бургас-Созопол"

    # And with a publisher suffix appended, the road must survive the strip.
    both = "Затворен е пътя Бургас-Созопол - Бургаска новина"
    anchors = event_search.event_anchors(both)
    assert anchors["road"] == "Бургас-Созопол", anchors
    assert "Бургаска новина" not in anchors["subject"], anchors


def test_the_registered_site_rung_still_works_after_stripping():
    """The `site:` tier depends on the entity being present; it must not regress."""
    ladder = event_search.event_queries(
        event_search.event_anchors("Общински съвет Бургас - Бургаска новина")
    )
    assert any("site:" in q for q in ladder), ladder
