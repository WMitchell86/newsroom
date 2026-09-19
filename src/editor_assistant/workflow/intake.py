"""YouTube URL intake orchestrator (M3B Part G/H/L/N).

    URL -> normalize/identify -> metadata -> transcribe or reuse
        -> validate raw SRT -> TranscriptDocument -> discovery V2 -> readiness
        -> optional Jev SHADOW observation

Principles:

* a URL is an intake request, not a story - `NO_PUBLISHABLE_ANGLE` is a
  successful outcome, not a failed intake;
* raw timestamped SRT is authoritative machine evidence; discovery V2 is reused
  unchanged (no semantic edits);
* each stage reports its own status, so a failure names its stage;
* Jev is **shadow only**: enabling it cannot change facts, angles, readiness or
  drafting, and the production result is identical either way.

All external calls (transcriber, metadata, discovery model work, Jev) are
injectable seams; the unit suite never touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

from editor_assistant.workflow import angles as angles_mod
from editor_assistant.workflow import discovery, discovery_cache, intake_store, jev_shadow
from editor_assistant.workflow import transcriber as transcriber_mod
from editor_assistant.workflow import youtube as youtube_mod
from editor_assistant.workflow.live_store import atomic_write
from editor_assistant.workflow.transcripts import (
    TRUST_AUTO_CAPTION,
    TranscriptError,
    load_srt,
)

OUTCOME_DRAFT_READY = "DRAFT_READY"
OUTCOME_RESEARCH_MORE = "RESEARCH_MORE"
OUTCOME_EDITOR_DECISION_REQUIRED = "EDITOR_DECISION_REQUIRED"
OUTCOME_NO_PUBLISHABLE_ANGLE = "NO_PUBLISHABLE_ANGLE"
OUTCOME_NO_FACTS = "NO_EXTRACTED_FACTS"
OUTCOME_DISCOVERY_DEGRADED = "DISCOVERY_DEGRADED"
OUTCOME_INVALID_URL = "INVALID_YOUTUBE_URL"
OUTCOME_TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
OUTCOME_DISCOVERY_FAILED = "DISCOVERY_FAILED"
OUTCOME_UNKNOWN = "UNKNOWN"


class DiscoveryError(RuntimeError):
    """Transcript discovery (model) stage failed; the stage is named."""


def _segment_support(doc, segment_ids):
    wanted = set(segment_ids or [])
    return " ".join(s.raw_text for s in doc.segments if s.segment_id in wanted).strip()


def default_analyze(doc, *, raw_srt=None, force=False):
    """Run the unchanged discovery V2 chain for one TranscriptDocument.

    Mirrors the V2 batch flow exactly: topics -> facts (+dropped) ->
    proposals -> deterministic assessment -> angles.assess_angles -> readiness.
    No editorial logic lives here.

    M3D Part L4: the two MODEL stages (fact extraction + angle proposals) are
    cached after their first SUCCESSFUL run, keyed by transcript hash + stage
    version + model config. Same SRT bytes -> same cached semantic inputs ->
    the deterministic downstream gate (assessment, angles, readiness) becomes
    reproducible. The cache never stores a failure, and `force=True` bypasses
    it. With `raw_srt=None` (legacy callers/tests) the cache is skipped —
    caching requires the input-bytes identity to key on.
    """
    topics = discovery.segment_topics(doc)
    facts, dropped, skips = [], [], []
    proposals = []
    cache = None
    if raw_srt is not None and not force:
        cache = discovery_cache.load(discovery_cache.transcript_hash(raw_srt))
    if cache is not None:
        facts = list(cache["facts"])
        dropped = list(cache.get("dropped") or [])
        skips = list(cache.get("skips") or [])
        proposals = list(cache["proposals"])
        cache_status = discovery_cache.cached_result_status(cache)
    else:
        if topics:
            try:
                facts = list(discovery.extract_facts(doc, topics))
            except Exception as exc:  # name the stage, never fake facts
                raise DiscoveryError(
                    f"fact extraction failed: {type(exc).__name__}: {exc}"
                ) from exc
            dropped = list(getattr(discovery.extract_facts, "dropped", []))
            skips = list(getattr(discovery.extract_facts, "skipped_topics", []))
        if facts:
            try:
                proposals = discovery.propose_angles(facts)
            except Exception:  # noqa: BLE001 - proposal failure is not a hard intake failure
                proposals = []
        if raw_srt is not None and facts:
            discovery_cache.store(
                discovery_cache.transcript_hash(raw_srt),
                facts=facts,
                proposals=proposals,
                dropped=dropped,
                skips=skips,
                source={"transcript_id": doc.transcript_id},
            )
        cache_status = (
            ("MISS" if raw_srt is not None else "DISABLED_NO_RAW_SRT")
            if not force
            else ("FORCED_RERUN" if raw_srt is not None else "DISABLED_NO_RAW_SRT")
        )

    # Fact identity (M3D regression fix): `extract_facts` labels RETAINED facts
    # itself, but grounding-REJECTED candidates carry no id, and the support-text
    # map below keys on it. Restored verbatim from the M3B.1 behaviour so a
    # transcript with at least one rejected fact cannot crash the intake path.
    for position, fact in enumerate(facts):
        fact["fact_id"] = f"{doc.transcript_id}-f{position + 1:03d}"
    for position, fact in enumerate(dropped):
        fact.setdefault("fact_id", f"{doc.transcript_id}-d{position + 1:03d}")

    candidates, diagnostics = discovery.assess_candidates(
        proposals, facts, repeated={}, use_model_judge=False
    )
    if candidates:
        packet_facts = [
            {"id": fact["fact_id"], "text": fact["text"], "scope": "current_event"}
            for fact in facts
        ]
        try:
            assessment = angles_mod.assess_angles(
                {
                    "facts": packet_facts,
                    "source_type": "transcript",
                    "source_text": " ".join(fact["text"] for fact in facts),
                },
                candidates,
                min_candidates=1,
            )
        except angles_mod.AngleError as exc:
            assessment = {
                "status": "INVALID_PROPOSALS",
                "reason": str(exc),
                "candidates": candidates,
            }
    elif facts:
        assessment = {
            "status": discovery.INSUFFICIENT_ANGLES,
            "reason": "фактите не предложиха реални ъгли",
            "candidates": [],
        }
    else:
        assessment = {
            "status": "NO_EXTRACTED_FACTS",
            "reason": "моделът не върна факти",
            "candidates": [],
        }
    assessment["diagnostics"] = diagnostics

    readiness = {"status": "NOT_RUN", "reason": f"angle gate: {assessment.get('status')}"}
    if assessment.get("status") in (
        angles_mod.READY,
        angles_mod.NEEDS_RESEARCH,
        angles_mod.NO_ANGLE,
    ):
        packet = discovery.build_evidence_packet(doc, facts, assessment)
        readiness = discovery.run_readiness(packet)

    support_texts = {
        fact["fact_id"]: _segment_support(
            doc, fact.get("supporting_segment_ids") or fact.get("segment_ids")
        )
        for fact in list(facts) + list(dropped)
    }
    return {
        "topics": topics,
        "facts": facts,
        "dropped": dropped,
        "skips": skips,
        "proposals": proposals,
        "candidates": candidates,
        "assessment": assessment,
        "readiness": readiness,
        "support_texts": support_texts,
        "cache_status": cache_status,
    }


def _model_zero_execution_surfaces(analysis):
    """Zero-yield reasons that mean model EXECUTION failed, not 'no facts'.

    M3D Part M: if a transcript produced valid grounded facts before under the
    same discovery version/config, a later zero-yield run with an execution
    failure must not silently become editorial no-story evidence. The reasons
    live in discovery (single taxonomy owner); this maps them to topics.
    """
    from editor_assistant.workflow import discovery as discovery_mod

    failed = set(discovery_mod.EXECUTION_FAILURE_REASONS)
    surfaces = []
    for skip in analysis.get("skips") or []:
        reason = str(skip.get("reason") or "")
        if reason.split(":", 1)[0].strip() in failed:
            surfaces.append({"topic_id": skip.get("topic_id"), "reason": reason})
    return surfaces


def _outcome_from(analysis):
    readiness_status = (analysis.get("readiness") or {}).get("status")
    if readiness_status in (
        OUTCOME_DRAFT_READY,
        OUTCOME_RESEARCH_MORE,
        OUTCOME_EDITOR_DECISION_REQUIRED,
    ):
        return readiness_status
    assessment_status = (analysis.get("assessment") or {}).get("status")
    if assessment_status in (angles_mod.NO_ANGLE, angles_mod.NOT_VIABLE):
        return OUTCOME_NO_PUBLISHABLE_ANGLE
    if assessment_status == OUTCOME_NO_FACTS and _model_zero_execution_surfaces(analysis):
        # Zero yield WITH an execution surface: report degraded, not no-story.
        # A historical-facts lookup is deliberately NOT used to flip this back
        # to a positive outcome (no caching/versioning exists yet; M3D Part M).
        return OUTCOME_DISCOVERY_DEGRADED
    if assessment_status == OUTCOME_NO_FACTS:
        return OUTCOME_NO_FACTS
    return OUTCOME_UNKNOWN


def intake_youtube(
    url,
    *,
    language=None,
    force_retranscribe=False,
    jev_shadow_enabled=True,
    transcriber_fn=None,
    metadata_fn=None,
    analyze_fn=None,
    jev_evaluate_fn=None,
    transcriber_kwargs=None,
    root=None,
    retrieved_at=None,
):
    """One YouTube URL in; a structured intake result out. Never drafts."""
    stages = {}
    result = {
        "original_url": (url or "").strip(),
        "video": None,
        "outcome": None,
        "stages": stages,
        "analysis": None,
        "artifacts": {},
    }

    # 1. normalize / identify
    try:
        source = youtube_mod.identify(url, retrieved_at=retrieved_at)
    except youtube_mod.YouTubeSourceError as exc:
        stages["normalize"] = {"status": "FAILED", "reason": str(exc)}
        result["outcome"] = OUTCOME_INVALID_URL
        return result
    stages["normalize"] = {
        "status": "OK",
        "video_id": source.video_id,
        "canonical_url": source.canonical_url,
    }

    # 2. metadata (optional, never fatal)
    metadata_fn = metadata_fn or youtube_mod.resolve_metadata
    meta = metadata_fn(source.canonical_url)
    source = youtube_mod.identify(url, metadata=meta, retrieved_at=retrieved_at)
    origin = str(meta.get("origin") or "")
    if origin.endswith(("unavailable", "error", "invalid")):
        stages["metadata"] = {"status": "PARTIAL", "origin": origin, "reason": meta.get("reason")}
    else:
        stages["metadata"] = {"status": "OK", "origin": origin}

    # 3. transcribe or reuse
    registry = intake_store.read_registry(root)
    cached = intake_store.reusable_record(registry, source.video_id, force=force_retranscribe)
    if cached:
        raw_srt = Path(cached["transcript_file"]).read_text(encoding="utf-8")
        stages["transcription"] = {
            "status": "REUSED",
            "transcript_hash": cached.get("transcript_hash"),
            "transcript_file": cached.get("transcript_file"),
            "origin": cached.get("transcriber_identity"),
            "trust_level": cached.get("trust_level"),
        }
        transcript_language = cached.get("language")
        trust_level = cached.get("trust_level") or TRUST_AUTO_CAPTION
    else:
        transcriber_fn = transcriber_fn or transcriber_mod.transcribe_youtube
        try:
            transcription = transcriber_fn(source, language=language, **(transcriber_kwargs or {}))
        except transcriber_mod.TranscriberError as exc:
            stages["transcription"] = {
                "status": "FAILED",
                "category": exc.category,
                "reason": exc.detail,
            }
            result["outcome"] = OUTCOME_TRANSCRIPTION_FAILED
            return result
        raw_srt = transcription.raw_srt
        transcript_language = transcription.language
        # Trust is never silently upgraded: the transcriber reports the level it
        # has evidence for (ASR vs a creator-uploaded track) and nothing here
        # can raise it further.
        trust_level = getattr(transcription, "trust_level", None) or TRUST_AUTO_CAPTION
        stages["transcription"] = {
            "status": "OK",
            "language": transcription.language,
            "origin": transcription.origin,
            "provider": transcription.provider_or_command,
            "trust_level": trust_level,
            "fallback_used": bool(getattr(transcription, "fallback_used", False)),
        }

    # 4. validate raw SRT -> TranscriptDocument
    try:
        doc = load_srt(
            raw_srt,
            transcript_id=source.video_id,
            source_url=source.canonical_url,
            title=source.title or "",
            language=transcript_language or "bg",
            origin=stages["transcription"].get("origin") or transcriber_mod.ORIGIN_YTDLP,
            trust_level=trust_level,
        )
    except TranscriptError as exc:
        stages["validate"] = {
            "status": "FAILED",
            "category": transcriber_mod.TRANSCRIPT_INVALID,
            "reason": str(exc),
        }
        result["outcome"] = OUTCOME_TRANSCRIPTION_FAILED
        return result
    stages["validate"] = {
        "status": "OK",
        "segments": len(doc.segments),
        "trust_level": doc.trust_level,
    }

    # 5. persist raw transcript + registry (only after validation)
    file_path, digest = intake_store.store_transcript(source.video_id, raw_srt, root)
    intake_store.upsert_record(
        registry,
        video_id=source.video_id,
        canonical_url=source.canonical_url,
        transcript_file=str(file_path),
        transcript_hash_value=digest,
        transcriber_identity=stages["transcription"].get("origin") or transcriber_mod.ORIGIN_YTDLP,
        language=transcript_language,
        trust_level=doc.trust_level,
        source=source,
        timestamp=retrieved_at,
    )
    intake_store.save_registry(registry, root)
    stages["persist"] = {
        "status": "OK",
        "transcript_file": str(file_path),
        "transcript_hash": digest,
    }
    video = source.as_dict()
    video["transcript_hash"] = digest
    video["transcript_trust_level"] = doc.trust_level
    result["video"] = video
    result["artifacts"]["transcript_file"] = str(file_path)

    # 6. discovery V2 (deterministic gate unchanged; model stages L4-cached)
    analyze_fn = analyze_fn or default_analyze
    try:
        if analyze_fn is default_analyze:
            analysis = analyze_fn(doc, raw_srt=raw_srt)
        else:
            analysis = analyze_fn(doc)
    except Exception as exc:  # noqa: BLE001 - name the stage
        stages["discovery"] = {
            "status": "FAILED",
            "category": OUTCOME_DISCOVERY_FAILED,
            "reason": str(exc),
        }
        result["outcome"] = OUTCOME_DISCOVERY_FAILED
        return result
    stages["discovery"] = {
        "status": "OK",
        "topics": len(analysis.get("topics") or []),
        "facts": len(analysis.get("facts") or []),
        "dropped_facts": len(analysis.get("dropped") or []),
        "assessment_status": (analysis.get("assessment") or {}).get("status"),
        "readiness_status": (analysis.get("readiness") or {}).get("status"),
    }
    result["analysis"] = analysis

    # 7. optional Jev SHADOW (never affects the analysis above)
    result["stages"]["jev_shadow"] = _run_jev_shadow(
        analysis,
        source=video,
        jev_evaluate_fn=jev_evaluate_fn,
        enabled=jev_shadow_enabled,
        root=root,
    )

    # 8. outcome (no-story is a valid result) + durable summary artifact
    result["outcome"] = _outcome_from(analysis)
    _persist_artifact(
        result, source=source, analysis=analysis, root=root, retrieved_at=retrieved_at
    )
    return result


def _persist_artifact(result, *, source, analysis, root=None, retrieved_at=None):
    """Persist the intake summary so the Workbench can display completed results."""
    directory = intake_store.artifacts_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source.video_id}.json"
    assessment = analysis.get("assessment") or {}
    readiness = analysis.get("readiness") or {}
    summary = {
        "video_id": source.video_id,
        "canonical_url": source.canonical_url,
        "title": source.title,
        "channel": source.channel,
        "outcome": result.get("outcome"),
        "generated_at": retrieved_at,
        "topics": len(analysis.get("topics") or []),
        "facts": len(analysis.get("facts") or []),
        "dropped_facts": len(analysis.get("dropped") or []),
        "assessment_status": assessment.get("status"),
        "readiness_status": readiness.get("status"),
        "transcript_hash": (result.get("video") or {}).get("transcript_hash"),
        "stages": result.get("stages"),
    }
    atomic_write(path, json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    result["artifacts"]["discovery_artifact"] = str(path)
    registry = intake_store.read_registry(root)
    record = registry.get(source.video_id)
    if record is not None:
        record["discovery_artifact"] = str(path)
        intake_store.save_registry(registry, root)


def _run_jev_shadow(analysis, *, source, jev_evaluate_fn, enabled, root=None):
    """Observe real cases; store under ignored runtime artifacts. No authority."""
    if not enabled:
        return {"status": "SKIPPED", "reason": "disabled"}
    if jev_evaluate_fn is None:
        return {"status": "NOT_AVAILABLE", "reason": "no Jev evaluator configured"}
    support = analysis.get("support_texts") or {}
    # Shadow both retained and deterministically-dropped facts: the rejects are
    # the semantic-rescue evidence (Part N). No auto-rescue either way.
    shadow_facts = [
        {
            "fact_id": fact["fact_id"],
            "text": fact.get("text"),
            "procedural_status": fact.get("procedural_status"),
            "fact_grounding_status": fact.get("fact_grounding_status"),
            "grounding_failures": fact.get("grounding_failures"),
            "support_text": support.get(fact["fact_id"]),
        }
        for fact in (analysis.get("facts") or []) + (analysis.get("dropped") or [])
    ]
    grounding_rows = jev_shadow.collect_fact_grounding(
        shadow_facts, evaluate_fn=jev_evaluate_fn, source=source
    )
    angle_rows = jev_shadow.collect_angle_signals(
        _angle_cases(analysis), evaluate_fn=jev_evaluate_fn, source=source
    )
    rescue = jev_shadow.rescue_candidates(grounding_rows)
    if grounding_rows:
        jev_shadow.write_rows(grounding_rows, _shadow_path(root, "intake_grounding_shadow.jsonl"))
    if angle_rows:
        jev_shadow.write_rows(angle_rows, _shadow_path(root, "intake_angle_shadow.jsonl"))
    if rescue:
        jev_shadow.write_rows(rescue, jev_shadow.semantic_rescue_path())
    return {
        "status": "OK",
        "grounding_cases": len(grounding_rows),
        "angle_cases": len(angle_rows),
        "rescue_candidates": len(rescue),
    }


def _angle_cases(analysis):
    candidates = analysis.get("candidates") or []
    facts = {f["fact_id"]: f for f in (analysis.get("facts") or [])}
    cases = []
    for candidate in candidates:
        cases.append(
            {
                "case_id": candidate.get("angle_id"),
                "proposition": candidate.get("new_proposition"),
                "supporting_facts": [
                    {"fact_id": fid, "text": (facts.get(fid) or {}).get("text")}
                    for fid in candidate.get("fact_ids") or []
                ],
                "deterministic_assessment": {
                    "eligible": candidate.get("eligible"),
                    "total": candidate.get("total"),
                    "semantic_status": candidate.get("semantic_status"),
                    "reason": candidate.get("reason"),
                },
            }
        )
    return cases


def _shadow_path(root, name):
    return Path(intake_store.intake_root(root)) / name
