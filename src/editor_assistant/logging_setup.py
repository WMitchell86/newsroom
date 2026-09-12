"""M0 structured logging skeleton — stdlib only, local output, no shippers."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter: {"ts","level","logger","msg",...extra}."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge structured extras passed via logger.info("...", extra={...}),
        # excluding stdlib LogRecord internals.
        reserved = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in reserved and key not in payload:
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def setup_logging(level: str = "INFO", stream=None) -> logging.Logger:
    """Configure root handler once (idempotent) and return the app logger."""
    global _configured
    root = logging.getLogger()
    log_level = getattr(logging, (level or "INFO").upper(), logging.INFO)
    root.setLevel(log_level)
    if not _configured:
        handler = logging.StreamHandler(stream or sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        _configured = True
    return logging.getLogger("editor_assistant")


def get_logger(name: str = "editor_assistant") -> logging.Logger:
    """Return a named logger (call setup_logging() first in app entrypoints)."""
    return logging.getLogger(name)


def reset_logging_for_tests() -> None:
    """Test helper: remove handlers so each test can attach its own."""
    global _configured
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    _configured = False
