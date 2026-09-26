#!/usr/bin/env python3
"""V1.1-F0 — JEV Story-identity full-corpus replay (READ-ONLY / ISOLATED).

Question being answered, with evidence:

    Would a *conservative* JEV SAME_STORY confirmer, inserted into the existing
    grouper, reduce real false splits across the whole current corpus — and
    would it introduce any false merge?

Hard boundaries enforced by this script
--------------------------------------
* **isolated** — the replay runs against an in-memory store rebuilt from the
  raw inbox. It never opens `var/newsroom` or `var/editorial_workflow` for
  writing, and never calls a production write path;
* **no production grouping change** — `story_identity.py` is imported read-only
  and is NOT modified; Candidate B is an experimental strategy inside this
  script;
* **no authority** — JEV may only *confirm* a plausible deterministic candidate.
  It can never override a hard contradiction, never invent a merge, and never
  decide `NEW_DEVELOPMENT` / `RELATED_BACKGROUND` / `NEW_STORY`;
* **false split is preferable to false merge** — every structural rule here is
  biased toward keeping two items separate when uncertain;
* **secret hygiene** — the key is read from the environment and never printed,
  logged or persisted.

Usage:
  PYTHONPATH=src python3 scripts/v11f0_jev_story_identity_replay.py --dry-run
  PYTHONPATH=src python3 scripts/v11f0_jev_story_identity_replay.py \
      --out /tmp/v11f0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from editor_assistant.workflow import (
    inbox_store,
    story_identity,
    story_store,
)

STORIES_PATH = ROOT / "var" / "newsroom" / "stories.json"
INBOX_PATH = ROOT / "var" / "newsroom" / "inbox.jsonl"
METADATA_PATH = ROOT / "var" / "newsroom" / "story_editor_metadata.json"
ARTICLES_PATH = ROOT / "var" / "editorial_workflow" / "editor_articles.jsonl"

#: Stores that must be byte-identical before and after.
GUARDED_STORES = (
    ROOT / "var" / "newsroom",
    ROOT / "var" / "editorial_workflow",
)

TYPESAFE_API_KEY_ENV = "TYPESAFE_API_KEY"
JEV_MODEL_ENV = "JEV_MODEL"
DEFAULT_MODEL_ALIAS = "jev-latest"

#: Maximum JEV comparisons per incoming item. A duplicate should be visible in
#: the existing shortlist; this bounds cost and forbids a semantic O(n^2) sweep.
JEV_CANDIDATE_LIMIT = 3

#: Deterministic replay configuration, frozen for reproducibility.
REPLAY_CONFIG = {
    "candidate_limit": JEV_CANDIDATE_LIMIT,
    "shortlist_size": story_identity.SHORTLIST_SIZE,
    "shortlist_days": story_identity.STORY_SHORTLIST_DAYS,
    "strong_title_overlap": story_identity.STRONG_TITLE_OVERLAP,
    "strong_distinctive_overlap": story_identity.STRONG_DISTINCTIVE_OVERLAP,
    "anchor_title_overlap": story_identity.ANCHOR_TITLE_OVERLAP,
    "anchor_shared_strong_tokens": story_identity.ANCHOR_SHARED_STRONG_TOKENS,
    "anchor_max_hours": story_identity.ANCHOR_MAX_HOURS,
    "close_publication_hours": story_identity.CLOSE_PUBLICATION_HOURS,
}

#: The narrowest useful JEV question: is this the same event? Nothing else.
SAME_STORY_QUESTION = (
    "Do these two news headlines report the SAME real-world event? "
    "Answer SAME_EVENT only if a reader would say both describe one occurrence. "
    "Answer DIFFERENT_EVENT if they describe separate occurrences, even when "
    "they share the same town, the same institution or the same topic."
)


# ------------------------------------------------------------------- integrity


def _hash_tree(root: Path) -> dict[str, str]:
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
    problems = []
    for store in sorted(set(before) | set(after)):
        b, a = before.get(store, {}), after.get(store, {})
        for rel in sorted(set(b) | set(a)):
            if b.get(rel) != a.get(rel):
                problems.append(f"{store}/{rel}")
    return problems


def corpus_fingerprint() -> str:
    """A single hash binding this run to the exact corpus snapshot."""
    digest = hashlib.sha256()
    for path in (INBOX_PATH, STORIES_PATH, METADATA_PATH, ARTICLES_PATH):
        digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------ hard exclusions
#
# Deterministic contradictions JEV may NEVER override. Each is derived from a
# real repository signal, not invented for this experiment.

#: Municipality / town names that identify *where* an event happened.
PLACE_RX = re.compile(
    r"\b(?:община|общината|кмет(?:ът|ът|а)|съвет|болница|мбал|гробищ|газ|водопровод|"
    r"детска\s+градина|дг|пик|училищ(?:е|ето|а)|университет|пристанище|яз|пиро)"
    r"\b",
    re.IGNORECASE,
)

#: Tokens that name an official act, an office, or a candidacy.
OFFICE_TOKENS = (
    "кмет",
    "общински съвет",
    "министър",
    "министерство",
    "депутат",
    "кандидат",
    "избори",
    "квалификация",
    "конкурс",
    "договор",
    "заповед",
    "решение на",
)


def _story_rows(story, items_by_id) -> list[dict]:
    """Member inbox rows of a Story; the grouper's own membership order."""
    return [items_by_id.get(m["item_id"]) or {} for m in story.get("members") or []]


