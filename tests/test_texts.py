from watcher.models import Event, Session, Status
from watcher.texts import event_message, human_dt


def test_human_dt():
    assert human_dt("2026-11-26T19:00") == "26 ноября, чт, 19:00"
    assert human_dt("2027-01-05T18:30") == "5 января, вт, 18:30"


def test_event_message_tickets_appeared():
    s = Session("main", "Основная сцена", "2026-11-26T19:00", Status.AVAILABLE,
                "https://vakhtangov.ru/tickets/buy/?stageuid=main&datetime=2026-11-26-19-00-00")
    text, buttons = event_message(
        Event("tickets_appeared", "Маскарад & Co", "https://vakhtangov.ru/show/maskarade/", s))
    assert "Маскарад &amp; Co" in text          # html-экранирование
    assert "появились билеты" in text
    assert "26 ноября, чт, 19:00" in text and "Основная сцена" in text
    assert buttons == [("Купить билеты", s.buy_url)]


def test_event_message_new_date_without_buy_url_has_no_buttons():
    s = Session("main", "Основная сцена", "2026-11-26T19:00", Status.AVAILABLE, None)
    text, buttons = event_message(
        Event("new_date", "Маскарад", "https://vakhtangov.ru/show/maskarade/", s))
    assert "новая дата" in text
    assert buttons == []
