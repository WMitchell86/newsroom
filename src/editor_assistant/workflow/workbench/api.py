"""Isolated stdlib JSON adapter for the editor-facing ``/api/v1`` contract."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

from editor_assistant.drafting.model_policy import PolicyError
from editor_assistant.workflow import (
    draft_material,
    editor_queries,
    rewrite_feedback,
    story_editor_metadata,
)
from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import editor_source_settings as sources_settings
from editor_assistant.workflow.workbench import newsroom as wb_newsroom

LOG = logging.getLogger(__name__)
MAX_BODY_BYTES = 1_000_000
STORY_ID_RE = re.compile(r"s[a-zA-Z0-9_-]{1,127}\Z")
ARTICLE_ID_RE = re.compile(r"art_[a-z0-9]+(?:_[0-9]+)?\Z")
_JSON = "application/json; charset=utf-8"
_MESSAGES = {
    "VALIDATION_ERROR": "Проверете подадените данни.",
    "NOT_FOUND": "Заявеният ресурс не е намерен.",
    "INVALID_TRANSITION": "Това действие не е налично в текущото състояние.",
    # §R4: research owns its own codes so each branch can carry a truthful
    # sentence. `INVALID_TRANSITION` above belongs to Article lifecycle refusals.
    "RESEARCH_NOT_APPLICABLE": "Проучването не е налично за тази Story.",
    "ARTICLE_VERSION_CONFLICT": "Черновата е променена в друга сесия. Няма загубени локални промени.",
    # V1.2-G4.1 §B6: the ONE real Draft blocker. The old four-way split of
    # BLOCKING_GAP / NO_CONFIRMED_FACTS / NO_OPEN_SOURCE is gone — an unresolved
    # question is a warning on the Draft, not a refusal to start it. What is
    # left is "there is genuinely nothing to write from", one honest sentence.
    "NO_DRAFT_MATERIAL": draft_material.NO_MATERIAL_MESSAGE,
    "STORY_UNASSESSED": "За чернова първо е нужно проучване на историята.",
    "FOCUS_NOT_CONFIRMED": "Добавете редакционен фокус, за да създадете чернова.",
    "NOT_IN_PREPARATION": "Черновата не е налична в текущото състояние на статията.",
    "STORY_UNAVAILABLE": "Историята на статията вече не е достъпна.",
    "ARTICLE_HAS_TEXT": "Статията вече има текст.",
    "WORKING_TITLE_REQUIRED": "Работното заглавие не може да е празно.",
    "SAFETY_BLOCKED": "Проверката за безопасност спря операцията.",
    "SOURCE_UNAVAILABLE": "Източникът временно не е наличен.",
    # V1.2-G2.2 §3: an operational refusal to research is NOT an evidence
    # statement. The editor is told the capability is unavailable, never that a
    # source is missing and never that a quota of evidence was reached.
    "RESEARCH_UNAVAILABLE": "Автоматичното проучване временно не е налично.",
    "RESEARCH_QUOTA_EXHAUSTED": "Достигнат е лимитът за автоматично проучване на тази история.",
    # §R4: the branches that used to collapse into one generic sentence. Each
    # names a different real outcome, so the editor can tell "no page opened"
    # from "pages opened but nothing is confirmed" from "try again".
    "RESEARCH_NO_SOURCE": "Не успяхме да отворим подходящ източник.",
    "RESEARCH_NOT_CONFIRMED": (
        "Намерени са източници, но информацията още не е достатъчно потвърдена."
    ),
    "RESEARCH_INTERRUPTED": "Проучването прекъсна поради технически проблем. Опитайте отново.",
    "INTERNAL_ERROR": "Вътрешна грешка. Опитайте отново.",
}


class ApiError(ValueError):
    def __init__(self, status: int, code: str, message: str, *, field_errors=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field_errors = list(field_errors or [])


def owns_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _path_parts(handler: BaseHTTPRequestHandler) -> list[str]:
    path = urllib.parse.urlparse(handler.path).path
    return [urllib.parse.unquote(part) for part in path.split("/") if part]


def _query_scope(handler: BaseHTTPRequestHandler) -> str:
    """V1.2-G4.1 §A4 — the desk scope, defaulting to the regional working view.

    An unknown value is a client error, exactly as it is for every other filter
    on this API: silently falling back would make the desk show something other
    than what the editor asked for without saying so.
    """
    values = _query(handler, {"scope"})
    scope = values.get("scope", editor_queries.SCOPE_REGION)
    if scope not in editor_queries.TODAY_SCOPES:
        raise ApiError(400, "VALIDATION_ERROR", "Нямате право да използвате този филтър.")
    return scope


def _query(handler: BaseHTTPRequestHandler, allowed: set[str]) -> dict[str, str]:
    parsed = urllib.parse.parse_qs(
        urllib.parse.urlparse(handler.path).query, keep_blank_values=True
    )
    unknown = sorted(set(parsed) - allowed)
    if unknown:
        raise ApiError(400, "VALIDATION_ERROR", "Нямате право да използвате този филтър.")
    values = {}
    for key, rows in parsed.items():
        if len(rows) != 1:
            raise ApiError(400, "VALIDATION_ERROR", "Филтърът е зададен повече от веднъж.")
        values[key] = rows[0].strip()
    return values


def _enum(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ApiError(400, "VALIDATION_ERROR", f"Невалиден {label}.")
    return value


def _identifier(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise ApiError(400, "VALIDATION_ERROR", f"Невалиден {label}.")
    return value


def _body_required(handler: BaseHTTPRequestHandler) -> bool:
    raw_length = handler.headers.get("Content-Length", "0").strip()
    try:
        return int(raw_length) > 0
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "Размерът на заявката е невалиден.") from exc


def _body(handler: BaseHTTPRequestHandler, required: set[str]) -> dict:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ApiError(400, "VALIDATION_ERROR", "Очаква се JSON съдържание.")
    raw_length = handler.headers.get("Content-Length")
    try:
        length = int(raw_length or "")
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "Размерът на заявката е невалиден.") from exc
    if length < 0 or length > MAX_BODY_BYTES:
        raise ApiError(400, "VALIDATION_ERROR", "Заявката е твърде голяма.")
    try:
        raw = handler.rfile.read(length)
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite number")),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ApiError(400, "VALIDATION_ERROR", "JSON заявката е невалидна.") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "VALIDATION_ERROR", "JSON заявката трябва да е обект.")
    unknown = sorted(set(value) - required)
    missing = sorted(required - set(value))
    if unknown or missing:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Съдържанието на заявката не съответства на действието.",
            field_errors=[{"field": name} for name in unknown + missing],
        )
    return value


def _body_partial(handler: BaseHTTPRequestHandler, allowed: set[str]) -> dict:
    """A body carrying **some** of `allowed`, and nothing else.

    The exact-match `_body` is right for a command that takes one fixed shape.
    A partial update is different: `Следи се`, `Надежден за факти`, `Приоритет`
    and the name are independent editor actions, and a row must be editable one
    field at a time. The key set is still closed, so no unregistered field can be
    reached — the refusal is on the name, not on completeness (§10, §32).
    """
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ApiError(400, "VALIDATION_ERROR", "Очаква се JSON съдържание.")
    try:
        length = int(handler.headers.get("Content-Length") or "")
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "Размерът на заявката е невалиден.") from exc
    if length < 0 or length > MAX_BODY_BYTES:
        raise ApiError(400, "VALIDATION_ERROR", "Заявката е твърде голяма.")
    try:
        value = json.loads(
            handler.rfile.read(length).decode("utf-8"),
            parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("non-finite number")),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ApiError(400, "VALIDATION_ERROR", "JSON заявката е невалидна.") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "VALIDATION_ERROR", "JSON заявката трябва да е обект.")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Тези полета не могат да се променят.",
            field_errors=[{"field": name} for name in unknown],
        )
    if not value:
        raise ApiError(400, "VALIDATION_ERROR", "Няма какво да се промени.")
    return value


def _string(value, field: str, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} трябва да е текст.")
    if required and not value.strip():
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} е задължително.")
    if len(value) > maximum:
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} е твърде дълго.")
    return value


def _int(value, field: str, *, minimum: int, maximum: int | None = None) -> int:
    """A positive whole number from a query parameter.

    V1.2-G4.14. A page number is not optional-but-loose: `page=0` or `page=abc`
    would otherwise become a silent clamp, and the editor would be looking at
    page 2 wondering what happened to the rows they filtered. A bad page is a
    client error here, exactly like an unknown filter.
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} трябва да е цяло число.") from None
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} е извън допустимия обхват.")
    return parsed


