"""Transcriber adapter boundary (M3B Part D) + anti-ban hardening (M3B.1).

No transcriber exists in the repository, so this is a small adapter over the
transcriber that *is* actually available on the machine: **yt-dlp**
(`--skip-download --write-auto-subs --write-subs --convert-subs srt`). It is a
boundary, not a new transcription implementation.

The raw timestamped SRT stays the authoritative machine evidence (Part E). This
module contains no article/editorial logic and never collapses infrastructure
failure into "no useful story": every failure maps to an explicit category.

Hardening (ideas from the sibling *ytvault* project - see
`m3/review/M3B1_INTAKE_HARDENING_REPORT.md`):

* **player-client rotation** - `tv_simply` / `web_safari` are reported to pass
  checks the default web client fails, so a client-specific failure rotates to
  the next client instead of giving up, and yt-dlp's own default client is
  always kept as the last attempt. A *block* or a content-level answer stops
  rotation immediately rather than spending requests on a flagged IP;
* **explicit block classification** - YouTube pushback (429 / bot check /
  "sign in to confirm") becomes `TRANSCRIBER_BLOCKED`, which is what trips the
  run-level circuit breaker. Permanent per-video problems are matched *first*,
  because several of their messages contain the word "blocked" and must never
  stop a run;
* **browser-like identity** - optional cookie file, proxy and TLS impersonation
  (impersonation only when the optional `curl-cffi` extra is installed);
* **Invidious fallback** - once YouTube has pushed back, the video is rescued
  through a public instance so this IP stops touching YouTube.

`runner` and `fallback_fn` are the test seams - the unit suite never shells out
to yt-dlp and never opens a socket.
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
#: YouTube pushed back (429 / bot check). Distinct on purpose: this is the only
#: category allowed to trip the run-level circuit breaker.
TRANSCRIBER_BLOCKED = "TRANSCRIBER_BLOCKED"
#: YouTube was already blocked, and the fallback engine could not serve the
#: video either. This video never touched YouTube, so it must NOT trip the
#: breaker - a flaky public instance cannot be allowed to kill the run.
TRANSCRIBER_FALLBACK_FAILED = "TRANSCRIBER_FALLBACK_FAILED"
#: The video itself cannot be served right now (removed / private / region
#: locked). Parked without burning the retry budget: retrying a dead video is
#: just extra requests aimed at a flagged IP.
TRANSCRIPT_UNAVAILABLE = "TRANSCRIPT_UNAVAILABLE"

#: Preference order when no explicit language is requested. Kept deliberately
#: short: each extra language is another subtitle request and YouTube rate-limits
#: bursts (HTTP 429). Bulgarian originals first; `--language` overrides entirely.
DEFAULT_LANGUAGE_PREFERENCE = ("bg-orig", "bg")
DEFAULT_TIMEOUT = 180
ORIGIN_YTDLP = "yt-dlp"

#: Substrings that mean "YouTube is pushing back on this IP", not "this video
#: has a problem". Matched only *after* the permanent per-video patterns, since
#: several of those messages also contain the word "blocked".
_BLOCK_SIGNALS = (
    "429",
    "too many requests",
    "sign in to confirm",
    "not a bot",
    "bot check",
    "ipblocked",
)

#: Substrings that mean the *video* cannot be served right now (geo block,
#: takedown, private). Several contain "blocked", so they are checked first:
#: a region-locked video must never stop a whole run.
_PERMANENT_SIGNALS = (
    "unavailable",
    "private video",
    "removed",
    "does not exist",
    "not exist",
    "in your country",
    "members-only",
)


#: Categories a different player client cannot change, so rotation stops
#: immediately instead of spending extra requests on a possibly flagged IP:
#: an answer about the content itself, or an explicit block.
_STOP_ROTATION = (
    UNSUPPORTED_LANGUAGE,
    TRANSCRIPT_UNAVAILABLE,
    TRANSCRIPT_INVALID,
    TRANSCRIBER_BLOCKED,
)


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
    trust_level: str = TRUST_AUTO_CAPTION
    fallback_used: bool = False

    def as_dict(self):
        return asdict(self)


def transcriber_available():
    """(available, command_or_reason) for the external transcriber."""
    import shutil

    binary = shutil.which("yt-dlp")
    if binary:
        return True, binary
    return False, "yt-dlp is not on PATH"


def impersonation_available():
    """Whether TLS impersonation can be used (optional `curl-cffi` extra)."""
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        return False
    return True


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


def _identity_flags(policy, *, impersonate_ok=None):
    """Browser-identity flags for the yt-dlp command (only what is usable)."""
    flags = []
    if policy is None:
        return flags
    # A folder/missing cookies path would poison every request of the run; the
    # caller reports it once (see `_initial_warnings`) instead of letting it
    # turn into a run of unexplained failures.
    if policy.cookies_file and Path(policy.cookies_file).is_file():
        flags += ["--cookies", policy.cookies_file]
    if policy.proxy:
        flags += ["--proxy", policy.proxy]
    if policy.impersonate and policy.impersonate.lower() != "none":
        if impersonate_ok is None:
            impersonate_ok = impersonation_available()
        if impersonate_ok:
            flags += ["--impersonate", policy.impersonate]
    return flags


def _build_command(binary, url, language, *, client=None, policy=None, impersonate_ok=None):
    requested = (
        f"{language}.*"
        if language
        else ",".join(f"{lang}.*" for lang in DEFAULT_LANGUAGE_PREFERENCE)
    )
    cmd = [binary]
    if client:
        cmd += ["--extractor-args", f"youtube:player_client={client}"]
    cmd += [
        # We only ever want subtitle tracks, but yt-dlp still runs format
        # selection, and the rotated player clients expose no selectable
        # formats -> 'Requested format is not available' on every video.
        # Verified live against yt-dlp 2026.07.04: without this flag the
        # `tv_simply` / `web_safari` clients fail even with --skip-download.
        # This is the CLI equivalent of the sibling project's `process=False`
        # extraction trick.
        "--ignore-no-formats-error",
        "--socket-timeout",
        "30",
        "--retries",
        "1",
        *_identity_flags(policy, impersonate_ok=impersonate_ok),
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
    return cmd


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


def classify_failure(output):
    """Map yt-dlp output to an explicit failure category.

    Permanent per-video problems are matched *before* block signals: a
    region-locked or removed video often says "blocked" too, and mistaking it
    for pushback would trip the run-level breaker on a single dead video.
    """
    text = (output or "").lower()
    if any(signal in text for signal in _PERMANENT_SIGNALS):
        return TRANSCRIPT_UNAVAILABLE
    if any(signal in text for signal in _BLOCK_SIGNALS):
        return TRANSCRIBER_BLOCKED
    return TRANSCRIPTION_FAILED


def _fallback_languages(language):
    return (language,) if language else DEFAULT_LANGUAGE_PREFERENCE


def _run_engine(
    source, language, *, binary, runner, workdir, policy, client, timeout, impersonate_ok
):
    """One yt-dlp attempt with one player client. Returns the SRT path + command."""
    cmd = _build_command(
        binary,
        source.canonical_url,
        language,
        client=client,
        policy=policy,
        impersonate_ok=impersonate_ok,
    )
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
        output = stderr or stdout
        category = classify_failure(output)
        tail = (output or f"yt-dlp exit {returncode}")[-400:]
        raise TranscriberError(category, tail)

    chosen = _pick_srt(files, language)
    if chosen is None:
        if language:
            raise TranscriberError(
                UNSUPPORTED_LANGUAGE,
                f"no '{language}' subtitles were produced for {source.video_id}",
            )
        raise TranscriberError(TRANSCRIPT_EMPTY, "yt-dlp produced no subtitle files")
    return chosen, cmd, stderr


def _validate(raw_srt, source):
    raw = canonicalize_srt(raw_srt)
    try:
        segments = T.parse_srt(raw)
    except T.TranscriptError as exc:
        raise TranscriberError(TRANSCRIPT_INVALID, str(exc)) from exc
    if not segments:
        raise TranscriberError(TRANSCRIPT_INVALID, "parsed SRT contains no segments")
    return raw


def _initial_warnings(policy, impersonate_ok=None):
    """Configuration problems the operator must see, on success **and** failure.

    A misconfigured cookies file is a prime cause of bot checks, so this trace
    must survive the failure path too - it is folded into the raised error.
    """
    warnings = []
    if policy is not None and policy.cookies_file and not Path(policy.cookies_file).is_file():
        warnings.append(
            f"cookies_file '{policy.cookies_file}' is not a file - running without cookies"
        )
    if policy is not None and policy.impersonate and not impersonate_ok:
        warnings.append(
            f"impersonate '{policy.impersonate}' requested but curl-cffi is not installed"
        )
    return warnings


def _annotate(exc, notes):
    """Re-raise `exc` with the configuration trace appended, not swallowed."""
    if not notes:
        return exc
    return TranscriberError(exc.category, f"{exc.detail} | config: {'; '.join(notes)}")


def _ytdlp_result(
    source, language, *, binary, runner, workdir, policy, timeout, impersonate_ok, warnings=()
):
    """Try each configured player client in turn; the first success wins.

    yt-dlp's **default** client is always kept as the last attempt: it is the
    path that is known to work today, so the rotated clients can only add
    options, never remove the fallback.
    """
    clients = list(policy.player_clients) if policy is not None else []
    last_failure = None

    for client in [*clients, None]:
        label = client or "default"
        try:
            chosen, _cmd, _stderr = _run_engine(
                source,
                language,
                binary=binary,
                runner=runner,
                workdir=workdir,
                policy=policy,
                client=client,
                timeout=timeout,
                impersonate_ok=impersonate_ok,
            )
        except TranscriberError as exc:
            if exc.category in _STOP_ROTATION:
                # A different client cannot change this answer, and every extra
                # attempt pokes an IP that may already be flagged.
                raise
            # This client produced nothing (or errored in a client-specific
            # way); give the next one a chance before giving up on the video.
            last_failure = exc
            continue
        raw = Path(chosen).read_text(encoding="utf-8", errors="replace")
        if not raw.strip():
            raise TranscriberError(TRANSCRIPT_EMPTY, f"subtitle file {Path(chosen).name} is empty")
        return TranscriptionResult(
            status="TRANSCRIPTION_OK",
            video_id=source.video_id,
            raw_srt=_validate(raw, source),
            language=_language_from_path(chosen),
            origin=f"{ORIGIN_YTDLP}:{label}:auto-sub",
            provider_or_command="yt-dlp (auto-subs)",
            generated_at=_now(),
            warnings=tuple(warnings),
            trust_level=TRUST_AUTO_CAPTION,
        )

    raise last_failure or TranscriberError(TRANSCRIPT_EMPTY, "yt-dlp produced no subtitle files")


def transcribe_youtube(
    source,
    *,
    language=None,
    workdir=None,
    runner=None,
    timeout=None,
    policy=None,
    fallback_fn=None,
    direct_only=False,
    impersonate_ok=None,
):
    """Fetch raw timestamped SRT subtitles for one canonical source.

    `source` is a `youtube.YouTubeSource`. Returns `TranscriptionResult` or
    raises `TranscriberError` with an explicit category.

    When YouTube pushes back, the video is retried through the Invidious
    fallback (`TRANSCRIBER_BLOCKED` -> fallback -> `TRANSCRIBER_FALLBACK_FAILED`).
    `direct_only=True` is the run-level latch: once one video in a run has been
    blocked, later videos skip YouTube entirely.
    """
    from editor_assistant.workflow import youtube_policy as policy_mod

    policy = policy or policy_mod.load_policy()
    timeout = policy.timeout_s if timeout is None else timeout
    impersonate_ok = impersonation_available() if impersonate_ok is None else impersonate_ok
    warnings = _initial_warnings(policy, impersonate_ok)
    # A bypass-only run needs a bypass engine to exist at all.
    direct_only = bool(direct_only) and bool(policy.fallback_enabled)

    if direct_only:
        # Run-level latch: YouTube already pushed back earlier in this run, so
        # do not touch it again. `_try_fallback` raises when it cannot help.
        rescued, _note = _try_fallback(
            source, language, policy=policy, fallback_fn=fallback_fn, direct_only=True
        )
        return rescued

    available, detail = transcriber_available()
    if runner is None and not available:
        raise _annotate(TranscriberError(TRANSCRIBER_UNAVAILABLE, detail), warnings)
    runner = runner or _default_runner
    binary = detail if available else "yt-dlp"

    own_tmp = workdir is None
    workdir = Path(workdir or tempfile.mkdtemp(prefix="yt_intake_"))
    workdir.mkdir(parents=True, exist_ok=True)

    # The owned temp directory is removed on every path, including failures
    # (each failed video used to leave a directory behind in the temp dir).
    try:
        try:
            return _ytdlp_result(
                source,
                language,
                binary=binary,
                runner=runner,
                workdir=workdir,
                policy=policy,
                timeout=timeout,
                impersonate_ok=impersonate_ok,
                warnings=warnings,
            )
        except TranscriberError as exc:
            if exc.category != TRANSCRIBER_BLOCKED:
                raise _annotate(exc, warnings) from exc
            # YouTube pushed back. Stop poking it and let an Invidious instance
            # proxy the captions instead.
            rescued, note = _try_fallback(
                source, language, policy=policy, fallback_fn=fallback_fn, direct_only=direct_only
            )
            if rescued is not None:
                return rescued
            # Keep both traces in the error: without the fallback note a total
            # bypass outage is indistinguishable from "YouTube blocked us", and
            # without the config note a misconfigured cookies file is invisible
            # on the exact path where it matters.
            detail = f"{exc.detail} | fallback: {note}"
            if warnings:
                detail += f" | config: {'; '.join(warnings)}"
            raise TranscriberError(exc.category, detail) from exc
    finally:
        if own_tmp:
            _cleanup(workdir)


def _try_fallback(source, language, *, policy, fallback_fn, direct_only):
    """Invidious rescue. Returns `(result_or_None, note)` - the note is a trace
    of why the fallback could not help, and is never silently dropped."""
    from editor_assistant.workflow import invidious as invidious_mod

    if not policy.fallback_enabled:
        return None, "disabled"
    if fallback_fn is None:
        fallback_fn = invidious_mod.fetch_captions
    try:
        captioned = fallback_fn(
            source.video_id,
            _fallback_languages(language),
            instances=policy.invidious_instances,
            timeout=policy.timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - fallback must never mask the original block
        captioned = None
        note = f"{type(exc).__name__}: {exc}"
    else:
        served = isinstance(captioned, dict) and captioned.get("status") == "ok"
        if served:
            note = ""
        else:
            warnings = tuple((captioned or {}).get("warnings") or ())
            note = "; ".join(str(w) for w in warnings) or "no instance served captions"

    if not (isinstance(captioned, dict) and captioned.get("status") == "ok"):
        if direct_only:
            # YouTube was never contacted for this video: a flaky public
            # instance must not trip the run-level breaker.
            raise TranscriberError(
                TRANSCRIBER_FALLBACK_FAILED,
                f"fallback engine could not serve captions ({note})",
            )
        return None, note[:400]

    raw = _validate(captioned["raw_srt"], source)
    return TranscriptionResult(
        status="TRANSCRIPTION_OK",
        video_id=source.video_id,
        raw_srt=raw,
        language=captioned.get("language"),
        origin=f"{invidious_mod.ORIGIN_INVIDIOUS}:{captioned.get('caption_kind', 'caption')}",
        provider_or_command="invidious captions API",
        generated_at=_now(),
        warnings=tuple(captioned.get("warnings") or ()),
        trust_level=captioned.get("trust_level") or TRUST_AUTO_CAPTION,
        fallback_used=True,
    ), ""


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
