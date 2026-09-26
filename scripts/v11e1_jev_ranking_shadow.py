#!/usr/bin/env python3
"""V1.1-E1 — Editorial classification + JEV ranking shadow benchmark (EVALUATION).

This is a **shadow experiment**, not a feature. It answers one question:

    Which of the current real Stories would an editor want to see first, and
    does adding TypeSafe JEV signals on top of signals the newsroom already owns
    actually improve that judgement?

Hard boundaries enforced by this script
--------------------------------------
* **read-only** — it opens `var/newsroom/*` and `var/editorial_workflow/*` for
  reading only, and never imports a write path;
* **no production ranking** — Today stays chronological; this script produces a
  report, not an ordering the product consumes;
* **no authority** — JEV output here is attention/classification intelligence
  only. It can never set `factual_authority`, promote a source to evidence,
  mark a claim true, bypass research, or create a Story/Article;
* **no schema change** — nothing is written into `story_store`, and no
  locality/category/score field is added anywhere;
* **secret hygiene** — the API key is read from the environment, never printed,
  never logged and never persisted.

Usage:
  PYTHONPATH=src python3 scripts/v11e1_jev_ranking_shadow.py --limit 80
  PYTHONPATH=src python3 scripts/v11e1_jev_ranking_shadow.py --dry-run
  PYTHONPATH=src python3 scripts/v11e1_jev_ranking_shadow.py --repeat-subset 12
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from editor_assistant.workflow import editor_projections, inbox_store, story_store

STORIES_PATH = ROOT / "var" / "newsroom" / "stories.json"
INBOX_PATH = ROOT / "var" / "newsroom" / "inbox.jsonl"
METADATA_PATH = ROOT / "var" / "newsroom" / "story_editor_metadata.json"
SOURCES_PATH = ROOT / "var" / "newsroom" / "sources.json"
ARTICLES_PATH = ROOT / "var" / "editorial_workflow" / "editor_articles.jsonl"

#: Stores whose bytes must be identical before and after the run.
GUARDED_STORES = (
    ROOT / "var" / "newsroom",
    ROOT / "var" / "editorial_workflow",
)

#: Deterministic sampling seed. Frozen so the evaluation set is reproducible.
SAMPLING_SEED = 20260926

#: Target evaluation set size (the brief asks for roughly 60-100 Stories).
TARGET_SAMPLE = 80


# ------------------------------------------------------------------ JEV config
#
# `TYPESAFE_API_KEY` is read from the environment exactly as the rest of the
# project already does (`workflow/jev.py`). It is never copied into source,
# never renamed, never logged and never exposed to the frontend.

TYPESAFE_API_KEY_ENV = "TYPESAFE_API_KEY"
JEV_MODEL_ENV = "JEV_MODEL"
DEFAULT_MODEL_ALIAS = "jev-latest"

#: Locality taxonomy, frozen from a census of the real inbox: every value below
#: is observed in the corpus, so no option is dead weight.
LOCALITY_CHOICES = (
    "BURGAS",
    "POMORIE",
    "NESSEBAR",
    "SOZOPOL",
    "TSAREVO",
    "PRIMORSKO",
    "KARNOBAT",
    "AYTOS",
    "OTHER_BURGAS_REGION",
    "BULGARIA_NATIONAL",
    "INTERNATIONAL",
    "UNCLEAR",
)

#: Editorial category taxonomy. Derived from the real sample plus the site's own
#: archive categories (Общество / Култура / Туризъм / Бизнес / Спорт /
#: Образование in `m2/review/style_profiles.json`). Closed, no free text.
CATEGORY_CHOICES = (
    "LOCAL_GOVERNMENT",
    "INFRASTRUCTURE_TRANSPORT",
    "PUBLIC_SERVICES_OUTAGES",
    "WEATHER_SAFETY",
    "CRIME_INCIDENTS",
    "HEALTHCARE",
    "EDUCATION",
    "TOURISM",
    "CULTURE_EVENTS",
    "SPORT",
    "BUSINESS_ECONOMY",
    "NATIONAL_POLITICS",
    "OTHER",
)

SCORE_LEVELS = ("LOW", "MEDIUM", "HIGH")


# ------------------------------------------------------------------- integrity


def _hash_tree(root: Path) -> dict[str, str]:
    """SHA-256 of every regular file under `root`, keyed by relative path."""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        out[str(path.relative_to(root))] = digest.hexdigest()
    return out


def hash_guarded_stores() -> dict[str, dict[str, str]]:
    return {str(root.relative_to(ROOT)): _hash_tree(root) for root in GUARDED_STORES}


def compare_stores(before, after) -> list[str]:
    """Every byte-level difference between two manifests; empty means clean."""
    problems = []
    for store in sorted(set(before) | set(after)):
        b = before.get(store, {})
        a = after.get(store, {})
        for rel in sorted(set(b) | set(a)):
            if b.get(rel) != a.get(rel):
                problems.append(f"{store}/{rel}")
    return problems


# ---------------------------------------------------------------------- input


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus():
    """Read every real store. Nothing is written, no write path is imported."""
    stories = story_store.read_store(STORIES_PATH)["stories"]
    items = inbox_store.read_items(INBOX_PATH)
    items_by_id = {row["item_id"]: row for row in items}
    metadata = {row["story_id"]: row for row in _read_json(METADATA_PATH)["stories"]}
    sources_by_id = {row["source_id"]: row for row in _read_json(SOURCES_PATH)}
    article_lines = ARTICLES_PATH.read_text(encoding="utf-8").splitlines()
    articles = [json.loads(line) for line in article_lines if line.strip()]
    return {
        "stories": stories,
        "items": items,
        "items_by_id": items_by_id,
        "metadata": metadata,
        "sources_by_id": sources_by_id,
        "articles": articles,
    }


def _default_metadata(story_id: str) -> dict:
    return {
        "story_id": story_id,
        "followed": False,
        "last_reviewed_at": None,
        "reviewed_development_ids": [],
    }


def parse_ts(value: str):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ------------------------------------------------- deterministic Story features


def build_deterministic_features(corpus, now):
    """Every signal the newsroom already owns. No model is consulted here."""
    items_by_id = corpus["items_by_id"]
    sources_by_id = corpus["sources_by_id"]
    metadata = corpus["metadata"]
    article_story_ids = {a["story_id"] for a in corpus["articles"]}

    rows = []
    for story in corpus["stories"]:
        story_id = story["story_id"]
        meta = metadata.get(story_id) or _default_metadata(story_id)
        members = story.get("members") or []
        member_items = [items_by_id.get(m["item_id"]) or {} for m in members]

        representative = items_by_id.get(story.get("representative_item_id")) or {}
        if not representative and member_items:
            representative = member_items[0]

        publishers = sorted(
            {
                (i.get("publisher_domain") or "").lower()
                for i in member_items
                if i.get("publisher_domain")
            }
        )
        publisher_kinds = sorted(
            {
                (i.get("publisher_kind") or "").lower()
                for i in member_items
                if i.get("publisher_kind")
            }
        )
        source_kinds = sorted(
            {(i.get("source_kind") or "").lower() for i in member_items if i.get("source_kind")}
        )
        source_names = []
        for item in member_items:
            entry = sources_by_id.get(item.get("source_id") or "")
            if entry and entry.get("name"):
                source_names.append(entry["name"])

        # Source priority: the strongest priority among the Story's members.
        rank = {"high": 2, "normal": 1, "low": 0}
        priorities = [i.get("priority") or "normal" for i in member_items] or ["normal"]
        best_priority = max(priorities, key=lambda p: rank.get(p, 1))

        chronology_at = editor_projections.story_chronology_at(story)
        moment = parse_ts(chronology_at) or parse_ts(story.get("last_seen_at"))
        age_hours = None
        if moment is not None:
            age_hours = round((now - moment).total_seconds() / 3600.0, 3)

        developments = editor_projections.meaningful_developments(story, items_by_id)

        rows.append(
            {
                "story_id": story_id,
                "status": story.get("status"),
                "needs_review": bool(story.get("needs_review")),
                "title": str(representative.get("title") or ""),
                "summary": str(representative.get("summary") or ""),
                "published_at": str(representative.get("published_at") or ""),
                "publisher_domain": str(representative.get("publisher_domain") or ""),
                "publisher_kind": str(representative.get("publisher_kind") or "").lower(),
                "source_id": str(representative.get("source_id") or ""),
                "source_name": source_names[0] if source_names else "",
                "source_kind": str(representative.get("source_kind") or "").lower(),
                "priority": best_priority,
                "latestChangeAt": chronology_at,
                "age_hours": age_hours,
                "publisher_count": len(publishers),
                "publishers": publishers,
                "publisher_kinds": publisher_kinds,
                "source_kinds": source_kinds,
                "member_count": len(members),
                "meaningful_development_count": len(developments),
                "followed": bool(meta.get("followed")),
                "last_reviewed_at": meta.get("last_reviewed_at"),
                "has_active_article": story_id in article_story_ids,
                "fact_authority_item_count": sum(
                    1 for i in member_items if i.get("factual_authority")
                ),
            }
        )
    return rows


# ------------------------------------------------------ deterministic sampling


def stratum_key(row) -> tuple:
    """Coverage strata, all derived from real stored signals (never from JEV).

    `publisher_count` and `followed` are in the key even though the real corpus
    makes them rare (only 15 of 253 Stories have 2+ publishers, exactly 1 is
    followed, and no Story has a meaningful development yet). Without them those
    signals would never be exercised, and the evaluation would silently cover
    only the easy single-publisher case.
    """
    kind = row["source_kind"] or "unknown"
    members = "multi" if row["member_count"] > 1 else "single"
    authority = "authority" if row["fact_authority_item_count"] else "no_authority"
    corroboration = "corroborated" if row["publisher_count"] > 1 else "single_publisher"
    followed = "followed" if row["followed"] else "unfollowed"
    return (kind, members, row["priority"], authority, corroboration, followed)


def sample_stories(rows, *, target=TARGET_SAMPLE, seed=SAMPLING_SEED):
    """Deterministic, reproducible sample covering every real stratum.

    Stories are bucketed by `stratum_key`, each bucket is shuffled with a seeded
    RNG, and buckets are then drawn round-robin. A rare stratum (a single-member
    low-priority Story from an aggregator) is therefore represented even though
    it is a small share of the corpus, without any human selection: the same
    corpus always yields the same set, and no Story is ever picked because it
    looked interesting.
    """
    eligible = [r for r in rows if r["title"]]
    buckets: dict[tuple, list] = {}
    for row in sorted(eligible, key=lambda r: r["story_id"]):
        buckets.setdefault(stratum_key(row), []).append(row)

    rng = random.Random(seed)
    for key in sorted(buckets):
        rng.shuffle(buckets[key])

    order = sorted(buckets)
    picked: list[dict] = []
    position = 0
    while len(picked) < target and any(buckets[k] for k in order):
        key = order[position % len(order)]
        if buckets[key]:
            picked.append(buckets[key].pop())
        position += 1
    return sorted(
        picked,
        key=lambda r: (-(r["age_hours"] if r["age_hours"] is not None else 1e9), r["story_id"]),
    )


# ------------------------------------------------------------------ JEV client


class JevUnavailable(RuntimeError):
    """SDK or key missing. A future production ranking must degrade, not fail."""


def build_client(timeout=60.0):
    """Construct the live TypeSafe client, or raise `JevUnavailable`.

    The key is taken from the environment and is never echoed, logged, stored or
    included in any result record.
    """
    try:
        import typesafe_sdk as sdk
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise JevUnavailable("typesafe_sdk is not installed") from exc

    key = (os.environ.get(TYPESAFE_API_KEY_ENV) or "").strip()
    if not key:
        raise JevUnavailable(f"{TYPESAFE_API_KEY_ENV} is not set")
    return sdk.TypeSafeClient(api_key=key, timeout=timeout), sdk


def model_alias() -> str:
    return (os.environ.get(JEV_MODEL_ENV) or "").strip() or DEFAULT_MODEL_ALIAS


def build_state(row, now) -> dict:
    """The minimum Story triage context. No ids, no editor data, no drafts.

    Sent to TypeSafe: title, a de-duplicated summary excerpt, the publisher
    domain, the source kind, the publication timestamp and the evaluation
    reference time. Story ids, item ids, URLs, editor metadata, Article content
    and any existing model output are all excluded.
    """
    title = " ".join((row["title"] or "").split())[:400]
    summary = " ".join((row["summary"] or "").split())[:600]
    # A summary that merely repeats the headline adds tokens and no signal.
    if summary and summary[:120].lower() == title[:120].lower():
        summary = ""
    return {
        "title": title,
        "summary": summary,
        "publisher_domain": row["publisher_domain"],
        "source_kind": row["source_kind"] or "unknown",
        "published_at": row["published_at"],
        "reference_time": now.isoformat(),
    }


def build_questions(sdk):
    """The six E1 questions, built ONCE and asked in a SINGLE request.

    `system_one(state=..., questions={...})` accepts a mapping of typed
    questions, so one Story costs one round trip and yields six typed outputs.
    This is the documented batching the brief asks for, not six calls.
    """
    return {
        # Task 1 — constrained locality. No free-form strings are permitted.
        "locality": sdk.Choice(
            instructions=(
                "Which single locality is this news item primarily about? "
                "Choose exactly one option. Use UNCLEAR only if the item names no "
                "place at all. If the item is about Bulgaria as a whole rather "
                "than one municipality, choose BULGARIA_NATIONAL."
            ),
            criteria={option: None for option in LOCALITY_CHOICES},
        ),
        # Task 2 — closed editorial category.
        "category": sdk.Choice(
            instructions=(
                "Which single editorial category best describes this news item "
                "for a regional newsroom? Choose exactly one option."
            ),
            criteria={option: None for option in CATEGORY_CHOICES},
        ),
        # Task 3 — local relevance (NOT importance).
        "local_relevance": sdk.Score(
            instructions=(
                "How relevant is this development to readers in Burgas city and "
                "the surrounding Burgas region? Judge only the geography of the "
                "impact, not how important the topic is."
            ),
            criteria=list(SCORE_LEVELS),
        ),
        # Task 4 — public interest (NOT clickbait).
        "public_interest": sdk.Score(
            instructions=(
                "How likely is this development to be genuinely useful or "
                "interesting to a general regional-news audience? Judge real "
                "reader value and civic relevance, not sensationalism, drama or "
                "headline punchiness."
            ),
            criteria=list(SCORE_LEVELS),
        ),
        # Task 5 — urgency.
        "urgency": sdk.Score(
            instructions=(
                "How time-sensitive is editorial attention to this development? "
                "High means readers are affected now or today (dangerous weather, "
                "an active outage, a live traffic disruption, an event happening "
                "today). Medium means it matters within days. Low means a "
                "scheduled announcement for a later date or evergreen background."
            ),
            criteria=list(SCORE_LEVELS),
        ),
        # Task 6 — novelty / editorial interest. Triage, not verification.
        "novelty": sdk.Noul(
            instructions=(
                "Does this item appear to contain a meaningful new development "
                "worth editorial attention, rather than routine, repetitive or "
                "evergreen material? Answer on newness of the development only, "
                "not on whether the facts are true."
            )
        ),
    }


def _plain(value):
    """SDK msgspec structs -> plain JSON-serializable data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    fields = getattr(type(value), "__struct_fields__", None)
    if fields:
        return {name: _plain(getattr(value, name)) for name in fields}
    return str(value)


