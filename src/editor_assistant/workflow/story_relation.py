"""M4C: semantic story relation — one narrow capability, not a clustering engine.

The deterministic pass decides the obvious cases (exact publication identity, then
a conservative title/time/token test). Only the *ambiguous shortlist* reaches a
model, and the model answers exactly one question:

```text
new publication  vs  existing story  ->  relation
```

Output contract (strict JSON, validated before it can influence anything):

```json
{
  "same_event": true,
  "relation": "SAME_STORY | NEW_DEVELOPMENT | RELATED_BACKGROUND | DIFFERENT_STORY",
  "material_change": true,
  "shared_anchors": ["..."],
  "reason": "short explanation"
}
```

Rules
-----
* the model is a **narrow fallback**: no all-pairs clustering, no embeddings, no
  editorial scoring, no free-text trust;
* it may never draft, publish, or change publisher authority — it returns a
  relation string and nothing else;
* **failure never merges**: an unavailable provider, a rate-limited call, a
  timeout or malformed output returns `None`, and the caller keeps the item as a
  separate story with `needs_review = true`;
* the model pool is its own role (`role="story"`), never the weak `judge` pool —
  this is semantic event comparison, not mechanical entailment (M3D lesson).

The prompt carries a compact surface only (M4C §9): the story's representative
title, its origin title, up to two latest development titles, short summaries,
publisher domains and times — never whole article bodies and never a long history.
"""

from __future__ import annotations

RELATIONS = ("SAME_STORY", "NEW_DEVELOPMENT", "RELATED_BACKGROUND", "DIFFERENT_STORY")

#: Relations that keep the item inside the story.
SAME_STORY_GROUP = ("SAME_STORY", "NEW_DEVELOPMENT", "RELATED_BACKGROUND")

MAX_CONTEXT_PUBLICATIONS = 3
MAX_SUMMARY_CHARS = 240
MAX_REASON_CHARS = 300
MAX_ANCHORS = 8


class RelationError(ValueError):
    """Malformed model output (never stored, never acted on)."""


def _cut(text, limit):
    return str(text or "").strip()[:limit]


def build_context(item, story, items_by_id):
    """The compact comparison surface — at most 3 unique publications."""
    members = list(story.get("members") or [])
    ordered = sorted(members, key=lambda m: str(m.get("added_at") or ""))
    picks = []
    seen = set()
    for member in ordered:
        if member["item_id"] == item["item_id"]:
            continue
        key = member.get("publication_key") or member["item_id"]
        if key in seen:
            continue
        seen.add(key)
        picks.append(member)
        if len(picks) >= MAX_CONTEXT_PUBLICATIONS:
            break

    publications = []
    for member in picks:
        row = items_by_id.get(member["item_id"]) or {}
        publications.append(
            {
                "title": _cut(row.get("title"), 200),
                "summary": _cut(row.get("summary"), MAX_SUMMARY_CHARS),
                "publisher_domain": _cut(row.get("publisher_domain"), 120),
                "published_at": _cut(row.get("published_at"), 40),
                "discovered_at": _cut(row.get("discovered_at"), 40),
                "relation": member.get("relation") or "",
            }
        )
    development_titles = [
        _cut((items_by_id.get(m["item_id"]) or {}).get("title"), 200)
        for m in ordered
        if m.get("relation") == "NEW_DEVELOPMENT"
    ][-2:]
    origin = next((m for m in ordered if m.get("relation") == "ORIGIN"), None)
    return {
        "candidate_title": _cut(item.get("title"), 200),
        "candidate_summary": _cut(item.get("summary"), MAX_SUMMARY_CHARS),
        "candidate_publisher": _cut(item.get("publisher_domain"), 120),
        "candidate_published_at": _cut(item.get("published_at"), 40),
        "representative_title": _cut(
            (items_by_id.get(story.get("representative_item_id")) or {}).get("title"), 200
        ),
        "origin_title": _cut(
            (items_by_id.get(origin["item_id"]) or {}).get("title") if origin else "", 200
        ),
        "development_titles": development_titles,
        "publications": publications,
    }


