"""M2.1A style corpus package — isolated from frozen Radar (stdlib only)."""

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
from editor_assistant.style.extract import (
    ArticleParseError,
    extract_post_id,
    normalize_chrono_date,
    normalize_live_datetime,
    parse_article_html,
    stable_article_id,
)

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
    "extract_post_id",
    "find_duplicates",
    "make_article_id",
    "manifest_to_dict",
    "normalize_chrono_date",
    "normalize_live_datetime",
    "normalize_text",
    "parse_article_html",
    "stable_article_id",
]
