"""V1.2-G2.4 §B — event-level search coverage: find OTHER publishers on THIS event.

**Why this module exists.** G2.3 proved the real remaining bottleneck is
*coverage*, not the evidence gate. The pages open, the claims are extracted, and
then the comparer correctly answers `DIFFERENT_FACT` — because the publishers
that search returned were writing about something else. G2.3's own example
paired "Министър Шишков ще инспектира ремонта на художествената галерия" with
"Царево с две отличия в конкурс…". That is a search problem.

**What this module adds, in order of what actually helps.**

1. `event_anchors` / `event_queries` (§B1, §B2) — a small, bounded, *deterministic*
   ladder of queries built from the Story's own identifying material, rather
   than one generic `topic + " Бургас"` string. Tier 1 uses the distinctive
   event phrase, Tier 2 the compressed entity+action+locality identity, Tier 3
   key name/number/place combinations. A bounded set, never dozens of variants.
2. `event_filter` (§B7) — a deterministic pre-open filter that drops a result
   whose own metadata contradicts the Story's locality/date, so the expensive
   open is never spent on a page about another accident. Snippet/title metadata
   is used for *ranking and filtering only*; it can never become a fact.
3. The Serper discovery budget (§B3–§B5) lives in `search`; this module owns
   only the anchors, the ladder and the filter it needs.

**The safety rule is untouched.** Nothing here grants authority, promotes a
fact, or weakens the independent-publisher requirement. A snippet can never
back a fact; only an opened page on a real publisher can, and only then does
the existing `story_research` promotion logic apply.
"""

from __future__ import annotations

import re

#: The generic local anchor the old planner appended to every query. §B1 says
#: NOT to do that blindly: when the event already carries a stronger locality,
#: appending "Бургас" only widens the search towards unrelated regional news.
DEFAULT_LOCATION = "Бургас"

#: §B5 — the Research-specific Serper budget. Three per round is the owner's
#: suggested starting point, bounded per *round* rather than per day, so a
#: single Story can never spend the account. Measured on the frozen 24-Story
#: sample by `scripts/v12g24_coverage_replay.py`; it is a policy constant, not
#: a per-call argument, so no caller can raise it.
MAX_SERPER_QUERIES_PER_ROUND = 3

#: §B2 — the ladder is small on purpose. A bounded ladder of tiers beats a wide
#: fan-out of query variants, because each extra query costs part of the
#: owner's Serper allocation while the recall gain flattens immediately.
MAX_TOTAL_QUERIES = 6



# ---------------------------------------------------------------------------
# §B1/B2 — deterministic event query ladder
# ---------------------------------------------------------------------------


#: §B1 — the high-signal EVENT/ACTION vocabulary of Bulgarian local news.
#:
#: These are the words that make a query event-specific. Measured on the frozen
#: sample: `"\"Бургас-Созопол\""` alone returns bus timetables, while
#: `"\"Бургас-Созопол\"" пострадаха катастрофа` returns the ten publishers that
#: actually covered the accident. The list is a small, curated, deterministic
#: template set — the same kind of generic editorial template §D4 allows for the
#: Focus — and never a model call. A word that is not here simply is not used as
#: an action anchor; the ladder still works, only more generically.
_EVENT_WORDS = frozenset(
    {
        "пострадаха", "пострадал", "пострадала", "загина", "загинал", "загинаха",
        "ранен", "ранени", "катастрофа", "катастрофи", "инцидент", "инциденти",
        "пожари", "пожар", "земетресение", "наводнение", "сблъскване", "обръщане",
        "крадеж", "грабеж", "нападение", "авари", "авария", "проблем",
        "отвори", "отвориха", "отваря", "започна", "започнаха", "завърши",
        "представи", "представя", "представяне", "изнесе", "изнася", "изяви",
        "прие", "приеха", "одобри", "одобриха", "отхвърли", "избра", "провежда",
        "пристигна", "заминава", "завършиха", "подписа", "обяви",
        "награди", "празнува", "отдава", "посрещне", "среща", "изложба", "концерт",
        "спектакъл", "турнир", "мач", "предаване", "зала", "събитие", "фестивал",
    }
)


def _action_words(value: str) -> list[str]:
    """The event/action words of a subject, in appearance order.

    Falls back to the distinctive content words when a subject names no known
    event word, so the ladder degrades to a generic-but-still-bounded query
    rather than to nothing at all.
    """
    words = _content_words(value, for_query=True)
    actions = [w for w in words if w in _EVENT_WORDS]
    return actions or words


