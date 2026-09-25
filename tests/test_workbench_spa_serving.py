"""D1: production SPA serving + safe routing (opt-in deployment mode).

Verifies that the existing Python `ThreadingHTTPServer` can serve the compiled
React build on the approved editor routes while every backend surface keeps
its precedence, and that `legacy` mode (the default) is byte-for-byte the
pre-D1 behavior.

Runtime stores are isolated through the standard env overrides, so the real
`var/` store is never touched by any test in this module.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from editor_assistant.workflow.workbench import http, spa

_OPENER = urllib.request.build_opener()


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
    """Isolated runtime stores for every test in this module."""
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
    (root / "assets" / "noto-sans-cyrillic-B2hlT84T.woff2").write_bytes(b"wOF2\x00\x01\x02binary")
    return root


def _server():
    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def legacy_server():
    server, thread, base = _server()
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def spa_server(monkeypatch, build):
    monkeypatch.setenv(spa.SPA_DIST_ENV, str(build))
    monkeypatch.setenv(spa.FRONTEND_MODE_ENV, spa.MODE_SPA)
    server, thread, base = _server()
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# §6/§7 — the deployment flag
# --------------------------------------------------------------------------


class TestFrontendFlag:
    def test_default_is_legacy(self, monkeypatch):
        monkeypatch.delenv(spa.FRONTEND_MODE_ENV, raising=False)
        assert spa.frontend_mode() == spa.MODE_LEGACY
        assert spa.is_spa_enabled() is False

    @pytest.mark.parametrize("raw", ["", "legacy", "LEGACY", "nonsense", "react", "v2"])
    def test_unknown_values_fail_closed_to_legacy(self, monkeypatch, raw):
        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, raw)
        assert spa.frontend_mode() != spa.MODE_SPA

    @pytest.mark.parametrize("raw", ["spa", "SPA", " spa "])
    def test_spa_is_opt_in_only(self, monkeypatch, raw):
        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, raw)
        assert spa.frontend_mode() == spa.MODE_SPA


# --------------------------------------------------------------------------
# §26 — legacy mode must be unchanged
# --------------------------------------------------------------------------


class TestLegacyModeUnchanged:
    def test_legacy_serves_server_rendered_pages(self, legacy_server):
        for path in ["/", "/stories", "/articles", "/settings", "/cases", "/inbox"]:
            status, body, _ = _get(legacy_server, path)
            assert status == 200, (path, status)
            assert b'<div id="root">' not in body, path
            assert b"<!doctype html>" in body.lower(), path

    def test_legacy_never_serves_spa_assets_or_entry(self, legacy_server, build):
        """Compiled output is invisible in legacy mode, even when it exists."""
        for path in ["/", "/stories", "/settings"]:
            _, body, _ = _get(legacy_server, path)
            assert b"index-CCWo5GjE.js" not in body, path
        status, body, headers = _get(legacy_server, "/assets/index-CCWo5GjE.js")
        assert status == 404
        assert b'<div id="root">' not in body
        assert headers["Content-Type"] == "text/html; charset=utf-8"

    def test_legacy_mode_ignores_the_compat_prefix(self, legacy_server):
        """In legacy mode the compat path is just an unknown 404."""
        status, body, _ = _get(legacy_server, "/wb-legacy/stories")
        assert status == 404
        assert b'<div id="root">' not in body

    def test_api_and_health_work_in_legacy_mode(self, legacy_server):
        status, body, _ = _get(legacy_server, "/api/v1/stories")
        assert status == 200
        assert b'"data"' in body
        assert _get(legacy_server, "/healthz")[0] == 200


# --------------------------------------------------------------------------
# §11/§27 — rollback and preserved operator surfaces (SPA mode)
# --------------------------------------------------------------------------


class TestRollbackAndOperatorAccess:
    def test_legacy_pages_remain_reachable_via_compat_prefix(self, spa_server):
        for path in ["/", "/stories", "/articles", "/settings", "/cases", "/inbox"]:
            status, body, _ = _get(spa_server, f"/wb-legacy{path}")
            assert status == 200, (path, status)
            assert b'<div id="root">' not in body, path
            assert b"<!doctype html>" in body.lower(), path

    def test_compat_root_maps_to_legacy_home(self, spa_server):
        status, body, _ = _get(spa_server, "/wb-legacy/")
        assert status == 200
        assert b'<div id="root">' not in body

    def test_operator_surfaces_keep_their_own_paths(self, spa_server):
        """§27: cases/inbox/sources/models/intake are not SPA routes."""
        for path in ["/cases", "/inbox", "/sources", "/models", "/intake"]:
            status, body, _ = _get(spa_server, path)
            assert status == 200, (path, status)
            assert b'<div id="root">' not in body, path

    def test_legacy_stylesheet_still_served(self, spa_server):
        status, body, headers = _get(spa_server, "/static/style.css")
        assert status == 200
        assert headers["Content-Type"] == "text/css; charset=utf-8"
        assert len(body) > 0


# --------------------------------------------------------------------------
# §18 — missing build fails loudly
# --------------------------------------------------------------------------


class TestMissingBuild:
    def test_startup_refuses_spa_mode_without_a_build(self, monkeypatch, tmp_path, capsys):
        from editor_assistant.workflow.workbench import __main__ as wb_main

        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, spa.MODE_SPA)
        monkeypatch.setenv(spa.SPA_DIST_ENV, str(tmp_path / "absent"))
        assert wb_main.main(argv=["--port", "0"]) == 2
        assert "no compiled build" in capsys.readouterr().err

    def test_spa_routes_return_503_not_legacy_html(self, monkeypatch, tmp_path):
        monkeypatch.setenv(spa.FRONTEND_MODE_ENV, spa.MODE_SPA)
        monkeypatch.setenv(spa.SPA_DIST_ENV, str(tmp_path / "absent"))
        server, thread, base = _server()
        try:
            for path in ["/", "/stories", "/articles/art_1", "/settings"]:
                status, body, headers = _get(base, path)
                assert status == 503, (path, status)
                # An explicit diagnostic — never a legacy page pretending to work.
                assert headers["Content-Type"] == "text/plain; charset=utf-8", path
                assert b"<!doctype html>" not in body.lower(), path
                text = body.decode("utf-8")
                assert "npm run build" in text, path
                assert spa.FRONTEND_MODE_ENV in text, path
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_require_build_raises_with_actionable_message(self, monkeypatch, tmp_path):
        monkeypatch.setenv(spa.SPA_DIST_ENV, str(tmp_path / "absent"))
        with pytest.raises(spa.SpaBuildMissing) as excinfo:
            spa.require_build()
        assert "npm run build" in str(excinfo.value)


# --------------------------------------------------------------------------
# §20 — development workflow is untouched
# --------------------------------------------------------------------------


class TestDevWorkflowUnaffected:
    def test_vite_proxy_config_is_unchanged(self):
        """The dev server keeps proxying /api to the Python origin."""
        config = (spa.ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        assert '"/api"' in config
        assert "http://127.0.0.1:8123" in config
        assert "port: 5173" in config

    def test_spa_client_uses_same_origin_relative_api(self):
        """§13: production must not need a second API base URL or CORS."""
        client = (spa.ROOT / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
        assert "`/api/v1${path}`" in client
        assert "http://" not in client


# --------------------------------------------------------------------------
# §4/§16/§24 — compiled asset serving
# --------------------------------------------------------------------------


class TestAssetServing:
    def test_hashed_js_css_and_woff2_are_served_with_correct_mime(self, spa_server):
        cases = [
            ("/assets/index-CCWo5GjE.js", "text/javascript; charset=utf-8", b"console.log"),
            ("/assets/index-CXmK9Rrr.css", "text/css; charset=utf-8", b"body{"),
            (
                "/assets/noto-sans-cyrillic-B2hlT84T.woff2",
                "font/woff2",
                b"wOF2",
            ),
        ]
        for path, expected_type, marker in cases:
            status, body, headers = _get(spa_server, path)
            assert status == 200, (path, status)
            assert headers["Content-Type"] == expected_type, path
            assert marker in body, path

    def test_woff2_is_binary_safe(self, spa_server):
        """NUL bytes and invalid UTF-8 must survive the round trip."""
        _, body, headers = _get(spa_server, "/assets/noto-sans-cyrillic-B2hlT84T.woff2")
        assert body == b"wOF2\x00\x01\x02binary"
        assert headers["Content-Length"] == str(len(body))

    def test_hashed_assets_are_immutably_cached(self, spa_server):
        """§16: Vite's content hash changes whenever the bytes do."""
        for path in ["/assets/index-CCWo5GjE.js", "/assets/index-CXmK9Rrr.css"]:
            _, _, headers = _get(spa_server, path)
            assert headers["Cache-Control"] == "public, max-age=31536000, immutable", path

    def test_missing_hashed_asset_is_404_not_index(self, spa_server):
        """§4/§24: a broken chunk must not be masked as a working SPA."""
        status, body, _ = _get(spa_server, "/assets/index-DOESNOTEXIST.js")
        assert status == 404
        assert b'<div id="root">' not in body

    def test_root_static_file_is_served(self, spa_server, build):
        (build / "favicon.svg").write_text("<svg/>", encoding="utf-8")
        status, body, headers = _get(spa_server, "/favicon.svg")
        assert status == 200
        assert headers["Content-Type"] == "image/svg+xml"
        assert b"<svg/>" in body

    def test_no_directory_listing(self, spa_server):
        status, body, _ = _get(spa_server, "/assets/")
        assert status == 404
        assert b"index-CCWo5GjE.js" not in body


