"""Strict canonical Story-owned research basis."""

from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from editor_assistant.workflow import live_store

VERSION = 1
STORY_ID_RE = re.compile(r"s[a-zA-Z0-9_-]{1,127}\Z")
SOURCE_ID_RE = re.compile(r"[a-zA-Z0-9_.:-]{1,128}\Z")
GAP_ID_RE = re.compile(r"gap_[a-zA-Z0-9_.:-]{1,128}\Z")
FACT_ID_RE = re.compile(r"fact_[a-zA-Z0-9_.:-]{1,160}\Z")
_LOCK = threading.RLock()


class StoryResearchStoreError(ValueError):
    pass


class StoryResearchIdentityError(StoryResearchStoreError):
    pass


def story_research_path(*, root=None):
    if root is not None:
        return Path(root) / "story_research.json"
    if os.environ.get("WB_STORY_RESEARCH_PATH"):
        return Path(os.environ["WB_STORY_RESEARCH_PATH"])
    return (
        Path(
            os.environ.get("WB_EDITORIAL_WORKFLOW_DIR")
            or (Path(__file__).resolve().parents[3] / "var/editorial_workflow")
        )
        / "story_research.json"
    )


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(v, f):
    if not isinstance(v, str) or not v.strip():
        raise StoryResearchStoreError(f"{f} must be non-empty")
    return v.strip()


def _ts(v, f):
    t = _text(v, f)
    try:
        p = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError as e:
        raise StoryResearchStoreError(f"{f} must be ISO-8601") from e
    if p.tzinfo is None:
        raise StoryResearchStoreError(f"{f} must include timezone")
    return t


def _sid(v):
    if not isinstance(v, str) or not STORY_ID_RE.fullmatch(v):
        raise StoryResearchIdentityError("invalid story_id")
    return v


def _url(value, field):
    text = _text(value, field)
    parsed = urlsplit(text)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise StoryResearchStoreError(f"{field} must be an absolute http(s) URL")
    return text


def _source(v):
    if not isinstance(v, dict):
        raise StoryResearchStoreError("source must be object")
    i = _text(v.get("id"), "source.id")
    if not SOURCE_ID_RE.fullmatch(i):
        raise StoryResearchStoreError("invalid source.id")
    u = _url(v.get("url"), "source.url")
    return {
        "id": i,
        "name": _text(v.get("name"), "source.name"),
        "url": u,
        "domain": urlsplit(u).netloc,
    }


def _fact(v, ids):
    if not isinstance(v, dict):
        raise StoryResearchStoreError("fact must be object")
    i = _text(v.get("id"), "fact.id")
    if not FACT_ID_RE.fullmatch(i):
        raise StoryResearchStoreError("invalid fact.id")
    s = _text(v.get("sourceId"), "fact.sourceId")
    if s not in ids:
        raise StoryResearchIdentityError(f"unknown source: {s}")
    scope = v.get("scope", "current")
    if scope not in {"current", "background"}:
        raise StoryResearchStoreError("invalid fact.scope")
    return {
        "id": i,
        "text": _text(v.get("text"), "fact.text"),
        "sourceId": s,
        "locator": _text(v.get("locator"), "fact.locator"),
        "scope": scope,
    }


def _gap(v):
    if not isinstance(v, dict):
        raise StoryResearchStoreError("gap must be object")
    i = _text(v.get("id"), "gap.id")
    if not GAP_ID_RE.fullmatch(i):
        raise StoryResearchStoreError("invalid gap.id")
    k = v.get("kind", "unresolved")
    if k not in {"missing_fact", "conflict", "unresolved"}:
        raise StoryResearchStoreError("invalid gap.kind")
    if "blocking" in v and type(v["blocking"]) is not bool:
        raise StoryResearchStoreError("gap.blocking must be boolean")
    out = {
        "id": i,
        "question": _text(v.get("question"), "gap.question"),
        "kind": k,
        "blocking": v.get("blocking", False),
    }
    if v.get("reason"):
        out["reason"] = _text(v["reason"], "gap.reason")
    return out


def _row(v):
    req = {
        "story_id",
        "facts",
        "sources",
        "gaps",
        "assessed_at",
        "research_rounds",
        "operation_ids",
    }
    if not isinstance(v, dict) or set(v) != req:
        raise StoryResearchStoreError("Story research row fields mismatch")
    sources = [_source(x) for x in v["sources"]]
    ids = {x["id"] for x in sources}
    if len(ids) != len(sources):
        raise StoryResearchIdentityError("duplicate source identity")
    facts = [_fact(x, ids) for x in v["facts"]]
    gaps = [_gap(x) for x in v["gaps"]]
    if len({x["id"] for x in facts}) != len(facts) or len({x["id"] for x in gaps}) != len(gaps):
        raise StoryResearchStoreError("duplicate fact/gap id")
    n = v["research_rounds"]
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 2:
        raise StoryResearchStoreError("invalid research_rounds")
    ops = v["operation_ids"]
    if not isinstance(ops, list) or any(not isinstance(x, str) or not x for x in ops):
        raise StoryResearchStoreError("operation_ids must be strings")
    return {
        "story_id": _sid(v["story_id"]),
        "facts": sorted(facts, key=lambda x: x["id"]),
        "sources": sorted(sources, key=lambda x: x["id"]),
        "gaps": gaps,
        "assessed_at": _ts(v["assessed_at"], "assessed_at"),
        "research_rounds": n,
        "operation_ids": sorted(set(ops)),
    }