def hard_contradiction(item, story, items_by_id) -> str | None:
    """Return a reason string when JEV must NOT be consulted at all.

    Conservative by design: a contradiction only fires on signals the current
    grouper already computes, and absence of a contradiction is never treated as
    evidence for a merge.
    """
    # 1. Materially incompatible dates: an event is not both "now" and weeks ago.
    detail_hours = story_identity.similarity(item, story, items_by_id).get("hours")
    if detail_hours is not None and detail_hours > story_identity.ANCHOR_MAX_HOURS:
        return f"temporal gap {detail_hours}h > ANCHOR_MAX_HOURS"

    # 2. Two different official acts / offices.
    #    NOTE: an earlier draft also tried to hard-exclude on "disjoint named
    #    people". That rule was REMOVED after it was measured firing on publisher
    #    suffixes ("Варна Спасиха", "Новини Делфин", "Поморие Черноморски") and
    #    blocking 3 of the 7 genuine dolphin duplicates. Bulgarian headlines carry
    #    no reliable person marker, so a capital-letter heuristic cannot separate
    #    a person from a source name. An unsound hard negative is worse than none:
    #    it silently converts recall into false splits.
    item_offices = {t for t in OFFICE_TOKENS if t in str(item.get("title") or "").lower()}
    story_offices = set()
    for row in _story_rows(story, items_by_id):
        low = str(row.get("title") or "").lower()
        story_offices |= {t for t in OFFICE_TOKENS if t in low}
    if item_offices and story_offices and not (item_offices & story_offices):
        return f"disjoint official acts {sorted(item_offices)} vs {sorted(story_offices)}"

    return None


# ------------------------------------------------------------------ JEV client


class JevUnavailable(RuntimeError):
    """SDK or key missing. The replay must degrade, never fabricate a merge."""


def build_client(timeout=60.0):
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


def _plain(value):
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


