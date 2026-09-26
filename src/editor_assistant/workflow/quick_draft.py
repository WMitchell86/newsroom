"""V1.1-D2 — Quick Draft: the decision half of «Today → Чернова».

**What this module is.** One explicit editorial click, `Чернова`, on a Today
Story row. The click says: *this Story is worth turning into a straightforward
news Article — do the necessary preparation and produce a Draft if the evidence
supports it.* Everything mechanical after that decision belongs to the
application layer (`editor_application.start_quick_draft`); this module holds
only what must be **decided**, never performed.

**What this module is emphatically not.** It is not a second workflow. There is
no research implementation, no evidence model, no readiness predicate, no
prompt, no generator and no failure state here. The canonical machinery is
reused by reference:

* the Story evidence basis is `story_research_store` (V1.1-A);
* the Draft readiness decision is `article_readiness` (V1.1-B) — called, never
  re-derived;
* generation is the one C2 pipeline, reached through the shared synchronous
  worker the normal «Направи чернова» operation also runs;
* a genuine generation failure is V1.1-C's durable marker, not a new one.

**Three decisions live here, and each one is safe by construction.**

1. `default_focus` — the straight-news Focus (§13). Deterministic, Story-specific,
   built from the clean canonical Story title, and requiring no model call. It is
   NOT the old generic V1 placeholder ("Да разкажем какво се е променило…"),
   which survives only in the manual `Направи статия` screen.
2. `availability` — whether the Today row may even offer `Чернова` (§4). The
   backend is the authority; the frontend renders what this returns and derives
   nothing. Ambiguity is the important part: more than one active Article is a
   refusal, never a guess.
3. `plan` — the existing-Article resolution (§11) and the narrow result
   vocabulary (§19): `draft_created`, `existing_article`, `needs_attention`.

**One operation registry, not a second job system.** A Quick Draft is a bounded
in-process operation like Research and Draft, keyed by an Idempotency-Key and
scoped per Story, so a double click, a browser retry and a returning editor all
address the *same* operation instead of starting parallel work.
"""

from __future__ import annotations

import threading

#: Operation scope prefix. Not a Story id: it tells the shared bounded-operation
#: registry which editor wording a transport result belongs to, exactly as
#: `article_generation.SCOPE_PREFIX` does for the C2 Draft command.
SCOPE_PREFIX = "quick-draft:"

#: The one positive result of a Quick Draft: a new Draft was generated.
DRAFT_CREATED = "draft_created"
#: A Draft (or Ready) Article for this Story already existed; nothing was
#: regenerated and the editor is sent to it.
EXISTING_ARTICLE = "existing_article"
#: The canonical path could not safely complete. The real blocker travels with
#: the result; the orchestration never invents a Draft to hide it.
NEEDS_ATTENTION = "needs_attention"

#: Every status this command can end in. A closed set, so a new outcome has to
#: be classified here rather than appearing as an ad-hoc string.
RESULT_STATUSES = frozenset({DRAFT_CREATED, EXISTING_ARTICLE, NEEDS_ATTENTION})

#: Row labels. `Чернова` is the ask; the other is the backend telling the editor
#: that the work already exists and must not be repeated.
LABEL_DRAFT = "Чернова"
LABEL_OPEN_DRAFT = "Отвори чернова"

#: The ambiguity refusal (§11). Multiple Articles per Story is a supported
#: canonical feature, so the answer is a question for the editor, not a guess.
MULTIPLE_ACTIVE_ARTICLES = "MULTIPLE_ACTIVE_ARTICLES"
STORY_IGNORED = "STORY_IGNORED"

#: A generation attempt that passed readiness and then genuinely failed (§18).
#: V1.1-C already recorded it; this only names it for the editor-facing result.
DRAFT_GENERATION_FAILED = "DRAFT_GENERATION_FAILED"

#: The Editorial Focus could not be confirmed. Deliberately distinct from a
#: generation failure: no model was ever called and the Article is intact.
FOCUS_UNCONFIRMABLE = "FOCUS_UNCONFIRMABLE"
FOCUS_UNCONFIRMABLE_MESSAGE = "Фокусът на статията не може да бъде потвърден."

#: Bounded wording for a Quick Draft operation that failed in transport. Never a
#: provider message, never a prompt, never a model id.
_OPERATION_ERROR = {
    "code": DRAFT_GENERATION_FAILED,
    "message": "Черновата не можа да бъде създадена. Опитайте отново.",
    "retryable": True,
}

#: One Quick Draft per Story at a time. A second click reattaches to the running
#: operation instead of starting a second research round and a second generation.
_ACTIVE: dict[str, str] = {}
_LOCK = threading.RLock()


def scope_for(story_id: str) -> str:
    return f"{SCOPE_PREFIX}{story_id}"


def is_quick_draft_scope(scope: str) -> bool:
    return str(scope or "").startswith(SCOPE_PREFIX)


def operation_error() -> dict:
    """The bounded, sanitized error envelope for a failed Quick Draft."""
    return dict(_OPERATION_ERROR)


def active_token(story_id: str) -> str:
    """The still-pending Quick Draft for this Story, or `""`."""
    with _LOCK:
        return _ACTIVE.get(story_id, "")


def acquire(story_id: str, token: str) -> None:
    with _LOCK:
        _ACTIVE[story_id] = token


def release(story_id: str, token: str) -> None:
    with _LOCK:
        if _ACTIVE.get(story_id) == token:
            _ACTIVE.pop(story_id, None)


# --------------------------------------------------------------------------
# §13 the default straight-news Focus
# --------------------------------------------------------------------------


