"""D2B: the SPA is now the default editor frontend; legacy is explicit rollback.

The cutover itself is deliberately small. These tests pin exactly the two
behaviors an operator depends on, plus the safety properties around them:

1. a normal start with **no** ``WB_EDITOR_FRONTEND`` serves the compiled SPA on
   the primary editor routes;
2. ``WB_EDITOR_FRONTEND=legacy`` restores the server-rendered Workbench on those
   same routes, with no code change, no migration and no rebuild.

Runtime stores are isolated through the standard env overrides, so the real
``var/`` stores are never touched by any test in this module.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from editor_assistant.workflow.workbench import http, spa

_OPENER = urllib.request.build_opener()

#: The exact primary editor routes the cutover moves (§8).
PRIMARY_ROUTES = [
    "/",
    "/stories",
    "/stories/s-one",
    "/articles",
    "/articles/art_1",
    "/archive",
    "/archive/art_1",
    "/settings",
]

#: Backend/operator surfaces that must not change owner in any mode (§8/§20).
BACKEND_ROUTES = ["/healthz", "/static/style.css", "/cases", "/inbox", "/models", "/sources"]


def _get(base, path):
    try:
        response = _OPENER.open(f"{base}{path}", timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read(), dict(response.headers)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    newsroom = tmp_path / "newsroom"
    newsroom.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(newsroom))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    monkeypatch.delenv(spa.FRONTEND_MODE_ENV, raising=False)


@pytest.fixture
def build(tmp_path):
    """A minimal but realistic compiled build (hashed names, nested assets)."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><html lang="bg"><head>'
        '<script type="module" crossorigin src="/assets/index-CCWo5GjE.js"></script>'
        '<link rel="stylesheet" crossorigin href="/assets/index-CXmK9Rrr.css">'
        '</head><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (root / "assets" / "index-CCWo5GjE.js").write_bytes(b"console.log('spa');\n")
    (root / "assets" / "index-CXmK9Rrr.css").write_text("body{margin:0}\n", encoding="utf-8")
    return root


def _server():
    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _serving(monkeypatch, build, mode):
    """A running server with the given frontend environment.

    ``mode=None`` means the variable is *absent* — an ordinary production start.
    """
    monkeypatch.setenv(spa.SPA_DIST_ENV, str(build))
    if mode is None:
        monkeypatch.delenv(spa.FRONTEND_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, mode)
    return _server()


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


# --------------------------------------------------------------------------
# §6 — the new default
# --------------------------------------------------------------------------


class TestDefaultIsSpa:
    def test_a_normal_start_serves_the_spa_on_every_primary_route(self, monkeypatch, build):
        """No ``WB_EDITOR_FRONTEND`` at all: the SPA owns the primary routes."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            for path in PRIMARY_ROUTES:
                status, body, headers = _get(base, path)
                assert status == 200, (path, status)
                assert b'<div id="root">' in body, path
                assert headers["Content-Type"] == "text/html; charset=utf-8", path
        finally:
            _stop(server, thread)

    def test_the_default_is_indistinguishable_from_explicit_spa(self, monkeypatch, build):
        """Default and explicit ``spa`` must be the same thing to a client."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            _, default_body, default_headers = _get(base, "/")
        finally:
            _stop(server, thread)

        server, thread, base = _serving(monkeypatch, build, spa.MODE_SPA)
        try:
            _, explicit_body, explicit_headers = _get(base, "/")
        finally:
            _stop(server, thread)

        assert default_body == explicit_body
        assert default_headers["Content-Type"] == explicit_headers["Content-Type"]

    def test_deep_links_work_without_any_configuration(self, monkeypatch, build):
        """§19: a pasted nested URL is the same document as ``/``."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            _, root_body, _ = _get(base, "/")
            for path in ["/stories/s-one", "/articles/art_1", "/archive/art_1"]:
                status, body, _ = _get(base, path)
                assert status == 200, (path, status)
                assert body == root_body, path
        finally:
            _stop(server, thread)


# --------------------------------------------------------------------------
# §9 — explicit rollback
# --------------------------------------------------------------------------


class TestLegacyRollback:
    def test_one_variable_restores_the_server_rendered_workbench(self, monkeypatch, build):
        """`WB_EDITOR_FRONTEND=legacy` brings back the old primary routes."""
        server, thread, base = _serving(monkeypatch, build, spa.MODE_LEGACY)
        try:
            for path in ["/", "/stories", "/articles", "/settings"]:
                status, body, _ = _get(base, path)
                assert status == 200, (path, status)
                assert b"<!doctype html>" in body.lower(), path
                assert b'<div id="root">' not in body, path
        finally:
            _stop(server, thread)

    def test_rollback_serves_nothing_of_the_compiled_bundle(self, monkeypatch, build):
        server, thread, base = _serving(monkeypatch, build, spa.MODE_LEGACY)
        try:
            for path in ["/", "/stories", "/articles", "/settings"]:
                _, body, _ = _get(base, path)
                assert b"index-CCWo5GjE.js" not in body, path
            status, _, _ = _get(base, "/assets/index-CCWo5GjE.js")
            assert status == 404, status
        finally:
            _stop(server, thread)

    def test_rollback_consumes_no_build_and_no_data(self, monkeypatch, build):
        """§9: only the environment differs — same build, same stores, same routes."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            spa_status, spa_body, _ = _get(base, "/")
        finally:
            _stop(server, thread)

        server, thread, base = _serving(monkeypatch, build, spa.MODE_LEGACY)
        try:
            legacy_status, legacy_body, _ = _get(base, "/")
        finally:
            _stop(server, thread)

        assert spa_status == legacy_status == 200
        assert b'<div id="root">' in spa_body
        assert b"<!doctype html>" in legacy_body.lower()
        assert (build / "index.html").exists(), "rollback must not consume the build"


