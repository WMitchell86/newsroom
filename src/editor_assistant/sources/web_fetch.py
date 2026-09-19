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

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

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


def _is_private_host(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # unresolvable hosts are not fetchable targets
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def guard_target(url):
    """Reject non-HTTP(S) and localhost/private-network targets up front."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise WebFetchError(FETCH_BLOCKED_TARGET, f"scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host or host.lower() in ("localhost",) or host.endswith(".localhost"):
        raise WebFetchError(FETCH_BLOCKED_TARGET, f"host not allowed: {host!r}")
    if _is_private_host(host):
        raise WebFetchError(FETCH_BLOCKED_TARGET, "target resolves to a private/loopback address")


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
    guard_target(url)
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
    }
