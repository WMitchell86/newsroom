"""Isolated stdlib JSON adapter for the editor-facing ``/api/v1`` contract."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler

from editor_assistant.workflow import editor_application as app
from editor_assistant.workflow import story_editor_metadata

LOG = logging.getLogger(__name__)
MAX_BODY_BYTES = 1_000_000
STORY_ID_RE = re.compile(r"s[a-zA-Z0-9_-]{1,127}\Z")
ARTICLE_ID_RE = re.compile(r"art_[a-z0-9]+(?:_[0-9]+)?\Z")
_JSON = "application/json; charset=utf-8"
_MESSAGES = {
    "VALIDATION_ERROR": "Проверете подадените данни.",
    "NOT_FOUND": "Заявеният ресурс не е намерен.",
    "INVALID_TRANSITION": "Това действие не е налично в текущото състояние.",
    "ARTICLE_VERSION_CONFLICT": "Черновата е променена в друга сесия. Няма загубени локални промени.",
    "BLOCKING_GAP": "Има непопълнена информация, която пречи да продължите.",
    "SAFETY_BLOCKED": "Проверката за безопасност спря операцията.",
    "SOURCE_UNAVAILABLE": "Източникът временно не е наличен.",
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


def _string(value, field: str, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} трябва да е текст.")
    if required and not value.strip():
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} е задължително.")
    if len(value) > maximum:
        raise ApiError(400, "VALIDATION_ERROR", f"Полето {field} е твърде дълго.")
    return value


def _version(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError(400, "VALIDATION_ERROR", "Очакваната версия трябва да е цяло число.")
    return value


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


def _ready(handler: BaseHTTPRequestHandler, article_id: str) -> dict:
    """`Отбележи като готова` — the client sends only the version it observed."""
    body = _body(handler, {"expectedVersion"})
    return app.mark_article_ready(article_id, _version(body["expectedVersion"]))


def _resource(method: str, handler: BaseHTTPRequestHandler) -> tuple[int, object] | None:
    parts = _path_parts(handler)
    prefix = ["api", "v1"]
    if parts == [*prefix, "today"] and method == "GET":
        return 200, app.read_today()
    if parts == [*prefix, "today", "refresh"] and method == "POST":
        key = handler.headers.get("Idempotency-Key", "").strip()
        if key and (len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key)):
            raise ApiError(400, "VALIDATION_ERROR", "Idempotency key is invalid.")
        return 202, {
            "operationToken": app.start_newsroom_refresh(idempotency_key=key)["operationToken"]
        }
    if parts == [*prefix, "stories"] and method == "GET":
        query = _query(handler, {"filter", "query"})
        filter_name = _enum(query.get("filter", "all"), app.STORY_FILTERS, "филтър")
        search = _string(query.get("query", ""), "query", maximum=200, required=False)
        return 200, {"stories": app.list_stories(filter_name, search)}
    if len(parts) in (4, 5) and parts[:3] == [*prefix, "stories"]:
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
        if method == "PUT" and len(parts) == 5 and parts[4] == "title":
            return 200, _title(handler, article_id)
        if method == "PUT" and len(parts) == 5 and parts[4] == "content":
            return 200, _content(handler, article_id)
        if method == "POST" and len(parts) == 5 and parts[4] == "ready":
            # `Отбележи като готова`. The client sends only the version it
            # observed; it never sends warnings, a digest or an override flag.
            return 200, _ready(handler, article_id)
    if parts == [*prefix, "archive"] and method == "GET":
        query = _query(handler, {"query"})
        search = _string(query.get("query", ""), "query", maximum=200, required=False)
        return 200, {"articles": app.list_archive(search)}
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
        [*prefix, "stories"],
        [*prefix, "articles"],
        [*prefix, "archive"],
    ):
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


def dispatch(handler: BaseHTTPRequestHandler, method: str) -> None:
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


def _respond(handler: BaseHTTPRequestHandler, status: int, value: object) -> None:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", _JSON)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(body)


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
