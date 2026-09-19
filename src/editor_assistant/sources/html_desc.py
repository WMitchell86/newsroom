"""M1.2.1 HTML description normalizer — deterministic, stdlib only, no network.

Pipeline position: XML parsing → description string → here → plain text + links.
Rules: strip tags, decode entities, keep block boundaries readable, skip
<script>/<style>, collect <a href> in appearance order (dedup, resolve relative
against item_url), collapse whitespace deterministically.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

_WS_RE = re.compile(r"\s+")

# Tags that open a readable textual boundary (separator inserted).
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "section",
        "article",
        "header",
        "footer",
    }
)

_SKIP_TAGS = frozenset({"script", "style"})


class _DescriptionParser(HTMLParser):
    """Collect visible text chunks + anchor hrefs in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # entities decoded into handle_data
        self.chunks: list[str] = []
        self.hrefs: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if name == "a":
            for attr, value in attrs:
                if attr.lower() == "href" and value and value.strip():
                    self.hrefs.append(value.strip())
                    break
        if name in _BLOCK_TAGS:
            self.chunks.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (<br/>, <img/>) — same handling without end tag.
        # A self-closing <script/> / <style/> has no content, and no end tag will
        # arrive to close it: incrementing the skip depth here would suppress
        # every remaining text chunk in the description. (Reachable in practice:
        # ElementTree re-serializes an empty <script></script> as <script />.)
        if tag.lower() in _SKIP_TAGS:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if name in _BLOCK_TAGS:
            self.chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self.chunks.append(data)


def normalize_description(
    raw: str | None, *, base_url: str = ""
) -> tuple[str | None, tuple[str, ...]]:
    """Normalize an RSS description into (plain_text, links).

    - None/blank → (None, ()).
    - Plain text without markup passes through (whitespace-collapsed).
    - HTML → tags removed, entities decoded, blocks separated by spaces.
    - Links: appearance order, relative resolved via urljoin(base_url),
      duplicates removed (first occurrence wins), empty hrefs ignored.
    """
    if raw is None or not raw.strip():
        return None, ()
    parser = _DescriptionParser()
    parser.feed(raw)
    parser.close()
    # NBSP (U+00A0) is display whitespace: map it to a normal space first so
    # "a&amp;b&nbsp;c" decodes deterministically to "a&b c".
    text = _WS_RE.sub(" ", "".join(parser.chunks).replace(" ", " ")).strip()
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.hrefs:
        resolved = urljoin(base_url, href) if base_url else href
        if resolved not in seen:
            seen.add(resolved)
            links.append(resolved)
    return (text or None, tuple(links))