def _choice(response, name):
    answer = (getattr(response, "choices", {}) or {}).get(name)
    if answer is None:
        return {"answer": None, "confidence": None, "probabilities": {}}
    return {
        "answer": _plain(getattr(answer, "choice", None)),
        "confidence": _plain(getattr(answer, "confidence", None)),
        "probabilities": _plain(getattr(answer, "probabilities", {}) or {}),
    }


def _score(response, name):
    answer = (getattr(response, "scores", {}) or {}).get(name)
    if answer is None:
        return {"answer": None, "score": None, "confidence": None, "probabilities": {}}
    legend = _plain(getattr(answer, "legend", {}) or {})
    raw = _plain(getattr(answer, "score", None))
    # A Score returns a continuous value plus a legend index->label map. Both are
    # preserved: the continuous value feeds the ranking, the label is what a
    # human reads.
    return {
        "answer": legend.get(int(raw)) if raw is not None and legend else None,
        "score": raw,
        "confidence": _plain(getattr(answer, "confidence", None)),
        "probabilities": _plain(getattr(answer, "probabilities", {}) or {}),
    }


def _noul(response, name):
    answer = (getattr(response, "nouls", {}) or {}).get(name)
    if answer is None:
        return {"answer": None, "score": None, "probabilities": {}}
    value = _plain(getattr(answer, "noul", None))
    return {
        "answer": "YES" if (value is not None and value >= 0.5) else "NO",
        "score": value,
        "probabilities": {
            "YES": value,
            "NO": None if value is None else round(1.0 - value, 4),
        },
    }


