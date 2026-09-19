"""M3B offline tests: URL identity, transcriber adapter, cache, pipeline, CLI.

Hermetic by construction - every external boundary (transcriber, metadata,
discovery model work, Jev) is injected. No network, no yt-dlp, no LLM calls.
"""

import json
from pathlib import Path

import pytest

from editor_assistant.workflow import cli, intake, intake_store, jev_shadow
from editor_assistant.workflow import transcriber as T
from editor_assistant.workflow import youtube as Y

SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\nЗдравейте\n\n"
    "2\n00:00:03,000 --> 00:00:06,000\nсвят на комисията\n"
)
VID = "dQw4w9WgXcQ"


# ---------- Part B: identity ----------


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}&t=42s",
        f"https://youtu.be/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"https://youtube.com/shorts/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://m.youtube.com/watch?v={VID}",
        f"youtube.com/watch?v={VID}",
    ],
)
def test_all_common_url_forms_normalize_to_one_identity(url):
    assert Y.parse_video_id(url) == VID
    assert Y.canonical_url(VID) == f"https://www.youtube.com/watch?v={VID}"


def test_equivalent_url_forms_deduplicate_to_same_video_id():
    ids = {
        Y.parse_video_id(u)
        for u in (
            f"https://youtu.be/{VID}",
            f"https://www.youtube.com/watch?v={VID}",
            f"https://www.youtube.com/shorts/{VID}",
        )
    }
    assert ids == {VID}


def test_original_url_is_preserved_separately():
    source = Y.identify(f"https://youtu.be/{VID}")
    assert source.original_url == f"https://youtu.be/{VID}"
    assert source.canonical_url == f"https://www.youtube.com/watch?v={VID}"
    assert source.transcript_trust_level == "AUTO_CAPTION"


@pytest.mark.parametrize(
    "bad",
    [
        "https://vimeo.com/12345",
        "https://www.youtube.com/watch?v=short",
        "not a url",
        "https://youtube.com/watch",
        "https://youtube.com/watch?v=abcdefgh!jk",
        "",
    ],
)
def test_invalid_urls_rejected_cleanly(bad):
    with pytest.raises(Y.YouTubeSourceError):
        Y.parse_video_id(bad)


def test_metadata_overlay_never_invents_values():
    source = Y.identify(f"https://youtu.be/{VID}", metadata={"origin": "test:unavailable"})
    assert source.title is None and source.channel is None
    assert source.metadata_origin == "test:unavailable"


def test_metadata_failure_is_explicit():
    def boom(_url):
        raise RuntimeError("no net")

    meta = Y.resolve_metadata(f"https://youtu.be/{VID}", extractor=boom)
    assert meta["origin"] == "yt_dlp:error" and "no net" in meta["reason"]


def test_metadata_resolves_fields_when_available():
    meta = Y.resolve_metadata(
        f"https://youtu.be/{VID}",
        extractor=lambda _u: {
            "id": VID,
            "title": "T",
            "channel": "C",
            "upload_date": "20260901",
            "duration": 754,
            "language": "bg",
        },
    )
    assert meta["published_at"] == "2026-09-01"
    assert meta["duration_seconds"] == 754
    assert meta["origin"] == "yt_dlp"


# ---------- Part D: transcriber adapter ----------


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _runner(srt=SRT, lang="bg", returncode=0, stderr=""):
    def run(cmd, cwd, timeout):
        if srt is not None:
            Path(cwd, f"{VID}.{lang}.srt").write_text(srt, encoding="utf-8")
        return _Completed(returncode, stderr=stderr)

    return run


def _source():
    return Y.identify(f"https://youtu.be/{VID}")


def test_transcriber_success_returns_raw_srt_and_autocaption(tmp_path):
    result = T.transcribe_youtube(_source(), runner=_runner(), workdir=tmp_path)
    assert result.status == "TRANSCRIPTION_OK"
    assert result.raw_srt == SRT
    assert result.language == "bg"
    assert T.TRUST_LEVEL_FOR_AUTO_SUB == "AUTO_CAPTION"  # never silently upgraded


def test_transcriber_unavailable_when_ytdlp_missing(monkeypatch):
    monkeypatch.setattr(T, "transcriber_available", lambda: (False, "yt-dlp is not on PATH"))
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(_source(), workdir=Path("/tmp/x"))
    assert exc.value.category == T.TRANSCRIBER_UNAVAILABLE


