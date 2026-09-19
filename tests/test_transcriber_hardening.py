"""M3B.1 offline tests: transcriber anti-ban hardening.

Every yt-dlp invocation and every fallback request is injected; nothing here
touches the network or the real yt-dlp binary.
"""

import json
from pathlib import Path

import pytest

from editor_assistant.workflow import invidious as I
from editor_assistant.workflow import transcriber as T
from editor_assistant.workflow import youtube as Y
from editor_assistant.workflow import youtube_policy as P

SRT = "1\n00:00:01,000 --> 00:00:03,000\nЗдравейте\n\n2\n00:00:03,000 --> 00:00:06,000\nсвят\n"
VID = "dQw4w9WgXcQ"


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _source():
    return Y.identify(f"https://youtu.be/{VID}")


def _policy(**overrides):
    base = {
        "player_clients": ("client_one", "client_two"),
        "fallback_enabled": False,
        "delay_min_s": 0,
        "delay_max_s": 0,
        "timeout_s": 5,
    }
    base.update(overrides)
    return P.IntakePolicy(**base)


def _sequence_runner(outcomes):
    """Each call consumes one outcome: ('ok', lang) | ('fail', rc, stderr) | ('empty',)."""
    calls = []

    def run(cmd, cwd, timeout):
        calls.append(cmd)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if outcome[0] == "ok":
            Path(cwd, f"{VID}.{outcome[1]}.srt").write_text(SRT, encoding="utf-8")
            return _Completed(0)
        if outcome[0] == "empty":
            return _Completed(0)
        return _Completed(outcome[1], stderr=outcome[2])

    return run, calls


def _fallback(result):
    def fetch(video_id, languages, *, instances, timeout):
        return result

    return fetch


FALLBACK_OK = {
    "status": "ok",
    "raw_srt": SRT,
    "language": "bg",
    "caption_kind": "asr-invidious",
    "trust_level": "AUTO_CAPTION",
    "instance": "https://one.invalid",
    "warnings": (),
}


# ---------- failure classification ----------


def test_429_is_a_block_and_not_an_ordinary_failure():
    assert T.classify_failure("ERROR: HTTP Error 429: Too Many Requests") == T.TRANSCRIBER_BLOCKED
    assert T.classify_failure("Sign in to confirm you're not a bot") == T.TRANSCRIBER_BLOCKED


def test_permanent_video_problems_are_matched_before_block_signals():
    # A region-locked video message must never trip the run-level breaker, even
    # when it literally contains the word "blocked".
    for message in (
        "ERROR: The uploader has not made this video available in your country",
        "ERROR: This video is blocked in your country",
    ):
        assert T.classify_failure(message) == T.TRANSCRIPT_UNAVAILABLE


def test_unknown_failure_is_an_ordinary_transcription_failure():
    assert T.classify_failure("ERROR: unable to extract player") == T.TRANSCRIPTION_FAILED


# ---------- player-client rotation ----------


def test_a_failing_client_rotates_to_the_next_one(tmp_path):
    runner, calls = _sequence_runner([("empty",), ("ok", "bg")])
    result = T.transcribe_youtube(_source(), policy=_policy(), runner=runner, workdir=tmp_path)
    assert result.status == "TRANSCRIPTION_OK"
    assert len(calls) == 2
    assert "youtube:player_client=client_one" in calls[0]
    assert "youtube:player_client=client_two" in calls[1]
    assert result.origin == f"{T.ORIGIN_YTDLP}:client_two:auto-sub"


def test_rotation_stops_immediately_on_client_independent_answers(tmp_path):
    runner, calls = _sequence_runner([("fail", 1, "Video unavailable")])
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(_source(), policy=_policy(), runner=runner, workdir=tmp_path)
    assert exc.value.category == T.TRANSCRIPT_UNAVAILABLE
    assert len(calls) == 1  # no wasted extra requests


def test_a_block_stops_rotation_immediately(tmp_path):
    """A block is about the IP: do not keep poking it with more clients."""
    runner, calls = _sequence_runner([("fail", 1, "HTTP Error 429: Too Many Requests")])
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(_source(), policy=_policy(), runner=runner, workdir=tmp_path)
    assert exc.value.category == T.TRANSCRIBER_BLOCKED
    assert len(calls) == 1


