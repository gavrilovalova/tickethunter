import json

import httpx
import pytest

from watcher.telegram import Telegram, TelegramError


def make_tg(handler):
    return Telegram("TOKEN", transport=httpx.MockTransport(handler))


def test_get_updates_parses_result():
    def handler(request):
        assert request.url.path == "/botTOKEN/getUpdates"
        body = json.loads(request.content)
        assert body["offset"] == 42
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 43}]})
    assert make_tg(handler).get_updates(42) == [{"update_id": 43}]


def test_send_message_builds_keyboard():
    seen = {}
    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})
    make_tg(handler).send_message(
        "1", "привет", url_buttons=[("Купить", "https://x")],
        callback_buttons=[("Удалить", "del|maskarade")])
    kb = seen["reply_markup"]["inline_keyboard"]
    assert kb == [[{"text": "Купить", "url": "https://x"}],
                  [{"text": "Удалить", "callback_data": "del|maskarade"}]]
    assert seen["parse_mode"] == "HTML" and seen["chat_id"] == "1"


def test_retry_once_then_success(monkeypatch):
    import watcher.telegram as tgmod
    monkeypatch.setattr(tgmod.time, "sleep", lambda s: None)
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True, "result": []})
    assert make_tg(handler).get_updates(0) == []
    assert len(calls) == 2


def test_two_failures_raise(monkeypatch):
    import watcher.telegram as tgmod
    monkeypatch.setattr(tgmod.time, "sleep", lambda s: None)
    def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "nope"})
    with pytest.raises(TelegramError):
        make_tg(handler).send_message("1", "x")
