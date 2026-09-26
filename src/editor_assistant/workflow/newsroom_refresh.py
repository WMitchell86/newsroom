"""B4B — the one editor-facing newsroom refresh command («Обнови»).

**Orchestration only.** This module adds no collection, ingestion,
deduplication, story-identity, provenance, quota or persistence logic of its
own. Every step delegates to the existing, already-exercised pipeline:

* `newsroom_run.collect`  — registry -> collectors -> dedup -> inbox + health
* `story_identity.update` — inbox items -> canonical Stories
* `source_health`         — per-source health and last-run records
* `inbox_store` / `story_store` / `live_store` — the validated atomic writes

The editor sees ONE action. The stages stay internal: what leaves this module
is completion metadata, and the canonical Today projection is re-read from the
stores after the run. Nothing here creates a Research, Case, Article or Idea
object, and Story Research (B4A) is never called — «Обнови» discovers
newsroom material broadly from configured sources, «Проучи още» answers the
open questions inside one Story.

Partial failure is the pipeline's own behaviour, not a new policy: a source
that fails is reported and the run continues, so successful material is always
preserved. What this module decides is only *when a failure is worth the
editor's attention* (see `today_problems`).
"""

from __future__ import annotations

import hashlib
import threading

from editor_assistant.workflow import newsroom_run, source_health, sources_registry, story_identity

#: A failed configured source is actionable newsroom news up to this many rows;
#: beyond that the operator belongs in source diagnostics, not in «Днес».
MAX_TODAY_PROBLEMS = 5


class RefreshUnavailable(RuntimeError):
    """Refresh cannot run safely right now; the reason is never invented."""


class RefreshBusy(RefreshUnavailable):
    """Another refresh already owns the canonical intake/story stores."""

    def __init__(self, active_token: str = "") -> None:
        super().__init__("вече тече обновяване на новините")
        self.active_token = str(active_token or "")


#: In-process guard around the canonical stores. It complements (never
#: replaces) `newsroom_run`'s own `collect.lock`, which is what stops a cron
#: run and this command from interleaving inbox writes.
_GUARD = threading.RLock()
_ACTIVE_TOKEN = ""


def acquire(token: str) -> None:
    global _ACTIVE_TOKEN
    with _GUARD:
        if _ACTIVE_TOKEN:
            raise RefreshBusy(_ACTIVE_TOKEN)
        _ACTIVE_TOKEN = str(token)


def release(token: str) -> None:
    global _ACTIVE_TOKEN
    with _GUARD:
        if _ACTIVE_TOKEN == str(token):
            _ACTIVE_TOKEN = ""


def active_token() -> str:
    with _GUARD:
        return _ACTIVE_TOKEN


def newsroom_paths(root=None) -> dict:
    """The canonical runtime files, resolved exactly like the collector's."""
    base = newsroom_run.newsroom_dir(root)
    return {
        "root": base,
        "sources": base / "sources.json",
        "inbox": base / "inbox.jsonl",
        "stories": base / "stories.json",
        "health": base / "source_health.json",
        "blocked": base / "blocked_domains.json",
        "last_run": base / "last_run.json",
    }


def _problem_id(source_id: str) -> str:
    return "problem_" + hashlib.sha256(f"source:{source_id}".encode()).hexdigest()[:16]


def _problem(source_id: str, name: str, consequence: str) -> dict:
    return {
        "id": _problem_id(source_id),
        "title": f"Източникът „{name}“ не се обнови",
        "consequence": consequence,
        "label": "Прегледай източниците",
        "target": "/settings",
    }


