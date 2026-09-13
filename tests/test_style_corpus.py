"""M2.1A Style Corpus tests — offline fixtures only, no network.

Covers M2.1A section 18 (10 required proofs) + M2.1 extractor cases:
valid live-template extraction, missing author/category, Unicode,
multi-paragraph body, quote-in-body, metadata/caption, nav exclusion,
deterministic normalization, stable identity, quarantine, re-run.
"""

from __future__ import annotations

import json
import pathlib

from editor_assistant.style.corpus import (
    SOURCE_TYPE,
    article_from_dict,
    article_to_dict,
    body_hash,
    build_manifest,
    find_duplicates,
    normalize_text,
)
from editor_assistant.style.extract import (
    extract_post_id,
    normalize_chrono_date,
    normalize_live_datetime,
    parse_article_html,
    stable_article_id,
)
from editor_assistant.style.store import import_pages, read_jsonl, write_jsonl

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "style"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_valid_live_extraction():
    record = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    assert "\u043a\u0438\u043d\u043e" in (record.headline or "")
    assert record.headline and "\u043a\u0438\u043d\u043e" in record.headline
    assert (
        record.author == "\u0427\u0435\u0440\u043d\u043e\u043c\u043e\u0440\u0438\u0435-\u0431\u0433"
    )
    assert record.post_id == "7085"
    assert record.source_type == SOURCE_TYPE


def test_missing_author_stays_none():
    record = parse_article_html(
        _read("live_old_no_author.html"), url="https://example.com/post/m-bus-x"
    )
    assert record.author is None
    assert record.headline is not None


def test_missing_category_or_single():
    record = parse_article_html(
        _read("live_old_no_author.html"), url="https://example.com/post/m-bus-x"
    )
    assert record.category == "\u041d\u0430 \u043f\u044a\u0442"
    assert record.categories == ("\u041d\u0430 \u043f\u044a\u0442",)


def test_bulgarian_unicode_preserved():
    record = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    assert "Burgas" in (record.body or "")
    assert "\u201e\u0414\u0435\u043a\u0430\u043c\u0435\u0440\u043e\u043d" in (record.body or "")
    again = parse_article_html(
        _read("live_culture.html").encode("utf-8"), url="https://example.com/post/x-7085"
    )
    assert again.body == record.body


def test_multi_paragraph_body():
    record = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    assert record.body is not None
    assert len(record.body.split("\n\n")) >= 3


def test_quote_remains_in_body_and_structured():
    record = parse_article_html(_read("live_quote.html"), url="https://example.com/post/q-1")
    assert len(record.quotes) == 1
    assert "\u0418\u0441\u043a\u0430\u0445\u043c\u0435" in record.quotes[0]
    assert record.quotes[0] in (record.body or "")


def test_metadata_cleanup_and_caption_not_lead():
    record = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    assert record.caption == "Caption text stays out of body and lead."
    assert record.lead is None
    assert record.caption not in (record.body or "")
    assert len(record.tags) == 2


def test_navigation_and_related_exclusion():
    record = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    assert record.body is not None
    for noise in (
        "\u041e\u0449\u0435 \u043d\u043e\u0432\u0438\u043d\u0438",
        "\u0422\u0430\u0433\u043e\u0432\u0435",
        "Related Headline",
    ):
        assert noise not in record.body
    assert "tag-one" not in record.body


def test_deterministic_normalization():
    raw = _read("live_culture.html").replace("</p>", "  </p>\n  ")
    first = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    second = parse_article_html(raw, url="https://example.com/post/x-7085")
    assert first == second
    assert normalize_text("  \u0430   \u0431 \n \u0432  ") == "\u0430 \u0431 \u0432"
    assert normalize_text("   ") is None


def test_identity_stable_against_headline_edit():
    first = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    edited = _read("live_culture.html").replace(
        "\u043a\u0438\u043d\u043e", "\u041a\u0418\u041d\u041e"
    )
    second = parse_article_html(edited, url="https://example.com/post/x-7085")
    assert first.article_id == second.article_id
    assert first.headline != second.headline


def test_identity_stable_against_body_edit():
    first = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    edited = _read("live_culture.html").replace(
        "Third paragraph closes", "Third paragraph closes with extra program notes"
    )
    second = parse_article_html(edited, url="https://example.com/post/x-7085")
    assert first.article_id == second.article_id
    assert first.body != second.body


def test_canonical_identity_and_post_id():
    record = parse_article_html(
        _read("live_culture.html"), url="https://example.com/post/other-path"
    )
    assert record.url == "https://example.com/post/x-7085"
    assert record.post_id == "7085"
    assert record.article_id == stable_article_id(record.url, "7085")
    assert extract_post_id("https://example.com/post/m-bus-x") is None


def test_chrono_date_parsing():
    assert normalize_live_datetime("2026-09-03EEST17:38:00+02:00") == "2026-09-03T17:38:00+02:00"
    assert normalize_chrono_date("2026-09-03T17:38:00+02:00") == "2026-09-03"
    assert normalize_chrono_date("03.09.2026\u0433. 17:38\u0447.") == "2026-09-03"
    record = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    assert record.published_date == "2026-09-03"


def test_duplicate_detection_by_post_and_url():
    first = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    twin = parse_article_html(_read("live_culture.html"), url="https://example.com/post/x-7085")
    other = parse_article_html(
        _read("live_old_no_author.html"), url="https://example.com/post/m-bus-x"
    )
    dups = find_duplicates([first, twin, other])
    assert len(dups["by_url"]) == 1
    assert len(dups["by_post_id"]) == 1
    assert len(dups["by_body_hash"]) == 1
    manifest = build_manifest([first, twin, other])
    assert manifest.duplicate_count == 1
    assert body_hash(first.body) == body_hash(twin.body)
    assert body_hash(None) is None


def test_malformed_page_quarantine():
    records, failures = import_pages(
        [("https://example.com/bad", _read("article_malformed.html"))],
        observed_at="2026-09-13T00:00:00+00:00",
    )
    assert records == []
    assert len(failures) == 1
    assert failures[0].url == "https://example.com/bad"
    assert failures[0].failure_detail
    assert failures[0].observed_at == "2026-09-13T00:00:00+00:00"


def test_rerun_stability_and_jsonl_roundtrip(tmp_path):
    records, failures = import_pages(
        [
            ("https://example.com/post/x-7085", _read("live_culture.html")),
            ("https://example.com/post/m-bus-x", _read("live_old_no_author.html")),
        ]
    )
    assert failures == []
    path = write_jsonl(records, tmp_path / "corpus.jsonl")
    again = read_jsonl(path)
    assert [article_to_dict(r) for r in again] == [article_to_dict(r) for r in records]
    assert [article_from_dict(article_to_dict(r)) for r in again] == records
    assert build_manifest(records) == build_manifest(read_jsonl(path))
    assert build_manifest(records).total_articles == 2
    assert build_manifest(records).date_min == "2015-10-28"
    assert build_manifest(records).date_max == "2026-09-03"
    raw = path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 2
    assert json.loads(raw[0])["source_type"] == SOURCE_TYPE