def _clean_title(title: str, *, limit: int = 180) -> str:
    """The Story title as a focus subject: one line, no trailing source noise.

    The canonical representative/development title is already clean, so this is
    only whitespace collapsing plus a length bound. It never rewrites the title
    and never appends a publication name: a focus that ends in "– Вестник" is the
    V1 placeholder defect in a new costume.
    """
    text = " ".join(str(title or "").split())
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def default_focus(title: str) -> str:
    """The standard straight-news Focus for a Quick Draft (§13).

    Deterministic, one sentence, Story-specific, and free of any model call: the
    click itself is the editor's confirmation of this default, which is the whole
    point of the quick path. It states the straight-news intent and nothing else
    — it invents no angle, no quote, no source and no consequence.
    """
    subject = _clean_title(title)
    if not subject:
        # No clean Story title means no honest subject. `article_readiness`
        # refuses such an Article on its own terms (WORKING_TITLE_REQUIRED), and
        # this text would never be stored for it.
        return ""
    return (
        f"Да се отрази потвърденото развитие „{subject}“ като кратка информационна "
        "новина, с акцент върху проверените факти, кога и къде се случва и "
        "значението му за читателите в региона."
    )


def is_empty_preparation(article: dict, content: dict) -> bool:
    """Whether this Article is still an empty Preparation Article.

    Deliberately the two conditions `editor_projections.derive_article_state`
    itself uses for `preparation`, evaluated without a validation digest. The
    distinction Quick Draft needs is only "is there already a Draft here?", and a
    Ready Article is never mistaken for one because it necessarily has a body.
    """
    return not str(content.get("body") or "").strip() and not article.get(
        "draft_established_version"
    )


def _active_articles(articles, story_id: str) -> list[dict]:
    """Every non-finalized Article of this Story. A finalized one is Archive."""
    return [
        article
        for article in articles
        if article.get("story_id") == story_id and not article.get("finalized_at")
    ]


# --------------------------------------------------------------------------
# §4 backend authority for the Today row
# --------------------------------------------------------------------------


def availability(*, story: dict, articles, contents) -> dict:
    """Whether the Today row may offer `Чернова`, and under which label (§4).

    The backend is the authority. The frontend renders this and derives nothing,
    so a Story the server cannot safely drive to a Draft never shows a button
    that promises it.

    Unavailable for an ignored Story and for the ambiguous case of more than one
    active Article. Deliberately *available* for an `unassessed` Story: the quick
    path researches it first, so the editor is not asked to make a decision the
    system is able to make.

    The label is a hint, never authority — the orchestration re-resolves the
    Article from canonical state when the click arrives.
    """
    ignored = story.get("status") == "IGNORED"
    active = _active_articles(articles, story["story_id"])
    if ignored or len(active) > 1:
        return {
            "available": False,
            "label": LABEL_DRAFT,
            "articleId": None,
            "reasonCode": STORY_IGNORED if ignored else MULTIPLE_ACTIVE_ARTICLES,
        }
    if not active:
        return {"available": True, "label": LABEL_DRAFT, "articleId": None, "reasonCode": None}
    article = active[0]
    article_id = article["article_id"]
    if is_empty_preparation(article, contents.get(article_id) or {}):
        return {
            "available": True,
            "label": LABEL_DRAFT,
            "articleId": article_id,
            "reasonCode": None,
        }
    return {
        "available": True,
        "label": LABEL_OPEN_DRAFT,
        "articleId": article_id,
        "reasonCode": None,
    }


# --------------------------------------------------------------------------
# §11 existing-Article resolution
# --------------------------------------------------------------------------

#: The four outcomes. Named constants, so the orchestration and its tests cannot
#: drift into inventing a fifth.
PLAN_CREATE = "create"
PLAN_REUSE = "reuse"
PLAN_EXISTING = "existing"
PLAN_AMBIGUOUS = "ambiguous"


def plan(articles, contents, story_id: str) -> dict:
    """Resolve the Article a Quick Draft should use for this Story.

    * no active Article → `create` (only reached after evidence is sufficient);
    * one empty Preparation → `reuse`, preserving a confirmed Focus;
    * one Article that already carries a Draft or is Ready → `existing`, never
      regenerated and never reopened;
    * more than one active Article → `ambiguous`. Multiple Articles per Story is
      a supported canonical feature, so this stops and asks instead of guessing.
    """
    active = _active_articles(articles, story_id)
    if not active:
        return {"outcome": PLAN_CREATE, "articleId": None}
    if len(active) > 1:
        return {"outcome": PLAN_AMBIGUOUS, "articleId": None}
    article = active[0]
    article_id = article["article_id"]
    if is_empty_preparation(article, contents.get(article_id) or {}):
        return {"outcome": PLAN_REUSE, "articleId": article_id}
    return {"outcome": PLAN_EXISTING, "articleId": article_id}


# --------------------------------------------------------------------------
# §19 the narrow, editor-facing result vocabulary
# --------------------------------------------------------------------------


def result_draft_created(article_id: str) -> dict:
    return {"status": DRAFT_CREATED, "articleId": article_id}


def result_existing_article(article_id: str) -> dict:
    return {"status": EXISTING_ARTICLE, "articleId": article_id}


def result_needs_attention(
    story_id: str, reason_code: str, message: str, *, article_id: str | None = None
) -> dict:
    """The honest stop. Never a fabricated Draft, never a generic excuse.

    `article_id` is present only when a real Preparation Article exists, so the
    editor can be sent to the recovery surface V1.1-C opened there: the retry
    «Направи чернова» plus the earned «Редактирай».

    Nothing internal crosses here — no Case id, no EvidencePacket id, no
    provider, no search operation and no model id.
    """
    return {
        "status": NEEDS_ATTENTION,
        "storyId": story_id,
        "reasonCode": str(reason_code or ""),
        "message": str(message or ""),
        **({"articleId": article_id} if article_id else {}),
    }
