"""V1.1-B — the ONE canonical Draft readiness / preflight decision.

**Why this module exists.** Before V1.1-B the editor had two independent
answers to a single question. The Article preparation projection asked only
`focus confirmed AND no blocking gaps` (`editor_application._article_actions`),
while the Draft generation command additionally required assessed evidence, at
least one confirmed fact and a usable opened source URL
(`article_generation.evaluate`). The result was a UI that promised
"Може да се направи чернова" for an Article the backend was guaranteed to
refuse. The diagnostic proved 5 of 6 real preparation Articles were in exactly
that state.

**The contract.** One pure predicate, `evaluate(snapshot)`, is the only place
that decides whether this exact Article can generate a Draft right now. Both
consumers read the same result:

* the Article preparation projection, for `draftEligible` / `MAKE_DRAFT` /
  the editor-facing reason;
* `article_generation.evaluate`, which raises the classified `DraftRefused`.

Neither re-derives the other, so they cannot disagree for any canonical state.

**Readiness is not a promise about the provider.** Everything evaluated here is
deterministic and pre-provider: canonical existence, lifecycle state, Story
lineage, confirmed Focus, evidence status, fact and opened-source sufficiency,
blocking gaps, and the two safety guards. A refusal is a stable semantic
reason, never a generic "Нещо липсва." and never a raw internal text.

**Reason codes are the contract.** They are narrow, editor-safe and stable, and
they are the same strings the editor sees in the DTO, the `nextAction`
`reasonCode` and the HTTP error envelope. Adding a condition means adding a
code here — never reusing a neighbouring one, never inventing near-duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from editor_assistant.workflow import blocked_domains, editor_projections

# --- The reason taxonomy. Every editor-facing refusal has exactly one code. ---

#: A Draft can be generated from this Article right now.
DRAFT_ELIGIBLE = "DRAFT_ELIGIBLE"
#: The Editorial Focus is not confirmed yet. Independent of any evidence state.
FOCUS_NOT_CONFIRMED = "FOCUS_NOT_CONFIRMED"
#: The Story has never been researched. There is no basis to draft from yet.
STORY_UNASSESSED = "STORY_UNASSESSED"
#: The Story was assessed and confirmed nothing usable. Research must find facts.
NO_CONFIRMED_FACTS = "NO_CONFIRMED_FACTS"
#: Facts exist, but none carries a usable opened source URL to build on.
NO_OPEN_SOURCE = "NO_OPEN_SOURCE"
#: The assessed basis still carries a real blocking gap. Not the same as NO_CONFIRMED_FACTS.
BLOCKING_GAP = "BLOCKING_GAP"
#: The Article is not in the `preparation` state, so it cannot start a Draft.
NOT_IN_PREPARATION = "NOT_IN_PREPARATION"
#: The Story lineage the Article points at is gone, or the Story is ignored.
STORY_UNAVAILABLE = "STORY_UNAVAILABLE"
#: The Article already has text; a generation would silently overwrite it.
ARTICLE_HAS_TEXT = "ARTICLE_HAS_TEXT"
#: A deterministic safety guard (circular / blocked source) stops generation.
SAFETY_BLOCKED = "SAFETY_BLOCKED"
#: The exact content version changed between decision and generation.
ARTICLE_VERSION_CONFLICT = "ARTICLE_VERSION_CONFLICT"
#: The working title is empty, so there is nothing to draft under.
WORKING_TITLE_REQUIRED = "WORKING_TITLE_REQUIRED"

#: The exact editor wording for each reason. One message per code, so the UI can
#: never render a second, contradictory sentence for the same decision.
REASON_MESSAGES = {
    DRAFT_ELIGIBLE: "Има достатъчно потвърдена информация за чернова.",
    FOCUS_NOT_CONFIRMED: "Потвърдете фокуса, преди да правите чернова.",
    STORY_UNASSESSED: "Историята трябва първо да бъде проучена.",
    NO_CONFIRMED_FACTS: "Няма потвърдени факти, върху които да се изгради черновата.",
    NO_OPEN_SOURCE: "Няма отворен източник, върху който да се изгради черновата.",
    BLOCKING_GAP: "Има непопълнена информация, която пречи да продължите.",
    NOT_IN_PREPARATION: "Черновата не е налична в текущото състояние на статията.",
    STORY_UNAVAILABLE: "Историята на статията вече не е достъпна.",
    ARTICLE_HAS_TEXT: "Статията вече има текст.",
    SAFETY_BLOCKED: "Проверката за безопасност спря операцията.",
    ARTICLE_VERSION_CONFLICT: (
        "Статията е променена, преди черновата да се създаде. Няма загубени локални промени."
    ),
    WORKING_TITLE_REQUIRED: "Работното заглавие не може да е празно.",
}

#: Reasons whose remedy is one and the same: research the owning Story. The
#: Article itself never orchestrates research; it only routes the editor there.
RESEARCH_REMEDY_CODES = frozenset(
    {STORY_UNASSESSED, NO_CONFIRMED_FACTS, NO_OPEN_SOURCE, BLOCKING_GAP}
)

#: Refusals about the Article's lifecycle and lineage rather than its evidence.
#: These are transition problems, so the editor API keeps its historical
#: `INVALID_TRANSITION` contract for them, with the specific message attached.
LIFECYCLE_CODES = frozenset(
    {
        NOT_IN_PREPARATION,
        STORY_UNAVAILABLE,
        ARTICLE_HAS_TEXT,
        WORKING_TITLE_REQUIRED,
    }
)


@dataclass(frozen=True)
class DraftReadiness:
    """The one readiness decision, for both the projection and the command.

    `eligible` is the answer; `reason_code` and `reason_message` are the
    explanation the editor is owed. The remaining fields are the canonical
    inputs that produced it, carried so no consumer has to re-derive them.
    """

    eligible: bool
    reason_code: str
    reason_message: str
    evidence_status: str = ""
    fact_count: int = 0
    has_open_source: bool = False
    blocking_gaps: list[dict] = field(default_factory=list)
    remedy: str = ""

    @property
    def is_researchable(self) -> bool:
        """True when the editor's next step is `Проучи още` on the Story."""
        return self.reason_code in RESEARCH_REMEDY_CODES

    def as_dto(self) -> dict:
        """The narrow editor-facing shape: code + message, nothing internal."""
        return {"code": self.reason_code, "message": self.reason_message}

    def refuse(self) -> None:
        """Raise the classified refusal (import is local: this module is low-level)."""
        from editor_assistant.workflow import article_generation

        raise article_generation.DraftRefused(self.reason_code, self.reason_message)