def test_transcriber_failure_is_explicit_not_empty(tmp_path):
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(
            _source(), runner=_runner(srt=None, returncode=1, stderr="boom"), workdir=tmp_path
        )
    assert exc.value.category == T.TRANSCRIPTION_FAILED


def test_transcriber_empty_and_invalid_are_distinct(tmp_path):
    with pytest.raises(T.TranscriberError) as empty:
        T.transcribe_youtube(_source(), runner=_runner(srt=None), workdir=tmp_path)
    assert empty.value.category == T.TRANSCRIPT_EMPTY
    with pytest.raises(T.TranscriberError) as invalid:
        T.transcribe_youtube(_source(), runner=_runner(srt="not an srt"), workdir=tmp_path)
    assert invalid.value.category == T.TRANSCRIPT_INVALID


def test_requested_language_not_produced_is_unsupported(tmp_path):
    with pytest.raises(T.TranscriberError) as exc:
        T.transcribe_youtube(_source(), language="de", runner=_runner(lang="bg"), workdir=tmp_path)
    assert exc.value.category == T.UNSUPPORTED_LANGUAGE


# ---------- Part F: registry / cache ----------


def test_transcript_store_is_content_addressed_and_never_overwrites(tmp_path):
    p1, h1 = intake_store.store_transcript(VID, "transcript one", root=tmp_path)
    p2, h2 = intake_store.store_transcript(VID, "transcript two", root=tmp_path)
    assert p1 != p2 and p1.exists() and p2.exists()
    assert h1 != h2


def test_registry_keeps_version_history_and_current_pointer(tmp_path):
    registry = intake_store.read_registry(tmp_path)
    intake_store.upsert_record(
        registry,
        video_id=VID,
        canonical_url=Y.canonical_url(VID),
        transcript_file="/a.srt",
        transcript_hash_value="h1",
        transcriber_identity="yt-dlp",
    )
    intake_store.upsert_record(
        registry,
        video_id=VID,
        canonical_url=Y.canonical_url(VID),
        transcript_file="/b.srt",
        transcript_hash_value="h2",
        transcriber_identity="yt-dlp",
    )
    intake_store.save_registry(registry, tmp_path)
    saved = intake_store.read_registry(tmp_path)
    assert saved[VID]["transcript_hash"] == "h2"
    assert {v["transcript_hash"] for v in saved[VID]["versions"]} == {"h1", "h2"}


def test_reusable_record_requires_existing_file_and_respects_force(tmp_path):
    registry = intake_store.read_registry(tmp_path)
    transcript = tmp_path / "t.srt"
    transcript.write_text(SRT, encoding="utf-8")
    intake_store.upsert_record(
        registry,
        video_id=VID,
        canonical_url=Y.canonical_url(VID),
        transcript_file=str(transcript),
        transcript_hash_value="h1",
        transcriber_identity="yt-dlp",
    )
    assert intake_store.reusable_record(registry, VID) is not None
    assert intake_store.reusable_record(registry, VID, force=True) is None


def test_interrupted_run_does_not_leave_success_row(tmp_path):
    """Transcriber failure must name the stage and not write the registry."""

    def failing(src, language=None):
        raise T.TranscriberError(T.TRANSCRIPTION_FAILED, "died mid-run")

    result = intake.intake_youtube(
        f"https://youtu.be/{VID}",
        root=tmp_path,
        metadata_fn=lambda _u: {"origin": "test:stub"},
        transcriber_fn=failing,
        jev_shadow_enabled=False,
    )
    assert result["outcome"] == "TRANSCRIPTION_FAILED"
    assert result["stages"]["transcription"]["category"] == T.TRANSCRIPTION_FAILED
    assert intake_store.read_registry(tmp_path) == {}


# ---------- Part G/H/L: pipeline ----------


def _analysis(outcome_ready="DRAFT_READY", facts=True):
    facts_list = (
        [
            {
                "fact_id": f"{VID}-f001",
                "text": "Комисията прие бюджета.",
                "segment_ids": [f"{VID}-s0001"],
                "supporting_segment_ids": [f"{VID}-s0001"],
                "procedural_status": "APPROVED",
                "fact_grounding_status": "GROUNDED",
                "grounding_failures": [],
                "risk_flags": [],
            }
        ]
        if facts
        else []
    )
    return {
        "topics": [{"topic_id": f"{VID}-t01"}],
        "facts": facts_list,
        "dropped": [],
        "skips": [],
        "proposals": [],
        "candidates": [
            {
                "angle_id": "budget",
                "new_proposition": "Бюджетът е приет.",
                "fact_ids": [f["fact_id"] for f in facts_list],
                "eligible": True,
                "total": 6,
                "semantic_status": "ANGLE_SELECTED",
                "reason": "конкретна новост",
            }
        ],
        "assessment": {"status": "ANGLE_SELECTED", "selected_angle_id": "budget", "candidates": []},
        "readiness": {"status": outcome_ready, "reason": "ok"},
        "support_texts": {f["fact_id"]: "Комисията прие бюджета." for f in facts_list},
    }


