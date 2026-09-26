#!/usr/bin/env python3
"""V1.1-F1 — Grouping availability root cause + healthy baseline (DIAGNOSTIC).

F0 left a numerical contradiction that a Story count cannot resolve:

    model unavailable -> 263 Stories
    model available   -> 253 Stories
    live store        -> 253 Stories

Equal counts do NOT imply equal partitions. This script therefore compares
**publication membership**, never Story ids, across three partitions:

    LIVE          the canonical store as it exists on disk
    HEALTHY       the unmodified grouper with a verified-reachable model
    NO_MODEL      the same grouper with ONLY the semantic classifier disabled

Method: for every unordered pair of publications, record whether the two are in
the same cluster in each partition. That co-clustering matrix is independent of
generated Story ids and is the only comparison that can settle §1 of the brief.

Nothing is written to any store. All replay state is in memory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from editor_assistant.workflow import (
    inbox_store,
    story_identity,
    story_relation,
    story_store,
)

STORIES_PATH = ROOT / "var" / "newsroom" / "stories.json"
INBOX_PATH = ROOT / "var" / "newsroom" / "inbox.jsonl"
ARTICLES_PATH = ROOT / "var" / "editorial_workflow" / "editor_articles.jsonl"

GUARDED_STORES = (
    ROOT / "var" / "newsroom",
    ROOT / "var" / "editorial_workflow",
)

#: Pairs of publications are only compared when both sides are actually present
#: in a partition; a publication that is unassigned cannot be "co-clustered".


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
    digest = hashlib.sha256()
    for path in (INBOX_PATH, STORIES_PATH, ARTICLES_PATH):
        digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------------ partitions


def partition_from_store(store) -> dict[str, int]:
    """`item_id -> cluster index`, using a *dense* index, never a Story id.

    A partition is a grouping, not a naming. Mapping every Story to a dense
    index means two partitions can be compared even when their Story ids differ
    entirely (a replay generates new ids by construction).
    """
    return {
        member["item_id"]: index
        for index, story in enumerate(store["stories"])
        for member in story["members"]
    }


def cluster_members(partition) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for item_id, cluster in partition.items():
        out.setdefault(cluster, []).append(item_id)
    return out


def cocluster_pairs(partition) -> set[tuple[str, str]]:
    """Every unordered pair of publications that share a cluster."""
    pairs: set[tuple[str, str]] = set()
    for members in cluster_members(partition).values():
        ordered = sorted(members)
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                pairs.add((left, right))
    return pairs


def compare_partitions(name_a, part_a, name_b, part_b) -> dict:
    """Pairwise co-clustering difference between two partitions.

    Every disagreement is an actual membership change, which is precisely what a
    Story count hides.
    """
    pairs_a = cocluster_pairs(part_a)
    pairs_b = cocluster_pairs(part_b)
    shared = sorted(pairs_a & pairs_b)
    only_a = sorted(pairs_a - pairs_b)  # together in A, apart in B
    only_b = sorted(pairs_b - pairs_a)  # apart in A, together in B

    def affected(pairs):
        return len({item for pair in pairs for item in pair})

    def clusters_touched(part, pairs):
        touched = {item for pair in pairs for item in pair}
        return len({part[item] for item in touched if item in part})

    return {
        "comparison": f"{name_a} vs {name_b}",
        "stories_a": len(set(part_a.values())),
        "stories_b": len(set(part_b.values())),
        "items_a": len(part_a),
        "items_b": len(part_b),
        "pairs_together_both": len(shared),
        "pairs_together_only_a": len(only_a),
        "pairs_together_only_b": len(only_b),
        "affected_publications_only_a": affected(only_a),
        "affected_publications_only_b": affected(only_b),
        "affected_clusters_only_a": clusters_touched(part_a, only_a),
        "affected_clusters_only_b": clusters_touched(part_b, only_b),
        "identical_partition": not only_a and not only_b,
        "examples_only_a": [{"a": x, "b": y} for x, y in only_a[:12]],
        "examples_only_b": [{"a": x, "b": y} for x, y in only_b[:12]],
    }


# ------------------------------------------------- instrumented semantic layer


class SemanticTrace:
    """Records why the production semantic classifier answered or failed.

    F0 collapsed every `classify() -> None` into "model offline". This records
    the actual cause for each one: an import failure, a provider exception, a
    timeout, an unparseable body, a schema rejection, or a genuine
    DIFFERENT_STORY / SAME_STORY answer.
    """

    def __init__(self):
        self.events: list[dict] = []
        self.calls = 0
        self.failures = 0
        self.parse_failures = 0
        self.answers = 0
        self.latencies: list[float] = []
        self.routes: Counter = Counter()
        self.providers: Counter = Counter()
        self.models: Counter = Counter()
        self._current: dict | None = None

    def begin(self, item_id, candidate_story_id, signals):
        self._current = {
            "item_id": item_id,
            "candidate_story_id": candidate_story_id,
            "deterministic_signals": signals,
            "outcome": None,
            "reason": None,
        }

    def end(self):
        if self._current is not None:
            self.events.append(self._current)
            self._current = None

    def __call__(self, prompt_text, *, role="draft", **kwargs):
        self.calls += 1
        started = time.monotonic()
        outcome = {"outcome": None, "reason": None}
        try:
            from editor_assistant.drafting import generate

            raw, meta = generate.call_model(prompt_text, role=role, **kwargs)
        except ImportError as exc:
            self.failures += 1
            outcome = {"outcome": "IMPORT_FAILURE", "reason": type(exc).__name__}
            self._record(outcome, None, started)
            return None, {}
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            name = type(exc).__name__
            reason = name
            if "Budget" in name or "Exhaust" in name or "Limit" in name:
                reason = "BUDGET_OR_ROUTE_EXHAUSTED"
            elif "Timeout" in name:
                reason = "TIMEOUT"
            elif "Auth" in name or "Permission" in name:
                reason = "AUTH_OR_PERMISSION"
            outcome = {"outcome": "PROVIDER_FAILURE", "reason": reason}
            self._record(outcome, None, started)
            return None, {}
        provider = (meta or {}).get("provider")
        model = (meta or {}).get("model")
        fallbacks = (meta or {}).get("fallbacks", 0)
        self.providers[str(provider)] += 1
        self.models[str(model)] += 1
        self.routes[f"provider={provider} fallbacks={fallbacks}"] += 1
        try:
            from editor_assistant.drafting.generate import _extract_first_object

            payload = _extract_first_object(raw)
        except Exception:  # noqa: BLE001
            self.parse_failures += 1
            outcome = {"outcome": "PARSE_FAILURE", "reason": "unparseable model body"}
            self._record(outcome, provider, started)
            return None, {}
        try:
            answer = story_relation.parse_relation(payload)
        except Exception as exc:  # noqa: BLE001
            self.parse_failures += 1
            outcome = {"outcome": "SCHEMA_FAILURE", "reason": type(exc).__name__}
            self._record(outcome, provider, started)
            return None, {}
        self.answers += 1
        outcome = {
            "outcome": "ANSWERED",
            "reason": answer.get("relation"),
            "same_event": answer.get("same_event"),
        }
        self._record(outcome, provider, started)
        return answer, {"provider": provider, "model": model}

    def _record(self, outcome, provider, started):
        self.latencies.append((time.monotonic() - started) * 1000.0)
        if self._current is not None:
            self._current["outcome"] = outcome["outcome"]
            self._current["reason"] = outcome["reason"]
            self._current["same_event"] = outcome.get("same_event")
            self._current["provider"] = provider
        self._current = outcome

    def summary(self):
        return {
            "calls": self.calls,
            "answered": self.answers,
            "failures": self.failures,
            "parse_failures": self.parse_failures,
            "latency_mean_ms": round(statistics.fmean(self.latencies), 1)
            if self.latencies
            else None,
            "latency_p95_ms": (
                round(sorted(self.latencies)[int((len(self.latencies) - 1) * 0.95)], 1)
                if self.latencies
                else None
            ),
            "providers": dict(self.providers),
            "models": dict(self.models),
            "routes": dict(self.routes),
            "outcomes": dict(Counter(e["outcome"] for e in self.events if e.get("outcome"))),
            "answer_relations": dict(
                Counter(e["reason"] for e in self.events if e.get("outcome") == "ANSWERED")
            ),
        }


# ---------------------------------------------------------------- replay engine


def replay_partition(items, items_by_id, *, trace, semantic, now=None, limit=None):
    """Rebuild one partition in memory using the production grouper unchanged.

    `semantic=False` disables ONLY the semantic classifier (the call model is
    replaced by a stub that always fails the way an unavailable provider does).
    Deterministic anchors, candidate generation, ordering and thresholds are all
    left exactly as the production code has them, which is what isolates the
    value of the semantic stage.
    """
    store = {"version": story_store.VERSION, "stories": [], "overrides": []}
    outcomes = []
    candidate_log: list[dict] = []
    ordered = sorted(items, key=lambda i: (i.get("discovered_at") or "", i["item_id"]))
    if limit:
        ordered = ordered[:limit]

    for item in ordered:
        key = story_identity.publication_identity.publication_key(item)
        existing = story_store.story_id_for_publication(store, key) if key else ""
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
            outcomes.append(
                {
                    "item_id": item["item_id"],
                    "action": "EXACT_DUPLICATE",
                    "relation": "SAME_STORY",
                    "story_id": existing,
                }
            )
            continue

        candidates = story_identity.shortlist(item, store, items_by_id, now=now)
        anchored = []
        for story, detail in candidates:
            ok, why = story_identity.strong_anchor(detail)
            if ok:
                anchored.append((story, detail, why))
        # Candidate-generation evidence (§12): is the correct Story even offered?
        candidate_log.append(
            {
                "item_id": item["item_id"],
                "title": str(item.get("title") or "")[:110],
                "candidates": len(candidates),
                "candidate_ids": [s["story_id"] for s, _d in candidates],
                "anchored_ids": [s["story_id"] for s, _d, _w in anchored],
            }
        )

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

        if anchored and semantic:
            story, detail, why = anchored[0]
            trace.begin(
                item["item_id"],
                story["story_id"],
                {
                    "score": detail["score"],
                    "title_overlap": detail["title"],
                    "distinctive_overlap": detail["distinctive"],
                    "numbers": detail["numbers"],
                    "hours": detail["hours"],
                    "shared_tokens": detail.get("shared_tokens", []),
                    "anchor_reason": why,
                    "anchored_candidate_count": len(anchored),
                },
            )
            outcome = story_identity.process_item(
                item, store, items_by_id, semantic=True, call_model=trace, now=now
            )
            trace.end()
            outcomes.append(outcome)
            continue

        outcome = story_identity.process_item(
            item, store, items_by_id, semantic=semantic, call_model=trace, now=now
        )
        outcomes.append(outcome)

    return {
        "store": store,
        "outcomes": outcomes,
        "partition": partition_from_store(store),
        "candidate_log": candidate_log,
    }


# ------------------------------------------------------------------- analysis

#: The labelled duplicate events F0/E1 identified, as publication-keyword probes.
KNOWN_CLUSTERS = {
    "pomporie_dolphin": ["делфин"],
    "pomporie_mbal": [
        "мбал",
        "болницатa",
        "болницата",
        "инвеститор за спасяване",
        "стратегически партньор",
        "стратегически инвеститор",
    ],
    "nessebar_sports_capital": [
        "черноморска столица на спорта",
        "европейска черноморска столица",
        "столица на спорта 2027",
    ],
    "nessebar_wifi": ["безплатен wi-fi", "безплатен достъп до wi-fi", "старинен несебър"],
    "bulgaria_air": ["българия еър"],
}


def known_cluster_membership(partitions, items_by_id) -> dict:
    """For each labelled event: which publications are together in each partition."""
    out = {}
    for label, keywords in KNOWN_CLUSTERS.items():
        members = sorted(
            item_id
            for item_id, item in items_by_id.items()
            if any(
                k in (item.get("title", "") + " " + (item.get("summary") or "")[:200]).lower()
                for k in keywords
            )
        )
        entry = {"publications": len(members), "partitions": {}}
        for name, partition in partitions.items():
            clusters = Counter(partition[m] for m in members if m in partition)
            entry["partitions"][name] = {
                "publications_present": sum(clusters.values()),
                "distinct_clusters": len(clusters),
                "cluster_sizes": sorted(clusters.values(), reverse=True),
                "reunited": len(clusters) == 1 and bool(clusters),
            }
        out[label] = entry
    return out


def candidate_generation_check(candidate_log, partitions, items_by_id) -> dict:
    """§12: could a classifier have merged it if it had wanted to?

    For every item that the HEALTHY run left as a separate Story, was there at
    least one anchored candidate? If not, the blocker was upstream of the model.
    """
    healthy = partitions["HEALTHY"]
    unassigned_after = _items_still_singleton(healthy, items_by_id)
    rows = []
    for item_id in unassigned_after:
        log = next((c for c in candidate_log if c["item_id"] == item_id), None)
        if log is None:
            continue
        rows.append(
            {
                "item_id": item_id,
                "title": log["title"],
                "candidates": log["candidates"],
                "anchored_candidates": len(log["anchored_ids"]),
                "classifier_was_consultable": bool(log["anchored_ids"]),
            }
        )
    return {
        "items_left_separate": len(rows),
        "classifier_was_consultable": sum(1 for r in rows if r["classifier_was_consultable"]),
        "blocked_upstream_no_candidate": sum(
            1 for r in rows if not r["classifier_was_consultable"]
        ),
        "rows": rows,
    }


def _items_still_singleton(partition, items_by_id) -> list[str]:
    clusters = cluster_members(partition)
    return sorted(item_id for item_id, cluster in partition.items() if len(clusters[cluster]) == 1)


def cross_cluster_merges(baseline_part, candidate_part) -> list[dict]:
    """Candidate-partition clusters that fuse two or more baseline clusters."""
    clusters = cluster_members(candidate_part)
    out = []
    for members in clusters.values():
        origins = {baseline_part[m] for m in members if m in baseline_part}
        if len(origins) > 1:
            out.append({"publications": sorted(members), "baseline_clusters": sorted(origins)})
    return out


def grade_merges(merges, items_by_id, live_part) -> dict:
    """Deterministic grading of every proposed merge, with no sampling.

    The grade is a *structural* judgement, stated up front: a merge is only
    CLEAR when every publication it joins was already, in the LIVE partition,
    either in one cluster or in clusters whose headlines share a distinctive
    anchor. Anything else is UNCERTAIN and must be read by a human.
    """
    grades = []
    for merge in merges:
        pubs = merge["publications"]
        live_clusters = {live_part[p] for p in pubs if p in live_part}
        titles = [str((items_by_id.get(p) or {}).get("title") or "") for p in pubs]
        anchors = [story_identity.distinctive_tokens(t) for t in titles]
        common = set.intersection(*anchors) if anchors else set()
        # A shared proper noun / number / rare token is the only evidence this
        # script will accept as "clearly one event".
        strong_common = sorted(tok for tok in common if tok.isdigit() or len(tok) >= 5)
        if len(live_clusters) == 1 or strong_common:
            grade = "CLEAR_SAME_STORY"
        else:
            grade = "UNCERTAIN"
        grades.append(
            {
                "grade": grade,
                "publications": len(pubs),
                "live_clusters_joined": len(live_clusters),
                "shared_strong_tokens": strong_common[:6],
                "headlines": [t[:100] for t in titles],
            }
        )
    counts = Counter(g["grade"] for g in grades)
    return {
        "total": len(grades),
        "counts": dict(counts),
        "precision_clear": (
            round(100.0 * counts.get("CLEAR_SAME_STORY", 0) / len(grades), 1) if grades else None
        ),
        "merges": grades,
    }


# ------------------------------------------------------- preflight + main


def preflight(trace) -> dict:
    """Verify the semantic route is genuinely reachable before trusting HEALTHY."""
    probe = SemanticTrace()
    started = time.monotonic()
    try:
        from editor_assistant.drafting import generate

        raw, meta = generate.call_model('Отговори само с JSON: {"ok": true}', role="story")
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "error": type(exc).__name__,
            "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
        }
    from editor_assistant.drafting.generate import _extract_first_object

    parsed = _extract_first_object(raw)
    del probe
    return {
        "reachable": True,
        "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
        "parsed": bool(parsed),
        "provider": (meta or {}).get("provider"),
        "model": (meta or {}).get("model"),
        "fallbacks": (meta or {}).get("fallbacks"),
        "on_exhausted": (meta or {}).get("on_exhausted"),
        "input_tokens": (meta or {}).get("input_tokens"),
        "output_tokens": (meta or {}).get("output_tokens"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="V1.1-F1 grouping availability diagnosis")
    parser.add_argument("--out", default="/tmp/v11f1", help="scratch dir (never var/)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-healthy", action="store_true", help="NO_MODEL + LIVE only")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    verbose = not args.quiet
    now = datetime.now(timezone.utc)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    before = hash_guarded_stores()
    items = inbox_store.read_items(INBOX_PATH)
    items_by_id = {i["item_id"]: i for i in items}
    live_store = story_store.read_store(STORIES_PATH)
    live_part = partition_from_store(live_store)

    if verbose:
        print(f"[corpus] fingerprint {corpus_fingerprint()[:16]}")
        print(f"[live] {len(set(live_part.values()))} Stories, {len(live_part)} publications")

    payload = {
        "generated_at": now.isoformat(),
        "corpus_fingerprint": corpus_fingerprint(),
        "publications": len(items_by_id),
    }

    # ---- NO_MODEL: only the semantic classifier disabled.
    no_model_trace = SemanticTrace()
    started = time.monotonic()
    no_model = replay_partition(
        items, items_by_id, trace=no_model_trace, semantic=False, now=now, limit=args.limit
    )
    no_model_seconds = round(time.monotonic() - started, 1)
    if verbose:
        print(
            f"[no-model] {len(set(no_model['partition'].values()))} Stories in {no_model_seconds}s"
        )

    partitions = {"LIVE": live_part, "NO_MODEL": no_model["partition"]}
    healthy = None
    healthy_trace = SemanticTrace()

    if not args.skip_healthy:
        probe = preflight(healthy_trace)
        payload["preflight"] = probe
        if verbose:
            print(
                f"[preflight] reachable={probe.get('reachable')} "
                f"model={probe.get('model')} provider={probe.get('provider')}"
            )
        if not probe.get("reachable"):
            payload["integrity"] = {
                "files_hashed": sum(len(v) for v in before.values()),
                "byte_identical": not compare_stores(before, hash_guarded_stores()),
            }
            (out_dir / "v11f1_results.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print("[fatal] semantic route unreachable; cannot build a healthy baseline")
            return 2
        started = time.monotonic()
        healthy = replay_partition(
            items, items_by_id, trace=healthy_trace, semantic=True, now=now, limit=args.limit
        )
        healthy_seconds = round(time.monotonic() - started, 1)
        if verbose:
            print(
                f"[healthy] {len(set(healthy['partition'].values()))} Stories in {healthy_seconds}s"
            )
        partitions["HEALTHY"] = healthy["partition"]

    # ---- §3 partition comparisons (pairwise, id-independent)
    comparisons = []
    if "HEALTHY" in partitions:
        comparisons.append(
            compare_partitions("LIVE", partitions["LIVE"], "HEALTHY", partitions["HEALTHY"])
        )
    comparisons.append(
        compare_partitions("LIVE", partitions["LIVE"], "NO_MODEL", partitions["NO_MODEL"])
    )
    if "HEALTHY" in partitions:
        comparisons.append(
            compare_partitions("HEALTHY", partitions["HEALTHY"], "NO_MODEL", partitions["NO_MODEL"])
        )

    payload.update(
        {
            "story_counts": {name: len(set(part.values())) for name, part in partitions.items()},
            "partitions_compared": comparisons,
            "known_clusters": known_cluster_membership(partitions, items_by_id),
            "semantic_trace": {
                "healthy": healthy_trace.summary() if healthy else None,
                "no_model": no_model_trace.summary(),
            },
            "classify_none_cases": healthy_trace.events if healthy else [],
        }
    )

    if healthy:
        payload["candidate_generation"] = candidate_generation_check(
            healthy["candidate_log"], partitions, items_by_id
        )
        merges = cross_cluster_merges(live_part, healthy["partition"])
        payload["healthy_cross_cluster_merges"] = grade_merges(merges, items_by_id, live_part)

    after = hash_guarded_stores()
    diffs = compare_stores(before, after)
    payload["integrity"] = {
        "files_hashed": sum(len(v) for v in before.values()),
        "stores": {k: len(v) for k, v in before.items()},
        "differences": diffs,
        "byte_identical": not diffs,
    }
    if verbose:
        print(f"[integrity] {'BYTE-IDENTICAL' if not diffs else 'CHANGED ' + str(diffs)}")
    (out_dir / "v11f1_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if verbose:
        print(f"[out] {out_dir / 'v11f1_results.json'}")
    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
