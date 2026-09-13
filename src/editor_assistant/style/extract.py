"""M2.1A article HTML extractor — deterministic, stdlib only, no network.

Live chernomorie-bg.com contract (validated 2026-09-13, 10 pages):
- headline: <h1 itemprop="headline" class="post-title">
- author: .post-meta .post-author a (empty on old pages -> None)
- categories: .post-cat anchors inside .post-title-area (multiple kept)
- dates: <meta itemprop="datePublished"/"dateModified"> with odd
  "2026-09-03EEST17:38:00+02:00" form -> "2026-09-03T17:38:00+02:00";
  visible .post-date text kept as *_raw; chrono YYYY-MM-DD derived.
- body: <div class="entry-content"> <p> only. Tags (.post-tags),
  related (.related-posts "\u041e\u0449\u0435 \u043d\u043e\u0432\u0438\u043d\u0438"),
  caption (.picture_alt_text outside entry-content) are NOT body.
- quotes: no <blockquote> on live pages; quoted speech stays inline in
  body. Structured quotes from <blockquote>/<q> only (additive, kept in
  body per M2.1A section 7).
- lead: no structurally distinct lead element observed -> lead=None.
- identity: canonical <link rel="canonical"> (else fetched URL) +
  numeric post-id suffix; article_id stable against content edits.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from html.parser import HTMLParser

from editor_assistant.style.corpus import ArticleRecord, normalize_text

_WS_RE = re.compile(r"\s+")
_POST_ID_RE = re.compile(r"-(\d{1,10})\s*$")
_DATEPREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[A-Za-z]{2,5}(\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})$")
_BG_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*\u0433?\.")


class ArticleParseError(ValueError):
    """Raised when page HTML is structurally invalid or unusable."""


def extract_post_id(url: str) -> str | None:
    """Stable numeric post id from canonical URL suffix, else None."""
    slug = (url or "").strip().rstrip("/").rsplit("/", 1)[-1]
    match = _POST_ID_RE.search(slug)
    return match.group(1) if match else None


def stable_article_id(canonical_url: str, post_id: str | None) -> str:
    """Identity from canonical URL — never from headline/date/body."""
    seed = f"chernomorie-post:{post_id}" if post_id else f"chernomorie-url:{canonical_url}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def normalize_live_datetime(raw: str | None) -> str | None:
    """Normalize odd live form "2026-09-03EEST17:38:00+02:00"."""
    text = normalize_text(raw)
    if text is None:
        return None
    match = _DATEPREFIX_RE.match(text.replace(" ", ""))
    if match:
        return f"{match.group(1)}T{match.group(2)}"
    return text


def normalize_chrono_date(raw: str | None) -> str | None:
    """Deterministic YYYY-MM-DD from ISO text or BG "DD.MM.YYYY." text."""
    text = normalize_text(raw)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    match = _BG_DATE_RE.search(text)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
        except ValueError:
            return None
    return None


class _LiveParser(HTMLParser):
    """Collect live-template fields; entry-content <p> only for body."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.headline_parts: list[str] = []
        self.in_h1 = False
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.in_title_area = False
        self.title_area_depth = 0
        self.categories: list[str] = []
        self._in_post_cat = False
        self._cat_buf: list[str] = []
        self.in_post_meta = False
        self.post_meta_depth = 0
        self.in_author_span = False
        self._in_author_link = False
        self._author_buf: list[str] = []
        self.in_post_date = False
        self._date_buf: list[str] = []
        self.caption_parts: list[str] = []
        self._in_caption = False
        self.in_entry = False
        self.entry_depth = 0
        self.paragraphs: list[str] = []
        self._current: list[str] = []
        self._in_para = False
        self.quotes: list[str] = []
        self._quote_buf: list[str] = []
        self._in_quote = False
        self.tag_links: list[str] = []
        self._in_post_tags = False
        self.post_tags_depth = 0
        self._in_tag_link = False
        self._tag_buf: list[str] = []

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> str:
        for key, value in attrs:
            if key.lower() == "class":
                return (value or "").lower()
        return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        classes = self._classes(attrs)
        attr = {k.lower(): (v or "") for k, v in attrs}
        if name == "title":
            self.in_title = True
            return
        if name == "meta":
            key = (attr.get("itemprop") or attr.get("property") or attr.get("name") or "").lower()
            if key and attr.get("content", "").strip():
                self.meta.setdefault(key, attr["content"].strip())
            return
        if (
            name == "link"
            and attr.get("rel", "").lower() == "canonical"
            and attr.get("href", "").strip()
        ):
            self.canonical = attr["href"].strip()
            return
        if name == "div" and "post-title-area" in classes:
            self.in_title_area = True
            self.title_area_depth = 1
            return
        if self.in_title_area and name == "div":
            self.title_area_depth += 1
        if self.in_title_area and name == "a" and "post-cat" in classes:
            self._in_post_cat = True
            self._cat_buf = []
            return
        if name == "h1":
            self.in_h1 = True
            return
        if name == "div" and "post-meta" in classes:
            self.in_post_meta = True
            self.post_meta_depth = 1
            return
        if self.in_post_meta and name == "div":
            self.post_meta_depth += 1
        if self.in_post_meta and name == "span":
            if "post-author" in classes:
                self.in_author_span = True
            if "post-date" in classes:
                self.in_post_date = True
            return
        if self.in_author_span and name == "a":
            self._in_author_link = True
            self._author_buf = []
            return
        if name == "p" and "picture_alt_text" in classes:
            self._in_caption = True
            self.caption_parts = []
            return
        if name == "div" and "entry-content" in classes:
            self.in_entry = True
            self.entry_depth = 1
            return
        if self.in_entry and name == "div":
            self.entry_depth += 1
            return
        if self.in_entry and name == "p" and not self._in_quote:
            self._in_para = True
            self._current = []
            return
        if self.in_entry and name in ("blockquote", "q"):
            self._in_quote = True
            self._quote_buf = []
            return
        if name == "div" and "post-tags" in classes:
            self._in_post_tags = True
            self.post_tags_depth = 1
            return
        if self._in_post_tags and name == "div":
            self.post_tags_depth += 1
        if self._in_post_tags and name == "a":
            self._in_tag_link = True
            self._tag_buf = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self.in_title = False
            return
        if name == "h1" and self.in_h1:
            self.in_h1 = False
            return
        if name == "a" and self._in_post_cat:
            text = normalize_text("".join(self._cat_buf))
            if text and text not in self.categories:
                self.categories.append(text)
            self._in_post_cat = False
            return
        if self.in_title_area and name == "div":
            self.title_area_depth -= 1
            if self.title_area_depth <= 0:
                self.in_title_area = False
            return
        if name == "a" and self._in_author_link:
            self._author_buf.append("")
            self._in_author_link = False
            return
        if name == "span" and self.in_author_span:
            self.in_author_span = False
        if name == "span" and self.in_post_date:
            self.in_post_date = False
        if self.in_post_meta and name == "div":
            self.post_meta_depth -= 1
            if self.post_meta_depth <= 0:
                self.in_post_meta = False
        if name == "p" and self._in_caption:
            self._in_caption = False
            return
        if name in ("blockquote", "q") and self._in_quote:
            text = normalize_text("".join(self._quote_buf))
            if text:
                self.quotes.append(text)
                self.paragraphs.append(text)
            self._in_quote = False
            return
        if self.in_entry and name == "p" and self._in_para:
            text = normalize_text("".join(self._current))
            if text:
                self.paragraphs.append(text)
            self._in_para = False
            return
        if self.in_entry and name == "div":
            self.entry_depth -= 1
            if self.entry_depth <= 0:
                self.in_entry = False
            return
        if name == "a" and self._in_tag_link:
            text = normalize_text("".join(self._tag_buf))
            if text and text not in self.tag_links:
                self.tag_links.append(text)
            self._in_tag_link = False
            return
        if self._in_post_tags and name == "div":
            self.post_tags_depth -= 1
            if self.post_tags_depth <= 0:
                self._in_post_tags = False

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self._in_post_cat:
            self._cat_buf.append(data)
            return
        if self.in_h1:
            self.headline_parts.append(data)
            return
        if self._in_author_link:
            self._author_buf.append(data)
            return
        if self.in_post_date:
            self._date_buf.append(data)
            return
        if self._in_caption:
            self.caption_parts.append(data)
            return
        if self._in_quote:
            self._quote_buf.append(data)
            return
        if self._in_para:
            self._current.append(data)
            return
        if self._in_tag_link:
            self._tag_buf.append(data)