def test_the_default_client_is_always_the_last_attempt(tmp_path):
    runner, calls = _sequence_runner([("empty",)])
    with pytest.raises(T.TranscriberError):
        T.transcribe_youtube(_source(), policy=_policy(), runner=runner, workdir=tmp_path)
    assert len(calls) == 3  # client_one, client_two, then yt-dlp's own default
    assert "player_client" not in " ".join(calls[-1])


def test_a_configuration_problem_survives_the_failure_path(tmp_path):
    """A misconfigured cookies file is a prime cause of blocks - never hide it."""
    runner, _ = _sequence_runner([("fail", 1, "429 Too Many Requests")])
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(
            _source(),
            policy=_policy(cookies_file="/definitely/not/here.txt"),
            runner=runner,
            workdir=tmp_path,
        )
    assert "config: " in exc.value.detail
    assert "not a file" in exc.value.detail


def test_an_owned_temp_directory_is_removed_even_when_transcription_fails(tmp_path, monkeypatch):
    leaked = tmp_path / "yt_intake_leak"
    leaked.mkdir()
    monkeypatch.setattr(T.tempfile, "mkdtemp", lambda **_kwargs: str(leaked))
    runner, _ = _sequence_runner([("fail", 1, "boom")])
    with pytest.raises(T.TranscriberError):
        T.transcribe_youtube(_source(), policy=_policy(), runner=runner)
    assert not leaked.exists()


def test_a_caller_supplied_workdir_is_never_deleted(tmp_path):
    runner, _ = _sequence_runner([("fail", 1, "boom")])
    with pytest.raises(T.TranscriberError):
        T.transcribe_youtube(_source(), policy=_policy(), runner=runner, workdir=tmp_path)
    assert tmp_path.exists()


def test_the_command_never_runs_format_selection():
    """Without this flag the rotated clients fail even with --skip-download."""
    cmd = T._build_command("yt-dlp", "https://youtu.be/x", None, client="tv_simply")
    assert "--ignore-no-formats-error" in cmd
    assert "--skip-download" in cmd


# ---------- browser-like identity ----------


