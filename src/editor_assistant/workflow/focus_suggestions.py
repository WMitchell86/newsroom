"""V1.2-G2.4 §D — the fast Editorial Focus: one good default, zero friction.

**The contract this module implements.** D1 asks for one thing: when an Article
enters Preparation, the Focus field must ALREADY hold one usable, Story-specific
proposal, so `open -> accept everything by doing nothing -> Направи чернова`
works. D2 adds two or three quiet alternatives below it. D3 keeps the field
editable at all times and adds no state of its own.

**Why the suggestions are deterministic.** D4 is explicit that a strong Draft
model must never be spent on Focus choices, and it asks for a determination
first: can three useful variants be produced from the Story title, its facts,
its gaps and ordinary editorial templates? For local Bulgarian news the answer
is yes, so this module does that and spends no model call at all. The primary
Focus therefore has no failure mode: it is a pure function of canonical Story
state, which is what makes "never make Draft eligibility depend on successful
alternative generation" true by construction rather than by promise.

**What this is not.** Not a proposal state, not an approval step, not a wizard.
The caller persists a suggestion through the ONE canonical Focus save
(`editor_article_store.update_editor_focus`), so clicking an alternative and
typing your own text reach exactly the same place.
"""

from __future__ import annotations

import re

#: The quiet alternatives are labelled, never "Apply". §D2: clicking one simply
#: replaces the text.
WRITE_YOUR_OWN = "Напиши свой"

#: The compact alternatives offered under the field. Their CONTENT is built per
#: Story; only these labels are shared, and none of them is a button that
#: confirms anything.
ALTERNATIVE_LABELS = (
    "Какво се случи и какво следва",
    "Практична информация за читателите",
    "Последствията за региона",
)

_TRAILING_PUBLISHER = re.compile(r"\s+[-–—]\s+[^-–—|]{2,40}$")
_QUOTES = re.compile(r"[„“”\"«»]")


def _clean_title(title: str) -> str:
    """The Story subject, without the publisher suffix and stray quotes."""
    text = " ".join(str(title or "").split())
    text = _TRAILING_PUBLISHER.sub("", text)
    text = _QUOTES.sub("", text).strip(" -–—,.")
    return text


def primary_focus(title: str, *, facts=(), gaps=()) -> str:
    """D1 — the one usable Focus an editor can accept without doing anything.

    Deterministic, Story-specific, one sentence, and free of any model call. It
    names the Story's own subject and the editorial job, and invents no angle,
    no quote, no source and no consequence.

    `facts` and `gaps` shape only *where the emphasis goes*, never *what is
    claimed*: a Story that still has confirmed facts is framed around them, and
    one that does not is framed around what is established so far. A Story with
    no usable subject yields `""`, exactly like the Quick-Draft default, and the
    canonical readiness decision then reports `WORKING_TITLE_REQUIRED`.

    **V1.2-G4.3 — no template that could sit on any other Story.** The previous
    wording (`с акцент върху потвърдените факти, кога и къде се е случило и какво
    следва за хората, за които новината има значение`) was editorially empty: it
    named no decision and would paste onto any story in the desk. Worse, it
    called the subject "потвърдено" while the same screen warned that the
    information was NOT independently confirmed, so the page contradicted itself.
    The Focus now states what the text must actually settle for THIS Story, and
    never asserts a level of confirmation the basis does not have.
    """
    subject = _clean_title(title)
    if not subject:
        return ""
    has_facts = bool(list(facts or ()))
    if has_facts:
        return (
            f"Какво точно е установено за „{subject}“ и какво следва за "
            "хората, за които новината има значение."
        )
    return (
        f"Какво вече е известно за „{subject}“ и какво остава неуточнено, "
        "без да се представя за потвърдено."
    )


def alternatives(title: str, *, facts=(), gaps=()) -> tuple[str, ...]:
    """V1.2-G4.3 §C3 — no alternatives at all, and that is the point.

    The previous contract asked for two or three quiet variants derived
    deterministically from the Story. The owner's review of real generated
    articles found the opposite problem: the alternatives were templates that
    could sit on any story in the desk, so they added a choice the editor had to
    evaluate without it ever being a real editorial decision.

    The brief for this slice is explicit — do not spend more effort producing
    generic alternatives, and do not render chips unless they are genuinely
    Story-specific and materially different. At the current deterministic quality
    that set is EMPTY, so this returns an empty tuple and the caller treats that
    as the normal outcome rather than as a failure.

    The function is kept, with its signature, because it is the single place the
    decision lives: if a future model-backed Focus proposal ever becomes
    genuinely Story-specific, this is where it is allowed to return something,
    and every consumer already handles the empty case correctly.
    """
    return ()
