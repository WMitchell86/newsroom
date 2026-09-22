"""M4F F5 originality guard (owner requirement): a draft must differ from its
source and must not look copy-pasted. Deterministic, stdlib, fully offline.

Threshold contract: a contiguous run of ORIGINALITY_THRESHOLD_WORDS verbatim
prose words is copy-paste. Direct quotes are excluded from both sides —
quoting the source is correct journalism, copying its prose is not.
"""

from __future__ import annotations

from editor_assistant.drafting.generate import (
    ORIGINALITY_THRESHOLD_WORDS,
    originality_check,
)

SOURCE = (
    "Общинският съвет прие бюджета за 2026 година на извънредно заседание "
    "в четвъртък вечерта, съобщиха от общинската администрация."
)


def test_verbatim_source_prose_fails_and_names_the_copied_sentence():
    draft = (
        "Съветниците гласуваха след дебат. "
        "Общинският съвет прие бюджета за 2026 година на извънредно заседание в четвъртък."
    )
    result = originality_check(draft, SOURCE)
    assert result["checked"] is True
    assert result["pass"] is False
    assert result["longest_run_words"] >= result["threshold"] == ORIGINALITY_THRESHOLD_WORDS
    assert any("Общинският съвет прие бюджета" in s for s in result["copied"])


def test_a_reworded_draft_passes():
    draft = (
        "Бюджетът за догодина беше одобрен от съветниците по време на спешно "
        "свикано гласуване в края на седмицата, обявиха от общината."
    )
    result = originality_check(draft, SOURCE)
    assert result["pass"] is True
    assert result["longest_run_words"] < ORIGINALITY_THRESHOLD_WORDS
    assert result["copied"] == []


def test_a_direct_quote_may_match_the_source_verbatim():
    draft = (
        "Кметът коментира решението. "
        "«Общинският съвет прие бюджета за 2026 година на извънредно заседание "
        "в четвъртък вечерта, съобщиха от общинската администрация.»"
    )
    result = originality_check(draft, SOURCE)
    assert result["pass"] is True


def test_short_shared_runs_stay_under_the_threshold():
    draft = "Общинският съвет прие бюджета след продължителен спор."
    result = originality_check(draft, SOURCE)
    assert result["checked"] is True
    assert result["pass"] is True


def test_missing_source_prose_is_reported_not_guessed():
    result = originality_check("Изречение без източник.", "")
    assert result["checked"] is False
    assert result["pass"] is True


def test_threshold_boundary_is_exact():
    eight = " ".join(f"дума{n}" for n in range(1, 9))  # exactly 8 shared words
    source = f"{eight} допълнително."
    assert originality_check(f"{eight} край.", source)["pass"] is False
    seven = " ".join(f"дума{n}" for n in range(1, 8))
    assert originality_check(f"{seven} своя", source)["pass"] is True
