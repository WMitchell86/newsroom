"""V1.2-G4.27 — the regional rule covered 9 of the district's 13 municipalities.

A regional newsroom that drops four of its thirteen municipalities is not
regional. A fire in Камено or a council decision in Сунгураре was being
filtered OFF the regional desk by the very rule that exists to make it
regional.

Four were missing: Камено, Малко Търново, Средет, Сунгураре.

TWO OF THEM NEEDED MORE THAN A STEM, and both mistakes were caught by probing
for false positives before the change was finished. Both stemmed from adding
a municipality whose name is a PREFIX of something common:

    "търново"  → "Велико Търново" is a different city entirely, and
                 "Търново офис затвори счетоводство" is a national story.
                 The Burgas municipality is МАЛКО Търново, so the whole phrase
                 is matched and the bare stem is never used.
    "камено"   → "Каменол" is a MEDICINE, and it binds at a word start. A
                 word-end anchor keeps the municipality and drops the drug.

So the display names and the matching patterns are now separate tuples. The
first says what a person reads; the second says what binds. Guessing a stem
and trusting it is how "Каменол" ends up on the regional desk.

Not covered, and stated rather than guessed: the villages. A list assembled
from memory is a list of invented place names, and a wrong locality in this
tuple puts the wrong story on the desk. The villages are real work, done
against a real gazetteer, and not invented here.
"""

import pytest

from editor_assistant.workflow import regional_scope as rs

ALL_THIRTEEN = (
    "Бургас", "Айтос", "Камено", "Карнобат", "Малко Търново", "Несебър",
    "Поморие", "Приморско", "Руен", "Созопол", "Средет", "Сунгураре", "Царево",
)

NOT_OURS = (
    "Велико Търново ще празнува 100 години",
    "Търново офис затвори счетоводство",
    "Пловдив, Търново и Русе с най-много гостопадни",
    "Каменол не се продава без рецепта",
    "Каменна пътя до морето",
    "Сундуците са приети",
    "Средното училище е пълно",
    "София обяви бюджета за 2027",
    "Варна привлича туристи",
    "Пловдив домакин на форума",
)


@pytest.mark.parametrize("municipality", ALL_THIRTEEN)
def test_every_municipality_of_the_district_counts(municipality):
    assert rs.mentions_region(municipality), municipality


@pytest.mark.parametrize("story", NOT_OURS)
def test_a_national_or_merely_similarly_named_story_does_not(story):
    """The two stems that needed sharpening are pinned from both sides."""
    assert rs.mentions_region(story) is False, story


def test_the_four_new_ones_work_inside_a_sentence():
    for story in (
        "Пожар горя близо до Камено",
        "Община Средет прие бюджета си",
        "Сунгураре обявиха нови тръби",
        "Малко Търново празнува през уикенда",
    ):
        assert rs.mentions_region(story), story


# --- caught by re-probing, after the first version looked finished ----------

def test_the_definite_form_of_a_two_word_municipality_counts():
    """Bulgarian writes «Малкото Търново» routinely.

    Measured before the fix: the definite form did not match, so a story
    headlined «Малкото Търново празнува 100 години» was filtered OFF the
    regional desk by the rule that makes the desk regional. The four new
    municipalities were added and the first verification only checked that the
    four now MATCH — which passed, because the probes used the indefinite
    form. Re-probing is what found it.
    """
    for form in ("Малко Търново празнува", "Малкото Търново празнува", "с. Малко Търново"):
        assert rs.mentions_region(form), form


def test_the_reported_vocabulary_is_not_shorter_than_the_rule():
    """A public function that reports less than the rule uses is worse than none.

    `regional_localities()` returned the bare stems, which no longer described
    what is matched: a two-word municipality and a word-end-anchored one are
    both in the patterns and neither was in the list. A settings screen built
    on it would show fewer municipalities than the desk recognises.
    """
    reported = rs.regional_localities()
    for name in ("малко търново", "камено"):
        assert name in reported, name
    assert len(reported) >= 17
