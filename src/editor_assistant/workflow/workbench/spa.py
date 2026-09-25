"""D1 deployment-level frontend serving mode for the Python process.

This module is deployment infrastructure, not product IA. It decides, per
request, whether the compiled React SPA or the server-rendered Workbench owns
an incoming GET path, and it reads compiled assets off disk safely.

Two deployment modes, selected by one environment variable:

``WB_EDITOR_FRONTEND=legacy`` (the default)
    The M3A server-rendered Workbench owns the current routes exactly as it
    does today. Nothing in this module is reachable.

``WB_EDITOR_FRONTEND=spa``
    Python serves the compiled SPA on the *approved editor routes only*
    (see :func:`owns_spa_route`). Backend API and health endpoints keep their
    existing precedence, and every non-approved path still reaches the legacy
    dispatcher or a real 404 — the SPA never becomes a catch-all.

Safety properties this module is responsible for:

* Assets are confined to the build root. ``..``, encoded traversal, absolute
  paths and NUL bytes are rejected before any filesystem access, and the
  resolved path is re-checked against the root's real path.
* A missing asset is a real ``404``, never the SPA ``index.html`` — a broken
  hashed chunk must not be masked as a silently working application.
* A missing build is a loud ``503``, never a silent fall back to legacy pages,
  because silently serving legacy would hide a broken deployment.
* Unknown paths are never turned into ``200 index.html``; only the explicit
  allowlist below matches.
"""

from __future__ import annotations

import mimetypes
import os
import re
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

#: Deployment-mode switch. ``legacy`` (default) / ``spa``.
FRONTEND_MODE_ENV = "WB_EDITOR_FRONTEND"
#: Override for the compiled build root (used by tests and unusual layouts).
SPA_DIST_ENV = "WB_SPA_DIST"

MODE_LEGACY = "legacy"
MODE_SPA = "spa"

#: Technical rollback prefix: in ``spa`` mode the server-rendered editor pages
#: stay reachable for validation/rollback. It is operational infrastructure —
#: never linked from the SPA and never presented to editors as navigation.
LEGACY_COMPAT_PREFIX = "/wb-legacy"

#: A single client-route identifier segment. Structural only (never semantic):
#: the SPA resolves the resource and renders its own not-found state, so the
#: server must not second-guess which identifiers "exist".
_SEGMENT_RE = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")

#: Vite emits content-hashed filenames such as ``index-CCWo5GjE.js``.
_HASHED_NAME_RE = re.compile(r"-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+\Z")

#: Top-level directory of the compiled build that may be served recursively.
_ASSET_DIR = "assets"

_MIME_OVERRIDES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}

#: Content-hashed build output is immutable; its URL changes whenever the
#: bytes do. Everything else stays short-lived so a rebuild is picked up.
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
_REVALIDATE_CACHE = "public, max-age=300, must-revalidate"
#: The entry document must never be cached: it names the current chunk hashes.
INDEX_CACHE = "no-cache"


class SpaBuildMissing(RuntimeError):
    """SPA mode is enabled but the compiled build is absent or incomplete."""


def frontend_mode(environ: dict[str, str] | None = None) -> str:
    """Resolve the deployment mode. Unknown values fail closed to ``legacy``."""
    env = environ if environ is not None else os.environ
    raw = (env.get(FRONTEND_MODE_ENV) or "").strip().lower()
    if raw == MODE_SPA:
        return MODE_SPA
    return MODE_LEGACY


def is_spa_enabled(environ: dict[str, str] | None = None) -> bool:
    return frontend_mode(environ) == MODE_SPA


