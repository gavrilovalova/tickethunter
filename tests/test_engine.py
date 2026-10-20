from datetime import datetime

from watcher.engine import diff
from watcher.models import Session, ShowSnapshot, Status

NOW = datetime(2026, 10, 20, 12, 0)
URL = "https://vakhtangov.ru/show/maskarade/"
BUY = "https://vakhtangov.ru/tickets/buy/?stageuid=main&datetime=2026-11-26-19-00-00"


def snap(*sessions):
    return ShowSnapshot("Маскарад", URL, list(sessions))


def stored_of(s: Session) -> dict:
    return {s.key: {"status": s.status.value, "buy_url": s.buy_url,
                    "stage_title": s.stage_title, "dt": s.dt}}


AV = Session("main", "Основная сцена", "2026-11-26T19:00", Status.AVAILABLE, BUY)
SO = Session("main", "Основная сцена", "2026-11-26T19:00", Status.SOLD_OUT)


def test_soldout_to_available_fires_tickets_appeared():
    new, events = diff(stored_of(SO), snap(AV), NOW)
    assert [e.kind for e in events] == ["tickets_appeared"]
    assert events[0].session.buy_url == BUY
    assert new[AV.key]["status"] == "available"


def test_new_available_session_fires_new_date():
    new, events = diff({}, snap(AV), NOW)
    assert [e.kind for e in events] == ["new_date"]


def test_new_soldout_session_is_silent():
    new, events = diff({}, snap(SO), NOW)
    assert events == [] and new[SO.key]["status"] == "sold_out"


def test_available_to_soldout_silent_and_rearms():
    new, events = diff(stored_of(AV), snap(SO), NOW)
    assert events == []
    # антиспам-цикл: после sold_out следующее появление снова уведомляет
    _, events2 = diff(new, snap(AV), NOW)
    assert [e.kind for e in events2] == ["tickets_appeared"]


def test_available_stays_available_no_repeat():
    new, events = diff(stored_of(AV), snap(AV), NOW)
    assert events == []


def test_past_session_dropped():
    past = Session("main", "Основная сцена", "2026-10-19T19:00", Status.AVAILABLE, BUY)
    new, events = diff(stored_of(past), snap(past), NOW)
    assert new == {} and events == []


def test_disappeared_session_dropped():
    new, events = diff(stored_of(SO), snap(), NOW)
    assert new == {} and events == []
