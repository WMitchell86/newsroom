"""V1.2-G4.20 — «Започни от идея»: the editor's own hint becomes real material.

The editor wants to start from an idea, not from a collected article. The
tempting shape is to let the hint itself be the Story and write from it. That
is refused here on purpose.

`inbox_store.validate_item` demands an absolute http(s) URL, because every
Story is a collected article whose body came off that page. An editor's hint
has no page. The only way to admit it as-is is to invent a placeholder URL
(`https://editor.local/hint/1` passes the shape check today), and that is the
exact lie this system exists to avoid: the Story would carry a URL that opens
nothing, `build_packet_from_record` would treat the placeholder as the source,
and a later reader — or the fact checker — would chase a source that was never
there.

So the hint is a SEARCH QUERY, never evidence. It runs the same
`run_search_operation` the rest of research uses, which plans queries, runs
the provider chain, filters candidates against the recorded constraints, and
OPENS every kept page. Only a page that actually opened becomes a Story, and
it lands with its own real URL and body, indistinguishable from one collected
by the newsroom. From that point the ordinary path applies: research →
EvidencePacket → Draft, with real provenance. The editor's idea selects the
material; it does not stand in for it.

Failure is explicit and never dressed up as material. No opened page means no
Story and a stated reason — the editor is told the search found nothing open,
which is a real fact about the world, not a failure to invent around.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from editor_assistant.sources import web_fetch
from editor_assistant.workflow import search as search_mod

#: A hint must be a topic, not a paragraph of prose. Long input is almost
#: always a pasted article, which is the OTHER feature ("research this
#: article"), and searching a whole article finds nothing useful.
HINT_MIN_CHARS = 6
HINT_MAX_CHARS = 300


class HintRejected(ValueError):
    """The editor's own hint could not be used, and says why."""


@dataclass
class HintResult:
    """What the hint actually produced. Empty material is a valid outcome."""

    hint: str
    #: Pages that passed the constraints AND opened. Their bodies become Stories.
    opened: list[dict] = field(default_factory=list)
    #: Everything the search saw, including pages that failed to open. Kept so a
    #: failure can be reported as the real category rather than "nothing".
    considered: int = 0
    #: Pages that satisfied the constraints but could not be opened.
    unopened: list[dict] = field(default_factory=list)
    queries: list[dict] = field(default_factory=list)
    audit: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return bool(self.opened)


def _clean_hint(raw: str) -> str:
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text:
        raise HintRejected("Подсказката е празна.")
    if len(text) < HINT_MIN_CHARS:
        raise HintRejected(
            f"Подсказката е твърде кратка ({len(text)} символа) — минимумът е {HINT_MIN_CHARS}."
        )
    if len(text) > HINT_MAX_CHARS:
        raise HintRejected(
            f"Подсказката е твърде дълга ({len(text)} символа) — максимумът е {HINT_MAX_CHARS}. "
            "По-дълъг текст е материал за изследване, а не тема за търсене."
        )
    return text


class _RecordingOpener:
    """Wraps the fetcher so the opened page's TEXT is kept, not just its URL.

    `run_search_operation` records only metadata for a candidate — url, bytes,
    content type. That is enough to prove a page was OPENED, and useless for
    writing: a Story with a URL and no body is an empty lead. Since we supply
    the opener, we see the page on its way past, and keep the text so the
    material that leaves this module is the real article rather than a link.
    """

    def __init__(self, inner):
        self._inner = inner
        self.pages: dict[str, dict] = {}

    def __call__(self, url):
        page = self._inner(url)
        if isinstance(page, dict):
            key = page.get("final_url") or url
            self.pages[key] = page
            self.pages.setdefault(url, page)
        return page


def run_hint_search(
    hint: str,
    *,
    provider=None,
    page_opener=None,
    max_open: int = 3,
    env=None,
    capability: str = search_mod.CAP_WEB,
) -> HintResult:
    """Search the open web for the hint and return only pages that opened.

    The constraints are recorded with a description naming the hint, so the
    audit says which topic produced which page. We deliberately do NOT pin
    required domains: the editor named a topic, not a publisher, and silently
    narrowing to a guessed domain would change the meaning of the request
    (audit A7, the same lesson as the BTA→municipality switch).
    """
    text = _clean_hint(hint)
    constraints = search_mod.make_constraints(
        description=f"материали по редакторска подсказка: {text}"
    )
    recorder = _RecordingOpener(page_opener or web_fetch.fetch_page)
    operation = search_mod.run_search_operation(
        topic=text,
        constraints=constraints,
        provider=provider,
        page_opener=recorder,
        max_open=max_open,
        capability=capability,
        env=env,
    )
    result = HintResult(hint=text)
    result.considered = len(operation.get("candidates") or [])
    result.queries = list(operation.get("queries") or [])
    result.audit = {
        k: operation.get(k)
        for k in ("topic", "capability", "provider_chain", "started_at", "finished_at", "status", "reason")
    }
    for candidate in operation.get("candidates") or []:
        opened = candidate.get("opened") or {}
        if opened.get("status") == web_fetch.FETCH_OK:
            final_url = opened.get("final_url") or candidate.get("url") or ""
            page = recorder.pages.get(final_url) or recorder.pages.get(candidate.get("url")) or {}
            result.opened.append(
                {
                    "title": candidate.get("title") or "",
                    "url": final_url,
                    "bytes": opened.get("bytes") or 0,
                    "content_type": opened.get("content_type") or "",
                    "text": page.get("text") or "",
                }
            )
        else:
            # Kept with the provider's own category so a failure is never
            # reported as "no such material exists".
            result.unopened.append(
                {
                    "url": candidate.get("url") or "",
                    "status": opened.get("status") or "not-attempted",
                    "detail": opened.get("detail") or "",
                }
            )
    return result
