"""M3A workbench service layer: the ONLY module that writes.

Rules (harness M3A):
* canonical writes pass through the existing validated workflow contracts
  (`record_editor_final` + `save_cases`, readiness override on the live
  evidence row) — never raw JSONL edits;
* the editor working copy is a separate non-authoritative store; saving it
  can never finalize, publish or touch the immutable AI draft;
* finalization is explicit and refuses stale working copies (a working copy
  bound to an older draft generation);
* all workbench actions land in a minimal append-only audit log.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from editor_assistant.workflow import cases as cases_mod
from editor_assistant.workflow import live_store
from editor_assistant.workflow import readiness as readiness_mod
from editor_assistant.workflow.cases import (
    READINESS_ANSWER_KEYS,
    READINESS_OUTCOMES,
    TRACK_DRYRUN,
    TRACK_LIVE,
)

ROOT = Path(__file__).resolve().parents[4]


def workflow_dir():
    """Runtime dir; overridable for tests (never read/write outside it)."""
    return Path(
        os.environ.get("WB_EDITORIAL_WORKFLOW_DIR") or (ROOT / "var" / "editorial_workflow")
    )


def cases_path():
    return workflow_dir() / "cases.jsonl"


def ideas_path():
    return workflow_dir() / "ideas.jsonl"


def live_evidence_path():
    return workflow_dir() / "live_evidence.jsonl"


def working_dir():
    return workflow_dir() / "editor_working"


def audit_path():
    return workflow_dir() / "workbench_actions.jsonl"


class WorkbenchError(ValueError):
    pass


class StaleDraftError(WorkbenchError):
    """Working copy is bound to an older AI draft generation (harness §11)."""


# The server is threaded, and several actions are read-modify-write over shared
# JSONL stores (read cases -> mutate -> rewrite the file). Serialize those.
_MUTATION_LOCK = threading.RLock()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write(path, data):
    """Atomic write: temp file in the same dir + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ---------- minimal audit (harness §19: case_id, timestamp, action only) ----------


def record_action(action, case_id):
    row = {"action": action, "case_id": case_id, "timestamp": _now()}
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def read_actions(case_id=None):
    path = audit_path()
    if not path.exists():
        return []
    out = []
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        if case_id is None or row.get("case_id") == case_id:
            out.append(row)
    return out


# ---------- editor working copy (non-authoritative, harness §10) ----------


def load_working_copy(case_id):
    """Read the working copy; a corrupt/absent file means "no working copy".

    The working copy is non-authoritative, so a truncated file (crash, manual
    edit) must never wedge a case page or block every future save.
    """
    path = working_dir() / f"{case_id}.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def save_working_copy(case, *, headline, body, review_answers=None, accept_new_base=False):
    """Save the non-authoritative working copy. Never touches canonical state.

    Stale-edit protection (harness §11): if the working copy already exists and
    was started from an older AI draft generation, the save keeps that original
    base instead of silently re-basing onto the new draft. Re-basing requires an
    explicit `accept_new_base=True` (an editor action in the UI). The editor's
    text is always persisted, so no work is lost either way.
    """
    answers = {k: v for k, v in dict(review_answers or {}).items() if v}
    unknown = [k for k in answers if k not in READINESS_ANSWER_KEYS]
    if unknown:
        raise WorkbenchError(
            f"unknown working-copy answer keys {unknown} (use {READINESS_ANSWER_KEYS})"
        )
    if case.get("final_text"):
        raise WorkbenchError(
            f"{case['case_id']} е вече финализиран — работно копие не може да се запази"
        )
    with _MUTATION_LOCK:
        existing = load_working_copy(case["case_id"])
        base = case["draft_id"]
        if existing and not accept_new_base:
            base = existing.get("base_draft_id") or base
        doc = {
            "base_draft_id": base,
            "body": body,
            "case_id": case["case_id"],
            "headline": headline,
            "review_answers": answers,
            "updated_at": _now(),
        }
        atomic_write(
            working_dir() / f"{case['case_id']}.json",
            json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        )
        record_action("working_copy_saved", case["case_id"])
    return doc


def working_copy_is_stale(case, wc):
    """True when the working copy started from an older AI draft generation."""
    if not wc:
        return False
    return wc.get("base_draft_id") != case.get("draft_id")


# ---------- read-only views over the canonical stores ----------


def _live_evidence_rows():
    """Canonical store reader (workflow/live_store.py), same store as the CLI."""
    return live_store.read_live_evidence(live_evidence_path())


def _live_evidence_save(row):
    """Canonical store writer (workflow/live_store.py): atomic, deterministic."""
    live_store.save_live_evidence_row(row, live_evidence_path())


def intake_registry():
    """M3B intake registry (display only; writes are CLI-only)."""
    from editor_assistant.workflow import intake_store

    return intake_store.read_registry()


def intake_view(video_id, record):
    """Flatten one registry row + its discovery artifact for display."""
    record = record or {}
    artifact = {}
    path = record.get("discovery_artifact")
    if path and Path(path).exists():
        try:
            artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            artifact = {}
    return {
        "video_id": video_id,
        "canonical_url": record.get("canonical_url") or artifact.get("canonical_url"),
        "title": artifact.get("title") or record.get("title"),
        "outcome": artifact.get("outcome"),
        "generated_at": artifact.get("generated_at") or record.get("last_checked_at"),
        "topics": artifact.get("topics", 0),
        "facts": artifact.get("facts", 0),
        "dropped_facts": artifact.get("dropped_facts", 0),
        "assessment_status": artifact.get("assessment_status"),
        "readiness_status": artifact.get("readiness_status"),
    }