def _version(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError(400, "VALIDATION_ERROR", "Очакваната версия трябва да е цяло число.")
    return value


# ---------- V1.2-G4: Settings / Sources ----------


#: §26. `/settings/sources/{id}` is the only path with a free-form id, so the id
#: is constrained to the registry's own slug shape rather than to the Story or
#: Article patterns used elsewhere.
SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")


def _source_id(value: str) -> str:
    if not SOURCE_ID_RE.match(value):
        raise ApiError(404, "NOT_FOUND", "Източникът не е намерен.")
    return value


def _sources_error(exc: sources_settings.SourceSettingsError) -> ApiError:
    """A registry refusal becomes the editor's own sentence, with a 4xx.

    The service already speaks editor language (§20); this only picks the status.
    A missing source is a genuine 404; everything else is a bad request, because
    the SPA must never be able to reach the store with an invalid change.
    """
    if isinstance(exc, sources_settings.SourceNotFound):
        return ApiError(404, "NOT_FOUND", exc.message)
    return ApiError(
        400,
        "VALIDATION_ERROR",
        exc.message,
        field_errors=[{"field": exc.field}] if exc.field else None,
    )


def _sources_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except sources_settings.SourceSettingsError as exc:
        raise _sources_error(exc) from exc


def _list_sources() -> dict:
    return _sources_call(sources_settings.list_sources)


def _create_source(handler: BaseHTTPRequestHandler) -> dict:
    """`+ Добави източник`. Every field is explicit; nothing is inferred here."""
    body = _body(handler, {"name", "address", "kind", "monitored", "factualAuthority", "priority"})
    return _sources_call(
        sources_settings.add_source,
        name=_string(body["name"], "name", maximum=120),
        address=_string(body["address"], "address", maximum=500, required=False),
        kind=_string(body["kind"], "kind", maximum=40),
        monitored=body["monitored"],
        factual_authority=body["factualAuthority"],
        priority=_string(body["priority"], "priority", maximum=20),
    )


def _update_source(handler: BaseHTTPRequestHandler, source_id: str) -> dict:
    """`Редактирай` and both toggles (§10).

    The four settable fields are one flat body rather than a sub-resource per
    field, so a row can never be half-updated by a client that sends two
    requests. Unknown keys are refused, which is what keeps a frontend from
    reaching `source_id`, `collector` or any other registry field (§10, §32).
    """
    body = _body_partial(handler, {"name", "monitored", "factualAuthority", "priority"})
    changes: dict = {}
    if "name" in body:
        changes["name"] = _string(body["name"], "name", maximum=120)
    if "monitored" in body:
        changes["monitored"] = body["monitored"]
    if "factualAuthority" in body:
        changes["factualAuthority"] = body["factualAuthority"]
    if "priority" in body:
        changes["priority"] = _string(body["priority"], "priority", maximum=20)
    return _sources_call(sources_settings.update_source, _source_id(source_id), changes)


def _feedback_call(fn, *args, **kwargs):
    """A refused decision is the client's error, with the service's own sentence."""
    try:
        return fn(*args, **kwargs)
    except rewrite_feedback.FeedbackError as exc:
        raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc


def _proposal_json(row: dict) -> dict:
    """One analyzer proposal in the editor's own vocabulary.

    The service speaks the CLI's snake_case; the SPA speaks camelCase. The API
    is where that translation belongs, so neither side has to know the other's
    field names and the service stays the CLI's own contract.
    """
    return {
        "patternId": str(row.get("pattern_id") or ""),
        "label": str(row.get("label") or ""),
        "target": str(row.get("target") or ""),
        "support": int(row.get("support") or 0),
        "total": int(row.get("total") or 0),
        "examples": [str(item) for item in (row.get("examples") or [])],
        "suggestedInstruction": str(row.get("suggested_instruction") or ""),
        "status": str(row.get("status") or "proposed"),
    }


def _instruction_json(row: dict) -> dict:
    """One approved (or rejected) instruction in the editor's vocabulary."""
    return {
        "patternId": str(row.get("pattern_id") or ""),
        "target": str(row.get("target") or ""),
        "instruction": str(row.get("instruction") or ""),
        "support": int(row.get("support") or 0),
        "approved": bool(row.get("approved")),
        "decidedAt": str(row.get("decided_at") or ""),
    }


def _read_feedback() -> dict:
    """The controlled learning loop as the Settings screen reads it.

    A pure read: it runs the deterministic analyzer and the approved-instruction
    read and changes nothing. Proposals are reported only once the threshold is
    reached, so the screen can never offer a decision the service would refuse.
    """
    eligible = rewrite_feedback.is_eligible()
    return {
        "pending": len(rewrite_feedback.unprocessed()),
        "threshold": rewrite_feedback.threshold(),
        "eligible": eligible,
        "proposals": [
            _proposal_json(row) for row in (rewrite_feedback.analyze() if eligible else [])
        ],
        "instructions": [
            _instruction_json(row) for row in rewrite_feedback.approved_instructions()
        ],
    }


def _decide_feedback(handler: BaseHTTPRequestHandler) -> dict:
    """`Одобри` / `Отхвърли` — a human decision about ONE proposal.

    The client sends a `patternId` and an `approved` flag, and nothing else. It
    never sends the instruction text: the server re-analyzes and decides the
    pattern the analyzer actually found (`decide_proposal`), so a frontend can
    never invent a rule, only decide a real one. The whole new state comes back,
    so the screen never has to guess what changed.
    """
    body = _body(handler, {"patternId", "approved"})
    if not isinstance(body["approved"], bool):
        raise ApiError(400, "VALIDATION_ERROR", "Решението трябва да е вярно или невярно.")
    entry = _feedback_call(
        rewrite_feedback.decide_proposal,
        _string(body["patternId"], "patternId", maximum=64),
        approved=body["approved"],
    )
    return {"decision": _instruction_json(entry), **_read_feedback()}


def _review(handler: BaseHTTPRequestHandler, story_id: str) -> dict:
    body = _body(handler, {"observedDevelopmentIds"})
    observed = body["observedDevelopmentIds"]
    if not isinstance(observed, list) or len(observed) > 100:
        raise ApiError(400, "VALIDATION_ERROR", "Наблюдаваните развития трябва да бъдат списък.")
    for value in observed:
        if not isinstance(value, str) or len(value) > 64:
            raise ApiError(400, "VALIDATION_ERROR", "Наблюдаваното развитие е невалидно.")
    try:
        return app.review_story(story_id, observed)
    except story_editor_metadata.StoryEditorMetadataError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "Наблюдаваните развития не са валидни.") from exc