def _first_source_url(facts: list[dict]) -> str:
    """The first fact carrying a usable opened source URL, or `""`.

    Deliberately the same rule the C2 snapshot already used to pick the packet's
    `source_url`, so the projection and the command can never disagree about
    which source the Draft would be built on.
    """
    for fact in facts:
        url = str((fact.get("source") or {}).get("url") or "")
        if url:
            return url
    return ""


def build_snapshot(
    article: dict,
    content: dict,
    story: dict | None,
    facts: list[dict],
    missing: dict,
) -> dict:
    """Assemble the ONE canonical readiness input from already-loaded state.

    Pure and store-free: every caller has already read the canonical Article,
    its current content, its Story and its evidence basis, so the projection and
    the command cannot disagree about what they looked at. This is the existing
    C2 `_draft_snapshot` shape, extracted with no new evidence system.
    """
    return {
        "article": article,
        "content": content,
        "story": story,
        "content_version": int(content.get("content_version", 0)),
        "state": editor_projections.derive_article_state(article, content, None),
        "facts": list(facts),
        "gaps": list(missing.get("items") or []),
        "blocking_gaps": [item for item in missing.get("items") or [] if item.get("blocking")],
        "evidence_status": str(missing.get("evidenceStatus") or ""),
        "assessed_at": missing.get("assessedAt"),
        "source_url": _first_source_url(facts),
    }


def _refusal(
    code: str,
    *,
    evidence_status: str,
    fact_count: int,
    has_open_source: bool,
    blocking_gaps: list[dict] | None = None,
) -> DraftReadiness:
    """One refusal, built from the taxonomy so no caller writes its own wording."""
    return DraftReadiness(
        eligible=False,
        reason_code=code,
        reason_message=REASON_MESSAGES[code],
        evidence_status=evidence_status,
        fact_count=fact_count,
        has_open_source=has_open_source,
        blocking_gaps=list(blocking_gaps or []),
        remedy="RESEARCH" if code in RESEARCH_REMEDY_CODES else "",
    )


