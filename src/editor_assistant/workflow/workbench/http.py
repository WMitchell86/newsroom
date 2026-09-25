"""M3A HTTP layer: stdlib http.server, no framework, Bulgarian-first responses.

Routing (paths only; query params parsed in handlers):
  GET  /                 daily landing (Начало; ?filter=... still opens the archive)
  GET  /settings         settings hub: every advanced surface, explained
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

from editor_assistant.workflow import blocked_domains as blocked_mod
from editor_assistant.workflow import inbox_store as inbox_mod
from editor_assistant.workflow import sources_registry as sources_mod
from editor_assistant.workflow import story_store as story_store_mod
from editor_assistant.workflow.workbench import api as api_mod
from editor_assistant.workflow.workbench import html as html_mod
from editor_assistant.workflow.workbench import newsroom as wb_newsroom
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
    if parts == ["static", "style.css"]:
        return "static_css", None
    if parts == ["intake"]:
        return "intake", None
    if parts == ["settings"]:
        return "settings", None
    if parts == ["cases"]:
        return "cases", None
    if parts == ["sources"]:
        return "sources", None
    if parts == ["inbox"]:
        return "inbox", None
    if parts == ["stories"]:
        return "stories", None
    if parts == ["articles"]:
        return "articles", None
    if parts == ["models"]:
        return "models", None
    if len(parts) == 2 and parts[0] == "stories":
        return "story", parts[1]
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
        if api_mod.owns_path(path):
            api_mod.dispatch(self, "GET")
            return
        route, case_id = _route(path)
        try:
            if route == "root":
                self._get_root()
            elif route == "static_css":
                self._get_static_css()
            elif route == "cases":
                self._get_cases()
            elif route == "intake":
                self._get_intake()
            elif route == "settings":
                self._get_settings()
            elif route == "case":
                self._get_case(case_id)
            elif route == "sources":
                self._get_sources()
            elif route == "inbox":
                self._get_inbox()
            elif route == "stories":
                self._get_stories()
            elif route == "articles":
                self._get_articles()
            elif route == "models":
                self._get_models()
            elif route == "story":
                self._get_story(case_id)
            elif route == "healthz":
                self._healthz()
            else:
                self._notfound(path)
        except Exception as e:  # noqa: BLE001 - any handler error must become an HTTP response
            self._handle_error(e)

    def do_PATCH(self):
        if api_mod.owns_path(urllib.parse.urlparse(self.path).path):
            api_mod.dispatch(self, "PATCH")
            return
        self.send_error(501, "Unsupported method")

    def do_PUT(self):
        if api_mod.owns_path(urllib.parse.urlparse(self.path).path):
            api_mod.dispatch(self, "PUT")
            return
        self.send_error(501, "Unsupported method")

    def do_DELETE(self):
        if api_mod.owns_path(urllib.parse.urlparse(self.path).path):
            api_mod.dispatch(self, "DELETE")
            return
        self.send_error(501, "Unsupported method")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if api_mod.owns_path(path):
            api_mod.dispatch(self, "POST")
            return
        route, case_id = _route(path)
        try:
            if route == "save":
                self._post_save(case_id)
            elif route == "finalize":
                self._post_finalize(case_id)
            elif route == "decision":
                self._post_decision(case_id)
            elif route == "sources":
                self._post_sources()
            elif route == "inbox":
                self._post_inbox()
            elif route == "stories":
                self._post_stories()
            elif route == "articles":
                self._post_articles()
            elif route == "models":
                self._post_models()
            elif route == "quit":
                self._quit()
            else:
                self._notfound(path)
        except Exception as e:  # noqa: BLE001 - any handler error must become an HTTP response
            self._handle_error(e)

    def _get_static_css(self):
        _respond(
            self,
            200,
            html_mod.CSS,
            content_type="text/css; charset=utf-8",
        )

    def _get_home(self):
        """Daily landing page: what is new, what needs attention, start here.

        Read-only: it aggregates the same views the /stories, /inbox and
        /sources pages use, so it can never drift from the store contract.
        The frozen M3A queue stays reachable under /cases but is not the
        daily entry point any more (UX review P0).
        """
        try:
            stories = wb_newsroom.stories_view(status="NEW", page_size=5)
        except Exception:  # noqa: BLE001 - home must render even on bad story store
            stories = {"stories": [], "counts": {}, "total_stories": 0}
        try:
            inbox = wb_newsroom.inbox_view(status="NEW", page_size=5)
        except Exception:  # noqa: BLE001 - home must render even on bad inbox store
            inbox = {"items": [], "total": 0, "unreviewed": 0, "today": {}}
        try:
            sources = wb_newsroom.sources_view()
        except Exception:  # noqa: BLE001 - home must render even on bad registry
            sources = {"summary": {}, "rows": []}
        body = html_mod.render_home(stories, inbox, sources)
        _respond(self, 200, body)

    def _get_cases(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs, keep_blank_values=True)
        filt = _first(params, "filter", "all") or "all"
        if filt not in {k for k, _ in html_mod.lb.FILTERS}:
            filt = "all"
        q = wb_state.queue()
        body = html_mod.render_queue(q, active_filter=filt)
        _respond(self, 200, body)

    def _get_root(self):
        """Back-compat: old queue links (?filter=...) still reach the archive."""
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs, keep_blank_values=True)
        if "filter" in params:
            filt = _first(params, "filter", "all") or "all"
            if filt not in {k for k, _ in html_mod.lb.FILTERS}:
                filt = "all"
            q = wb_state.queue()
            body = html_mod.render_queue(q, active_filter=filt)
            _respond(self, 200, body)
            return
        self._get_home()

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
        _respond(self, 200, html_mod.render_intake(rows))

    def _get_settings(self):
        """«Настройки»: the one hub that explains every advanced surface."""
        params = self._query()
        body = html_mod.render_settings(
            message=_first(params, "message", ""),
            error=_first(params, "error", ""),
        )
        _respond(self, 200, body)

    # ---------- M4A: sources + inbox ----------

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query, keep_blank_values=True)

    @staticmethod
    def _sources_view():
        """Registry view + the blocked-domain policy the page renders together."""
        view = wb_newsroom.sources_view()
        view["blocked"] = wb_newsroom.blocked_view()
        return view

    def _get_sources(self):
        params = self._query()
        body = html_mod.render_sources(
            self._sources_view(),
            message=_first(params, "message", ""),
            error=_first(params, "error", ""),
        )
        _respond(self, 200, body)

    def _get_inbox(self):
        params = self._query()
        view = wb_newsroom.inbox_view(
            status=_first(params, "status", "NEW") or "NEW",
            source_id=_first(params, "source", ""),
            kind=_first(params, "kind", ""),
            priority=_first(params, "priority", ""),
            date=_first(params, "date", ""),
            authority=_first(params, "authority", ""),
            page=_first(params, "page", "1"),
        )
        body = html_mod.render_inbox(
            view,
            message=_first(params, "message", ""),
            error=_first(params, "error", ""),
        )
        _respond(self, 200, body)

    @staticmethod
    def _source_values(form):
        """Echo the submitted add-form so a refusal never loses typing."""
        return {
            key: _first(form, key, "")
            for key in ("source_id", "name", "kind", "domain", "collector", "url", "query", "note")
        }

    def _post_sources(self):
        form = _post_form(self)
        action = _first(form, "action", "")
        source_id = _first(form, "source_id", "")
        catalog_actions = ("defaults_preview", "defaults_apply", "domain_add", "domain_remove")
        try:
            if action in catalog_actions:
                message = self._apply_catalog_action(action, form)
            else:
                message = self._apply_source_action(action, form, source_id)
        except (
            sources_mod.RegistryError,
            inbox_mod.InboxError,
            blocked_mod.BlockedDomainError,
        ) as exc:
            # A refusal is a readable message on the page, never a 500/traceback.
            body = html_mod.render_sources(
                self._sources_view(), error=str(exc), values=self._source_values(form)
            )
            _respond(self, 400, body)
            return
        _redirect(self, "/sources?" + urllib.parse.urlencode({"message": message}))

    def _apply_source_action(self, action, form, source_id):
        if action == "add":
            entry = wb_newsroom.add_source(
                source_id=_first(form, "source_id", ""),
                name=_first(form, "name", ""),
                kind=_first(form, "kind", ""),
                collector=_first(form, "collector", ""),
                domain=_first(form, "domain", ""),
                url=_first(form, "url", ""),
                query=_first(form, "query", ""),
                priority=_first(form, "priority", "normal") or "normal",
                cadence=_first(form, "cadence", "each_run") or "each_run",
                monitoring_only=bool(_first(form, "monitoring_only", "")),
                calendar=bool(_first(form, "calendar", "")),
                note=_first(form, "note", ""),
            )
            return f"Източникът {entry['name']} е добавен."
        if not source_id:
            raise sources_mod.RegistryError("липсва източник за действието")
        if action == "edit":
            changes = {}
            for key in sources_mod.EDITABLE_FIELDS:
                if key in form:
                    changes[key] = _first(form, key, "")
            wb_newsroom.update_source(source_id, **changes)
            return f"Промените по {source_id} са запазени."
        if action in ("enable", "disable", "unmute"):
            status = "active" if action in ("enable", "unmute") else "disabled"
            wb_newsroom.set_status(source_id, status)
            return f"{source_id}: {html_mod.lb.SOURCE_STATUS_LABELS.get(status, status)}"
        if action == "mute":
            until = _first(form, "muted_until", "")
            wb_newsroom.set_status(source_id, "muted", muted_until=until)
            return f"{source_id} е заглушен до {until}."
        if action == "priority":
            value = _first(form, "value", "")
            wb_newsroom.set_priority(source_id, value)
            return f"{source_id}: приоритет {value}."
        if action in ("authority", "monitoring_only"):
            wb_newsroom.set_authority(source_id, action == "authority")
            return (
                f"{source_id}: фактологичен авторитет."
                if action == "authority"
                else f"{source_id}: само наблюдение."
            )
        if action == "remove":
            wb_newsroom.remove_source(source_id)
            return f"{source_id} е премахнат (събраното остава)."
        raise sources_mod.RegistryError(f"непознато действие: {action!r}")

    def _apply_catalog_action(self, action, form):
        if action == "defaults_preview":
            result = wb_newsroom.apply_defaults(preview=True)
            return (
                f"Преглед: ще бъдат добавени {len(result['added'])} източника, "
                f"вече налични {len(result['present'])} (без запис)."
            )
        if action == "defaults_apply":
            result = wb_newsroom.apply_defaults(preview=False)
            return (
                f"Добавени {len(result['added'])} източника; "
                f"вече наличните {len(result['present'])} остават непроменени."
            )
        if action == "domain_add":
            result = wb_newsroom.add_blocked_domain(_first(form, "domain", ""))
            verb = "е забранен" if result["added"] else "вече беше забранен"
            return f"{result['domain']} {verb}."
        if action == "domain_remove":
            result = wb_newsroom.remove_blocked_domain(_first(form, "domain", ""))
            return f"{result['domain']} е премахнат от забранените."
        raise sources_mod.RegistryError(f"непознато действие: {action!r}")

    def _post_inbox(self):
        form = _post_form(self)
        action = _first(form, "action", "")
        if action in ("collect", "collect_preview"):
            self._collect_now(dry_run=action == "collect_preview")
            return
        item_id = _first(form, "item_id", "")
        status = _first(form, "status", "")
        try:
            wb_newsroom.set_inbox_status(item_id, status)
        except inbox_mod.InboxError as exc:
            body = html_mod.render_inbox(wb_newsroom.inbox_view(status="all"), error=str(exc))
            _respond(self, 400, body)
            return
        _redirect(self, "/inbox?" + urllib.parse.urlencode({"message": "Отбелязано."}))

    def _collect_now(self, *, dry_run):
        """«Събери новите сега»: the same one-shot service cron calls."""
        try:
            summary = wb_newsroom.collect_now(dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - a readable message, never a 500
            _redirect(
                self,
                "/inbox?" + urllib.parse.urlencode({"error": f"Събирането се провали: {exc}"}),
            )
            return
        if summary.get("locked"):
            _redirect(
                self,
                "/inbox?"
                + urllib.parse.urlencode({"message": "Друго събиране вече тече — опитайте пак."}),
            )
            return
        if dry_run:
            message = (
                f"Пробен преглед: {len(summary['sources'])} източника, "
                f"{summary['estimated_network_calls']} заявки (без мрежа)."
            )
        else:
            wb_newsroom.record_action("collect_now", f"new={summary['new']}")
            message = (
                f"Събрани {summary['new']} нови · вече известни {summary['duplicate']} · "
                f"грешки {summary['failed']} · филтрирани по домейн {summary['blocked_filtered']}"
            )
        _redirect(self, "/inbox?" + urllib.parse.urlencode({"message": message}))

    # ---------- M4C: stories ----------

    def _get_stories(self):
        params = self._query()
        view = wb_newsroom.stories_view(
            status=_first(params, "status", "NEW") or "NEW",
            review=bool(_first(params, "review", "")),
            page=_first(params, "page", "1"),
        )
        body = html_mod.render_stories(
            view,
            message=_first(params, "message", ""),
            error=_first(params, "error", ""),
        )
        _respond(self, 200, body)

    def _get_story(self, story_id):
        detail = wb_newsroom.story_view(story_id)
        if detail is None:
            self._notfound(self.path)
            return
        params = self._query()
        body = html_mod.render_story(
            detail,
            message=_first(params, "message", ""),
            error=_first(params, "error", ""),
        )
        _respond(self, 200, body)

    def _post_stories(self):
        """Editor corrections + the story refresh action (no network here)."""
        form = _post_form(self)
        action = _first(form, "action", "")
        story_id = _first(form, "story", "")
        try:
            if action in ("update", "update_preview"):
                summary = wb_newsroom.refresh_stories(dry_run=action == "update_preview")
                if action == "update_preview":
                    message = (
                        f"Пробен преглед: {summary['scanned']} материала · "
                        f"нови истории {summary['new_stories']} · без запис."
                    )
                else:
                    message = (
                        f"Нови истории {summary['new_stories']} · "
                        f"добавени към съществуващи "
                        f"{summary['deterministic_matches'] + summary['semantic_matches'] + summary['exact_duplicates']} · "
                        f"за преглед {summary['needs_review']}."
                    )
            elif action == "status":
                status = _first(form, "status", "")
                wb_newsroom.set_story_status(story_id, status)
                message = "Историята е отбелязана."
            elif action == "split":
                result = wb_newsroom.split_story_item(story_id, _first(form, "item", ""))
                story_id = result["to_story"]
                message = "Материалът е отделен като нова история."
            elif action == "merge":
                result = wb_newsroom.merge_story(
                    _first(form, "target", ""), _first(form, "source", "")
                )
                story_id = result["story_id"]
                message = "Историите са обединени."
            else:
                raise story_store_mod.StoryStoreError(f"непознато действие: {action!r}")
        except story_store_mod.StoryStoreError as exc:
            detail = wb_newsroom.story_view(story_id) if story_id else None
            if detail is None:
                _redirect(self, "/stories?" + urllib.parse.urlencode({"error": str(exc)}))
                return
            _respond(self, 400, html_mod.render_story(detail, error=str(exc)))
            return
        if action in ("update", "update_preview"):
            _redirect(self, "/stories?" + urllib.parse.urlencode({"message": message}))
            return
        _redirect(
            self,
            f"/stories/{urllib.parse.quote(story_id)}?"
            + urllib.parse.urlencode({"message": message}),
        )

    # ---------- M4F: ideas -> drafts («Статии») ----------

    def _get_articles(self):
        params = self._query()
        try:
            view = wb_state.articles_view()
        except Exception as e:  # noqa: BLE001 - page must render even on bad stores
            _respond(self, 500, html_mod.render_articles({"ideas": [], "counts": {}}, error=str(e)))
            return
        body = html_mod.render_articles(
            view,
            message=_first(params, "message", ""),
            error=_first(params, "error", ""),
        )
        _respond(self, 200, body)

    def _post_articles(self):
        form = _post_form(self)
        action = _first(form, "action", "")
        idea_id = _first(form, "idea", "")
        try:
            if action == "request_draft":
                idea = wb_state.request_draft_for_idea(idea_id)
                message = f"Заявета чернова за «{idea['title'][:60]}»."
                _redirect(self, "/articles?" + urllib.parse.urlencode({"message": message}))
                return
            if action == "prepare":
                idea_id = _required(form, "idea")
                evidence_id = _required(form, "evidence")
                result = wb_state.prepare_case(idea_id, evidence_id, mode=_first(form, "mode", ""))
                if result["status"] == "PREPARED":
                    message = (
                        f"Пакетът е подготвен (режим: "
                        f"{html_mod.lb.MODE_LABELS.get(result['mode'], result['mode'])}). "
                        "Сега «Подготви AI чернова»."
                    )
                else:  # NO_ANGLE refusal from the angle gate
                    message = f"Без публикуем ъгъл: {result.get('reason', '')}"
                _redirect(self, "/articles?" + urllib.parse.urlencode({"message": message}))
                return
            if action == "generate":
                idea_id = _required(form, "idea")
                evidence_id = _required(form, "evidence")
                result = wb_state.generate_draft(
                    idea_id,
                    evidence_id,
                    force=bool(_first(form, "force", "")),
                    force_reason=_first(form, "force_reason", ""),
                )
                if result["status"] == "DRAFTED":
                    _redirect(
                        self,
                        f"/case/{urllib.parse.quote(result['case_id'])}?"
                        + urllib.parse.urlencode(
                            {"message": "AI черновата е готова и отворена като случай."}
                        ),
                    )
                    return
                message = (
                    f"Генерацията беше отказана ({result['status']}): {result.get('reason', '')}"
                )
                _redirect(self, "/articles?" + urllib.parse.urlencode({"message": message}))
                return
            if action == "promote":
                story_id = _required(form, "story")
                result = wb_state.promote_story_to_idea(
                    story_id,
                    inbox_path=wb_newsroom.inbox_store_path(),
                    stories_path=wb_newsroom.stories_store(),
                    why_now=_first(form, "why_now", ""),
                    angle=_first(form, "angle", ""),
                )
                message = (
                    f"Историята стана идея «{result['title'][:60]}» "
                    f"с {result['fact_count']} факта. Отвори «Статии»."
                )
                _redirect(self, "/articles?" + urllib.parse.urlencode({"message": message}))
                return
            raise wb_state.WorkbenchError(f"непознато действие: {action!r}")
        except wb_state.WorkbenchError as exc:
            _redirect(self, "/articles?" + urllib.parse.urlencode({"error": str(exc)}))
        except Exception as e:  # noqa: BLE001 - generation failures must stay visible
            _redirect(self, "/articles?" + urllib.parse.urlencode({"error": str(e)}))

    # ---------- M4D: the AI models policy page ----------

    def _get_models(self):
        params = self._query()
        body = html_mod.render_models(
            wb_newsroom.models_view(),
            message=_first(params, "message", ""),
            error=_first(params, "error", ""),
        )
        _respond(self, 200, body)

    def _post_models(self):
        """Operator configuration only: no editorial content, no key ever echoed."""
        from editor_assistant.drafting import model_policy as policy_mod

        form = _post_form(self)
        action = _first(form, "action", "")
        role = _first(form, "role", "")
        try:
            # Compact single-form manager posts op+index; translate to the legacy
            # vocabulary so the policy contract (and its tests) never changes.
            if not action and _first(form, "op", ""):
                op = _first(form, "op", "")
                index = _first(form, "index", "0") or "0"
                if op in ("up", "down"):
                    action = "move"
                    form = {**form, "action": [action], "direction": [op], "index": [index]}
                elif op == "toggle":
                    action = "toggle"
                    form = {**form, "action": [action], "index": [index]}
                    if "enabled" not in form:
                        # No explicit target: flip the current state of that route.
                        flip = True
                        try:
                            roles = wb_newsroom.models_view().get("roles") or []
                            row = next((r for r in roles if r.get("role") == role), None)
                            current = next(
                                (
                                    r
                                    for r in (row or {}).get("routes", [])
                                    if str(r.get("index")) == str(index)
                                ),
                                None,
                            )
                            if current is not None:
                                flip = not bool(current.get("enabled"))
                        except Exception as exc:
                            # M4F P3 fail-CLOSED: never guess a policy read
                            # into an *enable* — refuse, change nothing.
                            raise policy_mod.PolicyError(
                                "не можа да се прочете текущото състояние на "
                                f"маршрута — нищо не е променено ({exc})"
                            ) from exc
                        form = {**form, "enabled": ["1" if flip else "0"]}
                elif op == "remove":
                    action = "remove"
                    form = {**form, "action": [action], "index": [index]}
            if action == "validate":
                report = wb_newsroom.validate_models()
                message = (
                    f"Проверката приключи: невалидни {len(report['invalid'])} · "
                    f"несъответствия {len(report['mismatches'])}."
                )
            elif action == "global":
                wb_newsroom.edit_policy(
                    action_edit="global",
                    paid_enabled=bool(_first(form, "paid_enabled", "")),
                    soft_paid_budget_usd_day=float(
                        _first(form, "soft_paid_budget_usd_day", "0") or 0
                    ),
                )
                message = "Глобалните настройки са запазени."
            elif action == "role_budget":
                wb_newsroom.edit_policy(
                    action_edit="role_budget",
                    role=role,
                    soft_calls_day=int(_first(form, "soft_calls_day", "0") or 0),
                    hard_calls_day=int(_first(form, "hard_calls_day", "0") or 0),
                )
                message = f"Границите за {role} са запазени."
            elif action == "move":
                direction = _first(form, "direction", "up") or "up"
                wb_newsroom.edit_policy(
                    action_edit="move",
                    role=role,
                    index=int(_first(form, "index", "0") or 0),
                    direction=direction,
                )
                message = f"{role}: маршрутът е преместен ({direction})."
            elif action == "toggle":
                enabled = _first(form, "enabled", "") in ("1", "true", "on")
                wb_newsroom.edit_policy(
                    action_edit="toggle",
                    role=role,
                    index=int(_first(form, "index", "0") or 0),
                    enabled=enabled,
                )
                message = f"{role}: маршрутът е {'включен' if enabled else 'изключен'}."
            elif action == "remove":
                wb_newsroom.edit_policy(
                    action_edit="remove", role=role, index=int(_first(form, "index", "0") or 0)
                )
                message = f"{role}: маршрутът е премахнат."
            elif action == "add":
                provider = _first(form, "provider", "").strip()
                model = _first(form, "model", "").strip()
                if not provider or not model:
                    raise policy_mod.PolicyError("попълнете provider и model")
                wb_newsroom.edit_policy(
                    action_edit="add",
                    role=role,
                    provider=provider,
                    model=model,
                    billing=_first(form, "billing", "").strip() or None,
                    public_only=bool(_first(form, "public_only", "")),
                )
                message = f"{role}: добавен {provider}:{model}."
            else:
                raise policy_mod.PolicyError(f"непознато действие: {action!r}")
        except (
            policy_mod.PolicyError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            try:
                body = html_mod.render_models(wb_newsroom.models_view(), error=str(exc))
            except Exception:  # noqa: BLE001 - the view itself may be unreadable
                body = html_mod.page("AI модели", f'<p class="muted">{html_mod.esc(str(exc))}</p>')
            _respond(self, 400, body)
            return
        _redirect(self, "/models?" + urllib.parse.urlencode({"message": message}))

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