# --------------------------------------------------------------------------
# §10 — operational legacy access in SPA mode
# --------------------------------------------------------------------------


class TestOperatorCompatInSpaMode:
    def test_wb_legacy_prefix_still_serves_the_workbench(self, monkeypatch, build):
        """§10: the technical compatibility path survives the cutover."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            for path in ["/", "/stories", "/articles", "/settings", "/cases", "/inbox"]:
                status, body, _ = _get(base, f"/wb-legacy{path}")
                assert status == 200, (path, status)
                assert b"<!doctype html>" in body.lower(), path
                assert b'<div id="root">' not in body, path
        finally:
            _stop(server, thread)

    def test_operator_surfaces_stay_server_rendered(self, monkeypatch, build):
        """§8/§10: the operational pages are not part of the SPA migration."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            for path in BACKEND_ROUTES:
                status, body, _ = _get(base, path)
                assert status == 200, (path, status)
                assert b'<div id="root">' not in body, path
        finally:
            _stop(server, thread)


# --------------------------------------------------------------------------
# §8/§20 — route ownership and API isolation
# --------------------------------------------------------------------------


class TestRouteOwnershipUnderDefault:
    def test_api_and_health_are_never_swallowed(self, monkeypatch, build):
        """§20: no route-precedence regression under the default mode."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            status, body, headers = _get(base, "/api/v1/today")
            assert status == 200, status
            assert headers["Content-Type"] == "application/json; charset=utf-8"
            assert b'<div id="root">' not in body

            status, body, headers = _get(base, "/api/v1/stories")
            assert status == 200, status
            assert headers["Content-Type"] == "application/json; charset=utf-8"

            status, body, headers = _get(base, "/api/v1/not-real")
            assert status == 404, status
            assert json.loads(body)["error"]["code"] == "NOT_FOUND"
            assert b'<div id="root">' not in body

            status, body, _ = _get(base, "/healthz")
            assert status == 200 and body == b"OK\n"
        finally:
            _stop(server, thread)

    def test_unknown_routes_are_still_real_404s(self, monkeypatch, build):
        """The SPA is never a catch-all, in the default mode either."""
        server, thread, base = _serving(monkeypatch, build, None)
        try:
            for path in ["/nope", "/not-a-page", "/stories/extra/segment"]:
                status, body, _ = _get(base, path)
                assert status == 404, (path, status)
                assert b'<div id="root">' not in body, path
        finally:
            _stop(server, thread)


# --------------------------------------------------------------------------
# §14 — startup reporting
# --------------------------------------------------------------------------


def _startup(capsys, monkeypatch, mode, dist):
    """Run the real entry point just far enough to report, then stop it.

    The reporting happens before the server starts blocking, so a stub server
    that raises on ``serve_forever`` captures exactly the operational output an
    operator sees without opening a real socket.
    """
    from editor_assistant.workflow.workbench import __main__ as wb_main

    if mode is None:
        monkeypatch.delenv(spa.FRONTEND_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, mode)
    monkeypatch.setenv(spa.SPA_DIST_ENV, str(dist))

    class _Stub:
        def serve_forever(self):
            raise SystemExit(0)

        def shutdown(self):
            pass

    monkeypatch.setattr(wb_main.http, "serve", lambda *a, **kw: _Stub())
    with pytest.raises(SystemExit):
        wb_main.main(argv=["--port", "0"])
    return capsys.readouterr().err


class TestStartupReporting:
    def test_startup_reports_the_spa_by_default(self, capsys, monkeypatch, build):
        """§14: the operator is told which editor owns the primary routes."""
        err = _startup(capsys, monkeypatch, None, build)
        assert "Editor frontend: SPA" in err
        assert str(build / "index.html") in err
        assert "Editor frontend: legacy" not in err

    def test_startup_reports_legacy_on_rollback(self, capsys, monkeypatch, build):
        err = _startup(capsys, monkeypatch, spa.MODE_LEGACY, build)
        assert "Editor frontend: legacy" in err
        assert "server-rendered Workbench" in err
        assert "Editor frontend: SPA" not in err

    def test_the_report_is_operational_logging_not_a_browser_banner(self):
        """§14: it goes to stderr, so it never reaches an editor screen."""
        from editor_assistant.workflow.workbench import __main__ as wb_main

        source = (
            spa.ROOT / "src" / "editor_assistant" / "workflow" / "workbench" / "__main__.py"
        ).read_text(encoding="utf-8")
        assert "Editor frontend:" in source
        for line in source.splitlines():
            if "Editor frontend:" in line:
                assert "file=sys.stdout" not in line, line
        assert wb_main.__name__ == "editor_assistant.workflow.workbench.__main__"


# --------------------------------------------------------------------------
# §15 — a missing SPA build must fail loudly
# --------------------------------------------------------------------------


class TestMissingBuildIsLoud:
    def test_a_normal_start_without_a_build_refuses_to_serve(self, monkeypatch, capsys, tmp_path):
        """§15: the default is the SPA, so a missing build is a startup failure."""
        from editor_assistant.workflow.workbench import __main__ as wb_main

        monkeypatch.delenv(spa.FRONTEND_MODE_ENV, raising=False)
        monkeypatch.setenv(spa.SPA_DIST_ENV, str(tmp_path / "absent"))
        assert wb_main.main(argv=["--port", "0"]) == 2
        err = capsys.readouterr().err
        assert "no compiled build" in err
        assert "npm run build" in err
        # Rollback is offered, but it is never taken automatically.
        assert f"{spa.FRONTEND_MODE_ENV}=legacy" in err

    def test_editor_routes_answer_503_never_legacy_html(self, monkeypatch, build, tmp_path):
        """The D1 mechanism, unchanged: a loud plain-text 503 per editor route."""
        monkeypatch.setenv(spa.SPA_DIST_ENV, str(tmp_path / "absent"))
        server, thread, base = _server()
        try:
            for path in ["/", "/stories", "/articles/art_1", "/settings"]:
                status, body, headers = _get(base, path)
                assert status == 503, (path, status)
                assert headers["Content-Type"] == "text/plain; charset=utf-8", path
                assert b"<!doctype html>" not in body.lower(), path
                assert b'<div id="root">' not in body, path
                text = body.decode("utf-8")
                assert "npm run build" in text, path
                assert f"{spa.FRONTEND_MODE_ENV}=legacy" in text, path
        finally:
            _stop(server, thread)

    def test_the_backend_still_answers_while_the_build_is_missing(self, monkeypatch, tmp_path):
        """A broken frontend build must not take the API or health down with it."""
        monkeypatch.setenv(spa.SPA_DIST_ENV, str(tmp_path / "absent"))
        server, thread, base = _server()
        try:
            status, body, _ = _get(base, "/api/v1/today")
            assert status == 200, status
            status, body, _ = _get(base, "/healthz")
            assert status == 200 and body == b"OK\n"
        finally:
            _stop(server, thread)


# --------------------------------------------------------------------------
# §7 — invalid configuration
# --------------------------------------------------------------------------


class TestInvalidConfigurationIsLoud:
    @pytest.mark.parametrize("raw", ["spaa", "nonsense", "react", "1", "true"])
    def test_serve_refuses_to_start_on_a_bad_value(self, monkeypatch, raw):
        """A typo is a deployment error, never a silent choice of editor."""
        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, raw)
        with pytest.raises(spa.FrontendConfigError):
            http.serve(0, host="127.0.0.1")

    def test_startup_refuses_to_start_on_a_bad_value(self, monkeypatch, capsys, build):
        from editor_assistant.workflow.workbench import __main__ as wb_main

        monkeypatch.setenv(spa.SPA_DIST_ENV, str(build))
        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, "spaa")
        assert wb_main.main(argv=["--port", "0"]) == 2
        err = capsys.readouterr().err
        assert "not a valid editor frontend" in err
        assert spa.FRONTEND_MODE_ENV in err

    def test_a_running_server_refuses_instead_of_guessing(self, monkeypatch, build):
        """If the value is broken while serving, no route silently changes owner."""
        server, thread, base = _serving(monkeypatch, build, spa.MODE_SPA)
        try:
            status, _, headers = _get(base, "/")
            assert status == 200, status

            monkeypatch.setenv(spa.FRONTEND_MODE_ENV, "spaa")
            status, body, headers = _get(base, "/")
            assert status == 500, status
            assert headers["Content-Type"] == "text/plain; charset=utf-8"
            assert b"<!doctype html>" not in body.lower()
            assert b'<div id="root">' not in body
            assert b"not a valid editor frontend" in body
        finally:
            _stop(server, thread)

    def test_the_contract_is_exactly_two_values(self):
        """§7 decision, stated so a future change is a deliberate edit."""
        assert set(spa.VALID_MODES) == {"spa", "legacy"}
        assert spa.DEFAULT_MODE == spa.MODE_SPA
