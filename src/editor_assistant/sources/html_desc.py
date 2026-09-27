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

# --- V1.2-G2.4 §A2: structural segmentation --------------------------------
#
# `normalize_description` deliberately flattens every block boundary to a single
# space, which is right for an RSS summary and wrong for an article body: a
# `<h2>Heading</h2><p>Sentence.</p>` pair becomes the single run
# "Heading Sentence." and the sentence splitter — which can only break on
# punctuation — has nothing to break on. That is the *structural cause* of the
# three heading-plus-sentence merges G2.3 promoted ("Мъжки сингъл – любители
# Към момента..."), and it is why blacklisting those three strings would have
# been the wrong repair.
#
# The fix is to keep the boundary information instead of discarding it. Each
# visible text run is emitted as a typed block, and a heading, a list item and a
# paragraph can then never be concatenated into one factual sentence. The
# flattening behaviour of `normalize_description` is untouched for its existing
# callers.

#: Block kinds. Only `PROSE` may become a factual sentence.
HEADING = "HEADING"
LIST_ITEM = "LIST_ITEM"
NAV = "NAV"
LABEL = "LABEL"
PROSE = "PROSE"

#: Tags whose text is structural furniture rather than article prose.
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_LIST_TAGS = frozenset({"li"})
#: Containers that are almost always page furniture. A `<nav>` or `<aside>` is
#: never article prose, so its text is classified before anything reads it.
_NAV_TAGS = frozenset(
    {"nav", "aside", "header", "footer", "menu", "form", "select", "button"}
)
_LABEL_TAGS = frozenset({"dt", "figcaption", "caption", "label", "summary", "time"})


class _DescriptionParser(HTMLParser):
    """Collect visible text chunks + anchor hrefs in document order.

    §A2: when `typed=True` the parser also records which block each chunk
    belongs to, so segmentation survives the loss of HTML.
    """

    def __init__(self, *, typed: bool = False) -> None:
        super().__init__(convert_charrefs=True)  # entities decoded into handle_data
        self.chunks: list[str] = []
        self.hrefs: list[str] = []
        self._skip_depth = 0
        self._typed = typed
        self._kind_stack: list[str] = []
        self.blocks: list[dict] = []
        self._open: str | None = None
        self._buffer: list[str] = []

    # -- typed segmentation helpers -------------------------------------
    def _kind(self) -> str:
        """The strongest structural kind currently open, else PROSE."""
        for kind in reversed(self._kind_stack):
            if kind in (NAV, HEADING, LABEL, LIST_ITEM):
                return kind
        return PROSE

    def _flush(self) -> None:
        if self._open is None:
            return
        text = _WS_RE.sub(" ", "".join(self._buffer).replace(" ", " ")).strip()
        if text:
            self.blocks.append({"kind": self._open, "text": text})
        self._open = None
        self._buffer = []

    def _open_kind(self, kind: str) -> None:
        if self._open == kind:
            return
        self._flush()
        self._open = kind
        self._buffer = []

    def _close_kind(self, kind: str) -> None:
        if self._kind_stack and self._kind_stack[-1] == kind:
            self._kind_stack.pop()
        if self._open is not None and self._kind_stack:
            # The block continues under the next enclosing kind.
            self._open_kind(self._kind())
        else:
            self._flush()

    def _push(self, tag: str) -> None:
        kind = None
        if tag in _NAV_TAGS:
            kind = NAV
        elif tag in _HEADING_TAGS:
            kind = HEADING
        elif tag in _LABEL_TAGS:
            kind = LABEL
        elif tag in _LIST_TAGS:
            kind = LIST_ITEM
        if kind is not None:
            self._flush()
            self._kind_stack.append(kind)
            if self._open is None:
                self._open_kind(kind)

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
        if self._typed:
            self._push(name)
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
        if self._typed:
            self._close_kind_for(name)
        if name in _BLOCK_TAGS:
            self.chunks.append(" ")

    def _close_kind_for(self, name: str) -> None:
        """Close the block kind this end tag opened, if it opened one."""
        kind = None
        if name in _NAV_TAGS:
            kind = NAV
        elif name in _HEADING_TAGS:
            kind = HEADING
        elif name in _LABEL_TAGS:
            kind = LABEL
        elif name in _LIST_TAGS:
            kind = LIST_ITEM
        if kind is not None:
            self._close_kind(kind)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self.chunks.append(data)
            if self._typed:
                if self._open is None:
                    self._open_kind(self._kind())
                self._buffer.append(data)


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


def normalize_blocks(raw: str | None) -> tuple[dict, ...]:
    """V1.2-G2.4 §A2 — an article body as TYPED blocks, in document order.

    This is the structural repair for the heading-plus-sentence merges. The
    caller receives each visible run already classified as `PROSE`, `HEADING`,
    `LIST_ITEM`, `LABEL` or `NAV`, and can therefore refuse to build a
    proposition out of anything that is not prose. A heading is still *readable*
    and still appears in `HEADING` blocks, so it can give context to the
    sentence that follows it — it simply can no longer be concatenated into one.

    Deterministic and offline, exactly like `normalize_description`, which it
    shares the same parser with. Returns an empty tuple for unusable input.
    """
    if raw is None or not str(raw).strip():
        return ()
    parser = _DescriptionParser(typed=True)
    parser.feed(str(raw))
    parser.close()
    parser._flush()
    return tuple(parser.blocks)