def load_cases():
    return cases_mod.read_cases(cases_path()) if cases_path().exists() else []


# ---------- evidence-only special cases (no case row, e.g. NO_PUBLISHABLE_ANGLE) ----------

# Readiness statuses that must be reviewable even when the workflow never
# opened a case for the evidence (no draft was ever produced).
_EVIDENCE_ONLY_STATUSES = ("NO_PUBLISHABLE_ANGLE", "RESEARCH_MORE", "EDITOR_DECISION_REQUIRED")


def case_id_from_evidence(evidence_id):
    """Derive the editor-facing case id for an evidence-only special case.

    Stored evidence ids are not uniform (`LIV-06-EVIDENCE`, `LIV03-EVIDENCE`);
    this only normalizes the route/display id — stored values stay untouched.
    """
    base = (evidence_id or "").removesuffix("-EVIDENCE")
    match = re.match(r"^([A-Za-z]+)(\d+)$", base)
    return f"{match.group(1)}-{match.group(2)}" if match else base


def _pseudo_case(row):
    """A review/decision-only case view for a special evidence row with no case row."""
    readiness = row.get("readiness") or {}
    decision = row.get("workbench_decision") or {}
    return {
        "case_id": case_id_from_evidence(row["evidence_id"]),
        "idea_id": row.get("idea_id", ""),
        "evidence_id": row["evidence_id"],
        "track": TRACK_LIVE,
        "source_url": (row.get("packet") or {}).get("source_url", ""),
        "draft_id": "",
        "voice_selected": "",
        "mode_suggested": "",
        "mode_selected": readiness.get("mode") or "",
        "mode_suggestion_reason": "",
        "mode_changed": False,
        "draft_headline": "",
        "draft_headlines": [],
        "final_headline": "",
        "draft_text": "",
        "final_text": "",
        "editor_outcome": "",
        "editing_weight": "",
        "time_saved_estimate": "",
        "prefer_ai_start": "",
        "published_or_ready": "",
        "notes": "",
        "factual_gate": "",
        "audit": {},
        "workbench_decision": decision,
        "decision_updated_at": decision.get("updated_at", ""),
        "_evidence_only": True,
    }


def _evidence_only_cases():
    cases = []
    seen = {c.get("evidence_id") for c in load_cases()}
    for row in _live_evidence_rows().values():
        if row["evidence_id"] in seen:
            continue
        readiness = row.get("readiness") or {}
        status = readiness.get("status")
        post_loop = readiness.get("post_loop_decision")
        if status in _EVIDENCE_ONLY_STATUSES or post_loop == "EDITOR_DECISION_REQUIRED":
            cases.append(_pseudo_case(row))
    return cases


def all_cases():
    """Canonical cases plus evidence-only special cases (never hardcoded ids)."""
    return load_cases() + _evidence_only_cases()


def find_case(case_id):
    for case in all_cases():
        if case["case_id"] == case_id:
            return case
    return None


def case_draft(case):
    """Resolve the current immutable AI draft for a case (live store first)."""
    if case.get("track") == TRACK_LIVE:
        row = _live_evidence_rows().get(case["evidence_id"])
        if row and row.get("lineage", {}).get("draft_id") == case.get("draft_id"):
            return row
    for sup in sorted((workflow_dir() / "superseded").glob(f"{case['case_id']}-*.json")):
        try:
            row = json.loads(sup.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if row.get("lineage", {}).get("draft_id") == case.get("draft_id"):
            return row
    return None


def evidence_row_for_case(case):
    return _live_evidence_rows().get(case["evidence_id"]) if case.get("evidence_id") else None


def _case_readiness(case, evidence_rows):
    """Case readiness state from the stored contract (never recomputed here)."""
    if case.get("readiness"):
        return case["readiness"]
    row = evidence_rows.get(case.get("evidence_id"))
    if row:
        return row.get("readiness") or {}
    return {}


def special_kind(case, readiness):
    """One of: None | 'nostory' | 'decision' | 'research' (UI routing).

    A recorded editor decision keeps the case in its special bucket: recording
    "не публикувай" overwrites the readiness `post_loop_decision`, so without
    this the case would fall back into the "за редакция" queue and ask for a
    finalize it explicitly rejected.
    """
    if case.get("final_text"):
        return None
    status = readiness.get("status") or ""
    if status == "NO_PUBLISHABLE_ANGLE":
        return "nostory"
    decision = (case.get("workbench_decision") or {}).get("decision")
    if decision in ("REJECT_STORY", "NO_STORY_CONFIRMED"):
        return "nostory"
    if decision == "REQUEST_MORE_RESEARCH":
        return "research"
    if (
        status == "EDITOR_DECISION_REQUIRED"
        or readiness.get("post_loop_decision") == "EDITOR_DECISION_REQUIRED"
    ):
        return "decision"
    if status == "RESEARCH_MORE" and not case.get("draft_id"):
        return "research"
    return None


def queue_filter(kind, final):
    """Which queue filter a case belongs to (single bucket, first match).

    `special_kind` is the single source of classification: a case whose page
    offers only a decision must not sit in the editing bucket, and vice versa.
    A stale working copy stays in the editing queue — it needs the editor's
    attention, not a bucket of its own.
    """
    if final:
        return "finalized"
    return kind if kind in ("nostory", "research", "decision") else "edit"


def queue():
    """Rows for the editorial queue. LIVE pilot cases first, benchmark after."""
    evidence_rows = _live_evidence_rows()
    rows = []
    for case in all_cases():
        readiness = _case_readiness(case, evidence_rows)
        wc = load_working_copy(case["case_id"])
        kind = special_kind(case, readiness)
        final = bool(case.get("final_text"))
        stale = working_copy_is_stale(case, wc)
        updated_at = ""
        row = case_draft(case)
        if row:
            updated_at = str(row.get("lineage", {}).get("generated_at", ""))[:19]
        if wc:
            updated_at = wc.get("updated_at") or updated_at
        if case.get("decision_updated_at"):
            updated_at = case["decision_updated_at"][:19]
        rows.append(
            {
                "case_id": case["case_id"],
                "case": case,
                "readiness": readiness,
                "readiness_status": readiness.get("status") or "",
                "kind": kind,
                "filter": queue_filter(kind, final),
                "final": final,
                "gate": case.get("factual_gate") or "",
                "mode": case.get("mode_selected") or "",
                "track": case.get("track") or TRACK_LIVE,
                "headline": case.get("draft_headline") or (case.get("final_headline") or ""),
                "wc": wc,
                "stale": stale,
                "decision": case.get("workbench_decision") or {},
                "updated_at": updated_at,
            }
        )
    live = [r for r in rows if r["track"] == TRACK_LIVE]
    dryrun = [r for r in rows if r["track"] == TRACK_DRYRUN]
    return {"live": live, "dryrun": dryrun}


# ---------- case detail view (four surfaces: draft, sources, status, editor) ----------


def _domain(url):
    url = url or ""
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix) :].split("/")[0]
    return ""