#: §B1 — words that carry no SEARCH signal either, because they are true noise
#: rather than event vocabulary. This is deliberately MUCH narrower than the
#: claim-agreement blocklist: "пострадаха" and "катастрофа" are exactly the words
#: that make `"Бургас-Созопол" пострадаха катастрофа` find the right publishers,
#: while `"Бургас-Созопол"` alone returns bus timetables. Reusing the anchor
#: blocklist here was measured to cost most of the recall.
_QUERY_NOISE_WORDS = frozenset(
    {
        "новини", "новина", "статия", "статии", "български", "българска", "българия",
        "българският", "днес", "вчера", "утре", "година", "години", "годишен",
        "събитие", "събития", "събитието", "съобщение", "съобщения", "източник",
        "публикация", "медия", "медиите", "новинар", "кореспондент", "инцидент",
        "произшествие", "според", "пътят", "пътища", "път", "пътя",
    }
)


def _content_words(value: str, *, for_query: bool = False) -> list[str]:
    """Distinctive content words of one text, generic news vocabulary removed.

    The claim-agreement blocklist is imported from the extraction side rather
    than restated here, so the ladder and the extractor cannot drift apart on
    what counts as a distinctive term.

    `for_query=True` uses the much narrower noise list instead, because the two
    jobs are genuinely different: an event word like `пострадаха` must never
    count towards claim agreement, but it is precisely what a search query
    needs in order to return publishers covering that event.
    """
    from editor_assistant.workflow.claim_quality import _NEVER_ANCHOR, _key

    blocked = _QUERY_NOISE_WORDS if for_query else _NEVER_ANCHOR
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[\wа-яА-Я]+", str(value or "").casefold()):
        if len(raw) <= 3:
            continue
        key = _key(raw)
        if len(key) < 4 or key in blocked or key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return out


#: Locality is detectable without a gazetteer: a capitalised word in a title is
#: a place far more often than not, and the case that matters (§B7) is a
#: *contradiction*, which only needs the Story's own locality set.
_CAPS_WORD = re.compile(r"\b[А-Я][а-я]{2,}\b")

#: Punctuation that separates the two ends of a road/route name — the shape
#: carrying the strongest same-event signal in Bulgarian local news.
_DASH = re.compile(r"\s*[–—/-]\s*")

#: A road/route phrase: "пътя Бургас-Созопол", "пътя Стара Загора – Казанлък".
#: The `път` marker is what makes this high-precision, so it is required rather
#: than assumed — a bare dash between two capitalised words is far too common in
#: ordinary prose to be treated as a locality pair.
_ROAD = re.compile(
    r"\bпът(?:я|ят|ища|ищата)?\s+"
    r"([А-Я][а-я]+(?:[\s–—-]+[А-Я][а-я]+){0,2})",
    re.IGNORECASE,
)

#: Capitalised words that open a headline and name nothing: "Нов", "Първи",
#: "Още". §B1 needs real entities, and counting an ordinary adjective as a person
#: or an organisation would produce a Tier-2 query built on nothing.
_NON_ENTITY_OPENERS = frozenset(
    {
        "нов", "нова", "нови", "ново", "първи", "първа", "първо", "втори", "втора",
        "второ", "трети", "трета", "трето", "още", "следващ", "следваща",
        "бъдещ", "бъдеща", "поред", "последен", "последна", "само", "вече", "как",
        "кой", "която", "когато", "къде", "защо", "какво", "пътя", "пътят",
    }
)


def _road_phrase(text: str) -> str:
    """The dash-joined locality pair of a road/route phrase, or `""`.

    Requires the `път` marker, so "Нов спортен комплекс" never produces a
    locality pair and "пътя Бургас-Созопол" always does.
    """
    for match in _ROAD.finditer(str(text or "")):
        span = match.group(1).strip()
        parts = [part.strip() for part in _DASH.split(span) if part.strip()]
        if len(parts) >= 2 and all(_CAPS_WORD.fullmatch(part) for part in parts):
            return "-".join(parts)
    return ""


def _entities(text: str) -> list[str]:
    """Capitalised spans that actually name a person, organisation or place."""
    out: list[str] = []
    for word in _CAPS_WORD.findall(str(text or "")):
        if word.casefold() in _NON_ENTITY_OPENERS:
            continue
        if word not in out:
            out.append(word)
    return out


