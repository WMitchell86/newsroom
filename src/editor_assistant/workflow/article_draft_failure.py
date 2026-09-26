"""V1.1-C — has an eligible Draft generation genuinely failed for this basis?

**What this answers.** C3 shipped `Редактирай` on every focus-confirmed
Preparation Article, as an always-on escape hatch. That was a defect: manual
continuation is a *recovery* path offered only after a real generation failure,
never an alternative to `Направи чернова` on a clean Article. The diagnostic
(P1-7) proved no durable signal anywhere in the product distinguishes
"generation failed, write it yourself" from "deliberately hand written".

**What is deliberately NOT authority.** `article_generation._attempts` counts
every attempt including successful ones, the bounded operation registry expires,
and `_ACTIVE` plus any frontend local state die with the process. None of them
answers "did a *genuine* generation failure happen", so none may open this path.
Only a persisted marker written after the deterministic preflight was crossed
may, which is why it lives in canonical Article state and survives a browser
reload and a server restart.

**Two questions, kept apart.** `article_readiness` answers *may generation
start?*. This module answers *did an eligible attempt fail, and is that failure
still current?*. They are deliberately not merged into one boolean: an Article
can be eligible with no failure (normal work), ineligible after a failure (the
material changed) and ineligible with no failure (research is still the remedy).

**Narrowness.** The marker carries an editor-safe failure identity only — no
provider exception, prompt, payload, model name or secret. It is bound to the
generation *basis*, so a later material change retires it instead of leaving a
stale recovery path open forever.
"""

from __future__ import annotations

import hashlib

#: The external provider or model could not be reached. The attempt is retryable
#: and nothing about the material is wrong, so `Опитай отново` stays offered
#: alongside the manual path.
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
#: The generation pipeline ran and published no usable Draft (a refusal, an empty
#: result or a failed generation). Manual writing is a sensible fallback here.
GENERATION_FAILED = "GENERATION_FAILED"

#: Every reason class this marker may ever carry. The editor sees a class, never
#: an internal exception type: three classes would only create distinctions the
#: UI cannot act on differently, and mirroring every internal error would leak
#: the provider's failure surface into canonical state.
REASON_CODES = frozenset({PROVIDER_UNAVAILABLE, GENERATION_FAILED})

#: The refusal codes that unlock manual continuation, and the class each one
#: records. A code absent here is a readiness or transition refusal —
#: `STORY_UNASSESSED`, `NO_CONFIRMED_FACTS`, `NO_OPEN_SOURCE`, `BLOCKING_GAP`,
#: `FOCUS_NOT_CONFIRMED`, `ARTICLE_HAS_TEXT`, `WORKING_TITLE_REQUIRED`,


def reason_for(code: str) -> str:
    """The marker reason class for a refusal, or `""` when it does not qualify.

    `""` means: this failure was never a generation attempt, so no marker may be
    written. The check is an allow-list on purpose — a new refusal code added
    anywhere in the product stays non-qualifying until it is classified here, so
    a readiness refusal can never leak open the editor by default.
    """
    return QUALIFYING_REFUSALS.get(str(code or ""), "")


def basis_digest(snapshot: dict) -> str:
    """A stable identity for the exact material a generation attempt would use.

    This is the invalidation rule, not new versioning infrastructure: it reuses
    the one snapshot `article_readiness.build_snapshot` already assembles and
    digests only the inputs that change the generation basis — the Article, its
    content version and working title, the confirmed Focus, and the Story's
    evidence basis (status, assessment time, fact identities, gap identities).

    So a failure authorizes manual continuation only while the material it was
    produced from is still the material on screen. Changing the Focus, editing
    the title, or materially changing the Story's evidence retires the marker,
    and the editor must attempt a real generation again to get the path back.
    """
    article = snapshot.get("article") or {}
    content = snapshot.get("content") or {}
    facts = sorted(str(item.get("id") or "") for item in snapshot.get("facts") or [])
    gaps = sorted(str(item.get("id") or "") for item in snapshot.get("gaps") or [])
    seed = "\0".join(
        [
            str(article.get("article_id") or ""),
            str(snapshot.get("content_version") or ""),
            str(content.get("title") or ""),
            str(article.get("editorial_focus") or ""),
            str(article.get("focus_confirmed_at") or ""),
            str(snapshot.get("evidence_status") or ""),
            str(snapshot.get("assessed_at") or ""),
            ",".join(facts),
            ",".join(gaps),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def is_current(article: dict, snapshot: dict) -> bool:
    """True only when a stored failure still describes this exact basis.

    The explicit `content_version` comparison is redundant with the digest by
    construction and is kept anyway: it is the field a reader checks first, and
    it makes "the editor's own text moved on" impossible to miss.
    """
    marker = article.get("draft_generation_failure")
    if not isinstance(marker, dict):
        return False
    if int(marker.get("content_version", -1)) != int(snapshot.get("content_version", -2)):
        return False
    return str(marker.get("basis_digest") or "") == basis_digest(snapshot)


#: `STORY_UNAVAILABLE`, `NOT_IN_PREPARATION`, `SAFETY_BLOCKED`, a stale
#: `ARTICLE_VERSION_CONFLICT` and the in-flight `INVALID_TRANSITION` — and must
#: never open the editor, because none of them attempted a generation.
#:
#: The empty code is the unclassified transport failure the command path raises
#: for an exception that is not a readiness decision.
QUALIFYING_REFUSALS = {
    "": PROVIDER_UNAVAILABLE,
    "DRAFT_UNAVAILABLE": GENERATION_FAILED,
}
