"""Transcriber adapter boundary (M3B Part D).

No transcriber existed in the repository, so this is a small adapter over the
transcriber that *is* actually available on the machine: **yt-dlp**
(`--skip-download --write-auto-subs --convert-subs srt`). It is a boundary, not
a new transcription implementation.

The raw timestamped SRT stays the authoritative machine evidence (Part E). This
module contains no article/editorial logic and never collapses infrastructure
failure into "no useful story": every failure maps to an explicit category.

`runner` is the test seam - the unit suite never shells out to yt-dlp.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import transcripts as T
from editor_assistant.workflow.transcripts import TRUST_AUTO_CAPTION

TRANSCRIBER_UNAVAILABLE = "TRANSCRIBER_UNAVAILABLE"
TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
TRANSCRIPT_EMPTY = "TRANSCRIPT_EMPTY"
TRANSCRIPT_INVALID = "TRANSCRIPT_INVALID"
UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"

#: Preference order when no explicit language is requested. Kept deliberately
#: short: each extra language is another subtitle request and YouTube rate-limits
#: bursts (HTTP 429). Bulgarian originals first; `--language` overrides entirely.
DEFAULT_LANGUAGE_PREFERENCE = ("bg-orig", "bg")
DEFAULT_TIMEOUT = 180
ORIGIN_YTDLP = "yt-dlp"


class TranscriberError(ValueError):
    """Transcription failed; `category` names the explicit failure state."""

    def __init__(self, category, detail):
        super().__init__(f"{category}: {detail}")
        self.category = category
        self.detail = detail


@dataclass(frozen=True)
class TranscriptionResult:
    status: str
    video_id: str
    raw_srt: str
    language: str | None
    origin: str
    provider_or_command: str
    generated_at: str
    warnings: tuple = ()

    def as_dict(self):
        return asdict(self)


def transcriber_available():
    """(available, command_or_reason) for the external transcriber."""
    import shutil

    binary = shutil.which("yt-dlp")
    if binary:
        return True, binary
    return False, "yt-dlp is not on PATH"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_runner(cmd, cwd, timeout):
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


_TS_MARKER = "-->"


def _next_nonempty_is_timestamp(lines, index):
    for line in lines[index + 1 :]:
        if line.strip():
            return _TS_MARKER in line
    return False


def canonicalize_srt(text):
    """Normalize yt-dlp's SRT line structure into standard blocks.

    yt-dlp's VTT->SRT conversion emits blank lines *inside* a cue and can leave
    a stray header. We only fix the line structure (drop blank/sequence/header
    lines, renumber sequentially); every timestamp and text line is preserved
    byte-for-byte, so the raw timestamped transcript remains authoritative.
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    timestamp = None
    texts = []
    for index, raw in enumerate(lines):
        line = raw.strip()
        if _TS_MARKER in line:
            if timestamp is not None:
                blocks.append((timestamp, texts))
            timestamp, texts = line, []
            continue
        if not line:
            continue
        if line.isdigit() and _next_nonempty_is_timestamp(lines, index):
            continue  # sequence number, not cue text
        if timestamp is None:
            continue  # stray header before the first cue
        texts.append(line)
    if timestamp is not None:
        blocks.append((timestamp, texts))
    rendered = [
        f"{number}\n{ts}\n" + "\n".join(cue_text)
        for number, (ts, cue_text) in enumerate((b for b in blocks if b[1]), start=1)
    ]
    return "\n\n".join(rendered) + ("\n" if rendered else "")


def _build_command(binary, url, language):
    requested = (
        f"{language}.*"
        if language
        else ",".join(f"{lang}.*" for lang in DEFAULT_LANGUAGE_PREFERENCE)
    )
    return [
        binary,
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs",
        requested,
        "--convert-subs",
        "srt",
        "-o",
        "%(id)s.%(ext)s",
        url,
    ]


def _language_from_path(path):
    """`<id>.<lang>.srt` -> lang (yt-dlp names the language in the filename)."""
    name = Path(path).name
    parts = name.split(".")
    return parts[-2] if len(parts) >= 3 else None


