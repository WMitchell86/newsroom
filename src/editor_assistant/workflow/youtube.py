"""Canonical YouTube source identity (M3B Part B/C).

A URL is an *intake request*, not a story. This module turns any common YouTube
URL form into a stable identity (`video_id` + deterministic canonical URL), and
resolves only the metadata needed for editorial provenance. It never invents
metadata: unresolved fields stay `None` and the transcript can still be
processed from `video_id` + canonical URL + raw SRT alone.

Identity is the **video id**, never the title or any other mutable field.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from editor_assistant.workflow.transcripts import TRUST_AUTO_CAPTION

#: Hosts that can carry a YouTube video id.
YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
        "www.youtu.be",
    }
)

#: YouTube video ids are 11 chars of [A-Za-z0-9_-].
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

#: Path prefixes whose next segment is the video id.
_ID_PATH_PREFIXES = ("live", "shorts", "embed", "v", "watch")


class YouTubeSourceError(ValueError):
    """The URL cannot be confidently normalized to a YouTube video id."""


@dataclass(frozen=True)
class YouTubeSource:
    """Canonical, deterministic source identity for one YouTube video."""

    video_id: str
    canonical_url: str
    original_url: str
    title: str | None = None
    channel: str | None = None
    published_at: str | None = None
    retrieved_at: str | None = None
    duration_seconds: int | None = None
    language: str | None = None
    transcript_trust_level: str = TRUST_AUTO_CAPTION
    transcript_origin: str | None = None
    metadata_origin: str | None = None

    def as_dict(self):
        return asdict(self)


def _with_scheme(url):
    url = (url or "").strip()
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url.lstrip("/")
    return url


def parse_video_id(url):
    """Extract a stable video id from a common YouTube URL form.

    Supports `watch?v=`, `youtu.be/`, `/live/`, `/shorts/`, `/embed/`, `/v/`
    (and `watch/<id>`). Anything that cannot be normalized confidently raises
    `YouTubeSourceError` - malformed input is rejected, never guessed.
    """
    cleaned = _with_scheme(url)
    parsed = urllib.parse.urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise YouTubeSourceError(f"not a YouTube host: {host or url!r}")
    segments = [seg for seg in parsed.path.split("/") if seg]

    if host.endswith("youtu.be"):
        candidate = segments[0] if segments else ""
    elif segments[:1] == ["watch"]:
        candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    elif len(segments) >= 2 and segments[0] in _ID_PATH_PREFIXES:
        candidate = segments[1]
    else:
        raise YouTubeSourceError(f"unsupported YouTube URL path: {parsed.path!r}")

    candidate = candidate.strip()
    if not _VIDEO_ID_RE.match(candidate):
        raise YouTubeSourceError(f"invalid video id: {candidate!r}")
    return candidate


def canonical_url(video_id):
    """Deterministic canonical URL for a validated video id."""
    if not _VIDEO_ID_RE.match(video_id or ""):
        raise YouTubeSourceError(f"invalid video id: {video_id!r}")
    return f"https://www.youtube.com/watch?v={video_id}"


def identify(url, *, metadata=None, retrieved_at=None):
    """Build a `YouTubeSource`; equivalent URL forms deduplicate by video id."""
    video_id = parse_video_id(url)
    source = YouTubeSource(
        video_id=video_id,
        canonical_url=canonical_url(video_id),
        original_url=(url or "").strip(),
        retrieved_at=retrieved_at or _now(),
    )
    return _apply_metadata(source, metadata or {})


def _apply_metadata(source, metadata):
    """Overlay resolved metadata without inventing missing values."""
    return YouTubeSource(
        video_id=source.video_id,
        canonical_url=source.canonical_url,
        original_url=source.original_url,
        title=metadata.get("title") or source.title,
        channel=metadata.get("channel") or source.channel,
        published_at=metadata.get("published_at") or source.published_at,
        retrieved_at=source.retrieved_at,
        duration_seconds=metadata.get("duration_seconds", source.duration_seconds),
        language=metadata.get("language") or source.language,
        transcript_trust_level=source.transcript_trust_level,
        transcript_origin=source.transcript_origin,
        metadata_origin=metadata.get("origin"),
    )


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _published_at(upload_date):
    if not upload_date:
        return None
    text = str(upload_date).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def resolve_metadata(url, *, extractor=None):
    """Resolve source metadata with the least fragile available mechanism.

    Uses `yt_dlp`'s metadata extractor without downloading the media. Metadata
    failure is explicit (`origin` says why) and never blocks transcript
    processing. `extractor` is the test seam.
    """
    if extractor is None:
        try:
            import yt_dlp
        except ImportError:
            return {"origin": "yt_dlp:unavailable", "reason": "yt_dlp is not installed"}
        opts = {"quiet": True, "skip_download": True, "no_warnings": True}

        def extractor(target):  # pragma: no cover - live network path
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(target, download=False)

    try:
        info = extractor(_with_scheme(url))
    except Exception as exc:  # noqa: BLE001 - metadata is optional, never fatal
        return {"origin": "yt_dlp:error", "reason": f"{type(exc).__name__}: {exc}"}
    if not isinstance(info, dict) or not info.get("id"):
        return {"origin": "yt_dlp:invalid", "reason": "extractor returned no video id"}
    return {
        "origin": "yt_dlp",
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "published_at": _published_at(info.get("upload_date")),
        "duration_seconds": int(info["duration"]) if info.get("duration") else None,
        "language": info.get("language"),
    }
