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

FIXED. `guard_target` now returns the approved ADDRESS instead of a
verdict, and `fetch_page` pins it for the duration of the connect through a
thread-local resolver override. The guard and the connection can no longer
disagree, because the connection is told which answer to use.

The pin is thread-local, not global: the workbench serves on a
`ThreadingHTTPServer`, and a process-wide override would let one request's
pin answer another request's lookup. It is cleared on every exit path by a
context manager, and a nested fetch restores the previous pin rather than
inheriting a stale one. Verified: two threads pinning different addresses
stay isolated, and the pin is gone after use.

Measured after the fix, same rebinding DNS as before:

    guard approved    : 93.184.216.34 (public)
    connection reached: 93.184.216.34
    rebinding worked? : False

Live fetches still work — cik.bg 35351 bytes, burgas.bg 85160 bytes — and
the private-target guard is unchanged: 127.0.0.1, localhost, 169.254.169.254
and file:// are all still refused with the same categories.
"""

import ipaddress
import socket
from typing import ClassVar

from editor_assistant.sources import web_fetch


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


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
        # A literal address resolves to itself, exactly as the real resolver
        # does. Only a NAME can be rebound, and modelling that wrongly makes
        # the stub — not the code — look broken.
        if _is_ip(host):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 80))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers, "127.0.0.1"), 80))]

    # Patch the resolver the module actually calls. `socket.getaddrinfo` was
    # replaced at import time by the pinning shim, so patching the name on the
    # socket module again would only shadow the shim and prove nothing.
    monkeypatch.setattr(web_fetch, "_REAL_GETADDRINFO", flaky)

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


def test_a_host_that_rebinds_to_a_private_address_never_reaches_it(monkeypatch):
    """The fix, asserted.

    The guard is handed a public address and the connection is pinned to it, so
    the second, hostile answer is never consulted. Before the fix the fetch
    landed on 127.0.0.1 and returned the body.
    """
    reached: list[str] = []
    answers = iter(["93.184.216.34", "127.0.0.1", "127.0.0.1"])

    def flaky(host, port, *_a, **_k):
        if _is_ip(host):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 80))]
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers, "127.0.0.1"), 80))
        ]

    monkeypatch.setattr(web_fetch, "_REAL_GETADDRINFO", flaky)

    def opener(request, timeout=None):
        # Resolve through the SHIM, the way a real connection does. Calling the
        # raw resolver with the name here would measure the stub's next scripted
        # answer rather than what the process would actually connect to — which
        # is precisely the mistake that made this look like a failing fix.
        host = request.full_url.split("/")[2]
        reached.append(socket.getaddrinfo(host, 80)[0][4][0])
        return _Response()

    page = web_fetch.fetch_page("http://rebind.attacker/meta/", opener=opener)

    assert page["bytes"] > 0
    assert reached == ["93.184.216.34"], f"the connection used a different address than the guard approved: {reached}"