def _pick_srt(files, language):
    if not files:
        return None
    if language:
        for path in files:
            if _language_from_path(path) == language:
                return path
        return None  # requested language not produced -> explicit unsupported
    ranked = sorted(
        files,
        key=lambda p: (
            DEFAULT_LANGUAGE_PREFERENCE.index(_language_from_path(p))
            if _language_from_path(p) in DEFAULT_LANGUAGE_PREFERENCE
            else len(DEFAULT_LANGUAGE_PREFERENCE),
            p,
        ),
    )
    return ranked[0]


def transcribe_youtube(
    source, *, language=None, workdir=None, runner=None, timeout=DEFAULT_TIMEOUT
):
    """Fetch raw timestamped SRT subtitles for one canonical source.

    `source` is a `youtube.YouTubeSource`. Returns `TranscriptionResult` or
    raises `TranscriberError` with an explicit category.
    """
    available, detail = transcriber_available()
    if runner is None and not available:
        raise TranscriberError(TRANSCRIBER_UNAVAILABLE, detail)
    runner = runner or _default_runner
    binary = detail if available else "yt-dlp"

    own_tmp = workdir is None
    workdir = Path(workdir or tempfile.mkdtemp(prefix="yt_intake_"))
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = _build_command(binary, source.canonical_url, language)

    try:
        completed = runner(cmd, str(workdir), timeout)
    except subprocess.TimeoutExpired as exc:
        raise TranscriberError(TRANSCRIPTION_FAILED, f"yt-dlp timed out after {timeout}s") from exc
    except OSError as exc:
        raise TranscriberError(TRANSCRIBER_UNAVAILABLE, f"{type(exc).__name__}: {exc}") from exc

    stderr = (getattr(completed, "stderr", "") or "").strip()
    stdout = (getattr(completed, "stdout", "") or "").strip()
    returncode = getattr(completed, "returncode", 0)

    files = sorted(glob.glob(str(workdir / "*.srt")))
    if returncode != 0 and not files:
        tail = (stderr or stdout)[-400:]
        raise TranscriberError(TRANSCRIPTION_FAILED, tail or f"yt-dlp exit {returncode}")

    chosen = _pick_srt(files, language)
    if chosen is None:
        if language:
            raise TranscriberError(
                UNSUPPORTED_LANGUAGE,
                f"no '{language}' subtitles were produced for {source.video_id}",
            )
        raise TranscriberError(TRANSCRIPT_EMPTY, "yt-dlp produced no subtitle files")

    raw = Path(chosen).read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        raise TranscriberError(TRANSCRIPT_EMPTY, f"subtitle file {Path(chosen).name} is empty")
    warnings = ()
    raw = canonicalize_srt(raw)
    try:
        segments = T.parse_srt(raw)
    except T.TranscriptError as exc:
        raise TranscriberError(TRANSCRIPT_INVALID, str(exc)) from exc
    if not segments:
        raise TranscriberError(TRANSCRIPT_INVALID, "parsed SRT contains no segments")
    if own_tmp:
        _cleanup(workdir)

    return TranscriptionResult(
        status="TRANSCRIPTION_OK",
        video_id=source.video_id,
        raw_srt=raw,
        language=_language_from_path(chosen),
        origin=f"{ORIGIN_YTDLP}:auto-sub",
        provider_or_command=" ".join(cmd[:1]) + " (auto-subs)",
        generated_at=_now(),
        warnings=warnings,
    )


def _cleanup(workdir):
    for path in glob.glob(str(Path(workdir) / "*")):
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        os.rmdir(workdir)
    except OSError:
        pass


# Trust is never silently upgraded: yt-dlp auto-captions are AUTO_CAPTION.
TRUST_LEVEL_FOR_AUTO_SUB = TRUST_AUTO_CAPTION

_LANG_RE = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)?$")


def is_language_code(value):
    return bool(value) and bool(_LANG_RE.match(value.lower()))