def today_problems(*, root=None) -> list[dict]:
    """Actionable newsroom problems, derived read-only from canonical stores.

    A failure qualifies only when it has a concrete consequence and a possible
    next action, so «Днес» never becomes a telemetry feed:

    * the source is **active** — a muted or disabled source is the operator's
      own decision, not a problem;
    * its collector is **wired** — a declared capability gap (a `web` or
      `youtube` source) is not a newsroom failure;
    * it **worked before** and its last recorded status is now **FAILED** — a
      source that has never delivered is a configuration matter for source
      diagnostics, not lost newsroom coverage the editor must act on;
    * a source refused by the blocked policy is a deliberate rule, and an empty
      run is an honest answer.

    Everything else (transient retries, mirror duplicates, provider telemetry,
    parser detail) stays in source diagnostics. Nothing is written here and no
    attention row is persisted.
    """
    paths = newsroom_paths(root)
    try:
        rows = sources_registry.describe_all(paths["sources"], today=source_health.sofia_date())
        health = source_health.read_health(paths["health"])
    except (OSError, ValueError, sources_registry.RegistryError, source_health.HealthError):
        # A read problem is not an editorial problem; Today stays as it was.
        return []
    problems = []
    for row in rows:
        if row.get("effective_status") != "active":
            continue
        if row.get("collector") not in newsroom_run.SUPPORTED_COLLECTORS:
            continue
        record = health.get(row["source_id"]) or {}
        if record.get("last_status") != source_health.FAILED:
            continue
        if not record.get("last_success_at"):
            # Never delivered: there is no lost coverage to act on yet.
            continue
        problems.append(
            _problem(
                row["source_id"],
                row.get("name") or row["source_id"],
                "Източникът е работил, но при последното обновяване не е дал материал. "
                "Новините от него може да липсват от Днес.",
            )
        )
        if len(problems) >= MAX_TODAY_PROBLEMS:
            break
    return problems


def capability(*, root=None) -> dict:
    """Whether a refresh is currently possible, derived from real state."""
    paths = newsroom_paths(root)
    try:
        rows = sources_registry.describe_all(paths["sources"], today=source_health.sofia_date())
    except (OSError, ValueError, sources_registry.RegistryError):
        return {"canRefresh": False, "reason": "unreadable_sources"}
    if not [row for row in rows if row.get("effective_status") == "active"]:
        return {"canRefresh": False, "reason": "no_active_sources"}
    return {"canRefresh": True, "reason": ""}


def refresh_newsroom(
    *,
    root=None,
    now=None,
    fetch_bytes=None,
    news_provider=None,
    semantic=True,
    call_model=None,
) -> dict:
    """Collect, ingest and group through the existing pipeline, once.

    Ordering is the pipeline's, not a new workflow: availability is checked,
    the existing collector runs (a failing source never stops the run), the
    newly ingested material is grouped into canonical Stories by the existing
    identity service, and the editor-facing consequence is derived from the
    source-health records the collector has just written.

    Returns completion metadata only — no scraped documents, provider traces,
    parser logs or file paths. The caller re-reads the canonical Today
    projection afterwards; this is not the authority on it.
    """
    paths = newsroom_paths(root)
    state = capability(root=paths["root"])
    if not state["canRefresh"]:
        raise RefreshUnavailable(
            "няма активни източници за обновяване"
            if state["reason"] == "no_active_sources"
            else "източниците не могат да бъдат прочетени"
        )

    summary = newsroom_run.collect(
        dry_run=False,
        path=paths["sources"],
        store=paths["inbox"],
        health_path=paths["health"],
        blocked_path=paths["blocked"],
        last_run_path=paths["last_run"],
        root=paths["root"],
        fetch_bytes=fetch_bytes,
        news_provider=news_provider,
        now=now,
        use_lock=True,
    )
    if summary.get("locked"):
        # The existing collection lock is held (cron, operator CLI). Reporting
        # success would falsely claim the newsroom was refreshed.
        raise RefreshBusy()

    stories = story_identity.update(
        inbox=paths["inbox"],
        stories=paths["stories"],
        dry_run=False,
        semantic=semantic,
        call_model=call_model,
        blocked_path=paths["blocked"],
        now=now,
    )
    # The collection summary is already on disk by this point; the Story count
    # only exists after the identity stage, so it is merged into that same
    # latest-run record. This is the only extra state the refresh adds.
    source_health.record_run_stories(stories.get("new_stories", 0), path=paths["last_run"])
    # V1.1-F2A: the same latest-run record carries whether this run's identity
    # stage could classify everything it needed to. Without it a run that kept a
    # third of the corpus separate looked exactly like a run where nothing
    # interesting happened, and the problem surfaced days later as duplicates.
    grouping = stories.get("grouping")
    if isinstance(grouping, dict):
        source_health.record_run_grouping(grouping, path=paths["last_run"])

    return {
        "collected": int(summary.get("collected", 0)),
        "new": int(summary.get("new", 0)),
        "duplicate": int(summary.get("duplicate", 0)),
        "failedSources": int(summary.get("failed", 0)),
        "stories": {
            "scanned": int(stories.get("scanned", 0)),
            "newStories": int(stories.get("new_stories", 0)),
            "needsReview": int(stories.get("needs_review", 0)),
        },
        "problems": today_problems(root=paths["root"]),
        "finishedAt": str(summary.get("finished_at") or ""),
    }