def normalize(response) -> dict:
    """Six typed outputs + usage, with no editorial interpretation attached."""
    usage = getattr(response, "usage", None)
    return {
        "status": "JEV_OK",
        "model_effective": _plain(getattr(response, "model", None)),
        "usage": {
            "input_tokens": _plain(getattr(usage, "input_tokens", None)),
            "output_tokens": _plain(getattr(usage, "output_tokens", None)),
        },
        "locality": _choice(response, "locality"),
        "category": _choice(response, "category"),
        "local_relevance": _score(response, "local_relevance"),
        "public_interest": _score(response, "public_interest"),
        "urgency": _score(response, "urgency"),
        "novelty": _noul(response, "novelty"),
    }


# ------------------------------------------------------------------ evaluation


def evaluate_sample(sample, now, *, client, sdk, model, dry_run=False, verbose=True):
    """One compact decision request per Story, six typed outputs each.

    Latency and token usage are measured per call. A single failing Story is
    recorded as a failure and the run continues: a production ranking must be
    able to drop one Story, not lose the whole screen.
    """
    questions = build_questions(sdk) if sdk is not None else None
    results = []
    for index, row in enumerate(sample, start=1):
        state = build_state(row, now)
        if dry_run:
            results.append({"story_id": row["story_id"], "jev": {"status": "DRY_RUN"}})
            continue
        started = time.monotonic()
        try:
            response = client.system_one(state=state, questions=questions, model=model)
            jev = normalize(response)
            jev["latency_ms"] = round((time.monotonic() - started) * 1000.0, 1)
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            jev = {
                "status": "JEV_PROVIDER_ERROR",
                "error": type(exc).__name__,
                "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
                "usage": {"input_tokens": None, "output_tokens": None},
            }
        results.append({"story_id": row["story_id"], "jev": jev})
        if verbose:
            loc = (jev.get("locality") or {}).get("answer")
            cat = (jev.get("category") or {}).get("answer")
            print(
                f"  [{index:>3}/{len(sample)}] {row['story_id']} "
                f"{jev.get('status'):<18} loc={loc} cat={cat} {jev.get('latency_ms')}ms",
                flush=True,
            )
    return results


