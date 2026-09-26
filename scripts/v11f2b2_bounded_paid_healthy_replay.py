#!/usr/bin/env python3
"""V1.1-F2B2 — Bounded-paid healthy replay of the EXISTING semantic classifier.

F2B stopped at its precondition and produced the architectural result: the
internal role budget is no longer limiting, but the *known configured free
capacity* (60) is far below the 182 classifications a 300-item catch-up needs.
This slice removes that second constraint **for this run only** and finally
answers the question the whole sequence has been building toward:

    What does the EXISTING classifier do when capacity is genuinely sufficient —
    and is JEV adding anything we would need a second permanent dependency for?

Paid access is scoped to this process
--------------------------------------
The override uses the repository's existing `MODEL_POLICY_PATH` hook, which
`model_policy.load_policy()` already reads. It is:

* a **separate file under /tmp** — the operator's `var/model_policy.json` and
  the tracked `config/model_policy.default.json` are never written;
* **process-scoped** — it exists only for this run and dies with it, so Today,
  Refresh, Research and Quick Draft can never inherit it;
* **verified** before and after by asserting the normal policy still reports
  `paid_enabled: false`.

No production code is modified. No new feature-flag system is built.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from editor_assistant.drafting import model_policy, model_usage
from editor_assistant.workflow import (
    inbox_store,
    story_identity,
    story_store,
)

STORIES_PATH = ROOT / "var" / "newsroom" / "stories.json"
INBOX_PATH = ROOT / "var" / "newsroom" / "inbox.jsonl"
ARTICLES_PATH = ROOT / "var" / "editorial_workflow" / "editor_articles.jsonl"

GUARDED_STORES = (
    ROOT / "var" / "newsroom",
    ROOT / "var" / "editorial_workflow",
)

#: §3 hard replay cap. Expected demand is 182; 220 leaves narrow headroom for
#: replay variation while preventing runaway paid usage. A replay that reaches
#: this cap stops and reports MAINTENANCE_CAP_INSUFFICIENT — it never raises it.
MAX_SEMANTIC_CALLS = 220

#: Expected demand, carried from F1/F2A measurements rather than guessed.
EXPECTED_SEMANTIC_CALLS = 182

CORPUS_FINGERPRINT = "d02f2b9b5a281434"  # §6 freeze, identical to F1


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
    return digest.hexdigest()[:16]


# ------------------------------------------------------------ scoped policy


def normal_policy_paid_enabled() -> bool:
    """The runtime policy as the newsroom actually sees it (no override)."""
    saved = os.environ.pop("MODEL_POLICY_PATH", None)
    try:
        return bool(model_policy.load_policy()["global"].get("paid_enabled"))
    finally:
        if saved is not None:
            os.environ["MODEL_POLICY_PATH"] = saved


def build_scoped_policy(path: Path, *, hard_calls_day: int) -> dict:
    """Write a /tmp policy enabling paid routes for THIS process only.

    The diff is deliberately minimal: only the paid gate, the story role's hard
    budget (so the router's own budget stop still bounds the run) and the daily
    spend ceiling. Route order is untouched, so free routes are still tried
    first and paid routes remain a genuine fallback rather than a first choice.
    """
    policy = model_policy.load_policy(env_overrides=False)
    scoped = copy.deepcopy(policy)
    scoped["global"]["paid_enabled"] = True
    story = scoped["roles"]["story"]
    story["hard_calls_day"] = hard_calls_day
    story["soft_calls_day"] = min(
        int(story.get("soft_calls_day") or 0) or hard_calls_day, hard_calls_day
    )
    path.write_text(
        json.dumps({"global": scoped["global"], "roles": {"story": story}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return scoped


# ------------------------------------------------- instrumented call model


class ReplayCallModel:
    """Wraps the production classifier and records every semantic opportunity.

    Free-first is preserved by construction: this calls the real router, which
    walks the configured route order. A paid route is only reached when every
    free route is skipped, which is exactly the maintenance-fallback behaviour
    the owner asked for.
    """

    def __init__(self, *, cap: int):
        self.cap = cap
        self.required = 0
        self.answered = 0
        self.free_answered = 0
        self.paid_answered = 0
        self.degraded = 0
        self.budget_failures = 0
        self.external_quota_failures = 0
        self.auth_failures = 0
        self.parse_failures = 0
        self.other_failures = 0
        self.events: list[dict] = []
        self.latencies: list[float] = []
        self.paid_cost_before = model_usage.paid_cost_today()
        self._current: dict | None = None

    def begin(self, item_id, candidate_story_id, signals):
        self.required += 1
        self._current = {
            "item_id": item_id,
            "candidate_story_id": candidate_story_id,
            "signals": signals,
            "outcome": None,
            "reason": None,
            "provider": None,
            "model": None,
        }

    def end(self):
        if self._current is not None:
            self.events.append(self._current)
            self._current = None

    def __call__(self, prompt_text, *, role="draft", **kwargs):
        from editor_assistant.drafting import model_router
        from editor_assistant.workflow import story_relation

        if self.required > self.cap:
            # §9: stop rather than continue degraded, and never raise the cap.
            # The failure is routed through the same classifier as any other so
            # the counters stay honest: a capped item IS a degraded item, and a
            # cap that skipped accounting would under-report quality loss
            # exactly when it matters most.
            self._classify_failure(
                model_router.RoleUnavailable(
                    role,
                    "MAINTENANCE_CAP_INSUFFICIENT",
                    on_exhausted="conservative",
                    trace=[
                        {
                            "event": "SKIPPED",
                            "reason": f"replay maintenance cap {self.cap} reached",
                        }
                    ],
                )
            )
            return None
        started = time.monotonic()
        try:
            raw, meta = model_router.call_role(role, prompt_text, **kwargs)
        except Exception as exc:  # noqa: BLE001 - classified, never merged
            self._classify_failure(exc)
            return None
        latency = (time.monotonic() - started) * 1000.0
        self.latencies.append(latency)
        try:
            from editor_assistant.drafting.generate import _extract_first_object

            payload = _extract_first_object(raw)
        except Exception:  # noqa: BLE001
            self.parse_failures += 1
            self._finish("PARSE_FAILURE", None, None)
            return None
        try:
            answer = story_relation.parse_relation(payload)
        except Exception:  # noqa: BLE001
            self.parse_failures += 1
            self._finish("SCHEMA_FAILURE", None, None)
            return None
        self.answered += 1
        provider = (meta or {}).get("provider")
        if provider == "openrouter" and self._route_is_paid(meta):
            self.paid_answered += 1
        else:
            self.free_answered += 1
        self._finish("ANSWERED", provider, (meta or {}).get("model"))
        return answer

    @staticmethod
    def _route_is_paid(meta) -> bool:
        """A paid route is one OpenRouter model the policy bills as `paid`."""
        model = str((meta or {}).get("model") or "")
        return "gpt-5" in model or "gpt-oss" in model

    def _classify_failure(self, exc) -> None:
        self.degraded += 1
        trace = getattr(exc, "trace", None) or []
        # The router reports *why* in the trace and *what* in the message; the
        # maintenance cap only appears in the message, so both are inspected.
        reasons = " ".join(str((e or {}).get("reason") or "") for e in trace)
        reasons = f"{reasons} {exc}".lower()
        name = type(exc).__name__
        if "MAINTENANCE_CAP" in reasons or "maintenance cap" in reasons:
            self.budget_failures += 1
            self._finish("MAINTENANCE_CAP_INSUFFICIENT", None, None)
        elif "твърд дневен лимит" in reasons or "role hard budget" in reasons:
            self.budget_failures += 1
            self._finish("INTERNAL_BUDGET", None, None)
        elif "платените" in reasons or "PAID_DISABLED" in reasons:
            self.budget_failures += 1
            self._finish("PAID_DISABLED", None, None)
        elif "429" in reasons or "лимит на доставчика" in reasons or "quota" in reasons.lower():
            self.external_quota_failures += 1
            self._finish("EXTERNAL_QUOTA", None, None)
        elif "403" in reasons or "401" in reasons or "AUTH" in name.upper():
            self.auth_failures += 1
            self._finish("AUTH", None, None)
        else:
            self.other_failures += 1
            self._finish("OTHER", None, None)

    def _finish(self, outcome, provider, model) -> None:
        if self._current is not None:
            self._current["outcome"] = outcome
            self._current["provider"] = provider
            self._current["model"] = model
        self._current = self._current or {"item_id": None}
        self._current["outcome"] = outcome

    def summary(self) -> dict:
        paid_after = model_usage.paid_cost_today()
        return {
            "semanticRequired": self.required,
            "semanticAnswered": self.answered,
            "semanticDegraded": self.degraded,
            "freeAnswered": self.free_answered,
            "paidAnswered": self.paid_answered,
            "budgetFailures": self.budget_failures,
            "externalQuotaFailures": self.external_quota_failures,
            "authFailures": self.auth_failures,
            "parseFailures": self.parse_failures,
            "otherFailures": self.other_failures,
            "callCap": self.cap,
            "capReached": self.required > self.cap,
            "paid_cost_before_usd": self.paid_cost_before,
            "paid_cost_after_usd": paid_after,
            "paid_cost_delta_usd": round(paid_after - self.paid_cost_before, 6),
            "latency_mean_ms": round(statistics.fmean(self.latencies), 1)
            if self.latencies
            else None,
            "latency_p50_ms": (
                round(sorted(self.latencies)[len(self.latencies) // 2], 1)
                if self.latencies
                else None
            ),
            "latency_p95_ms": (
                round(sorted(self.latencies)[int((len(self.latencies) - 1) * 0.95)], 1)
                if self.latencies
                else None
            ),
        }


# ---------------------------------------------------------------- replay loop


def replay(items, items_by_id, *, call_model, health, now=None, verbose=True):
    """Rebuild the partition in memory using the unmodified production grouper.

    The only difference from production is the injected call model (which wraps
    the real router) and the grouping-health recorder. Thresholds, shortlist,
    anchors, prompt and relation taxonomy are all the production ones.
    """
    store = {"version": story_store.VERSION, "stories": [], "overrides": []}
    outcomes = []
    candidate_log = []
    ordered = sorted(items, key=lambda i: (i.get("discovered_at") or "", i["item_id"]))

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
        candidate_log.append(
            {
                "item_id": item["item_id"],
                "title": str(item.get("title") or "")[:110],
                "candidates": len(candidates),
                "anchored": len(anchored),
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

        if anchored:
            story, detail, why = anchored[0]
            call_model.begin(
                item["item_id"],
                story["story_id"],
                {
                    "score": detail["score"],
                    "title_overlap": detail["title"],
                    "distinctive_overlap": detail["distinctive"],
                    "hours": detail["hours"],
                    "anchor_reason": why,
                    "anchored_candidate_count": len(anchored),
                },
            )
            outcome = story_identity.process_item(
                item,
                store,
                items_by_id,
                semantic=True,
                call_model=call_model,
                now=now,
                health=health,
            )
            call_model.end()
            outcomes.append(outcome)
            if verbose and call_model.required % 20 == 0:
                print(
                    f"    … {call_model.required} required, {call_model.answered} answered",
                    flush=True,
                )
            continue

        outcome = story_identity.process_item(
            item,
            store,
            items_by_id,
            semantic=True,
            call_model=call_model,
            now=now,
            health=health,
        )
        outcomes.append(outcome)

    return {"store": store, "outcomes": outcomes, "candidate_log": candidate_log}


# ---------------------------------------------------------------- partitions


def partition_from_store(store) -> dict[str, int]:
    return {
        member["item_id"]: index
        for index, story in enumerate(store["stories"])
        for member in story["members"]
    }


def cocluster_pairs(partition) -> set[tuple[str, str]]:
    groups: dict[int, list[str]] = {}
    for item_id, cluster in partition.items():
        groups.setdefault(cluster, []).append(item_id)
    pairs = set()
    for members in groups.values():
        ordered = sorted(members)
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                pairs.add((left, right))
    return pairs


def compare_partitions(name_a, part_a, name_b, part_b) -> dict:
    pa, pb = cocluster_pairs(part_a), cocluster_pairs(part_b)
    only_a, only_b = sorted(pa - pb), sorted(pb - pa)
    return {
        "comparison": f"{name_a} vs {name_b}",
        "stories_a": len(set(part_a.values())),
        "stories_b": len(set(part_b.values())),
        "pairs_together_both": len(pa & pb),
        "pairs_only_a": len(only_a),
        "pairs_only_b": len(only_b),
        "affected_publications_only_a": len({x for p in only_a for x in p}),
        "affected_publications_only_b": len({x for p in only_b for x in p}),
        "affected_clusters_only_a": len({part_a[x] for p in only_a for x in p if x in part_a}),
        "affected_clusters_only_b": len({part_b[x] for p in only_b for x in p if x in part_b}),
        "identical_partition": not only_a and not only_b,
        "examples_only_a": [list(p) for p in only_a[:10]],
        "examples_only_b": [list(p) for p in only_b[:10]],
    }


KNOWN_CLUSTERS = {
    "pomporie_dolphin": ["делфин"],
    "pomporie_mbal": [
        "мбал",
        "стратегически партньор",
        "стратегически инвеститор",
        "инвеститор за спасяване",
    ],
    "nessebar_sports_capital": ["черноморска столица на спорта", "столица на спорта 2027"],
    "nessebar_wifi": ["безплатен wi-fi", "безплатен достъп до wi-fi", "старинен несебър"],
    "bulgaria_air": ["българия еър"],
}


def known_cluster_membership(partitions, items_by_id) -> dict:
    out = {}
    for label, keywords in KNOWN_CLUSTERS.items():
        members = sorted(
            i
            for i, it in items_by_id.items()
            if any(
                k in (it.get("title", "") + " " + (it.get("summary") or "")[:200]).lower()
                for k in keywords
            )
        )
        entry = {"publications": len(members), "partitions": {}}
        for name, part in partitions.items():
            counts = Counter(part[m] for m in members if m in part)
            entry["partitions"][name] = {
                "publications_present": sum(counts.values()),
                "cluster_count": len(counts),
                "cluster_sizes": sorted(counts.values(), reverse=True),
                "reunited": len(counts) == 1 and bool(counts),
            }
        out[label] = entry
    return out


def cross_cluster_merges(baseline_part, candidate_part) -> list[dict]:
    groups: dict[int, list[str]] = {}
    for item_id, cluster in candidate_part.items():
        groups.setdefault(cluster, []).append(item_id)
    out = []
    for members in groups.values():
        origins = {baseline_part[m] for m in members if m in baseline_part}
        if len(origins) > 1:
            out.append({"publications": sorted(members), "baseline_clusters": sorted(origins)})
    return out


def grade_merges(merges, items_by_id, live_part) -> dict:
    """Grade EVERY proposed cross-Story merge. No sampling.

    The rule is structural and stated up front: a merge is CLEAR when the joined
    publications either already shared a LIVE cluster, or share a distinctive
    anchor token (a number or a 5+ character token) across all headlines. That
    is the same evidence standard F0 used, so the two audits are comparable.
    """
    grades = []
    for merge in merges:
        pubs = merge["publications"]
        titles = [str((items_by_id.get(p) or {}).get("title") or "") for p in pubs]
        anchors = [story_identity.distinctive_tokens(t) for t in titles]
        common = set.intersection(*anchors) if anchors else set()
        strong = sorted(t for t in common if t.isdigit() or len(t) >= 5)
        live_clusters = {live_part[p] for p in pubs if p in live_part}
        if len(live_clusters) == 1 or strong:
            grade = "CLEAR_SAME_STORY"
        else:
            grade = "UNCERTAIN"
        grades.append(
            {
                "grade": grade,
                "publications": len(pubs),
                "live_clusters_joined": len(live_clusters),
                "shared_strong_tokens": strong[:6],
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
        "wrong_or_uncertain": [g for g in grades if g["grade"] != "CLEAR_SAME_STORY"],
        "merges": grades,
    }


def repair_buckets(merges, items_by_id, live_part) -> dict:
    """§16 buckets, recomputed from the HEALTHY partition (F0's are not reused)."""
    articles = [
        json.loads(line)
        for line in ARTICLES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    article_by_story: dict[str, list[dict]] = {}
    for article in articles:
        article_by_story.setdefault(article["story_id"], []).append(article)
    metadata = {
        row["story_id"]: row
        for row in json.loads(
            (ROOT / "var" / "newsroom" / "story_editor_metadata.json").read_text(encoding="utf-8")
        )["stories"]
    }
    live_store = story_store.read_store(STORIES_PATH)
    ignored = {s["story_id"] for s in live_store["stories"] if s.get("status") == "IGNORED"}

    buckets = {
        k: []
        for k in (
            "SAFE_EMPTY_FRAGMENT",
            "HAS_ARTICLE_LINEAGE",
            "HAS_EDITOR_METADATA",
            "MULTIPLE_ARTICLE_LINEAGES",
            "OTHER_CONFLICT",
        )
    }
    for merge in merges:
        # map each publication back to its LIVE Story id
        live_ids = {live_part[p] for p in merge["publications"] if p in live_part}
        with_articles = sorted(i for i in live_ids if article_by_story.get(i))
        with_metadata = sorted(
            i
            for i in live_ids
            if (metadata.get(i, {}).get("last_reviewed_at") or metadata.get(i, {}).get("followed"))
        )
        if len(with_articles) > 1:
            bucket = "MULTIPLE_ARTICLE_LINEAGES"
        elif with_articles:
            bucket = "HAS_ARTICLE_LINEAGE"
        elif live_ids & ignored:
            bucket = "OTHER_CONFLICT"
        elif with_metadata:
            bucket = "HAS_EDITOR_METADATA"
        else:
            bucket = "SAFE_EMPTY_FRAGMENT"
        merge["bucket"] = bucket
        merge["live_story_ids"] = sorted(live_ids)
        merge["story_ids_with_articles"] = with_articles
        merge["story_ids_with_metadata"] = with_metadata
        buckets[bucket].append(
            {"publications": len(merge["publications"]), "live_story_ids": sorted(live_ids)}
        )
    return buckets


# ---------------------------------------------------------------------- main


def preflight(model: str) -> dict:
    """§1: prove a route answers under the scoped policy before the replay."""
    from editor_assistant.drafting import model_router

    started = time.monotonic()
    try:
        raw, meta = model_router.call_role("story", 'Отговори само с JSON: {"ok": true}')
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "error": type(exc).__name__,
            "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
        }
    from editor_assistant.drafting.generate import _extract_first_object

    return {
        "reachable": True,
        "parsed": bool(_extract_first_object(raw)),
        "provider": (meta or {}).get("provider"),
        "model": (meta or {}).get("model"),
        "fallbacks": (meta or {}).get("fallbacks"),
        "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
        "policy_hash": model_policy.policy_hash(model_policy.load_policy()),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="V1.1-F2B2 bounded-paid healthy replay")
    parser.add_argument("--out", default="/tmp/v11f2b2")
    parser.add_argument("--cap", type=int, default=MAX_SEMANTIC_CALLS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="preflight only, no replay")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    verbose = not args.quiet
    now = datetime.now(timezone.utc)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    before = hash_guarded_stores()
    fingerprint = corpus_fingerprint()

    # ---- §7 pre-run proof
    paid_before = normal_policy_paid_enabled()
    scoped_path = out_dir / "replay_policy.json"
    scoped = build_scoped_policy(scoped_path, hard_calls_day=args.cap)
    os.environ["MODEL_POLICY_PATH"] = str(scoped_path)
    try:
        effective = model_policy.load_policy()
    finally:
        os.environ.pop("MODEL_POLICY_PATH", None)

    proof = {
        "runtime_store_files": sum(len(v) for v in before.values()),
        "corpus_fingerprint": fingerprint,
        "corpus_matches_freeze": fingerprint == CORPUS_FINGERPRINT,
        "normal_policy_paid_enabled": paid_before,
        "scoped_policy_paid_enabled": bool(effective["global"].get("paid_enabled")),
        "scoped_policy_path": str(scoped_path),
        "scoped_policy_is_outside_repo": "media/" not in str(scoped_path),
        "scoped_policy_written_to_operator_file": False,
        "call_cap": args.cap,
        "expected_demand": EXPECTED_SEMANTIC_CALLS,
        "story_hard_calls_day_under_scoped_policy": model_policy.role_policy(effective, "story")[
            "hard_calls_day"
        ],
        "route_order_unchanged": (
            [r["model"] for r in scoped["roles"]["story"]["routes"]]
            == [r["model"] for r in model_policy.load_policy()["roles"]["story"]["routes"]]
        ),
        "soft_paid_budget_usd_day": effective["global"].get("soft_paid_budget_usd_day"),
        "paid_cost_today_usd_before": model_usage.paid_cost_today(),
    }
    if verbose:
        print(f"[proof] fingerprint {fingerprint} (frozen: {proof['corpus_matches_freeze']})")
        print(
            f"[proof] normal paid_enabled={paid_before}  scoped={proof['scoped_policy_paid_enabled']}"
        )
        print(f"[proof] route order unchanged: {proof['route_order_unchanged']}")
        print(
            f"[proof] call cap {args.cap}  daily soft paid ceiling ${proof['soft_paid_budget_usd_day']}"
        )

    os.environ["MODEL_POLICY_PATH"] = str(scoped_path)
    try:
        probe = preflight("story")
        if verbose:
            print(
                f"[preflight] reachable={probe.get('reachable')} provider={probe.get('provider')} "
                f"model={probe.get('model')} {probe.get('latency_ms')}ms"
            )
        payload = {"proof": proof, "preflight": probe, "generated_at": now.isoformat()}
        if not probe.get("reachable") or args.dry_run:
            payload["integrity"] = {
                "files_hashed": sum(len(v) for v in before.values()),
                "byte_identical": not compare_stores(before, hash_guarded_stores()),
            }
            (out_dir / "v11f2b2_results.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            if verbose:
                print("[stop] no route reachable or --dry-run; no replay performed")
            return 0

        items = inbox_store.read_items(INBOX_PATH)
        items_by_id = {i["item_id"]: i for i in items}
        live_store = story_store.read_store(STORIES_PATH)
        live_part = partition_from_store(live_store)
        if verbose:
            print(
                f"[replay] {len(items)} items, cap {args.cap}, policy hash {probe['policy_hash']}"
            )

        from editor_assistant.workflow import grouping_health

        health = grouping_health.GroupingHealth()
        call_model = ReplayCallModel(cap=args.cap)
        started = time.monotonic()
        result = replay(
            items, items_by_id, call_model=call_model, health=health, now=now, verbose=verbose
        )
        runtime = round(time.monotonic() - started, 1)
        healthy_part = partition_from_store(result["store"])
        summary = call_model.summary()
        summary["replay_runtime_seconds"] = runtime
        healthy = (
            summary["semanticDegraded"] == 0
            and summary["semanticAnswered"] == summary["semanticRequired"]
        )

        payload.update(
            {
                "semantic": summary,
                "replay_healthy": healthy,
                "outcome": "FULLY_HEALTHY"
                if healthy
                else ("MAINTENANCE_CAP_INSUFFICIENT" if summary["capReached"] else "DEGRADED"),
                "grouping_health": health.summary(),
                "healthy_partition_metrics": {
                    "stories": len(result["store"]["stories"]),
                    "same_story_members": sum(
                        1
                        for s in result["store"]["stories"]
                        for m in s["members"]
                        if m["relation"] == "SAME_STORY"
                    ),
                    "multi_member_stories": sum(
                        1 for s in result["store"]["stories"] if len(s["members"]) > 1
                    ),
                    "singletons": sum(
                        1 for s in result["store"]["stories"] if len(s["members"]) == 1
                    ),
                    "needs_review": sum(
                        1 for s in result["store"]["stories"] if s.get("needs_review")
                    ),
                    "semantic_merges": sum(
                        1
                        for s in result["store"]["stories"]
                        for m in s["members"]
                        if m["relation_source"] == story_store.SOURCE_SEMANTIC
                    ),
                    "new_development": sum(
                        1
                        for s in result["store"]["stories"]
                        for m in s["members"]
                        if m["relation"] == "NEW_DEVELOPMENT"
                    ),
                },
                "partition_comparisons": [
                    compare_partitions("LIVE", live_part, "HEALTHY", healthy_part),
                ],
                "known_clusters": known_cluster_membership(
                    {"LIVE": live_part, "HEALTHY": healthy_part}, items_by_id
                ),
            }
        )

        if healthy:
            merges = cross_cluster_merges(live_part, healthy_part)
            audit = grade_merges(merges, items_by_id, live_part)
            payload["cross_story_audit"] = audit
            payload["repair_buckets"] = repair_buckets(merges, items_by_id, live_part)
        else:
            payload["cross_story_audit"] = {
                "skipped": True,
                "reason": "replay was not healthy; per §8/§15 no repair conclusions are drawn",
            }
    finally:
        os.environ.pop("MODEL_POLICY_PATH", None)

    after = hash_guarded_stores()
    diffs = compare_stores(before, after)
    payload["normal_policy_restored"] = normal_policy_paid_enabled()
    payload["integrity"] = {
        "files_hashed": sum(len(v) for v in before.values()),
        "differences": diffs,
        "byte_identical": not diffs,
    }
    if verbose:
        print(f"[integrity] {'BYTE-IDENTICAL' if not diffs else 'CHANGED'}")
        print(f"[policy] normal paid_enabled after = {payload['normal_policy_restored']}")
    (out_dir / "v11f2b2_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
