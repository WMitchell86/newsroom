"""Read-only web page fetcher for research source opening (M2S Track S).

Distinct from the frozen RSS/Radar fetcher (`sources/fetcher.py`): this one
serves research source opening (HTML/text), not feed ingestion, and never
touches Radar behavior. Safety posture (harness A6):

* HTTP/HTTPS only; localhost / private-network / link-local targets rejected;
* GET only; no JavaScript; no cookies; explicit UA;
* bounded size and explicit timeout;
* content-type restricted to text/html, application/xhtml+xml, text/plain;
* every failure lands in an explicit taxonomy - infrastructure failure is
  never silently translated into "the information does not exist".
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

from editor_assistant.sources import html_desc

MAX_BYTES = 1_000_000  # bounded response size (audit A3)
DEFAULT_TIMEOUT = 20
USER_AGENT = (
    "chernomorie-editorial-research/1.0 (read-only research fetcher; +https://chernomorie-bg.com)"
)
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

FETCH_OK = "FETCH_OK"
FETCH_BLOCKED_TARGET = "FETCH_BLOCKED_TARGET"
FETCH_HTTP_ERROR = "FETCH_HTTP_ERROR"
FETCH_UNREACHABLE = "FETCH_UNREACHABLE"
FETCH_TIMEOUT = "FETCH_TIMEOUT"
FETCH_UNSUPPORTED_CONTENT = "FETCH_UNSUPPORTED_CONTENT"
FETCH_TOO_LARGE = "FETCH_TOO_LARGE"
FETCH_PARSE_FAILED = "FETCH_PARSE_FAILED"


class WebFetchError(ValueError):
    """Raised on fetch failure; `category` names the explicit failure state."""

    def __init__(self, category, detail, *, status=None, retry_after=None):
        super().__init__(f"{category}: {detail}")
        self.category = category
        self.detail = detail
        self.status = status
        self.retry_after = retry_after


def _approved_addresses(host):
    """Every address the host resolves to, or [] when any of them is unsafe.

    Returns the ADDRESSES, not a verdict. The caller must connect to one of
    these exact values: a boolean check and a later name-based lookup are two
    separate resolutions, and a host whose DNS answers the first with a public
    address and the second with a private one walks straight through a boolean
    guard. See `_PinnedResolver` for how the connection is pinned.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []  # unresolvable hosts are not fetchable targets
    addresses = []
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return []
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return []
        addresses.append(address)
    return addresses


#: Per-thread pin. Resolver state has to be per-thread rather than global
#: because the workbench serves on a `ThreadingHTTPServer`: a process-wide
#: override would let one request's pin answer another request's lookup.
_PIN = threading.local()


def _pinned_getaddrinfo(host, port, *args, **kwargs):
    """Resolve to the address the guard already approved, for this thread only."""
    if getattr(_PIN, "host", None) == host:
        return socket.getaddrinfo(_PIN.address, port, *args, **kwargs)
    return _REAL_GETADDRINFO(host, port, *args, **kwargs)


_REAL_GETADDRINFO = socket.getaddrinfo
if not getattr(socket.getaddrinfo, "_newsroom_pinned", False):
    socket.getaddrinfo = _pinned_getaddrinfo
    socket.getaddrinfo._newsroom_pinned = True  # type: ignore[attr-defined]