def call_statistics(results) -> dict:
    """Measured call/latency/token totals. Monetary cost is never asserted."""
    ok = [r["jev"] for r in results if r["jev"].get("status") == "JEV_OK"]
    latencies = sorted(j["latency_ms"] for j in ok if j.get("latency_ms") is not None)
    in_tokens = [
        j["usage"]["input_tokens"] for j in ok if j["usage"].get("input_tokens") is not None
    ]
    out_tokens = [
        j["usage"]["output_tokens"] for j in ok if j["usage"].get("output_tokens") is not None
    ]

    def pct(values, q):
        if not values:
            return None
        index = min(len(values) - 1, max(0, round((len(values) - 1) * q)))
        return round(values[index], 1)

    return {
        "stories_sampled": len(results),
        "calls_made": len(ok),
        "calls_failed": len(results) - len(ok),
        "latency_mean_ms": round(statistics.fmean(latencies), 1) if latencies else None,
        "latency_p50_ms": pct(latencies, 0.50),
        "latency_p95_ms": pct(latencies, 0.95),
        "input_tokens_mean": round(statistics.fmean(in_tokens), 1) if in_tokens else None,
        "input_tokens_total": sum(in_tokens) if in_tokens else None,
        "output_tokens_mean": round(statistics.fmean(out_tokens), 1) if out_tokens else None,
        "output_tokens_total": sum(out_tokens) if out_tokens else None,
        "wall_clock_seconds": round(sum(latencies) / 1000.0, 2) if latencies else None,
        "models_seen": sorted({j.get("model_effective") for j in ok if j.get("model_effective")}),
        "note": (
            "tokens are measured; the API exposes no price field on Usage or "
            "ModelMetadata, so monetary cost is NOT asserted here"
        ),
    }


