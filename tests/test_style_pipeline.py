"""M2.1B discovery + sampling + fetch tests — offline fixtures only.

Covers: listing parsing (article links, pagination scoping, metadata),
same-domain enforcement, seeded deterministic sampling (band targets,
year round-robin, category soft cap, cap rejection, URL de-dup),
fetch URL allow-list and collect_corpus offline behavior (snapshots,
quarantine, JSONL outputs, duplicates).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from editor_assistant.style.corpus import author_class, band_for_date
from editor_assistant.style.discover import ListingParseError, parse_listing_page
from editor_assistant.style.fetch import collect_corpus, is_allowed_article_url
from editor_assistant.style.sampling import (
    MAX_ARTICLES,
    listing_date_to_iso,
    selection_summary,
    stratified_selection,
    write_selected_jsonl,
)

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "style"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_listing_parse_extracts_posts_and_pagination():
    entries, pages = parse_listing_page(
        _read("listing_kultura.html"),
        page_url="https://chernomorie-bg.com/posts/kultura",
    )
    assert len(entries) == 2
    first = next(e for e in entries if e["url"].endswith("-5258"))
    assert first["headline"].startswith("Валентин Танев")
    assert first["author"] == "Черноморие-бг"
    assert first["date"].startswith("12.09.2026г.")
    # sidebar + same-page links are NOT pagination; only same-scope pages
    assert pages == [
        "https://chernomorie-bg.com/posts/kultura/1828",
        "https://chernomorie-bg.com/posts/kultura/2",
    ]


def test_listing_parse_rejects_empty_and_cross_domain():
    with pytest.raises(ListingParseError):
        parse_listing_page("", page_url="https://chernomorie-bg.com/posts/kultura")
    entries, pages = parse_listing_page(
        '<a href="https://other.example.com/post/x-1">x</a>',
        page_url="https://chernomorie-bg.com/posts/kultura",
    )
    assert entries == []
    assert pages == []


def test_listing_author_archive_pagination_scope():
    html = (
        _read("listing_kultura.html")
        .replace(
            "https://chernomorie-bg.com/posts/kultura/2",
            "https://chernomorie-bg.com/author/Chernomorie/posts/2",
        )
        .replace(
            "https://chernomorie-bg.com/posts/kultura/1828",
            "https://chernomorie-bg.com/author/Chernomorie/posts/4707",
        )
    )
    _, pages = parse_listing_page(html, page_url="https://chernomorie-bg.com/author/Chernomorie")
    assert pages == [
        "https://chernomorie-bg.com/author/Chernomorie/posts/2",
        "https://chernomorie-bg.com/author/Chernomorie/posts/4707",
    ]


def test_listing_date_to_iso_deterministic():
    assert (
        listing_date_to_iso("03.08.2009г. 20:46ч., обновена на 03.08.2009г. 20:49ч.")
        == "2009-08-03"
    )
    assert listing_date_to_iso("26.07.2009г. 21:28ч.") == "2009-07-26"
    assert listing_date_to_iso(None) is None
    assert listing_date_to_iso("no date here") is None


def test_band_and_author_class_helpers():
    assert band_for_date("2026-09-03") == "2024-2026"
    assert band_for_date("2021-05-01") == "2020-2023"
    assert band_for_date("2015-10-28") == "2015-2019"
    assert band_for_date("2009-08-03") == "2009-2014"
    assert band_for_date("2004-01-01") is None
    assert band_for_date(None) is None
    assert author_class("Черноморие-бг") == "house"
    assert author_class("Десислава Георгиева") == "named"
    assert author_class(None) == "unknown"


def _mk_rows() -> list[dict]:
    rows = []
    # 2024-2026 band: 4 candidates across 2024/2025/2026
    for i, (year, month) in enumerate([(2024, 3), (2025, 6), (2026, 1), (2026, 8)], start=1):
        rows.append(
            {
                "url": f"https://chernomorie-bg.com/post/recent-{i}-{9000 + i}",
                "date": f"01.{month:02d}.{year}г. 10:00ч.",
                "headline": f"Recent {i}",
                "author": "Черноморие-бг" if i % 2 else "Десислава Георгиева",
            }
        )
    # 2020-2023 band: single candidate (under-fill allowed)
    rows.append(
        {
            "url": "https://chernomorie-bg.com/post/mid-one-8001",
            "date": "05.05.2021г. 12:00ч.",
            "headline": "Mid one",
            "author": "Ина Димова",
        }
    )
    # 2009-2014 band: two candidates
    for i, year in enumerate([2009, 2012], start=1):
        rows.append(
            {
                "url": f"https://chernomorie-bg.com/post/old-{i}-{7000 + i}",
                "date": f"03.08.{year}г. 20:46ч.",
                "headline": f"Old {i}",
                "author": None,
            }
        )
    return rows


def test_sampling_deterministic_and_band_targets():
    targets = {"2024-2026": 3, "2020-2023": 1, "2009-2014": 2}
    first = stratified_selection(_mk_rows(), seed=20260913, band_targets=targets)
    second = stratified_selection(_mk_rows(), seed=20260913, band_targets=targets)
    assert [r["url"] for r in first] == [r["url"] for r in second]
    assert len(first) == 6
    urls = {r["url"] for r in first}
    assert any(u.endswith("-8001") for u in urls)
    recent = {int(u.rsplit("-", 1)[1]) for u in urls if "recent" in u}
    assert len(recent) == 3
    assert {7001, 7002} <= {int(u.rsplit("-", 1)[1]) for u in urls if "old" in u}


def test_sampling_year_round_robin_spread():
    # 40 candidates in 2026 + 1 in 2024: round-robin must surface the 2024 one
    rows = [
        {
            "url": f"https://chernomorie-bg.com/post/a-{i}-9100",
            "date": f"{(i % 28) + 1:02d}.01.2026г. 10:00ч.",
        }
        for i in range(40)
    ]
    rows.append({"url": "https://chernomorie-bg.com/post/b-9200", "date": "01.06.2024г. 10:00ч."})
    sel = stratified_selection(rows, seed=7, band_targets={"2024-2026": 10})
    years = {str(listing_date_to_iso(r["date"]))[:4] for r in sel}
    assert "2024" in years


def test_sampling_category_soft_cap_and_dedup():
    rows = []
    for i in range(10):
        rows.append(
            {
                "url": f"https://chernomorie-bg.com/post/cap-{i}-810{i}",
                "date": f"{i + 1:02d}.03.2026г. 10:00ч.",
                "categories": ("Спорт",) if i < 8 else ("Култура",),
            }
        )
    rows.append(dict(rows[0]))  # duplicate URL row must be dropped
    sel = stratified_selection(rows, seed=1, band_targets={"2024-2026": 9})
    from collections import Counter

    counts = Counter(c for r in sel for c in r.get("categories", ()))
    # soft cap: 30% of target 9 -> max 2 per category
    assert counts["Спорт"] <= 2
    assert counts["Култура"] <= 2
    assert len(sel) == 4
    assert len({r["url"] for r in sel}) == len(sel)


def test_sampling_respects_hard_cap():
    with pytest.raises(ValueError):
        stratified_selection(
            [{"url": "https://chernomorie-bg.com/post/x-1"}], total_target=MAX_ARTICLES + 1
        )


def test_selection_summary_shape():
    sel = stratified_selection(_mk_rows(), seed=3)
    summary = selection_summary(sel)
    assert summary["sampling_version"] == "m2.1b-sampling-1"
    assert summary["selected_count"] == len(sel)
    assert set(summary["band_counts"]) <= {
        "2024-2026",
        "2020-2023",
        "2015-2019",
        "2009-2014",
        "unk",
    }


def test_write_selected_jsonl_roundtrip(tmp_path):
    sel = stratified_selection(_mk_rows(), seed=5)
    path = write_selected_jsonl(sel, tmp_path / "selected_urls.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(sel)
    parsed = [json.loads(line) for line in lines]
    assert [p["url"] for p in parsed] == [r["url"] for r in sel]


def test_fetch_url_allow_list():
    assert is_allowed_article_url("https://chernomorie-bg.com/post/some-slug-5258")
    assert is_allowed_article_url("https://chernomorie-bg.com/post/-12-")
    assert not is_allowed_article_url("https://evil.example.com/post/x-1")
    assert not is_allowed_article_url("https://chernomorie-bg.com/posts/kultura")
    assert not is_allowed_article_url("https://chernomorie-bg.com/post/x-1?utm=1")
    assert not is_allowed_article_url("")


def test_collect_corpus_offline_quarantine_and_outputs(tmp_path, monkeypatch):
    import editor_assistant.style.fetch as fetch_mod

    article_html = _read("live_culture.html")

    def fake_fetch(url: str, *, delay=None):
        if url.endswith("-7085"):
            return article_html, None
        return None, f"HTTP 404: {url}"

    monkeypatch.setattr(fetch_mod, "fetch_article", fake_fetch)
    urls = [
        "https://chernomorie-bg.com/post/x-7085",
        "https://chernomorie-bg.com/post/gone-404",
    ]
    result = collect_corpus(urls, raw_dir=tmp_path / "raw")
    assert result["requested"] == 2
    assert result["fetched"] == 1
    assert result["failed"] == 1
    from editor_assistant.style.extract import extract_post_id, stable_article_id

    expected_snapshot = f"{stable_article_id(urls[0], extract_post_id(urls[0]))}.html"
    assert (tmp_path / "raw" / expected_snapshot).read_text(encoding="utf-8") == article_html
    articles = [
        json.loads(line)
        for line in (tmp_path / "articles.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(articles) == 1
    assert articles[0]["post_id"] == "7085"
    failures = [
        json.loads(line)
        for line in (tmp_path / "failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(failures) == 1
    assert failures[0]["failure_type"] == "FETCH"
    assert failures[0]["url"].endswith("-404")
    dups = json.loads((tmp_path / "duplicates.json").read_text(encoding="utf-8"))
    assert dups == {"by_url": [], "by_post_id": [], "by_body_hash": []}


def test_collect_corpus_rejects_disallowed_urls(tmp_path):
    result = collect_corpus(["https://evil.example.com/post/x-1"], raw_dir=tmp_path / "raw")
    assert result["fetched"] == 0
    assert result["failed"] == 1


# --- M2.1C corrective-step regressions --------------------------------------


def _minimal_page(canonical: str, headline: str, post_id_suffix: str) -> str:
    return (
        "<!DOCTYPE html><html><head>"
        f'<link rel="canonical" href="{canonical}">'
        f'<meta itemprop="datePublished" content="2026-09-03EEST17:38:00+02:00">'
        "</head><body>"
        '<div class="post-title-area"><h1 class="post-title">'
        f"{headline}</h1></div>"
        '<div class="entry-content"><p>Body text here.</p></div>'
        "</body></html>"
    )


def test_identity_is_url_based_not_post_id():
    """M2.1C #2: same post_id suffix must NOT yield the same article_id."""
    from editor_assistant.style.extract import extract_post_id, parse_article_html

    first = parse_article_html(
        _minimal_page(
            "https://chernomorie-bg.com/post/vav-varna-maratona-7720",
            "Маратонът във Варна",
            "7720",
        ),
        url="https://chernomorie-bg.com/post/vav-varna-maratona-7720",
    )
    second = parse_article_html(
        _minimal_page(
            "https://chernomorie-bg.com/post/epopeya-premiera-7720",
            "Епопея с премиера",
            "7720",
        ),
        url="https://chernomorie-bg.com/post/epopeya-premiera-7720",
    )
    assert extract_post_id(first.url) == "7720"
    assert extract_post_id(second.url) == "7720"
    assert first.post_id == "7720"
    assert second.post_id == "7720"
    assert first.article_id != second.article_id


