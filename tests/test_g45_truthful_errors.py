"""V1.2-G4.5 — an error the editor reads must be one the system observed.

Four measured failures, each pinned where it was observed:

* a provider detail carried a bearer token straight into the editor's message;
* the generic Research/Refresh envelope echoed the raw exception text and
  invented a source cause for it;
* a second Quick Draft with a fresh key could overwrite the in-flight guard and
  orphan the first operation, which kept running while the editor saw nothing;
* an unwritable operation ledger would have failed a request that should have
  succeeded, because the mirror is best-effort by contract.

The quota side of G4.5 (`QUOTA_AMBIGUOUS` vs `QUOTA_EXHAUSTED`) lives with the
routing policy it belongs to, in `tests/test_model_policy.py`.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from editor_assistant.workflow import article_generation, quick_draft, story_operations
from editor_assistant.workflow import editor_application as app

# --------------------------------------------------------------------------
# §G4.5 error detail — fail closed on anything that looks like a credential
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "detail",
    [
        "upstream 401: Authorization: Bearer sk-live-abcdef123456",
        "POST https://openrouter.ai/api/v1/chat failed with AIzaSyExample12345",
        "the call carried ?api_key=deadbeefcafe0123456789 and timed out",
        "config /home/test/.config/router.json says api_key = hunter2hunter2",
    ],
)
def test_a_credential_in_the_detail_never_reaches_the_editor(detail: str):
    """Redaction drops the whole bounded detail rather than masking a piece of it."""
    assert article_generation.safe_detail(detail) == ""


def test_a_real_reason_is_kept_and_still_bounded():
    """The reason is what makes a failure diagnosable - when it holds no secret."""
    reason = "429 RESOURCE_EXHAUSTED: the provider rate limit is in force"
    assert article_generation.safe_detail(reason) == reason
    long_reason = "причината: " + "а" * 400
    assert len(article_generation.safe_detail(long_reason)) == 160


# --------------------------------------------------------------------------
# §G4.5 envelope — a classified refusal keeps its code, nothing else does
# --------------------------------------------------------------------------


def test_an_unclassified_failure_is_not_echoed_back_to_the_editor():
    detail = (
        "openrouter/gemini-3-flash failed at /home/test/.config/router.json "
        "with sk-1234567890abcdef while POSTing the request"
    )
    envelope = app._generic_operation_error("s-one", "", detail)

    assert envelope["code"] == "OPERATION_UNAVAILABLE"
    assert envelope["retryable"] is True
    # Nothing from the raw text may cross into the editor's message - it can
    # carry a provider name, a path or an echoed credential.
    for leaked in ("openrouter", "gemini", "/home/test", "sk-1234"):
        assert leaked not in envelope["message"]


def test_a_classified_research_refusal_keeps_its_own_sentence():
    envelope = app._generic_operation_error(
        "s-one", "INSUFFICIENT_CORROBORATION", "raw provider text"
    )

    assert envelope["code"] == "RESEARCH_NOT_CONFIRMED"
    assert envelope["message"] == app.EditorResearchNotConfirmed.default_message
    assert "raw provider text" not in envelope["message"]


def test_a_classified_refresh_refusal_keeps_its_own_sentence():
    envelope = app._generic_operation_error(app.REFRESH_SCOPE, "REFRESH_BUSY", "")

    assert envelope == {
        "code": "REFRESH_BUSY",
        "message": "Обновяването вече тече. Изчакайте да завърши.",
        "retryable": True,
    }


# --------------------------------------------------------------------------
# §G4.5 in-flight guard — reattach, never orphan
# --------------------------------------------------------------------------


def test_a_second_quick_draft_cannot_orphan_a_running_one():
    """Two fresh keys raced past the §29 check: the guard still decides.

    The first operation owns the guard and is still `running`, so the second
    must reattach to it. Silently overwriting would leave the first running
    unobserved: the registry still runs it while the editor is told a different
    operation started.
    """
    gate = threading.Event()
    token, _view = story_operations.start(quick_draft.scope_for("s-one"), "", gate.wait)
    quick_draft.acquire("s-one", token)

    with pytest.raises(quick_draft.GuardBusy) as busy:
        quick_draft.acquire("s-one", "op_" + "b" * 24)
    assert busy.value.token == token, "the caller is handed the token it must reattach to"

    gate.set()
    for _ in range(500):
        row = story_operations.get(token)
        if row is not None and row["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    else:  # pragma: no cover - the gated work above always finishes
        raise AssertionError("the first operation never settled")

    # Released by a settled operation, the guard is claimable again.
    quick_draft.acquire("s-one", "op_" + "b" * 24)


# --------------------------------------------------------------------------
# §G4.5 registry boundary — the Operations LIST leaked what the single
# operation endpoint had already been fixed not to leak
# --------------------------------------------------------------------------


class _Classified(Exception):
    """A refusal that named itself, the way a real command classifies one."""

    code = "PROVIDER_UNAVAILABLE"


def _run_to_completion(work, scope="s-one", key=""):
    token, _view = story_operations.start(scope, key, work)
    for _ in range(500):
        row = story_operations.get(token)
        if row is not None and row["status"] in {"succeeded", "failed"}:
            return token, row
        time.sleep(0.01)
    raise AssertionError("the operation never settled")  # pragma: no cover


def test_the_operations_list_never_carries_an_unobserved_cause():
    """A measured leak, pinned where it was observed.

    `GET /api/v1/operations` returned the raw exception, and the Operations page
    renders it verbatim. A provider failure therefore showed the editor
    "openrouter/gemini-3 failed at /home/test/.config/router.json" - a provider
    name and this machine's filesystem path, presented as the reason for a
    failure the system had not actually diagnosed. G4.5 had already fixed the
    single-operation envelope and missed this one.
    """

    def explode():
        raise RuntimeError("openrouter/gemini-3 failed at /home/test/.config/router.json")

    _token, row = _run_to_completion(explode)
    assert row["error_code"] == "", "this failure is unclassified by construction"
    # The raw text is still recorded for whoever is debugging - withholding it
    # from the editor is not the same as throwing it away.
    assert "router.json" in row["error"]

    listed = story_operations.recent()
    blob = json.dumps(listed, ensure_ascii=False)
    for leaked in ("openrouter", "gemini", "/home/test", "router.json"):
        assert leaked not in blob, f"{leaked} reached the Operations list"
    # A neutral sentence, NOT silence: `OperationsPage` renders `op.error` only
    # when it is non-empty, so "" is a red badge with no cause - the exact
    # symptom G4.6 exists to remove. The sentence names no cause because none
    # was observed, which is the part that must stay true.
    assert listed[0]["error"] == story_operations._UNOBSERVED_REASON
    assert "източник" not in listed[0]["error"].lower()

    for scoped in story_operations.last_for_scope("s-one"):
        assert scoped["error"] == story_operations._UNOBSERVED_REASON


def test_a_classified_reason_is_still_shown_in_the_operations_list():
    """Withholding the unobserved is not the same as silencing everything.

    A refusal that named itself carries the editor's own sentence, and that is
    the whole value of the Operations page: the row has to say WHICH failure
    happened, or the editor is back to a red badge with no cause.
    """

    def refused():
        raise _Classified("Моделът не отговаря.")

    token, row = _run_to_completion(refused)
    assert row["error_code"] == "PROVIDER_UNAVAILABLE"

    listed = [item for item in story_operations.recent() if item["operationToken"] == token]
    assert listed, "the settled operation must be listed"
    assert listed[0]["errorCode"] == "PROVIDER_UNAVAILABLE"
    assert listed[0]["error"] == "Моделът не отговаря."

    scoped = story_operations.last_for_scope("s-one")
    assert scoped[0]["error"] == "Моделът не отговаря."


def test_a_secret_in_a_classified_reason_is_still_redacted():
    """Classification earns a reason, not a licence to leak a credential."""

    def leaky():
        raise _Classified("upstream rejected Authorization: Bearer sk-live-abcdef123456")

    _run_to_completion(leaky)
    blob = json.dumps(story_operations.recent(), ensure_ascii=False)
    assert "sk-live" not in blob and "Bearer" not in blob
    # A classified reason that IS a credential degrades to the neutral sentence,
    # not to the credential and not to nothing.
    assert story_operations.recent()[0]["error"] == story_operations._UNOBSERVED_REASON


def test_the_single_operation_envelope_keeps_its_own_diagnosable_policy():
    """`get()` is deliberately raw: the envelope decides what may be shown.

    The point of the split is that asking about ONE operation is how a provider
    failure stays diagnosable, so the registry must not launder the text before
    `operation_status` gets to apply its own rule.
    """

    def refused():
        raise _Classified("Моделът не отговаря.")

    token, _row = _run_to_completion(refused)
    assert story_operations.get(token)["error"] == "Моделът не отговаря."


# --------------------------------------------------------------------------
# §G4.6 ledger — a best-effort mirror never fails a request
# --------------------------------------------------------------------------


def test_a_failed_ledger_write_does_not_fail_the_operation(monkeypatch, caplog):
    """`_write_ledger` promises to lose history rather than fail the request."""
    monkeypatch.setenv("WB_OPERATIONS_LEDGER_PATH", "/dev/null/operations.json")

    with caplog.at_level(logging.WARNING, logger="editor_assistant.workflow.story_operations"):
        story_operations._write_ledger()

    assert any("ledger write failed" in record.getMessage() for record in caplog.records)


# --------------------------------------------------------------------------
# §G4.37 history — a finished operation is bounded by COUNT, never by a clock
# --------------------------------------------------------------------------


def test_a_finished_operation_is_never_silenced_by_age():
    """The registry forgot settled work 15 minutes after it finished.

    Measured: `_prune` deleted every finished row once its `updated_at` passed
    `TTL_SECONDS = 900`, while `recent()` and `last_for_scope()` read only the
    in-memory `_ROWS`. The durable ledger - mirrored to `var/operations.json`
    precisely so a lost operation stays visible instead of looking like one
    nobody asked for - therefore kept the row while the editor-visible index
    went empty.

    Two consequences, and this pins both: the Operations page lost every entry
    after 15 quiet minutes, and `quick_draft.availability.lastAttempt` forgot a
    refusal, so Today offered «Чернова» again with the reason nowhere on screen.
    That is the symptom V1.2-G4.36 exists to remove, so an expired row is not a
    cache eviction here - it is the defect coming back in a later costume.
    """

    def refused():
        return quick_draft.result_needs_attention(
            "s-one", "NO_DRAFT_MATERIAL", "Няма от какво да се напише чернова."
        )

    scope = quick_draft.scope_for("s-one")
    token, row = _run_to_completion(refused, scope=scope)
    # The WORK succeeded; the COMMAND refused. Both facts are recorded, and it
    # is the second one the editor needs (V1.2-G4.36).
    assert row["status"] == "succeeded"
    assert row["result"]["status"] == quick_draft.NEEDS_ATTENTION

    # Age the settled row well past the expiry that used to delete it.
    story_operations._ROWS[token]["updated_at"] -= 24 * 60 * 60

    listed = [item for item in story_operations.recent() if item["operationToken"] == token]
    assert listed, "a finished operation must stay in the index"
    assert listed[0]["outcome"] == quick_draft.NEEDS_ATTENTION
    assert listed[0]["outcomeCode"] == "NO_DRAFT_MATERIAL"

    scoped = story_operations.last_for_scope(scope)
    assert [item["operationToken"] for item in scoped] == [token]
    assert scoped[0]["outcome"] == quick_draft.NEEDS_ATTENTION

    # The user-facing half: the Today row must still say the attempt failed,
    # rather than offering the button as if nothing had been asked.
    view = quick_draft.availability(story={"story_id": "s-one"}, articles=[], contents={})
    assert view["lastAttempt"] is not None
    assert view["lastAttempt"]["status"] == "failed"
    assert view["lastAttempt"]["errorCode"] == "NO_DRAFT_MATERIAL"
    assert view["lastAttempt"]["error"] == "Няма от какво да се напише чернова."


def test_the_registry_is_bounded_by_count_and_never_evicts_live_work():
    """Removing the clock must not remove the bound.

    `MAX_OPERATIONS` is now the only limit, and it must only ever take FINISHED
    rows: evicting a `pending`/`running` row would orphan live work, because the
    worker's own `release` then no-ops on token inequality while the thread keeps
    running.
    """
    gate = threading.Event()
    live = []
    try:
        for index in range(story_operations.MAX_OPERATIONS):
            token, _view = story_operations.start(f"s-live-{index}", "", gate.wait)
            live.append(token)
        # `MAX_OPERATIONS` live rows fill the registry; a new one must be told
        # the truth rather than quietly discarding a running operation.
        with pytest.raises(story_operations.BusyError):
            story_operations.start("s-one-too-many", "", gate.wait)
    finally:
        gate.set()
        for token in live:
            for _ in range(500):
                row = story_operations.get(token)
                if row is not None and row["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.01)
    for token in live:
        assert story_operations.get(token) is not None, token
