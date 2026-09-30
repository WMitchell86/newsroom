"""MEASURED DEFECT, documented not fixed — the same story appears 3 times.

Found by reading the 35 "baseline failures" instead of re-running the hint
path for a sixth time. They are NOT all stale bookkeeping. Grouped by cause:

  ~17  stale expectations after a CORRECT honesty change. The code now emits
       DRAFT_FROM_UNREAD_SOURCE ("източникът още не е прочетен") where it used
       to emit NO_DRAFT_MATERIAL ("няма достатъчно изходен материал"). Those
       are different claims — one is an action, one is a refusal — and the
       source comment says the old one was a false claim about a Story with
       zero opened sources. The code is right; the tests are behind it.

  ~14  A REAL, STILL-LIVE DEFECT. This file.

  ~3   STALE FIXTURES AFTER A DELIBERATE PRECISION CHANGE. The claim
       filter's `_GENERIC_NEWS_WORDS` deliberately lists
       съобщение/съобщения/съобщи as vocabulary that can occur in any two
       unrelated stories and must never produce agreement. git log dates
       that list to 6a095c3, "coverage, cost routing, fast focus, and the
       official-source fix". The research fixtures lean on "съобщение" as
       the word that distinguishes their question, and that repair
       neutralised exactly it. The code is right; the fixtures no longer
       satisfy it.

  ~6   not yet classified.

THE DEFECT. `test_near_identical_titles_are_merged_deterministically` seeds
two items with the same title and different URLs, and expects one Story. It
gets zero matches, and four more tests in `test_workbench_newsroom` die on
`_pair_story`'s `next()` because no Story with two members is ever created.

Grouping keys on `publication_key`, which is derived from the URL. The newsroom
collects through Google News RSS, where every item gets its own opaque
redirect URL — so two copies of the same story never share a key and can
never be merged, no matter how identical their headlines.

CONFIRMED ON THE LIVE CORPUS, not inferred:

    5 identical headlines are spread across DIFFERENT stories
    3 stories carry the headline "Очаквайте вакцина през септември"
      se3fa89b6bf474d2  bnr-burgas  news.google.com/rss/articles/CBMie0FVX3lxTE9kZ0l
      s55c2ae251e3e70c  bnr-burgas  news.google.com/rss/articles/CBMiekFVX3lxTE9UeFh
      sfbe776682838492  bnr-burgas  news.google.com/rss/articles/CBMie0FVX3lxTE9NWmE

The editor sees the same story three times.

NOT FIXED HERE, deliberately. Merging on title is what the failing tests ask
for and it is the wrong thing to implement blindly: shared titles are routine
in wire copy ("Обявиха новия кмет", "Промените в сила") and title-keyed
merging collapses unrelated stories. It also has to be decided against a live
corpus of 467 stories, not inferred. This file records the measurement so the
next person starts from evidence.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

STORIES = Path("var/newsroom/stories.json")
INBOX = Path("var/newsroom/inbox.jsonl")


def _title_key(title: str) -> str:
    return re.sub(r"[^a-zа-я]+", "", (title or "").lower())[:70]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Grouping keys on publication_key, which is URL-derived, and Google News "
        "RSS gives every item its own opaque redirect URL. Identical headlines "
        "therefore never merge. Measured: 5 such headlines, one of them in 3 "
        "separate Stories. Fixing it needs an owner decision — title-keyed "
        "merging collapses unrelated stories that share routine wire wording. "
        "See this file's docstring."
    ),
)
def test_identical_headlines_are_currently_split_across_stories():
    """The defect, recorded so it cannot be quietly forgotten.

    Marked xfail, not asserted-failing: a permanently red test reads as a new
    regression and trains people to ignore red. `strict=False` means the day
    grouping is fixed this reports XPASS, which is the signal to replace it
    with a real merge test.
    """
    if not STORIES.exists() or not INBOX.exists():
        return  # no live corpus in this environment; the unit tests cover it
    rows = [json.loads(line) for line in INBOX.read_text(encoding="utf-8").splitlines() if line]
    by_id = {r["item_id"]: r for r in rows}
    store = json.loads(STORIES.read_text(encoding="utf-8"))
    stories = store.get("stories", store)
    stories = stories if isinstance(stories, list) else list(stories.values())

    by_title = defaultdict(set)
    for story in stories:
        for member in story.get("members", []):
            item = by_id.get(member["item_id"])
            if item:
                by_title[_title_key(item["title"])].add(story["story_id"])

    split = {t: ids for t, ids in by_title.items() if t and len(ids) > 1}
    assert not split, (
        f"{len(split)} identical headline(s) are split across separate stories; "
        f"e.g. {next(iter(split))[:50]!r} -> {len(next(iter(split.values())))} stories"
    )
