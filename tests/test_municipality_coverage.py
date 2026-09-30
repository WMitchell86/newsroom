"""V1.2-G4.30 — the safety net covered 6 of the district's 13 municipalities.

The editor asked for a review of the Bulgarian in the code. That is not a
spelling question here: a misspelled or missing place name in the COLLECTION
layer means a whole municipality is never gathered, and it presents as "the
source has no news about that" rather than as a mistake.

MEASURED, not assumed. The broad monitoring query — whose own note says it
exists to «открива покритие извън фиксирания списък» — read:

    Бургас OR Поморие OR Несебър OR Созопол OR Царево OR Приморско

Six of thirteen. Eight of the thirteen have a dedicated «Община …» source
(Айтос, Бургас, Карнобат, Несебър, Поморие, Приморско, Созопол, Царево), so
those were collected regardless. FIVE had neither a dedicated source nor a
place in the query:

    Камено · Малко Търново · Руен · Средет · Сунгураре

The corpus agrees. As standalone words, Средет and Сунгураре occur ZERO
times in 632 collected items, and Руен four.

This is 5 of 13 — 38% of the district, structurally unreachable by the layer
that gathers. The DESK side of the same gap was fixed three commits ago in
`regional_scope`, and the collection side was missed. A story the editor can
now see on the desk but the newsroom cannot collect is a half-fix, and the
half that was left is the half that decides whether the story exists.

Every municipality is now in the net, including Айтос, which has a dedicated
source anyway: the net is the thing that must not have holes, because the
dedicated source can be muted or fail.
"""

import pytest

from editor_assistant.workflow import default_sources as ds

ALL_THIRTEEN = (
    "Бургас", "Айтос", "Камено", "Карнобат", "Малко Търново", "Несебър",
    "Поморие", "Приморско", "Руен", "Созопол", "Средет", "Сунгураре", "Царево",
)


def _monitoring_query() -> str:
    entries = [
        entry for entry in ds.DEFAULT_ENTRIES
        if "OR" in str(entry.get("query") or "")
    ]
    assert entries, "no broad monitoring query found in the default sources"
    return entries[0]["query"]


@pytest.mark.parametrize("municipality", ALL_THIRTEEN)
def test_the_monitoring_net_covers_every_municipality(municipality):
    query = _monitoring_query()
    assert municipality in query, f"{municipality!r} is not in the monitoring net"


def test_the_net_is_the_one_described_as_the_safety_net():
    """Guard against a second OR-query being added and quietly becoming the net."""
    queries = [str(e.get("query") or "") for e in ds.DEFAULT_ENTRIES if "OR" in str(e.get("query") or "")]
    assert len(queries) == 1, f"more than one monitoring query: {queries}"


def test_the_two_word_municipality_is_quoted():
    """«Малко Търново» unquoted in an OR chain is two loose words.

    A bare OR query passes each term to a news search, and «Малко Търново»
    unquoted is not a phrase — it invites matches on «малко» alone, which is
    a common word, and would fill the net with noise from anywhere.
    """
    assert '"Малко Търново"' in _monitoring_query()
