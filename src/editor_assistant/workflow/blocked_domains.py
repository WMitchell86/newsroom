"""Editor-owned blocked-domain policy (M4A.1).

Broad monitoring collectors (Google News / search) can return publishers the
editor does not want in the inbox. The registry can only exclude a *source*, not
a domain that a query happens to surface, so the exclusion lives here as its own
tiny, editor-owned store.

Contract:

* stored values are **canonical hosts** (`example.com`), never URLs/paths;
* input may be a bare host or an `http(s)://` URL, but a URL carrying a path is
  refused — a pasted article link is a mistake, not a domain decision;
* matching is host-suffix based, so `m.flagman.bg` is covered by `flagman.bg`;
* blocked hosts are filtered **before** an item reaches the inbox, and a source
  whose own URL targets a blocked host is refused outright;
* atomic writes, deterministic bytes, no expiration — a domain stays blocked
  until the editor removes it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from editor_assistant.workflow import live_store

ROOT = Path(__file__).resolve().parents[3]

#: The initial policy: the outlet the research explicitly excluded.
DEFAULT_BLOCKED = ("flagman.bg",)

_HOST_RX = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class BlockedDomainError(ValueError):
    """A domain value or action that must not be stored."""


def blocked_path(path=None):
    if path is not None:
        return Path(path)
    override = os.environ.get("NEWSROOM_BLOCKED_DOMAINS_PATH")
    if override:
        return Path(override)
    root = Path(os.environ.get("NEWSROOM_DIR") or (ROOT / "var" / "newsroom"))
    return root / "blocked_domains.json"


def canonical_host(value):
    """`value` -> canonical host, or raise. Accepts a host or an http(s) URL.

    Scheme, `www.`, case and a trailing slash/dot are normalized away. Anything
    with a path, query, fragment, credentials or port is refused: the stored
    value is a domain, not a page.
    """
    text = str(value or "").strip()
    if not text:
        raise BlockedDomainError("домейнът е задължителен")
    candidate = text
    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme.lower() not in ("http", "https"):
            raise BlockedDomainError(f"само http(s) адреси са валидни: {text!r}")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise BlockedDomainError(f"въведете само домейн, не адрес на страница: {text!r}")
        if parsed.username or parsed.password:
            raise BlockedDomainError("домейнът не може да съдържа потребител/парола")
        if parsed.port:
            raise BlockedDomainError("домейнът не може да съдържа порт")
        candidate = parsed.hostname or ""
    if any(ch in candidate for ch in "/?#@:"):
        raise BlockedDomainError(f"въведете само домейн: {text!r}")
    host = candidate.strip().strip(".").lower().removeprefix("www.")
    if not _HOST_RX.match(host):
        raise BlockedDomainError(f"невалиден домейн: {text!r}")
    if "." not in host:
        raise BlockedDomainError(f"домейнът трябва да съдържа точка: {text!r}")
    return host


def read_domains(path=None):
    """Sorted canonical hosts. A missing store is an empty policy (not an error)."""
    store = blocked_path(path)
    if not store.exists():
        return []
    try:
        rows = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlockedDomainError(f"списъкът със забранени домейни е нечетим: {exc}") from exc
    if not isinstance(rows, list):
        raise BlockedDomainError("списъкът със забранени домейни трябва да е JSON масив")
    return sorted({canonical_host(row) for row in rows})


def effective_domains(path=None):
    """The policy in force: the stored list once the editor has edited it, else
    the default policy. A fresh install blocks `flagman.bg` before anyone clicks
    anything; the first edit materializes the list and the editor can then remove
    even a default.
    """
    if blocked_path(path).exists():
        return read_domains(path)
    return sorted(DEFAULT_BLOCKED)


def save_domains(domains, path=None):
    normalized = sorted({canonical_host(d) for d in domains})
    payload = json.dumps(normalized, ensure_ascii=False, indent=1) + "\n"
    live_store.atomic_write(blocked_path(path), payload)
    return normalized


def add_domain(value, *, path=None):
    domains = effective_domains(path)
    host = canonical_host(value)
    if host in domains:
        return {"added": False, "domain": host, "domains": domains}
    domains = save_domains(domains + [host], path)
    return {"added": True, "domain": host, "domains": domains}


def remove_domain(value, *, path=None):
    host = canonical_host(value)
    domains = effective_domains(path)
    if host not in domains:
        raise BlockedDomainError(f"домейнът не е в списъка: {host}")
    domains = save_domains([d for d in domains if d != host], path)
    return {"removed": True, "domain": host, "domains": domains}


def seed_defaults(*, path=None, dry_run=False):
    """Write the default policy to the store additively (used by install/CLI)."""
    domains = effective_domains(path)
    added = [d for d in DEFAULT_BLOCKED if d not in domains]
    if added and not dry_run:
        domains = save_domains(domains + added, path)
    return {"added": added, "domains": domains}


def host_of(url_or_host):
    """Best-effort host of a URL; None when it cannot be read."""
    text = str(url_or_host or "").strip()
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"//{text}")
    host = (parsed.hostname or "").lower()
    return host or None


def is_blocked(url_or_host, domains=None, *, path=None):
    """True when a URL/host falls under (or equals) a blocked domain."""
    host = host_of(url_or_host)
    if not host:
        return False
    policy = effective_domains(path) if domains is None else list(domains)
    return any(host == d or host.endswith("." + d) for d in policy)


def blocked_reason(entry, *, path=None):
    """Why a registry entry must not be collected, or None.

    Three cases, all checked **before any network call** (M4B.1 F6): a source whose
    own URL is blocked (a direct blocked publisher), a source that *declares* a
    blocked publisher domain, or a monitoring query that names a blocked domain.
    A source is refused, not silently emptied.
    """
    policy = effective_domains(path)
    if not policy:
        return None
    url = entry.get("url") or ""
    if url and is_blocked(url, policy):
        return f"домейнът на източника е забранен ({host_of(url)})"
    declared = entry.get("domain") or ""
    if declared and is_blocked(declared, policy):
        return f"обявеният домейн на източника е забранен ({declared})"
    query = (entry.get("query") or "").lower()
    if query:
        for domain in policy:
            stem = domain.split(".")[0]
            if domain in query or (stem and stem in query):
                return f"заявката споменава забранен домейн ({domain})"
    return None
