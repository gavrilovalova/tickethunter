from datetime import date
from pathlib import Path

import pytest

from watcher.models import ParseError, Status
from watcher.parser_vakhtangov import parse_show_page

FIX = Path(__file__).parent / "fixtures"
URL = "https://vakhtangov.ru/show/maskarade/"
TODAY = date(2026, 10, 20)


def load(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_mixed_page():
    snap = parse_show_page(load("synthetic_mixed.html"), URL, today=TODAY)
    assert snap.title == "Маскарад"
    by_key = {s.key: s for s in snap.sessions}
    avail = by_key["main|2026-12-26T19:00"]
    assert avail.status is Status.AVAILABLE
    assert avail.buy_url == ("https://vakhtangov.ru/tickets/buy/"
                             "?stageuid=main&datetime=2026-12-26-19-00-00")
    assert avail.stage_title == "Основная сцена"
    sold = by_key["основная-сцена|2026-11-26T19:00"]
    assert sold.status is Status.SOLD_OUT and sold.buy_url is None
    # «5 января» в октябре = следующий год (Review Focus #2)
    assert "новая-сцена|2027-01-05T18:00" in by_key
    # битая buy-ссылка молча пропущена (Review Focus #1) — лишних сеансов нет
    assert len(snap.sessions) == 3


def test_soldout_only_page():
    snap = parse_show_page(load("synthetic_soldout.html"), URL, today=TODAY)
    assert [s.status for s in snap.sessions] == [Status.SOLD_OUT]


def test_no_schedule_raises_parse_error():
    with pytest.raises(ParseError):
        parse_show_page(load("no_schedule.html"), URL, today=TODAY)


def test_soldout_marker_but_unparsable_row_raises():
    html = "<html><body><h1>Маскарад</h1><p>Билеты закончились</p></body></html>"
    with pytest.raises(ParseError):
        parse_show_page(html, URL, today=TODAY)


def test_live_fixture_invariants():
    live = FIX / "live.html"
    if not live.exists():
        pytest.skip("live.html не захвачен")
    snap = parse_show_page(live.read_text(encoding="utf-8"), URL, today=date.today())
    assert snap.title
    for s in snap.sessions:
        assert s.dt >= "2026"
        if s.status is Status.AVAILABLE:
            assert s.buy_url and "stageuid=" in s.buy_url and "datetime=" in s.buy_url
