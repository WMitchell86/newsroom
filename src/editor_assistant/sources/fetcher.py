"""M1.2 HTTP fetcher — stdlib urllib only, read-only, no retries/scheduling.

Boundary: network lives here; parsing stays pure in sources/rss.py.
fetch_bytes(url) -> FetchedResponse(status, content_type, payload).
Any network/HTTP/size/content problem raises FetchError — never an empty list.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "editor-assistant-m12/0.1 (+local verification; read-only RSS fetch)"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MAX_BYTES = 512 * 1024  # 512 KiB: generous for RSS, blocks huge downloads
_READ_CHUNK = 16 * 1024


class FetchError(RuntimeError):
    """Raised for any fetch failure: timeout, DNS, HTTP error, size, content."""


@dataclass(frozen=True)
class FetchedResponse:
    final_url: str
    status: int
    content_type: str | None
    payload: bytes


def _check_redirect_chain(start_host: str, final_url: str) -> None:
    """Accept same-site redirects; block hops to unrelated hosts."""
    end_host = (urlparse(final_url).hostname or "").lower()
    if end_host != start_host:
        raise FetchError(f"redirect to unrelated host blocked: {end_host or final_url!r}")


def fetch_bytes(
    url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> FetchedResponse:
    """HTTP GET `url` with timeout + size guard. Returns raw bytes for the parser."""
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise FetchError(f"refusing non-http(s) URL: {url!r}")
    start_host = (urlparse(url).hostname or "").lower()
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200) or 200
            if status < 200 or status >= 300:
                raise FetchError(f"HTTP non-success status: {status}")
            final_url = response.geturl()
            _check_redirect_chain(start_host, final_url)
            content_type = response.headers.get_content_type() if response.headers else None
            if content_type and not any(
                token in content_type for token in ("xml", "rss", "atom", "text", "octet-stream")
            ):
                raise FetchError(f"unexpected content type: {content_type!r}")
            body = bytearray()
            while True:
                chunk = response.read(_READ_CHUNK)
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise FetchError(f"response exceeds {max_bytes} bytes")
            payload = bytes(body)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        if isinstance(exc, FetchError):
            raise
        raise FetchError(f"fetch failed for {url!r}: {exc}") from exc
    if not payload.strip():
        raise FetchError("empty response body")
    first = payload.lstrip()[:1]
    if first not in (b"<",):
        raise FetchError("response is not XML (does not start with '<')")
    return FetchedResponse(
        final_url=final_url, status=status, content_type=content_type, payload=payload
    )