def _intake(tmp_path, **overrides):
    kwargs = {
        "root": tmp_path,
        "metadata_fn": lambda _u: {
            "origin": "test:stub",
            "title": "Заседание",
            "channel": "Бургас",
        },
        "transcriber_fn": lambda src, language=None: T.TranscriptionResult(
            status="TRANSCRIPTION_OK",
            video_id=src.video_id,
            raw_srt=SRT,
            language="bg",
            origin="test:stub",
            provider_or_command="test",
            generated_at="2026-09-19T00:00:00Z",
        ),
        "analyze_fn": lambda doc: _analysis(),
        "jev_shadow_enabled": False,
    }
    kwargs.update(overrides)
    return intake.intake_youtube(f"https://youtu.be/{VID}", **kwargs)


def test_pipeline_stages_and_outcome(tmp_path):
    result = _intake(tmp_path)
    assert result["outcome"] == "DRAFT_READY"
    assert result["stages"]["normalize"]["status"] == "OK"
    assert result["stages"]["transcription"]["status"] == "OK"
    assert result["stages"]["discovery"]["status"] == "OK"
    assert result["video"]["video_id"] == VID
    assert Path(result["artifacts"]["transcript_file"]).exists()


def test_repeated_intake_reuses_cached_transcript(tmp_path):
    calls = {"n": 0}

    def counting(src, language=None):
        calls["n"] += 1
        return T.TranscriptionResult(
            "TRANSCRIPTION_OK", src.video_id, SRT, "bg", "test", "test", "now"
        )

    _intake(tmp_path, transcriber_fn=counting)
    second = _intake(tmp_path, transcriber_fn=counting)
    assert calls["n"] == 1
    assert second["stages"]["transcription"]["status"] == "REUSED"


def test_changed_transcript_is_not_silently_overwritten(tmp_path):
    _intake(tmp_path)
    other = T.TranscriptionResult(
        "TRANSCRIPTION_OK",
        VID,
        SRT + "\n3\n00:00:06,000 --> 00:00:08,000\nкрай\n",
        "bg",
        "test",
        "test",
        "now",
    )
    result = _intake(
        tmp_path, force_retranscribe=True, transcriber_fn=lambda src, language=None: other
    )
    registry = intake_store.read_registry(tmp_path)
    assert len(registry[VID]["versions"]) == 2
    assert result["stages"]["transcription"]["status"] == "OK"


def test_no_story_is_a_successful_outcome(tmp_path):
    result = _intake(
        tmp_path,
        analyze_fn=lambda doc: {
            **_analysis(),
            "assessment": {
                "status": "NO_PUBLISHABLE_ANGLE",
                "reason": "няма новина",
                "candidates": [],
            },
            "readiness": {"status": "NOT_RUN"},
        },
    )
    assert result["outcome"] == "NO_PUBLISHABLE_ANGLE"


def test_invalid_url_names_the_stage(tmp_path):
    result = intake.intake_youtube(
        "https://example.com/not-yt", root=tmp_path, jev_shadow_enabled=False
    )
    assert result["outcome"] == "INVALID_YOUTUBE_URL"
    assert result["stages"]["normalize"]["status"] == "FAILED"


def test_discovery_failure_names_the_stage(tmp_path):
    def boom(_doc):
        raise RuntimeError("model down")

    result = _intake(tmp_path, analyze_fn=boom)
    assert result["outcome"] == "DISCOVERY_FAILED"
    assert result["stages"]["discovery"]["status"] == "FAILED"


# ---------- Part H: Jev shadow cannot change production output ----------


def _fake_jev(state, questions, env=None):
    return {
        "status": "JEV_OK",
        "model_requested": "jev-latest",
        "model_effective": "jev-test",
        "latency_ms": 1,
        "usage": {},
        "answers": {
            name: {"type": s["kind"], "answer": None, "probabilities": {}, "confidence": 0.5}
            for name, s in questions.items()
        },
    }