def evaluate_evidence(
    *,
    evidence_status: str,
    facts: list[dict],
    blocking_gaps: list[dict],
    source_url: str,
) -> DraftReadiness:
    """The evidence half of `evaluate`, answerable without an Article (§7 D2).

    `evaluate` answers a question about one Article: may *this* Article start a
    Draft? Its first two steps are about the Article (lifecycle, lineage, Focus,
    content version) and the rest is about the Story's evidence basis, which
    exists and is canonical long before any Article does.

    V1.1-D2 has to ask that second question at a point where no Article exists
    yet — §10 requires evidence to be judged sufficient *before* an Article is
    created, so a Story that cannot acquire evidence leaves no empty Preparation
    Article behind. Duplicating the rules here would create a second readiness
    authority that could drift, which §16 forbids. So the evidence steps live
    here once, and `evaluate` calls this function for them: one taxonomy, one
    message per code, one place a new evidence reason is added.

    The order is the one `evaluate` already documents: unassessed is "no basis",
    a real blocking gap is explained by the gap, and facts without a usable
    opened source are not usable material.
    """
    blocking_gaps = list(blocking_gaps or [])
    fact_count = len(facts or [])
    has_open_source = bool(source_url)

    def refusal(code: str) -> DraftReadiness:
        return _refusal(
            code,
            evidence_status=evidence_status,
            fact_count=fact_count,
            has_open_source=has_open_source,
            blocking_gaps=blocking_gaps,
        )

    # V1.1-A: an unresearched Story is UNASSESSED, not a clean empty basis.
    # Checked before facts so the editor is told to research the Story rather
    # than shown a fabricated Article-level gap.
    if evidence_status != "assessed":
        return refusal(STORY_UNASSESSED)
    # A real blocking gap is explained by the gap itself, never by a generic
    # "something is missing".
    if blocking_gaps:
        return refusal(BLOCKING_GAP)
    # Facts and an opened source are separate failures with separate reasons.
    if not fact_count:
        return refusal(NO_CONFIRMED_FACTS)
    if not has_open_source:
        return refusal(NO_OPEN_SOURCE)
    # The same deterministic guard the mature pipeline applies to any factual
    # input, re-checked before the Article exists rather than only before a
    # model call. Imported here to keep this module free of a cycle through
    # `live`.
    from editor_assistant.workflow.cases import is_chernomorie_source

    if is_chernomorie_source(source_url) or blocked_domains.is_blocked(source_url):
        return refusal(SAFETY_BLOCKED)
    return DraftReadiness(
        eligible=True,
        reason_code=DRAFT_ELIGIBLE,
        reason_message=REASON_MESSAGES[DRAFT_ELIGIBLE],
        evidence_status=evidence_status,
        fact_count=fact_count,
        has_open_source=True,
        blocking_gaps=[],
    )


def evaluate(snapshot: dict) -> DraftReadiness:
    """The canonical decision: can this exact Article generate a Draft now?

    Evaluated in a fixed order so the reported reason is always the most
    fundamental one, and so a given canonical state always yields the same code:

    1. lifecycle / lineage — a Draft is a `preparation` transition;
    2. Editorial Focus — an independent editorial blocker;
    3. evidence status — `unassessed` is not an empty basis, it is no basis;
    4. blocking gaps — the actual reason, with the actual questions;
    5. facts, then a usable opened source — a distinct, honest explanation each;
    6. the two deterministic safety guards, re-checked before any model call.

    No C2 requirement is weakened: every precondition the generation preflight
    enforced is evaluated here, and the projection rises to that level rather
    than the command falling to the projection's.
    """
    article = snapshot.get("article") or {}
    content = snapshot.get("content") or {}
    story = snapshot.get("story")
    facts = list(snapshot.get("facts") or [])
    blocking_gaps = list(snapshot.get("blocking_gaps") or [])
    evidence_status = str(snapshot.get("evidence_status") or "")
    fact_count = len(facts)
    source_url = str(snapshot.get("source_url") or "")
    has_open_source = bool(source_url)

    def refusal(code: str, gaps: list[dict] | None = None) -> DraftReadiness:
        return _refusal(
            code,
            evidence_status=evidence_status,
            fact_count=fact_count,
            has_open_source=has_open_source,
            blocking_gaps=blocking_gaps if gaps is None else gaps,
        )

    # 1. Lifecycle and lineage. A Draft belongs to `preparation` only. The three
    # content checks run BEFORE the derived-state check so the editor is told
    # the specific thing that is wrong (`ARTICLE_HAS_TEXT`, not a generic "not
    # in preparation") — the state is only a summary of these conditions.
    if article.get("finalized_at"):
        return refusal(NOT_IN_PREPARATION)
    if not story or story.get("story_id") != article.get("story_id"):
        return refusal(STORY_UNAVAILABLE)
    if story.get("status") == "IGNORED":
        return refusal(STORY_UNAVAILABLE)

    # The exact content version is re-checked here, so an editor edit that
    # landed while a command was queued fails it instead of overwriting text.
    if int(content.get("content_version", -1)) != int(snapshot.get("content_version", -2)):
        return refusal(ARTICLE_VERSION_CONFLICT)
    if str(content.get("body") or "").strip():
        return refusal(ARTICLE_HAS_TEXT)
    if not str(content.get("title") or "").strip():
        return refusal(WORKING_TITLE_REQUIRED)
    if str(snapshot.get("state") or "") != "preparation":
        return refusal(NOT_IN_PREPARATION)

    # 2. Focus is an independent editorial blocker, never mixed with evidence.
    if not editor_projections.focus_is_confirmed(article):
        return refusal(FOCUS_NOT_CONFIRMED)

    # 3-6. The evidence decision, in one place. V1.1-D2 must be able to ask the
    # same question before an Article exists (§10), so the rules live in
    # `evaluate_evidence` and are applied here rather than restated.
    return evaluate_evidence(
        evidence_status=evidence_status,
        facts=facts,
        blocking_gaps=blocking_gaps,
        source_url=source_url,
    )
