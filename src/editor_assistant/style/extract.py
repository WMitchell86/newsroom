"""M2.1 article HTML extractor — deterministic, stdlib only, no network.

Extracts article content only; excludes nav/footer/related/ads/share/
sidebar via explicit denylist. Preserves published wording verbatim.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from editor_assistant.style.corpus import (
    ArticleRecord,
    make_article_id,
    normalize_text,
)

_WS_RE = re.compile(r"\s+")


class ArticleParseError(ValueError):
    """Raised when page HTML is structurally invalid or unusable."""


# Class/token fragments that mark non-article regions (explicit denylist).
_SKIP_CLASS_RE = re.compile(
    r"(nav|footer|sidebar|aside|related|recommend|share|social-share|"
    r"advert|ads?-|banner|popup|newsletter|comment|widget|menu|breadcrumb)",
    re.IGNORECASE,
)
_SKIP_ID_RE = re.compile(
    r"(nav|footer|sidebar|related|share|advert|banner|popup|newsletter|comment|menu)",
    re.IGNORECASE,
)
_SKIP_TAG = frozenset({"nav", "footer", "aside", "script", "style", "form", "iframe"})

_QUOTE_TAG = frozenset({"blockquote", "q"})
_PARAGRAPH_TAG = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"})


class _ArticleParser(HTMLParser):
    """Collect article-region text; skip boilerplate regions."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.in_article = False
        self.article_found = False
        self.title_parts: list[str] = []
        self.in_title = False
        self.headline_parts: list[str] = []
        self.in_h1 = False
        self.paragraphs: list[str] = []
        self._current: list[str] = []
        self._in_para = False
        self.quotes: list[str] = []
        self._quote_buf: list[str] = []
        self._in_quote = False
        self.meta: dict[str, str] = {}
        self.time_text: list[str] = []
        self._in_time = False

    def _is_skip_node(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in _SKIP_TAG:
            return True
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        cls = attrs_d.get("class", "")
        ident = attrs_d.get("id", "")
        role = attrs_d.get("role", "").lower()
        if role in {"navigation", "banner", "complementary", "contentinfo"}:
            return True
        if cls and _SKIP_CLASS_RE.search(cls):
            return True
        return bool(ident and _SKIP_ID_RE.search(ident))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name == "article":
            self.in_article = True
            self.article_found = True
            return
        if name == "title":
            self.in_title = True
            return
        if name == "meta":
            d = {k.lower(): (v or "") for k, v in attrs}
            key = (d.get("property") or d.get("name") or "").lower()
            if key and d.get("content", "").strip():
                self.meta.setdefault(key, d["content"].strip())
            return
        if name == "time":
            d = {k.lower(): (v or "") for k, v in attrs}
            if d.get("datetime", "").strip():
                self.meta.setdefault("time_datetime", d["datetime"].strip())
            self._in_time = True
            return
        if self.skip_depth:
            if self._is_skip_node(name, attrs):
                self.skip_depth += 1
            return
        if not self.in_article and self.article_found:
            return
        if self._is_skip_node(name, attrs):
            self.skip_depth = 1
            return
        if name == "h1" and not self.headline_parts:
            self.in_h1 = True
            return
        if name in _QUOTE_TAG:
            self._in_quote = True
            self._quote_buf = []
            return

        if name in _PARAGRAPH_TAG:
            self._in_para = True
            self._current = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "article":
            self.in_article = False
            return
        if name == "title":
            self.in_title = False
            return
        if name == "time":
            self._in_time = False
            return
        if self.skip_depth:
            if name not in {"br", "img", "hr"}:
                self.skip_depth = max(0, self.skip_depth - 1)
            return
        if name == "h1" and self.in_h1:
            self.in_h1 = False
            return
        if name in _QUOTE_TAG and self._in_quote:
            text = normalize_text("".join(self._quote_buf))
            if text:
                self.quotes.append(text)
            self._in_quote = False
            self._quote_buf = []
            return
        if name in _PARAGRAPH_TAG and self._in_para:
            text = normalize_text("".join(self._current))
            if text:
                self.paragraphs.append(text)
            self._in_para = False
            self._current = []

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self._in_time:
            self.time_text.append(data)
        if self.skip_depth:
            return
        if not self.in_article and self.article_found:
            return
        if self.in_h1:
            self.headline_parts.append(data)
            return
        if self._in_quote:
            self._quote_buf.append(data)
            return
        if self._in_para:
            self._current.append(data)


def _meta_lookup(meta: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if value and value.strip():
            return value.strip()
    return None


def parse_article_html(html: str | bytes, *, url: str) -> ArticleRecord:
    """Parse one article page into an ArticleRecord (deterministic).

    Raises ArticleParseError for empty/malformed pages or pages with no
    usable headline + body. Missing author/category/date stay None.
    """
    if not url or not url.strip():
        raise ArticleParseError("article url is required")
    if isinstance(html, bytes):
        try:
            raw = html.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArticleParseError(f"page is not valid UTF-8: {exc}") from exc
    else:
        raw = html
    if not raw or not raw.strip():
        raise ArticleParseError("empty article page")
    parser = _ArticleParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:
        raise ArticleParseError(f"malformed HTML: {exc}") from exc
    headline = normalize_text("".join(parser.headline_parts))
    if headline is None:
        headline = normalize_text(_meta_lookup(parser.meta, "og:title", "twitter:title"))
    if headline is None:
        headline = normalize_text("".join(parser.title_parts))
    body_paras = list(parser.paragraphs)
    for quote in parser.quotes:
        if quote in body_paras:
            body_paras.remove(quote)
    body = "\n\n".join(body_paras) if body_paras else None
    if headline is None or body is None:
        raise ArticleParseError("page has no usable headline + body")
    author = normalize_text(
        _meta_lookup(parser.meta, "author", "article:author", "og:author", "twitter:creator")
    )
    category = normalize_text(
        _meta_lookup(parser.meta, "article:section", "category", "og:section")
    )
    published_at = normalize_text(
        _meta_lookup(
            parser.meta,
            "article:published_time",
            "time_datetime",
            "datepublished",
            "publish_date",
            "og:published_time",
        )
    )
    if published_at is None:
        published_at = normalize_text("".join(parser.time_text))
    subheadline = normalize_text(
        _meta_lookup(parser.meta, "og:description", "twitter:description", "description")
    )
    lead = body_paras[0] if body_paras else None
    tags_raw = normalize_text(_meta_lookup(parser.meta, "keywords", "news_keywords"))
    tags = tuple(t.strip() for t in (tags_raw or "").split(",") if t.strip())
    clean_url = url.strip()
    return ArticleRecord(
        article_id=make_article_id(clean_url, published_at, headline),
        url=clean_url,
        published_at=published_at,
        author=author,
        category=category,
        headline=headline,
        subheadline=subheadline,
        lead=lead,
        body=body,
        quotes=tuple(parser.quotes),
        tags=tags,
        source_type="chernomorie_archive",
    )