class SameStoryJudge:
    """One narrow question: same event or not. No taxonomy, no relation ladder.

    Deliberately binary. The corpus rule is `false split is preferable to false
    merge`, so JEV is never asked for `NEW_DEVELOPMENT` or `RELATED_BACKGROUND`:
    those stay the existing system's responsibility, and a `DIFFERENT_EVENT`
    answer simply hands the item back to the production path.
    """

    def __init__(self, client, sdk, model, *, timeout_stats):
        self._client = client
        self._sdk = sdk
        self._model = model
        self._stats = timeout_stats
        self._questions = {
            "relation": sdk.Choice(
                instructions=SAME_STORY_QUESTION,
                criteria={"SAME_EVENT": None, "DIFFERENT_EVENT": None},
            )
        }
        self.calls = 0
        self.errors = 0
        self.latencies: list[float] = []
        self.input_tokens = 0
        self.output_tokens = 0

    def judge(self, item, story, items_by_id) -> dict:
        """Return `{decision, confidence, latency_ms}`; never raises."""
        state = {
            "headline_a": " ".join(str(item.get("title") or "").split())[:300],
            "summary_a": " ".join(str(item.get("summary") or "").split())[:400],
            "published_a": str(item.get("published_at") or ""),
            "headline_b": " ".join(
                str(
                    (items_by_id.get(story["members"][0]["item_id"]) or {}).get("title") or ""
                ).split()
            )[:300],
            "summary_b": " ".join(
                str(
                    (items_by_id.get(story["members"][0]["item_id"]) or {}).get("summary") or ""
                ).split()
            )[:400],
        }
        started = time.monotonic()
        self.calls += 1
        try:
            response = self._client.system_one(
                state=state, questions=self._questions, model=self._model
            )
        except Exception as exc:  # noqa: BLE001 - degradation, never a merge
            self.errors += 1
            return {
                "decision": "UNAVAILABLE",
                "confidence": None,
                "error": type(exc).__name__,
                "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
            }
        latency = round((time.monotonic() - started) * 1000.0, 1)
        self.latencies.append(latency)
        usage = getattr(response, "usage", None)
        self.input_tokens += _plain(getattr(usage, "input_tokens", 0)) or 0
        self.output_tokens += _plain(getattr(usage, "output_tokens", 0)) or 0
        answer = (getattr(response, "choices", {}) or {}).get("relation")
        if answer is None:
            self.errors += 1
            return {"decision": "UNAVAILABLE", "confidence": None, "latency_ms": latency}
        return {
            "decision": _plain(getattr(answer, "choice", None)),
            "confidence": _plain(getattr(answer, "confidence", None)),
            "latency_ms": latency,
        }


class SemanticCache:
    """Records the production LLM's answers so both arms cost one set of calls.

    Baseline A and Candidate B ask the *same* production question about the
    *same* (item, story) pair whenever Candidate B declines to merge. Replaying
    the live model for both arms would double a ~30 minute LLM-bound run for no
    additional evidence, and any drift between the two passes would make the A/B
    comparison unfair.

    The cache is a pure memo of an external side effect. It changes no decision
    and grants no authority: a cache miss simply calls the real grouper.
    """

    def __init__(self, enabled=True):
        self.enabled = enabled
        self._memo: dict[tuple, object] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(prompt_text, role):
        return (role, hashlib.sha256(prompt_text.encode("utf-8")).hexdigest())

    def __call__(self, prompt_text, *, role="draft", **kwargs):
        key = self._key(prompt_text, role)
        if self.enabled and key in self._memo:
            self.hits += 1
            return self._memo[key]
        self.misses += 1
        from editor_assistant.drafting import generate

        result = generate.call_model(prompt_text, role=role, **kwargs)
        if self.enabled:
            self._memo[key] = result
        return result

    def stats(self):
        return {"hits": self.hits, "misses": self.misses, "enabled": self.enabled}


# ---------------------------------------------------------------- replay engine


