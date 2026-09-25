"""C4 — validation of the CURRENT Article working content.

**One narrow, synchronous, deterministic validation path.** The editor's
readiness checkpoint is bound to the exact text that exists right now, so the
validation that produces it must be the same for an unedited generated Draft, an
edited generated Draft and a hand-written manual Draft. That is why nothing here
reads the immutable generated Draft, the generation-time Case audit or
`generated_content_version`: a generation audit describes the version the model
produced, not the version the editor is looking at.

**No second validation engine.** Every audit below is delegated to the mature,
already exercised machinery:

* `article_generation.build_packet` — the C2 adapter that turns the canonical
  Story evidence basis into one M2.3B `EvidencePacket` (the same provenance and
  the same `validate_packet` contract the drafting gate uses);
* `generate.audit_claims` — the M2.3B token-level factual audit
  (SUPPORTED / UNSUPPORTED, invented numbers, source leakage);
* `generate.originality_check` — the deterministic M4F F5 no-copy guard.

**The provider-based semantic judge is deliberately not part of C4.**
`generate.verify_claims_semantic` is a live model call (240 s budget) bound to
the generation pipeline, and a readiness checkpoint must be reproducible: the
digest it stores is compared on every later read and on finalization. A
non-deterministic, network-bound check cannot be that authority. What C4 does
instead is fail *closed* on the deterministic layer: if the evidence basis
cannot be assembled or audited at all, the content is blocking, never silently
"clean". The semantic second pass stays where it already is — generation-time.

**Warnings never become state.** They are editor-facing annotations over one
exact content version; only the durable readiness checkpoint moves the Article
from `Чернова` to `Готова`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from editor_assistant.drafting import evidence as evidence_mod
from editor_assistant.drafting import generate as generate_mod
from editor_assistant.workflow import article_generation, editor_projections

#: How many unsupported sentences are listed as separate editorial notes. The
#: count itself is always reported, so the editor never loses the scale.
MAX_LISTED_SENTENCES = 5

#: Every rule this validator can raise, with its frozen three-level presentation
#: severity and its authoritative blocking status. Blocking is a property of the
#: rule, never of the message wording, and a blocking rule is never downgraded
#: because the editor can act on it inside the Draft workspace.
_RULES: dict[str, tuple[str, bool]] = {
    # Blocking: the content cannot be validated, or its basis is broken.
    "story_lineage_unavailable": ("blocking", True),
    "content_empty": ("blocking", True),
    "evidence_basis_empty": ("blocking", True),
    "evidence_source_missing": ("blocking", True),
    "evidence_basis_invalid": ("blocking", True),
    "blocking_gap_open": ("blocking", True),
    # Review: real findings the editor may decide about.
    "unsupported_claims": ("review", False),
    "lexical_unsupported_sentence": ("review", False),
    "originality_copy": ("review", False),
    # Informational: the audit itself was partial.
    "audit_partial": ("info", False),
}

_MESSAGES = {
    "story_lineage_unavailable": "Историята на статията вече не е достъпна за проверка.",
    "content_empty": "Няма текст, който може да се отбележи като готов.",
    "evidence_basis_empty": "Няма потвърдени факти, срещу които текстът да се провери.",
    "evidence_source_missing": "Факт от основата няма отворен източник и не може да се провери.",
    "evidence_basis_invalid": "Основата за проверка не отговаря на договора за доказателства.",
    "blocking_gap_open": "Има непопълнена информация, която пречи да продължите.",
    "unsupported_claims": "Част от твърденията в текста не са подкрепени от източниците.",
    "lexical_unsupported_sentence": "Изречение без директна опора в източниците.",
    "originality_copy": "Текстът повтаря дословно изречение от източника. Препишете със свои думи.",
    "audit_partial": "Проверката на твърденията не е завършена изцяло. Прегледайте текста.",
}


class ValidationUnavailable(RuntimeError):
    """The current content could not be validated at all (fail closed)."""


@dataclass(frozen=True)
class ContentValidation:
    """The internal result of one current-content validation, bound to a version."""

    content_version: int
    digest: str
    warnings: tuple[dict, ...]
    blocking: bool
    validated_at: str


def _normalize(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp(now) -> str:
    """A display stamp for the editor. Never an input of the digest."""
    text = str(now or "").strip()
    return text or _now()


def validation_evidence_id(article_id: str) -> str:
    """A stable packet id per Article: no counter, no clock, no randomness."""
    seed = f"article-validation\0{article_id}".encode()
    return "EV-VAL-" + hashlib.sha256(seed).hexdigest()[:10]


def warning_id(rule: str, *, affected: str = "", evidence: str = "") -> str:
    """Deterministic warning identity: same rule + same text + same evidence.

    No counter and no random suffix, so `same text + same evidence + same
    validation` always yields the same warning set and therefore the same digest.
    """
    seed = "\0".join((rule, _normalize(affected).casefold(), _normalize(evidence)))
    return "warn_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:15]


def _warning(
    rule: str, *, affected: str = "", evidence: str = "", identity: str | None = None
) -> dict:
    """One editor-facing warning.

    `affected` is the editor's own current text and is the only thing that ever
    becomes `affectedText`. `identity` exists for warnings that need a stable
    identity without quoting text (a count, for example) - so a summary warning
    can never pretend that a count is a quote from the article.
    """
    severity, blocking = _RULES[rule]
    warning = {
        "id": warning_id(rule, affected=affected, evidence=evidence)
        if identity is None
        else warning_id(rule, affected=identity, evidence=evidence),
        "rule": rule,
        "severity": severity,
        "message": _MESSAGES[rule],
        "blocking": blocking,
    }
    text = _normalize(affected)
    if text:
        # Only ever the editor's own current text, truncated. No range is
        # fabricated: the deterministic audits cannot prove character offsets.
        warning["affectedText"] = text[:200]
    return warning


def _sort_key(warning: dict) -> tuple:
    return (
        0 if warning["blocking"] else 1,
        str(warning.get("rule") or ""),
        str(warning["id"]),
    )


def content_fingerprint(title, body) -> str:
    """The normalized text identity a digest is bound to."""
    return hashlib.sha256((_normalize(title) + "\0" + str(body or "")).encode("utf-8")).hexdigest()[
        :32
    ]


def evidence_identity(facts: list[dict], gaps: list[dict]) -> str:
    """Canonical identity of the evidence basis, independent of display order.

    This is what makes a readiness checkpoint stale when external evidence
    changes while the Article text does not: the same words checked against a
    different basis are not the same validation.
    """
    rows = set()
    for fact in facts or []:
        source = fact.get("source") or {}
        rows.add(
            "fact|{}|{}|{}|{}".format(
                fact.get("id"),
                source.get("id"),
                source.get("url"),
                _normalize(fact.get("text")),
            )
        )
    for gap in gaps or []:
        rows.add(
            "gap|{}|{}|{}".format(
                gap.get("id"),
                int(bool(gap.get("blocking"))),
                _normalize(gap.get("question")),
            )
        )
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:32]


def compute_digest(
    *,
    article_id: str,
    content_version: int,
    fingerprint: str,
    evidence: str,
    warnings: list[dict],
    blocking: bool,
) -> str:
    """A stable identity for one validation of one content version.

    Inputs are canonical validation data only: the Article, the content version
    and fingerprint, the sorted normalized warning identities, the blocking
    status and the evidence basis. Timestamps, display order, random ids and
    provider request ids are never inputs, so the validation stamp cannot move
    the digest and a reordered warning list cannot move it either.
    """
    payload = {
        "article": str(article_id),
        "contentVersion": int(content_version),
        "content": str(fingerprint),
        "blocking": bool(blocking),
        "warnings": sorted(
            "{}|{}|{}|{}".format(
                row.get("id"),
                row.get("severity"),
                int(bool(row.get("blocking"))),
                _normalize(row.get("affectedText")),
            )
            for row in warnings
        ),
        "evidence": str(evidence),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "vd_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _packet(
    article: dict,
    facts: list[dict],
    gaps: list[dict],
    *,
    headline: str,
    assessed_at: str,
) -> dict:
    """The C2 packet adapter over the canonical Story basis (not a new one)."""
    source_url = next(
        (
            str((fact.get("source") or {}).get("url") or "")
            for fact in facts
            if str((fact.get("source") or {}).get("url") or "")
        ),
        "",
    )
    snapshot = {
        "facts": facts,
        "gaps": list(gaps or []),
        "source_url": source_url,
        "assessed_at": assessed_at,
        "headline": headline,
    }
    return article_generation.build_packet(snapshot, validation_evidence_id(article["article_id"]))


def evaluate_current_content(
    article: dict,
    content: dict,
    *,
    story: dict | None,
    facts: list[dict],
    gaps: list[dict],
    headline: str = "",
    assessed_at: str = "",
    now=None,
) -> ContentValidation:
    """Validate the current working content of one Article.

    Loads nothing: the caller passes the canonical Article, its exact current
    content version, the canonical Story and the canonical Story evidence basis.
    The result is bound to `content["content_version"]` and to nothing else.
    """
    content_version = int(content.get("content_version", -1))
    if content_version < 0:
        raise ValidationUnavailable("the Article has no current content version")
    title = str(content.get("title") or "")
    body = str(content.get("body") or "")
    warnings: list[dict] = []

    if (
        story is None
        or story.get("story_id") != article.get("story_id")
        or str(story.get("status") or "") == "IGNORED"
    ):
        warnings.append(
            _warning("story_lineage_unavailable", affected=str(article.get("story_id") or ""))
        )
    if not title.strip() or not body.strip():
        # Nothing to audit. That is a real, blocking finding - never a pass.
        warnings.append(_warning("content_empty"))

    for gap in [gap for gap in gaps or [] if gap.get("blocking")]:
        warnings.append(_warning("blocking_gap_open", affected=str(gap.get("id") or "")))

    audit: dict = {}
    if body.strip() and facts:
        missing_source = [
            fact for fact in facts if not str((fact.get("source") or {}).get("url") or "").strip()
        ]
        if missing_source:
            warnings.append(
                _warning(
                    "evidence_source_missing",
                    affected=",".join(sorted(str(f.get("id") or "") for f in missing_source)),
                )
            )
        try:
            packet = _packet(article, facts, gaps, headline=headline, assessed_at=assessed_at)
        except (evidence_mod.EvidenceError, ValueError, TypeError, KeyError):
            # The canonical basis cannot be assembled into a valid packet, so the
            # audit did not run. The content is blocking, not silently clean.
            warnings.append(_warning("evidence_basis_invalid"))
            packet = None
        if packet is not None and not missing_source:
            try:
                audit = generate_mod.audit_claims(body, packet)
                audit["originality"] = generate_mod.originality_check(body, packet["source_text"])
            except Exception as exc:  # pragma: no cover - defensive, fail closed
                raise ValidationUnavailable("the current-content audit failed") from exc
    elif body.strip() and not any(row["rule"] == "blocking_gap_open" for row in warnings):
        # No canonical fact to check the text against: the audit is impossible.
        warnings.append(_warning("evidence_basis_empty"))

    warnings.extend(_audit_warnings(audit))
    warnings = _dedupe(warnings)
    blocking = any(row["blocking"] for row in warnings)
    return ContentValidation(
        content_version=content_version,
        digest=compute_digest(
            article_id=str(article.get("article_id") or ""),
            content_version=content_version,
            fingerprint=content_fingerprint(title, body),
            evidence=evidence_identity(facts, gaps),
            warnings=warnings,
            blocking=blocking,
        ),
        warnings=tuple(warnings),
        blocking=blocking,
        validated_at=_timestamp(now),
    )


def _dedupe(warnings: list[dict]) -> list[dict]:
    """One entry per warning identity, in a stable editorial order."""
    unique: dict[str, dict] = {}
    for row in warnings:
        unique.setdefault(str(row["id"]), row)
    return sorted(unique.values(), key=_sort_key)


def _audit_warnings(audit: dict) -> list[dict]:
    """Project the deterministic current-content audits into editor warnings."""
    if not audit:
        return []
    rows: list[dict] = []
    unsupported = [str(item) for item in (audit.get("unsupported") or [])]
    if unsupported:
        rows.append(_warning("unsupported_claims", identity=f"count:{len(unsupported)}"))
        for sentence in unsupported[:MAX_LISTED_SENTENCES]:
            rows.append(
                _warning("lexical_unsupported_sentence", affected=_normalize(sentence)[:200])
            )
    originality = audit.get("originality") or {}
    if originality.get("checked") and not originality.get("pass", True):
        copied = [str(item) for item in (originality.get("copied") or [])]
        rows.append(_warning("originality_copy", affected=_normalize(copied[0]) if copied else ""))
    leaks = [str(item) for item in (audit.get("leak_hits") or [])]
    if leaks:
        rows.append(_warning("audit_partial", affected=_normalize(leaks[0])[:200]))
    return rows


def ready_eligible(article: dict, content: dict, validation: ContentValidation) -> bool:
    """Backend authority for `MARK_READY`; the command still revalidates.

    The Article is a non-finalized `Чернова` with confirmed focus, real current
    content, a current validation and no known blocking issue. React never
    derives this from a warning count.
    """
    if article.get("finalized_at"):
        return False
    if not editor_projections.can_mark_article_ready(article, content):
        return False
    if editor_projections.derive_article_state(article, content, validation.digest) != "draft":
        return False
    return not validation.blocking