def event_anchors(topic: str) -> dict:
    """The identifying material of one Story event, as a small explicit record.

    Deliberately a named record rather than a free-form query string, because
    every consumer downstream (the query ladder, the result filter, the audit
    record) needs to reason about *which* anchor it used:

    * `subject`    — the cleaned Story title, used verbatim in Tier 1;
    * `entities`   — capitalised spans (a person, an organisation, a place);
    * `localities` — capitalised spans long enough to name a place;
    * `terms`      — distinctive content words, generic news vocabulary removed;
    * `road`       — a dash-joined locality pair, the strongest same-event signal.
    """
    text = " ".join(str(topic or "").split())
    entities = _entities(text)
    return {
        "subject": text,
        "entities": entities,
        "localities": [word for word in entities if len(word) > 3],
        "terms": _content_words(text),
        "road": _road_phrase(text),
    }


def _registered_official_domain(title: str) -> str | None:
    """The domain of a registered OFFICIAL source this Story names, if any.

    Deliberately conservative, because `site:` excludes everything else: a
    wrong domain is worse than no domain, because it locks the authority out.

    * Only entries the editor registered as `official`. A media source is
      coverage, not the authority a reader would go to for the decision.
    * Matched on the HEAD of the registered name. Entries carry qualifiers the
      Story will not have — «Летище Бургас / Fraport», «БТА — област Бургас»
      — and requiring the full string missed a registered official source.
    * A loose token match is NOT used. «Бургас» appears in a dozen entries and
      would aim a budget story at burgas-os.justice.bg. The full head
      required for a match keeps «Окръжен съд Бургас» precise.
    * A missing or unreadable registry is not a reason to fail the round; it
      simply contributes nothing.
    """
    text = (title or "").casefold()
    if not text:
        return None
    try:
        from editor_assistant.workflow import sources_registry

        rows = sources_registry.describe_all()
    except Exception:  # noqa: BLE001 - the registry is configuration, not a dependency
        return None
    best: tuple[int, str] | None = None
    for row in rows:
        if (row.get("kind") or "") != "official":
            continue
        domain = (row.get("domain") or "").strip()
        name = (row.get("name") or "").strip()
        if not domain or not name:
            continue
        needle = name.casefold().split("\u2014")[0].split("/")[0].strip()
        if len(needle) >= 6 and needle in text and (best is None or len(needle) > best[0]):
            best = (len(needle), domain)
    return best[1] if best else None