def replay(items, items_by_id, *, judge=None, call_model=None, now=None, verbose=True, limit=None):
    """Rebuild grouping from the raw inbox in ingestion order, in memory only.

    Two strategies share this one function so the comparison is exact:

    * `judge=None`  -> **Baseline A**, the production grouper unchanged
      (`story_identity.process_item` verbatim);
    * `judge=<JEV>` -> **Candidate B**, identical except that an anchored
      candidate which the deterministic test left undecided may be *confirmed*
      as `SAME_STORY` by JEV, subject to the dual gate and hard exclusions.

    Nothing is persisted. The store is a local dict.
    """
    store = {"version": story_store.VERSION, "stories": [], "overrides": []}
    outcomes = []
    shadow = []
    ordered = sorted(items, key=lambda i: (i.get("discovered_at") or "", i["item_id"]))
    if limit:
        ordered = ordered[:limit]

    for item in ordered:
        key = story_identity.publication_identity.publication_key(item)
        existing = story_store.story_id_for_publication(store, key) if key else ""

        if existing:
            # Stage A: exact publication identity. Never spends a JEV call.
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
            outcomes.append(
                {
                    "item_id": item["item_id"],
                    "action": "EXACT_DUPLICATE",
                    "relation": "SAME_STORY",
                    "story_id": existing,
                }
            )
            continue

        # Stage B: strong deterministic matches stay deterministic (no JEV call).
        candidates = story_identity.shortlist(item, store, items_by_id, now=now)
        decided = None
        for story, detail in candidates:
            relation, _reason = story_identity.deterministic_relation(item, story, detail)
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
                decided = {
                    "item_id": item["item_id"],
                    "action": "DETERMINISTIC",
                    "relation": relation,
                    "story_id": story["story_id"],
                }
                break
        if decided:
            outcomes.append(decided)
            continue

        if judge is None:
            # ---- Baseline A: the production semantic stage, verbatim.
            outcome = story_identity.process_item(
                item, store, items_by_id, semantic=True, call_model=call_model, now=now
            )
            outcomes.append(outcome)
            continue

        # ---- Candidate B: conservative JEV SAME_STORY confirmation.
        decided = _candidate_b(item, store, items_by_id, judge, key, now, shadow)
        if decided:
            outcomes.append(decided)
            continue

        # No confirmation: hand back to the production path unchanged.
        outcome = story_identity.process_item(
            item, store, items_by_id, semantic=True, call_model=call_model, now=now
        )
        outcomes.append(outcome)

    return {"store": store, "outcomes": outcomes, "shadow": shadow}


def _candidate_b(item, store, items_by_id, judge, key, now, shadow) -> dict | None:
    """`plausible deterministic candidate AND JEV SAME_STORY AND no contradiction`.

    Three conditions, all required:

    1. the candidate cleared the production `strong_anchor` gate, so it is a
       plausible duplicate and not an unrelated same-town Story;
    2. no `hard_contradiction` fires;
    3. JEV answers `SAME_EVENT`.

    A contradiction, an `UNAVAILABLE` answer or a `DIFFERENT_EVENT` answer all
    fall through to the production path. There is no path here that creates a
    merge JEV did not explicitly confirm.
    """
    candidates = story_identity.shortlist(item, store, items_by_id, now=now)
    anchored = []
    for story, detail in candidates:
        ok, why = story_identity.strong_anchor(detail)
        if ok:
            anchored.append((story, detail, why))
    # Bounded: never an unbounded semantic search over the whole store.
    for story, detail, why in anchored[:JEV_CANDIDATE_LIMIT]:
        contradiction = hard_contradiction(item, story, items_by_id)
        if contradiction:
            shadow.append(
                {
                    "item_id": item["item_id"],
                    "candidate_story_id": story["story_id"],
                    "gate": "HARD_CONTRADICTION",
                    "reason": contradiction,
                    "jev": None,
                    "result": "NOT_CONSULTED",
                }
            )
            continue
        verdict = judge.judge(item, story, items_by_id)
        shadow.append(
            {
                "item_id": item["item_id"],
                "candidate_story_id": story["story_id"],
                "gate": "ANCHORED",
                "anchor_reason": why,
                "deterministic_score": detail["score"],
                "title_overlap": detail["title"],
                "shared_tokens": detail.get("shared_tokens", []),
                "jev": verdict,
                "result": "CONFIRMED" if verdict["decision"] == "SAME_EVENT" else "REJECTED",
            }
        )
        if verdict["decision"] == "SAME_EVENT":
            story_store.add_member(
                story,
                item,
                relation="SAME_STORY",
                relation_source="jev_confirmed",
                publication_key=key or "",
                now=now,
            )
            story_store.refresh_times(story, items_by_id, now=now)
            return {
                "item_id": item["item_id"],
                "action": "JEV_CONFIRMED_SAME_STORY",
                "relation": "SAME_STORY",
                "story_id": story["story_id"],
            }
    return None


# ------------------------------------------------------------------- analysis


def cluster_map(store, items_by_id) -> dict[str, list[str]]:
    """Story id -> its member item ids, for cluster inspection."""
    return {
        story["story_id"]: [m["item_id"] for m in story["members"]] for story in store["stories"]
    }