def dist_root(environ: dict[str, str] | None = None) -> Path:
    """The compiled build directory. Overridable so tests never touch a real build."""
    env = environ if environ is not None else os.environ
    override = (env.get(SPA_DIST_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return ROOT / "frontend" / "dist"


def index_path(environ: dict[str, str] | None = None) -> Path:
    return dist_root(environ) / "index.html"


def build_available(environ: dict[str, str] | None = None) -> bool:
    """True only when the entry document exists and is a regular file."""
    try:
        return index_path(environ).is_file()
    except OSError:  # pragma: no cover - defensive; unreadable mount
        return False


def require_build(environ: dict[str, str] | None = None) -> Path:
    """Return the entry document, or raise :class:`SpaBuildMissing`."""
    entry = index_path(environ)
    if not build_available(environ):
        raise SpaBuildMissing(
            f"{FRONTEND_MODE_ENV}=spa requires a compiled frontend build at {entry}. "
            "Run `npm ci && npm run build` in frontend/, or set "
            f"{FRONTEND_MODE_ENV}=legacy to serve the server-rendered Workbench."
        )
    return entry


# --------------------------------------------------------------------------
# route ownership
# --------------------------------------------------------------------------


def _segments(path: str) -> list[str] | None:
    """Split a URL path into safe segments, or ``None`` if it is unsafe.

    ``urlparse`` does not URL-decode, so decoding happens here exactly once.
    Traversal is judged on the *decoded* value, which is what actually reaches
    the filesystem.
    """
    decoded = urllib.parse.unquote(path)
    if "\x00" in decoded or "\\" in decoded:
        return None
    return [part for part in decoded.split("/") if part and part != "."]


def _is_identifier(segment: str) -> bool:
    return bool(_SEGMENT_RE.fullmatch(segment)) and segment not in {".", ".."}


def owns_spa_route(path: str) -> bool:
    """True when the SPA owns this exact client route.

    The allowlist is deliberately closed: ``/``, the three list routes, the
    three detail routes and ``/settings``. Everything else — including
    ``/case/*``, ``/cases``, ``/inbox``, ``/sources``, ``/models``, ``/intake``
    and every unknown URL — is excluded.
    """
    parts = _segments(path)
    if parts is None:
        return False
    if not parts:
        return True
    if parts == ["settings"]:
        return True
    if len(parts) == 1:
        return parts[0] in {"stories", "articles", "archive"}
    if len(parts) == 2 and parts[0] in {"stories", "articles", "archive"}:
        return _is_identifier(parts[1])
    return False


def strip_legacy_prefix(path: str) -> str | None:
    """Map ``/wb-legacy/<rest>`` onto the legacy path ``/<rest>``.

    Returns ``None`` when the request is not a compatibility request. The
    prefix is honored only in SPA mode; in legacy mode it stays a 404 so the
    default deployment surface is unchanged.
    """
    if not is_spa_enabled():
        return None
    parts = _segments(path)
    if not parts or parts[0] != LEGACY_COMPAT_PREFIX.strip("/"):
        return None
    return "/" + "/".join(parts[1:])


def owns_static_path(path: str) -> bool:
    """True when the path addresses compiled build output."""
    parts = _segments(path)
    if not parts:
        return False
    # The entry document is never fetched as a plain asset: it is always served
    # with revalidation semantics through the SPA entry.
    if parts == ["index.html"]:
        return False
    if parts[0] == _ASSET_DIR:
        return len(parts) >= 2
    # Single-segment root files only (favicon, manifest, icons). This keeps the
    # build root from becoming a general-purpose file server.
    return len(parts) == 1


# --------------------------------------------------------------------------
# asset resolution
# --------------------------------------------------------------------------


def resolve_asset(path: str, environ: dict[str, str] | None = None) -> Path | None:
    """Resolve a URL path to a regular file inside the build root, or ``None``.

    ``None`` covers every rejection reason: unsafe path, traversal, a directory
    instead of a file, or a file outside the resolved root.
    """
    parts = _segments(path)
    if not parts:
        return None
    try:
        root_real = dist_root(environ).resolve(strict=True)
    except OSError:
        return None

    try:
        resolved = root_real.joinpath(*parts).resolve(strict=True)
    except OSError:
        return None

    # Containment check on the *real* paths: a symlink inside the build cannot
    # be used to read a file elsewhere on disk.
    if resolved != root_real and root_real not in resolved.parents:
        return None
    if not resolved.is_file():
        return None
    return resolved


def content_type(path: Path) -> str:
    """MIME type for a served file, with explicit overrides for build output."""
    suffix = path.suffix.lower()
    if suffix in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def cache_control(path: Path) -> str:
    """Proportionate caching: hashed build output is immutable, the rest is not."""
    if _HASHED_NAME_RE.search(path.name):
        return _IMMUTABLE_CACHE
    return _REVALIDATE_CACHE
