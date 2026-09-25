"""Live isolated UI proof for the workbench redesign (real HTTP, temp stores).

Run:  PYTHONPATH=src python3 tmp/ui_proof.py
Exit 0 = every check passed.
"""

from __future__ import annotations

import html.parser
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

TMP = tempfile.mkdtemp(prefix="ui_proof_")
os.environ["WB_NEWSROOM_DIR"] = os.path.join(TMP, "newsroom")
os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = os.path.join(TMP, "editorial_workflow")
# D2B: this proof verifies the server-rendered Workbench's markup, so it requests
# the legacy frontend explicitly. The Workbench is retained for rollback and for
# the operator surfaces; the SPA is the default editor frontend.
os.environ["WB_EDITOR_FRONTEND"] = "legacy"
os.makedirs(os.environ["WB_NEWSROOM_DIR"], exist_ok=True)
os.makedirs(os.environ["WB_EDITORIAL_WORKFLOW_DIR"], exist_ok=True)

from editor_assistant.workflow import inbox_store  # env must be set first
from editor_assistant.workflow.workbench import http, newsroom

RESULTS: list[bool] = []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # pragma: no cover - trivial
        return None


OP = urllib.request.build_opener(_NoRedirect)


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def get(url):
    try:
        return OP.open(url, timeout=10)
    except urllib.error.HTTPError as err:  # type: ignore[attr-defined]
        return err