def _safe_href(url):
    """Allow-list schemes; anything else renders as plain text (never a link)."""
    url = (url or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    return ""


def research_sources(case):
    """Sources from the stored research record(s) for the case's evidence."""
    out = []
    research_dir = workflow_dir() / "research"
    ev = case.get("evidence_id") or ""
    candidates = []
    if ev:
        candidates.append(research_dir / f"{case_id_from_evidence(ev)}.json")
        candidates.append(research_dir / f"{case['case_id']}.json")
        candidates.append(research_dir / f"{ev.replace('-EVIDENCE', '')}.json")
    seen = set()
    for path in candidates:
        if not path.exists() or path in seen:
            continue
        seen.add(path)
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for src in rec.get("sources") or []:
            if not isinstance(src, dict):
                continue
            claims = [str(claim) for claim in _as_list(src.get("relevant_claims"))]
            out.append(
                {
                    "source_id": src.get("source_id", ""),
                    "name": src.get("source_name") or src.get("title") or src.get("source_id", ""),
                    "type": src.get("source_type", ""),
                    "authority": src.get("authority", ""),
                    "url": _safe_href(src.get("url", "")),
                    "url_raw": src.get("url", ""),
                    "domain": _domain(src.get("url", "")),
                    "published_at": src.get("published_at", ""),
                    "retrieved_at": (
                        src.get("retrieved_at") or rec.get("research_completed_at") or ""
                    )[:19],
                    "claims": claims,
                    "warning": "",
                    "trust": "",
                    "note": src.get("content_reference", ""),
                }
            )
        if out:
            break
    return out


def _as_list(value):
    """Normalize a possibly-missing / possibly-scalar store field into a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _norm_locs(locs):
    """Normalize packet provenance locators to `[{locator, source_id}]`."""
    out = []
    for loc in _as_list(locs):
        if isinstance(loc, dict):
            out.append(
                {"locator": str(loc.get("locator", "")), "source_id": str(loc.get("source_id", ""))}
            )
        elif isinstance(loc, str):
            out.append({"locator": loc, "source_id": ""})
    return out


def _packet_sources(row):
    """Packet-level source (e.g. transcript) + per-fact locator provenance.

    Tolerant of malformed stored shapes: a bad packet must degrade to less
    detail, never to a 500 on the case page.
    """
    packet = row.get("packet") or {}
    prov = packet.get("provenance") or {}
    raw_attached = prov.get("attached") or {}
    attached = {}
    if isinstance(raw_attached, dict):
        for fact_id, locs in raw_attached.items():
            normalized = _norm_locs(locs)
            if normalized:
                attached[fact_id] = normalized
    sources_used = [str(s) for s in _as_list(prov.get("sources_used"))]
    facts = packet.get("facts") or []
    by_fact = {}
    for fact in facts if isinstance(facts, list) else []:
        if not isinstance(fact, dict):
            continue
        locs = _norm_locs(fact.get("source_refs"))
        if not locs and fact.get("source_reference"):
            locs = [{"locator": str(fact["source_reference"]), "source_id": ""}]
        by_fact[fact.get("id", "")] = {"text": fact.get("text", ""), "locators": locs}
    # which research source each source_id maps to (for name/url joining)
    name_by_id = research_sources_by_id(row)
    return {
        "source_ids": sources_used,
        "attached": attached,
        "facts": by_fact,
        "names": name_by_id,
        "unknowns": [str(u) for u in (packet.get("unknowns") or [])],
    }


def research_sources_by_id(row):
    """Join packet source_ids (S-TR, S-WEB:...) with research source names."""
    mapping = {}
    ev = row.get("evidence_id", "")
    research_dir = workflow_dir() / "research"
    candidates = []
    for cand in (case_id_from_evidence(ev), ev.replace("-EVIDENCE", ""), row.get("case_id", "")):
        if cand:
            candidates.append(research_dir / f"{cand}.json")
    for path in candidates:
        if not path.exists():
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for src in rec.get("sources") or []:
            if not isinstance(src, dict):
                continue
            mapping[src.get("source_id", "")] = {
                "name": src.get("source_name") or src.get("title") or src.get("source_id", ""),
                "url": _safe_href(src.get("url", "")),
                "domain": _domain(src.get("url", "")),
                "authority": src.get("authority", ""),
                "trust": "",
                "retrieved_at": (src.get("retrieved_at") or "")[:19],
            }
        if mapping:
            break
    return mapping


def _transcript_trust(evidence_row, case):
    """Trust level for editor-supplied transcript cases (stored convention)."""
    packet = (evidence_row or {}).get("packet") or {}
    url = packet.get("source_url", "") or ""
    if url.startswith("transcript://editor-supplied"):
        # editor-supplied committee transcripts were auto-caption intake (M2S)
        return "AUTO_CAPTION"
    if packet.get("source_type") in ("council_transcript", "transcript"):
        return "AUTO_CAPTION"
    return ""


def case_view(case_id):
    """Everything the case page needs, read from the stored contracts."""
    case = find_case(case_id)
    if not case:
        return None
    evidence_rows = _live_evidence_rows()
    readiness = _case_readiness(case, evidence_rows)
    kind = special_kind(case, readiness)
    wc = load_working_copy(case_id)
    audit = case.get("audit") or {}
    semantic = audit.get("semantic") or {}
    warnings = []
    n_unsupported = int(semantic.get("n_unsupported") or 0)
    if n_unsupported:
        warnings.append(
            {
                "level": "review",
                "text": (
                    f"⚠ Нужна проверка: {n_unsupported} твърдения в черновата не са "
                    "достатъчно подкрепени от използваните източници. "
                    "Прегледайте ги преди финализиране."
                ),
            }
        )
    lexical_unsupported = (audit.get("lexical") or {}).get("unsupported") or []
    for item in lexical_unsupported:
        text = item if isinstance(item, str) else str(item.get("sentence", item))
        warnings.append(
            {
                "level": "review",
                "text": f"⚠ Нужна проверка: изречение без директна опора в източниците — „{text[:200]}“.",
            }
        )
    evidence_row = evidence_rows.get(case.get("evidence_id") or "")
    duplicates = evidence_row.get("duplicate_check") if evidence_row else None
    if duplicates and duplicates.get("status") not in (None, "NO_DUPLICATE"):
        warnings.append(
            {
                "level": "info",
                "text": (
                    "Проверка за дублирано покритие: "
                    + str(duplicates.get("status", ""))
                    + (" — " + duplicates["note"] if duplicates.get("note") else "")
                ),
            }
        )
    unknowns = [str(u) for u in ((evidence_row or {}).get("packet", {}).get("unknowns") or [])]
    for unknown in unknowns:
        warnings.append(
            {"level": "info", "text": f"Непознати/неясни данни от доказателствата: {unknown}"}
        )
    # research warnings from the evidence readiness loop
    if evidence_row and evidence_row.get("readiness_rounds"):
        for round_rec in evidence_row["readiness_rounds"].get("research_rounds", []):
            for src in round_rec.get("sources", []):
                if src.get("note"):
                    warnings.append({"level": "info", "text": f"Проучване: {src['note']}"})
    # transcript trust (harness §17)
    trust = ""
    trust_note = ""
    if evidence_row:
        trust = _transcript_trust(evidence_row, case)
        if trust == "AUTO_CAPTION":
            trust_note = (
                "Източникът е автоматичен YouTube транскрипт и може да съдържа грешки "
                "в разпознаването. Материали с висок риск (числа, имена, решения, цитати) "
                "изискват потвърждение от друг източник преди публикуване."
            )
    return {
        "case": case,
        "case_id": case_id,
        "readiness": readiness,
        "kind": kind,
        "wc": wc,
        "stale": working_copy_is_stale(case, wc),
        "draft": {
            "headline": case.get("draft_headline", ""),
            "headlines": case.get("draft_headlines") or [case.get("draft_headline", "")],
            "body": case.get("draft_text", ""),
            "draft_id": case.get("draft_id", ""),
            "voice": case.get("voice_selected", ""),
            "mode": case.get("mode_selected", ""),
        },
        "gate": case.get("factual_gate", ""),
        "warnings": warnings,
        "sources": research_sources(case),
        "packet": _packet_sources(evidence_row)
        if evidence_row
        else {"facts": {}, "attached": {}, "names": {}, "source_ids": [], "unknowns": []},
        "trust": trust,
        "trust_note": trust_note,
        "evidence_readiness": (evidence_row or {}).get("readiness") or {},
        "research_rounds": (evidence_row or {}).get("readiness_rounds") or {},
        "duplicate_check": duplicates or {},
        "decision": case.get("workbench_decision") or {},
    }


# ---------- write actions (thin: through the existing validated contracts) ----------


def finalize(
    case_id,
    *,
    headline,
    body,
    editor_outcome,
    editing_weight,
    time_saved_estimate="",
    prefer_ai_start="",
    published_or_ready="",
    notes="",
    readiness_outcome="",
    readiness_note="",
    readiness_answers=None,
    base_draft_id=None,
):
    """Explicit editor finalization through the existing validated contract.

    Refuses: unknown case, no AI draft, already-finalized case, empty
    headline/body, stale generation, and any validation error raised by
    cases.record_editor_final. The AI draft fields are never mutated.

    Stale generation (harness §11) is evaluated against BOTH the working copy's
    recorded base and any base submitted with the request, so a stale working
    copy cannot be finalized by re-submitting the current draft id.
    """
    with _MUTATION_LOCK:
        all_cases = load_cases()
        case = next((c for c in all_cases if c["case_id"] == case_id), None)
        if not case:
            if any(c["case_id"] == case_id for c in _evidence_only_cases()):
                raise WorkbenchError(
                    f"{case_id}: няма AI чернова за финализиране "
                    "(случаят е само за редакторско решение)"
                )
            raise WorkbenchError(f"unknown case_id: {case_id}")
        if case.get("final_text"):
            raise WorkbenchError(
                f"{case_id} е вече финализиран — черновата и финалът са неизменими"
            )
        if case.get("track") == TRACK_DRYRUN:
            raise WorkbenchError(
                f"{case_id} е {TRACK_DRYRUN}: усилийни показатели (време/тежест/резултат) "
                "не са валидни за еталонни случаи"
            )
        if not (headline or "").strip() or not (body or "").strip():
            raise WorkbenchError(
                "Финализирането изисква заглавие и текст. "
                "Ако материалът няма новинарски ъгъл, запишете редакторско решение."
            )
        wc = load_working_copy(case_id)
        current_draft_id = case.get("draft_id")
        bases = [b for b in (base_draft_id, (wc or {}).get("base_draft_id")) if b]
        if any(base != current_draft_id for base in bases):
            raise StaleDraftError(
                "Междувременно е генерирана по-нова AI версия. "
                "Прегледайте разликите преди финализиране."
            )
        answers = {k: v for k, v in dict(readiness_answers or {}).items() if v}
        cases_mod.record_editor_final(
            case,
            final_headline=headline,
            final_text=body,
            editor_outcome=editor_outcome,
            editing_weight=editing_weight,
            time_saved_estimate=time_saved_estimate,
            prefer_ai_start=prefer_ai_start,
            published_or_ready=published_or_ready,
            notes=notes,
            readiness_outcome=readiness_outcome,
            readiness_note=readiness_note,
            readiness_answers=answers,
        )
        cases_mod.save_cases(all_cases, cases_path())
        record_action("editor_final_submitted", case_id)
        return case


def record_decision(
    case_id, *, decision, reason="", readiness_outcome="", readiness_note="", missed_angle=""
):
    """Record a special-case editor decision (no article body required).

    Maps UI choices through the existing readiness override contract on the
    live evidence row (same store the CLI writes), plus a case-level decision
    record. M3A only records; it does not execute research (M3C).
    """
    with _MUTATION_LOCK:
        return _record_decision_locked(
            case_id,
            decision=decision,
            reason=reason,
            readiness_outcome=readiness_outcome,
            readiness_note=readiness_note,
            missed_angle=missed_angle,
        )


def _record_decision_locked(
    case_id, *, decision, reason="", readiness_outcome="", readiness_note="", missed_angle=""
):
    all_cases = load_cases()
    case = next((c for c in all_cases if c["case_id"] == case_id), None)
    evidence_only = None
    if case is None:
        evidence_only = next((c for c in _evidence_only_cases() if c["case_id"] == case_id), None)
        if evidence_only is None:
            raise WorkbenchError(f"unknown case_id: {case_id}")
    if case is not None and case.get("final_text"):
        raise WorkbenchError(f"{case_id} е вече финализиран")
    if not decision:
        raise WorkbenchError("изборът на решение е задължителен")
    mapping = {
        "FORCE_BRIEF_FROM_VERIFIED": "FORCE_DRAFT",
        "REQUEST_MORE_RESEARCH": "REQUEST_MORE_RESEARCH",
        "REJECT_STORY": "REJECT_STORY",
        "NO_STORY_CONFIRMED": "REJECT_STORY",
        "ANGLE_CHANGED": "CHANGE_ANGLE",
    }
    override_action = mapping.get(decision)
    if override_action is None:
        raise WorkbenchError(f"непознато решение: {decision!r}")
    reason = (reason or "").strip() or (missed_angle or "").strip()
    if not reason:
        raise WorkbenchError("решението изисква причина (записва се за проверимост)")
    if readiness_outcome and readiness_outcome not in READINESS_OUTCOMES:
        raise WorkbenchError(
            f"невалиден readiness_outcome: {readiness_outcome!r} (използвайте {READINESS_OUTCOMES})"
        )
    evidence_row = (
        _live_evidence_rows().get(evidence_only["evidence_id"])
        if evidence_only is not None
        else evidence_row_for_case(case)
    )
    if evidence_row is not None and evidence_row.get("readiness"):
        updated = readiness_mod.apply_editor_override(
            dict(evidence_row["readiness"]), action=override_action, reason=reason
        )
        updated["post_loop_decision"] = (
            "EDITOR_DECISION_REQUIRED"
            if decision == "REQUEST_MORE_RESEARCH"
            else updated.get("post_loop_decision", "")
        )
        if decision in ("REJECT_STORY", "NO_STORY_CONFIRMED"):
            updated["post_loop_decision"] = "REJECTED_BY_EDITOR"
        evidence_row["readiness"] = updated
        _live_evidence_save(evidence_row)
    decision_doc = {
        "decision": decision,
        "readiness_outcome": readiness_outcome,
        "readiness_note": readiness_note,
        "missed_angle": missed_angle,
        "reason": reason,
        "updated_at": _now(),
    }
    if case is not None:
        case["workbench_decision"] = decision_doc
        case["decision_updated_at"] = decision_doc["updated_at"]
        cases_mod.save_cases(all_cases, cases_path())
    else:
        # An evidence-only special case has no case row: the decision is stored
        # on the same evidence row the readiness override already touched.
        evidence_row["workbench_decision"] = decision_doc
        _live_evidence_save(evidence_row)
        evidence_only["workbench_decision"] = decision_doc
        evidence_only["decision_updated_at"] = decision_doc["updated_at"]
        case = evidence_only
    record_action("editor_decision_submitted", case_id)
    return case


# ---------- M4F: ideas -> prepared cases -> drafts («Статии» bridge) ----------
#
# The daily loop used to end at "story reviewed". These functions expose the
# existing M2.3B drafting contracts (ideas.request_draft, live.live_case_request,
# live.live_generate_draft) to the workbench UI without changing them: the same
# validation, the same stores, the same immutability rules. The AI draft store
# stays append-only; generation always goes through live_generate_draft.

#: The four editing modes the prompt layer knows (workflow/modes.py). The UI
#: select offers exactly these; anything else is rejected before a model call.
EDITING_MODES = (
    "MODE_BRIEF",
    "MODE_STANDARD_NEWS",
    "MODE_EVENT_PREVIEW",
    "MODE_CULTURE_FEATURE",
)


def live_drafts_path():
    return workflow_dir() / "live_drafts.jsonl"


def load_ideas():
    from editor_assistant.workflow import ideas as ideas_mod

    path = ideas_path()
    return ideas_mod.read_ideas(path) if path.exists() else []


def save_ideas(ideas):
    from editor_assistant.workflow import ideas as ideas_mod

    ideas_mod.save_ideas(ideas, ideas_path())


def load_live_rows():
    from editor_assistant.workflow import live_store

    return live_store.read_live_evidence(live_evidence_path())


def _save_live_row(row):
    from editor_assistant.workflow import live_store

    live_store.save_live_evidence_row(row, live_evidence_path())


def _load_draft_rows():
    """AI drafts are append-only JSONL; reading tolerates an absent file."""
    path = live_drafts_path()
    if not path.exists():
        return []
    out = []
    for line in path.open(encoding="utf-8"):
        if line.strip():
            out.append(json.loads(line))
    return out


def articles_view():
    """Rows for the «Статии» page: ideas joined with packets, drafts, cases.

    Purely read-only: every mutation the page offers goes through the explicit
    service functions below (and lands in the audit log).
    """
    ideas = load_ideas()
    rows = load_live_rows()
    drafts = _load_draft_rows()
    cases = load_cases()
    cases_by_evidence = {}
    for case in cases:
        if case.get("track") == TRACK_LIVE and case.get("evidence_id"):
            cases_by_evidence.setdefault(case["evidence_id"], case)
    drafts_by_idea = {}
    for draft in drafts:
        drafts_by_idea.setdefault(draft.get("idea_id", ""), []).append(draft)
    evidence_by_idea = {}
    for row in rows.values():
        evidence_by_idea.setdefault(row.get("idea_id", ""), []).append(row)
    idea_rows = []
    for idea in ideas:
        evidence = []
        for row in evidence_by_idea.get(idea["idea_id"], ()):
            packet = row.get("packet") or {}
            prepared = row.get("prepared")
            case = cases_by_evidence.get(row["evidence_id"])
            evidence.append(
                {
                    "evidence_id": row["evidence_id"],
                    "observed_at": row.get("observed_at", ""),
                    "fact_count": len(packet.get("facts") or ()),
                    "prepared": bool(prepared),
                    "mode": (prepared or {}).get("mode", ""),
                    "mode_suggested": bool((prepared or {}).get("mode_suggested")),
                    "suggested_mode": (prepared or {}).get("suggested_mode", ""),
                    "suggestion_reason": (prepared or {}).get("suggestion_reason", ""),
                    "drafts": [
                        {
                            "draft_id": (d.get("lineage") or {}).get("draft_id", ""),
                            "headline": (d.get("draft") or {}).get("headline", ""),
                            "gate": d.get("factual_gate", ""),
                            "generated_at": (d.get("lineage") or {}).get("generated_at", ""),
                            "model": (d.get("lineage") or {}).get("model", ""),
                        }
                        for d in drafts_by_idea.get(idea["idea_id"], ())
                    ],
                    "case_id": (case or {}).get("case_id", ""),
                    "case_headline": (case or {}).get("draft_headline", ""),
                }
            )
        idea_rows.append({"idea": idea, "evidence": evidence})
    return {
        "ideas": idea_rows,
        "counts": {
            "ideas": len(ideas),
            "prepared": sum(1 for r in idea_rows for e in r["evidence"] if e["prepared"]),
            "drafts": len(drafts),
            "live_cases": sum(1 for c in cases if c.get("track") == TRACK_LIVE),
        },
        "story_options": wb_newsroom_story_options(),
    }


def wb_newsroom_story_options():
    """Newest stories as promote candidates (lazy import: no cycle at load)."""
    from editor_assistant.workflow import story_identity
    from editor_assistant.workflow.workbench import newsroom as wb_newsroom

    cards = story_identity.story_cards(
        inbox=wb_newsroom.inbox_store_path(),
        stories=wb_newsroom.stories_store(),
        blocked_path=wb_newsroom.blocked_store(),
    )["stories"]
    return [c for c in cards if c.get("title")][:30]



def request_draft_for_idea(idea_id):
    """Editor action: NEW/FOLLOW_UP idea becomes DRAFT_REQUESTED (contract)."""
    with _MUTATION_LOCK:
        from editor_assistant.workflow import ideas as ideas_mod

        ideas = load_ideas()
        idea = next((i for i in ideas if i["idea_id"] == idea_id), None)
        if idea is None:
            raise WorkbenchError(f"unknown idea_id: {idea_id}")
        try:
            ideas_mod.request_draft(idea)
        except ideas_mod.IdeaError as exc:
            raise WorkbenchError(str(exc)) from exc
        save_ideas(ideas)
        record_action("draft_requested", idea_id)
        return idea


def prepare_case(idea_id, evidence_id, *, mode=""):
    """Bind voice+mode to an idea's packet via the real live_case_request.

    Mirrors the CLI contract: the suggestion is always computed and shown; the
    stored prepared row carries an explicitly chosen mode (auto-confirmed from
    the suggestion when the editor leaves the select empty), so generation is
    never blocked by an unconfirmed tool suggestion.
    """
    with _MUTATION_LOCK:
        from editor_assistant.workflow import angles, live
        from editor_assistant.workflow import modes as modes_mod

        idea = next((i for i in load_ideas() if i["idea_id"] == idea_id), None)
        if idea is None:
            raise WorkbenchError(f"unknown idea_id: {idea_id}")
        row = load_live_rows().get(evidence_id)
        if row is None or row.get("idea_id") != idea_id:
            raise WorkbenchError("материалът не принадлежи на тази идея")
        packet = row.get("packet") or {}
        try:
            suggestion = modes_mod.suggest_mode(packet)
        except Exception as exc:
            raise WorkbenchError(f"материалът не може да бъде подготвен: {exc}") from exc
        chosen = mode if mode in EDITING_MODES else suggestion["suggested_mode"]
        try:
            prepared = live.live_case_request(idea, packet, voice=live.DEFAULT_VOICE, mode=chosen)
        except live.LiveError as exc:
            raise WorkbenchError(str(exc)) from exc
        if prepared.get("status") == angles.NO_ANGLE:
            save_ideas(load_ideas())  # live_case_request set the NO_ANGLE status
            record_action("prepare_refused_no_angle", evidence_id)
            return {"status": angles.NO_ANGLE, "reason": prepared.get("reason", "")}
        row["prepared"] = prepared
        _save_live_row(row)
        save_ideas(load_ideas())  # live_case_request set DRAFT_REQUESTED
        record_action("case_prepared", evidence_id)
        return {
            "status": "PREPARED",
            "mode": prepared["mode"],
            "mode_suggested": prepared.get("mode_suggested", False),
            "suggested_mode": prepared.get("suggested_mode", ""),
            "suggestion_reason": prepared.get("suggestion_reason", ""),
        }


def generate_draft(idea_id, evidence_id, *, force=False, force_reason=""):
    """The real M2.3B generation path, then the same stores the CLI writes.

    Appends the immutable AI draft to live_drafts.jsonl and opens a LIVE case
    (LIV-nn). Readiness refusals (RESEARCH_MORE / NO_ANGLE) come back as a
    status, never silently; a forced generation requires a recorded reason.
    """
    with _MUTATION_LOCK:
        from editor_assistant.workflow import angles, live
        from editor_assistant.workflow import cases as cases_mod
        from editor_assistant.workflow import readiness as readiness_mod

        idea = next((i for i in load_ideas() if i["idea_id"] == idea_id), None)
        if idea is None:
            raise WorkbenchError(f"unknown idea_id: {idea_id}")
        row = load_live_rows().get(evidence_id)
        if row is None or row.get("idea_id") != idea_id:
            raise WorkbenchError("материалът не принадлежи на тази идея")
        prepared = row.get("prepared")
        if not prepared:
            raise WorkbenchError("първо подготви случая (глас и режим)")
        if prepared.get("mode_suggested"):
            raise WorkbenchError("потвърди или промени предложенния режим първо")
        if force and not force_reason.strip():
            raise WorkbenchError("принудителната генерация изисква причина (записва се)")
        cases = load_cases()
        if any(c["evidence_id"] == evidence_id and c.get("track") == TRACK_LIVE for c in cases):
            raise WorkbenchError("за този материал вече е отворен LIVE случай")
        try:
            result = live.live_generate_draft(
                row["packet"],
                voice=prepared["voice"],
                mode=prepared["mode"],
                force_draft=force,
                editor_override_reason=force_reason or None,
            )
        except (angles.AngleError, live.LiveError) as exc:
            raise WorkbenchError(str(exc)) from exc
        status = result.get("status")
        if status in (angles.NO_ANGLE, readiness_mod.RESEARCH_MORE):
            record_action(f"draft_refused_{status}", evidence_id)
            return {"status": status, "reason": result.get("reason", "")}
        store = {
            "evidence_id": evidence_id,
            "idea_id": prepared["idea_id"],
            "draft": result["draft"],
            "lineage": result["lineage"],
            "lexical": result["lexical"],
            "semantic": result["semantic"],
            "factual_gate": result["factual_gate"],
            "readiness": result["readiness"],
            "voice": prepared["voice"],
            "mode": prepared["mode"],
            "mode_suggested_by_tool": prepared.get("mode_suggested", False),
            "retrieval": {k: v for k, v in result["retrieval"].items() if k != "examples"},
            "retrieval_example_ids": [e["article_id"] for e in result["retrieval"]["examples"]],
        }
        path = live_drafts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(store, ensure_ascii=False, sort_keys=True) + "\n")
        used_ids = {c["case_id"] for c in cases}
        n = 1
        while f"LIV-{n:02d}" in used_ids:
            n += 1
        case_id = f"LIV-{n:02d}"
        case = cases_mod.open_case(
            case_id=case_id,
            idea_id=prepared["idea_id"],
            evidence_id=evidence_id,
            draft=store,
            voice=prepared["voice"],
            mode=prepared["mode"],
            mode_suggested=prepared.get("suggested_mode"),
            suggestion_reason=prepared.get("suggestion_reason", ""),
            factual_gate=store["factual_gate"],
            prompt_version=store["lineage"].get("prompt_version", ""),
            audit={"semantic": store["semantic"], "lexical": store["lexical"]},
            track=TRACK_LIVE,
            source_url=(row.get("packet") or {}).get("source_url", ""),
        )
        cases.append(case)
        cases_mod.save_cases(cases, cases_path())
        record_action("draft_generated", case_id)
        return {
            "status": "DRAFTED",
            "case_id": case_id,
            "headline": store["draft"].get("headline", ""),
            "gate": store["factual_gate"],
        }


def promote_story_to_idea(story_id, *, inbox_path, stories_path, why_now="", angle=""):
    """Bridge: an M4 story becomes an idea + EvidencePacket (M2.3B path).

    The packet is built from the story's own collected material (facts only),
    so the drafting gates later see real provenance — nothing is invented here.
    Blocked publishers are skipped; a story with no usable material is refused
    with an explicit error instead of fabricating a packet.
    """
    with _MUTATION_LOCK:
        from editor_assistant.workflow import inbox_store, live, story_identity

        detail = story_identity.story_detail(story_id, inbox=inbox_path, stories=stories_path)
        if detail is None:
            raise WorkbenchError(f"unknown story_id: {story_id}")
        items = {i["item_id"]: i for i in inbox_store.read_items(inbox_path)}
        candidate = None
        # Prefer a material long enough to carry facts, then any clean material.
        for need_body in (True, False):
            for entry in detail["timeline"]:
                if entry.get("blocked_publisher"):
                    continue
                item = items.get(entry["item_id"]) or {}
                url = str(item.get("url") or "")
                if not url.startswith("http"):
                    continue
                if need_body and len((item.get("body") or "").strip()) < 200:
                    continue
                candidate = item
                break
            if candidate is not None:
                break
        if candidate is None:
            raise WorkbenchError("историята няма подходящ незаблокиран материал за запис")
        url = candidate["url"]
        source_type = "upstream_press_release"
        if "transcript" in url.lower():
            source_type = "council_transcript"
        try:
            idea = live.new_idea(
                source_type=source_type,
                source_url=url,
                title=detail["title"] or candidate.get("title") or "(без заглавие)",
                what_changed=(candidate.get("summary") or candidate.get("title") or "")[:600],
                why_now=why_now.strip(),
                possible_angle=angle.strip(),
            )
            record = {
                "url": url,
                "headline": candidate.get("title") or "",
                "body": candidate.get("body") or candidate.get("summary") or "",
                "quotes": [],
            }
            evidence_id = f"{idea['idea_id']}-EVIDENCE"
            packet = live.build_live_packet(idea, record=record, evidence_id=evidence_id)
        except live.LiveError as exc:
            raise WorkbenchError(str(exc)) from exc
        except ValueError as exc:  # packet validation failures
            raise WorkbenchError(f"материалът не може да стане пакет: {exc}") from exc
        _save_live_row(
            {
                "evidence_id": evidence_id,
                "idea_id": idea["idea_id"],
                "packet": packet,
                "observed_at": packet["observed_at"],
            }
        )
        save_ideas(load_ideas() + [idea])
        record_action("story_promoted", idea["idea_id"])
        return {
            "idea_id": idea["idea_id"],
            "evidence_id": evidence_id,
            "title": idea["title"],
            "fact_count": len(packet.get("facts") or ()),
        }