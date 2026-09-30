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
from urllib.parse import urlsplit

from editor_assistant.sources import web_fetch
from editor_assistant.workflow import search as search_mod

#: A hint must be a topic, not a paragraph of prose. Long input is almost
#: always a pasted article, which is the OTHER feature ("research this
#: article"), and searching a whole article finds nothing useful.
HINT_MIN_CHARS = 6
HINT_MAX_CHARS = 300

#: The honest origin label for material an editor's hint led us to. It is not
#: a registered publisher and does not pretend to be one.
HINT_SOURCE_ID = "editor-hint"


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


def materialise_hint_stories(
    result: HintResult,
    *,
    inbox_path,
    stories_path=None,
    now: str = "",
) -> list[dict]:
    """Turn the pages a hint opened into ordinary Stories in the inbox.

    They are written with the same fields the newsroom's own collector writes,
    so everything downstream — promotion, research, the readiness gates — is
    exercised exactly as it is for collected material. There is no "hint" kind
    downstream and no branch that knows an editor typed something.

    `stories_path` is not optional in practice. Writing inbox rows is only
    HALF of becoming a Story: `story_identity` is what assigns items to
    stories, and an item that nobody assigned is invisible to the editor —
    it sits in the inbox forever and the Stories list never shows it. This
    was found by measuring a live run, not by reading the code: three rows
    were written, all three were attached to no story, and the feature
    looked like it had worked. So the same incremental `update()` the
    newsroom refresh uses runs here, which also means a page the newsroom
    had already collected joins its existing Story instead of forming a
    duplicate.

    Two values are chosen for honesty rather than convenience:

    * `source_id` is `editor-hint`, which is simply true — the origin was the
      editor, not a registered publisher. It also makes the item id
      deterministic, so the same page found by two different hints collapses
      into ONE row instead of a duplicate.
    * `factual_authority` is False. A page reached through a search engine is
      not thereby an authority, and `cik.bg` found this way is not promoted
      above an official source. Authority is earned by registration, exactly
      as the sources registry already decides it.

    `summary` is left empty on purpose. The only text this path holds for a
    candidate is the provider snippet, which `search.py` marks DISCOVERY_ONLY;
    writing it into the lead's summary would move a discovery-only string into
    a field every other reader treats as collected material. The real article
    body is re-opened downstream, so nothing is actually lost by leaving it out.

    No body is written: the inbox record has no body field at all (verified
    against `inbox_store.FIELDS`), and the drafting path re-opens the page.
    """
    if not result.usable:
        return []
    from datetime import datetime, timezone

    from editor_assistant.workflow import inbox_store

    discovered = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = []
    for page in result.opened:
        url = (page.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        items.append(
            {
                "source_id": HINT_SOURCE_ID,
                "source_item_id": url,
                "title": (page.get("title") or "").strip() or result.hint,
                "url": url,
                "published_at": "",
                "event_at": "",
                "event_end_at": "",
                "discovered_at": discovered,
                "summary": "",
                "source_kind": "editor-hint",
                "priority": "normal",
                "publisher_domain": urlsplit(url).netloc,
                "publisher_kind": "",
                "factual_authority": False,
            }
        )
    if not items:
        return []
    saved = inbox_store.add_items(items, inbox_path) or {}
    # `add_items` returns {new, duplicate, items}; a page an earlier hint
    # already collected is counted as a duplicate, never written twice.
    written = [row for row in saved.get("items", []) if row.get("source_id") == HINT_SOURCE_ID]

    if written and stories_path is not None:
        # Assign them to Stories through the newsroom's OWN locked refresh,
        # not by calling `story_identity.update` directly. That function holds
        # the mutation lock the other stories-store writers hold; calling it
        # raw added a third, unlocked writer to a store that two existing
        # writers already protect with two *different* locks. Reusing the
        # public entry point keeps this path no less safe than the refresh,
        # and it is the same code the newsroom uses, so grouping cannot drift.
        from editor_assistant.workflow.workbench import newsroom as newsroom_mod

        newsroom_mod.refresh_stories(dry_run=False, semantic=False)
        written = _with_story_ids(written, inbox_path, stories_path)
    return written


def _with_story_ids(rows: list[dict], inbox_path, stories_path) -> list[dict]:
    """Attach the story each row actually landed in.

    The editor is sent to a story, not to a raw inbox item: `/stories/:id`
    validates the id and answers "Невалиден Story." for an item id, so
    returning `item_id` here produced a dead link the moment it was clicked.
    """
    from editor_assistant.workflow import story_store

    store = story_store.read_store(stories_path)
    story_of = {
        member["item_id"]: story["story_id"]
        for story in store.get("stories", [])
        for member in story.get("members", [])
    }
    out = []
    for row in rows:
        enriched = dict(row)
        enriched["story_id"] = story_of.get(row["item_id"], "")
        out.append(enriched)
    return out


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
