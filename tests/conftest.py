"""Shared offline test fixtures.

Hermetic network isolation (harness M3A A2): the production SSRF guard
(`sources/web_fetch._is_private_host`) resolves hostnames with real
`socket.getaddrinfo`. In a DNS-isolated environment that raises for public
fixture hostnames, so mocked-HTTP tests fail *before* reaching the mock with
`FETCH_BLOCKED_TARGET`. That is test-hygiene debt, not a production bug.

This module installs an explicit, deterministic test resolver for the duration
of every test:

* a fixed set of public fixture hostnames maps to a known public IP;
* IP literals resolve to themselves, so private/loopback rejection stays real;
* any hostname outside the set fails closed with `socket.gaierror`, exactly as
  the production guard treats unresolvable hosts.

The production guard is NOT disabled or weakened: its own code path runs
unchanged against this resolver.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections import OrderedDict
from collections.abc import Iterator

import pytest

from editor_assistant.sources import web_fetch

#: Deterministic public IP used for every resolvable test hostname.
#:
#: It MUST be a genuinely public address, and that is a constraint worth
#: recording because a well-meant change to it was tried and reverted.
#: `web_fetch` carries an SSRF guard that refuses any target resolving to a
#: private address, and Python's `ipaddress` counts every RFC 5737
#: documentation range (192.0.2/24, 198.51.100/24, 203.0.113/24) as private.
#: Substituting one of them made nine fetch and TinyFish tests fail with
#: "target resolves to a private/loopback address" - correctly, from the
#: guard's point of view.
#:
#: There is no "public but unroutable" IPv4 range, so this value cannot be made
#: to fail fast. The real cost is that a test performing a genuine HTTP call
#: waits out the socket timeout: `tests/test_draft_readiness_parity.py` measures
#: 961 s for 19 cases, because `_draft_snapshot` opens the Story's own
#: publication. Fixing that belongs in that test - substitute the publication
#: read, as `_no_automatic_draft_enrichment` already does for enrichment - and
#: NOT here, where the address is a security-relevant input.
#:
#: V1.2-G4.34 — the 961 s number above was attributed to the WRONG fetch, and the
#: note was itself part of the problem because it told the next reader where NOT
#: to look. Measured by severing the two seams: with `_keyless_lookup` and
#: `_news_lookup` replaced, the whole file runs in **0.30 s instead of 391 s**, same
#: 5 failures. The read of the Story's own publication was never the cost; it fails
#: fast through the resolver below. The cost is the RESOLVER CASCADE — a live
#: `DDGSProvider().search` plus a raw `urlopen` of news.google.com, run twice per
#: snapshot, at 12-20 s each.
#:
#: Both bypass `web_fetch`, so both also bypass the hermetic resolver: the shim
#: patches `web_fetch._REAL_GETADDRINFO`, not `socket` globally. That is why this
#: suite reaches the real internet while every other one does not.
#:
#: The real defect is still in `publication_material` — `_news_lookup` has no SSRF
#: guard and no test seam — and it is NOT fixed here. This fixture only stops the
#: harness from making live calls it did not intend to make.
TEST_PUBLIC_IP = "93.184.216.34"

#: Test-only hostnames that must resolve to a public address. Suffixes cover the
#: `.example` documentation family (`evil.example.com`, `other.example.org`, ...).
_TEST_PUBLIC_HOSTS = frozenset(
    {
        "example.org",
        "example.com",
        "example.net",
        "example.bg",
        "a.bg",
        "bta.bg",
        "www.bta.bg",
        "burgas.bg",
        "www.burgas.bg",
        "burgascouncil.org",
        "bg.wikipedia.org",
        "news.google.com",
        "chernomorie-bg.com",
    }
)

_TEST_PUBLIC_SUFFIXES = (".example", ".example.com", ".example.org", ".example.net")


def is_public_test_host(host: str) -> bool:
    host = (host or "").lower()
    if host in _TEST_PUBLIC_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _TEST_PUBLIC_SUFFIXES)


def make_test_resolver(host, port=None, family=0, type=0, proto=0, flags=0):
    """Deterministic getaddrinfo stand-in: public fixture map + IP literals.

    Anything else raises `socket.gaierror`, matching the fail-closed behavior of
    the production guard for unresolvable hosts.
    """
    port = port or 0
    if is_public_test_host(host):
        address = TEST_PUBLIC_IP
    else:
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None
    socktype = type or socket.SOCK_STREAM
    if family == socket.AF_INET6:
        return [(socket.AF_INET6, socktype, socket.IPPROTO_TCP, "", (address, port, 0, 0))]
    return [(socket.AF_INET, socktype, socket.IPPROTO_TCP, "", (address, port))]


@pytest.fixture(autouse=True)
def _hermetic_dns(monkeypatch) -> Iterator[None]:
    """Route every `socket.getaddrinfo` call through the deterministic resolver.

    V1.2-G4.22. This patched `web_fetch.socket.getaddrinfo`, which is the name
    the pinning shim REPLACES at import. Patching it again put the hermetic
    resolver ahead of the shim, so `web_fetch`'s DNS-rebinding pin was silently
    out of the chain in every single test — the security behaviour could not be
    exercised at all, and a test asserting either outcome would have been
    asserting the fixture instead of the code.

    Patching `_REAL_GETADDRINFO` keeps the shim installed and puts the
    deterministic resolver exactly where the shim delegates to, which is what
    the fixture meant in the first place.
    """
    monkeypatch.setattr(web_fetch, "_REAL_GETADDRINFO", make_test_resolver)
    yield


@pytest.fixture(autouse=True, scope="session")
def _isolated_editorial_workflow(tmp_path_factory) -> Iterator[None]:
    """Keep the Article store out of the operator's, for the WHOLE run.

    V1.2-G4.5. Found by running the real app, not by a test: `GET /api/v1/today`
    answered 500 because one Article record referenced a Story that no longer
    existed — and that record was written by the test suite.
    `editor_article_store.editor_articles_path` honours
    `WB_EDITORIAL_WORKFLOW_DIR` and otherwise writes to `var/editorial_workflow`,
    which no fixture here set. Every test that touched an Article without its own
    `newsroom` fixture therefore wrote into the live store.

    Session scope, for the same reason as the ledger override: a fixture that
    releases its env var at teardown is undone by a straggler, and the fix that
    has to hold for the whole process is the one with no teardown at all.
    """
    scratch = tmp_path_factory.mktemp("editorial-workflow")
    os.environ["WB_EDITORIAL_WORKFLOW_DIR"] = str(scratch)
    yield
    os.environ.pop("WB_EDITORIAL_WORKFLOW_DIR", None)


@pytest.fixture(autouse=True)
def _isolated_model_state(tmp_path, monkeypatch) -> Iterator[None]:
    """Keep model routing hermetic (M4D model policy).

    A test must never write the operator's real `var/model_usage/`,
    `var/model_health.json` or `var/model_policy.json`: the usage ledger feeds
    budgets and per-model daily limits, so a polluted ledger would make a later
    test skip a route it expects to call.
    """
    monkeypatch.setenv("MODEL_USAGE_DIR", str(tmp_path / "model_usage"))
    monkeypatch.setenv("MODEL_HEALTH_PATH", str(tmp_path / "model_health.json"))
    monkeypatch.setenv("MODEL_POLICY_PATH", str(tmp_path / "model_policy.json"))
    yield


@pytest.fixture(autouse=True)
def _isolated_operation_registry(monkeypatch) -> Iterator[None]:
    """Start every test with an empty operation registry and in-flight guard.

    Both are process-global on purpose - that is what lets a Today row say
    "a Draft for this Story is already being prepared" (V1.2-G4.6) - which also
    means a test that runs a Quick Draft leaves a row behind, and the next test
    in the same process reads the previous test's outcome as if it were its own.
    The first measured symptom was a Today DTO assertion that passed alone and
    failed in the full file, because an earlier test's failed Quick Draft was
    still remembered for the same Story.
    """
    from editor_assistant.workflow import quick_draft, story_operations

    monkeypatch.setattr(story_operations, "_ROWS", OrderedDict())
    monkeypatch.setattr(quick_draft, "_ACTIVE", {})
    yield


@pytest.fixture(autouse=True, scope="session")
def _hermetic_operation_ledger(tmp_path_factory) -> Iterator[None]:
    """Keep the operation ledger out of the operator's real history (V1.2-G4.6).

    `story_operations` mirrors every operation row to `var/operations.json` so a
    restart cannot erase the record of a Draft that was asked for. That file is
    the operator's real history, and any test that started an operation used to
    overwrite it. The file was found with zero rows.

    The scope is the whole point, and a per-test override was tried first and
    did not work. Operation workers are DAEMON THREADS and `_write_ledger`
    resolves its path at CALL time, so a worker still in flight when a test
    ended had the per-test override undone by monkeypatch teardown, and the
    straggler then mirrored that test's empty registry into the live file.
    Draining at teardown was the second attempt and is worse: plenty of tests
    deliberately start an operation and do not wait for it, so a drain turns
    correct tests into 10-second timeouts and fixture errors.

    A session-wide override has no teardown at all. It is set once and holds
    until the process exits, so a straggler from the last test of the run still
    writes into the temporary directory. Nothing has to be waited for, and the
    operator's history is unreachable for the entire run.
    """
    scratch = tmp_path_factory.mktemp("operation-ledger")
    os.environ["WB_OPERATIONS_LEDGER_PATH"] = str(scratch / "operations.json")
    yield
    os.environ.pop("WB_OPERATIONS_LEDGER_PATH", None)


@pytest.fixture(autouse=True)
def _no_automatic_draft_enrichment(monkeypatch) -> Iterator[None]:
    """Keep the V1.2-G4.3 automatic draft enrichment out of every test by default.

    `Чернова` now runs a bounded enrichment round internally, which reaches the
    real search provider. Without this, every test that presses `Чернова` would
    make a live network call - which breaks the harness rule that tests never
    touch the network, and turns a 0.4 s test into an 87 s one waiting on a
    provider that is not part of what is being tested.

    The switch is OFF in tests and ON in production, so the production path is
    the default and the tests are the exception - never the other way round.
    `tests/test_natural_draft_loop.py` opts back IN and controls the search
    transport explicitly, which is where the enrichment contract is actually
    asserted.
    """
    monkeypatch.setenv("NEWSROOM_DRAFT_ENRICHMENT", "off")
    yield


# ----------------------------------------------------------------------
# Shared test seam: make a Story's own publication unreadable.
#
# V1.2-G4.32. This existed as two functions of the same name in two files, and
# they did NOT do the same thing:
#
#   test_manual_continuation  took an UNUSED `story_id`, resolved the path
#                             through `app._paths()`, and rewrote only rows
#                             whose source_item_id is "origin" or whose url
#                             mentions "vestnik".
#   test_article_draft_command took a `root`, and rewrote EVERY row.
#
# One name, one intent, two behaviours — so a reader who saw the helper in one
# file and assumed the other did the same would be wrong, and one of them
# reached further than it looked. The comment in the copy even claimed "same
# seam and same reason as the helper in test_manual_continuation.py".
#
# Why the seam exists at all: since V1.2-G4.3 §A a Story whose publication CAN
# be read is always worth a Draft — the command reads that page on the way
# there — so "never opened" no longer makes a refusal reachable. A test that
# means to exercise a REFUSAL has to arrange something genuinely unreadable.
#
# The matcher is the CALLER's, because the two suites genuinely select
# different rows. A shared helper that guessed was tried and broke five tests,
# which is how this ended up parameterised rather than narrowed.


@pytest.fixture
def unreadable_publication():
    """Call as `unreadable_publication(matcher, path)`; returns the rows changed.

    A fixture rather than a shared module function because a test module cannot
    `import conftest` — that was measured, not assumed. Returns the number of
    rows rewritten so a test can assert the arrangement actually happened,
    rather than discovering later that it silently matched nothing.
    """

    def _apply(matcher, inbox_path):
        from editor_assistant.workflow import inbox_store

        items = inbox_store.read_items(inbox_path)
        changed = 0
        for row in items:
            if matcher(row):
                row["url"] = "https://www.facebook.com/somepage/posts/1"
                changed += 1
        if changed:
            inbox_store.save_items(items, inbox_path)
        return changed

    return _apply


# ----------------------------------------------------------------------
# Containing the browser suite's session-scoped boundary substitutes.
#
# V1.2-G4.32. `tests/browser/conftest.py::boundary_substitutes` is
# `scope="session"` and replaces the three outbound edges IN PLACE on the
# imported modules: `search.provider_chain`, `web_fetch.fetch_page`,
# `fetcher.fetch_bytes`, `newsroom_run._now` and the two drafting transports.
# It is a session fixture because the server it feeds is one, and a fresh
# server per test would be a different suite.
#
# The cost is that those patches outlive the server. Session fixtures tear
# down at the end of the SESSION, not at the end of the browser suite, and
# pytest collects `tests/browser/` BEFORE `tests/test_*.py`, so the real
# modules stayed substituted for every non-browser test that ran after it.
#
# Measured, both directions, on unmodified code:
#
#   tests/test_search_foundation.py alone                 30 passed
#   tests/test_search_foundation.py, then browser/        40 passed
#   tests/browser/, then tests/test_search_foundation.py   5 failed, 35 passed
#
# The failures were not about search. `provider_chain` returned a provider
# named "d2a_deterministic", so tests asserting the real chain's first rung
# failed with a message that named the substitute, and the browser fixture
# data leaked into files that never asked for it. A 53-failure full-suite run
# was mostly this one ordering effect.
#
# Restoring per test is wrong: the server needs the patch for its lifetime.
# What is restored is the boundary BETWEEN the two suites, so each non-browser
# test observes the real modules regardless of collection order.

_REAL_BOUNDARY_ATTRS = (
    ("editor_assistant.sources.web_fetch", "fetch_page"),
    ("editor_assistant.sources.fetcher", "fetch_bytes"),
    ("editor_assistant.workflow.search", "provider_chain"),
    ("editor_assistant.workflow.newsroom_run", "_now"),
    ("editor_assistant.drafting.generate", "_call_gemini"),
    ("editor_assistant.drafting.generate", "_call_openrouter"),
)


def _capture_pristine_boundary() -> dict:
    """The real boundary callables, captured before any browser fixture runs.

    Captured HERE, at conftest import, and not lazily on first use. The lazy
    version was wrong and was measured to be wrong: this fixture's first
    non-browser test runs AFTER the browser suite has already substituted
    these attributes, so a lazy capture records the substitutes as "pristine"
    and restores the leak it was written to remove. `tests/conftest.py` is
    imported before any `tests/browser/` fixture executes, which is the only
    moment at which the real values are observable.
    """
    import importlib

    return {
        (module_name, attr): getattr(importlib.import_module(module_name), attr)
        for module_name, attr in _REAL_BOUNDARY_ATTRS
    }


_PRISTINE_BOUNDARY: dict = _capture_pristine_boundary()


@pytest.fixture(autouse=True)
def real_boundaries_outside_browser(request):
    """Non-browser tests get the real boundary, whatever ran before them."""
    if "browser" in request.node.path.parts:
        yield
        return
    import importlib

    modules = {name: importlib.import_module(name) for name, _ in _REAL_BOUNDARY_ATTRS}
    for (module_name, attr), original in _PRISTINE_BOUNDARY.items():
        setattr(modules[module_name], attr, original)
    yield


@pytest.fixture(autouse=True)
def no_live_publication_url_resolution(monkeypatch):
    """Keep the publication-URL resolver cascade out of every test.

    V1.2-G4.34. `_draft_snapshot` resolves candidate publication URLs twice, and
    each resolution went to the real internet: `_keyless_lookup` runs a live
    `DDGSProvider().search`, and `_news_lookup` opens `news.google.com` with a raw
    `urllib.request.urlopen` that bypasses `web_fetch` entirely. Neither is covered
    by the hermetic resolver, which patches `web_fetch._REAL_GETADDRINFO` and so
    does not apply to either call.

    Measured: the parity file took 391.54s unmodified and **0.30s** with these two
    seams severed, with the same 5 failures either way. The suite was spending
    thirteen minutes making network calls it was not testing.

    This is the same shape as `_no_automatic_draft_enrichment` above: substitute
    the transport, keep the product code path real. Nothing about the seam the
    tests actually exercise is removed — a test that wants the resolver to find
    something overrides these.

    The product defect this exposed is NOT fixed here: `_news_lookup` performs a
    real fetch with no SSRF guard and no seam, while every other outbound edge in
    this codebase goes through `web_fetch`. That belongs in
    `publication_material`, and it is recorded in the review prompt rather than
    silently patched in a conftest.
    """
    from editor_assistant.workflow import publication_material

    monkeypatch.setattr(publication_material, "_keyless_lookup", lambda *a, **k: [])
    monkeypatch.setattr(publication_material, "_news_lookup", lambda *a, **k: [])
