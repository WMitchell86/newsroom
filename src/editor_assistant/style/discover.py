"""M2.1B listing discovery — deterministic, stdlib only, same-domain only.

Allowed: approved archive/listing pages -> same-scope pagination links
found inside paging containers -> article links. Article pages never
contribute crawl targets. No query strings, no cross-domain jumps.

Observed live template (validated 2026-09-13 on /author/desislava and
/posts/kultura + one deep pagination page each):
- listing item: <h2 class="post-title"><a href="https://.../post/<slug>">
- per-item metadata: <span class="post-author">, <span class="post-date">
  ("DD.MM.YYYYг. HH:MMч., обновена на ..." form)
- pagination: <div class="paging"><ul class="pagination"> with links of
  the form <base>/posts/<n> (category) or .../author/<slug>/posts/<n>
  (author); the last item is an absolute id-form page.
- deep archives keep identical markup (page 4707 probed).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from editor_assistant.style.corpus import normalize_text

ALLOWED_HOST = "chernomorie-bg.com"
POST_RE = re.compile(r"^https://chernomorie-bg\.com/post/[A-Za-z0-9_\-~.]+/?$")


class ListingParseError(ValueError):
    pass


class _ListingParser(HTMLParser):
    def __init__(self, *, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.posts: dict[str, dict[str, str]] = {}
        self.pages: set[str] = set()
        self._in_h2_title = False
        self._in_author = False
        self._in_date = False
        self._current: dict[str, str] = {}
        self._in_paging = False
        self._paging_depth = 0

    def _abs(self, href: str) -> str | None:
        href = (href or "").strip()
        if not href:
            return None
        absolute = urljoin(self.page_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != ALLOWED_HOST:
            return None
        return absolute.split("#")[0]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        attr = {k.lower(): (v or "") for k, v in attrs}
        classes = attr.get("class", "").lower()
        if "paging" in classes or "pagination" in classes:
            self._in_paging = True
            self._paging_depth = 1
            return
        if self._in_paging and name == "div":
            self._paging_depth += 1
        if name == "h2" and "post-title" in classes:
            self._in_h2_title = True
            self._current = {}
            return
        if name == "span" and "post-author" in classes:
            self._in_author = True
            return
        if name == "span" and "post-date" in classes:
            self._in_date = True
            self._current.setdefault("date", "")
            return
        if name == "a" and "href" in attr:
            absolute = self._abs(attr["href"])
            if absolute is None:
                return
            if POST_RE.match(absolute):
                entry = self.posts.setdefault(absolute, {})
                entry["url"] = absolute
                if self._in_h2_title:
                    self._current["url"] = absolute
                return
            if (
                self._in_paging
                and ("/posts/" in absolute or "/author/" in absolute)
                and absolute != self.page_url
            ):
                self.pages.add(absolute)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if self._in_paging and name == "div":
            self._paging_depth -= 1
            if self._paging_depth <= 0:
                self._in_paging = False
            return
        if name == "h2" and self._in_h2_title:
            self._in_h2_title = False
        if name == "span" and self._in_author:
            self._in_author = False
        if name == "span" and self._in_date:
            self._in_date = False

    def handle_data(self, data: str) -> None:
        if not data or not data.strip():
            return
        if self._in_h2_title and "url" in self._current:
            entry = self.posts[self._current["url"]]
            entry["headline"] = (entry.get("headline", "") + " " + data.strip()).strip()
        elif self._in_author:
            self._current["author"] = (self._current.get("author", "") + " " + data.strip()).strip()
            if "url" in self._current and self._current["url"] in self.posts:
                entry = self.posts[self._current["url"]]
                entry["author"] = self._current["author"]
        elif self._in_date:
            self._current["date"] = (self._current.get("date", "") + " " + data.strip()).strip()
            if "url" in self._current and self._current["url"] in self.posts:
                entry = self.posts[self._current["url"]]
                entry["date"] = self._current["date"]


def parse_listing_page(
    html: str | bytes, *, page_url: str
) -> tuple[list[dict[str, str]], list[str]]:
    """Parse one listing page -> (post entries, same-scope pagination urls)."""
    if isinstance(html, bytes):
        raw = html.decode("utf-8")
    else:
        raw = html
    if not raw or not raw.strip():
        raise ListingParseError("empty listing page")
    parser = _ListingParser(page_url=page_url)
    parser.feed(raw)
    parser.close()
    entries = []
    for url, entry in parser.posts.items():
        cleaned = {"url": url}
        for key in ("headline", "author", "date"):
            value = normalize_text(entry.get(key))
            if value:
                cleaned[key] = value
        entries.append(cleaned)
    base_prefix = page_url.rstrip("/") + "/"
    scoped = set()
    for candidate in sorted(parser.pages):
        if not candidate.startswith(base_prefix):
            continue
        rest = candidate[len(base_prefix) :]
        if re.fullmatch(r"(posts/)?\d+", rest):
            scoped.add(candidate)
    return entries, sorted(scoped)