def consistency_check(sample, now, *, client, sdk, model, repeats, verbose=True):
    """Re-ask identical input three times to measure output stability.

    This decides whether JEV could ever be *persisted* as a classification or
    is only usable as an ephemeral ranking signal.
    """
    subset = sample[:repeats] if repeats else []
    findings = []
    for row in subset:
        state = build_state(row, now)
        runs = []
        for _ in range(3):
            try:
                response = client.system_one(
                    state=state, questions=build_questions(sdk), model=model
                )
                runs.append(normalize(response))
            except Exception as exc:  # noqa: BLE001
                runs.append({"status": "JEV_PROVIDER_ERROR", "error": type(exc).__name__})
        localities = [r.get("locality", {}).get("answer") for r in runs]
        categories = [r.get("category", {}).get("answer") for r in runs]
        urgencies = [r.get("urgency", {}).get("score") for r in runs]
        novelties = [r.get("novelty", {}).get("score") for r in runs]
        urgen = [u for u in urgencies if isinstance(u, (int, float))]
        nov = [n for n in novelties if isinstance(n, (int, float))]
        finding = {
            "story_id": row["story_id"],
            "title": row["title"][:90],
            "locality_runs": localities,
            "category_runs": categories,
            "urgency_runs": urgencies,
            "novelty_runs": novelties,
            "locality_stable": len(set(localities)) == 1,
            "category_stable": len(set(categories)) == 1,
            "urgency_spread": round(max(urgen) - min(urgen), 3) if urgen else None,
            "novelty_spread": round(max(nov) - min(nov), 3) if nov else None,
        }
        findings.append(finding)
        if verbose:
            print(
                f"  [repeat] {row['story_id']} loc={localities} cat={categories} "
                f"urg_spread={finding['urgency_spread']} nov_spread={finding['novelty_spread']}",
                flush=True,
            )
    return findings


# ------------------------------------------------------- transparent ranking
#
# The model is NEVER asked for a single ranking score. Each dimension is
# normalized to [0, 1] here, in plain Python, with explicit published weights.

#: Candidate C weights. Explicit, reported, and deliberately NOT persisted.
#: Recency stays dominant so the hybrid can never bury genuinely new material,
#: and the fuzzy JEV dimensions add up to 50% in total.
HYBRID_WEIGHTS = {
    "recency": 0.30,
    "local_relevance": 0.15,
    "public_interest": 0.12,
    "urgency": 0.13,
    "novelty": 0.10,
    "publisher_corroboration": 0.10,
    "source_priority": 0.05,
    "followed": 0.05,
}

#: Baseline B weights: only signals the newsroom already owns.
DETERMINISTIC_WEIGHTS = {
    "recency": 0.50,
    "publisher_corroboration": 0.20,
    "source_priority": 0.15,
    "followed": 0.05,
    "meaningful_developments": 0.10,
}

#: Half-life in hours for the recency term. One half-life = one day.
RECENCY_HALF_LIFE_HOURS = 24.0


def recency_score(age_hours) -> float:
    """Exponential decay: 1.0 at age 0, 0.5 at 24 h, ~0.01 at ~6.6 days."""
    if age_hours is None:
        return 0.0
    return round(2.0 ** (-max(0.0, age_hours) / RECENCY_HALF_LIFE_HOURS), 4)


def corroboration_score(publisher_count: int) -> float:
    """Independent publishers, saturating at 3. Never 'more is always better'."""
    return round(min(publisher_count, 3) / 3.0, 4)


def priority_score(priority: str) -> float:
    return {"high": 1.0, "normal": 0.5, "low": 0.2}.get(priority, 0.5)


def _jev_unit(value) -> float | None:
    """Normalize a JEV dimension to [0, 1]; None means 'no usable signal'."""
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return None


def _jev_score_unit(record) -> float | None:
    """A LOW/MEDIUM/HIGH Score maps to 0.0/0.5/1.0."""
    return {"LOW": 0.0, "MEDIUM": 0.5, "HIGH": 1.0}.get(record.get("answer"))


def hybrid_components(row, jev) -> dict:
    """Every normalized component, kept separate so a human can audit a score."""
    return {
        "recency": recency_score(row["age_hours"]),
        "local_relevance": _jev_score_unit(jev.get("local_relevance") or {}),
        "public_interest": _jev_score_unit(jev.get("public_interest") or {}),
        "urgency": _jev_score_unit(jev.get("urgency") or {}),
        "novelty": _jev_unit((jev.get("novelty") or {}).get("score")),
        "publisher_corroboration": corroboration_score(row["publisher_count"]),
        "source_priority": priority_score(row["priority"]),
        "followed": 1.0 if row["followed"] else 0.0,
    }


def hybrid_score(row, jev) -> tuple[float, dict]:
    """Weighted sum, re-normalized over the dimensions actually present.

    Re-normalizing is what makes the fallback honest: when JEV is unavailable
    the JEV terms drop out of both the numerator and the denominator, so the
    remaining deterministic terms still produce a valid 0-1 score.
    """
    parts = hybrid_components(row, jev)
    total_weight = 0.0
    total = 0.0
    for name, weight in HYBRID_WEIGHTS.items():
        value = parts[name]
        if value is None:
            continue
        total += weight * value
        total_weight += weight
    score = round(total / total_weight, 4) if total_weight else 0.0
    return score, parts


def deterministic_score(row) -> tuple[float, dict]:
    parts = {
        "recency": recency_score(row["age_hours"]),
        "publisher_corroboration": corroboration_score(row["publisher_count"]),
        "source_priority": priority_score(row["priority"]),
        "followed": 1.0 if row["followed"] else 0.0,
        "meaningful_developments": round(min(row["meaningful_development_count"], 3) / 3.0, 4),
    }
    score = round(sum(DETERMINISTIC_WEIGHTS[k] * v for k, v in parts.items()), 4)
    return score, parts


