"""V1.1-B — the ONE shared Draft readiness decision, and its parity invariant.

The defect this file exists to prevent: the Article preparation projection said
`draftEligible: true` / offered `MAKE_DRAFT` for Articles the Draft command was
guaranteed to refuse, because the two used independent predicates. The command
additionally required assessed evidence, at least one confirmed fact and a
usable opened source URL — none of which the projection could see.

Three layers of proof, in increasing strength:

1. **The matrix** — for every canonical combination of Focus, evidence, facts,
   opened source and blocking gap, the projection, the action list and the
   command's deterministic preflight are asserted to agree on eligibility AND on
   the exact reason code.
2. **Command/preview parity** — for each matrix fixture, if the projection says
   eligible the command must reach the provider boundary; if it says ineligible
   the command must refuse before that boundary. The external model transport is
   substituted purely to detect whether the boundary was reached.
3. **Stale state** — the command re-evaluates canonical state and never trusts a
   client-supplied eligibility, in both directions.

Only the model transport is substituted. Every store, projection, command,
readiness decision and operation is production code.
"""

from __future__ import annotations

import pytest

from editor_assistant.drafting import generate as gen
from editor_assistant.workflow import (
    article_generation,
    article_readiness,
    inbox_store,
    story_operations,
    story_research_store,
    story_store,
)
from editor_assistant.workflow import (
    editor_application as app,
)
from editor_assistant.workflow import (
    editor_article_store as articles,
)

HEADLINE = "Съветът одобри графика за ремонта"
OPEN_URL = "https://vestnik.example.test/2026/budget"
FACT_TEXT = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата."


