"""M1.4B Telegram delivery tests — all offline, HTTP mocked (part 1: transport)."""

from __future__ import annotations

import json
import pathlib
import urllib.error
from datetime import datetime, timezone

import pytest

from editor_assistant.models import SourceDef
from editor_assistant.notify import telegram as tg
from editor_assistant.sources.rss import PARSER_ID

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "rss_burgas_municipality.xml"
SOURCE = SourceDef(
    source_id="burgas-municipality-press",
    canonical_url="https://www.burgas.bg/press",
    parser=PARSER_ID,
)
T0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
CFG = tg.TelegramConfig(bot_token="TESTTOKEN123", chat_id="999")


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.requests: list = []

    def __call__(self, request, timeout=None):
        assert timeout is not None
        self.requests.append(request)
        outer = self

        class Ctx:
            def __enter__(self):
                return outer

            def __exit__(self, *a):
                return False

        return Ctx()

    def read(self):
        return self._payload


def _ok(message_id=123):
    return _Resp(json.dumps({"ok": True, "result": {"message_id": message_id}}).encode())


def test_transport_post_target_and_payload():
    fake = _ok()
    out = tg.send_message(CFG, "здравей", opener=fake)
    assert out.message_id == 123
    (req,) = fake.requests
    assert req.get_method() == "POST"
    assert req.full_url == "https://api.telegram.org/botTESTTOKEN123/sendMessage"
    assert json.loads(req.data.decode()) == {"chat_id": "999", "text": "здравей"}


def test_transport_timeout_explicit():
    seen = {}

    def opener(request, timeout=None):
        seen["timeout"] = timeout
        raise TimeoutError("slow")

    with pytest.raises(tg.TelegramSendError):
        tg.send_message(CFG, "hi", opener=opener)
    assert seen["timeout"] == tg.TIMEOUT_SECONDS


def test_transport_http_failure_redacted():
    def opener(request, timeout=None):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", None, None)  # type: ignore[arg-type]

    with pytest.raises(tg.TelegramSendError, match="HTTP 401") as exc:
        tg.send_message(CFG, "hi", opener=opener)
    assert "TESTTOKEN123" not in str(exc.value)


def test_transport_malformed_json():
    with pytest.raises(tg.TelegramSendError, match="JSON"):
        tg.send_message(CFG, "hi", opener=_Resp(b"not json"))


def test_transport_ok_false():
    with pytest.raises(tg.TelegramSendError, match="ok=false"):
        tg.send_message(CFG, "hi", opener=_Resp(b'{"ok":false}'))


def test_transport_missing_message_id():
    with pytest.raises(tg.TelegramSendError, match="message_id"):
        tg.send_message(CFG, "hi", opener=_Resp(b'{"ok":true,"result":{}}'))


def test_token_never_in_url_error():
    with pytest.raises(tg.TelegramSendError) as exc:
        tg.send_message(CFG, "hi", opener=_Resp(b"xx"))
    assert "TESTTOKEN123" not in str(exc.value)


def test_message_limit_enforced_before_http():
    calls = []
    with pytest.raises(tg.TelegramSendError, match="4096"):
        tg.send_message(CFG, "x" * 5000, opener=lambda r, timeout=None: calls.append(r))
    assert calls == []


def test_bulgarian_survives_serialization():
    fake = _ok()
    tg.send_message(CFG, "Бургас — съвет", opener=fake)
    assert json.loads(fake.requests[0].data.decode())["text"] == "Бургас — съвет"
