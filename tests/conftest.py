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
    """Route every `socket.getaddrinfo` call through the deterministic resolver."""
    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", make_test_resolver)
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