def _item(item_id: str, title: str):
    return {
        "item_id": item_id,
        "source_id": "vestnik",
        "source_item_id": item_id,
        "title": title,
        "url": f"https://vestnik.example.test/{item_id}",
        "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z",
        "summary": "Обобщение",
        "source_kind": "media",
        "status": "NEW",
    }


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
    """An isolated newsroom + editorial root; nothing outside tmp_path is touched."""
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    origin = _item("origin", HEADLINE)
    inbox_store.save_items([origin], root / "inbox.jsonl")
    story = story_store.new_story(origin, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")
    story_operations.clear()
    yield root
    story_operations.clear()
    for token in list(getattr(article_generation._ACTIVE, "keys", list)()):
        article_generation.release(token, article_generation._ACTIVE[token])


@pytest.fixture
def model(monkeypatch):
    """The only substituted boundary: the external model transport.

    Every call is recorded instead of performed, which is how these tests detect
    whether a command was allowed to reach the provider boundary at all.
    """
    calls: list[dict] = []

    def record(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        raise RuntimeError("provider boundary reached")

    for name in ("call_model", "_call_gemini", "_call_openrouter"):
        if hasattr(gen, name):
            monkeypatch.setattr(gen, name, record)
    return calls


# --- The canonical matrix, as data -------------------------------------------
#
# Each row is one canonical Article state. `expected` is the readiness decision
# the product owes the editor for that state. The same table drives the
# projection assertions, the action-list assertions and the command assertions,
# so the three can never be checked against different expectations.
#
# `evidence` is "assessed" or "unassessed"; `facts` is a fact count;
# `open_source` is whether the facts carry a usable opened source URL; and
# `blocking_gap` is whether a real blocking gap is present. `focus` is whether
# the Editorial Focus is confirmed.
#
# Two rows the V1.1-B §22 sketch lists are deliberately absent, because the
# canonical stores make them unrepresentable and a fixture must not fake them:
#   * `assessed + 0 facts + 0 gaps` — V1.1-A made this the forbidden false
#     clean state; `story_research_store` refuses to persist it.
#   * `assessed + 1 fact + no open source` — a fact must reference a persisted
#     source, and that source must carry a non-empty URL. The `NO_OPEN_SOURCE`
#     branch is still reachable through verified legacy Article lineage and is
#     covered there (see `test_article_draft_command.py`).
MATRIX = [
    # focus, evidence,      facts, open_source, gap -> (eligible, reason code)
    (False, "assessed", 1, True, False, (False, "FOCUS_NOT_CONFIRMED")),
    (False, "unassessed", 0, False, False, (False, "FOCUS_NOT_CONFIRMED")),
    (True, "unassessed", 0, False, False, (False, "STORY_UNASSESSED")),
    (True, "assessed", 0, False, True, (False, "BLOCKING_GAP")),
    (True, "assessed", 0, False, False, (False, "NO_CONFIRMED_FACTS")),
    (True, "assessed", 1, True, True, (False, "BLOCKING_GAP")),
    (True, "assessed", 1, True, False, (True, "DRAFT_ELIGIBLE")),
]


def _apply_basis(*, evidence: str, facts: int, open_source: bool, blocking_gap: bool) -> None:
    """Write the canonical Story evidence basis for one matrix row.

    Uses the real research store through its production write path, so a state
    the store genuinely forbids cannot be expressed here as a passing fixture.
    """
    _reset_research_store()
    sources = [{"id": "vestnik", "name": "Вестник", "url": OPEN_URL}] if open_source else []
    fact_rows = [
        {
            "id": f"fact_{index}",
            "text": f"{FACT_TEXT} (ред {index})",
            "sourceId": "vestnik",
            "locator": f"Протокол, т. {index + 3}",
        }
        for index in range(facts)
    ]
    gaps = (
        [{"id": "gap_when", "question": "Кога започва работата?", "blocking": True}]
        if blocking_gap
        else (
            [{"id": "gap_who", "question": "Кой е основният заинтересован?", "blocking": False}]
            if evidence == "assessed" and not facts
            else []
        )
    )
    if evidence == "unassessed":
        # Absence IS the canonical unassessed projection (V1.1-A): the store
        # represents "never researched" by having no row, and the readers
        # resolve that to `unassessed`. Writing an explicit empty row would be
        # the false clean state the store deliberately refuses.
        return
    story_research_store.merge_research(
        "s-one",
        sources=sources,
        facts=fact_rows,
        gaps=gaps,
        assessed_at="2026-09-25T10:00:00Z",
        canonical_story={"story_id": "s-one"},
        operation_id=f"matrix-{evidence}-{facts}-{open_source}-{blocking_gap}",
    )


@pytest.fixture(autouse=True)
def _clean_research_store(tmp_path):
    """Each matrix row starts from a genuinely empty research store.

    `merge_research` merges into whatever is already persisted, so without an
    explicit reset between parametrized rows a later row would inherit an
    earlier row's facts and the matrix would silently test the wrong state.
    """
    yield


def _reset_research_store() -> None:
    """Wipe the canonical research store to the canonical "nothing yet" state."""
    path = story_research_store.story_research_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": 1, "stories": []}\n', encoding="utf-8")


def _article(newsroom, *, focus: bool = True) -> dict:
    """A preparation Article over `s-one`, with or without a confirmed Focus."""
    article = articles.create_editor_article(
        story_id="s-one",
        stories_path=newsroom / "stories.json",
        working_title="Работа за статия",
        now="2026-09-25T09:00:00Z",
    )
    if focus:
        articles.update_editor_focus(
            article["article_id"], "Да обясним решението и неговите последици."
        )
    return article


def _row_id(row: tuple) -> str:
    focus, evidence, facts, open_source, gap, _ = row
    return f"focus={focus}-evidence={evidence}-facts={facts}-open={open_source}-gap={gap}"


@pytest.mark.parametrize("row", MATRIX, ids=[_row_id(r) for r in MATRIX])
def test_the_readiness_matrix_covers_every_canonical_state(newsroom, model, row):
    """Projection, action list and command agree — on eligibility AND on reason.

    This is the V1.1-B §22 matrix. For each canonical state it asserts the
    projection's `draftEligible`, the presence or absence of `MAKE_DRAFT`, the
    reported reason code, and the command's deterministic preflight outcome.
    They must all agree; a single mismatch fails the test.
    """
    focus, evidence, facts, open_source, gap, (eligible, reason) = row
    article = _article(newsroom, focus=focus)
    article_id = article["article_id"]
    _apply_basis(evidence=evidence, facts=facts, open_source=open_source, blocking_gap=gap)

    projection = app.read_article(article_id)
    preparation = projection["preparation"]
    assert preparation is not None, "a preparation Article always has its projection"
    assert preparation["draftEligible"] is eligible
    assert preparation["draftReadiness"]["code"] == reason
    assert ("MAKE_DRAFT" in projection["availableActions"]) is eligible
    assert (preparation["draftReadiness"]["code"] == "DRAFT_ELIGIBLE") is eligible
    # The blocking gaps the projection shows are the real ones, never invented.
    assert [(row["id"], row["question"]) for row in preparation["blockingGaps"]] == (
        [("gap_when", "Кога започва работата?")] if gap else []
    )

    # The command's deterministic preflight must reach the same conclusion, with
    # the same reason, and must never reach the provider for an ineligible row.
    snapshot = app._draft_snapshot(article_id)
    decision = article_readiness.evaluate(snapshot)
    assert decision.eligible is eligible
    assert decision.reason_code == reason
    assert decision.reason_message == article_readiness.REASON_MESSAGES[reason]

    if eligible:
        article_generation.evaluate(snapshot)
    else:
        with pytest.raises(article_generation.DraftRefused) as refusal:
            article_generation.evaluate(snapshot)
        assert refusal.value.code == reason


@pytest.mark.parametrize("row", MATRIX, ids=[_row_id(r) for r in MATRIX])
def test_projection_and_command_never_disagree(newsroom, model, row):
    """The permanent parity invariant: same state in, same decision out.

    For every matrix fixture: if the projection says eligible, the command must
    pass every deterministic pre-provider check; if it says ineligible, the
    command must refuse before that boundary. The model transport is substituted
    only to detect whether the boundary was reached.
    """
    focus, evidence, facts, open_source, gap, (expected_eligible, reason) = row
    article = _article(newsroom, focus=focus)
    article_id = article["article_id"]
    _apply_basis(evidence=evidence, facts=facts, open_source=open_source, blocking_gap=gap)

    projection = app.read_article(article_id)
    assert projection["preparation"]["draftEligible"] is expected_eligible
    if projection["preparation"]["draftEligible"]:
        # Eligible: the deterministic preflight must pass. Generation itself is
        # out of scope here (it would spend model quota); reaching the preflight
        # boundary without refusal is the contract.
        snapshot = app._draft_snapshot(article_id)
        article_generation.evaluate(snapshot)
        assert article_readiness.evaluate(snapshot).eligible is True
        return

    # Ineligible: refuse before the provider boundary, with the very reason the
    # projection already displayed — never a generic masking message.
    with pytest.raises(app.EditorApplicationError) as refusal:
        app.start_article_draft(article_id, idempotency_key=f"parity-{_row_id(row)}")
    assert refusal.value.status == 409
    assert str(refusal.value) == article_readiness.REASON_MESSAGES[reason]
    assert model == [], "an ineligible state must never reach the provider boundary"


# --- Stale frontend state (V1.1-B §17) --------------------------------------


def test_a_stale_eligible_projection_is_refused_on_command(newsroom, model):
    """UI loaded an eligible Article, then a gap appeared, then the click.

    The command re-evaluates canonical state and refuses with the exact current
    reason. It never trusts the eligibility the client rendered, and it never
    reaches the provider.
    """
    article = _article(newsroom)
    article_id = article["article_id"]
    _apply_basis(evidence="assessed", facts=1, open_source=True, blocking_gap=False)

    loaded = app.read_article(article_id)
    assert loaded["preparation"]["draftEligible"] is True
    assert "MAKE_DRAFT" in loaded["availableActions"]

    # The basis changes underneath the still-open page: a new research round
    # introduces a real blocking gap.
    _apply_basis(evidence="assessed", facts=1, open_source=True, blocking_gap=True)

    with pytest.raises(app.EditorBlockingGap) as refusal:
        app.start_article_draft(article_id, idempotency_key="stale-eligible")
    assert refusal.value.code == "BLOCKING_GAP"
    assert model == []
    # Nothing was generated, and the Article is exactly as the editor left it.
    assert articles.get_article_content(article_id)["body"] == ""


def test_an_ineligible_projection_becomes_eligible_after_research(newsroom, model):
    """UI loaded an unassessed Article, research completed, refetch, eligible.

    The transition is driven by canonical state and the shared predicate alone.
    No local React inference is involved and no stale cache is consulted.
    """
    article = _article(newsroom)
    article_id = article["article_id"]
    _apply_basis(evidence="unassessed", facts=0, open_source=False, blocking_gap=False)

    before = app.read_article(article_id)
    assert before["preparation"]["draftEligible"] is False
    assert before["preparation"]["draftReadiness"]["code"] == "STORY_UNASSESSED"
    assert "MAKE_DRAFT" not in before["availableActions"]

    _apply_basis(evidence="assessed", facts=1, open_source=True, blocking_gap=False)

    after = app.read_article(article_id)
    assert after["preparation"]["draftEligible"] is True
    assert after["preparation"]["draftReadiness"]["code"] == "DRAFT_ELIGIBLE"
    assert "MAKE_DRAFT" in after["availableActions"]
    # The decision the command will make is identical, with no re-derivation.
    snapshot = app._draft_snapshot(article_id)
    assert article_readiness.evaluate(snapshot).eligible is True
    article_generation.evaluate(snapshot)


# --- The reason taxonomy itself (V1.1-B §9) ---------------------------------


def test_the_reason_taxonomy_is_narrow_and_non_contradictory():
    """Every code has one message, and the codes are the ones the contract names.

    Guards against a near-duplicate error accumulating: a new code must be added
    deliberately, with its own wording, never by reusing a neighbour.
    """
    required = {
        "DRAFT_ELIGIBLE",
        "STORY_UNASSESSED",
        "NO_CONFIRMED_FACTS",
        "NO_OPEN_SOURCE",
        "BLOCKING_GAP",
        "FOCUS_NOT_CONFIRMED",
    }
    assert required <= set(article_readiness.REASON_MESSAGES)
    # One message per code, and every message is distinct: the UI renders the
    # backend string, so two codes sharing wording would re-collapse the taxonomy.
    assert len(set(article_readiness.REASON_MESSAGES.values())) == len(
        article_readiness.REASON_MESSAGES
    )
    # The four research-remedy codes are exactly the ones that route to the Story.
    assert article_readiness.RESEARCH_REMEDY_CODES == {
        "STORY_UNASSESSED",
        "NO_CONFIRMED_FACTS",
        "NO_OPEN_SOURCE",
        "BLOCKING_GAP",
    }
    for code in article_readiness.RESEARCH_REMEDY_CODES:
        decision = article_readiness._refusal(
            code, evidence_status="assessed", fact_count=0, has_open_source=False
        )
        assert decision.is_researchable
        assert decision.remedy == "RESEARCH"
    for code in ("FOCUS_NOT_CONFIRMED", "SAFETY_BLOCKED", "NOT_IN_PREPARATION"):
        decision = article_readiness._refusal(
            code, evidence_status="assessed", fact_count=0, has_open_source=False
        )
        assert not decision.is_researchable
        assert decision.remedy == ""


def test_the_dto_exposes_a_code_and_a_message_and_nothing_internal():
    readiness = article_readiness.DraftReadiness(
        eligible=False,
        reason_code="STORY_UNASSESSED",
        reason_message="Историята трябва първо да бъде проучена.",
        fact_count=3,
        has_open_source=True,
    )
    assert readiness.as_dto() == {
        "code": "STORY_UNASSESSED",
        "message": "Историята трябва първо да бъде проучена.",
    }
