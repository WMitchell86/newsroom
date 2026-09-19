"""M3A HTTP layer: stdlib http.server, no framework, Bulgarian-first responses.

Routing (paths only; query params parsed in handlers):
  GET  /                 queue (filtered by ?filter=...)
  GET  /intake           M3B YouTube intake results (display only; initiation is CLI)
  GET  /case/{case_id}   case detail
  POST /case/{case_id}/save
  POST /case/{case_id}/finalize
  POST /case/{case_id}/decision
  GET  /healthz
  POST /quit             (dev/test only; honors WB_ALLOW_QUIT)
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from editor_assistant.workflow.workbench import html as html_mod
from editor_assistant.workflow.workbench import state as wb_state

ENABLE_QUIT = os.environ.get("WB_ALLOW_QUIT", "0") not in ("0", "", "no", "false", "False")


def _post_form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    """Parse application/x-www-form-urlencoded body (multipart not required)."""
    length = handler.headers.get("Content-Length")
    body = b""
    if length:
        try:
            n = int(length)
        except ValueError:
            n = 0
        if n > 0:
            body = handler.rfile.read(n)
    if not body:
        return {}
    return urllib.parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)


def _first(form: dict[str, list[str]], key: str, default: str = "") -> str:
    vals = form.get(key)
    if not vals:
        return default
    return vals[0].strip()


def _required(form: dict[str, list[str]], key: str) -> str:
    v = _first(form, key)
    if not v:
        raise wb_state.WorkbenchError(f"{key} е задължително")
    return v


def _route(path: str) -> tuple[str, str | None]:
    """/case/LIV-01 -> ('case', 'LIV-01'); empty segments are dropped."""
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "root", None
    if parts == ["healthz"]:
        return "healthz", None
    if parts == ["intake"]:
        return "intake", None
    if parts == ["quit"]:
        return "quit", None
    if len(parts) == 2 and parts[0] == "case":
        return "case", parts[1]
    if len(parts) == 3 and parts[0] == "case" and parts[2] in ("save", "finalize", "decision"):
        return parts[2], parts[1]
    return "notfound", None


def _respond(
    handler: BaseHTTPRequestHandler,
    code: int,
    body: str,
    *,
    content_type="text/html; charset=utf-8",
):
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(body.encode("utf-8"))


def _respond_json(handler: BaseHTTPRequestHandler, code: int, data: Any):
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(body.encode("utf-8"))


def _redirect(handler: BaseHTTPRequestHandler, location: str):
    """303 back to a GET page (Location MUST be sent before end_headers)."""
    handler.send_response(303)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()


def _render_error(kind: str, case_id: str | None, message: str) -> str:
    if kind == "save":
        title = "Запазването не може да се извърши"
    elif kind == "finalize":
        title = "Финализирането не може да се извърши"
    elif kind == "decision":
        title = "Записването на решението не може да се извърши"
    else:
        title = "Грешка"
    extra = ""
    if case_id:
        extra = f'<p><a href="/case/{html_mod.esc(case_id)}">Назад към случая</a></p>'
    return html_mod.page(title, f'<div class="notice error">{html_mod.esc(message)}</div>\n{extra}')


class WorkbenchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the M3A Editor Workbench."""

    server_version = "M3A-EditorWorkbench/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - {fmt % args}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        route, case_id = _route(path)
        try:
            if route == "root":
                self._get_root()
            elif route == "intake":
                self._get_intake()
            elif route == "case":
                self._get_case(case_id)
            elif route == "healthz":
                self._healthz()
            else:
                self._notfound(path)
        except Exception as e:  # noqa: BLE001 - any handler error must become an HTTP response
            self._handle_error(e)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        route, case_id = _route(path)
        try:
            if route == "save":
                self._post_save(case_id)
            elif route == "finalize":
                self._post_finalize(case_id)
            elif route == "decision":
                self._post_decision(case_id)
            elif route == "quit":
                self._quit()
            else:
                self._notfound(path)
        except Exception as e:  # noqa: BLE001 - any handler error must become an HTTP response
            self._handle_error(e)

    def _get_root(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs, keep_blank_values=True)
        filt = _first(params, "filter", "all") or "all"
        if filt not in {k for k, _ in html_mod.lb.FILTERS}:
            filt = "all"
        q = wb_state.queue()
        body = html_mod.render_queue(q, active_filter=filt)
        _respond(self, 200, body)

    def _get_case(self, case_id):
        if not case_id or not case_id.strip():
            self._notfound(self.path)
            return
        case_id = case_id.strip()
        view = wb_state.case_view(case_id)
        if view is None:
            self._notfound(self.path)
            return
        params = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query, keep_blank_values=True
        )
        body = html_mod.render_case(view, message=_first(params, "message", ""))
        _respond(self, 200, body)

    def _get_intake(self):
        """Display completed M3B intakes. Initiation is CLI-only (M3B Part J).

        Transcription + discovery are long and model-driven, so the local
        threaded server does not run them synchronously and no job queue was
        added; the Workbench only displays results written by
        `workflow.cli youtube-intake`.
        """
        registry = wb_state.intake_registry()
        rows = [wb_state.intake_view(video_id, record) for video_id, record in registry.items()]
        rows.sort(
            key=lambda r: (r.get("generated_at") or "", r.get("video_id") or ""), reverse=True
        )
        cards = []
        for row in rows:
            outcome = row.get("outcome") or "—"
            cards.append(
                "<div class='card'>"
                f"<h3>{html_mod.esc(row.get('title') or row.get('video_id') or '')}</h3>"
                f"<p class='muted'>{html_mod.esc(row.get('canonical_url') or '')}</p>"
                f"<p><b>Резултат:</b> {html_mod.esc(outcome)} · "
                f"теми {row.get('topics', 0)} · факти {row.get('facts', 0)} · "
                f"отхвърлени {row.get('dropped_facts', 0)}</p>"
                f"<p class='muted'>ъгъл: {html_mod.esc(row.get('assessment_status') or '—')} · "
                f"готовност: {html_mod.esc(row.get('readiness_status') or '—')}</p>"
                "</div>"
            )
        body = html_mod.page(
            "YouTube източници (M3B)",
            "<p class='muted'>Нов запис се добавя с командата "
            "<code>youtube-intake &lt;URL&gt;</code> (транскрипцията е дълга и се пуска от CLI). "
            "Тук се показват готовите резултати.</p>"
            + ("".join(cards) if cards else "<p>Няма добавени YouTube източници.</p>"),
        )
        _respond(self, 200, body)

    def _notfound(self, path):
        body = html_mod.page(
            "Не намерено",
            f'<p class="muted">Страницата не съществува: <code>{html_mod.esc(path)}</code></p>',
        )
        _respond(self, 404, body)

    def _healthz(self):
        body = "OK\n"
        _respond(self, 200, body, content_type="text/plain; charset=utf-8")

    def _quit(self):
        if not ENABLE_QUIT:
            self._notfound(self.path)
            return
        body = "Shutting down workbench.\n"
        _respond(self, 200, body, content_type="text/plain; charset=utf-8")
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _post_save(self, case_id):
        if not case_id or not case_id.strip():
            self._notfound(self.path)
            return
        case_id = case_id.strip()
        form = _post_form(self)
        headline = _first(form, "headline", "")
        body_text = _first(form, "body", "")
        answers = {}
        for key in html_mod.lb.ANSWER_LABELS:
            v = _first(form, f"answer_{key}", "")
            if v:
                answers[key] = v
        accept_base = _first(form, "accept_base", "")
        case = wb_state.find_case(case_id)
        if not case:
            _respond(self, 404, _render_error("save", case_id, f"случай {case_id} не съществува"))
            return
        try:
            wb_state.save_working_copy(
                case,
                headline=headline,
                body=body_text or "",
                review_answers=answers,
                accept_new_base=bool(accept_base),
            )
        except wb_state.WorkbenchError as e:
            view = wb_state.case_view(case_id)
            body_html = (
                html_mod.render_case(view, error=str(e))
                if view
                else _render_error("save", case_id, str(e))
            )
            _respond(self, 400, body_html)
            return
        qs = urllib.parse.urlencode({"message": "Работното копие е запазено."})
        _redirect(self, f"/case/{case_id}?{qs}")

    def _post_finalize(self, case_id):
        if not case_id or not case_id.strip():
            self._notfound(self.path)
            return
        case_id = case_id.strip()
        form = _post_form(self)
        headline = _first(form, "headline", "")
        body_text = _first(form, "body", "")
        editor_outcome = _first(form, "editor_outcome", "")
        editing_weight = _first(form, "editing_weight", "")
        time_saved_estimate = _first(form, "time_saved_estimate", "")
        prefer_ai_start = _first(form, "prefer_ai_start", "")
        notes = _first(form, "notes", "")
        readiness_outcome = _first(form, "readiness_outcome", "")
        readiness_note = _first(form, "readiness_note", "")
        base_draft_id = _first(form, "base_draft_id", "")
        answers = {}
        for key in html_mod.lb.ANSWER_LABELS:
            v = _first(form, f"answer_{key}", "")
            if v:
                answers[key] = v
        case = wb_state.find_case(case_id)
        if not case:
            _respond(
                self, 404, _render_error("finalize", case_id, f"случай {case_id} не съществува")
            )
            return
        if case.get("track") == wb_state.TRACK_DRYRUN:
            view = wb_state.case_view(case_id)
            msg = "Еталонен случай: финализирането на усилийни показатели не е позволено от работния плот."
            body_html = (
                html_mod.render_case(view, error=msg)
                if view
                else _render_error("finalize", case_id, msg)
            )
            _respond(self, 400, body_html)
            return
        try:
            out = wb_state.finalize(
                case_id,
                headline=headline,
                body=body_text,
                editor_outcome=editor_outcome,
                editing_weight=editing_weight,
                time_saved_estimate=time_saved_estimate,
                prefer_ai_start=prefer_ai_start,
                notes=notes,
                readiness_outcome=readiness_outcome,
                readiness_note=readiness_note,
                readiness_answers=answers,
                base_draft_id=base_draft_id or None,
            )
        except wb_state.StaleDraftError as e:
            _respond(self, 409, _render_error("finalize", case_id, str(e)))
            return
        except wb_state.WorkbenchError as e:
            view = wb_state.case_view(case_id)
            body_html = (
                html_mod.render_case(view, error=str(e))
                if view
                else _render_error("finalize", case_id, str(e))
            )
            _respond(self, 400, body_html)
            return
        if not out.get("final_text"):
            _respond(self, 400, _render_error("finalize", case_id, "Финализирането не успя."))
            return
        qs = urllib.parse.urlencode({"message": "Материалът е финализиран."})
        _redirect(self, f"/case/{case_id}?{qs}")

    def _post_decision(self, case_id):
        if not case_id or not case_id.strip():
            self._notfound(self.path)
            return
        case_id = case_id.strip()
        form = _post_form(self)
        decision = _first(form, "decision", "")
        reason = _first(form, "reason", "")
        readiness_outcome = _first(form, "readiness_outcome", "")
        readiness_note = _first(form, "readiness_note", "")
        missed_angle = _first(form, "missed_angle", "")
        case = wb_state.find_case(case_id)
        if not case:
            _respond(
                self, 404, _render_error("decision", case_id, f"случай {case_id} не съществува")
            )
            return
        if case.get("final_text"):
            view = wb_state.case_view(case_id)
            msg = f"{case_id} вече е финализиран — решението не може да се актуализира."
            body_html = (
                html_mod.render_case(view, error=msg)
                if view
                else _render_error("decision", case_id, msg)
            )
            _respond(self, 400, body_html)
            return
        try:
            wb_state.record_decision(
                case_id,
                decision=decision,
                reason=reason,
                readiness_outcome=readiness_outcome,
                readiness_note=readiness_note,
                missed_angle=missed_angle,
            )
        except wb_state.WorkbenchError as e:
            view = wb_state.case_view(case_id)
            body_html = (
                html_mod.render_case(view, error=str(e))
                if view
                else _render_error("decision", case_id, str(e))
            )
            _respond(self, 400, body_html)
            return
        qs = urllib.parse.urlencode({"message": "Решението е записано."})
        _redirect(self, f"/case/{case_id}?{qs}")

    def _handle_error(self, e):
        code = 500
        kind = "generic"
        message = str(e)
        if isinstance(e, wb_state.WorkbenchError):
            if "вече финализиран" in message or "already finalized" in message.lower():
                code = 409
                kind = "finalize"
            else:
                code = 400
                kind = "save"
        elif isinstance(e, ValueError):
            code = 400
            kind = "generic"
        if kind == "generic":
            body = html_mod.page(
                "Грешка", f'<div class="notice error">{html_mod.esc(message)}</div>'
            )
        else:
            body = _render_error(kind, None, message)
        try:
            _respond(self, code, body)
        except Exception:  # noqa: BLE001, S110 - client may have closed the socket
            pass


def serve(port, host="127.0.0.1", quit_allowed=False):
    """Start the workbench HTTP server. Returns the HTTPServer instance."""
    global ENABLE_QUIT
    ENABLE_QUIT = quit_allowed
    httpd = ThreadingHTTPServer((host, port), WorkbenchHandler)
    httpd.timeout = 1.0
    return httpd