def explanation(row, jev) -> str:
    """The editor-readable justification. A score is never shown alone."""

    def band(record):
        label = (record or {}).get("answer")
        return {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}.get(label, "unknown")

    return (
        f"locality={(jev.get('locality') or {}).get('answer') or 'n/a'}"
        f"; category={(jev.get('category') or {}).get('answer') or 'n/a'}"
        f"; local relevance={band(jev.get('local_relevance'))}"
        f"; public interest={band(jev.get('public_interest'))}"
        f"; urgency={band(jev.get('urgency'))}"
        f"; novelty={(jev.get('novelty') or {}).get('answer') or 'n/a'}"
        f"; independent publishers={row['publisher_count']}"
        f"; source={row['source_kind'] or 'n/a'}/{row['priority']} priority"
        f"; official={'yes' if 'official' in row['publisher_kinds'] else 'no'}"
        f"; age={row['age_hours']}h"
    )


# ------------------------------------------------------------- distributions


def _confidence_histogram(values, bins=(0.0, 0.5, 0.7, 0.85, 1.01)):
    out = []
    for low, high in itertools.pairwise(bins):
        count = sum(1 for v in values if low <= v < high)
        out.append({"range": f"{low:.2f}-{high:.2f}", "count": count})
    return out


def distribution(values):
    clean = [v for v in values if isinstance(v, (int, float))]
    if not clean:
        return {"n": 0}
    return {
        "n": len(clean),
        "min": round(min(clean), 3),
        "max": round(max(clean), 3),
        "mean": round(statistics.fmean(clean), 3),
        "median": round(statistics.median(clean), 3),
    }


def confidence_report(joined) -> dict:
    """Where the model is confident and where it is guessing."""
    ok = [r for r in joined if r["jev"].get("status") == "JEV_OK"]
    loc_conf = [
        r["jev"]["locality"]["confidence"]
        for r in ok
        if r["jev"]["locality"].get("confidence") is not None
    ]
    cat_conf = [
        r["jev"]["category"]["confidence"]
        for r in ok
        if r["jev"]["category"].get("confidence") is not None
    ]

    locality_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for r in ok:
        loc = r["jev"]["locality"].get("answer")
        cat = r["jev"]["category"].get("answer")
        if loc:
            locality_counts[loc] = locality_counts.get(loc, 0) + 1
        if cat:
            category_counts[cat] = category_counts.get(cat, 0) + 1

    # Candidate thresholds are reported as candidates only. None is chosen here.
    threshold_sweep = {}
    for threshold in (0.5, 0.6, 0.7, 0.8):
        below_loc = sum(1 for v in loc_conf if v < threshold)
        below_cat = sum(1 for v in cat_conf if v < threshold)
        threshold_sweep[f"below_{threshold}"] = {
            "locality": below_loc,
            "locality_pct": round(100.0 * below_loc / len(loc_conf), 1) if loc_conf else None,
            "category": below_cat,
            "category_pct": round(100.0 * below_cat / len(cat_conf), 1) if cat_conf else None,
        }

    def low_confidence_items(field):
        return [
            {
                "story_id": r["story_id"],
                "confidence": r["jev"][field].get("confidence"),
                "answer": r["jev"][field].get("answer"),
                "title": r["title"][:80],
            }
            for r in ok
            if (r["jev"][field].get("confidence") or 0) < 0.5
        ]

    return {
        "locality_confidence": {
            **distribution(loc_conf),
            "histogram": _confidence_histogram(loc_conf),
            "low_confidence_items": low_confidence_items("locality"),
        },
        "category_confidence": {
            **distribution(cat_conf),
            "histogram": _confidence_histogram(cat_conf),
            "low_confidence_items": low_confidence_items("category"),
        },
        "locality_distribution": dict(sorted(locality_counts.items(), key=lambda kv: -kv[1])),
        "category_distribution": dict(sorted(category_counts.items(), key=lambda kv: -kv[1])),
        "score_distributions": {
            "local_relevance": distribution([r["jev"]["local_relevance"].get("score") for r in ok]),
            "public_interest": distribution([r["jev"]["public_interest"].get("score") for r in ok]),
            "urgency": distribution([r["jev"]["urgency"].get("score") for r in ok]),
            "novelty": distribution([r["jev"]["novelty"].get("score") for r in ok]),
        },
        "threshold_sweep": threshold_sweep,
    }


# ------------------------------------------------------------ failure/fallback