def _update_models(handler: BaseHTTPRequestHandler) -> dict:
    """`AI и модели` — the operator's own paid-model switch.

    V1.2-G4.39. The budget is optional so a client can flip the switch without
    restating the budget it already has; when it IS sent it is bounded here and
    nowhere else, because this is the boundary an operator types a number into.

    A non-boolean `paidEnabled` is refused rather than coerced. `"false"` is
    truthy in Python, and a screen that silently read the operator's words as
    "turn paid models ON" is the worst possible failure for this switch.
    """
    body = _body_partial(handler, {"paidEnabled", "softPaidBudgetUsdDay"})
    if "paidEnabled" not in body:
        raise ApiError(400, "VALIDATION_ERROR", "Избери дали платените модели са разрешени.")
    enabled = body["paidEnabled"]
    if not isinstance(enabled, bool):
        raise ApiError(
            400, "VALIDATION_ERROR", "Разрешаването на платени модели е вярно или невярно."
        )
    budget = None
    if "softPaidBudgetUsdDay" in body and body["softPaidBudgetUsdDay"] is not None:
        value = body["softPaidBudgetUsdDay"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(400, "VALIDATION_ERROR", "Дневният платен бюджет е число в USD.")
        budget = float(value)
    try:
        return wb_newsroom.set_paid_models(paid_enabled=enabled, soft_paid_budget_usd_day=budget)
    except PolicyError as exc:
        raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc


def _focus(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    body = _body(handler, {"focus"})
    return app.update_focus(article_id, _string(body["focus"], "focus", maximum=4_000))


def _title(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    body = _body(handler, {"expectedVersion", "title"})
    return app.update_title(
        article_id,
        _version(body["expectedVersion"]),
        _string(body["title"], "title", maximum=500),
    )


def _content(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    body = _body(handler, {"expectedVersion", "title", "body"})
    return app.save_content(
        article_id,
        _version(body["expectedVersion"]),
        _string(body["title"], "title", maximum=500),
        _string(body["body"], "body", maximum=500_000, required=False),
    )


def _voice(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    """`Стил` — the optional Voice choice (§D). Empty string = automatic."""
    body = _body(handler, {"voice"})
    return app.update_voice(article_id, _string(body["voice"], "voice", maximum=64, required=False))


def _rewrite(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    """`Пренапиши` — the editor's comment is the whole request body."""
    # V1.2-G4.18. `mode` and `length` are the editor's controls over a rewrite.
    # Both are optional and both are validated against what the product offers:
    # an unknown value is a client error, never a silent fallback to the
    # auto-suggested one — which is the behaviour that made "разшири" come back
    # shorter.
    #
    # V1.2-G4.18 fix: the closed key set belongs to `_body_partial`, NOT to
    # `_body`. `_body` demands an EXACT match, so it also demanded that `mode`
    # and `length` be PRESENT — and the client deliberately omits a control the
    # editor did not touch ("Only the keys the editor actually chosen travel.
    # Sending empty values would be a claim that they were set"). The two
    # defaults therefore met in the middle and every ordinary rewrite came back
    # `400 VALIDATION_ERROR`: the editor who left both selects alone, and the
    # editor who set only one of them, were both refused by a field they never
    # had. Measured through the real HTTP server, not inferred: shapes
    # `{comment}`, `{comment, length}` and `{comment, mode}` were all 400, while
    # `{comment, mode, length}` was 202. The controls were unreachable in
    # exactly the case they exist for.
    #
    # So: the key set stays closed (an unregistered field is still a 400), the
    # comment stays required, and the two controls are genuinely optional.
    body = _body_partial(handler, {"comment", "mode", "length"})
    key = handler.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
        raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is required.")
    mode = ""
    if str(body.get("mode") or "").strip():
        mode = _enum(str(body["mode"]).strip(), app.EDITING_MODES, "режим")
    length = ""
    if str(body.get("length") or "").strip():
        length = _enum(str(body["length"]).strip(), app.REWRITE_LENGTHS, "дължина")
    return 202, {
        "operationToken": app.start_article_rewrite(
            article_id,
            _string(body.get("comment", ""), "comment", maximum=4000),
            idempotency_key=key,
            mode=mode,
            length=length,
        )["operationToken"]
    }


def _ready(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    """`Отбележи като готова` — the client sends only the version it observed."""
    body = _body(handler, {"expectedVersion"})
    return app.mark_article_ready(article_id, _version(body["expectedVersion"]))


def _reopen(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    """`Редактирай` from `Готова` — a decision, not a content edit.

    The client sends nothing: there is no version to negotiate, because
    reopening never changes the content.
    """
    if _body_required(handler):
        body = _body(handler, set())
        if body:
            raise ApiError(400, "VALIDATION_ERROR", "Редактирането не приема полета.")
    return app.reopen_article(article_id)


def _finalize(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    """`Финализирай` — the client sends the version it observed, nothing else.

    The server recomputes the current validation and compares its digest with
    the recorded readiness digest; a client-supplied digest is never authority.
    """
    body = _body(handler, {"expectedVersion"})
    key = handler.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
        raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is required.")
    return app.finalize_article(article_id, _version(body["expectedVersion"]), idempotency_key=key)


def _resource(method: str, handler: BaseHTTPRequestHandler) -> tuple[int, object] | None:
    parts = _path_parts(handler)
    prefix = ["api", "v1"]
    if parts == [*prefix, "today"] and method == "GET":
        return 200, app.read_today(_query_scope(handler))
    if parts == [*prefix, "health"] and method == "GET":
        # V1.2-G4.5. The health verdict belongs where the editor works, not only
        # in a terminal: a pure read, no provider call, no spend.
        return 200, app.read_health()
    if parts == [*prefix, "today", "refresh"] and method == "POST":
        key = handler.headers.get("Idempotency-Key", "").strip()
        if key and (len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key)):
            raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is invalid.")
        return 202, {
            "operationToken": app.start_newsroom_refresh(idempotency_key=key)["operationToken"]
        }
    if parts == [*prefix, "today", "quick-drafts"] and method == "POST":
        # V1.2-G4.40 «Направи чернови». One bounded press over the desk. The
        # Idempotency-Key is REQUIRED for the same reason it is on `Обнови` and
        # on a single Quick Draft: a double click, a browser retry and a
        # returning editor must all address the same run instead of spending a
        # second set of model calls on the same Stories. No body: the cap is the
        # server's decision, not the client's.
        if _body_required(handler):
            body = _body(handler, set())
            if body:
                raise ApiError(400, "VALIDATION_ERROR", "Операцията не приема полета.")
        key = handler.headers.get("Idempotency-Key", "").strip()
        if not key or len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
            raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is required.")
        return 202, {
            "operationToken": app.start_desk_quick_drafts(
                idempotency_key=key, scope=_query_scope(handler)
            )["operationToken"]
        }
    if parts == [*prefix, "stories", "hint"] and method == "POST":
        # V1.2-G4.20 «Започни от идея». The hint is a search query; the pages it
        # opens become ordinary Stories. Nothing here writes a provenance
        # record the editor did not earn by naming a real page.
        body = _body(handler, {"hint"})
        return 200, app.seed_stories_from_hint(_string(body.get("hint"), "hint", maximum=300))
    if parts == [*prefix, "stories"] and method == "GET":
        query = _query(handler, {"filter", "query", "page", "per_page"})
        filter_name = _enum(query.get("filter", "all"), app.STORY_FILTERS, "филтър")
        search = _string(query.get("query", ""), "query", maximum=200, required=False)
        # V1.2-G4.14. Server-side paging. Measured: the corpus is 445 stories
        # and the unfiltered list was a single 320 KB response carrying a full
        # summary for every one of them, fetched on every visit. Paging only in
        # the browser would still have downloaded all of it; the bytes are the
        # problem, not just the rows on screen.
        page = _int(query.get("page", "1"), "page", minimum=1)
        per_page = _int(
            query.get("per_page", str(app.STORY_PAGE_SIZE)), "per_page", minimum=1, maximum=200
        )
        # The page and its total come from ONE call. Reading the total from
        # shared state after the fact let a threaded server answer page 1 with
        # a number belonging to a request that started in between.
        rows, total, counts = app.list_stories_page(
            filter_name, search, page=page, per_page=per_page
        )
        return 200, {
            "stories": rows,
            # V1.2-G4.7. The four filters read as a partition of the corpus and
            # are not one. Sending the counts with the list is what lets the nav
            # stop implying a split it does not have.
            "counts": counts,
            "total": total,
            "page": page,
            "perPage": per_page,
        }
    # `hint` is a reserved subpath, not a story id (V1.2-G4.20). Without this
    # guard a GET on /stories/hint fell through here, was parsed as a story
    # id, and answered "Няма намерен Story" — a 400 that describes a missing
    # story, for a request that never asked about one.
    if len(parts) in (4, 5) and parts[:3] == [*prefix, "stories"] and parts[3] != "hint":
        story_id = _identifier(parts[3], STORY_ID_RE, "Story")
        if method == "GET" and len(parts) == 4:
            return 200, app.read_story(story_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "articles":
            if _body_required(handler):
                body = _body(handler, set())
                if body:
                    raise ApiError(400, "VALIDATION_ERROR", "Началото на статия не приема полета.")
            key = handler.headers.get("Idempotency-Key", "").strip()
            if not key or len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
                raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is required.")
            return 201, app.start_article(story_id, idempotency_key=key)
        if method == "POST" and len(parts) == 5 and parts[4] == "review":
            return 200, _review(handler, story_id)
        if method == "PUT" and len(parts) == 5 and parts[4] == "follow":
            return 200, app.follow_story(story_id, True)
        if method == "DELETE" and len(parts) == 5 and parts[4] == "follow":
            return 200, app.follow_story(story_id, False)
        if method == "POST" and len(parts) == 5 and parts[4] == "ignore":
            return 200, app.ignore_story(story_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "research":
            key = handler.headers.get("Idempotency-Key", "").strip()
            if key and (len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key)):
                raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is invalid.")
            return 202, {
                "operationToken": app.start_story_research(story_id, idempotency_key=key)[
                    "operationToken"
                ]
            }
        if method == "POST" and len(parts) == 5 and parts[4] == "quick-draft":
            # §5/§12: one orchestration command, one operation token, and a
            # REQUIRED Idempotency-Key so a double click, a browser retry and a
            # returning editor all address the same Quick Draft.
            if _body_required(handler):
                body = _body(handler, set())
                if body:
                    raise ApiError(400, "VALIDATION_ERROR", "Черновата не приема полета.")
            key = handler.headers.get("Idempotency-Key", "").strip()
            if not key or len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
                raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is required.")
            return 202, {
                "operationToken": app.start_quick_draft(story_id, idempotency_key=key)[
                    "operationToken"
                ]
            }
    if len(parts) == 3 and parts[:3] == [*prefix, "operations"] and method == "GET":
        # The index an editor needs after asking for several things at once.
        # V1.2-G4.38: through the application projection, so every row carries a
        # topic and a link. `recent()` alone returned the raw scope — an
        # internal id, and not a place. Measured: 2 of the 6 scope shapes the
        # application creates produced a link at all.
        return 200, app.list_operations()
    if len(parts) == 4 and parts[:3] == [*prefix, "operations"] and method == "GET":
        return 200, app.operation_status(
            _identifier(parts[3], re.compile(r"op_[0-9a-f]{24}\Z"), "операция")
        )
    if parts == [*prefix, "articles"] and method == "GET":
        query = _query(handler, {"filter", "query"})
        filter_name = _enum(query.get("filter", "all"), app.ARTICLE_FILTERS, "филтър")
        search = _string(query.get("query", ""), "query", maximum=200, required=False)
        return 200, {"articles": app.list_articles(filter_name, search)}
    if len(parts) in (4, 5) and parts[:3] == [*prefix, "articles"]:
        article_id = _identifier(parts[3], ARTICLE_ID_RE, "статия")
        if method == "GET" and len(parts) == 4:
            return 200, app.read_article(article_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "draft":
            if _body_required(handler):
                body = _body(handler, set())
                if body:
                    raise ApiError(400, "VALIDATION_ERROR", "Черновата не приема полета.")
            key = handler.headers.get("Idempotency-Key", "").strip()
            if not key or len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
                raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is required.")
            return 202, {
                "operationToken": app.start_article_draft(article_id, idempotency_key=key)[
                    "operationToken"
                ]
            }
        if method == "PUT" and len(parts) == 5 and parts[4] == "focus":
            return 200, _focus(handler, article_id)
        if method == "PUT" and len(parts) == 5 and parts[4] == "voice":
            # §D: the optional Voice choice. Progressive disclosure in the UI,
            # one authoritative write here.
            return 200, _voice(handler, article_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "rewrite":
            # §E: `Пренапиши`. The editor's own words are the entire request.
            return _rewrite(handler, article_id)
        if method == "PUT" and len(parts) == 5 and parts[4] == "title":
            return 200, _title(handler, article_id)
        if method == "PUT" and len(parts) == 5 and parts[4] == "content":
            return 200, _content(handler, article_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "ready":
            # `Отбележи като готова`. The client sends only the version it
            # observed; it never sends warnings, a digest or an override flag.
            return 200, _ready(handler, article_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "reopen":
            # `Редактирай` from `Готова`. No body, no confirmation dialog.
            return 200, _reopen(handler, article_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "finalize":
            # `Финализирай`. Finalization only - never publishing.
            return 200, _finalize(handler, article_id)
    if parts == [*prefix, "archive"] and method == "GET":
        query = _query(handler, {"query"})
        search = _string(query.get("query", ""), "query", maximum=200, required=False)
        return 200, {"articles": app.list_archive(search)}
    # V1.2-G4 §26. Three thin endpoints around the existing registry service.
    # Deliberately no DELETE: §11 requires proven historical-reference safety
    # first, and `Изключи` already covers the editor's real need.
    if parts == [*prefix, "settings", "sources"]:
        if method == "GET":
            return 200, _list_sources()
        if method == "POST":
            return 201, _create_source(handler)
    if len(parts) == 5 and parts[:4] == [*prefix, "settings", "sources"] and method == "PUT":
        return 200, _update_source(handler, parts[4])
    # V1.2-G4.3 §G, now reachable from the editor's own Settings screen. The
    # learning loop existed but only a terminal could drive it; these two routes
    # are the same service, so a decision made here and one made by the CLI are
    # the same decision.
    if parts == [*prefix, "settings", "feedback"] and method == "GET":
        return 200, _read_feedback()
    if parts == [*prefix, "settings", "feedback", "decisions"] and method == "POST":
        return 200, _decide_feedback(handler)
    # V1.2-G4.39 `AI и модели`. The paid-model switch already existed and worked
    # on the server-rendered `/models` page; this is the same decision over the
    # editor's own JSON boundary, through the same service, so it is the same
    # `var/model_policy.json` diff either way.
    if parts == [*prefix, "settings", "models"] and method == "GET":
        return 200, wb_newsroom.read_model_settings()
    if parts == [*prefix, "settings", "models"] and method == "PUT":
        return 200, _update_models(handler)
    if len(parts) == 4 and parts[:3] == [*prefix, "archive"] and method == "GET":
        article_id = _identifier(parts[3], ARTICLE_ID_RE, "статия")
        rows = [row for row in app.list_archive() if row["id"] == article_id]
        if not rows:
            raise ApiError(404, "NOT_FOUND", "Финализираната статия не е намерена.")
        return 200, rows[0]
    return None


def _method_not_allowed() -> ApiError:
    return ApiError(405, "VALIDATION_ERROR", "Този HTTP метод не се поддържа тук.")


def _known_resource_path(parts: list[str]) -> bool:
    prefix = ["api", "v1"]
    if parts in (
        [*prefix, "today"],
        [*prefix, "today", "refresh"],
        # V1.2-G4.40: known so a GET on it is 405, not a misleading 404.
        [*prefix, "today", "quick-drafts"],
        [*prefix, "health"],
        [*prefix, "stories"],
        # V1.2-G4.20: known so a GET on it is 405, not a misleading 404.
        [*prefix, "stories", "hint"],
        [*prefix, "articles"],
        [*prefix, "archive"],
        [*prefix, "settings", "sources"],
        # V1.2-G4.3 §G: known so a GET on `decisions` is 405, not a 404.
        [*prefix, "settings", "feedback"],
        [*prefix, "settings", "feedback", "decisions"],
        # V1.2-G4.39: known so a POST on it is 405, not a misleading 404.
        [*prefix, "settings", "models"],
    ):
        return True
    if len(parts) == 5 and parts[:4] == [*prefix, "settings", "sources"]:
        return True
    if len(parts) == 4 and parts[:3] == [*prefix, "operations"]:
        return True
    if len(parts) == 4 and parts[:3] in (
        [*prefix, "stories"],
        [*prefix, "articles"],
        [*prefix, "archive"],
    ):
        return True
    return len(parts) == 5 and parts[:3] in ([*prefix, "stories"], [*prefix, "articles"])


def _request_line(handler: BaseHTTPRequestHandler, method: str) -> str:
    """A loggable, secret-free identity for one request.

    The Idempotency-Key is never logged: it is a capability the editor's own
    request carries, and a log is exactly the place it should not accumulate.
    Only the path is kept, and only after long opaque ids are collapsed, so a
    log line identifies the Article without restating a token.
    """
    path = getattr(handler, "path", "") or ""
    parts = [p for p in path.split("?")[0].split("/") if p]
    return "/" + "/".join(f"{p[:6]}…" if len(p) > 24 else p for p in parts)


def dispatch(handler: BaseHTTPRequestHandler, method: str) -> None:
    started = time.monotonic()
    try:
        resource = _resource(method, handler)
        if resource is None:
            parts = _path_parts(handler)
            if _known_resource_path(parts):
                raise _method_not_allowed()
            if parts in (["api"], ["api", "v1"]):
                raise ApiError(404, "NOT_FOUND", "API ресурсът не е намерен.")
            if parts[:2] == ["api", "v1"]:
                raise ApiError(404, "NOT_FOUND", "API ресурсът не е намерен.")
            raise ApiError(404, "NOT_FOUND", "API ресурсът не е намерен.")
        status, data = resource
        _respond(handler, status, {"data": data})
    except ApiError as exc:
        _error(handler, exc.status, exc.code, exc.message, field_errors=exc.field_errors)
    except app.EditorApplicationError as exc:
        # Blocking validation returns the editor-safe warnings the workspace
        # needs to explain what must be addressed - never a raw audit trace.
        _error(
            handler,
            exc.status,
            exc.code,
            str(exc),
            warnings=getattr(exc, "warnings", None),
        )
    except Exception:
        LOG.exception("Unhandled editor API failure")
        _error(handler, 500, "INTERNAL_ERROR", _MESSAGES["INTERNAL_ERROR"])
    finally:
        # Every editor click lands here, so a run can be reconstructed after the
        # fact instead of inferred from model usage records. The status is read
        # back off the handler because the response may have been refused before
        # anything was written.
        LOG.info(
            "%s %s -> %s in %dms",
            method,
            _request_line(handler, method),
            getattr(handler, "_editor_status", "?"),
            int((time.monotonic() - started) * 1000),
        )


def _respond(handler: BaseHTTPRequestHandler, status: int, value: object) -> None:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler._editor_status = status
    handler.send_response(status)
    handler.send_header("Content-Type", _JSON)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        # The client hung up before the response was written - a closed tab, a
        # navigation away, a proxy timeout. That is the CLIENT's disconnect,
        # not a server fault, and letting it propagate took the whole workbench
        # process down: one abandoned request killed the editor for everyone
        # until someone restarted it. Nothing can be delivered now, so the
        # honest thing is to let this request end and keep serving.
        LOG.debug("client disconnected before the response was written")


def _error(
    handler: BaseHTTPRequestHandler,
    status: int,
    code: str,
    message: str,
    *,
    field_errors=None,
    warnings=None,
) -> None:
    _respond(
        handler,
        status,
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": code in {"INTERNAL_ERROR", "SOURCE_UNAVAILABLE"},
                "fieldErrors": list(field_errors or []),
                **({"warnings": [dict(row) for row in warnings]} if warnings else {}),
            }
        },
    )
