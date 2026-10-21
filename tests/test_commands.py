import pytest

from watcher.commands import Reply, handle_update
from watcher.models import AvailabilityError, ParseError, Session, ShowSnapshot, Status

CHAT = "111"
URL = "https://vakhtangov.ru/show/maskarade/"
SNAP = ShowSnapshot("Маскарад", URL, [
    Session("main", "Основная сцена", "2026-11-26T19:00", Status.SOLD_OUT),
    Session("main", "Основная сцена", "2026-12-26T19:00", Status.AVAILABLE,
            "https://vakhtangov.ru/tickets/buy/?stageuid=main&datetime=2026-12-26-19-00-00"),
])


def fresh_state():
    return {"telegram_offset": 0, "subscriptions": {}}


def msg(text, chat=CHAT):
    return {"update_id": 1, "message": {"chat": {"id": int(chat)}, "text": text}}


def test_subscribe_stores_baseline_and_confirms():
    st = fresh_state()
    replies = handle_update(msg(f"глянь {URL}"), st, CHAT, lambda u: SNAP)
    assert URL in st["subscriptions"]
    sub = st["subscriptions"][URL]
    assert sub["title"] == "Маскарад"
    assert sub["sessions"]["main|2026-12-26T19:00"]["status"] == "available"
    assert "Слежу" in replies[0].text and "26 декабря" in replies[0].text


def test_subscribe_normalizes_url_variants():
    st = fresh_state()
    handle_update(msg("https://www.vakhtangov.ru/show/maskarade"), st, CHAT, lambda u: SNAP)
    assert list(st["subscriptions"]) == [URL]  # Review Focus #5
    replies = handle_update(msg(URL), st, CHAT, lambda u: SNAP)
    assert "Уже слежу" in replies[0].text
    assert len(st["subscriptions"]) == 1


def test_foreign_chat_ignored():
    st = fresh_state()
    assert handle_update(msg(URL, chat="999"), st, CHAT, lambda u: SNAP) == []
    assert st["subscriptions"] == {}  # Review Focus #4


def test_subscribe_fetch_errors_reported():
    st = fresh_state()
    def boom_parse(u): raise ParseError("x")
    def boom_net(u): raise OSError("x")
    def boom_avail(u): raise AvailabilityError("x")
    assert "не смогла" in handle_update(msg(URL), st, CHAT, boom_parse)[0].text
    assert "попробуй" in handle_update(msg(URL), st, CHAT, boom_net)[0].text
    # сломанный data.json — не повод говорить «проверь ссылку»
    reply = handle_update(msg(URL), st, CHAT, boom_avail)[0].text
    assert "ссылк" not in reply and "позже" in reply
    assert st["subscriptions"] == {}


def test_list_and_delete():
    st = fresh_state()
    handle_update(msg(URL), st, CHAT, lambda u: SNAP)
    replies = handle_update(msg("/list"), st, CHAT, lambda u: SNAP)
    assert "Маскарад" in replies[0].text
    assert replies[0].callback_buttons == [("Удалить", "del|maskarade")]
    cb = {"update_id": 2, "callback_query": {
        "id": "cb1", "data": "del|maskarade",
        "message": {"chat": {"id": int(CHAT)}}}}
    replies = handle_update(cb, st, CHAT, lambda u: SNAP)
    assert "Больше не слежу" in replies[0].text
    assert st["subscriptions"] == {}


def test_unknown_text_gets_help():
    st = fresh_state()
    replies = handle_update(msg("привет"), st, CHAT, lambda u: SNAP)
    assert "vakhtangov.ru/show" in replies[0].text
