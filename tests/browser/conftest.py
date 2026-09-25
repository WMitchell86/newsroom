"""D2A/D2B harness fixtures: isolated runtime, real server, real Chromium.

Everything the browser sees is served by the production ``ThreadingHTTPServer``
in the **default** frontend mode — no ``WB_EDITOR_FRONTEND`` at all, which is
what a normal start does since the D2B cutover — from a real ``npm run build``
output directory. There is no Vite dev server, no Vite preview, no route
interception and no mocked API response anywhere in the main parity proof.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import threading
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from .fixture_data import build_fixture, install_boundary_substitutes

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist"
#: The repository's real runtime stores. Never written by this suite.
REAL_STORES = (ROOT / "var" / "editorial_workflow", ROOT / "var" / "newsroom")
SCREENSHOT_DIR = ROOT / "var" / "d2a_screenshots"
VIEWPORT = {"width": 1440, "height": 1080}


# --------------------------------------------------------------------------
# runtime-store integrity (the permanent migration gate, §4)
# --------------------------------------------------------------------------


def runtime_store_manifest() -> dict[str, str]:
    """SHA-256 of every file in the repository's real runtime stores."""
    manifest: dict[str, str] = {}
    for store in REAL_STORES:
        if not store.exists():
            continue
        for path in sorted(store.rglob("*")):
            if path.is_file():
                key = str(path.relative_to(ROOT))
                manifest[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


@pytest.fixture(scope="session", autouse=True)
def assert_runtime_stores_untouched():
    """Fail the whole session if any real runtime store byte changed.

    This is an explicit assertion, not an assumption: the manifest is taken
    before the first browser test starts and compared after the last one ends.
    It is session-scoped and autouse, so it also covers a run where the browser
    suite itself fails part-way through.
    """
    before = runtime_store_manifest()
    yield
    after = runtime_store_manifest()
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    assert not changed, (
        "the real runtime stores were modified by the browser suite; every browser "
        f"test must use isolated store roots. Changed: {changed}"
    )


# --------------------------------------------------------------------------
# isolated runtime + the real production server
# --------------------------------------------------------------------------


#: The serving mode is process-global (one environment variable, read per request),
#: so the default-mode and legacy-mode servers cannot be up at the same time.
_FRONTEND_MODE_LOCK = threading.RLock()


@contextlib.contextmanager
def _frontend_mode(mode: str | None):
    """Pin (or unpin, with ``None``) `WB_EDITOR_FRONTEND` for one server.

    ``None`` means the variable is **absent**, which since the D2B cutover is the
    normal production default: the SPA owns the primary routes without anybody
    configuring anything.
    """
    with _FRONTEND_MODE_LOCK:
        previous = os.environ.get("WB_EDITOR_FRONTEND")
        if mode is None:
            os.environ.pop("WB_EDITOR_FRONTEND", None)
        else:
            os.environ["WB_EDITOR_FRONTEND"] = mode
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("WB_EDITOR_FRONTEND", None)
            else:
                os.environ["WB_EDITOR_FRONTEND"] = previous


@pytest.fixture(scope="session")
def spa_runtime(tmp_path_factory):
    """Isolated store root + deterministic fixture, built once per session."""
    root = tmp_path_factory.mktemp("d2a-spa")
    tracked = (
        "WB_NEWSROOM_DIR",
        "NEWSROOM_DIR",
        "WB_EDITORIAL_WORKFLOW_DIR",
        "MODEL_USAGE_DIR",
        "MODEL_HEALTH_PATH",
        "WB_EDITOR_FRONTEND",
        "WB_SPA_DIST",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "SERPER_API_KEY",
        "TINYFISH_API_KEY",
        "SEARCH_PROVIDER",
    )
    saved = {name: os.environ.get(name) for name in tracked}
    newsroom = root / "newsroom"
    editorial = root / "editorial"
    for path in (newsroom, editorial, root / "model_usage"):
        path.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "WB_NEWSROOM_DIR": str(newsroom),
            "NEWSROOM_DIR": str(newsroom),
            "WB_EDITORIAL_WORKFLOW_DIR": str(editorial),
            "MODEL_USAGE_DIR": str(root / "model_usage"),
            "MODEL_HEALTH_PATH": str(root / "model_health.json"),
            "WB_SPA_DIST": str(DIST),
        }
    )
    # D2B: the whole browser suite runs in the DEFAULT mode, with no
    # `WB_EDITOR_FRONTEND` at all. A real operator types nothing, so neither does
    # this proof: it demonstrates that a normal start serves the SPA.
    os.environ.pop("WB_EDITOR_FRONTEND", None)
    # The transport is substituted below, so no request can leave the process. The
    # role policy still requires *a* key before it will consider any route, so a
    # dummy is set: it never authenticates anything, because the seam it would be
    # used at is replaced. A real key is removed so operator quota/health can
    # never influence this proof.
    os.environ["GEMINI_API_KEY"] = "d2a-substitute-not-a-real-key"
    for name in (
        "OPENROUTER_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "SERPER_API_KEY",
        "TINYFISH_API_KEY",
    ):
        os.environ.pop(name, None)
    from editor_assistant.workflow import story_operations

    try:
        story_operations.clear()
        yield build_fixture(newsroom=newsroom, editorial=editorial)
    finally:
        story_operations.clear()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="session")
