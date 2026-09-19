"""M1.4B Telegram transport — stdlib urllib POST to Bot API sendMessage.

Plain text only (no parse mode). Token is read from env/config by the caller;
this module never logs it. All failures raise TelegramSendError with the
token redacted (URL host + status only, never the token/path).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

API_BASE = "https://api.telegram.org"
SEND_PATH = "sendMessage"
TIMEOUT_SECONDS = 15
MAX_TEXT_CHARS = 4096


class TelegramSendError(RuntimeError):
    """Raised for any Telegram send failure (transport or API-level)."""


@dataclass(frozen=True)
class TelegramSendResult:
    message_id: int


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


def load_telegram_test_config(env=None) -> TelegramConfig | None:
    """Read TELEGRAM_TEST_BOT_TOKEN / TELEGRAM_TEST_CHAT_ID from env mapping.

    Returns None when either is missing/blank (dry-run stays possible).
    Never logs or prints the values.
    """
    source = env if env is not None else os.environ
    token = (source.get("TELEGRAM_TEST_BOT_TOKEN") or "").strip()
    chat_id = (source.get("TELEGRAM_TEST_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return None
    return TelegramConfig(bot_token=token, chat_id=chat_id)


def _redacted_error(status: str) -> TelegramSendError:
    return TelegramSendError(f"Telegram API error ({status}); see local logs")


def send_message(
    config: TelegramConfig,
    text: str,
    *,
    timeout_seconds: int = TIMEOUT_SECONDS,
    opener=None,
) -> TelegramSendResult:
    """POST text to the test chat. Returns message_id on confirmed success."""
    if not text or len(text) > MAX_TEXT_CHARS:
        raise TelegramSendError(
            f"message length {len(text)} outside Telegram 1-4096 char limit; left PENDING"
        )
    body = json.dumps({"chat_id": config.chat_id, "text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}/bot{config.bot_token}/{SEND_PATH}",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "editor-assistant-m14b/0.1"},
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # Status code is safe to surface; the token lives only in the URL path.
        raise _redacted_error(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise _redacted_error(f"{type(exc).__name__}") from None
    except Exception as exc:  # noqa: BLE001 - no failure may leak the token
        # Any other failure (e.g. http.client.InvalidURL / ValueError) would
        # stringify the request URL, which contains the token. Fail closed:
        # report the exception type only.
        raise _redacted_error(type(exc).__name__) from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _redacted_error("invalid JSON response") from None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise _redacted_error("ok=false")
    result = payload.get("result") or {}
    message_id = result.get("message_id")
    if not isinstance(message_id, int):
        raise _redacted_error("missing message_id")
    return TelegramSendResult(message_id=message_id)
