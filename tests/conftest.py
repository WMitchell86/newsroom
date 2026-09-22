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
import socket
from collections.abc import Iterator

import pytest

from editor_assistant.sources import web_fetch

#: Deterministic public IP used for every resolvable test hostname.
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
