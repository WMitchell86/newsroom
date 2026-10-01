"""V1.2-G4.3 §G, now reachable from the editor's own Settings screen.

The learning loop already existed behind the operator CLI. This slice puts the
same *decision* in the product, and these tests pin the two properties that make
that safe:

* the client never supplies the instruction — it names a `pattern_id`, and the
  proposal is re-analyzed server-side, so a screen can only decide a rule the
  analyzer actually found;
* the threshold gates the DECISION, not merely the report, so no surface can
  approve a rule built from too little evidence.

Levels, as in the Sources contract:

* **service level** — `decide_proposal` is the one place a decision may be made,
  and every refusal leaves the store untouched;
* **HTTP level** — `/api/v1/settings/feedback` is a pure read and
  `/decisions` is the thin decision endpoint.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from editor_assistant.workflow import rewrite_feedback as rfb
from editor_assistant.workflow.workbench import http

_OPENER = urllib.request.build_opener()


@pytest.fixture
def editorial(tmp_path, monkeypatch):
    """An isolated editorial root. The repository's real stores are never read."""
    root = tmp_path / "editorial"
    root.mkdir()
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(root))
    return root


@pytest.fixture
def api_server(editorial):
    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(base, path, *, method="GET", body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        response = _OPENER.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _data(result):
    return result[1]["data"]


def _error(result):
    return result[1]["error"]


def _seed(comments):
    """Real records through the product's own writer, so the log is authentic."""
    for index, comment in enumerate(comments):
        rfb.record(
            article_id=f"art_seed{index}",
            editor_comment=comment,
            draft_version_before=1,
            draft_version_after=2,
        )


def _eligible_comments(pattern="direct_lead"):
    if pattern == "shorter_text":
        return ["Съкрати текста."] * rfb.threshold()
    return ["Започни директно с факта."] * rfb.threshold()


# ---------- service: the threshold gates the DECISION ----------


def test_a_proposal_below_the_threshold_is_not_decidable(editorial):
    _seed(["Започни директно с факта."] * 3)
    assert not rfb.is_eligible()
    with pytest.raises(rfb.ProposalNotDecidable) as caught:
        rfb.decide_proposal("direct_lead", approved=True)
    assert caught.value.code == "NOT_ELIGIBLE"
    assert rfb.approved_instructions() == [], "a refused decision must write nothing"
    assert len(rfb.unprocessed()) == 3, "the evidence must stay unprocessed"


def test_only_a_pattern_the_analyzer_found_is_decidable(editorial):
    _seed(_eligible_comments())
    assert rfb.is_eligible()
    with pytest.raises(rfb.ProposalNotDecidable) as caught:
        rfb.decide_proposal("invented_by_the_client", approved=True)
    assert caught.value.code == "UNKNOWN_PATTERN"
    assert rfb.active_instruction_texts() == ()


def test_a_conflict_is_a_question_and_cannot_be_approved(editorial):
    # Both directions present: the analyzer reports the length conflict, and a
    # conflict is never an approvable instruction.
    _seed(_eligible_comments("shorter_text") + _eligible_comments("direct_lead"))
    with pytest.raises(rfb.ProposalNotDecidable) as caught:
        rfb.decide_proposal("conflicting_length", approved=True)
    assert caught.value.code == "CONFLICT"
    assert rfb.active_instruction_texts() == ()


def test_an_approval_becomes_active_and_marks_its_own_evidence(editorial):
    _seed(_eligible_comments())
    pending_before = len(rfb.unprocessed())
    entry = rfb.decide_proposal("direct_lead", approved=True)
    assert entry["approved"] is True
    assert entry["pattern_id"] == "direct_lead"
    assert entry["instruction"] in rfb.active_instruction_texts()
    # The exact records it rested on are now processed, so they are never
    # counted twice.
    assert len(rfb.unprocessed()) == pending_before - entry["support"]


def test_a_rejection_is_recorded_and_never_active(editorial):
    _seed(_eligible_comments())
    entry = rfb.decide_proposal("direct_lead", approved=False)
    assert entry["approved"] is False
    assert rfb.active_instruction_texts() == ()
    # A refusal is a decision: the pattern is retired, not re-proposed.
    assert "direct_lead" in rfb.retired_patterns()


# ---------- HTTP: the Settings screen ----------


def test_the_feedback_screen_reports_pending_threshold_and_active_instructions(api_server):
    _seed(["Започни директно с факта."] * 3)
    status, payload = request(api_server, "/api/v1/settings/feedback")
    assert status == 200
    data = _data((status, payload))
    assert data["pending"] == 3
    assert data["threshold"] == rfb.threshold()
    assert data["eligible"] is False
    assert data["proposals"] == []
    assert data["instructions"] == []


def test_the_screen_offers_no_proposal_until_the_threshold_is_reached(api_server):
    _seed(_eligible_comments())
    data = _data(request(api_server, "/api/v1/settings/feedback"))
    assert data["eligible"] is True
    ids = {row["patternId"] for row in data["proposals"]}
    assert "direct_lead" in ids
    assert all("suggestedInstruction" in row for row in data["proposals"])


def test_a_decision_over_http_is_recorded_and_returns_the_new_state(api_server):
    _seed(_eligible_comments())
    status, payload = request(
        api_server,
        "/api/v1/settings/feedback/decisions",
        method="POST",
        body={"patternId": "direct_lead", "approved": True},
    )
    assert status == 200
    data = _data((status, payload))
    assert data["decision"]["patternId"] == "direct_lead"
    assert data["decision"]["approved"] is True
    # The whole new state travels back, so the screen does not have to guess.
    assert data["instructions"], "the approved instruction must be in the response"
    assert rfb.active_instruction_texts(), "and it must really be active"


def test_the_screen_cannot_invent_an_instruction_over_http(api_server):
    _seed(_eligible_comments())
    status, payload = request(
        api_server,
        "/api/v1/settings/feedback/decisions",
        method="POST",
        body={"patternId": "made_up", "approved": True},
    )
    assert status == 400
    assert _error((status, payload))["code"] == "VALIDATION_ERROR"
    assert rfb.active_instruction_texts() == (), "nothing may reach the prompt"


def test_a_below_threshold_decision_is_refused_over_http(api_server):
    _seed(["Започни директно с факта."] * 3)
    status, _payload = request(
        api_server,
        "/api/v1/settings/feedback/decisions",
        method="POST",
        body={"patternId": "direct_lead", "approved": True},
    )
    assert status == 400
    assert rfb.active_instruction_texts() == ()


def test_the_decision_route_refuses_extra_fields_and_a_non_boolean(api_server):
    _seed(_eligible_comments())
    extra, payload = request(
        api_server,
        "/api/v1/settings/feedback/decisions",
        method="POST",
        body={"patternId": "direct_lead", "approved": True, "instruction": "invented"},
    )
    assert extra == 400, "a client must not be able to supply the instruction text"
    assert _error((extra, payload))["code"] == "VALIDATION_ERROR"

    bad, payload = request(
        api_server,
        "/api/v1/settings/feedback/decisions",
        method="POST",
        body={"patternId": "direct_lead", "approved": "yes"},
    )
    assert bad == 400
    assert rfb.active_instruction_texts() == ()


def test_a_get_on_the_decision_route_is_405_not_404(api_server):
    status, payload = request(api_server, "/api/v1/settings/feedback/decisions")
    assert status == 405
    assert _error((status, payload))["code"] == "VALIDATION_ERROR"