def test_legacy_div_body_preserved_in_dom_order():
    """M2.1C #1: direct <div> content blocks inside entry-content are kept."""
    from editor_assistant.style.extract import parse_article_html

    record = parse_article_html(
        _read("legacy_div_body.html"),
        url="https://chernomorie-bg.com/post/ciklon-42",
    )
    paras = [p for p in (record.body or "").split("\n\n") if p.strip()]
    assert len(paras) == 3
    assert paras[0].startswith("Първи параграф")
    assert paras[1].startswith("Втори блок")
    assert paras[2].startswith("Трети блок")
    assert "продължава репортажа с резултатите" in paras[1]


def test_br_boundary_prevents_gluing():
    """M2.1C #4: <br> becomes a space boundary, never glues sentences."""
    from editor_assistant.style.extract import parse_article_html

    record = parse_article_html(
        _read("legacy_div_body.html"),
        url="https://chernomorie-bg.com/post/ciklon-42",
    )
    body = record.body or ""
    assert "приключва. Пътниците" in body
    assert "приключва.Пътниците" not in body


def test_subheadline_is_none_not_meta_description():
    """M2.1C #3: og:description/meta description is NOT a subheadline."""
    from editor_assistant.style.extract import parse_article_html

    record = parse_article_html(
        _read("legacy_div_body.html"),
        url="https://chernomorie-bg.com/post/ciklon-42",
    )
    assert record.subheadline is None
    assert "SEO описанието" not in (record.body or "")