def _author_text(parts: list[str]) -> str | None:
    return normalize_text("".join(parts))


def parse_article_html(html: str | bytes, *, url: str) -> ArticleRecord:
    """Parse one live article page into an ArticleRecord (deterministic)."""
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
    parser = _LiveParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:
        raise ArticleParseError(f"malformed HTML: {exc}") from exc
    headline = normalize_text("".join(parser.headline_parts))
    if headline is None:
        headline = normalize_text(parser.meta.get("og:title"))
    if headline is None:
        headline = normalize_text("".join(parser.title_parts))
    body = "\n\n".join(parser.paragraphs) if parser.paragraphs else None
    if headline is None or body is None:
        raise ArticleParseError("page has no usable headline + body")
    canonical = normalize_text(parser.canonical) or url.strip()
    post_id = extract_post_id(canonical) or extract_post_id(url)
    published_raw = normalize_live_datetime(parser.meta.get("datepublished"))
    updated_raw = normalize_live_datetime(parser.meta.get("datemodified"))
    date_display = normalize_text("".join(parser._date_buf))
    chrono = normalize_chrono_date(published_raw) or normalize_chrono_date(date_display)
    author = _author_text(parser._author_buf)
    categories = [c for c in parser.categories if c]
    category = categories[0] if categories else None
    subheadline = normalize_text(parser.meta.get("og:description")) or normalize_text(
        parser.meta.get("description")
    )
    caption = normalize_text("".join(parser.caption_parts))
    return ArticleRecord(
        article_id=stable_article_id(canonical, post_id),
        url=canonical,
        published_at=published_raw,
        published_at_raw=normalize_text(parser.meta.get("datepublished"))
        or normalize_text("".join(parser._date_buf)),
        published_date=chrono,
        updated_at=updated_raw,
        updated_at_raw=normalize_text(parser.meta.get("datemodified")),
        author=author,
        category=category,
        categories=tuple(categories),
        headline=headline,
        subheadline=subheadline,
        lead=None,
        body=body,
        quotes=tuple(parser.quotes),
        tags=tuple(parser.tag_links),
        caption=caption,
        post_id=post_id,
        source_type="chernomorie_archive",
    )