PROMPT_TEMPLATE = """Ти сравняваш ЕДНА нова публикация с ЕДНА съществуваща история.

Отговори само с JSON обект, без обяснения извън него:
{{"same_event": true|false, "relation": "SAME_STORY|NEW_DEVELOPMENT|RELATED_BACKGROUND|DIFFERENT_STORY", "material_change": true|false, "shared_anchors": ["..."], "reason": "кратко обяснение"}}

Определения:
- SAME_STORY: същото събитие/история без съществено ново развитие (друга медия отразява същото решение; преписана агенционна новина).
- NEW_DEVELOPMENT: същата история, но нещо съществено се промени (предложение -> решение на комисия; разследване -> обвинение; обявено събитие -> отмяна/нова дата; ново официално число).
- RELATED_BACKGROUND: свързан контекст, история, обяснение или съседен материал, но не същото текущо събитие.
- DIFFERENT_STORY: различна история, дори при съвпадащи лица или населено място.

Бъди консервативен: съмнително => DIFFERENT_STORY. Не обединявай по догадки.
Не оценявай качество, важност или политическа стойност. Не добавяй други полета.

НОВА ПУБЛИКАЦИЯ
  заглавие: {candidate_title}
  издател: {candidate_publisher}
  публикувано: {candidate_published_at}
  резюме: {candidate_summary}

СЪЩЕСТВУВАЩА ИСТОРИЯ
  представително заглавие: {representative_title}
  първоначално заглавие: {origin_title}
  последни развития: {development_titles}
  публикации:
{publications}
"""


def render_prompt(context):
    publications = "\n".join(
        f"    - {p['title']} ({p['publisher_domain']} · {p['published_at'] or p['discovered_at']})"
        f" — {p['relation']}" + (f"\n      {p['summary']}" if p["summary"] else "")
        for p in context["publications"]
    )
    if not publications:
        publications = "    - (няма)"
    return PROMPT_TEMPLATE.format(
        candidate_title=context["candidate_title"],
        candidate_publisher=context["candidate_publisher"] or "неизвестен",
        candidate_published_at=context["candidate_published_at"] or "неизвестно",
        candidate_summary=context["candidate_summary"],
        representative_title=context["representative_title"],
        origin_title=context["origin_title"],
        development_titles=", ".join(context["development_titles"]) or "(няма)",
        publications=publications,
    )


def parse_relation(payload):
    """Strict validation of the model's JSON. Raises `RelationError`."""
    if not isinstance(payload, dict):
        raise RelationError("relation output must be a JSON object")
    allowed = {"same_event", "relation", "material_change", "shared_anchors", "reason"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise RelationError(f"unknown relation fields {unknown}")
    relation = payload.get("relation")
    if relation not in RELATIONS:
        raise RelationError(f"relation must be one of {RELATIONS}, got {relation!r}")
    same_event = payload.get("same_event")
    if not isinstance(same_event, bool):
        raise RelationError("same_event must be true or false")
    material_change = payload.get("material_change")
    if not isinstance(material_change, bool):
        raise RelationError("material_change must be true or false")
    anchors = payload.get("shared_anchors", [])
    if not isinstance(anchors, list) or any(not isinstance(a, str) for a in anchors):
        raise RelationError("shared_anchors must be a list of strings")
    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        raise RelationError("reason must be a string")
    if relation == "DIFFERENT_STORY" and same_event:
        raise RelationError("DIFFERENT_STORY with same_event=true is contradictory")
    if relation in SAME_STORY_GROUP and not same_event:
        raise RelationError(f"{relation} with same_event=false is contradictory")
    if relation == "NEW_DEVELOPMENT" and not material_change:
        raise RelationError("NEW_DEVELOPMENT requires material_change=true")
    return {
        "same_event": same_event,
        "relation": relation,
        "material_change": material_change,
        "shared_anchors": [a.strip()[:80] for a in anchors][:MAX_ANCHORS],
        "reason": _cut(reason, MAX_REASON_CHARS),
    }


def classify(item, story, items_by_id, *, call_model=None):
    """Ask the semantic model for the relation, or return `None`.

    `None` means **no merge** (provider unavailable, rate-limited, malformed
    output) — the caller creates a separate story flagged for review. An
    infrastructure failure must never force a merge.
    """
    if call_model is None:
        try:
            from editor_assistant.drafting import generate

            call_model = generate.call_model
        except Exception:  # noqa: BLE001 - no provider import must stay a no-merge
            return None
    prompt = render_prompt(build_context(item, story, items_by_id))
    try:
        raw, _meta = call_model(prompt, role="story")
    except Exception:  # noqa: BLE001 - any transport/provider failure is a no-merge
        return None
    try:
        from editor_assistant.drafting.generate import _extract_first_object

        payload = _extract_first_object(raw)
    except Exception:  # noqa: BLE001 - unparseable output is a no-merge
        return None
    try:
        return parse_relation(payload)
    except RelationError:
        return None