def size_distribution(store) -> dict:
    sizes: dict[int, int] = {}
    for story in store["stories"]:
        sizes[len(story["members"])] = sizes.get(len(story["members"]), 0) + 1
    return {str(k): sizes[k] for k in sorted(sizes)}


def summarize(store, outcomes, items_by_id) -> dict:
    relations: dict[str, int] = {}
    actions: dict[str, int] = {}
    for row in outcomes:
        rel = row.get("relation") or "-"
        relations[rel] = relations.get(rel, 0) + 1
        act = row.get("action") or "-"
        actions[act] = actions.get(act, 0) + 1
    return {
        "stories": len(store["stories"]),
        "items": len(items_by_id),
        "same_story_members": sum(
            1 for s in store["stories"] for m in s["members"] if m["relation"] == "SAME_STORY"
        ),
        "new_development_members": sum(
            1 for s in store["stories"] for m in s["members"] if m["relation"] == "NEW_DEVELOPMENT"
        ),
        "multi_member_stories": sum(1 for s in store["stories"] if len(s["members"]) > 1),
        "largest_cluster": max((len(s["members"]) for s in store["stories"]), default=0),
        "needs_review": sum(1 for s in store["stories"] if s.get("needs_review")),
        "relations": relations,
        "actions": actions,
        "cluster_sizes": size_distribution(store),
    }


def cross_story_merges(baseline_store, candidate_store) -> list[dict]:
    """Every Candidate-B Story that absorbed items from >1 Baseline-A Story.

    This is the complete set of proposed merges — the §14 false-merge audit
    input. Nothing is sampled.
    """
    owner: dict[str, str] = {}
    for story in baseline_store["stories"]:
        for member in story["members"]:
            owner[member["item_id"]] = story["story_id"]

    merges = []
    for story in candidate_store["stories"]:
        origins = {owner.get(m["item_id"]) for m in story["members"]}
        origins.discard(None)
        if len(origins) > 1:
            merges.append(
                {
                    "candidate_story_id": story["story_id"],
                    "baseline_story_ids": sorted(origins),
                    "item_count": len(story["members"]),
                    "members": [
                        {
                            "item_id": m["item_id"],
                            "from_baseline_story": owner.get(m["item_id"]),
                            "relation": m["relation"],
                            "relation_source": m["relation_source"],
                        }
                        for m in story["members"]
                    ],
                }
            )
    return merges


