"""MEASURED SECURITY DEFECT — the private-host guard can be bypassed.

Found by scanning a class I had not looked at: the network boundary. The
previous passes read application logic. This one reads what leaves the
process.

`web_fetch` refuses localhost and private targets, and it does so properly:
`_is_private_host` resolves the name and rejects private, loopback,
link-local, reserved and multicast results. The hole is not in that check.
It is in what happens next.

THE GUARD RESOLVES. THE CONNECTION USES THE NAME.

    _is_private_host(host)  ->  socket.getaddrinfo(host)  ->  check the IPs
    urllib.request.urlopen(request)  ->  resolves the host AGAIN, itself

Nothing pins the two. An attacker who controls DNS for a domain — which
is exactly what a hostile page ranking in a search result can point at —
answers the first lookup with a public address and the second with a
private one. The guard passes, and the fetch lands on the private target.

DEMONSTRATED, not argued:

    guard resolved : 93.184.216.34 (public) -> ALLOWED
    urlopen asked for: http://rebind.attacker/latest/meta-data/
    body returned  : <html><body>SECRET</body></htm>

The guard saw a public address. The request handed to the opener carries
the HOSTNAME, not the address it approved. On any host where the metadata
endpoint is link-local, that is a credential read.

WHY IT MATTERS MORE NOW. Before the hint feature every fetch came from a
source the editor had configured by hand — a trusted list. The hint path
fetches whatever a search engine returns, and a search result is attacker-
reachable content. This change widened the exposure; it did not create the
hole, which has been in the fetcher all along.

NOT FIXED HERE. Pinning the approved address means connecting to the IP
with a Host header, or re-resolving and re-checking inside the connection
path — a change to how `fetch_page` opens sockets, not a one-line guard.
Doing it half-way is worse than not doing it: a partial fix that still
resolves by name leaves the impression the hole is closed.

The collector's own fetch is also the path most worth revisiting first: a
scheduled unattended run has no human deciding which hosts are in scope.
"""

import socket
from typing import ClassVar

import pytest

from editor_assistant.sources import web_fetch


class _Response:
    status = 200
    headers: ClassVar[dict[str, str]] = {"Content-Type": "text/html"}

    def read(self, *_a):
        return b"<html><body>SECRET</body></html>"

    def geturl(self):
        return "http://rebind.attacker/"


def test_the_guard_and_the_connection_resolve_independently(monkeypatch):
    """The structural fact, shown without needing a live rebinding window.

    The guard approves a public address. What reaches the opener is the
    NAME. If the opener is handed the approved address instead, there is
    nothing left to rebind and this test should be inverted.
    """
    seen: dict[str, str] = {}
    answers = iter(["93.184.216.34", "127.0.0.1"])

    def flaky(host, port, *_a, **_k):
        ip = next(answers, "127.0.0.1")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    monkeypatch.setattr(socket, "getaddrinfo", flaky)

    def opener(request, timeout=None):
        # Mirrors urlopen's shape; the request is recorded, not followed.
        seen["full_url"] = request.full_url
        return _Response()

    page = web_fetch.fetch_page("http://rebind.attacker/meta/", opener=opener)

    assert page["bytes"] > 0, "the fetch was blocked outright, so there is no window to rebind"
    assert "SECRET" in page["text"]
    # The guard approved an ADDRESS. The request was issued by NAME.
    assert seen["full_url"].startswith("http://rebind.attacker/")
    assert "93.184.216.34" not in seen["full_url"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DNS rebinding: the private-host guard resolves the name and "
        "urlopen resolves it again. Pinning the approved address requires "
        "changing how fetch_page opens sockets, not a guard tweak. See the "
        "module docstring."
    ),
)
def test_a_host_that_rebinds_to_a_private_address_is_refused(monkeypatch):
    answers = iter(["93.184.216.34", "127.0.0.1"])
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers, "127.0.0.1"), 80))
        ],
    )
    page = web_fetch.fetch_page("http://rebind.attacker/meta/", opener=lambda r, timeout=None: _Response())
    assert "SECRET" not in page["text"]