def simulate_fallbacks(sample, now) -> dict:
    """Show that the newsroom still works when JEV does not.

    Each scenario re-derives the ranking with the JEV layer removed or one
    Story's JEV output replaced by garbage. No scenario may raise.
    """
    scenarios: dict[str, dict] = {}
    try:
        client, _ = build_client()
    except JevUnavailable as exc:
        client = None
        scenarios["sdk_unavailable"] = {"raised": type(exc).__name__, "degrades": True}

    # 1. API unavailable: no JEV layer at all -> every Story must still rank.
    for row in sample[:5]:
        hybrid_score(row, {"status": "JEV_UNAVAILABLE"})
    scenarios["all_jev_unavailable"] = {
        "description": "every JEV layer removed; the deterministic terms must carry the score",
        "survived": True,
    }

    # 2. Per-Story provider error / invalid response: that Story drops its JEV
    #    terms; the rest of the screen is unaffected.
    broken = {
        "status": "JEV_PROVIDER_ERROR",
        "locality": {"answer": None, "confidence": None},
        "category": {"answer": None, "confidence": None},
        "local_relevance": {"answer": None},
        "public_interest": {"answer": None},
        "urgency": {"answer": None},
        "novelty": {"score": None},
    }
    for row in sample[:5]:
        hybrid_score(row, broken)
    scenarios["per_story_provider_error"] = {"survived": True}

    # 3. Low confidence: a weak answer must not veto a Story.
    weak = {
        "status": "JEV_OK",
        "locality": {"answer": "UNCLEAR", "confidence": 0.2},
        "category": {"answer": "OTHER", "confidence": 0.2},
        "local_relevance": {"answer": "LOW"},
        "public_interest": {"answer": "LOW"},
        "urgency": {"answer": "LOW"},
        "novelty": {"score": 0.05},
    }
    for row in sample[:5]:
        hybrid_score(row, weak)
    scenarios["low_confidence"] = {
        "survived": True,
        "note": "terms are still counted; E1 deliberately enforces no threshold",
    }

    # 4. A real timeout against the live API with an intentionally tiny budget.
    if client is not None:
        try:
            tight, tight_sdk = build_client(timeout=0.001)
            tight.system_one(
                state=build_state(sample[0], now),
                questions=build_questions(tight_sdk),
                model=model_alias(),
            )
            scenarios["timeout"] = {"raised": "none (unexpected)", "degrades": False}
        except Exception as exc:  # noqa: BLE001
            scenarios["timeout"] = {"raised": type(exc).__name__, "degrades": True}
    return scenarios


# ------------------------------------------------------------------- assembly


def join_results(sample, evaluations) -> list[dict]:
    """Deterministic features + JEV output + all three scores, per Story."""
    by_id = {e["story_id"]: e["jev"] for e in evaluations}
    joined = []
    for row in sample:
        jev = by_id.get(row["story_id"], {"status": "JEV_MISSING"})
        hybrid, _parts = hybrid_score(row, jev)
        det, _ = deterministic_score(row)
        joined.append(
            {
                "story_id": row["story_id"],
                "title": row["title"],
                "latestChangeAt": row["latestChangeAt"],
                "age_hours": row["age_hours"],
                "publisher_domain": row["publisher_domain"],
                "publisher_kinds": row["publisher_kinds"],
                "source_kind": row["source_kind"],
                "priority": row["priority"],
                "publisher_count": row["publisher_count"],
                "member_count": row["member_count"],
                "meaningful_development_count": row["meaningful_development_count"],
                "followed": row["followed"],
                "has_active_article": row["has_active_article"],
                "jev": jev,
                "hybrid_score": hybrid,
                "deterministic_score": det,
                "chronological_key": row["latestChangeAt"],
                "explanation": explanation(row, jev),
            }
        )
    return joined


def rank_baselines(joined, *, top=15):
    """Baseline A (chronology), B (deterministic), C (deterministic + JEV)."""

    def compact(entry, method):
        return {
            "method": method,
            "story_id": entry["story_id"],
            "title": entry["title"],
            "latestChangeAt": entry["latestChangeAt"],
            "age_hours": entry["age_hours"],
            "locality": (entry["jev"].get("locality") or {}).get("answer"),
            "locality_confidence": (entry["jev"].get("locality") or {}).get("confidence"),
            "category": (entry["jev"].get("category") or {}).get("answer"),
            "local_relevance": (entry["jev"].get("local_relevance") or {}).get("answer"),
            "public_interest": (entry["jev"].get("public_interest") or {}).get("answer"),
            "urgency": (entry["jev"].get("urgency") or {}).get("answer"),
            "novelty": (entry["jev"].get("novelty") or {}).get("answer"),
            "publisher_count": entry["publisher_count"],
            "source_kind": entry["source_kind"],
            "priority": entry["priority"],
            "hybrid_score": entry["hybrid_score"],
            "deterministic_score": entry["deterministic_score"],
            "explanation": entry["explanation"],
        }

    chronological = sorted(
        joined, key=lambda r: (r["chronological_key"], r["story_id"]), reverse=True
    )
    deterministic = sorted(
        joined, key=lambda r: (r["deterministic_score"], r["chronological_key"]), reverse=True
    )
    hybrid = sorted(joined, key=lambda r: (r["hybrid_score"], r["chronological_key"]), reverse=True)
    return {
        "A_chronology": [compact(e, "A_chronology") for e in chronological[:top]],
        "B_deterministic": [compact(e, "B_deterministic") for e in deterministic[:top]],
        "C_deterministic_plus_jev": [compact(e, "C_deterministic_plus_jev") for e in hybrid[:top]],
    }


def overlap(baselines) -> dict:
    """Where the three methods actually disagree."""
    ids = {name: [e["story_id"] for e in rows] for name, rows in baselines.items()}
    a, b, c = ids["A_chronology"], ids["B_deterministic"], ids["C_deterministic_plus_jev"]
    return {
        "A_only": sorted(set(a) - set(b) - set(c)),
        "B_only": sorted(set(b) - set(a) - set(c)),
        "C_only": sorted(set(c) - set(a) - set(b)),
        "A_and_B_only": sorted((set(a) & set(b)) - set(c)),
        "A_and_C_only": sorted((set(a) & set(c)) - set(b)),
        "B_and_C_only": sorted((set(b) & set(c)) - set(a)),
        "in_all_three": sorted(set(a) & set(b) & set(c)),
        "rank_changes_A_to_C": {
            entry["story_id"]: {
                "A": a.index(entry["story_id"]) + 1 if entry["story_id"] in a else None,
                "C": c.index(entry["story_id"]) + 1 if entry["story_id"] in c else None,
            }
            for entry in baselines["C_deterministic_plus_jev"]
        },
    }