# --------------------------------------------------------------------------
# §17 — traversal and containment
# --------------------------------------------------------------------------


class TestStaticSecurity:
    @pytest.mark.parametrize(
        "path",
        [
            "/assets/../../.env",
            "/assets/../../../etc/passwd",
            "/assets/%2e%2e/%2e%2e/.env",
            "/assets/..%2f..%2f.env",
            "/assets/%2e%2e%2f%2e%2e%2f.env",
            "/assets/....//....//.env",
            "/../.env",
            "/assets/..%5c..%5c.env",
        ],
    )
    def test_traversal_attempts_never_escape_the_build_root(self, spa_server, path):
        status, body, _ = _get(spa_server, path)
        assert status == 404, (path, status)
        # No repository or environment content leaked into the response.
        assert b"EDITOR" not in body and b"root:x:" not in body, path

    def test_symlink_out_of_build_root_is_refused(self, spa_server, build, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("TOPSECRET", encoding="utf-8")
        link = build / "assets" / "escape.txt"
        link.symlink_to(secret)
        status, body, _ = _get(spa_server, "/assets/escape.txt")
        assert status == 404
        assert b"TOPSECRET" not in body

    def test_repository_files_are_not_reachable(self, spa_server, build):
        """Only the build root is served — not the repository above it."""
        for path in ["/.env", "/package.json", "/src/editor_assistant/config.py"]:
            status, body, _ = _get(spa_server, path)
            assert status == 404, (path, status)
            assert b"DRY_RUN" not in body, path

    def test_nul_byte_path_is_rejected(self, spa_server):
        assert spa.owns_static_path("/assets/index.js") is True
        assert spa.resolve_asset("/assets/%00index.js") is None


# --------------------------------------------------------------------------
# §10/§23 — API and health isolation (must never be swallowed)
# --------------------------------------------------------------------------


class TestApiIsolation:
    @pytest.mark.parametrize(
        "path",
        ["/api/v1/today", "/api/v1/stories", "/api/v1/articles", "/api/v1/archive"],
    )
    def test_api_endpoints_stay_json(self, spa_server, path):
        status, body, headers = _get(spa_server, path)
        assert status == 200, (path, status)
        assert headers["Content-Type"] == "application/json; charset=utf-8", path
        assert b'"data"' in body, path
        assert b'<div id="root">' not in body, path

    @pytest.mark.parametrize("path", ["/api/v1/not-real", "/api/v1", "/api/nope"])
    def test_unknown_api_path_stays_api_404(self, spa_server, path):
        """§23: no SPA fallback for unknown API paths."""
        status, body, headers = _get(spa_server, path)
        assert status == 404, (path, status)
        assert headers["Content-Type"] == "application/json; charset=utf-8", path
        assert json.loads(body)["error"]["code"] == "NOT_FOUND", path
        assert b'<div id="root">' not in body, path

    def test_healthz_is_never_swallowed(self, spa_server):
        status, body, headers = _get(spa_server, "/healthz")
        assert status == 200
        assert body == b"OK\n"
        assert headers["Content-Type"] == "text/plain; charset=utf-8"

    def test_api_responses_keep_no_store(self, spa_server):
        """§16: no static cache headers may leak onto dynamic API responses."""
        _, _, headers = _get(spa_server, "/api/v1/today")
        assert headers["Cache-Control"] == "no-store"


# --------------------------------------------------------------------------
# §8/§22 — approved SPA routes and history fallback
# --------------------------------------------------------------------------

SPA_ROUTES = [
    "/",
    "/stories",
    "/stories/s-one",
    "/articles",
    "/articles/art_1",
    "/archive",
    "/archive/art_1",
    "/settings",
]


class TestSpaRouteOwnership:
    def test_route_matcher_owns_exactly_the_approved_routes(self):
        for path in SPA_ROUTES:
            assert spa.owns_spa_route(path) is True, path

    @pytest.mark.parametrize(
        "path",
        [
            "/cases",
            "/case/LIV-01",
            "/inbox",
            "/sources",
            "/models",
            "/intake",
            "/healthz",
            "/static/style.css",
            "/api/v1/today",
            "/assets/index-CCWo5GjE.js",
            "/index.html",
            "/nope",
            "/stories/extra/segment",
            "/settings/advanced",
        ],
    )
    def test_route_matcher_never_leaks(self, path):
        assert spa.owns_spa_route(path) is False, path

    def test_every_approved_route_serves_spa_html(self, spa_server):
        for path in SPA_ROUTES:
            status, body, headers = _get(spa_server, path)
            assert status == 200, (path, status)
            assert b'<div id="root">' in body, path
            assert headers["Content-Type"] == "text/html; charset=utf-8", path

    def test_deep_links_match_root_byte_for_byte(self, spa_server):
        """§14/§32/§34: refresh and paste-URL must work without visiting `/`."""
        _, root_body, _ = _get(spa_server, "/")
        for path in ["/stories/s-one", "/articles/art_1", "/archive/art_1"]:
            _, body, _ = _get(spa_server, path)
            assert body == root_body, path

    def test_index_html_is_never_immutably_cached(self, spa_server):
        """§16: the entry document names the current chunk hashes."""
        for path in SPA_ROUTES:
            _, _, headers = _get(spa_server, path)
            assert headers["Cache-Control"] == spa.INDEX_CACHE, path
            assert "immutable" not in headers["Cache-Control"], path

    def test_unknown_route_is_404_not_spa(self, spa_server):
        """§25: no blanket `200 index.html` for arbitrary URLs."""
        for path in ["/nope", "/not-a-page", "/stories/extra/segment"]:
            status, body, _ = _get(spa_server, path)
            assert status == 404, (path, status)
            assert b'<div id="root">' not in body, path
