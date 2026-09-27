"""V1.2-G2.4 §E — the single-source Draft policy, as an ISOLATED EXPERIMENT.

**This module changes no policy.** §E4 is explicit: compare the current strict
pre-Draft gate against a single-source-attributed Draft gate, measure on real
Stories, report, and let the owner decide. So nothing here is wired into
`article_readiness`, `story_research` or any production path. It is a pure
evaluation function plus the vocabulary the report needs.

**The contract being tested.** E1 splits a question the current system conflates:

* *Can we start writing?* — one opened, non-aggregator, complete-provenance
  source is enough to begin, provided the Draft attributes it;
* *Is it confirmed enough to finalise?* — unchanged, and still two independent
  publishers (or an appropriate official PRIMARY).

E2 keeps the existing rule strongest: an official PRIMARY may establish its own
first-party facts. E3's attribution wording is what a single ordinary media
source would be required to use, and a single-source Draft must NOT become
silently confirmed — measuring that is the whole point.

**The invariant.** `evaluate` never returns a *ready* verdict. Its strongest
possible output is `DRAFT_CAPABLE_ATTRIBUTED`, strictly weaker than
`DRAFT_ELIGIBLE`, and it always carries warnings.
"""

from __future__ import annotations

# --- outcomes ---------------------------------------------------------------
#: The current production gate already allows this Draft. Nothing is proposed.
DRAFT_ELIGIBLE = "DRAFT_ELIGIBLE"
#: The experimental gate would allow a Draft, attributed to the single source.
#: Strictly weaker than DRAFT_ELIGIBLE, and always warned.
DRAFT_CAPABLE_ATTRIBUTED = "DRAFT_CAPABLE_ATTRIBUTED"
#: Not eligible and not Draft-capable: something is genuinely missing.
NOT_ELIGIBLE = "NOT_ELIGIBLE"

EXPERIMENT_OUTCOMES = frozenset({DRAFT_ELIGIBLE, DRAFT_CAPABLE_ATTRIBUTED, NOT_ELIGIBLE})

# --- the warnings a single-source Draft must carry (§E3) -------------------
#: These are WARNINGS, never an Article state. The owner was explicit that no
#: fourth Article state is wanted; warnings are already separate from state.
WARNING_SINGLE_SOURCE = (
    "Твърдението е потвърдено само от един източник. Проверете ключовите твърдения "
    "преди финализиране."
)
WARNING_SINGLE_SOURCE_ATTRIBUTION = (
    "Един източник. Формулировките трябва да са атрибутирани към него — например "
    "„По информация на …“ — вместо да се представят като независимо потвърдени."
)

#: A source that is an unresolved aggregator or a social wrapper can never
#: support even an attributed Draft (§E1).
_NON_PUBLISHER_HOSTS = frozenset(
    {
        "news.google.com", "google.com", "facebook.com", "fb.com", "instagram.com",
        "twitter.com", "x.com", "tiktok.com", "youtube.com", "youtu.be",
        "linkedin.com", "t.me", "telegram.me", "reddit.com",
    }
)


def is_publisher(source: dict) -> bool:
    """True when this source is a real publisher rather than a wrapper (§E1)."""
    host = str((source or {}).get("domain") or "").lower()
    if not host:
        return False
    return host not in _NON_PUBLISHER_HOSTS and not host.endswith(".google.com")


def provenance_complete(source: dict, facts) -> bool:
    """Every promoted fact must carry this source's id; provenance is whole.

    §E1 requires complete provenance. A fact that cannot name the opened source
    is not attributable, and an unattributable claim may not enter a Draft.
    """
    rows = list(facts or ())
    if not rows:
        return False
    source_id = str((source or {}).get("id") or "")
    if not source_id:
        return False
    return all(str(row.get("sourceId") or "") == source_id for row in rows)


def has_known_contradiction(gaps) -> bool:
    """A detected conflict is never something to write around (§E1)."""
    return any(str(gap.get("kind") or "") == "conflict" for gap in (gaps or ()))



def _refusal(current, *, eligible_now: bool = False) -> dict:
    """A Story the experiment does not unlock, keeping the production reason."""
    return {
        "eligible_now": eligible_now,
        "eligible_now_code": current.reason_code,
        "draft_capable_single": False,
        "delta": False,
        "warnings": [],
        "attribution_required": False,
    }


def evaluate(*, evidence_status, facts, sources, gaps) -> dict:
    """Evaluate ONE Story basis under both gates, side by side.

    Returns a record that answers the owner's question directly:

    ```text
    eligible_now          what the CURRENT production gate says
    draft_capable_single  what the EXPERIMENTAL gate would additionally allow
    delta                 Stories newly Draft-capable ONLY under the experiment
    warnings              the warnings such a Draft must carry
    attribution_required  whether the wording must name the single source
    ```

    Both verdicts are computed independently and both are reported, so the
    report can state exactly what the experiment would change. `delta` is true
    only when the experiment grants something the current gate does not.
    """
    from editor_assistant.workflow import article_readiness

    facts = list(facts or ())
    sources = list(sources or ())
    gaps = list(gaps or ())
    source_url = article_readiness._first_source_url(facts)

    current = article_readiness.evaluate_evidence(
        evidence_status=evidence_status,
        facts=facts,
        blocking_gaps=[gap for gap in gaps if gap.get("blocking", True)],
        source_url=source_url,
    )
    eligible_now = bool(current.eligible)

    # E4: the experiment only speaks where the CURRENT gate refuses. Where
    # production already allows the Draft there is nothing to propose, and
    # counting it would overstate what the change buys.
    if eligible_now or len(sources) != 1:
        return _refusal(current, eligible_now=eligible_now)

    source = sources[0]
    # E1's conditions, each checked in code rather than assumed.
    if not is_publisher(source) or not provenance_complete(source, facts):
        return _refusal(current)
    if has_known_contradiction(gaps):
        return _refusal(current)

    # E2: an official PRIMARY is already handled by the production gate, so
    # reaching here means an ORDINARY media source — exactly the case E3 covers.
    return {
        "eligible_now": False,
        "eligible_now_code": current.reason_code,
        "draft_capable_single": True,
        "delta": True,
        "warnings": [WARNING_SINGLE_SOURCE, WARNING_SINGLE_SOURCE_ATTRIBUTION],
        "attribution_required": True,
    }