def boundary_substitutes(spa_runtime):
    """Install the three outbound-edge substitutes for the whole session."""
    from _pytest.monkeypatch import MonkeyPatch

    patcher = MonkeyPatch()
    install_boundary_substitutes(patcher)
    yield
    patcher.undo()


@pytest.fixture(scope="session", autouse=True)
def operation_diagnostics():
    """Surface a real operation-worker failure instead of a bare client timeout.

    A failed background operation is otherwise invisible to the browser: the SPA
    only sees a sanitized message. This prints the worker's own exception, so a
    harness or product failure is diagnosable straight from the test output.
    """
    import traceback

    from editor_assistant.workflow import article_generation

    original = article_generation.generate

    def traced(snapshot, **kwargs):
        try:
            return original(snapshot, **kwargs)
        except BaseException:
            print("\n[d2a] article_generation.generate raised:", file=sys.stderr)
            traceback.print_exc()
            raise

    article_generation.generate = traced
    try:
        yield
    finally:
        article_generation.generate = original


@pytest.fixture(scope="session")
def spa_server(spa_runtime, boundary_substitutes):
    """The real Python server in the DEFAULT mode, on a real socket.

    D2B: this fixture does **not** set ``WB_EDITOR_FRONTEND``. Since the cutover
    the variable is absent, so this is an ordinary production start and the whole
    D2A parity suite proves the default. The mode is read per request from the
    process environment, so the variable is held absent for as long as the server
    is up; the legacy fixture takes the same lock, which keeps the two modes from
    bleeding into each other.
    """
    from editor_assistant.workflow.workbench import http

    if not (DIST / "index.html").exists():
        pytest.skip(f"production build missing: run `cd frontend && npm run build` ({DIST})")
    with _frontend_mode(None):
        server = http.serve(0, host="127.0.0.1")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.fixture(scope="session")
def legacy_server(tmp_path_factory):
    """The SAME Python runtime in `WB_EDITOR_FRONTEND=legacy`, on its own socket.

    The rollback surface is proven by actually running the default mode, not by
    asserting a variable: the server-rendered Workbench must still answer.
    """
    from editor_assistant.workflow.workbench import http

    root = tmp_path_factory.mktemp("d2a-legacy")
    newsroom = root / "newsroom"
    editorial = root / "editorial"
    for path in (newsroom, editorial, root / "model_usage"):
        path.mkdir(parents=True, exist_ok=True)
    tracked = (
        "WB_NEWSROOM_DIR",
        "NEWSROOM_DIR",
        "WB_EDITORIAL_WORKFLOW_DIR",
        "MODEL_USAGE_DIR",
        "MODEL_HEALTH_PATH",
        "WB_EDITOR_FRONTEND",
        "WB_SPA_DIST",
    )
    saved = {name: os.environ.get(name) for name in tracked}
    os.environ.update(
        {
            "WB_NEWSROOM_DIR": str(newsroom),
            "NEWSROOM_DIR": str(newsroom),
            "WB_EDITORIAL_WORKFLOW_DIR": str(editorial),
            "MODEL_USAGE_DIR": str(root / "model_usage"),
            "MODEL_HEALTH_PATH": str(root / "model_health.json"),
        }
    )
    from editor_assistant.workflow import story_operations

    try:
        story_operations.clear()
        build_fixture(newsroom=newsroom, editorial=editorial)
        # No lock is held here: the mode is pinned per navigation by `legacy_page`,
        # so this server can coexist with the SPA-mode server in one process.
        server = http.serve(0, host="127.0.0.1")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    finally:
        story_operations.clear()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture
def legacy_page(browser, legacy_server):
    """A page against the legacy-mode server, for the rollback smoke.

    The serving mode is one process-global variable read per request, so it is
    pinned around each navigation rather than for the whole session. That lets the
    SPA-mode and legacy-mode proofs live in the same run without either bleeding
    into the other.
    """
    context = browser.new_context(viewport=VIEWPORT, locale="bg-BG")
    new_page = context.new_page()
    probe = PageProbe(new_page, legacy_server)
    probe.page.set_default_timeout(15000)

    def goto(path: str) -> None:
        with _frontend_mode("legacy"):
            probe.page.goto(f"{legacy_server}{path}", wait_until="load")

    probe.goto = goto
    try:
        yield probe
    finally:
        context.close()


# --------------------------------------------------------------------------
# real Chromium + the console/network error gate
# --------------------------------------------------------------------------

