"""V1.2-G4.1 §B — what counts as enough to START writing.

**The rule this module encodes.** A Draft is work in progress. Missing
information should normally warn the editor, not prevent writing. The previous
contract made research quality equal to permission-to-write: `BLOCKING_GAP`
refused `MAKE_DRAFT` *before* the evaluator ever looked at the facts, so a
Story with four confirmed facts from a real opened source and seven open
questions could not be drafted at all. That is the screen the owner hit.

So the gate is split in two, and this module owns the first half:

  * **Gate 1 — can a Draft be created?** This module. Focus is confirmed, and
    there is *some* source-backed material to write from. Unresolved gaps do not
    stop it; they travel with the Draft as warnings.
  * **Gate 2 — can it be marked Ready?** `article_validation`, unchanged in
    strength and now genuinely reachable only after a Draft exists. Unresolved
    blocking gaps, unsupported claims and conflicts stop `Отбележи като готова`.

**Three ways to qualify**, in the order the brief sets out:

  * `PROMOTED` — confirmed/promoted facts that carry opened URLs. The existing,
    strongest path; a Draft from it needs no single-source caveat.
  * `PRIMARY` — one opened source the editor's own source settings make a
    factual authority (G4 stays authoritative). An official source may establish
    its own first-party facts.
  * `SINGLE_SOURCE` — the prototype fallback: one ordinary opened publisher page
    with extractable content. This produces an **attributed** Draft, never an
    independently confirmed one, and it always carries the single-source warning.

**What is never enough (§B4).** A search or aggregator snippet, an unresolved
wrapper, or a title with no opened page behind it. The fallback requires a page
that was actually fetched and yielded content, which is what `story_research`
now records as an opened-but-unpromoted source. A snippet can never reach a
Draft, because a snippet was never opened.

**No new state.** This module decides eligibility and produces warnings. It does
not add an Article state, change a gap's `blocking` flag, or touch the store.
The three Article states stay exactly `Подготовка` / `Чернова` / `Готова`.
"""

from __future__ import annotations

from editor_assistant.workflow import single_source_policy

#: The three ways a Draft may start. Ordered strongest first.
PROMOTED = "PROMOTED"
PRIMARY = "PRIMARY"
SINGLE_SOURCE = "SINGLE_SOURCE"

#: Stable reason codes for the Draft gate. The only genuine refusals left are
#: the two below: there is nothing to write from. A Story that has simply never
#: been researched is still reported as such, so the editor is sent to research
#: rather than shown a vague "no material".
NO_MATERIAL = "NO_MATERIAL"
NEVER_RESEARCHED = "NEVER_RESEARCHED"



def is_opened_publisher_source(source: dict) -> bool:
    """§B4 — is this an opened real publisher page, not a snippet/wrapper?

    Reuses the already-measured `single_source_policy` publisher test rather
    than growing a second host list: an aggregator, a social wrapper or a
    `news.google.com` redirect can never support even an attributed Draft.
    """
    return single_source_policy.is_publisher(source)


def primary_source_ids(sources) -> set[str]:
    """Ids of sources the editor's own settings make a factual authority.

    This reads the SAME `factual_authority` the research path already resolves
    through `newsroom_run.resolve_publisher_policy`, matched by publisher
    identity (so `www.burgas.bg` is `burgas.bg`). It introduces no new trust
    system: G4's `Надежден за факти` remains the only authority in the product.
    """
    ids: set[str] = set()
    for source in sources or ():
        row = source or {}
        if not row.get("factualAuthority") and not row.get("factual_authority"):
            continue
        if str(row.get("authority") or "").upper() == "PRIMARY":
            ids.add(str(row.get("id") or ""))
    return {value for value in ids if value}


