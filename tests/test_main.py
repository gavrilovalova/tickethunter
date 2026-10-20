from datetime import datetime

import httpx
import pytest

from watcher.main import run
from watcher.models import ParseError, Session, ShowSnapshot, Status
from watcher.telegram import TelegramError

CHAT = "111"
URL = "https://vakhtangov.ru/show/maskarade/"
BUY = "https://vakhtangov.ru/tickets/buy/?stageuid=main&datetime=2026-11-26-19-00-00"
NOW = datetime(2026, 10, 20, 12, 0)


class FakeTg:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.sent = []
        self.fail_texts = set()   # тексты, на которых send_message бросает

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]

    def send_message(self, chat_id, text, url_buttons=(), callback_buttons=()):
        if any(t in text for t in self.fail_texts):
            raise TelegramError("boom")
        self.sent.append((text, list(url_buttons)))

    def answer_callback(self, cb_id):
        pass


def sub_state(status="sold_out"):
    return {"telegram_offset": 0, "subscriptions": {URL: {
        "title": "Маскарад", "added_at": "2026-10-01T00:00:00+00:00",
        "parse_error_notified": False,
        "sessions": {"main|2026-11-26T19:00": {
            "status": status, "buy_url": BUY if status == "available" else None,
            "stage_title": "Основная сцена", "dt": "2026-11-26T19:00"}}}}}


def available_snap(u):
    return ShowSnapshot("Маскарад", URL, [
        Session("main", "Основная сцена", "2026-11-26T19:00", Status.AVAILABLE, BUY)])


def test_full_cycle_notifies_and_updates_state():
    tg = FakeTg()
    st = run(tg, CHAT, sub_state("sold_out"), fetch=available_snap, now=NOW)
    assert len(tg.sent) == 1
    text, buttons = tg.sent[0]
    assert "появились билеты" in text and buttons == [("Купить билеты", BUY)]
    assert st["subscriptions"][URL]["sessions"]["main|2026-11-26T19:00"]["status"] == "available"


def test_offset_advances_and_command_processed():
    upd = {"update_id": 7, "message": {"chat": {"id": int(CHAT)}, "text": "/list"}}
    tg = FakeTg(updates=[upd])
    st = run(tg, CHAT, sub_state("sold_out"), fetch=lambda u: sold_snap(), now=NOW)
    assert st["telegram_offset"] == 8
    assert any("Маскарад" in t for t, _ in tg.sent)


def sold_snap():
    return ShowSnapshot("Маскарад", URL, [
        Session("main", "Основная сцена", "2026-11-26T19:00", Status.SOLD_OUT)])


def test_poison_update_does_not_block_later_updates_or_offset():
    poison = {"update_id": 5, "callback_query": {"id": "cb1", "data": "del|maskarade"}}
    good = {"update_id": 6, "message": {"chat": {"id": int(CHAT)}, "text": "/list"}}
    tg = FakeTg(updates=[poison, good])
    st = run(tg, CHAT, sub_state("sold_out"), fetch=lambda u: sold_snap(), now=NOW)
    assert st["telegram_offset"] == 7
    assert any("Маскарад" in t for t, _ in tg.sent)


def test_network_error_skips_silently():
    def boom(u): raise httpx.ConnectError("down")
    tg = FakeTg()
    st = run(tg, CHAT, sub_state("sold_out"), fetch=boom, now=NOW)
    assert tg.sent == []
    assert st["subscriptions"][URL]["sessions"]["main|2026-11-26T19:00"]["status"] == "sold_out"


def test_parse_error_notifies_once():
    def boom(u): raise ParseError("x")
    tg = FakeTg()
    st = run(tg, CHAT, sub_state("sold_out"), fetch=boom, now=NOW)
    st = run(tg, CHAT, st, fetch=boom, now=NOW)
    warn = [t for t, _ in tg.sent if "Не могу прочитать" in t]
    assert len(warn) == 1
    # успешный парсинг сбрасывает флаг
    st = run(tg, CHAT, st, fetch=lambda u: sold_snap(), now=NOW)
    assert st["subscriptions"][URL]["parse_error_notified"] is False


def test_send_failure_keeps_old_status_for_retry():
    tg = FakeTg()
    tg.fail_texts = {"появились билеты"}
    st = run(tg, CHAT, sub_state("sold_out"), fetch=available_snap, now=NOW)
    # статус не зафиксирован — в следующем цикле уведомление повторится (Review Focus #3)
    assert st["subscriptions"][URL]["sessions"]["main|2026-11-26T19:00"]["status"] == "sold_out"
    tg.fail_texts = set()
    st = run(tg, CHAT, st, fetch=available_snap, now=NOW)
    assert any("появились билеты" in t for t, _ in tg.sent)
