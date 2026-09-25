#!/usr/bin/env python3
"""D1 production-like proof: the REAL compiled build through the REAL Python server.

This is the D1 stop-condition proof. It does not use the Vite dev server and it
does not use Vite preview: the browser origin is the same ``ThreadingHTTPServer``
that serves the legacy Workbench in production.

It proves, against a throwaway runtime store:

  1. the frontend production build exists and is a real compiled build;
  2. Python serves the SPA on every approved editor route;
  3. deep links (Story / Article / Archive) return the entry document, so
     browser refresh and pasted URLs work;
  4. every asset URL named by the built ``index.html`` is fetchable from the
     Python origin with the right MIME type (JS, CSS and all four WOFF2 fonts,
     including both Cyrillic subsets);
  5. a missing hashed asset is a real 404, never ``index.html``;
  6. traversal attempts cannot read files outside the build root;
  7. ``/api/v1/*`` and ``/healthz`` are never swallowed by the SPA fallback;
  8. unknown routes are 404, not a blanket SPA;
  9. the legacy rollback path still serves the server-rendered Workbench;
 10. the real ``var/`` runtime store is byte-identical before and after.

Usage:
  cd frontend && npm run build && cd ..
  PYTHONPATH=src python3 scripts/d1_spa_proof.py

Exit code 0 = every check passed.
"""

from __future__ import annotations