def test_cookies_and_proxy_flags_are_added_when_configured(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    runner, calls = _sequence_runner([("ok", "bg")])
    T.transcribe_youtube(
        _source(),
        policy=_policy(player_clients=("only",), cookies_file=str(cookies), proxy="http://p:1"),
        runner=runner,
        workdir=tmp_path,
    )
    assert "--cookies" in calls[0] and str(cookies) in calls[0]
    assert "--proxy" in calls[0] and "http://p:1" in calls[0]


def test_impersonation_is_only_passed_when_curl_cffi_is_available(tmp_path):
    runner, calls = _sequence_runner([("ok", "bg")])
    T.transcribe_youtube(
        _source(),
        policy=_policy(player_clients=("only",), impersonate="chrome"),
        runner=runner,
        workdir=tmp_path,
        impersonate_ok=False,
    )
    assert "--impersonate" not in calls[0]

    runner, calls = _sequence_runner([("ok", "bg")])
    T.transcribe_youtube(
        _source(),
        policy=_policy(player_clients=("only",), impersonate="chrome"),
        runner=runner,
        workdir=tmp_path,
        impersonate_ok=True,
    )
    assert "--impersonate" in calls[0] and "chrome" in calls[0]


def test_a_missing_cookies_file_is_reported_not_silently_ignored(tmp_path):
    runner, calls = _sequence_runner([("ok", "bg")])
    result = T.transcribe_youtube(
        _source(),
        policy=_policy(player_clients=("only",), cookies_file="/definitely/not/here.txt"),
        runner=runner,
        workdir=tmp_path,
    )
    assert "--cookies" not in calls[0]
    assert any("not a file" in warning for warning in result.warnings)


def test_impersonation_availability_is_reported_truthfully():
    assert isinstance(T.impersonation_available(), bool)


# ---------- Invidious fallback ----------


def test_a_block_rescues_the_video_through_the_fallback_engine(tmp_path):
    runner, _ = _sequence_runner([("fail", 1, "429 Too Many Requests")])
    result = T.transcribe_youtube(
        _source(),
        policy=_policy(fallback_enabled=True, player_clients=("only",)),
        runner=runner,
        workdir=tmp_path,
        fallback_fn=_fallback(FALLBACK_OK),
    )
    assert result.fallback_used is True
    assert result.origin.startswith(I.ORIGIN_INVIDIOUS)
    assert result.trust_level == "AUTO_CAPTION"
    assert result.raw_srt.startswith("1\n")


def test_a_block_without_a_working_bypass_stays_a_block(tmp_path):
    runner, _ = _sequence_runner([("fail", 1, "429 Too Many Requests")])
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(
            _source(),
            policy=_policy(fallback_enabled=True, player_clients=("only",)),
            runner=runner,
            workdir=tmp_path,
            fallback_fn=_fallback(None),
        )
    assert exc.value.category == T.TRANSCRIBER_BLOCKED


def test_the_fallback_trace_survives_a_total_bypass_outage(tmp_path):
    """A dead fallback must be distinguishable from 'YouTube blocked us'."""
    runner, _ = _sequence_runner([("fail", 1, "429 Too Many Requests")])
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(
            _source(),
            policy=_policy(fallback_enabled=True, player_clients=("only",)),
            runner=runner,
            workdir=tmp_path,
            fallback_fn=_fallback(
                {
                    "status": "unavailable",
                    "warnings": ("https://dead.invalid: empty caption track",),
                }
            ),
        )
    assert "fallback: " in exc.value.detail
    assert "dead.invalid" in exc.value.detail


def test_fallback_is_skipped_entirely_when_disabled(tmp_path):
    runner, _ = _sequence_runner([("fail", 1, "429 Too Many Requests")])
    calls = []

    def fallback(video_id, languages, *, instances, timeout):
        calls.append(video_id)
        return FALLBACK_OK

    with pytest.raises(T.TranscriberError):
        T.transcribe_youtube(
            _source(),
            policy=_policy(fallback_enabled=False, player_clients=("only",)),
            runner=runner,
            workdir=tmp_path,
            fallback_fn=fallback,
        )
    assert calls == []


def test_latched_run_never_touches_youtube_again(tmp_path):
    def exploding_runner(cmd, cwd, timeout):  # pragma: no cover - must not run
        raise AssertionError("YouTube must not be contacted while the latch is active")

    result = T.transcribe_youtube(
        _source(),
        policy=_policy(fallback_enabled=True),
        runner=exploding_runner,
        workdir=tmp_path,
        fallback_fn=_fallback(FALLBACK_OK),
        direct_only=True,
    )
    assert result.fallback_used is True


def test_latched_fallback_failure_is_not_a_youtube_block(tmp_path):
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(
            _source(),
            policy=_policy(fallback_enabled=True),
            runner=lambda *a: None,
            workdir=tmp_path,
            fallback_fn=_fallback(None),
            direct_only=True,
        )
    assert exc.value.category == T.TRANSCRIBER_FALLBACK_FAILED


def test_latch_is_ignored_when_there_is_no_bypass_engine(tmp_path):
    runner, calls = _sequence_runner([("ok", "bg")])
    result = T.transcribe_youtube(
        _source(),
        policy=_policy(fallback_enabled=False, player_clients=("only",)),
        runner=runner,
        workdir=tmp_path,
        direct_only=True,
    )
    assert result.status == "TRANSCRIPTION_OK"
    assert len(calls) == 1


def test_a_raising_fallback_never_masks_the_original_block(tmp_path):
    runner, _ = _sequence_runner([("fail", 1, "429 Too Many Requests")])

    def broken_fallback(video_id, languages, *, instances, timeout):
        raise RuntimeError("instance exploded")

    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(
            _source(),
            policy=_policy(fallback_enabled=True, player_clients=("only",)),
            runner=runner,
            workdir=tmp_path,
            fallback_fn=broken_fallback,
        )
    assert exc.value.category == T.TRANSCRIBER_BLOCKED


# ---------- trust propagation ----------


def test_a_rescued_creator_track_is_human_transcript_never_human_verified(tmp_path):
    runner, _ = _sequence_runner([("fail", 1, "429")])
    rescued = dict(FALLBACK_OK, caption_kind="manual-invidious", trust_level="HUMAN_TRANSCRIPT")
    result = T.transcribe_youtube(
        _source(),
        policy=_policy(fallback_enabled=True, player_clients=("only",)),
        runner=runner,
        workdir=tmp_path,
        fallback_fn=_fallback(rescued),
    )
    assert result.trust_level == "HUMAN_TRANSCRIPT"
    assert result.trust_level != "HUMAN_VERIFIED"


def test_result_is_json_serializable_for_the_registry(tmp_path):
    runner, _ = _sequence_runner([("ok", "bg")])
    result = T.transcribe_youtube(_source(), policy=_policy(), runner=runner, workdir=tmp_path)
    assert json.loads(json.dumps(result.as_dict()))["trust_level"] == "AUTO_CAPTION"
