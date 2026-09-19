"""YouTube intake registry + raw transcript store (M3B Part F).

A small deterministic, file-backed store - not a database. Two guarantees:

* raw transcripts are content-addressed (`<video_id>.<sha256[:8]>.srt`), so a
  **different** transcript for the same video never overwrites an earlier one;
* the registry is written atomically and only *after* a transcript is validated,
  so an interrupted transcription never leaves a successful registry row.

The registry keeps a per-video `versions` history plus a current pointer.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow.live_store import atomic_write

ROOT = Path(__file__).resolve().parents[3]


def intake_root(root=None):
    """Runtime root; overridable for tests (never read/write outside it)."""
    if root is not None:
        return Path(root)
    return Path(os.environ.get("YOUTUBE_INTAKE_DIR") or (ROOT / "var" / "youtube_intake"))


def registry_path(root=None):
    return intake_root(root) / "registry.json"


def transcripts_dir(root=None):
    return intake_root(root) / "transcripts"


def artifacts_dir(root=None):
    return intake_root(root) / "artifacts"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def transcript_hash(raw_srt):
    return hashlib.sha256((raw_srt or "").encode("utf-8")).hexdigest()


def read_registry(root=None):
    path = registry_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(registry, root=None):
    """Atomic registry write (temp file + os.replace + fsync)."""
    atomic_write(
        registry_path(root),
        json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
    )


def store_transcript(video_id, raw_srt, root=None):
    """Content-address the raw SRT; returns (path, sha256). Never overwrites."""
    digest = transcript_hash(raw_srt)
    directory = transcripts_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{video_id}.{digest[:8]}.srt"
    if not path.exists():
        atomic_write(path, raw_srt)
    return path, digest


def reusable_record(registry, video_id, *, force=False):
    """Return the cached record when it can be reused, else None.

    Same video + same transcript hash reuses; `force=True` forces re-transcription.
    """
    if force:
        return None
    record = registry.get(video_id)
    if not record:
        return None
    transcript_file = record.get("transcript_file")
    if not transcript_file or not Path(transcript_file).exists():
        return None
    return record


def upsert_record(
    registry,
    *,
    video_id,
    canonical_url,
    transcript_file,
    transcript_hash_value,
    transcriber_identity,
    language=None,
    trust_level=None,
    discovery_artifact=None,
    source=None,
    timestamp=None,
):
    """Insert/update one registry row, preserving transcript version history."""
    timestamp = timestamp or _now()
    record = registry.get(video_id) or {
        "video_id": video_id,
        "canonical_url": canonical_url,
        "created_at": timestamp,
        "versions": [],
    }
    versions = list(record.get("versions", []))
    known = {v.get("transcript_hash") for v in versions}
    if transcript_hash_value not in known:
        versions.append(
            {
                "transcript_hash": transcript_hash_value,
                "transcript_file": transcript_file,
                "transcriber_identity": transcriber_identity,
                "language": language,
                "trust_level": trust_level,
                "created_at": timestamp,
            }
        )
    record.update(
        {
            "video_id": video_id,
            "canonical_url": canonical_url,
            "transcript_file": transcript_file,
            "transcript_hash": transcript_hash_value,
            "transcriber_identity": transcriber_identity,
            "language": language,
            "trust_level": trust_level,
            "last_checked_at": timestamp,
            "discovery_artifact": discovery_artifact,
            "versions": versions,
        }
    )
    if source is not None:
        record["source"] = source.as_dict() if hasattr(source, "as_dict") else dict(source)
    registry[video_id] = record
    return record