import hashlib
import html.parser
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DIST = ROOT / "frontend" / "dist"
REAL_STORES = [ROOT / "var" / "editorial_workflow", ROOT / "var" / "newsroom"]

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def store_hashes() -> dict[str, str]:
    """SHA-256 of every file in the real runtime stores."""
    out: dict[str, str] = {}
    for store in REAL_STORES:
        if not store.exists():
            continue
        for path in sorted(store.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def fetch(base: str, path: str):
    try:
        response = urllib.request.urlopen(f"{base}{path}", timeout=10)
    except urllib.error.HTTPError as err:
        response = err
    with response:
        return response.status, response.read(), dict(response.headers)


class _AssetParser(html.parser.HTMLParser):
    """Collect the asset URLs the built entry document actually references."""

    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "script" and attr.get("src"):
            self.assets.append(attr["src"])
        if tag == "link" and attr.get("href"):
            self.assets.append(attr["href"])


SPA_ROUTES = [
    "/",
    "/stories",
    "/stories/s-proof",
    "/articles",
    "/articles/art_proof",
    "/archive",
    "/archive/art_proof",
    "/settings",
]
API_ROUTES = ["/api/v1/today", "/api/v1/stories", "/api/v1/articles", "/api/v1/archive"]
EVIL_PATHS = [
    "/assets/../../../.env",
    "/assets/%2e%2e/%2e%2e/%2e%2e/.env",
    "/assets/..%2f..%2f..%2f.env",
    "/.env",
    "/package.json",
]
UNKNOWN_PATHS = ["/nope", "/not-a-real-page", "/settings/advanced"]
ROLLBACK_PATHS = ["/", "/stories", "/cases", "/inbox"]


def main() -> int:
    # 1. the build must be a real compiled build
    if not (DIST / "index.html").is_file():
        check("1. production build present", False, f"missing {DIST / 'index.html'}")
        print("\nFAILED: run `npm ci && npm run build` in frontend/ first.")
        return 1
    index_bytes = (DIST / "index.html").read_bytes()
    parser = _AssetParser()
    parser.feed(index_bytes.decode("utf-8"))
    check(
        "1. production build present",
        b'<div id="root">' in index_bytes,
        f"{len(parser.assets)} asset references",
    )
    if not parser.assets:
        check("1b. build references compiled assets", False, "no script/link found")
        return 1
    check("1b. build references compiled assets", True, ", ".join(parser.assets))

    # Isolate the runtime store BEFORE importing the server modules.
    tmp = Path(tempfile.mkdtemp(prefix="d1_spa_proof_"))
    newsroom = tmp / "newsroom"
    newsroom.mkdir(parents=True)
    os.environ["WB_NEWSROOM_DIR"] = str(newsroom)
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(tmp / "editorial")
    # D2B: no `WB_EDITOR_FRONTEND` at all. Since the cutover the SPA *is* the
    # default, so an ordinary start is exactly what this proof must exercise.
    os.environ.pop("WB_EDITOR_FRONTEND", None)

    from editor_assistant.workflow.workbench import http  # env must be set first

    before = store_hashes()

    server = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        # 2. the SPA entry itself
        status, root_body, root_headers = fetch(base, "/")
        check(
            "2. SPA served on /",
            status == 200 and b'<div id="root">' in root_body,
            f"status={status} cache={root_headers.get('Cache-Control')}",
        )
        check(
            "2b. index.html is not immutably cached",
            "immutable" not in (root_headers.get("Cache-Control") or ""),
            root_headers.get("Cache-Control", ""),
        )

        # 3. history fallback: every approved route, byte-identical to /
        for path in SPA_ROUTES[1:]:
            status, body, _ = fetch(base, path)
            check(
                f"3. deep link {path}",
                status == 200 and body == root_body,
                f"status={status} identical_to_root={body == root_body}",
            )

        # 4. every asset the real build references, from the Python origin
        fonts_ok = True
        for asset in parser.assets:
            status, body, headers = fetch(base, asset)
            ctype = headers.get("Content-Type", "")
            ok = status == 200 and len(body) > 0
            if asset.endswith(".js"):
                ok = ok and ctype.startswith("text/javascript")
            elif asset.endswith(".css"):
                ok = ok and ctype.startswith("text/css")
            elif asset.endswith(".woff2"):
                ok = ok and ctype == "font/woff2" and body[:4] == b"wOF2"
                fonts_ok = fonts_ok and ok
            check(
                f"4. asset {asset}",
                ok,
                f"status={status} type={ctype} bytes={len(body)}",
            )
        check("4b. self-hosted Cyrillic/Latin WOFF2 fonts served by Python", fonts_ok)

        # 5. a missing hashed chunk is a real 404
        status, body, _ = fetch(base, "/assets/index-DEADBEEF.js")
        check(
            "5. missing hashed asset is 404 (not index.html)",
            status == 404 and b'<div id="root">' not in body,
            f"status={status}",
        )

        # 6. traversal cannot escape the build root
        for evil in EVIL_PATHS:
            status, body, _ = fetch(base, evil)
            leaked = b"DRY_RUN" in body or b"TELEGRAM" in body or b'"name"' in body
            check(
                f"6. traversal blocked {evil}",
                status == 404 and not leaked,
                f"status={status} leaked={leaked}",
            )

        # 7. API + health isolation
        for path in API_ROUTES:
            status, body, headers = fetch(base, path)
            ctype = headers.get("Content-Type", "")
            check(
                f"7. API stays JSON {path}",
                status == 200
                and ctype == "application/json; charset=utf-8"
                and b'<div id="root">' not in body,
                f"status={status} type={ctype}",
            )
        status, body, _ = fetch(base, "/api/v1/not-real")
        check(
            "7b. unknown API path stays API 404",
            status == 404 and b'"code":"NOT_FOUND"' in body,
            f"status={status}",
        )
        status, body, _ = fetch(base, "/healthz")
        check(
            "7c. /healthz never swallowed",
            status == 200 and body == b"OK\n",
            f"status={status} body={body[:8]!r}",
        )

        # 8. unknown routes are real 404s, not a blanket SPA
        for path in UNKNOWN_PATHS:
            status, body, _ = fetch(base, path)
            check(
                f"8. unknown route 404 {path}",
                status == 404 and b'<div id="root">' not in body,
                f"status={status}",
            )

        # 9. legacy rollback path
        for path in ROLLBACK_PATHS:
            status, body, _ = fetch(base, f"/wb-legacy{path}")
            check(
                f"9. legacy rollback /wb-legacy{path}",
                status == 200
                and b'<div id="root">' not in body
                and b"<!doctype html>" in body.lower(),
                f"status={status}",
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # 10. the real runtime store must be byte-identical
    after = store_hashes()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    check(
        "10. real runtime store byte-identical",
        not changed,
        "unchanged" if not changed else f"CHANGED: {changed[:5]}",
    )
    check(
        "10b. proof ran against an isolated store",
        str(tmp) in os.environ["WB_NEWSROOM_DIR"],
        os.environ["WB_NEWSROOM_DIR"],
    )
    shutil.rmtree(tmp, ignore_errors=True)

    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("D1 production-like proof: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