def assess(
    *,
    facts,
    sources=(),
    blocking_gaps=(),
    evidence_status="assessed",
) -> dict:
    """The one Draft-material decision. Pure; reads only canonical rows.

    Returns a record the readiness layer and the UI both read, so the reason a
    Draft button is offered and the reason it is not can never be two different
    sentences about one state.

    ```text
    basis        PROMOTED | PRIMARY | SINGLE_SOURCE | "" (nothing usable)
    eligible     may a Draft start now
    reason_code  a stable code, "" when eligible
    warnings     warnings the resulting Draft must carry
    attribution  the text must name this single source
    ```
    """
    facts = list(facts or ())
    sources = list(sources or ())
    gaps = list(blocking_gaps or ())

    # A conflict is a real editorial obstacle (§C2) and it is checked FIRST, on
    # any basis. Two opened sources disagreeing about the same proposition is not
    # something to write around, and it is the one gap kind that is not demoted
    # to a warning. It was previously only consulted on the no-facts path, which
    # would have let a Story carrying both a conflict and a promoted fact write
    # straight through it.
    if any(str(gap.get("kind") or "") == "conflict" for gap in gaps):
        return {
            "basis": "",
            "eligible": False,
            "reason_code": NO_MATERIAL,
            "warnings": [],
            "attribution": False,
        }

    # §B3 A. Confirmed facts that actually carry an opened source URL are the
    # strongest material and need no caveat. This is the path that already
    # worked.
    #
    # The URL is required, not cosmetic: a fact whose source was never opened
    # cannot be attributed, checked or re-read, so it is not material a Draft
    # may be built from (§B4). Such a fact still counts towards confirmation
    # elsewhere; here it simply does not license writing.
    usable_facts = [
        fact
        for fact in facts
        if str(((fact or {}).get("source") or {}).get("url") or "").strip()
    ]
    if usable_facts:
        return {
            "basis": PROMOTED,
            "eligible": True,
            "reason_code": "",
            "warnings": [WARNING_OPEN_GAPS] if gaps else [],
            "attribution": False,
        }

    # §B3 B/C. No promoted fact, but a page really was opened. The opened
    # source carries its own claims, so it is real source-backed material.
    opened = [row for row in sources if is_opened_publisher_source(row)]
    if not opened:
        return {
            "basis": "",
            "eligible": False,
            "reason_code": (
                NEVER_RESEARCHED if evidence_status != "assessed" else NO_MATERIAL
            ),
            "warnings": [],
            "attribution": False,
        }

    if primary_source_ids(opened):
        # An official PRIMARY may establish its own first-party facts (§B3 B).
        return {
            "basis": PRIMARY,
            "eligible": True,
            "reason_code": "",
            "warnings": [WARNING_OPEN_GAPS] if gaps else [],
            "attribution": False,
        }

    # §B3 C — the prototype fallback. One real opened publisher page is enough
    # to START. It is explicitly not enough to be Ready, and the Draft says so.
    return {
        "basis": SINGLE_SOURCE,
        "eligible": True,
        "reason_code": "",
        "warnings": [WARNING_SINGLE_SOURCE] + ([WARNING_OPEN_GAPS] if gaps else []),
        "attribution": True,
    }

#: §B6 — the one honest message for "there is genuinely nothing to write from".
NO_MATERIAL_MESSAGE = "Няма достатъчно изходен материал за чернова."

#: §B3 — the warning a single-source Draft must always carry. This is a warning
#: and never a state: the editor can write, and must know what they are writing
#: from before the text becomes `Готова`.
WARNING_SINGLE_SOURCE = "Информацията е от един източник и не е независимо потвърдена."

#: §B3 — the warning shown when a Draft is started while questions are still
#: open. The gaps themselves are rendered by the existing gap list; this says
#: plainly that they remain, so the Draft can never look finished by accident.
WARNING_OPEN_GAPS = "Остава информация за проверка преди черновата да е готова."

#: §C2 — the same condition phrased for an Article that is already a Draft. The
#: Preparation wording ("преди черновата да е готова") would be wrong there,
#: because the question is no longer whether to start writing but whether the
#: text may be declared finished.
WARNING_OPEN_DRAFT = "Остава информация за проверка преди статията да бъде отбелязана като готова."
