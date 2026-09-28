"""V1.2-G4.3 A - the automatic, bounded enrichment that runs INSIDE `Cернова`.

**The owner decision this encodes.** Pressing `Chernova` now means: "I want an
Article. Gather useful information automatically, then write the best Draft you
can now." The editor must not have to press `Prouchi oshte` first, and the Draft
must not be replaced by a refusal when the gathering finds nothing.

**Why this is a new module and not a Research call.** Research answers "is this
corroborated?" and is allowed to say no; `Prouchi oshte` writes to the canonical
Story basis, promotes facts and clears gaps. That is the wrong job here. This
module answers a narrower question - "is there a small amount of additional
usable context for this Draft?" - and it:

* never writes to `story_research_store`, so no fact is promoted and no gap is
  closed;
* never refuses the Draft, only degrades to less material plus a warning;
* reuses the already-exercised search / safe-open / extraction / publisher
  identity / authority / provenance services rather than adding a second engine.

**The bounds are policy, not hints (A3).** They are module constants, so no
caller - including a future one - can raise them. The whole point is that this
step is cheap enough to run on every single Draft:

    MAX_QUERIES       = 2-3 search queries
    MAX_OPENED_PAGES  = 3-5 useful publisher pages actually opened
    WALL_CLOCK_BUDGET = ~20-30 s before the Draft continues regardless

**A2 - it is opportunistic, never a gate again.** All three of these end in a
Draft: the original plus useful sources gives a richer Draft; the original
alone gives a Draft plus a warning; an unavailable provider with a readable
original gives a Draft plus a warning.

**A5 - a snippet is discovery only.** Nothing here reads text a search result
merely *showed*; only a page that was actually opened contributes claims, and
every claim keeps the page URL and a `claim:N` locator. The pre-existing
factual/style boundary is untouched: this module produces *material*, and the
existing `draft_material` gate decides what that material is worth.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time

from editor_assistant.sources import web_fetch as web_fetch_mod
from editor_assistant.workflow import publication_material
from editor_assistant.workflow import search as search_mod

LOG = logging.getLogger(__name__)

#: The operator switch for the automatic enrichment. The production default is
#: ON: pressing `Чернова` is supposed to gather useful material by itself, and
#: that behaviour must not depend on a configuration flag. The switch exists for
#: hermetic test runs and for an operator who deliberately wants a Draft to cost
#: nothing beyond the original page.
ENRICHMENT_ENV = "NEWSROOM_DRAFT_ENRICHMENT"
ENRICHMENT_OFF = "off"


def is_enabled() -> bool:
    """Whether the automatic enrichment should run at all.

    Only an explicit `off` disables it. Anything else - including an unset
    variable - means enabled, so a typo in a configuration can never silently
    turn the product back into "a Draft with no effort put in".
    """
    return str(os.environ.get(ENRICHMENT_ENV, "")).strip().lower() != ENRICHMENT_OFF

#: A3 - the starting envelope. These are policy constants, not arguments.
MAX_QUERIES = 3
MAX_OPENED_PAGES = 5
#: How long the enrichment may take before the Draft continues without it. The
#: editor is waiting on one click; a slow provider must degrade, never hang.
WALL_CLOCK_BUDGET_S = 30.0

#: A2 - enrichment ran and added nothing usable. A warning on the Draft, never
#: a reason to withhold it.
WARNING_ENRICHMENT_EMPTY = "Автоматичното обогатяване не намери допълнителни източници."

#: A2 - the search provider could not be reached at all. The Draft is written
#: from the original material and the editor is told the gathering was skipped.
WARNING_ENRICHMENT_UNAVAILABLE = (
    "Автоматичното обогатяване не можа да се извърши. Черновата е написана от наличния материал."
)

#: The editorial questions A4 asks of a Story. They are not a generic checklist
#: applied blindly: `plan_questions` picks the small set that fits the Story's
#: own shape, and `search.run_event_discovery` already builds its deterministic
#: query ladder from the Story's anchors.
EVENT_QUESTIONS = (
    "Кога и къде се провежда събитието.",
    "Кой участва и каква е програмата.",
    "Как се влиза — билети, регистрация, достъп.",
    "Кой е организаторът и има ли официална страница.",
)
INCIDENT_QUESTIONS = (
    "Къде се е случило инцидентът.",
    "Кога се е случило и каква е актуалната информация.",
    "Кой е засегнат.",
    "Има ли официално съобщение на полицията или пожарната.",
    "Има ли ограничения или практическо въздействие.",
)
DECISION_QUESTIONS = (
    "Какво точно се променя.",
    "От кога влиза решението в сила.",
    "Кой е засегнат.",
    "Къде е официалното решение.",
    "Какви са практическите последици.",
)
GENERAL_QUESTIONS = (
    "Къде и кога се е случило.",
    "Кой е засегнат.",
    "Има ли официален източник, който го потвърждава.",
)

#: The Story shapes A4 distinguishes, as a small deterministic keyword test.
#: No model call: this only chooses WHICH useful questions to ask, and asking a
#: slightly broader question is never a fabrication.
_EVENT_CUES = (
    "концерт", "фестивал", "спектакъл", "събитие", "преставяне", "изложба",
    "турнир", "мач", "зала", "театър", "кино", "празник", "събор",
)
_INCIDENT_CUES = (
    "пожар", "инцидент", "катастрофа", "авари", "земетресение",
    "наводнение", "сблъскване", "пострад", "загина", "ранен", "автомобил",
    "превозно", "влак", "самолет", "кораб", "спасява", "полиция", "пожарна",
)
_DECISION_CUES = (
    "одобри", "реши", "решение", "забрана", "забрани", "промяна", "промени",
    "закрива", "отваря", "тарифа", "цена", "такса", "данък", "бюджет",
    "конкурс", "назначава", "общински съвет",
)


def plan_questions(title: str, *, limit: int = 3) -> tuple[str, ...]:
    """The SMALL number of useful editorial questions for this Story (A4).

    The point of A4 is that enrichment is not "find another source" - it is
    "find the details that would make this Article better". So the questions are
    chosen from the Story's own shape, and the result is bounded by `limit`
    because a long question list is a slow Draft, not a better one.

    Deterministic and model-free, which keeps the *Draft* budget where it
    belongs: on writing the Article rather than on deciding what to ask.

    **Word-boundary matching, not substring.** Plain `cue in text` classified
    a theatre story as a municipal decision, because "цена" is a substring of
    "сцена" — so a Story about a stage asked what a government decision
    changes and when it takes effect. The wrong questions are worse than no
    questions: they steer the search away from the actual event.
    """
    text = " ".join(str(title or "").lower().split())
    if not text:
        return GENERAL_QUESTIONS[: max(1, int(limit))]
    if any(_has_word(text, cue) for cue in _INCIDENT_CUES):
        pool = INCIDENT_QUESTIONS
    elif any(_has_word(text, cue) for cue in _EVENT_CUES):
        pool = EVENT_QUESTIONS
    elif any(_has_word(text, cue) for cue in _DECISION_CUES):
        pool = DECISION_QUESTIONS
    else:
        pool = GENERAL_QUESTIONS
    return pool[: max(1, int(limit))]


def _has_word(text: str, cue: str) -> bool:
    """Whether `cue` appears in `text` as a whole word (or a whole prefix of one).

    Bulgarian inflects, so a cue is allowed to match the START of a word
    ("пожар" in "пожари"), but never in the middle of one.
    """
    return re.search(rf"(?<!\w){re.escape(cue)}\w*", text) is not None


class Budget:
    """The A3 envelope, measured once and shared by every step below.

    Exists so the bound is *enforced* rather than documented: `exhausted` is
    checked before each page open, so a slow provider costs the enrichment its
    extra work and never the editor's Draft.

    **The constructor CLAMPS to the module policy.** These are documented as
    constants "no caller — including a future one — can raise", so a caller
    passing `Budget(pages=99)` must not be able to open 99 pages. A caller may
    ask for LESS (a test, a deliberately cheap run), never for more.
    """

    def __init__(
        self,
        *,
        queries: int = MAX_QUERIES,
        pages: int = MAX_OPENED_PAGES,
        seconds: float = WALL_CLOCK_BUDGET_S,
        clock=time.monotonic,
    ) -> None:
        self.queries_left = min(MAX_QUERIES, max(0, int(queries)))
        self.pages_left = min(MAX_OPENED_PAGES, max(0, int(pages)))
        self.seconds = min(WALL_CLOCK_BUDGET_S, max(0.0, float(seconds)))
        self._clock = clock
        self._started = clock()
        self.timed_out = False

    def elapsed(self) -> float:
        return self._clock() - self._started

    def exhausted(self) -> bool:
        if self.timed_out or self.elapsed() >= self.seconds:
            self.timed_out = True
            return True
        return False

    def take_query(self) -> bool:
        """Spend one of the query allowance. Symmetric with `take_page`."""
        if self.queries_left <= 0:
            return False
        self.queries_left -= 1
        return True

    def take_page(self) -> bool:
        if self.pages_left <= 0 or self.exhausted():
            return False
        self.pages_left -= 1
        return True


class _PageCache:
    """A page opener that fetches each URL once and remembers the result.

    `run_event_discovery` opens a candidate page to decide whether it is a real
    publisher, and the extraction pass then reads the SAME page again. Without
    this, every accepted page was downloaded twice - so a stated envelope of "3-5
    opened pages" was really up to ten fetches plus the wrapper rejections.
    """

    def __init__(self, opener=None) -> None:
        self._opener = opener
        self._pages: dict[str, dict] = {}

    def __call__(self, url: str) -> dict:
        if url not in self._pages:
            self._pages[url] = self._opener(url) if self._opener else web_fetch_mod.fetch_page(url)
        return self._pages[url]

    def cached(self, url: str) -> dict | None:
        return self._pages.get(url)


def _run_discovery_bounded(work, *, seconds: float):
    """Run `work` with a real wall-clock deadline; `None` if it overran.

    The bounded-operation registry the product already uses is for POLLS, not
    for cancelling work, so the deadline here is enforced by running the call on
    a worker thread and simply not waiting for it past the envelope. The
    enrichment is opportunistic by contract, so an overrun costs the Draft its
    extra material and nothing else.
    """
    remaining = max(0.0, float(seconds))
    if remaining <= 0:
        return None
    result: dict = {}
    done = threading.Event()

    def runner() -> None:
        try:
            result["operation"] = work()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            result["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=runner, name="draft-enrichment", daemon=True)
    worker.start()
    if not done.wait(remaining):
        LOG.warning(
            "draft enrichment exceeded its %.0fs envelope; continuing without it", remaining
        )
        return None
    if "error" in result:
        error = result["error"]
        # A provider, key or transport problem is an enrichment problem and
        # nothing more; a real defect in this module still surfaces loudly.
        if isinstance(error, (search_mod.SearchError, OSError, ValueError, KeyError, TypeError)):
            LOG.warning("draft enrichment could not run: %s", type(error).__name__)
            return None
        raise error
    return result.get("operation")


def enrich(
    *,
    topic: str,
    existing_urls=(),
    questions=(),
    provider=None,
    page_opener=None,
    budget: Budget | None = None,
    audit_path=None,
) -> dict:
    """Run one bounded enrichment round and return usable material.

    Returns a mapping with three honest parts:

        sources  - opened publisher pages, with their verbatim claims
        queries  - the questions that were actually asked (for the product report)
        warnings - what stayed unresolved, as editor-safe sentences

    It never raises for an enrichment problem: an unreachable provider, a
    missing key or a spent budget all end in `sources == []` plus a warning, and
    the caller continues to the Draft. That is the A2 contract, and it is the
    exact opposite of the gate this replaced.
    """
    spend = budget or Budget()
    title = " ".join(str(topic or "").split())
    asked = tuple(str(item).strip() for item in questions if str(item or "").strip())
    if not is_enabled():
        # Deliberately NOT a warning: the editor did not ask for enrichment and
        # the operator turned it off, so there is nothing unresolved to report.
        return {"sources": [], "queries": [], "warnings": (), "elapsed_s": spend.elapsed()}
    if not title:
        # Nothing to search *for*. This reports NO warning at all rather than
        # "found no additional sources": no search was performed, so claiming it
        # found nothing would be a fabricated observation. The Draft still
        # proceeds from whatever material the Story already had.
        return {
            "sources": [],
            "queries": [],
            "warnings": (),
            "elapsed_s": spend.elapsed(),
        }

    known = {str(url or "").strip() for url in existing_urls if str(url or "").strip()}
    queries_run: list[str] = []

    # The pages discovery already opened are re-used for the extraction pass
    # below, so an accepted page is fetched ONCE rather than twice. This is
    # also what keeps the real page count near the stated envelope.
    cache = _PageCache(page_opener)

    # A3 - the deadline is REAL, not advisory. `run_event_discovery` is a single
    # blocking call with no cancellation, and the keyless provider chain inside
    # it can spend far longer than the whole envelope. Checking the clock before
    # and after the call is therefore not enough: the call has to be bounded
    # from the outside, or the editor waits for minutes behind a 30 s promise.
    #
    # On overrun the Draft continues with no enrichment and an honest warning.
    # The abandoned thread is left to die on its own; killing it would mean
    # interrupting a socket mid-write for no benefit to the editor.
    operation = _run_discovery_bounded(
        lambda: search_mod.run_event_discovery(
            topic=title,
            constraints=search_mod.make_constraints(
                description="автоматично обогатяване на материал за чернова",
                location="Бургас",
            ),
            missing_dimensions=list(asked),
            provider=provider,
            page_opener=cache,
            max_open=min(MAX_OPENED_PAGES, max(0, spend.pages_left)),
            audit_path=audit_path,
            # A3: the round may not spend more of the owner's Serper
            # allocation than the enrichment envelope allows.
            serper_budget=max(0, spend.queries_left),
            # A2: stop as soon as the material is good enough. A Story already
            # covered elsewhere must not cost the whole query ladder.
            stop_after_publishers=max(1, min(2, spend.pages_left)),
        ),
        seconds=spend.seconds - spend.elapsed(),
    )
    if operation is None:
        return {
            "sources": [],
            "queries": [],
            "warnings": (WARNING_ENRICHMENT_UNAVAILABLE,),
            "elapsed_s": spend.elapsed(),
        }

    queries_run.extend(
        str(row.get("query") or "")
        for row in (operation.get("queries") or [])
        if row.get("query")
    )

    opened: list[dict] = []
    for candidate in operation.get("candidates") or []:
        if spend.exhausted():
            break
        final_url = str(
            (candidate.get("opened") or {}).get("final_url") or candidate.get("url") or ""
        )
        if not final_url or final_url in known:
            continue
        if (candidate.get("opened") or {}).get("status") != web_fetch_mod.FETCH_OK:
            continue
        # A5 / B4: only a real publisher page that was actually OPENED may
        # contribute. `read_publication` re-checks the wrapper, blocked-domain
        # and on-topic rules, and returns verbatim claims with their locators.
        if not spend.take_page():
            break
        read = publication_material.read_publication(final_url, topic=title, opener=cache)
        if not read:
            continue
        known.add(read["url"])
        opened.append(
            {
                # A real identity, not "". The claims of two different
                # publisher pages would otherwise share the source_reference
                # "<id>:claim:0", which is what makes a claim traceable back to
                # the page it came from.
                "id": _source_id_for(read["url"]),
                "name": read["domain"],
                "url": read["url"],
                "domain": read["domain"],
                "claims": read["claims"],
                "origin": "enrichment",
            }
        )

    return {
        "sources": opened,
        "queries": queries_run,
        # Honesty about WHY there is nothing: a search that ran and found
        # nothing is one thing, and an envelope that ran out mid-flight is
        # another. Reporting the second as the first tells the editor a search
        # came back empty when it was in fact cut off.
        "warnings": _no_material_warning(opened, spend),
        "elapsed_s": spend.elapsed(),
    }


def _no_material_warning(opened: list[dict], spend: Budget) -> tuple[str, ...]:
    """The honest reason no enrichment material reached the Draft."""
    if opened:
        return ()
    if spend.exhausted():
        return (WARNING_ENRICHMENT_UNAVAILABLE,)
    return (WARNING_ENRICHMENT_EMPTY,)


def _source_id_for(url: str) -> str:
    """A stable, URL-derived source id.

    Derived from the URL rather than a counter so it is reproducible: the same
    publisher page always yields the same id, which is what lets a claim's
    provenance be re-resolved later.
    """
    return "src_enrichment_" + hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:10]


def merge_sources(existing, discovered) -> list[dict]:
    """The opened-source list with enrichment appended, de-duplicated by URL.

    Kept as a pure function so the merge rule is testable on its own: the
    original publication always comes first and is never replaced, and a
    discovered page already present is simply skipped.
    """
    merged: list[dict] = [dict(row) for row in (existing or [])]
    seen = {str(row.get("url") or "") for row in merged}
    for row in discovered or []:
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(dict(row))
    return merged
