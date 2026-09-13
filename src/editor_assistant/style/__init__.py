"""M2.1 style corpus package — isolated from frozen Radar (stdlib only)."""

from editor_assistant.style.corpus import (
    SOURCE_TYPE,
    ArticleRecord,
    CorpusManifest,
    FailureRecord,
    article_from_dict,
    article_to_dict,
    body_hash,
    build_manifest,
    find_duplicates,
    make_article_id,
    manifest_to_dict,
    normalize_text,
)
from editor_assistant.style.extract import ArticleParseError, parse_article_html

__all__ = [
    "SOURCE_TYPE",
    "ArticleParseError",
    "ArticleRecord",
    "CorpusManifest",
    "FailureRecord",
    "article_from_dict",
    "article_to_dict",
    "body_hash",
    "build_manifest",
    "find_duplicates",
    "make_article_id",
    "manifest_to_dict",
    "normalize_text",
    "parse_article_html",
]
