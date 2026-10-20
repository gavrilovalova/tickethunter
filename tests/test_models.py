from watcher.models import Event, ParseError, Session, ShowSnapshot, Status


def test_session_key():
    s = Session(stage="main", stage_title="Основная сцена",
                dt="2026-11-26T19:00", status=Status.SOLD_OUT)
    assert s.key == "main|2026-11-26T19:00"
    assert s.buy_url is None


def test_status_values():
    assert Status.AVAILABLE.value == "available"
    assert Status.SOLD_OUT.value == "sold_out"


def test_event_fields():
    s = Session("main", "Основная сцена", "2026-12-26T19:00",
                Status.AVAILABLE, "https://vakhtangov.ru/tickets/buy/?x=1")
    e = Event("tickets_appeared", "Маскарад", "https://vakhtangov.ru/show/maskarade/", s)
    assert e.kind == "tickets_appeared"
    assert issubclass(ParseError, Exception)
    assert ShowSnapshot("Маскарад", e.show_url, [s]).sessions[0] is s
