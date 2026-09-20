"""M4A.1 blocked-domain policy tests (offline).

The policy is editor-owned configuration with a strict value shape: a stored value
is a domain, never a page. These tests pin canonicalization, refusal of malformed
input, suffix matching, and the two collection refusal paths.
"""

from __future__ import annotations

import pytest

from editor_assistant.workflow import blocked_domains as B


@pytest.fixture
def store(tmp_path):
    return tmp_path / "blocked.json"


def test_canonicalization_normalizes_scheme_www_case_and_trailing(store):
    assert B.canonical_host("flagman.bg") == "flagman.bg"
    assert B.canonical_host("WWW.FlagMan.BG") == "flagman.bg"
    assert B.canonical_host("https://flagman.bg") == "flagman.bg"
    assert B.canonical_host("https://www.flagman.bg/") == "flagman.bg"
    assert B.canonical_host("http://m.flagman.bg") == "m.flagman.bg"


@pytest.mark.parametrize(
    "bad",
    (
        "https://flagman.bg/2026/09/article",
        "https://flagman.bg/?q=1",
        "flagman.bg:8080",
        "ftp://flagman.bg",
        "not a domain",
        "localhost",
        "",
    ),
)
def test_malformed_or_page_values_are_refused(bad):
    with pytest.raises(B.BlockedDomainError):
        B.canonical_host(bad)


def test_add_remove_and_seed_are_deterministic(store):
    # A fresh install has the default policy in force but no store on disk.
    assert B.read_domains(store) == []
    assert B.effective_domains(store) == ["flagman.bg"]
    assert not store.exists()

    assert B.add_domain("flagman.bg", path=store)["added"] is False  # already default
    result = B.add_domain("noise.example", path=store)
    assert result["added"] is True
    # the first edit materializes the effective set (default + new)
    assert B.read_domains(store) == ["flagman.bg", "noise.example"]

    with pytest.raises(B.BlockedDomainError):
        B.remove_domain("absent.example", path=store)
    B.remove_domain("noise.example", path=store)
    assert B.read_domains(store) == ["flagman.bg"]

    # an editor CAN remove even the default once the policy is materialized
    B.remove_domain("flagman.bg", path=store)
    assert B.effective_domains(store) == []

    seeded = B.seed_defaults(path=store)
    assert "flagman.bg" in seeded["domains"]


def test_a_bad_value_never_touches_the_store(store):
    B.add_domain("noise.example", path=store)  # materializes the policy
    before = store.read_text(encoding="utf-8")
    with pytest.raises(B.BlockedDomainError):
        B.add_domain("https://flagman.bg/2026/09/x", path=store)
    assert store.read_text(encoding="utf-8") == before


def test_suffix_matching_covers_subdomains(store):
    B.add_domain("flagman.bg", path=store)
    assert B.is_blocked("https://flagman.bg/x", path=store)
    assert B.is_blocked("https://m.flagman.bg/x", path=store)
    assert not B.is_blocked("https://notflagman.bg/x", path=store)
    assert not B.is_blocked("https://flagman.bg.example/x", path=store)


def test_blocked_reason_flags_direct_sources_and_queries(store):
    B.add_domain("flagman.bg", path=store)
    assert B.blocked_reason({"url": "https://flagman.bg/rss"}, path=store)
    assert B.blocked_reason({"query": "flagman.bg Бургас"}, path=store)
    assert B.blocked_reason({"url": "https://other.example/rss"}, path=store) is None
    assert B.blocked_reason({"query": "Бургас"}, path=store) is None


def test_an_unreadable_store_raises_instead_of_looking_empty(store):
    store.write_text("{not json", encoding="utf-8")
    with pytest.raises(B.BlockedDomainError):
        B.read_domains(store)
