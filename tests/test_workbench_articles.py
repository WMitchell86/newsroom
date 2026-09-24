"""M4F Workbench tests: «Статии» (ideas -> prepare -> generate -> case).

Offline and env-isolated: `WB_EDITORIAL_WORKFLOW_DIR` for the idea/draft/case
stores, `WB_NEWSROOM_DIR` for the story/inbox stores the promote bridge reads.
Generation itself is the real `live_generate_draft` contract (model calls are
only possible with API keys, which tests never provide) — so generation tests
assert the honest refusal paths, and the DRAFTED path is covered by store
invariants: append-only drafts, LIV-nn case ids, audit rows.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from editor_assistant.workflow import angles
from editor_assistant.workflow.workbench import http, state


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # pragma: no cover - trivial
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get(url):
    return _OPENER.open(url, timeout=5)


def _post(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as err:
        return err


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    wf = tmp_path / "editorial_workflow"
    wf.mkdir()
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(wf))
    nr = tmp_path / "newsroom"
    nr.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(nr))
    return wf


@pytest.fixture
def server(stores):
    srv = http.serve(0)  # ephemeral port; `make_server` never existed
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _add_idea(
    idea_id="LIVE-TEST-1",
    title="Тестова идея",
    status="NEW",
    source_type="council_transcript",
):
    ideas = state.load_ideas()
    ideas.append(
        {
            "idea_id": idea_id,
            "created_at": "2026-09-17T10:00:00Z",
            "source_type": source_type,
            "source_url": "transcript://test/1",
            "source_reference": "test",
            "title": title,
            "what_changed": "Комисията гласува бюджет.",
            "why_now": "",
            "location": "Бургас",
            "possible_angle": "",
            "status": status,
        }
    )
    state.save_ideas(ideas)


def _add_packet(
    evidence_id="LIVE-TEST-1-EVIDENCE",
    idea_id="LIVE-TEST-1",
    prepared=None,
    source_type="council_transcript",
    assessment=None,
):
    state._save_live_row(
        {
            "evidence_id": evidence_id,
            "idea_id": idea_id,
            "packet": {
                "evidence_id": evidence_id,
                "source_url": "https://example.bg/lead",
                "source_type": source_type,
                "source_headline": "Заглавие на материала",
                "facts": [{"id": "f1", "text": "Факт"}],
                "quotes": [],
                "unknowns": [],
                "editorial_assessment": assessment,
            },
            "observed_at": "2026-09-17T10:00:00Z",
            "prepared": prepared,
        }
    )


def _weak_assessment():
    """A real rubric-v2 assessment that the angle gate refuses (NO_ANGLE)."""
    packet = {"facts": [{"id": "f1", "text": "Факт"}]}
    candidates = []
    for i in range(1, 4):
        candidates.append(
            {
                "angle_id": f"A{i:02d}",
                "title": f"Тема {i}",
                "reason": "Няма конкретна новост в материала.",
                "new_proposition": f"Какво ново носи това {i}",
                "fact_ids": ["f1"],
                "scores": {
                    key: {"score": 0, "reason": "", "fact_ids": []} for key in angles.CRITERIA
                },
            }
        )
    return angles.assess_angles(packet, candidates)


def _qs(resp):
    """Query params of a 303 redirect (the POST handlers always redirect)."""
    location = resp.headers.get("Location", "")
    return urllib.parse.parse_qs(urllib.parse.urlparse(location).query)


# ---------- F7 regression coverage: the POST /articles write path ----------
# request_draft / prepare / generate had zero tests (the unfinished fixture
# file even called a non-existent http.make_server), which is how the F1
# status-persistence bug survived a green 914-test suite.


def test_post_request_draft_persists_status(server):
    _add_idea()
    resp = _post(f"{server}/articles", {"action": "request_draft", "idea": "LIVE-TEST-1"})
    assert resp.code == 303 and "message" in _qs(resp)
    assert state.load_ideas()[0]["status"] == "DRAFT_REQUESTED"
    assert "draft_requested" in [a["action"] for a in state.read_actions()]


def test_post_prepare_persists_draft_requested_status(server):
    _add_idea(source_type="upstream_press_release")
    _add_packet(source_type="upstream_press_release")
    resp = _post(
        f"{server}/articles",
        {"action": "prepare", "idea": "LIVE-TEST-1", "evidence": "LIVE-TEST-1-EVIDENCE"},
    )
    assert resp.code == 303
    assert "message" in _qs(resp) and "error" not in _qs(resp)
    # F1: the status change made by live_case_request must actually persist.
    assert state.load_ideas()[0]["status"] == "DRAFT_REQUESTED"
    row = state.load_live_rows()["LIVE-TEST-1-EVIDENCE"]
    assert row["prepared"]["voice"] and row["prepared"]["mode"]
    assert not row.get("last_refusal")
    assert "case_prepared" in [a["action"] for a in state.read_actions()]


def test_post_prepare_no_angle_refusal_persists_status(server):
    _add_idea()
    _add_packet(assessment=_weak_assessment())
    resp = _post(
        f"{server}/articles",
        {"action": "prepare", "idea": "LIVE-TEST-1", "evidence": "LIVE-TEST-1-EVIDENCE"},
    )
    assert resp.code == 303
    assert _qs(resp).get("message", [""])[0].startswith("Без публикуем ъгъл")
    # F1 (refusal branch): the NO_ANGLE verdict must persist too.
    assert state.load_ideas()[0]["status"] == angles.NO_ANGLE
    assert "prepare_refused_no_angle" in [a["action"] for a in state.read_actions()]


def test_post_generate_without_prepare_refuses_side_effect_free(server, stores):
    _add_idea(source_type="upstream_press_release")
    _add_packet(source_type="upstream_press_release")
    resp = _post(
        f"{server}/articles",
        {"action": "generate", "idea": "LIVE-TEST-1", "evidence": "LIVE-TEST-1-EVIDENCE"},
    )
    assert resp.code == 303
    assert "error" in _qs(resp)  # «първо подготви случая (глас и режим)»
    assert state.load_cases() == []
    assert not (stores / "live_drafts.jsonl").exists()


# ---------- G2 parity: a closed idea can no longer be revived from the UI ----------


@pytest.mark.parametrize("closed_status", ["IGNORED", "NO_PUBLISHABLE_ANGLE"])
def test_post_prepare_refuses_a_closed_idea_without_touching_any_store(server, closed_status):
    """The Workbench runs the SAME canonical `assert_draftable_status` guard
    the CLI uses: readable Bulgarian refusal, zero mutation, no audit success."""
    _add_idea(status=closed_status)
    _add_packet()
    before_ideas = state.ideas_path().read_bytes()

    resp = _post(
        f"{server}/articles",
        {"action": "prepare", "idea": "LIVE-TEST-1", "evidence": "LIVE-TEST-1-EVIDENCE"},
    )
    assert resp.code == 303
    params = _qs(resp)
    assert "error" in params and closed_status in params["error"][0]
    assert "message" not in params
    # every store byte-identical: idea unchanged, no prepared row, no audit
    assert state.ideas_path().read_bytes() == before_ideas
    row = state.load_live_rows()["LIVE-TEST-1-EVIDENCE"]
    assert not row.get("prepared")
    actions = [a["action"] for a in state.read_actions()]
    assert "case_prepared" not in actions and "prepare_refused_no_angle" not in actions
    assert state.load_cases() == []


def test_post_prepare_still_works_for_draftable_statuses(server):
    """Parity cut both ways: NEW/FOLLOW_UP/DRAFT_REQUESTED keep preparing."""
    _add_idea(source_type="upstream_press_release", status="FOLLOW_UP")
    _add_packet(source_type="upstream_press_release")
    resp = _post(
        f"{server}/articles",
        {"action": "prepare", "idea": "LIVE-TEST-1", "evidence": "LIVE-TEST-1-EVIDENCE"},
    )
    assert resp.code == 303
    params = _qs(resp)
    assert "message" in params and "error" not in params
    assert state.load_ideas()[0]["status"] == "DRAFT_REQUESTED"
    assert state.load_live_rows()["LIVE-TEST-1-EVIDENCE"].get("prepared")


def test_save_ideas_validation_failure_never_truncates_the_store():
    # F2: ideas.save_ideas must validate + serialize BEFORE touching the file
    # (it used to truncate first, so a bad idea destroyed the whole store).
    _add_idea("IDEA-KEEP-1")
    _add_idea("IDEA-KEEP-2")
    keep = state.load_ideas()
    with pytest.raises(ValueError):
        state.save_ideas([keep[0], {"idea_id": ""}])
    assert state.load_ideas() == keep
