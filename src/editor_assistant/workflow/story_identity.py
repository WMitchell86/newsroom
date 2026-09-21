"""M4C: story identity service — the one shared incremental story builder.

Pipeline per unassigned inbox item:

```text
Stage A  exact publication_key already in a story   -> SAME_STORY (no model call)
Stage B  cheap deterministic shortlist (<=5 stories, <=7 days) of recent stories
         strong title + time + distinctive-token test -> SAME_STORY (no model call)
         otherwise: the shortlist goes to the narrow semantic relation
Stage C  semantic relation (role="story"), only for the ambiguous shortlist
         provider unavailable / malformed -> SEPARATE STORY + needs_review
```

Design rules that were expensive to learn elsewhere in this repository:

* **cheap first** — never compare every item to every story; no embeddings, no
  all-pairs model calls, no long-term topic memory;
* **false merge is worse than false split** — `uncertain -> separate`; the editor
  can merge a false split, but a false merge hides a distinct story;
* **the semantic model is a fallback, not the engine** and infrastructure failure
  can never force a merge;
* **`NEW_DEVELOPMENT` is never inferred from token similarity** — only a real
  semantic answer may reopen a story.

The raw inbox is preserved: this service only ever *reads* it (plus the status
propagation an editor action explicitly asks for).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from editor_assistant.workflow import (
    blocked_domains,
    inbox_store,
    publication_identity,
    source_health,
    story_relation,
    story_store,
)

#: Only recent stories are candidates (no long-term topic memory yet).
STORY_SHORTLIST_DAYS = 7
SHORTLIST_SIZE = 5

#: Deterministic auto-match thresholds — deliberately conservative.
STRONG_TITLE_OVERLAP = 0.8
STRONG_DISTINCTIVE_OVERLAP = 0.6
CLOSE_PUBLICATION_HOURS = 48

TOKEN_RX = re.compile(r"[а-яёa-z0-9]+", re.UNICODE)

#: Function words / newsroom noise, in Bulgarian and English. Removing them is why
#: "Общинският съвет прие бюджета" and "Бюджетът мина през съвета" cannot match on
#: generic vocabulary alone.
STOPWORDS = frozenset(
    [
        "и",
        "в",
        "във",
        "вв",
        "на",
        "за",
        "от",
        "с",
        "със",
        "по",
        "при",
        "през",
        "до",
        "под",
        "над",
        "след",
        "пред",
        "без",
        "към",
        "че",
        "да",
        "е",
        "са",
        "се",
        "си",
        "ще",
        "би",
        "бил",
        "била",
        "било",
        "бе",
        "беше",
        "щял",
        "щяла",
        "щяло",
        "не",
        "ни",
        "но",
        "или",
        "ако",
        "като",
        "кой",
        "коя",
        "кое",
        "кои",
        "кога",
        "къде",
        "как",
        "какво",
        "защо",
        "този",
        "тази",
        "това",
        "тези",
        "онзи",
        "онази",
        "онова",
        "той",
        "тя",
        "то",
        "те",
        "му",
        "ѝ",
        "им",
        "го",
        "я",
        "ме",
        "ни",
        "ви",
        "ги",
        "съм",
        "сме",
        "сте",
        "нов",
        "нови",
        "нова",
        "ново",
        "новина",
        "новини",
        "новият",
        "новата",
        "новото",
        "съобщи",
        "съобщава",
        "община",
        "общински",
        "общинският",
        "съвет",
        "бургас",
        "българия",
        "бг",
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "those",
        "these",
        "will",
        "was",
        "were",
        "has",
        "have",
        "had",
        "are",
        "is",
        "news",
        "today",
        "report",
        "reports",
        "says",
        "said",
        "new",
    ]
)


def _now():
    return datetime.now(timezone.utc)


def tokens(text):
    """Lowercased word/number tokens (Cyrillic + Latin)."""
    return TOKEN_RX.findall(str(text or "").lower())


def distinctive_tokens(text):
    """Tokens that can actually identify an event (numbers always count)."""
    out = set()
    for token in tokens(text):
        if token.isdigit() or (len(token) >= 3 and token not in STOPWORDS):
            out.add(token)
    return out


def title_overlap(left, right):
    """Jaccard overlap of distinctive tokens (0.0 when there is nothing to compare)."""
    a, b = distinctive_tokens(left), distinctive_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _item_moment(item):
    return source_health.parse_timestamp(item.get("published_at")) or source_health.parse_timestamp(
        item.get("discovered_at")
    )


def _story_moment(story, items_by_id):
    moments = [
        _item_moment(items_by_id[m["item_id"]])
        for m in story["members"]
        if m["item_id"] in items_by_id
    ]
    moments = [m for m in moments if m is not None]
    return max(moments) if moments else None


def similarity(item, story, items_by_id):
    """Cheap deterministic hint: title/summary tokens, numbers, time proximity.

    The score is a **retrieval hint only** — it never grants authority to merge
    loosely related stories by itself (that is what the conservative deterministic
    test below and the narrow semantic step are for).
    """
    member_rows = [
        items_by_id[m["item_id"]] for m in story["members"] if m["item_id"] in items_by_id
    ]
    if not member_rows:
        return {"score": 0.0, "title": 0.0, "distinctive": 0.0, "numbers": 0.0, "hours": None}
    title = max(title_overlap(item.get("title"), row.get("title")) for row in member_rows)
    item_tokens = distinctive_tokens(f"{item.get('title')} {item.get('summary')}")
    story_tokens = set()
    for row in member_rows:
        story_tokens |= distinctive_tokens(f"{row.get('title')} {row.get('summary')}")
    shared = item_tokens & story_tokens
    distinctive = len(shared) / max(len(item_tokens), 1)
    item_numbers = {t for t in item_tokens if t.isdigit()}
    story_numbers = {t for t in story_tokens if t.isdigit()}
    numbers = len(item_numbers & story_numbers) / max(len(item_numbers), 1) if item_numbers else 0.0
    moment, story_moment = _item_moment(item), _story_moment(story, items_by_id)
    hours = None
    if moment and story_moment:
        hours = abs((moment - story_moment).total_seconds()) / 3600.0
    base = 0.5 * title + 0.3 * distinctive + 0.1 * numbers
    # No shared text at all means no candidate: a story from yesterday is not a
    # match merely because it was published around the same time.
    score = 0.0
    if base > 0:
        score = base + (0.1 if hours is not None and hours <= CLOSE_PUBLICATION_HOURS else 0.0)
    return {
        "score": round(score, 4),
        "title": round(title, 4),
        "distinctive": round(distinctive, 4),
        "numbers": round(numbers, 4),
        "hours": None if hours is None else round(hours, 2),
        "shared_tokens": sorted(shared)[:10],
    }


def shortlist(
    item, store, items_by_id, *, now=None, days=STORY_SHORTLIST_DAYS, size=SHORTLIST_SIZE
):
    """Recent stories worth comparing, best score first (never the whole store)."""
    moment = now or _now()
    floor = moment - timedelta(days=days)
    scored = []
    for story in store["stories"]:
        story_moment = _story_moment(story, items_by_id)
        # An undated story is still eligible: with no usable timestamp we cannot
        # honestly exclude it, and the deterministic test is conservative anyway.
        if story_moment is not None and story_moment < floor:
            continue
        detail = similarity(item, story, items_by_id)
        if detail["score"] <= 0:
            continue
        scored.append((detail["score"], story["story_id"], story, detail))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [(story, detail) for _score, _sid, story, detail in scored[:size]]


def deterministic_relation(item, story, detail):
    """`(relation, reason)` for an extremely strong match, else `(None, reason)`.

    Only `SAME_STORY` can be decided this way — a materially new development needs
    semantics, never token overlap.
    """
    strong = (
        detail["title"] >= STRONG_TITLE_OVERLAP
        and detail["distinctive"] >= STRONG_DISTINCTIVE_OVERLAP
        and (detail["hours"] is None or detail["hours"] <= CLOSE_PUBLICATION_HOURS)
    )
    if strong:
        reason = (
            f"near-identical title ({detail['title']}) + distinctive overlap "
            f"({detail['distinctive']}) + close publication time"
        )
        return "SAME_STORY", reason
    return None, "below the deterministic threshold"


def process_item(item, store, items_by_id, *, semantic=True, call_model=None, now=None):
    """Assign one unassigned item. Returns an outcome dict; never raises for models.

    The caller decides whether to persist `store` (the service works on a copy in
    dry-run mode).
    """
    key = publication_identity.publication_key(item)
    outcome = {
        "item_id": item["item_id"],
        "publication_key": key or "",
        "action": "",
        "relation": "",
        "relation_source": "",
        "story_id": "",
        "needs_review": False,
        "new_story": False,
        "semantic_call": False,
        "reason": "",
    }

    # ---- Stage A: exact publication identity (no model call)
    if key:
        existing = story_store.story_id_for_publication(store, key)
        if existing:
            story = story_store.story_by_id(store, existing)
            story_store.add_member(
                story,
                item,
                relation="SAME_STORY",
                relation_source=story_store.SOURCE_EXACT_PUBLICATION,
                publication_key=key,
                now=now,
            )
            story_store.refresh_times(story, items_by_id, now=now)
            outcome.update(
                action="EXACT_DUPLICATE",
                relation="SAME_STORY",
                relation_source=story_store.SOURCE_EXACT_PUBLICATION,
                story_id=existing,
                reason="same publication_url + publisher_domain",
            )
            return outcome

    # ---- Stage B: deterministic shortlist
    candidates = shortlist(item, store, items_by_id, now=now)
    for story, detail in candidates:
        relation, reason = deterministic_relation(item, story, detail)
        if relation:
            story_store.add_member(
                story,
                item,
                relation=relation,
                relation_source=story_store.SOURCE_DETERMINISTIC_TITLE,
                publication_key=key or "",
                now=now,
            )
            story_store.refresh_times(story, items_by_id, now=now)
            outcome.update(
                action="DETERMINISTIC",
                relation=relation,
                relation_source=story_store.SOURCE_DETERMINISTIC_TITLE,
                story_id=story["story_id"],
                reason=reason,
            )
            return outcome

    # ---- Stage C: narrow semantic relation for the ambiguous shortlist
    if candidates and semantic:
        outcome["semantic_call"] = True
        for story, detail in candidates:
            answer = story_relation.classify(item, story, items_by_id, call_model=call_model)
            if answer is None:
                # Infrastructure failure never merges: keep separate, flag review.
                outcome.update(
                    action="REVIEW",
                    needs_review=True,
                    reason=(
                        f"semantic model unavailable or invalid (shortlist score "
                        f"{detail['score']}); kept separate"
                    ),
                )
                break
            if answer["relation"] == "DIFFERENT_STORY":
                continue
            story_store.add_member(
                story,
                item,
                relation=answer["relation"],
                relation_source=story_store.SOURCE_SEMANTIC,
                publication_key=key or "",
                now=now,
            )
            story_store.refresh_times(story, items_by_id, now=now)
            outcome.update(
                action="SEMANTIC",
                relation=answer["relation"],
                relation_source=story_store.SOURCE_SEMANTIC,
                story_id=story["story_id"],
                reason=answer["reason"],
            )
            return outcome
        else:
            outcome.update(
                action="SEPARATE",
                needs_review=True,
                reason="every shortlisted story answered DIFFERENT_STORY; kept separate",
            )
    elif candidates:
        outcome.update(
            action="REVIEW",
            needs_review=True,
            reason="ambiguous shortlist but semantic relation is disabled; kept separate",
        )

    # ---- No match: a new story. `uncertain -> separate` is the correct default;
    # the story is flagged so a human can look at the suspicious ones.
    story = story_store.new_story(item, publication_key=key or "")
    story["needs_review"] = bool(candidates) or bool(outcome["needs_review"])
    store["stories"] = list(store["stories"]) + [story]
    outcome.update(
        story_id=story["story_id"],
        relation="ORIGIN",
        relation_source=story_store.SOURCE_FIRST_ITEM,
        needs_review=story["needs_review"],
        new_story=True,
    )
    if not outcome["action"]:
        outcome["action"] = "NEW_STORY"
        outcome["reason"] = outcome["reason"] or "no existing story matched"
    return outcome


def build_plan(*, inbox=None, stories=None, semantic=True, call_model=None, now=None):
    """Compute outcomes over every **unassigned** item without writing anything."""
    return _plan(
        inbox=inbox,
        stories=stories,
        semantic=semantic,
        call_model=call_model,
        now=now,
        only_unassigned=True,
    )


def rebuild(
    *,
    inbox=None,
    stories=None,
    semantic=True,
    preview=True,
    force=False,
    call_model=None,
    now=None,
    blocked_path=None,
):
    """Development/first-install rebuild of every story from raw items.

    **An automatic rebuild must never silently overwrite editor corrections.** If
    the current store carries SPLIT/MERGE overrides, a rebuild would lose them, so
    it refuses unless `force=True` is passed explicitly. The normal path stays the
    incremental `update()`.
    """
    current = story_store.read_store(stories)
    overrides = current.get("overrides") or []
    if overrides and not force:
        return {
            "refused": True,
            "preview": bool(preview),
            "reason": (
                f"{len(overrides)} editor correction(s) (split/merge) would be lost — "
                "no rebuild was performed; pass --force only if you accept that"
            ),
            "overrides": len(overrides),
        }
    plan = _plan(
        inbox=inbox,
        stories=stories,
        semantic=semantic,
        call_model=call_model,
        now=now,
        only_unassigned=False,
        fresh=True,
        blocked_path=blocked_path,
    )
    summary = _summarize(plan["outcomes"], dry_run=preview, semantic=semantic)
    summary["rebuilt_from_scratch"] = True
    summary["stories"] = len(plan["store"]["stories"])
    if not preview:
        story_store.write_store(plan["store"], stories)
        for story in plan["store"]["stories"]:
            _propagate(story, inbox=inbox)
    return summary


def blocked_publishers(blocked_path=None):
    """Publisher domains the editor has blocked (raw rows stay, grouping stops)."""
    return set(blocked_domains.effective_domains(blocked_path))


def is_blocked_publisher(item, blocked):
    """PART 17: a currently blocked publisher must not create/reinforce a story."""
    domain = str((item or {}).get("publisher_domain") or "")
    if not domain or not blocked:
        return False
    return any(domain == d or domain.endswith("." + d) for d in blocked)


def _plan(
    *,
    inbox,
    stories,
    semantic,
    call_model,
    now,
    only_unassigned=True,
    fresh=False,
    blocked_path=None,
):
    items = inbox_store.read_items(inbox)
    items_by_id = {item["item_id"]: item for item in items}
    if fresh:
        store = {"version": story_store.VERSION, "stories": [], "overrides": []}
    else:
        store = story_store.read_store(stories)
    blocked = blocked_publishers(blocked_path)
    assigned = story_store.assigned_item_ids(store)
    pending = [i for i in items if not only_unassigned or i["item_id"] not in assigned]
    pending.sort(key=lambda i: (i.get("discovered_at") or "", i["item_id"]))
    outcomes = []
    for item in pending:
        if is_blocked_publisher(item, blocked):
            # The raw row is preserved in the inbox for audit; it simply does not
            # participate in active story grouping (PART 17).
            outcomes.append(
                {
                    "item_id": item["item_id"],
                    "publication_key": "",
                    "action": "BLOCKED_PUBLISHER",
                    "relation": "",
                    "relation_source": "",
                    "story_id": "",
                    "needs_review": False,
                    "new_story": False,
                    "semantic_call": False,
                    "reason": f"издателят {item.get('publisher_domain')} е забранен",
                }
            )
            continue
        if story_store.is_editor_locked(store, item["item_id"]):
            outcomes.append(
                {
                    "item_id": item["item_id"],
                    "publication_key": "",
                    "action": "EDITOR_LOCKED",
                    "relation": "",
                    "relation_source": "",
                    "story_id": "",
                    "needs_review": True,
                    "semantic_call": False,
                    "reason": "editor split/merge decision covers this item",
                }
            )
            continue
        outcomes.append(
            process_item(
                item, store, items_by_id, semantic=semantic, call_model=call_model, now=now
            )
        )
    return {"store": store, "outcomes": outcomes, "items_by_id": items_by_id}


def _summarize(outcomes, *, dry_run, semantic):
    relations = {name: 0 for name in story_relation.RELATIONS}
    for row in outcomes:
        if row.get("relation"):
            relations[row["relation"]] = relations.get(row["relation"], 0) + 1
    return {
        "dry_run": bool(dry_run),
        "semantic_enabled": bool(semantic),
        "scanned": len(outcomes),
        "new_stories": sum(1 for r in outcomes if r.get("new_story")),
        "exact_duplicates": sum(1 for r in outcomes if r["action"] == "EXACT_DUPLICATE"),
        "deterministic_matches": sum(1 for r in outcomes if r["action"] == "DETERMINISTIC"),
        "semantic_matches": sum(1 for r in outcomes if r["action"] == "SEMANTIC"),
        "separate": sum(1 for r in outcomes if r["action"] in ("SEPARATE", "REVIEW")),
        "editor_locked": sum(1 for r in outcomes if r["action"] == "EDITOR_LOCKED"),
        "blocked_publisher": sum(1 for r in outcomes if r["action"] == "BLOCKED_PUBLISHER"),
        "needs_review": sum(1 for r in outcomes if r.get("needs_review")),
        "semantic_calls": sum(1 for r in outcomes if r.get("semantic_call")),
        # A shortlisted-but-separate item is exactly the "model did not help"
        # bucket; it is reported, never hidden.
        "semantic_failures": sum(
            1
            for r in outcomes
            if r["action"] == "REVIEW" and "shortlist score" in (r.get("reason") or "")
        ),
        "relations": relations,
        "outcomes": outcomes,
    }


def update(
    *,
    inbox=None,
    stories=None,
    dry_run=True,
    semantic=True,
    call_model=None,
    now=None,
    blocked_path=None,
):
    """One-shot incremental update: assign items not yet in a story.

    `dry_run=True` computes the plan and writes nothing. There is no daemon, no
    polling loop and no scheduling here — the caller owns those (cron/CLI/UI).
    """
    plan = _plan(
        inbox=inbox,
        stories=stories,
        semantic=semantic,
        call_model=call_model,
        now=now,
        blocked_path=blocked_path,
    )
    summary = _summarize(plan["outcomes"], dry_run=dry_run, semantic=semantic)
    summary["stories"] = len(plan["store"]["stories"])
    if not dry_run and plan["outcomes"]:
        story_store.write_store(plan["store"], stories)
        # A SAME_STORY arrival in an already-SEEN/IGNORED story must not look like
        # new work in the raw materials view (M4C §12). Idempotent by design.
        for story in plan["store"]["stories"]:
            _propagate(story, inbox=inbox)
    return summary


# ---------------------------------------------------------------- deterministic-only measurement


def analyze(*, inbox=None, stories=None, now=None):
    """PART 19 first measure: what deterministic-only story building achieves.

    Reports how many discovery rows collapse into the same publication and how
    many high-confidence `SAME_STORY` groups are formed **without any model call**,
    so the value of the semantic step can be judged against a real baseline.
    """
    items = inbox_store.read_items(inbox)
    keys = [publication_identity.publication_key(i) for i in items]
    exact_groups = {}
    for item, key in zip(items, keys, strict=True):
        if key:
            exact_groups.setdefault(key, []).append(item["item_id"])
    plan = build_plan(inbox=inbox, stories=stories, semantic=False, now=now)
    outcomes = plan["outcomes"]
    return {
        "source_items": len(items),
        "unique_publication_keys": len(exact_groups),
        "items_without_usable_url": sum(
            1 for item, key in zip(items, keys, strict=True) if not key
        ),
        "exact_duplicate_rows": sum(len(ids) - 1 for ids in exact_groups.values()),
        "deterministic_matches": sum(1 for r in outcomes if r["action"] == "DETERMINISTIC"),
        "remaining_ambiguous": sum(1 for r in outcomes if r["action"] == "REVIEW"),
        "new_stories": sum(1 for r in outcomes if r["action"] == "NEW_STORY"),
    }


# ---------------------------------------------------------------- views (Workbench / CLI)


def story_cards(*, inbox=None, stories=None, now=None, blocked_path=None):
    """Story-first view rows: real titles, honest counts, no internal ids shown.

    `discovery_count` / `publication_count` / `publisher_count` are reported
    separately (M4C §2.4): five discovery rows for two unique publications found
    through five monitors must never read as "5 sources".
    """
    items = inbox_store.read_items(inbox)
    items_by_id = {item["item_id"]: item for item in items}
    store = story_store.read_store(stories)
    blocked = blocked_publishers(blocked_path)
    cards = []
    for story in store["stories"]:
        metrics = story_store.metrics(story, items_by_id)
        representative = items_by_id.get(story["representative_item_id"]) or {}
        latest = _latest_item(story, items_by_id)
        publishers = sorted(
            {
                (items_by_id.get(m["item_id"]) or {}).get("publisher_domain") or ""
                for m in story["members"]
            }
            - {""}
        )
        cards.append(
            {
                "story_id": story["story_id"],
                "status": story["status"],
                "needs_review": story.get("needs_review", False),
                "title": representative.get("title") or latest.get("title") or "",
                "summary": (representative.get("summary") or latest.get("summary") or "")[:300],
                "publishers": publishers,
                "metrics": metrics,
                "first_seen_at": story["first_seen_at"],
                "last_seen_at": story["last_seen_at"],
                "first_public_at": story["first_public_at"],
                "latest_material_change_at": story["latest_material_change_at"],
                "new_development": _has_development(story),
                "blocked_publisher": any(
                    is_blocked_publisher(items_by_id.get(m["item_id"]) or {}, blocked)
                    for m in story["members"]
                ),
                "members": list(story["members"]),
            }
        )
    # Newest first, then unfinished work and flagged stories at the top.
    cards.sort(key=lambda c: c["last_seen_at"], reverse=True)
    cards.sort(key=lambda c: (0 if c["status"] == "NEW" else 1, 0 if c["needs_review"] else 1))
    return {"stories": cards, "overrides": store.get("overrides") or []}


def _has_development(story):
    return any(m["relation"] == "NEW_DEVELOPMENT" for m in story["members"])


def _latest_item(story, items_by_id):
    members = [m for m in story["members"] if m["item_id"] in items_by_id]
    if not members:
        return {}
    latest = max(members, key=lambda m: items_by_id[m["item_id"]].get("discovered_at") or "")
    return items_by_id[latest["item_id"]]


def story_detail(story_id, *, inbox=None, stories=None, blocked_path=None):
    """One story: chronology, unique publications grouped by publisher, metrics."""
    items = inbox_store.read_items(inbox)
    items_by_id = {item["item_id"]: item for item in items}
    store = story_store.read_store(stories)
    story = story_store.story_by_id(store, story_id)
    if story is None:
        return None
    order = sorted(
        story["members"],
        key=lambda m: (
            (items_by_id.get(m["item_id"]) or {}).get("discovered_at") or "",
            m["added_at"],
        ),
    )
    blocked = blocked_publishers(blocked_path)
    timeline = []
    publications = {}
    for member in order:
        item = items_by_id.get(member["item_id"]) or {}
        timeline.append(
            {
                "at": item.get("discovered_at") or member.get("added_at") or "",
                "relation": member["relation"],
                "title": item.get("title") or "",
                "item_id": member["item_id"],
                "publication_key": member["publication_key"],
                "publisher_domain": item.get("publisher_domain") or "",
                "blocked_publisher": is_blocked_publisher(item, blocked),
                "discoveries": [],
            }
        )
        key = member["publication_key"] or f"item:{member['item_id']}"
        publications.setdefault(
            key,
            {
                "publication_key": key,
                "title": item.get("title") or "",
                "publisher_domain": item.get("publisher_domain") or "",
                "published_at": item.get("published_at") or "",
                "blocked_publisher": is_blocked_publisher(item, blocked),
                "discoveries": [],
            },
        )["discoveries"].append(
            {
                "item_id": member["item_id"],
                "source_id": item.get("source_id") or "",
                "discovered_at": item.get("discovered_at") or "",
            }
        )
    return {
        "story_id": story_id,
        "status": story["status"],
        "needs_review": story.get("needs_review", False),
        "title": (items_by_id.get(story["representative_item_id"]) or {}).get("title") or "",
        "first_seen_at": story["first_seen_at"],
        "first_public_at": story["first_public_at"],
        "latest_material_change_at": story["latest_material_change_at"],
        "metrics": story_store.metrics(story, items_by_id),
        "timeline": timeline,
        "publications": list(publications.values()),
        "recent_stories": _recent_story_options(store, items_by_id, exclude=story_id),
    }


def _recent_story_options(store, items_by_id, *, exclude="", limit=20):
    options = []
    for story in store["stories"]:
        if story["story_id"] == exclude:
            continue
        item = items_by_id.get(story["representative_item_id"]) or {}
        options.append(
            {
                "story_id": story["story_id"],
                "title": item.get("title") or "(без заглавие)",
                "last_seen_at": story["last_seen_at"],
            }
        )
    options.sort(key=lambda o: o["last_seen_at"], reverse=True)
    return options[:limit]


# ---------------------------------------------------------------- editor actions


def set_story_status(story_id, status, *, inbox=None, stories=None, apply_to_items=True):
    """Set a story status and propagate it to the current member inbox rows."""
    store = story_store.read_store(stories)
    story = story_store.set_story_status(store, story_id, status)
    applied = _propagate(story, inbox=inbox) if apply_to_items else 0
    story_store.write_store(store, stories)
    return {"story_id": story_id, "status": story["status"], "items_updated": applied}


def _propagate(story, *, inbox=None):
    desired = story_store.desired_item_statuses(story)
    if not desired:
        return 0
    items = inbox_store.read_items(inbox)
    changed = 0
    for item in items:
        target = desired.get(item["item_id"])
        if target and item["status"] != target:
            item["status"] = target
            changed += 1
    if changed:
        inbox_store.save_items(items, inbox)
    return changed


def split_item(story_id, item_id, *, inbox=None, stories=None, note=""):
    """Editor correction: this material is not part of that story."""
    items = inbox_store.read_items(inbox)
    items_by_id = {item["item_id"]: item for item in items}
    store = story_store.read_store(stories)
    story = story_store.story_by_id(store, story_id)
    if story is None:
        raise story_store.StoryStoreError(f"unknown story_id: {story_id}")
    updated, fresh = story_store.split_member(
        story,
        item_id,
        items_by_id=items_by_id,
        note=note,
        reserved_ids={s["story_id"] for s in store["stories"]},
    )
    if updated is None:
        store["stories"] = [s for s in store["stories"] if s["story_id"] != story_id]
    store["stories"] = list(store["stories"]) + [fresh]
    story_store.record_split_override(
        store, item_id=item_id, from_story=story_id, to_story=fresh["story_id"], note=note
    )
    story_store.write_store(store, stories)
    return {"from_story": story_id, "to_story": fresh["story_id"], "item_id": item_id}


def merge_stories(target_id, source_id, *, inbox=None, stories=None, note=""):
    """Editor correction: merge a false split back into one story."""
    items = inbox_store.read_items(inbox)
    items_by_id = {item["item_id"]: item for item in items}
    store = story_store.read_store(stories)
    target = story_store.merge_stories(
        store, target_id, source_id, items_by_id=items_by_id, note=note
    )
    story_store.write_store(store, stories)
    return {
        "story_id": target["story_id"],
        "merged_from": source_id,
        "members": len(target["members"]),
    }


# ---------------------------------------------------------------- reporting


def render_summary(summary):
    lines = [
        ("ПРОБЕН ПРЕГЛЕД (без запис)" if summary["dry_run"] else "ИСТОРИИ: обновяване")
        + f": прегледани {summary['scanned']} нови материала",
        (
            f"  нови истории: {summary['new_stories']} · "
            f"нови развития: {summary['relations'].get('NEW_DEVELOPMENT', 0)} · "
            f"точни дубликати: {summary['exact_duplicates']}"
        ),
        (
            "  добавени към съществуващи: "
            f"{summary['deterministic_matches'] + summary['semantic_matches']} "
            f"(детерминистично {summary['deterministic_matches']} · "
            f"семантично {summary['semantic_matches']})"
        ),
        (
            f"  за преглед: {summary['needs_review']} · отделени: {summary['separate']} · "
            f"заключени от редактор: {summary['editor_locked']} · "
            f"забранени издатели: {summary['blocked_publisher']}"
        ),
        (
            f"  семантични заявки: {summary['semantic_calls']} · "
            f"неуспешни/невалидни: {summary['semantic_failures']}"
        ),
    ]
    relations = summary["relations"]
    lines.append("  връзки: " + " · ".join(f"{k}={v}" for k, v in relations.items() if v))
    if summary["dry_run"]:
        lines.append("Нищо не е записано (--dry-run).")
    return "\n".join(lines)
