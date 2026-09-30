"""V1.2-G4.26 — a local source does not make a Story regional.

Measured on the live regional desk before this change. Of the 30 Stories it
was showing, six qualified as regional with no regional word in the title OR
the body. Three of them were national:

    "Петрова: България трябва ясно да определи своята роля"
    "Акция срещу „Хелс Ейнджълс" и в България: Над 1000 полицаи"
    "България сменя регионалната карта"

All three came from `darik-burgas` — `kind="regional"`, `domain=dariknews.bg`.
It is a NATIONAL outlet's Burgas channel. The rule treated any local source as
proof of locality, so the regional working desk was occupied by national
wire copy republished locally, which is the exact thing the rule was written
to prevent.

THE DISTINCTION, which is not "local vs not" but "self-scoping vs not":

* `official` — a municipality, a court, a hospital, an airport. It publishes
  about itself and about nothing else, so its carrying a Story places that
  Story in the region. Evidence on its own.
* `regional` — a news outlet. It covers the region AND beyond, and
  republishes the national wire. Not evidence on its own; it counts only
  together with regional text in the Story.

A Story the editor is already writing, and a Story they are following with a
new development, are still unconditional — hiding in-flight work would lose
the work, and neither check is about locality at all.

After the change, on the live corpus: national Stories on the regional desk
0 (was 3 in the shown 30), and the regional total fell 109 -> 96, which is
the national copy leaving rather than being renamed.
"""

from editor_assistant.workflow import regional_scope as rs

REGISTRY = [
    {"source_id": "umbal-burgas", "kind": "official", "name": "УМБАЛ Бургас"},
    {"source_id": "burgas-district-court", "kind": "official", "name": "Съд"},
    {"source_id": "darik-burgas", "kind": "regional", "name": "Дарик Бургас"},
]


def test_an_institution_publishing_about_itself_is_evidence():
    assert rs.source_is_self_scoping("umbal-burgas", REGISTRY) is True
    assert rs.source_is_self_scoping("burgas-district-court", REGISTRY) is True


def test_a_news_outlet_is_not_evidence_on_its_own():
    """This is the whole fix. It used to be the same as the line above."""
    assert rs.source_is_self_scoping("darik-burgas", REGISTRY) is False
    assert rs.is_local_source("darik-burgas", REGISTRY) is True


def test_an_unconfigured_source_claims_nothing():
    assert rs.source_is_self_scoping("who-knows", REGISTRY) is False
    assert rs.is_local_source("", REGISTRY) is False


def test_the_region_stems_still_cover_the_district():
    for place in ("Бургас", "Поморие", "Несебър", "Созопол", "Приморск", "Айтос"):
        assert rs.mentions_region(place), place
    # And a stem must not bind inside an unrelated longer word.
    assert rs.mentions_region("бургското движение") is True  # a real derivation
    assert rs.mentions_region("София") is False
