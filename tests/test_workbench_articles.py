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
    srv = http.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _add_idea(idea_id="LIVE-TEST-1", title="Тестова идея", status="NEW"):
    ideas = state.load_ideas()
    ideas.append(
        {
            "idea_id": idea_id,
            "created_at": "2026-09-17T10:00:00Z",
            "source_type": "council_transcript",
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


def _add_packet(evidence_id="LIVE-TEST-1-EVIDENCE", idea_id="LIVE-TEST-1", prepared=None):
    state._save_live_row(
        {
            "evidence_id": evidence_id,
            "idea_id": idea_id,
            "packet": {
                "source_url": "https://example.bg/lead",
                "source_type": "council_transcript",
                "facts": [{"fact_id": "f1", "text": "Факт"}],
                "quotes": [],
                "unknowns": [],
            },
            "observed_at": "2026-09-17T10:00:00Z",
            "prepared": prepared,
        }
    )