def test_jev_enabled_and_disabled_produce_identical_outcome(tmp_path):
    without = _intake(tmp_path / "a", jev_shadow_enabled=False)
    with_jev = _intake(tmp_path / "b", jev_shadow_enabled=True, jev_evaluate_fn=_fake_jev)
    assert with_jev["outcome"] == "DRAFT_READY"
    assert with_jev["outcome"] == without["outcome"]
    assert with_jev["stages"]["discovery"] == without["stages"]["discovery"]
    assert with_jev["analysis"] == without["analysis"]


def test_semantic_rescue_classification():
    base = {"result": {"answers": {"overall_support": {"answer": "EXACT_SUPPORT"}}}}
    assert (
        jev_shadow.classify_grounding_case({**base, "deterministic_status": "DROPPED_UNGROUNDED"})
        == "DETERMINISTIC_REJECT__JEV_SUPPORTS"
    )
    reject = {"result": {"answers": {"overall_support": {"answer": "NOT_SUPPORTED"}}}}
    assert (
        jev_shadow.classify_grounding_case({**reject, "deterministic_status": "GROUNDED"})
        == "DETERMINISTIC_RETAIN__JEV_REJECTS"
    )
    assert jev_shadow.classify_grounding_case({**base, "deterministic_status": "GROUNDED"}) is None


def test_no_drafting_import_in_intake():
    """M3B is intake, not drafting: no drafting/publishing imports or calls."""
    root = Path(__file__).resolve().parents[1] / "src" / "editor_assistant" / "workflow"
    for name in ("intake.py", "transcriber.py", "youtube.py", "intake_store.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "from editor_assistant.drafting" not in text
        assert "import drafting" not in text
        assert "record_editor_final" not in text
        assert "draft_text" not in text


# ---------- Part I: CLI uses the same intake service ----------


def test_cli_youtube_intake_uses_the_intake_service(monkeypatch, capsys):
    seen = {}

    def fake_intake(url, **kwargs):
        seen["url"] = url
        return {
            "original_url": url,
            "outcome": "DRAFT_READY",
            "video": {
                "video_id": VID,
                "canonical_url": Y.canonical_url(VID),
                "transcript_trust_level": "AUTO_CAPTION",
            },
            "stages": {"normalize": {"status": "OK"}},
            "analysis": {"topics": [], "facts": [], "assessment": {}, "readiness": {}},
            "artifacts": {},
        }

    monkeypatch.setattr(intake, "intake_youtube", fake_intake)
    cli.main(["youtube-intake", f"https://youtu.be/{VID}", "--skip-jev-shadow"])
    out = capsys.readouterr().out
    assert seen["url"] == f"https://youtu.be/{VID}"
    assert "outcome: DRAFT_READY" in out
    assert VID in out


def test_workbench_displays_completed_intakes(tmp_path, monkeypatch):
    """M3B Part J: Workbench display path reads the same store (no initiation)."""
    from editor_assistant.workflow.workbench import http as wb_http
    from editor_assistant.workflow.workbench import state as wb_state

    assert wb_http._route("/intake") == ("intake", None)

    result = _intake(tmp_path, jev_shadow_enabled=False)
    monkeypatch.setenv("YOUTUBE_INTAKE_DIR", str(tmp_path))
    registry = wb_state.intake_registry()
    view = wb_state.intake_view(VID, registry[VID])
    assert view["outcome"] == result["outcome"] == "DRAFT_READY"
    assert view["canonical_url"] == Y.canonical_url(VID)
    assert view["facts"] == 1


def test_intake_persists_durable_summary_artifact(tmp_path):
    result = _intake(tmp_path, jev_shadow_enabled=False)
    artifact = Path(result["artifacts"]["discovery_artifact"])
    assert artifact.exists()
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    assert summary["video_id"] == VID and summary["outcome"] == "DRAFT_READY"
    assert intake_store.read_registry(tmp_path)[VID]["discovery_artifact"] == str(artifact)


def test_intake_writes_shadow_artifacts_only_when_jev_enabled(tmp_path):
    _intake(tmp_path, jev_shadow_enabled=True, jev_evaluate_fn=_fake_jev)
    assert (tmp_path / "intake_grounding_shadow.jsonl").exists()
    assert (tmp_path / "intake_angle_shadow.jsonl").exists()
    rows = [
        json.loads(line)
        for line in (tmp_path / "intake_grounding_shadow.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows and rows[0]["video_id"] == VID
