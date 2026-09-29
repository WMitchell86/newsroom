"""Bounded, fail-closed redaction for any text that can reach the editor.

An unclassified exception is untrusted text: a provider error can echo the
request back, and the request carries the API key. The same string can also
carry the provider's name and this machine's filesystem paths, none of which
are the editor's business and all of which have been mistaken for a cause the
system had not observed.

This lives in its own dependency-free module because BOTH ends of the operation
registry need it and they cannot import each other: `article_generation` imports
`story_operations`, so the registry cannot reach the Draft layer's redaction.
That is exactly how the single-operation envelope came to be safe while the
Operations LIST endpoint kept serving the raw text.

The rule is deliberately fail-CLOSED: anything matching below drops the whole
bounded detail rather than attempting surgical masking of part of a secret.
"""

from __future__ import annotations

import re

#: What a detail may never carry on its way to the editor. The old substring
#: list (Gemini / OpenRouter URL markers only) let a Bearer token, an sk-* key,
#: a Serper/TinyFish-style secret or a query-string credential pass straight
#: into the editor message.
_DETAIL_FORBIDDEN_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z\-_]{10,}"),
    re.compile(r"x-goog-api-key", re.IGNORECASE),
    re.compile(r"generativelanguage", re.IGNORECASE),
    re.compile(r"openrouter\.ai/api", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/=]{6,}", re.IGNORECASE),
    re.compile(r"[?&](?:key|token|api_key|apikey|secret|auth)=[^&\s]{3,}", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|secret|passwd|password)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
)
_DETAIL_FORBIDDEN = ("AIza", "x-goog-api-key", "generativelanguage", "openrouter.ai/api")

#: The bound on what is worth showing at all. Long enough to name a provider's
#: own reason, short enough not to become a log dump in a UI badge.
DETAIL_LIMIT = 160


def safe_detail(detail: str) -> str:
    """Bounded, redacted reason for an editor-visible failure.

    The reason is what makes a failure diagnosable, so it is surfaced - but a
    provider error is untrusted text that can echo the request, and the request
    carries the API key. Redaction is the price of saying anything at all.
    """
    text = str(detail or "").strip()
    for secret in _DETAIL_FORBIDDEN:
        if secret.lower() in text.lower():
            return ""
    for pattern in _DETAIL_FORBIDDEN_PATTERNS:
        if pattern.search(text):
            return ""
    return text[:DETAIL_LIMIT]
