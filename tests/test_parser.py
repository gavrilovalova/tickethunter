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
    # заголовок — первый h1 без класса site-logo, а не логотип и не пресса
    assert snap.title == "Маскарад"
    by_key = {s.key: s for s in snap.sessions}
    # битая data-datetime молча пропущена — ровно 3 сеанса
    assert set(by_key) == {"main|2026-11-26T19:00", "main|2026-12-26T19:00",
                           "new|2027-01-05T18:00"}
    assert len(snap.sessions) == 3
    assert by_key["main|2026-12-26T19:00"].stage_title == "Основная сцена"
    assert by_key["new|2027-01-05T18:00"].stage_title == "Новая сцена"


def test_sold_out_has_no_buy_url_and_available_uses_href():
    snap = parse_show_page(load("synthetic_mixed.html"), URL, today=TODAY)
    by_key = {s.key: s for s in snap.sessions}
    sold = by_key["main|2026-11-26T19:00"]
    assert sold.status is Status.SOLD_OUT and sold.buy_url is None
    avail = by_key["main|2026-12-26T19:00"]
    assert avail.status is Status.AVAILABLE
    assert avail.buy_url == ("https://vakhtangov.ru/tickets/buy/"
                             "?stageuid=main&datetime=2026-12-26-19-00-00")


def test_available_with_placeholder_href_constructs_buy_url():
    html = ('<html><body><h1>Маскарад</h1><h2>Арт-кафе</h2>'
            '<a href="#" class="btn js-buy-tickets-btn" data-stage="artcafe" '
            'data-datetime="2026-10-20-20-00-00">Купить билеты</a></body></html>')
    (s,) = parse_show_page(html, URL, today=TODAY).sessions
    assert s.status is Status.AVAILABLE
    assert s.key == "artcafe|2026-10-20T20:00"
    assert s.buy_url == ("https://vakhtangov.ru/tickets/buy/"
                         "?stageuid=artcafe&datetime=2026-10-20-20-00-00")


def test_soldout_only_page():
    snap = parse_show_page(load("synthetic_soldout.html"), URL, today=TODAY)
    assert [s.status for s in snap.sessions] == [Status.SOLD_OUT]


def test_sold_out_by_button_text_without_disabled_class():
    html = ('<html><body><h1>Маскарад</h1>'
            '<a href="#" class="js-buy-tickets-btn" data-stage="main" '
            'data-datetime="2026-11-26-19-00-00">Билеты закончились</a></body></html>')
    (s,) = parse_show_page(html, URL, today=TODAY).sessions
    assert s.status is Status.SOLD_OUT and s.buy_url is None


def test_title_falls_back_to_og_title():
    html = ('<html><head><meta property="og:title" content="Маскарад"></head><body>'
            '<h1 class="site-logo">Театр</h1>'
            '<a href="#" class="js-buy-tickets-btn" data-stage="main" '
            'data-datetime="2026-11-26-19-00-00">Билеты закончились</a></body></html>')
    assert parse_show_page(html, URL, today=TODAY).title == "Маскарад"


def test_no_title_raises_parse_error():
    html = ('<html><body><h1 class="site-logo">Театр</h1>'
            '<a href="#" class="js-buy-tickets-btn" data-stage="main" '
            'data-datetime="2026-11-26-19-00-00">Билеты закончились</a></body></html>')
    with pytest.raises(ParseError):
        parse_show_page(html, URL, today=TODAY)


def test_no_schedule_raises_parse_error():
    with pytest.raises(ParseError):
        parse_show_page(load("no_schedule.html"), URL, today=TODAY)


def test_all_buttons_malformed_raises_parse_error():
    html = ('<html><body><h1>Маскарад</h1>'
            '<a class="js-buy-tickets-btn" data-stage="main" data-datetime="broken">x</a>'
            '<a class="js-buy-tickets-btn" data-datetime="2026-11-26-19-00-00">x</a>'
            '</body></html>')
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


def test_calendar_invalid_datetime_is_skipped():
    good = ('<a class="js-buy-tickets-btn" data-stage="main" '
            'data-datetime="2026-11-26-19-00-00">Купить</a>')
    bad = ('<a class="js-buy-tickets-btn" data-stage="main" '
           'data-datetime="2026-02-30-19-00-00">Купить</a>')
    snap = parse_show_page(f"<html><body><h1>Маскарад</h1>{bad}{good}</body></html>",
                           URL, today=TODAY)
    assert [s.dt for s in snap.sessions] == ["2026-11-26T19:00"]


def test_only_calendar_invalid_datetimes_raises_parse_error():
    bad = ('<a class="js-buy-tickets-btn" data-stage="main" '
           'data-datetime="2026-02-30-19-00-00">Купить</a>')
    with pytest.raises(ParseError):
        parse_show_page(f"<html><body><h1>Маскарад</h1>{bad}</body></html>",
                        URL, today=TODAY)
