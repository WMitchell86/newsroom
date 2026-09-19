"""Successful-stage cache for transcript discovery (M3D Part L4).

The M3D measurement showed the discovery chain is execution-stable but that
model wording variance in ONE fact paraphrase flips the angle-assessment
outcome (NO_PUBLISHABLE_ANGLE <-> RESEARCH_MORE) for the same transcript in
~1/3 of runs. L4 is the smallest permitted correction: cache the **first
successful model stages** (facts + proposals) keyed by

    transcript hash + stage version + model config fingerprint

so the same immutable evidence always reaches the downstream deterministic
gate through the same semantic inputs. Nothing about the gate, prompts,
rubric, thresholds or readiness changes; the cache stores only what a
successful run produced, never a failure (Part L4/P guarantees):

* failed or partial extraction results are never cached as success;
* version/config changes invalidate automatically (key mismatch = miss);
* an operator can intentionally bypass/re-run with `force=True`;
* cache entries are auditable JSON files under the ignored `var/` tree;
* every hit records the provenance it replayed from.

This is reuse of a successful result for the same input bytes — the harness
(M3D scoping) treats it as measurement-driven stability, not a semantic
change. Discovery semantics are untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow.live_store import atomic_write

STAGE_VERSION = "discovery-stage-cache-v1"
#: Bump when prompts/models/config that shape fact or proposal output change.
CACHE_FORMAT = 1


def transcript_hash(raw_srt):
    """Input-bytes identity (sha256 of the raw SRT), same definition as the
    intake registry — one transcript, one hash, everywhere."""
    import hashlib

    return hashlib.sha256((raw_srt or "").encode("utf-8")).hexdigest()


def cache_root(root=None):
    """Cache directory; overridable for tests (never read/write outside it)."""
    if root is not None:
        return Path(root)
    base = os.environ.get("DISCOVERY_CACHE_DIR")
    if base:
        return Path(base)
    here = Path(__file__).resolve().parents[3]
    return here / "var" / "discovery_stage_cache"


def model_config_fingerprint():
    """Config that demonstrably shapes model output (Part J observability)."""
    from editor_assistant.drafting import generate as gen

    identity = {
        "provider": gen.API_PROVIDER,
        "judge_pool": list(gen.JUDGE_MODEL_POOL),
        "temperature": gen.GENERATION_SETTINGS["temperature"],
        "max_tokens": gen.GENERATION_SETTINGS["max_tokens"],
        "thinking_budget": gen.THINKING_BUDGET,
        "stage_version": STAGE_VERSION,
        "discovery_version": _discovery_version(),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _discovery_version():
    from editor_assistant.workflow import discovery

    return discovery.PIPELINE_VERSION


def cache_key(transcript_hash):
    """Explicit cache key: input bytes + stage version + model config."""
    return f"{transcript_hash[:16]}.{model_config_fingerprint()}"


def _path(transcript_hash, root=None):
    return cache_root(root) / f"{cache_key(transcript_hash)}.json"


def load(transcript_hash, *, root=None):
    """Return the cached successful stages or None. Key mismatch = miss."""
    path = _path(transcript_hash, root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("cache_format") != CACHE_FORMAT:
        return None
    if payload.get("cache_key") != cache_key(transcript_hash):
        return None
    if payload.get("success") is not True:
        return None  # a failed/partial result is never a cache hit
    if not payload.get("facts"):
        return None
    # NOTE: an EMPTY proposal list is a legitimate successful outcome (the model
    # proposed no angle for grounded facts) and MUST still be a hit — otherwise
    # the exact zero-angle class this milestone measures would be recomputed
    # forever instead of frozen.
    for key in ("proposals", "dropped", "skips"):
        payload.setdefault(key, [])
    return payload


def store(transcript_hash, *, facts, proposals, dropped=None, skips=None, source=None, root=None):
    """Persist the first SUCCESSFUL model stages. Returns the cache path.

    `facts`/`proposals` are the exact JSON-able stage captures. `dropped`
    (gate-rejected candidates) and `skips` (per-topic execution/model-zero
    attributions) travel with them so a replayed hit keeps the same audit
    provenance as a fresh run. Refuses to store an unsuccessful outcome (no
    facts) so a model outage or a legitimate zero can never freeze itself as
    "the answer".

    A `force=True` rerun never silently replaces the previous entry: the old
    payload is kept next to the new one as `<key>.<created_at>.prev.json`,
    so the frozen snapshot and its replacement stay comparable.
    """
    if not facts:
        return None  # nothing successful to remember
    path = _path(transcript_hash, root)
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = None
        if isinstance(previous, dict) and previous.get("success") is True:
            stamp = str(previous.get("created_at") or "unknown").replace(":", "-")
            backup = path.with_name(f"{path.stem}.{stamp}.prev.json")
            if not backup.exists():
                try:
                    backup.write_text(
                        json.dumps(previous, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                        encoding="utf-8",
                    )
                except OSError:
                    pass  # the new entry still lands; provenance is best-effort
    payload = {
        "cache_format": CACHE_FORMAT,
        "cache_key": cache_key(transcript_hash),
        "stage_version": STAGE_VERSION,
        "model_config_fp": model_config_fingerprint(),
        "discovery_version": _discovery_version(),
        "transcript_hash": transcript_hash,
        "success": True,
        "facts": facts,
        "proposals": proposals,
        "dropped": list(dropped or []),
        "skips": list(skips or []),
        "source": source or {},
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    return path


def cached_result_status(cached):
    """Human-auditable provenance line for a cache hit."""
    if not cached:
        return "MISS"
    return (
        f"HIT stage_version={cached.get('stage_version')} "
        f"model_config={cached.get('model_config_fp')} "
        f"created_at={cached.get('created_at')}"
    )
