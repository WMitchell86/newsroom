"""V1.2-G4.1 §A — the deterministic Burgas-region scope of the `Днес` desk.

**Why this module exists.** The owner's screen showed national wire copy
(Ирак, ЕК, Северна Македония, младежки национален футбол, АЕЖ) sitting on a
Burgas regional desk. Tracing the real corpus showed why: `project_today`
admitted **any** Story that was new or unreviewed inside the horizon, and
`bta-burgas` is a `kind: media` row on the *national* domain `bta.bg` collected
through a publisher-wide monitoring query. The publisher is a national news
agency; only its name mentions the region. There was no locality decision in the
Today path at all, so a national item looked identical to a Burgas one.

**The rule is deliberately simple and explainable.** A Story belongs to the
default regional view when ANY of three deterministic conditions holds. There is
no score, no weighting, no ranking and no model call, because every attempt at
one in this repository collapsed onto two levels and taught the editor nothing
(see `m4/review/V1_1_E1_JEV_RANKING_SHADOW_REPORT.md`).

  1. **Local source** — a current Publication comes from a source the editor
     has configured as a local institution or local outlet. That is registry
     `kind` in `{official, regional}`. These are the Burgas-region stack the
     newsroom is built on: the municipalities, ОДМВР Бургас, Областна администрация
     Бургас, the regional library and opera, and the local media rows.
  2. **Geographic text** — the cleaned Story title or concise summary names a
     Burgas-region locality outright.
  3. **Editorial work** — the Story is followed and has an unreviewed
     development, or already has an active Article. The editor never loses work
     that is in flight because a locality was not yet detected.

**Source authority and regional relevance are separate (§A3).** A national
publisher is never local by itself: BTA writing about Ирак is national, BTA
writing about Община Бургас is regional. Rule 1 encodes exactly that — a
`media`/`national`/`aggregator` row contributes nothing on its own, and a BTA or
БНР item only qualifies through rule 2, on the strength of its own text.

**Nothing is deleted.** This module is a pure predicate over already-loaded
canonical rows. It filters what the *desk* shows; `Истории` still reaches every
collected Story, and no store is ever written from here.
"""

from __future__ import annotations

import re

#: Registry `kind` values that mean "this is a Burgas-region institution or
#: local outlet", per §A2's local source rule. Deliberately excludes `media` and
#: `national` (national publishers) and `aggregator` (the catch-all monitoring

#: The closed Burgas-region locality vocabulary (§A2). Each entry is a stem, so
#: one listed place also covers its own adjectival forms: `бург` matches
#: `Бургас`, `бургаски`, `Бургаско` and `Бургашка` alike.
#:
#: These are stems and not whole words only where the adjective genuinely names
#: the same place. `черноморец` is deliberately the full town name and NOT a
#: `черномор` stem: `Черноморието` is this site's own name and `черноморски`
#: describes the whole Bulgarian coast, so a stem there would pull Varna and
#: Varna-oblast news onto a Burgas desk.
REGIONAL_LOCALITY_STEMS = (
    "бург",
    "помори",
    "несебър",
    "созопол",
    "царев",
    "приморск",
    "карнобат",
    "айтос",
    "руен",
    "каблешково",
    "черноморец",
    "ахтопол",
    "лозенец",
)

#: Pre-compiled once. A stem matches at a word start, so `бург` binds to
#: `Бургас` but can never bind to an unrelated suffix inside a longer word.
_LOCALITY_RX = re.compile(
    r"(?<![\w-])(?:" + "|".join(REGIONAL_LOCALITY_STEMS) + r")",
    re.IGNORECASE | re.UNICODE,
)


def regional_localities() -> tuple[str, ...]:
    """The closed locality vocabulary, for the settings/report surface."""
    return REGIONAL_LOCALITY_STEMS


def is_local_source(source_id: str, registry_rows) -> bool:
    """Whether the registry configures this source as Burgas-region/local.

    `source_id` is matched against the registry by identity, never by guessing
    a domain. A source absent from the registry is not local: an unconfigured
    source has made no local claim yet, and treating it as local would reopen
    the national-wire hole this rule exists to close.
    """
    wanted = str(source_id or "")
    if not wanted:
        return False
    for row in registry_rows or ():
        if str((row or {}).get("source_id") or "") == wanted:
            return str(row.get("kind") or "") in LOCAL_SOURCE_KINDS
    return False


def mentions_region(text: str) -> bool:
    """Whether cleaned editorial text names a Burgas-region locality.

    Matching is over the Story's own title and summary only. The *source name*
    is never scanned: `bta-burgas` is named "БТА — област Бургас", and reading
    that name would make every BTA wire item regional — the precise defect this
    module was written to remove.
    """
    if not text:
        return False
    return bool(_LOCALITY_RX.search(str(text)))


def story_has_local_publication(story: dict, items_by_id: dict, registry_rows) -> bool:
    """Rule 1 — at least one current Publication comes from a local source."""
    for member in story.get("members") or []:
        item = items_by_id.get(member.get("item_id")) or {}
        if is_local_source(item.get("source_id"), registry_rows):
            return True
    return False


