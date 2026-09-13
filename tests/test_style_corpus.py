"""M2.1 Style Corpus tests — offline fixtures only, no network.

Covers the 12 M2.1 cases: valid extraction, missing author/category,
Bulgarian Unicode, multi-paragraph body, quote preservation, metadata
cleanup, navigation exclusion, deterministic normalization, duplicate
detection, malformed quarantine, re-run stability.
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
    make_article_id,
    normalize_text,
)
from editor_assistant.style.extract import parse_article_html
from editor_assistant.style.store import import_pages, read_jsonl, write_jsonl

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "style"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_valid_extraction():
    record = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    assert record.headline == "Новият парк в Бургас отвори врати"
    assert record.author == "Иванка Петрова"
    assert record.category == "Бургас"
    assert record.published_at == "2026-08-14T10:30:00+03:00"
    assert record.source_type == SOURCE_TYPE


def test_missing_author_stays_none():
    record = parse_article_html(
        _read("article_missing_author.html"), url="https://example.com/cherries"
    )
    assert record.author is None
    assert record.headline is not None


def test_missing_category_stays_none():
    record = parse_article_html(
        _read("article_missing_category.html"), url="https://example.com/notice"
    )
    assert record.category is None
    assert record.published_at is None
    assert record.author == "Редакционен екип"


def test_bulgarian_unicode_preserved():
    record = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    assert "„" in (record.quotes[0] if record.quotes else "")
    assert "“" in (record.quotes[0] if record.quotes else "")
    assert "Бургаското езеро" in (record.body or "")
    record2 = parse_article_html(
        _read("article_standard.html").encode("utf-8"), url="https://example.com/park"
    )
    assert record2.body == record.body


def test_multi_paragraph_body():
    record = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    assert record.body is not None
    assert record.body.count("\n\n") == 2
    assert record.lead == record.body.split("\n\n")[0]


def test_metadata_cleanup():
    record = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    assert record.subheadline == "Паркът край езерото посрещна първите посетители."
    assert record.tags == ("Бургас", "парк", "езеро")


def test_navigation_exclusion():
    record = parse_article_html(_read("article_boilerplate.html"), url="https://example.com/season")
    assert record.body is not None
    for noise in ("Сподели", "Реклама", "Свързани", "Начало"):
        assert noise not in record.body


def test_deterministic_normalization():
    raw = _read("article_standard.html").replace("</p>", "  </p>\n  ")
    first = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    second = parse_article_html(raw, url="https://example.com/park")
    assert first == second
    assert normalize_text("  а   б \n в  ") == "а б в"
    assert normalize_text("   ") is None
    assert first.article_id == make_article_id(
        "https://example.com/park", first.published_at, first.headline
    )


def test_duplicate_detection():
    first = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    twin = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    other = parse_article_html(
        _read("article_missing_author.html"), url="https://example.com/cherries"
    )
    dups = find_duplicates([first, twin, other])
    assert len(dups["by_url"]) == 1
    assert len(dups["by_body_hash"]) == 1
    assert len(dups["by_headline_date"]) == 1
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
            ("https://example.com/park", _read("article_standard.html")),
            ("https://example.com/cherries", _read("article_missing_author.html")),
        ]
    )
    assert failures == []
    path = write_jsonl(records, tmp_path / "corpus.jsonl")
    again = read_jsonl(path)
    assert [article_to_dict(r) for r in again] == [article_to_dict(r) for r in records]
    assert [article_from_dict(article_to_dict(r)) for r in again] == records
    first_manifest = build_manifest(records)
    second_manifest = build_manifest(read_jsonl(path))
    assert first_manifest == second_manifest
    assert first_manifest.total_articles == 2
    assert first_manifest.missing_author == 1
    raw = path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 2
    assert json.loads(raw[0])["source_type"] == SOURCE_TYPE


def test_quote_preservation():
    record = parse_article_html(_read("article_standard.html"), url="https://example.com/park")
    assert len(record.quotes) == 1
    assert "Искахме място" in record.quotes[0]
    assert record.quotes[0] not in (record.body or "")