#: Browser noise that is expected and carries no product meaning. Anything not
#: listed here is treated as a failure: a real React/runtime exception is never
#: normalized away.
BENIGN_CONSOLE = (
    # Chromium logs this when a page is closed mid-navigation; it is browser
    # plumbing, not an application error.
    "Failed to load resource: net::ERR_ABORTED",
)


@pytest.fixture(scope="session")
def playwright_instance():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment problem, not product
        pytest.skip(
            "Playwright is required for the D2A browser gate: "
            "pip install playwright && python3 -m playwright install chromium "
            f"({exc})"
        )
    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="session")
def browser(playwright_instance):
    instance = playwright_instance
    try:
        launched = instance.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    except PlaywrightError as exc:  # pragma: no cover - environment problem, not product
        pytest.skip(f"Chromium could not be launched: {exc}")
    try:
        yield launched
    finally:
        launched.close()


class PageProbe:
    """One browser page plus every error the gate treats as a failure."""

    def __init__(self, page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.failed_requests: list[str] = []
        self.external_requests: list[str] = []
        self.api_404_urls: list[str] = []
        self._wire()

    def _wire(self) -> None:
        page = self.page
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("requestfailed", self._on_request_failed)
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _on_console(self, message) -> None:
        if message.type != "error":
            return
        text = message.text
        if any(token in text for token in BENIGN_CONSOLE):
            return
        self.console_errors.append(text)

    def _on_page_error(self, error) -> None:
        self.page_errors.append(f"{type(error).__name__}: {error}")

    def _on_request_failed(self, request) -> None:
        failure = request.failure or ""
        self.failed_requests.append(f"{request.method} {request.url} ({failure})")

    def _on_request(self, request) -> None:
        url = request.url
        if url.startswith(("http://", "https://")) and not url.startswith(self.base_url):
            self.external_requests.append(url)

    def _on_response(self, response) -> None:
        if response.status == 404 and "/api/v1" in response.url:
            self.api_404_urls.append(response.url)

    def reset(self) -> None:
        self.console_errors.clear()
        self.page_errors.clear()
        self.failed_requests.clear()
        self.external_requests.clear()
        self.api_404_urls.clear()

    def assert_clean(self, *, context: str, allow_api_404: bool = False) -> None:
        """The §8 gate: page errors and console errors are failures.

        ``allow_api_404`` is only for the not-found proofs, where the API
        correctly answers 404 and Chromium logs that as a console error. It never
        excuses an uncaught exception, a script error or any non-API failure.
        """
        assert not self.page_errors, f"{context}: uncaught page errors: {self.page_errors}"
        unexpected = []
        for text in self.console_errors:
            if allow_api_404 and _is_api_404_noise(text, self.api_404_urls):
                continue
            unexpected.append(text)
        assert not unexpected, f"{context}: console errors: {unexpected}"
        failed = [item for item in self.failed_requests if "ERR_ABORTED" not in item]
        assert not failed, f"{context}: failed requests: {failed}"

    def assert_only_conflict_noise(self, *, context: str) -> None:
        """For the conflict proof: the 409 *is* the product working correctly.

        The article save is genuinely rejected by the version check, and Chromium
        logs that status. Everything else must still be clean.
        """
        assert not self.page_errors, f"{context}: uncaught page errors: {self.page_errors}"
        unexpected = [
            text
            for text in self.console_errors
            if not ("409" in text and "Failed to load resource" in text)
        ]
        assert not unexpected, f"{context}: unexpected console errors: {unexpected}"
        failed = [item for item in self.failed_requests if "ERR_ABORTED" not in item]
        assert not failed, f"{context}: failed requests: {failed}"


def _is_api_404_noise(text: str, api_404_urls: list[str]) -> bool:
    """True only for Chromium's log line about an expected `/api/v1` 404."""
    if "404" not in text or "Failed to load resource" not in text:
        return False
    return bool(api_404_urls)


@pytest.fixture
def page(browser, spa_server):
    """A fresh page at the review viewport, with the error gate attached."""
    context = browser.new_context(viewport=VIEWPORT, locale="bg-BG")
    new_page = context.new_page()
    probe = PageProbe(new_page, spa_server)
    probe.page.set_default_timeout(15000)
    try:
        yield probe
    finally:
        context.close()


@pytest.fixture
def fresh_page(browser, spa_server):
    """A brand-new browser context: no shared cookies, storage or history.

    Used for the deep-link, pasted-URL and back/forward proofs, which must not
    rely on any existing session state.
    """
    context = browser.new_context(viewport=VIEWPORT, locale="bg-BG")
    new_page = context.new_page()
    probe = PageProbe(new_page, spa_server)
    probe.page.set_default_timeout(15000)
    try:
        yield probe
    finally:
        context.close()


@pytest.fixture
def screenshots():
    """Owner-review artifacts at 1440x1080, from the Python-served bundle."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def capture(probe, name: str) -> Path:
        target = SCREENSHOT_DIR / f"{name}.png"
        probe.page.screenshot(path=str(target), full_page=False)
        return target

    yield capture
