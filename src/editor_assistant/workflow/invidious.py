"""Invidious caption fallback engine (M3B.1).

Second engine, borrowed from the sibling *ytvault* project: when YouTube pushes
back (429 / bot check / "sign in to confirm"), the rest of the run is rescued
through a public Invidious instance. The instance proxies the request, so
**this IP never touches YouTube again** for the rest of the run. That is what
keeps a soft block from becoming a hard ban.

Deliberate properties:

* stdlib only (`urllib.request`), no new dependency;
* the engine produces a **canonical SRT**, so `transcripts.parse_srt` /
  `TranscriptDocument` stay the single machine representation and raw
  timestamped SRT stays authoritative evidence (M3B Part E);
* trust is never silently upgraded - a caption track that YouTube itself marks
  as automatic stays `AUTO_CAPTION`; a non-ASR creator track becomes at most
  `HUMAN_TRANSCRIPT` (still below `STRONG_TRUST`, so high-risk claims keep
  needing corroboration). Nothing here can ever reach `HUMAN_VERIFIED`.
* every instance failure leaves a trace in `warnings`; silent excepts are how a
  dead fallback engine hides for months.

`opener` is the test seam: the unit suite never performs network I/O.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from editor_assistant.workflow.transcripts import TRUST_AUTO_CAPTION, TRUST_HUMAN_TRANSCRIPT

ORIGIN_INVIDIOUS = "invidious"
KIND_MANUAL = "manual-invidious"
KIND_AUTO = "asr-invidious"

DEFAULT_TIMEOUT_S = 20
MAX_INSTANCES = 5

_VTT_TS = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{1,3})")
_MARKUP = re.compile(r"<[^>]+>")
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64)"


def _vtt_ms(text):
    match = _VTT_TS.search(text or "")
    if not match:
        return None
    hours, minutes, seconds, millis = match.groups()
    return (
        int(hours or 0) * 3600_000
        + int(minutes) * 60_000
        + int(seconds) * 1000
        + int(millis.ljust(3, "0"))
    )


def _ms_to_clock(ms):
    seconds, millis = divmod(int(ms), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _clean_text(line):
    text = html.unescape(_MARKUP.sub("", line))
    return re.sub(r"\s+", " ", text).strip()


def parse_vtt(text):
    """YouTube WebVTT -> cue dicts with exact ms bounds.

    Strips the header, NOTE/STYLE/REGION blocks, cue counters, inline markup
    (`<c>`, `<00:00:01.000>`, `<v Speaker>`), entities and bracket artifacts
    (`[Music]`), then removes consecutive repeats and rolling-caption echoes -
    YouTube ASR re-serves earlier text while a cue grows, which would otherwise
    duplicate words downstream.
    """
    cues = []
    start = end = None
    skipping_block = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            skipping_block = False  # blank line ends NOTE/STYLE/REGION bodies
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            skipping_block = True
            continue
        if skipping_block:
            continue
        if "-->" in line:
            left, _, right = line.partition("-->")
            start = _vtt_ms(left)
            end = _vtt_ms(right.split()[0]) if right.split() else start
            continue
        if line.isdigit():  # cue counter
            continue
        cleaned = _clean_text(line)
        if not cleaned or (cleaned.startswith("[") and cleaned.endswith("]")):
            continue
        if start is None:
            continue
        if cues and cleaned == cues[-1]["text"]:
            continue
        cues.append(
            {
                "start_ms": start,
                "end_ms": max(end if end is not None else start, start),
                "text": cleaned,
            }
        )
    cleaned_cues = []
    for index, cue in enumerate(cues):
        following = cues[index + 1]["text"] if index + 1 < len(cues) else None
        if following and following != cue["text"] and following.startswith(cue["text"]):
            continue  # rolling-caption prefix; the next cue already carries it
        cleaned_cues.append(cue)
    return cleaned_cues


def render_srt(cues):
    """Cues -> standard SRT (what `transcripts.parse_srt` consumes)."""
    blocks = [
        f"{index}\n{_ms_to_clock(cue['start_ms'])} --> {_ms_to_clock(cue['end_ms'])}\n{cue['text']}"
        for index, cue in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def vtt_to_srt(text):
    return render_srt(parse_vtt(text))


def default_opener(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _rank(track, languages):
    """(manual_first, requested_index) for a caption track, or None if unwanted."""
    code = str(track.get("language_code") or track.get("languageCode") or "").lower()
    label = str(track.get("label") or "").lower()
    manual_first = 1 if "auto" in label else 0
    for index, want in enumerate(languages):
        wanted = str(want).lower()
        if code == wanted or code.startswith(wanted + "-"):
            return manual_first, index
    return None


def fetch_captions(video_id, languages, *, instances, opener=None, timeout=DEFAULT_TIMEOUT_S):
    """Try each instance until one serves a caption track.

    Always returns a dict: `{"status": "ok", ...}` on success, otherwise
    `{"status": "unavailable", "warnings": (...)}`. The warnings are returned
    even on total failure on purpose - a silent `None` is how a dead fallback
    engine hides for months, and the per-instance reasons (dead instance, empty
    caption body, ...) are exactly what the operator needs to see.

    Never raises for an instance problem: the caller decides what a total
    fallback failure means (it is *not* proof that the video has no story).
    """
    opener = opener or default_opener
    warnings = []
    for base in list(instances)[:MAX_INSTANCES]:
        base = str(base).rstrip("/")
        try:
            meta = json.loads(opener(f"{base}/api/v1/captions/{video_id}", timeout).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - flaky public instances, kept as evidence
            warnings.append(f"{base}: {type(exc).__name__}: {exc}")
            continue
        tracks = meta if isinstance(meta, list) else (meta.get("captions") or [])
        ranked = [(_rank(t, languages), t) for t in tracks if isinstance(t, dict)]
        candidates = sorted(
            (pair for pair in ranked if pair[0] is not None), key=lambda pair: pair[0]
        )
        for _, track in candidates[:2]:
            url = track.get("url")
            if not url:
                continue
            absolute = base + url if str(url).startswith("/") else str(url)
            try:
                vtt_text = opener(absolute, timeout).decode("utf-8", "replace")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{base} track: {type(exc).__name__}: {exc}")
                continue
            cues = parse_vtt(vtt_text)
            if not cues:
                warnings.append(f"{base}: empty caption track ({len(vtt_text)} chars returned)")
                continue
            label = str(track.get("label") or "")
            is_auto = "auto" in label.lower()
            return {
                "status": "ok",
                "raw_srt": render_srt(cues),
                "segments": len(cues),
                "language": track.get("language_code") or track.get("languageCode"),
                "caption_kind": KIND_AUTO if is_auto else KIND_MANUAL,
                # Never above HUMAN_TRANSCRIPT: a creator caption track is not
                # human-verified evidence, so high-risk claims still need
                # corroboration (transcripts.STRONG_TRUST).
                "trust_level": TRUST_AUTO_CAPTION if is_auto else TRUST_HUMAN_TRANSCRIPT,
                "instance": base,
                "warnings": tuple(warnings),
            }
    return {"status": "unavailable", "warnings": tuple(warnings)}