def _empty(story_id):
    return {
        "story_id": story_id,
        "facts": [],
        "sources": [],
        "gaps": [],
        "assessed_at": _now(),
        "research_rounds": 0,
        "operation_ids": [],
    }


def read_store(*, root=None):
    p = story_research_path(root=root)
    if not p.exists():
        return {"version": VERSION, "stories": []}
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StoryResearchStoreError(f"unreadable store: {e}") from e
    if (
        not isinstance(v, dict)
        or v.get("version") != VERSION
        or not isinstance(v.get("stories"), list)
    ):
        raise StoryResearchStoreError("unsupported store format")
    rows = [_row(x) for x in v["stories"]]
    if len({x["story_id"] for x in rows}) != len(rows):
        raise StoryResearchIdentityError("duplicate story_id")
    return {"version": VERSION, "stories": sorted(rows, key=lambda x: x["story_id"])}


def get_story_research(story_id, *, root=None):
    s = _sid(story_id)
    return next(
        (deepcopy(x) for x in read_store(root=root)["stories"] if x["story_id"] == s), _empty(s)
    )


def _write(v, *, root=None):
    if not isinstance(v, dict) or set(v) != {"version", "stories"}:
        raise StoryResearchStoreError("invalid store fields")
    rows = [_row(x) for x in v["stories"]]
    if len({x["story_id"] for x in rows}) != len(rows):
        raise StoryResearchIdentityError("duplicate story_id")
    live_store.atomic_write(
        story_research_path(root=root),
        json.dumps(
            {"version": VERSION, "stories": sorted(rows, key=lambda x: x["story_id"])},
            ensure_ascii=False,
            sort_keys=True,
            indent=1,
        )
        + "\n",
    )
    return {"version": VERSION, "stories": sorted(rows, key=lambda x: x["story_id"])}


def save_story_research(row, *, root=None):
    row = _row(row)
    with _LOCK:
        rows = [x for x in read_store(root=root)["stories"] if x["story_id"] != row["story_id"]] + [
            row
        ]
        out = _write({"version": VERSION, "stories": rows}, root=root)
        return next(x for x in out["stories"] if x["story_id"] == row["story_id"])


def merge_research(
    story_id,
    *,
    facts,
    sources,
    gaps,
    assessed_at=None,
    root=None,
    canonical_story=None,
    operation_id=None,
    count_round=False,
    replace_gaps=False,
):
    s = _sid(story_id)
    if not isinstance(canonical_story, dict) or canonical_story.get("story_id") != s:
        raise StoryResearchIdentityError("canonical Story proof is required")
    if not operation_id:
        raise StoryResearchStoreError("operation_id is required")
    with _LOCK:
        cur = get_story_research(s, root=root)
        sm = {x["id"]: x for x in cur["sources"]}
        fm = {x["id"]: x for x in cur["facts"]}
        gm = {} if replace_gaps else {x["id"]: x for x in cur["gaps"]}
        for raw in sources:
            x = _source(raw)
            old = sm.get(x["id"])
            if old is not None and old != x:
                raise StoryResearchIdentityError(f"ambiguous source: {x['id']}")
            sm[x["id"]] = x
        fm = {x["id"]: x for x in cur["facts"]}
        for raw in facts:
            x = _fact(raw, set(sm))
            old = fm.get(x["id"])
            if old is not None and old != x:
                raise StoryResearchIdentityError(f"ambiguous fact: {x['id']}")
            fm[x["id"]] = x
        for raw in gaps:
            x = _gap(raw)
            old = gm.get(x["id"])
            if old is not None and old != x:
                raise StoryResearchIdentityError(f"ambiguous gap: {x['id']}")
            gm[x["id"]] = x
        old_ops = set(cur["operation_ids"])
        new_op = operation_id not in old_ops
        merged = {
            "story_id": s,
            "facts": list(fm.values()),
            "sources": list(sm.values()),
            "gaps": list(gm.values()),
            "assessed_at": _ts(assessed_at or _now(), "assessed_at"),
            "research_rounds": min(2, cur["research_rounds"] + int(count_round and new_op)),
            "operation_ids": sorted(old_ops | {operation_id}),
        }
        return save_story_research(merged, root=root)