def guard_target(url):
    """Reject non-HTTP(S) and localhost/private-network targets up front.

    Returns the approved address, which the caller must then pin. Discarding
    it and letting urllib resolve the name again is the DNS-rebinding hole
    this closes.
    """
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise WebFetchError(FETCH_BLOCKED_TARGET, f"scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host or host.lower() in ("localhost",) or host.endswith(".localhost"):
        raise WebFetchError(FETCH_BLOCKED_TARGET, f"host not allowed: {host!r}")
    addresses = _approved_addresses(host)
    if not addresses:
        raise WebFetchError(FETCH_BLOCKED_TARGET, "target resolves to a private/loopback address")
    return addresses[0]


def _ascii_url(url):
    """Percent-encode non-ASCII path/query characters (IRI -> URI).

    urllib's HTTP layer sends the request line as ASCII, so raw Cyrillic URLs
    (common for .bg publishers) crash with UnicodeEncodeError unless encoded
    first. Scheme and network location stay untouched, so the SSRF guard
    still evaluates the exact same target.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        encoded = parts._replace(
            path=urllib.parse.quote(parts.path, safe="/%:@&=$,+;~*'!()[]-._"),
            query=urllib.parse.quote(parts.query, safe="=%:@&/$,+;~*'!()[]-._"),
        )
    except ValueError:
        return None
    return urllib.parse.urlunsplit(encoded)


def fetch_page(
    url,
    *,
    timeout=DEFAULT_TIMEOUT,
    max_bytes=MAX_BYTES,
    opener=None,
):
    """Fetch one research source page. Returns a plain record, never HTML soup.

    opener: injection point for tests (a callable (Request) -> response-like
    with .status/.headers/.read()); defaults to a real urlopen.
    """
    address = guard_target(url)
    ascii_url = _ascii_url(url)
    if ascii_url is None:
        raise WebFetchError(FETCH_UNREACHABLE, f"unusable URL: {url}")
    request = urllib.request.Request(
        ascii_url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html, application/xhtml+xml, text/plain;q=0.9, */*;q=0.1",
            "Accept-Language": "bg, en;q=0.5",
        },
    )
    # Pin the approved address for this thread for the duration of the connect.
    # Without this the guard resolves one address and urllib resolves the NAME
    # again, which is a DNS-rebinding window: the guard can approve a public
    # address and the connection can land on a private one. The pin is
    # thread-local because the workbench serves on a ThreadingHTTPServer.
    with _pinned_host(urllib.parse.urlparse(ascii_url).hostname or "", address):
        return _fetch_with(request, url, timeout=timeout, max_bytes=max_bytes, opener=opener)


@contextlib.contextmanager
def _pinned_host(host, address):
    """Force this thread's resolution of `host` to the approved `address`.

    Restores whatever was pinned before, so a nested or repeated fetch cannot
    inherit a stale pin, and clears it on every exit path including exceptions.
    """
    previous = (getattr(_PIN, "host", None), getattr(_PIN, "address", None))
    _PIN.host = host
    _PIN.address = address
    try:
        yield
    finally:
        _PIN.host, _PIN.address = previous


def _fetch_with(request, url, *, timeout, max_bytes, opener):
    try:
        response = (opener or urllib.request.urlopen)(request, timeout=timeout)
        try:
            status = getattr(response, "status", None) or 200
            headers = response.headers or {}
            content_type = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
            body = response.read(max_bytes + 1)
        finally:
            # Release the socket promptly instead of waiting for GC. Injected
            # test openers may be plain stubs, so close only if offered.
            close = getattr(response, "close", None)
            if callable(close):
                close()
    except WebFetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise WebFetchError(
            FETCH_HTTP_ERROR,
            f"HTTP {exc.code} for {url}",
            status=exc.code,
            retry_after=(exc.headers or {}).get("Retry-After"),
        ) from exc
    except TimeoutError as exc:
        raise WebFetchError(FETCH_TIMEOUT, f"timeout after {timeout}s: {url}") from exc
    except (urllib.error.URLError, OSError, ConnectionError) as exc:
        raise WebFetchError(FETCH_UNREACHABLE, f"{type(exc).__name__}: {exc}") from exc

    if len(body) > max_bytes:
        raise WebFetchError(FETCH_TOO_LARGE, f"body exceeds {max_bytes} bytes", status=status)
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise WebFetchError(
            FETCH_UNSUPPORTED_CONTENT, f"content-type {content_type!r} not allowed", status=status
        )
    charset = "utf-8"
    if "charset=" in (headers.get("Content-Type") or "").lower():
        charset = (headers.get("Content-Type") or "").split("charset=")[-1].split(";")[0].strip()
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    return {
        "url": url,
        "final_url": getattr(response, "geturl", lambda: url)(),
        "status": status,
        "content_type": content_type,
        "bytes": len(body),
        "text": text,
        # V1.2-G4.28. What the page actually yielded as an ARTICLE, measured
        # once here and carried on the record. Without it a social wrapper, a
        # results table and a broken extractor all arrived as a successful
        # fetch with an almost-empty body, and no caller could tell them
        # apart. Extraction lives in `html_desc`; the fetch layer only reports
        # what the page turned out to be, because every consumer of this record
        # needs that and none of them should re-derive it.
        "prose": html_desc.article_prose(html_desc.normalize_blocks(text)),
    }