def event_queries(
    anchors: dict, *, missing_dimensions=(), limit: int = MAX_TOTAL_QUERIES
) -> list[str]:
    """The bounded, deterministic query ladder for one Story (§B1, §B2).

    Three tiers, in order, each derived from the Story's own anchors:

    * **Tier 1 — exact event anchors.** The distinctive subject phrase, quoted
      when it is a specific event title, and the road/route when the Story names
      one. This is the query that finds other publishers on the *same* event.
    * **Tier 2 — compressed event identity.** Central entity + action term +
      locality: the words that only one publication used are dropped.
    * **Tier 3 — key factual anchors.** Distinctive term combinations, used only
      when the Story names no entity to search on.

    The ladder stops at ``limit`` and never repeats a query. §B1's "do not append
    Бургас blindly" is honoured: the generic region is a last resort, used only
    when the Story itself carries no locality and no entity.
    """
    subject = str(anchors.get("subject") or "").strip()
    if not subject:
        return []

    entities = list(anchors.get("entities") or [])
    localities = list(anchors.get("localities") or [])
    terms = list(anchors.get("terms") or [])
    road = str(anchors.get("road") or "").strip()

    queries: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        text = " ".join(str(value or "").split())
        if not text:
            return
        folded = text.casefold()
        if folded in seen:
            return
        seen.add(folded)
        queries.append(text)

    # Tier 1 — the event itself.
    #
    # A specific multi-word subject is quoted: that is what turns "some page with
    # similar words" into "this event".
    if len(subject.split()) >= 3:
        push(f'"{subject}"')
    else:
        push(subject)
    # Tier 1b — the authority itself, when the Story names a REGISTERED
    # official publisher.
    #
    # Measured before this existed. For «Общински съвет прие бюджета на
    # Община Бургас за 2027 година» the ladder was:
    #
    #   1. "Общински съвет прие бюджета на Община Бургас за 2027 година"
    #   2. "Общински съвет прие бюджета на Община Бургас за 2027 година"
    #      Какво точно се променя.
    #
    # Both ask for COVERAGE. Neither names the one source that settles a
    # municipal decision — the municipality's own site — even though the editor
    # has already registered it and 32 of 35 entries carry a usable domain.
    # The other rung stays, because corroboration needs other publishers; this
    # one adds the authority the ladder was structurally unable to reach.
    official = _registered_official_domain(subject)
    if official:
        push(f'"{subject}" site:{official}')
    # The road/route pair is the strongest locality signal, BUT measured alone it
    # is too generic: `"Бургас-Созопол"` on its own returns bus timetables. It is
    # therefore only useful WITH the event's own action words, which is exactly
    # §B1's "distinctive event/action" anchor.
    if road:
        action = [w for w in _action_words(subject) if w not in road.casefold()][:2]
        push(f'"{road}" {" ".join(action)}'.strip() if action else f'"{road}"')

    # Tier 2 — compressed identity: entity + action term + locality.
    core_entity = next((e for e in entities if not e.isupper()), "")
    distinctive = [w for w in _action_words(subject) if w not in subject.casefold()][:2]
    if core_entity and distinctive:
        locality = next((loc for loc in localities if loc != core_entity), "")
        push(" ".join(part for part in (core_entity, *distinctive, locality) if part))

    # Tier 3 — anchor combinations, and only when the Story names no entity.
    if not entities and len(terms) >= 2:
        push(" ".join(terms[:3]))

    # §B1: the generic region is a LAST resort, used only when the Story itself
    # carries no locality and no entity to search on.
    if len(queries) == 1 and not localities and not entities:
        push(f"{subject} {DEFAULT_LOCATION}")

    # A missing dimension sharpens an existing query rather than inventing a new
    # one, so the ladder never grows a tier the anchors cannot justify.
    for dimension in list(missing_dimensions or [])[:1]:
        cue = str(dimension).replace("_", " ").strip()
        if cue and queries:
            push(f"{queries[0]} {cue}")

    return queries[: max(1, int(limit))]


# ---------------------------------------------------------------------------
# §B7 — deterministic search-result event filter
# ---------------------------------------------------------------------------


def event_filter(anchors: dict, candidates) -> list[dict]:
    """Rank and filter discovery results against the Story's event anchors.

    `candidates` are search results (title/url/snippet). Nothing here is ever
    promoted: the return value is a **reordered and reduced discovery list**.
    Snippet text is read only to decide what is worth opening, exactly as §B7
    permits, and never as evidence.

    Ranking, strongest first:

    1. a result whose metadata contains the Story's road/route pair;
    2. a result sharing two or more of the Story's distinctive terms;
    3. a result that neither matches nor contradicts — kept, so recall is never
       sacrificed to a weak anchor set.

    A result naming a locality the Story does not name, while sharing no
    distinctive term, is REJECTED: that is the "Катастрофа край Казанлък…"
    case, decided from metadata before the expensive open.
    """
    from editor_assistant.workflow.claim_quality import _NEVER_ANCHOR, _key

    subject_localities = {
        _key(word.casefold()) for word in (anchors.get("localities") or []) if len(word) > 3
    }
    terms = {
        _key(term) for term in (anchors.get("terms") or []) if _key(term) not in _NEVER_ANCHOR
    }
    road_key = str(anchors.get("road") or "").strip().casefold()

    kept: list[dict] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        # The metadata a filter may read. Never the page body.
        title = str(candidate.get("title") or "")
        haystack = " ".join(
            str(candidate.get(field) or "") for field in ("title", "url", "snippet")
        ).casefold()
        if not haystack.strip():
            continue
        if road_key and road_key in haystack:
            kept.append({**candidate, "_event_score": 3})
            continue
        hits = len(terms & {_key(w) for w in re.findall(r"[\wа-яА-Я]+", haystack)})
        result_localities = {
            _key(word.casefold()) for word in _CAPS_WORD.findall(title) if len(word) > 3
        }
        contradicts = (
            bool(subject_localities)
            and bool(result_localities)
            and not (result_localities & subject_localities)
            and hits < 2
        )
        if contradicts:
            continue
        kept.append({**candidate, "_event_score": min(hits, 2)})

    kept.sort(key=lambda row: -int(row.get("_event_score") or 0))
    return kept