def test_snapshot_files_unique_for_colliding_post_ids(tmp_path, monkeypatch):
    """M2.1C #2: colliding post_ids must not overwrite each other's snapshot."""
    import editor_assistant.style.fetch as fetch_mod
    from editor_assistant.style.fetch import collect_corpus

    article_html = _read("live_culture.html")
    monkeypatch.setattr(fetch_mod, "fetch_article", lambda url, *, delay=None: (article_html, None))
    urls = [
        "https://chernomorie-bg.com/post/maratona-900-dushi-7720",
        "https://chernomorie-bg.com/post/epopeya-premiera-septemvri-7720",
    ]
    result = collect_corpus(urls, raw_dir=tmp_path / "raw")
    assert result["fetched"] == 2
    files = sorted(p.name for p in (tmp_path / "raw").glob("*.html"))
    assert len(files) == 2
    assert files[0] != files[1]


def test_report_extended_manifest_and_qa(tmp_path):
    from editor_assistant.style.corpus import FailureRecord
    from editor_assistant.style.extract import parse_article_html
    from editor_assistant.style.report import (
        build_extended_manifest,
        build_qa_sample,
        check_record,
        write_manifest,
        write_qa_sample,
    )

    records = [
        parse_article_html(
            _read("live_culture.html"), url="https://chernomorie-bg.com/post/x-7085"
        ),
        parse_article_html(
            _read("live_old_no_author.html"), url="https://chernomorie-bg.com/post/m-bus-2"
        ),
        parse_article_html(_read("live_quote.html"), url="https://chernomorie-bg.com/post/q-3"),
    ]
    failures = [
        FailureRecord(
            url="https://chernomorie-bg.com/post/gone-1",
            failure_type="FETCH",
            failure_detail="HTTP 404",
            observed_at="2026-09-13T00:00:00+00:00",
        )
    ]
    extended = build_extended_manifest(records, failures)
    assert extended["article_count"] == 3
    assert extended["total_articles"] == 3
    assert extended["parse_failure_count"] == 1
    assert extended["parse_failure_types"] == {"FETCH": 1}
    assert set(extended["author_class_counts"]) == {"house", "named", "unknown"}
    assert extended["category_membership_count"] >= extended["article_count"]
    assert set(extended["band_counts"]) <= {
        "2024-2026",
        "2020-2023",
        "2015-2019",
        "2009-2014",
        "unk",
    }
    path = write_manifest(extended, tmp_path / "manifest.json")
    assert json.loads(path.read_text(encoding="utf-8"))["article_count"] == 3

    checks = check_record(records[0])
    assert checks["headline_present"] is True
    assert checks["body_present"] is True
    # fixture canonical URL is example.com, so the chernomorie check is False
    assert checks["url_valid"] is False
    assert checks["critical_errors"] == 1

    localized = _read("live_culture.html").replace(
        "https://example.com/post/x-7085", "https://chernomorie-bg.com/post/x-7085"
    )
    on_domain = check_record(
        parse_article_html(localized, url="https://chernomorie-bg.com/post/x-7085")
    )
    assert on_domain["url_valid"] is True
    assert on_domain["critical_errors"] == 0

    qa = build_qa_sample(records, size=2, spot_size=2, seed=1)
    assert qa["sample_size"] == 2
    assert qa["spot_check_count"] <= 2
    assert qa["total_critical_errors"] == sum(
        int(row["checks"]["critical_errors"]) for row in qa["qa_rows"]
    )
    qa_path = write_qa_sample(qa, tmp_path / "qa_sample.jsonl")
    lines = qa_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    # determinism
    again = build_qa_sample(records, size=2, spot_size=2, seed=1)
    assert [r["article_id"] for r in again["qa_rows"]] == [r["article_id"] for r in qa["qa_rows"]]