def post(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        return OP.open(req, timeout=10)
    except urllib.error.HTTPError as err:  # type: ignore[attr-defined]
        return err


VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class Balance(html.parser.HTMLParser):
    """Tag-balance check: unclosed / stray / out-of-order tags are errors."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"close without open <{tag}>")
        elif self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.errors.append(f"unclosed <{self.stack.pop()}>")
            self.stack.pop()
        else:
            self.errors.append(f"stray </{tag}>")


def wellformed(page):
    parser = Balance()
    parser.feed(page)
    parser.close()
    return parser.errors + [
        f"never closed <{t}>" for t in parser.stack if t not in ("html", "body")
    ]


def main() -> int:
    httpd = http.serve(0, host="127.0.0.1")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        run(base)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    failed = RESULTS.count(False)
    print(f"\nUI verification: {len(RESULTS) - failed}/{len(RESULTS)} passed")
    print("ALL CHECKS PASSED" if failed == 0 else f"{failed} CHECKS FAILED")
    return 0 if failed == 0 else 1


def run(base: str) -> None:
    # ---- seed through the real UI (no network) ----
    resp = post(
        f"{base}/sources",
        {
            "action": "add",
            "source_id": "council-feed",
            "name": "Общински съвет Бургас",
            "kind": "official",
            "collector": "rss",
            "url": "https://feed.example/rss",
            "priority": "high",
            "cadence": "each_run",
            "note": "",
        },
    )
    check("seed: source added via POST /sources", resp.code in (302, 303), f"code={resp.code}")

    inbox_store.add_items(
        [
            {
                "source_id": "council-feed",
                "title": "Общинският съвет прие бюджета",
                "url": "https://council.example/budget",
                "published_at": "2026-09-22T08:00:00Z",
                "discovered_at": "2026-09-22T08:05:00Z",
                "source_kind": "official",
                "priority": "high",
                "publisher_domain": "burgas.bg",
                "publisher_kind": "official",
                "factual_authority": True,
                "status": "NEW",
            }
        ],
        path=newsroom.inbox_store_path(),
    )
    resp = post(f"{base}/stories", {"action": "update"})
    check("seed: deterministic story build", resp.code in (302, 303), f"code={resp.code}")

    # ---- every page: 200, well-formed, new shell present ----
    pages = [
        "/",
        "/settings",
        "/stories",
        "/inbox",
        "/articles",
        "/sources",
        "/models",
        "/cases",
        "/intake",
    ]
    shell = [
        'id="nav-toggle"',
        'class="sidenav"',
        '<header class="topbar">',
        'class="nav-burger"',
        'href="/static/style.css"',
    ]
    fetched = {}
    for path in pages:
        resp = get(base + path)
        page = resp.read().decode("utf-8")
        fetched[path] = page
        errs = wellformed(page)
        check(f"{path} -> 200 + well-formed", resp.status == 200 and not errs, "; ".join(errs[:3]))
        missing = [s for s in shell if s not in page]
        check(f"{path} has the collapsible-sidebar shell", not missing, str(missing))

    home = fetched["/"]
    check("home is the daily landing", "Прегледай историите" in home and "Начало" in home)
    check("home has the collect action", 'name="action" value="collect"' in home)
    check("home shows the newest story", "Общинският съвет прие бюджета" in home)
    check("home has the 4-step howto", "Как се работи" in home)
    check(
        "no old pipe nav / version tag",
        'class="top"' not in home and "Редакторски работен плот" not in home,
    )
    check(
        "no dev milestone jargon on the daily page",
        "M3B" not in home and "M3A" not in home and "M4" not in home,
    )

    # advanced surfaces live behind Настройки: links exist in the nav, grouped
    for href in ("/settings", "/sources", "/models", "/cases", "/intake"):
        check(f"nav links {href}", f'href="{href}"' in home)
    for href in ("/", "/stories", "/inbox", "/articles"):
        check(f"daily nav links {href}", f'href="{href}"' in home)

    settings = fetched["/settings"]
    check("settings explains itself", "не днешната работа" in settings)
    for href in ("/sources", "/models", "/intake", "/cases"):
        check(f"settings links {href}", f'href="{href}"' in settings)
    check(
        "settings links back to daily work",
        'href="/stories"' in settings and 'href="/articles"' in settings,
    )

    check("sources page lists the registry", "Общински съвет Бургас" in fetched["/sources"])
    check("inbox page shows the material", "Общинският съвет прие бюджета" in fetched["/inbox"])
    check("inbox keeps the safety line", "не доказателства" in fetched["/inbox"])
    check("models page renders", "AI модели" in fetched["/models"])
    check("cases archive renders", "filter" in fetched["/cases"])
    check(
        "intake page renders (no dev jargon)",
        "YouTube" in fetched["/intake"] and "M3B" not in fetched["/intake"],
    )

    # ---- stylesheet ----
    resp = get(base + "/static/style.css")
    css = resp.read().decode("utf-8")
    check(
        "/static/style.css 200 + text/css",
        resp.status == 200 and "text/css" in resp.headers.get("Content-Type", ""),
    )
    check("css has the collapsible rail", "--rail-open" in css and ".nav-toggle:checked" in css)
    check("css has the mobile drawer", "translateX(-104%)" in css)
    check("pages keep the inline fallback", "<style>" in home)

    # ---- back-compat + actions ----
    resp = get(f"{base}/?filter=edit")
    page = resp.read().decode("utf-8")
    check(
        "old /?filter= links still reach the archive",
        resp.status == 200 and 'href="/cases?filter=edit"' in page,
    )

    resp = post(f"{base}/inbox", {"action": "collect_preview"})
    check("dry-run collect works (no network)", resp.code in (302, 303), f"code={resp.code}")

    resp = post(f"{base}/stories", {"action": "status", "story": "nope", "status": "SEEN"})
    loc = resp.headers.get("Location", "")
    check(
        "refusals stay readable (redirect carries the message)",
        resp.code in (302, 303) and "error=" in loc,
        f"code={resp.code} loc={loc}",
    )

    resp = get(f"{base}/definitely-not-a-page")
    page = resp.read().decode("utf-8")
    check(
        "404 keeps the shell and is well-formed",
        resp.status == 404 and not wellformed(page) and 'id="nav-toggle"' in page,
    )

    resp = get(f"{base}/healthz")
    check("/healthz OK", resp.status == 200 and resp.read().decode().startswith("OK"))


if __name__ == "__main__":
    sys.exit(main())