def optional_identity_shadow(joined, now, *, client, sdk, model, size=8, verbose=True):
    """Optional secondary check on a small labelled sample.

    NONE of this touches `story_identity.py`, and nothing here is used in
    production grouping. The point is only to see whether the same primitive
    that classifies a Story could also separate SAME_STORY / NEW_DEVELOPMENT /
    NEW_STORY, or whether that is a genuinely different decision.
    """
    if not joined or client is None:
        return {"attempted": False, "reason": "no client"}

    rng = random.Random(SAMPLING_SEED + 1)
    picked = rng.sample(joined, min(size, len(joined)))
    questions = {
        "relation": sdk.Choice(
            instructions=(
                "Given the anchor headline and a candidate headline, decide the "
                "editorial relation. SAME_STORY = the candidate reports the same "
                "event. NEW_DEVELOPMENT = the same ongoing situation but a "
                "materially new fact. NEW_STORY = a different story."
            ),
            criteria={"SAME_STORY": None, "NEW_DEVELOPMENT": None, "NEW_STORY": None},
        )
    }
    rows = []
    for index, entry in enumerate(picked):
        anchor = picked[(index + 1) % len(picked)]
        try:
            response = client.system_one(
                state={
                    "anchor_headline": entry["title"][:300],
                    "candidate_headline": anchor["title"][:300],
                    "reference_time": now.isoformat(),
                },
                questions=questions,
                model=model,
            )
            answer = _choice(response, "relation")
            rows.append(
                {
                    "anchor_story_id": entry["story_id"],
                    "candidate_story_id": anchor["story_id"],
                    "relation": answer["answer"],
                    "confidence": answer["confidence"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append({"error": type(exc).__name__})
    if verbose:
        for row in rows:
            print(f"  [identity] {row.get('relation')} conf={row.get('confidence')}", flush=True)
    return {"attempted": True, "pairs": len(rows), "results": rows}


# ------------------------------------------------------------------------ main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="V1.1-E1 JEV ranking shadow benchmark")
    parser.add_argument("--limit", type=int, default=TARGET_SAMPLE, help="evaluation set size")
    parser.add_argument("--out", default="/tmp/v11e1", help="scratch output dir (never in var/)")
    parser.add_argument("--dry-run", action="store_true", help="build the sample, make no JEV call")
    parser.add_argument("--repeat-subset", type=int, default=10, help="Stories re-asked 3x each")
    parser.add_argument("--identity-shadow", type=int, default=0, help="optional SAME_STORY pairs")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    verbose = not args.quiet
    now = datetime.now(timezone.utc)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Store integrity is captured BEFORE anything else happens.
    before = hash_guarded_stores()
    if verbose:
        total = sum(len(v) for v in before.values())
        print(f"[integrity] baseline: {total} files across {len(before)} stores")

    corpus = load_corpus()
    all_rows = build_deterministic_features(corpus, now)
    sample = sample_stories(all_rows, target=args.limit)
    if verbose:
        print(f"[sample] {len(sample)} Stories of {len(all_rows)} in the corpus")

    client = sdk = None
    model = model_alias()
    if not args.dry_run:
        try:
            client, sdk = build_client()
        except JevUnavailable as exc:
            print(f"[jev] UNAVAILABLE: {exc}", file=sys.stderr)
            return 2

    evaluations = evaluate_sample(
        sample, now, client=client, sdk=sdk, model=model, dry_run=args.dry_run, verbose=verbose
    )
    joined = join_results(sample, evaluations)
    baselines = rank_baselines(joined)

    payload = {
        "generated_at": now.isoformat(),
        "sampling_seed": SAMPLING_SEED,
        "corpus_size": len(all_rows),
        "sample_size": len(sample),
        "strata": len({stratum_key(r) for r in sample}),
        "weights": {"hybrid": HYBRID_WEIGHTS, "deterministic": DETERMINISTIC_WEIGHTS},
        "locality_taxonomy": list(LOCALITY_CHOICES),
        "category_taxonomy": list(CATEGORY_CHOICES),
        "call_statistics": call_statistics(evaluations),
        "confidence": confidence_report(joined),
        "baselines": baselines,
        "overlap": overlap(baselines),
        "joined": joined,
    }

    if not args.dry_run:
        payload["consistency"] = consistency_check(
            sample,
            now,
            client=client,
            sdk=sdk,
            model=model,
            repeats=args.repeat_subset,
            verbose=verbose,
        )
        payload["fallbacks"] = simulate_fallbacks(sample, now)
        if args.identity_shadow:
            payload["identity_shadow"] = optional_identity_shadow(
                joined,
                now,
                client=client,
                sdk=sdk,
                model=model,
                size=args.identity_shadow,
                verbose=verbose,
            )

    after = hash_guarded_stores()
    diffs = compare_stores(before, after)
    payload["integrity"] = {
        "files_hashed": sum(len(v) for v in before.values()),
        "stores": {k: len(v) for k, v in before.items()},
        "differences": diffs,
        "byte_identical": not diffs,
    }
    if verbose:
        print(f"[integrity] after: {'BYTE-IDENTICAL' if not diffs else 'CHANGED ' + str(diffs)}")

    result_path = out_dir / "v11e1_results.json"
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if verbose:
        print(f"[out] {result_path}")
    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
