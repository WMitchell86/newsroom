"""M2.7-9 Track B: LIVE_EDITORIAL_PILOT on fresh unpublished external leads.

Flow: upstream source (press release, municipality, event invite - NEVER a
published Chеrnomorie article) -> IdeaCard -> EvidencePacket (M2.3B contract,
with headline-number conflict annotations) -> suggested MODE (explainable
heuristic) -> VOICE_HOUSE default -> fresh grounded draft via the proven
M2.3B path (style retrieval = STYLE ONLY, semantic factual gate) -> editor
review. Every case carries full lineage.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.drafting import generate as gen
from editor_assistant.drafting.evidence import build_packet_from_record, validate_packet
from editor_assistant.drafting.prompt import PROMPT_VERSION, build_prompt
from editor_assistant.drafting.retrieval import retrieve_examples
from editor_assistant.workflow import angles
from editor_assistant.workflow import ideas as ideas_mod
from editor_assistant.workflow import modes as modes_mod
from editor_assistant.workflow import readiness as readiness_mod
from editor_assistant.workflow import research as research_mod
from editor_assistant.workflow.cases import CIRCULAR_NOTE, is_chernomorie_source

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "var" / "style_corpus" / "articles.jsonl"
ANALYSIS = ROOT / "var" / "style_analysis"
DEFAULT_VOICE = "VOICE_HOUSE"
OPT_IN_VOICE = "VOICE_DESISLAVA_RECENT"


class LiveError(ValueError):
    pass


def _unique_idea_id(prefix="LIVE"):
    """Collision-safe ID: UTC timestamp + monotonic nanos + uuid4 suffix.

    The seconds-resolution timestamp alone collided (LIV-01/LIV-03 and
    LIV-04/LIV-05 shared IDs when created within the same second).
    """
    n = datetime.now(timezone.utc)
    return (
        f"{prefix}-{n.strftime('%Y%m%d')}-{n.strftime('%H%M%S')}"
        f"-{time.monotonic_ns() % 1_000_000:06d}-{uuid.uuid4().hex[:8]}"
    )


def new_idea(
    *,
    source_type,
    source_url,
    title,
    what_changed,
    why_now="",
    location="",
    possible_angle="",
    created_at=None,
):
    """Register a fresh unpublished lead. Circular source guard applies."""
    if is_chernomorie_source(source_url):
        raise LiveError(CIRCULAR_NOTE)
    n = datetime.now(timezone.utc)
    return ideas_mod.make_idea(
        idea_id=_unique_idea_id(),
        created_at=created_at or n.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_type=source_type,
        source_url=source_url,
        source_reference="upstream source (unpublished material)",
        title=title,
        what_changed=what_changed,
        why_now=why_now,
        location=location,
        possible_angle=possible_angle,
        status="NEW",
    )


def _as_record(record):
    """Accept an ArticleRecord or a plain dict payload (CLI live-evidence JSON)."""
    if hasattr(record, "body"):
        return record
    from editor_assistant.style.corpus import ArticleRecord as _R

    return _R(
        article_id="live-lead",
        url=record.get("url", ""),
        headline=record.get("headline", ""),
        body=record.get("body", ""),
        quotes=tuple(record.get("quotes") or ()),
    )


def build_live_packet(idea, *, record, evidence_id, observed_at=None, bundle_path=None):
    """IdeaCard -> EvidencePacket from the lead's article record (facts only).

    `record` is an extracted ArticleRecord of the upstream source (fields as
    consumed by the M2.3 packet builder: headline/body/url/quotes). Applies
    the M2.3B headline-number conflict annotation on save/read.

    bundle_path: optional SourceBundle JSON. When given, every material fact
    must be traceable to a recorded claim of an opened PRIMARY/CORROBORATING
    source - claim-level provenance is attached and unverifiable facts raise
    instead of silently shipping unprovenanced.
    """
    packet = build_packet_from_record(
        _as_record(record),
        evidence_id=evidence_id,
        observed_at=observed_at or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    if bundle_path:
        bundle = research_mod.load_bundle(bundle_path)
        packet["provenance"] = research_mod.attach_bundle_refs(packet, bundle, strict=True)
    packet["source_type"] = idea["source_type"]
    validate_packet(packet)
    if packet.get("source_url") and is_chernomorie_source(packet["source_url"]):
        raise LiveError(CIRCULAR_NOTE)
    return packet


def dna_text():
    return json.loads((ANALYSIS / "site_dna.json").read_text(encoding="utf-8"))


def live_case_request(
    idea,
    packet,
    *,
    voice=DEFAULT_VOICE,
    mode=None,
    style_example_ids=(),
    retrieval_reason="",
    fallback_used=False,
):
    """Validate voice gating (HOUSE default, DESISLAVA explicit opt-in) and
    suggest a mode if none selected. Returns the prepared case inputs.

    Always records the tool suggestion (suggested_mode + reason); the
    selected mode may equal it (confirmed) or differ (editor override).
    """
    from editor_assistant.workflow.cases import _DEFAULT_VOICE, _OPT_IN_VOICE

    if voice not in (_DEFAULT_VOICE, _OPT_IN_VOICE):
        raise LiveError(f"unknown voice: {voice!r} (DESISLAVA is explicit opt-in)")
    assessment = angles.check_angle_gate({**packet, "source_type": idea["source_type"]})
    if assessment and assessment["status"] == angles.NO_ANGLE:
        idea["status"] = angles.NO_ANGLE
        return {"status": angles.NO_ANGLE, "reason": assessment["reason"]}
    suggestion = modes_mod.suggest_mode(packet)
    suggested_mode = suggestion["suggested_mode"]
    suggestion_reason = suggestion["reason"]
    if mode is None:
        mode, mode_suggested = suggested_mode, True
    else:
        mode_suggested = mode != suggested_mode
    idea["status"] = "DRAFT_REQUESTED"
    return {
        "idea_id": idea["idea_id"],
        "evidence_id": packet["evidence_id"],
        "voice": voice,
        "mode": mode,
        "mode_suggested": mode_suggested,
        "suggested_mode": suggested_mode,
        "suggestion_reason": suggestion_reason,
        "style_example_ids": list(style_example_ids),
        "retrieval_reason": retrieval_reason,
        "fallback_used": fallback_used,
    }


def _load_profile(profile_id):
    profiles = json.loads((ANALYSIS / "style_profiles.json").read_text(encoding="utf-8"))
    for p in profiles:
        if p["profile_id"] == profile_id:
            return p
    raise LiveError(f"missing style profile: {profile_id}")


def live_readiness(packet, *, mode=None, editor_override=None):
    """Editorial readiness decision for a LIVE packet (M2R §24).

    Composes newsworthiness + evidence sufficiency + reader-interest plan into
    one inspectable record. `mode` defaults to the deterministic suggestion.
    `editor_override` (FORCE_DRAFT | REQUEST_MORE_RESEARCH | REJECT_STORY) is
    recorded, never silent (§32): a forced draft proceeds despite RESEARCH_MORE/
    INSUFFICIENT with the override stored on the record.
    """
    suggestion = modes_mod.suggest_mode(packet)
    if mode is None:
        mode = suggestion["suggested_mode"]
    record = readiness_mod.assess_readiness(packet, mode=mode)
    if editor_override:
        if editor_override not in ("FORCE_DRAFT", "REQUEST_MORE_RESEARCH", "REJECT_STORY"):
            raise LiveError(f"unknown editor override: {editor_override!r}")
        record = readiness_mod.apply_editor_override(
            record, action=editor_override, reason=f"editor override: {editor_override}"
        )
    return record


def live_generate_draft(
    packet,
    *,
    voice,
    mode,
    api_key=None,
    timeout=240,
    force_draft=False,
    editor_override_reason=None,
):
    """Fresh grounded draft via the proven M2.3B path.

    The editor trigger is explicit: callers must pass an idea whose status is
    DRAFT_REQUESTED (see cli.live_generate). Reuses: sectioned prompt, style
    retrieval (STYLE ONLY), lexical + semantic factual gates, deterministic
    originality (no-copy) guard, full lineage.
    No auto-republish, no regeneration loop beyond the M2.3B single-attempt
    policy.

    M2R: the readiness layer gates drafting - ONLY DRAFT_READY proceeds
    automatically; every other status is a refusal or needs the editor's
    explicit forced override, and an unknown status fails closed (it must
    never reach generation by falling through the guard). RESEARCH_MORE
    returns the readiness record so the caller can run targeted enrichment;
    NO_PUBLISHABLE_ANGLE refuses to fabricate a weak article (§25) and is
    never forceable. `force_draft=True` overrides RESEARCH_MORE /
    INSUFFICIENT / EDITOR_DECISION_REQUIRED and is recorded on the result
    (§32) - it never silently pretends sufficiency.
    """
    assessment = angles.check_angle_gate(packet)
    if assessment:
        if assessment["status"] == angles.NO_ANGLE:
            return {"status": angles.NO_ANGLE, "reason": assessment["reason"]}
        packet = angles.selected_angle_packet(packet, assessment)
    readiness = readiness_mod.assess_readiness(packet, mode=mode)
    status = readiness["status"]
    if status == readiness_mod.NO_ANGLE:
        return {
            "status": readiness_mod.NO_ANGLE,
            "reason": readiness["reason"],
            "readiness": readiness,
        }
    if status == readiness_mod.DRAFT_READY:
        pass  # §24: only DRAFT_READY proceeds automatically
    elif status == readiness_mod.RESEARCH_MORE and not force_draft:
        return {
            "status": readiness_mod.RESEARCH_MORE,
            "reason": readiness["reason"],
            "readiness": readiness,
        }
    elif status in (
        readiness_mod.RESEARCH_MORE,
        readiness_mod.INSUFFICIENT,
        readiness_mod.EDITOR_DECISION,
    ):
        if not force_draft:
            raise LiveError("editor decision required before drafting from weak evidence")
        readiness = readiness_mod.apply_editor_override(
            readiness, action="FORCE_DRAFT", reason=editor_override_reason
        )
    else:
        # Fail closed: an unhandled readiness state must never reach generation
        # by falling through this guard (it would silently draft).
        raise LiveError(f"unexpected readiness status {status!r} - refusing to draft")
    voice_profile = _load_profile(voice)
    mode_profile = _load_profile(mode)
    examples = retrieve_examples(
        packet, voice=voice, mode=mode, corpus_path=CORPUS, analysis_dir=ANALYSIS
    )
    hook = readiness["reader_interest"]
    prompt_spec = build_prompt(
        packet,
        site_dna=dna_text(),
        voice_profile=voice_profile,
        mode_profile=mode_profile,
        style_examples=examples,
        task_extra=readiness_mod.hook_task_extra(hook),
    )
    raw, _meta = gen.call_model(prompt_spec["text"], api_key=api_key, timeout=timeout, role="draft")
    draft = gen.parse_draft_json(raw)
    lexical = gen.audit_claims(draft["body"], packet, style_texts=[e["headline"] for e in examples])
    semantic = gen.verify_claims_semantic(packet, draft["body"], api_key=api_key, timeout=timeout)
    gate = "FACTUAL_GATE_PASS" if semantic["pass"] else "FACTUAL_GATE_REVIEW"
    # M4F F5: the draft must differ from the source — deterministic, offline.
    originality = gen.originality_check(draft["body"], packet.get("source_text", ""))
    lineage = gen.make_lineage(
        draft_id=gen.draft_id_for(packet["evidence_id"], voice, mode, PROMPT_VERSION),
        evidence_id=packet["evidence_id"],
        voice_id=voice,
        mode_id=mode,
        style_example_ids=[e["article_id"] for e in examples],
        prompt_version=PROMPT_VERSION,
    )
    return {
        "draft": draft,
        "lineage": lineage,
        "lexical": lexical,
        "semantic": semantic,
        "factual_gate": gate,
        "originality": originality,
        "readiness": readiness,
        "retrieval": {
            "examples": examples,
            "retrieval_reason": "same VOICE+MODE preferred (M2.3 rules)",
            "fallback_used": False,
        },
    }