def load_reference_state() -> dict:
    """Canonical references that a future repair would have to respect."""
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))["stories"]
    articles = [
        json.loads(line)
        for line in ARTICLES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    article_by_story: dict[str, list[dict]] = {}
    for article in articles:
        article_by_story.setdefault(article["story_id"], []).append(article)
    return {
        "metadata": {row["story_id"]: row for row in metadata},
        "article_by_story": article_by_story,
    }


def classify_merge_buckets(merges, reference) -> dict:
    """§16 buckets: what each proposed merge would actually disturb."""
    buckets = {
        "SAFE_EMPTY_FRAGMENT": [],
        "HAS_EDITOR_METADATA": [],
        "HAS_ARTICLE_LINEAGE": [],
        "MULTIPLE_ARTICLE_LINEAGES": [],
        "OTHER_CONFLICT": [],
    }
    for merge in merges:
        ids = merge["baseline_story_ids"]
        with_articles = [i for i in ids if reference["article_by_story"].get(i)]
        with_metadata = [
            i
            for i in ids
            if reference["metadata"].get(i, {}).get("last_reviewed_at")
            or reference["metadata"].get(i, {}).get("followed")
        ]
        ignored = [s for s in ids if (s in reference["metadata"] and reference["metadata"][s])]
        if len(with_articles) > 1:
            bucket = "MULTIPLE_ARTICLE_LINEAGES"
        elif with_articles:
            bucket = "HAS_ARTICLE_LINEAGE"
        elif with_metadata:
            bucket = "HAS_EDITOR_METADATA"
        elif ignored:
            bucket = "OTHER_CONFLICT"
        else:
            bucket = "SAFE_EMPTY_FRAGMENT"
        merge["bucket"] = bucket
        merge["story_ids_with_articles"] = with_articles
        merge["story_ids_with_metadata"] = with_metadata
        buckets[bucket].append(merge["candidate_story_id"])
    return buckets


# ------------------------------------------------------- false-merge auditing


def audit_cross_story_merges(merges, baseline_store, items_by_id, judge, verbose=True):
    """Manual-grade EVERY proposed cross-Story merge (§14).

    Grading is deterministic and stated up front so the audit is reproducible:

    * `CLEAR_SAME_STORY` — every member pair is confirmed `SAME_EVENT` by JEV
      against the cluster's first member, with no contradiction;
    * `PLAUSIBLE_SAME_STORY` — confirmed but only after a contradiction was
      suppressed, or with a borderline deterministic signal;
    * `WRONG_MERGE` — any member pair answers `DIFFERENT_EVENT`;
    * `UNCERTAIN` — a JEV answer was unavailable, so no evidence exists either
      way. This is the bucket that must be reviewed by a human.

    No sampling: every merge in the list is graded.
    """
    baseline_title = {
        story["story_id"]: str(
            (items_by_id.get(story["members"][0]["item_id"]) or {}).get("title") or ""
        )
        for story in baseline_store["stories"]
    }
    grades = []
    for merge in merges:
        candidate_story = _candidate_index[merge["candidate_story_id"]]
        anchor_item = items_by_id.get(candidate_story["members"][0]["item_id"]) or {}
        votes = []
        suppressed = 0
        for member in merge["members"]:
            if member["relation_source"] != "jev_confirmed":
                continue
            item = items_by_id.get(member["item_id"]) or {}
            contradiction = hard_contradiction(
                item, _candidate_index[merge["candidate_story_id"]], items_by_id
            )
            if contradiction:
                suppressed += 1
                votes.append(("CONTRADICTION", None))
                continue
            verdict = judge.judge(item, candidate_story, items_by_id)
            votes.append((verdict["decision"], verdict.get("confidence")))

        labels = [v[0] for v in votes]
        if not votes:
            grade = "UNCERTAIN"
        elif "DIFFERENT_EVENT" in labels:
            grade = "WRONG_MERGE"
        elif "UNAVAILABLE" in labels or "CONTRADICTION" in labels:
            grade = "UNCERTAIN"
        elif suppressed:
            grade = "PLAUSIBLE_SAME_STORY"
        else:
            grade = "CLEAR_SAME_STORY"

        grades.append(
            {
                "candidate_story_id": merge["candidate_story_id"],
                "grade": grade,
                "bucket": merge.get("bucket"),
                "baseline_story_ids": merge["baseline_story_ids"],
                "item_count": merge["item_count"],
                "headline": str(anchor_item.get("title") or "")[:120],
                "votes": labels,
                "baseline_titles": [
                    baseline_title.get(i, "")[:70] for i in merge["baseline_story_ids"]
                ],
            }
        )
        if verbose:
            print(f"  [{grade:20}] {merge['candidate_story_id']} items={merge['item_count']}")
    return grades


_candidate_index: dict[str, dict] = {}


# ---------------------------------------------------------------------- main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="V1.1-F0 JEV Story-identity replay")
    parser.add_argument("--out", default="/tmp/v11f0", help="scratch dir (never var/)")
    parser.add_argument("--dry-run", action="store_true", help="Baseline A only, no JEV call")
    parser.add_argument("--limit", type=int, default=None, help="replay only N items")
    parser.add_argument("--no-cache", action="store_true", help="re-ask the LLM in both arms")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    verbose = not args.quiet
    now = datetime.now(timezone.utc)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    before = hash_guarded_stores()
    if verbose:
        total = sum(len(v) for v in before.values())
        print(f"[integrity] baseline: {total} files across {len(before)} stores")
        print(f"[corpus] fingerprint {corpus_fingerprint()[:16]}")

    items = inbox_store.read_items(INBOX_PATH)
    items_by_id = {i["item_id"]: i for i in items}
    reference = load_reference_state()

    # ---------------- Baseline A: the production grouper, unchanged.
    if verbose:
        print("[baseline A] replaying with story_identity.process_item ...")
    # One shared semantic cache: both arms ask the production grouper the same
    # questions, so the A/B difference is the JEV confirmer and nothing else.
    cache = SemanticCache(enabled=not args.no_cache)
    started = time.monotonic()
    baseline = replay(
        items, items_by_id, judge=None, call_model=cache, now=now, verbose=verbose, limit=args.limit
    )
    baseline_seconds = time.monotonic() - started
    baseline_summary = summarize(baseline["store"], baseline["outcomes"], items_by_id)
    baseline_summary["runtime_seconds"] = round(baseline_seconds, 1)
    if verbose:
        print(f"[baseline A] {baseline_summary['stories']} stories in {baseline_seconds:.1f}s")

    payload = {
        "generated_at": now.isoformat(),
        "corpus_fingerprint": corpus_fingerprint(),
        "semantic_cache_after_baseline": cache.stats(),
        "config": {**REPLAY_CONFIG, "item_limit": args.limit},
        "baseline_A": baseline_summary,
    }

    if args.dry_run:
        payload["integrity"] = {
            "files_hashed": sum(len(v) for v in before.values()),
            "byte_identical": not compare_stores(before, hash_guarded_stores()),
        }
        (out_dir / "v11f0_results.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        if verbose:
            print("[dry-run] no JEV call made")
        return 0

    # ---------------- Candidate B: + conservative JEV confirmation.
    client, sdk = build_client()
    judge = SameStoryJudge(client, sdk, model_alias(), timeout_stats=None)
    if verbose:
        print(
            f"[candidate B] replaying with JEV confirmer ({JEV_CANDIDATE_LIMIT} candidates max) ..."
        )
    started = time.monotonic()
    candidate = replay(
        items,
        items_by_id,
        judge=judge,
        call_model=cache,
        now=now,
        verbose=verbose,
        limit=args.limit,
    )
    candidate_seconds = time.monotonic() - started
    candidate_summary = summarize(candidate["store"], candidate["outcomes"], items_by_id)
    candidate_summary["runtime_seconds"] = round(candidate_seconds, 1)

    global _candidate_index
    _candidate_index = {s["story_id"]: s for s in candidate["store"]["stories"]}

    if verbose:
        print(f"[candidate B] {candidate_summary['stories']} stories in {candidate_seconds:.1f}s")

    # ---------------- Analysis
    merges = cross_story_merges(baseline["store"], candidate["store"])
    buckets = classify_merge_buckets(merges, reference)
    if verbose:
        print(f"[audit] {len(merges)} cross-Story merge(s) to grade")
    grades = audit_cross_story_merges(
        merges, baseline["store"], items_by_id, judge, verbose=verbose
    )

    grade_counts: dict[str, int] = {}
    for row in grades:
        grade_counts[row["grade"]] = grade_counts.get(row["grade"], 0) + 1

    latencies = sorted(judge.latencies)

    def pct(q):
        if not latencies:
            return None
        return round(latencies[min(len(latencies) - 1, round((len(latencies) - 1) * q))], 1)

    payload.update(
        {
            "candidate_B": candidate_summary,
            "cross_story_merges": merges,
            "merge_buckets": buckets,
            "merge_grades": grades,
            "grade_counts": grade_counts,
            "shadow_audit": candidate["shadow"],
            "jev_usage": {
                "judgement_calls": judge.calls,
                "errors": judge.errors,
                "input_tokens_total": judge.input_tokens,
                "output_tokens_total": judge.output_tokens,
                "input_tokens_mean": round(judge.input_tokens / judge.calls, 1)
                if judge.calls
                else None,
                "latency_mean_ms": round(statistics.fmean(latencies), 1) if latencies else None,
                "latency_p50_ms": pct(0.5),
                "latency_p95_ms": pct(0.95),
                "model": model_alias(),
                "note": "the API exposes no price field; no monetary cost is asserted",
            },
        }
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

    (out_dir / "v11f0_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if verbose:
        print(f"[out] {out_dir / 'v11f0_results.json'}")
    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