def story_text_mentions_region(story: dict, items_by_id: dict, *, title: str) -> bool:
    """Rule 2 — the Story's cleaned title or its concise summary is regional.

    The title is the already-cleaned editorial title the desk itself shows, so
    the filter can never disagree with the row above it about what the Story is
    called.
    """
    if mentions_region(title):
        return True
    representative = items_by_id.get(story.get("representative_item_id")) or {}
    if mentions_region(representative.get("summary")):
        return True
    for member in story.get("members") or []:
        if mentions_region((items_by_id.get(member.get("item_id")) or {}).get("summary")):
            return True
    return False


def story_has_active_article(story_id: str, article_records) -> bool:
    """Rule 3a — the Story already has an Article the editor is working on."""
    for article in article_records or ():
        if article.get("story_id") != story_id:
            continue
        if not article.get("finalized_at"):
            return True
    return False


def story_is_followed_with_development(story: dict, metadata: dict) -> bool:
    """Rule 3b — followed, with something the editor has not seen yet."""
    if not (metadata or {}).get("followed"):
        return False
    reviewed = set((metadata or {}).get("reviewed_development_ids") or [])
    from editor_assistant.workflow import editor_projections

    developments = editor_projections.meaningful_developments(story, {})
    return any(row["id"] not in reviewed for row in developments)


def _has_self_scoping_publication(story: dict, items_by_id: dict, registry_rows) -> bool:
    for member in story.get("members") or []:
        item = items_by_id.get(member.get("item_id")) or {}
        if source_is_self_scoping(item.get("source_id"), registry_rows):
            return True
    return False


def _any_member_mentions_region(story: dict, items_by_id: dict, *, title: str) -> bool:
    if mentions_region(title):
        return True
    for member in story.get("members") or []:
        item = items_by_id.get(member.get("item_id")) or {}
        for field in ("title", "summary"):
            if mentions_region(str(item.get(field) or "")):
                return True
    return False


def story_is_regional(
    story: dict,
    metadata: dict,
    items_by_id: dict,
    *,
    title: str,
    registry_rows=(),
    article_records=(),
) -> bool:
    """The one regional predicate. Pure; reads only already-loaded rows.

    Any one of the three conditions is sufficient. The editorial-work rule is
    checked first so in-flight work is never evaluated for locality at all: if
    the editor is already writing this Story, hiding it would lose the work.
    """
    story_id = str(story.get("story_id") or "")
    if story_has_active_article(story_id, article_records):
        return True
    if story_is_followed_with_development(story, metadata):
        return True
    if _has_self_scoping_publication(story, items_by_id, registry_rows):
        return True
    if story_text_mentions_region(story, items_by_id, title=title):
        return True
    # A merely regional outlet is the last resort, and only together with
    # regional text. On its own it is a republication, which is precisely what
    # this predicate was written to keep off the desk.
    return story_has_local_publication(story, items_by_id, registry_rows) and bool(
        _any_member_mentions_region(story, items_by_id, title=title)
    )

#: query, which is exactly what dragged national copy onto the desk).
#: Sources whose own publication is EVIDENCE of locality, because they only
#: ever speak about themselves: a municipality, a court, a hospital, an airport.
#:
#: Measured on the live regional desk. `kind="regional"` was treated as equally
#: strong, and six Stories qualified on that alone with no regional word in the
#: title or the body — three of them national:
#:
#:   "Петрова: България трябва ясно да определи своята роля"
#:   "Акция срещу „Хелс Ейнджълс" и в България: Над 1000 полицаи"
#:   "България сменя регионалната карта"
#:
#: All three came from `darik-burgas` (kind=regional, domain=dariknews.bg) — a
#: NATIONAL outlet's Burgas channel. Being a local source does not make a
#: Story regional; a republication of national wire is not regional news just
#: because a Burgas desk put it on its site.
#:
#: A `regional` source is therefore no longer sufficient on its own. It still
#: counts when the Story's text carries regional substance, which the existing
#: `story_text_mentions_region` already decides.
LOCAL_SOURCE_KINDS = frozenset({"official", "regional"})

#: The subset that speaks only for itself.
SELF_SCOPING_SOURCE_KINDS = frozenset({"official"})


def source_is_self_scoping(source_id: str, registry_rows) -> bool:
    """True when this source's own publication is evidence of locality.

    An institution — municipality, court, hospital, airport — publishes about
    itself and about nothing else, so its carrying a Story places that Story
    in the region. A news outlet does not, however regional its name: it
    republishes the national wire, and that is what the regional desk is for.
    """
    wanted = str(source_id or "")
    if not wanted:
        return False
    for row in registry_rows or ():
        if str((row or {}).get("source_id") or "") == wanted:
            return str(row.get("kind") or "") in SELF_SCOPING_SOURCE_KINDS
    return False
