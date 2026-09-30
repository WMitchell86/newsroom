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

#: §A2 recovery — how long a run of text may stay classified as NAV before the
#: classification is distrusted. A menu, a footer and a sidebar are short; a
#: navigation run longer than this means the container was never closed, and
#: continuing to label the rest of the article "navigation" would silently lose
#: real facts. Losing recall quietly is far worse than demoting chrome to prose.
_MAX_NAV_CHARS = 800

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
        self._tag_stack: list[str] = []
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

    def _open_kind(self, kind: str | None) -> None:
        if self._open == kind:
            return
        self._flush()
        self._open = kind
        self._buffer = []

    def _close_kind(self, tag: str) -> None:
        """Unwind to the matching open tag, tolerating markup that is not well formed.

        Real pages omit end tags. Popping only when the tag is on top of the stack
        leaves a container open forever, and every later paragraph is then
        classified as NAV and silently lost — a recall failure that looks like
        "this page had no usable text". The standard recovery is used instead:
        find the nearest matching open tag and unwind everything opened inside
        it; ignore an end tag that matches nothing.
        """
        if tag not in self._tag_stack:
            return
        while self._tag_stack:
            top = self._tag_stack.pop()
            self._kind_stack.pop()
            if top == tag:
                break
        self._open_kind(self._kind() if self._kind_stack else None)

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
            # §A2 recovery: a HEADING inside a still-open furniture container
            # means the container was never closed — a `<header>` left open at
            # the top of an article is the common case, and without this every
            # following paragraph is lost as NAV. A heading is the one block kind
            # that is essentially never nested inside a nav/footer/form.
            if kind == HEADING:
                while self._tag_stack and self._kind_stack[-1] == NAV:
                    self._tag_stack.pop()
                    self._kind_stack.pop()
                self._open_kind(self._kind())
            self._flush()
            self._tag_stack.append(tag)
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
            # §A2 recovery: a PARAGRAPH inside a still-open navigation container
            # means the container was never closed. Menus are built from links
            # and list items; a `<p>` only ever appears in the article. Without
            # this, one missing `</nav>` silently deletes the whole article.
            if name == "p" and NAV in self._kind_stack:
                index = len(self._kind_stack) - 1 - self._kind_stack[::-1].index(NAV)
                del self._kind_stack[index:]
                del self._tag_stack[index:]
                # Close the navigation block that was still open, so the
                # paragraph that follows is buffered as prose rather than
                # appended to the menu.
                self._open_kind(self._kind())
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
        """Close the block this end tag opened, if it opened one."""
        if name in _NAV_TAGS or name in _HEADING_TAGS or name in _LABEL_TAGS or name in _LIST_TAGS:
            self._close_kind(name)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self.chunks.append(data)
            if self._typed:
                if self._open is None:
                    self._open_kind(self._kind())
                if self._open == NAV and sum(len(part) for part in self._buffer) > _MAX_NAV_CHARS:
                    # The container was never closed. Stop trusting the label.
                    self._open_kind(PROSE)
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


# ---------------------------------------------------------------------------
# V1.2-G4.28 — is this page an ARTICLE, and how much of one?
#
# Measured on 32 real URLs from the newsroom's own corpus. Fetching succeeds on
# essentially all of them, and extraction yields usable article prose on 27:
#
#     burgas.bg / cik.bg / bnr.bg / bta.bg / dariknews.bg / vesti.bg
#     flagman.bg / gramofona.com / burgascouncil.org / bdz.bg / baem.bg ...
#     -> 1,013 to 11,625 characters of real prose
#
#     facebook.com/chernomoriebg.news   978,016 bytes ->  31 characters
#     facebook.com/capitalbg/posts      862,836 bytes ->  49 characters
#     results.cik.bg/.../index.html        1,449 bytes ->   0 characters
#
# None of the three is an article, and that is not a bug in the extraction —
# but it left the caller unable to tell "this page has no article" from "the
# extractor failed". Both arrived as a successful fetch carrying almost
# nothing, and the only way to notice was to measure the body afterwards and
# infer.
#
# So the measurement is made where the extraction happens and travels on the
# page record, rather than being re-derived by each caller. `fetch_page` calls
# this once; research, enrichment and the hint path read the verdict instead of
# re-deriving it.
ARTICLE = "article"
THIN = "thin"
NONE = "none"

#: Below this a page is a wrapper, a login wall or an error page rather than a
#: short article. Set from the measurement above, not chosen to look tidy: the
#: genuine failures sat at 31 and 49 characters, two orders of magnitude under
#: the smallest real article in the sample.
THRESHOLD_ARTICLE_CHARS = 200


def article_prose(blocks) -> dict:
    """The PROSE blocks of a page, and a verdict on whether it is an article.

    `blocks` is what `normalize_blocks` returns. The three-way verdict exists
    because "no article here" and "the extraction broke" look identical from
    the outside, and a caller that cannot tell them will either trust an empty
    page or retry something that will never work.
    """
    prose = " ".join(
        str(block.get("text") or "").strip()
        for block in (blocks or ())
        if str(block.get("kind") or "") == PROSE and str(block.get("text") or "").strip()
    )
    prose = " ".join(prose.split())
    chars = len(prose)
    if chars >= THRESHOLD_ARTICLE_CHARS:
        verdict = ARTICLE
    elif chars:
        verdict = THIN
    else:
        verdict = NONE
    return {"text": prose, "chars": chars, "verdict": verdict}
