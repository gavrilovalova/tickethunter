import json

import httpx
import pytest

from watcher.fetch import DATA_URL, fetch_availability, fetch_show
from watcher.models import AvailabilityError, Status

SHOW_URL = "https://vakhtangov.ru/show/maskarade/"

INNER = {"main": {"2026-12-26-19-00-00": {
    "has_tickets": True, "sales_on": True,
    "reveal_dt": "2026-07-01 15:00:00", "now": "2026-10-21 13:19:11"}}}

PAGE = ('<html><body><h1>Маскарад</h1><h2>Основная сцена</h2>'
        '<a href="/tickets/buy/?stageuid=main&amp;datetime=2026-12-26-19-00-00" '
        'class="js-buy-tickets-btn" data-stage="main" '
        'data-datetime="2026-12-26-19-00-00">Купить билеты</a>'
        '<a href="/tickets/buy/?stageuid=main&amp;datetime=2026-11-26-19-00-00" '
        'class="js-buy-tickets-btn" data-stage="main" '
        'data-datetime="2026-11-26-19-00-00">Купить билеты</a></body></html>')


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_availability_parses_nested_json():
    def handler(request):
        assert str(request.url) == DATA_URL
        return httpx.Response(200, json={"createdAt": "x", "data": json.dumps(INNER)})
    assert fetch_availability(make_client(handler)) == INNER


@pytest.mark.parametrize("payload", [
    {"data": '"не объект"'},   # не словарь
    {"data": "{}"},            # пустой словарь — почти наверняка глюк генерации
    {"data": "[]"},            # php-стиль пустого объекта
    {"нет": "ключа data"},
    {"data": "не json"},
])
def test_fetch_availability_bad_structure_raises(payload):
    def handler(request):
        return httpx.Response(200, json=payload)
    with pytest.raises(AvailabilityError):
        fetch_availability(make_client(handler))


def test_fetch_show_combines_page_and_availability():
    def handler(request):
        if str(request.url) == DATA_URL:
            return httpx.Response(200, json={"data": json.dumps(INNER)})
        return httpx.Response(200, text=PAGE)
    snap = fetch_show(SHOW_URL, client=make_client(handler))
    by_key = {s.key: s.status for s in snap.sessions}
    # декабрь есть в data.json — в продаже; ноябрь отсутствует — распродан,
    # хотя обе кнопки в HTML выглядят как «Купить билеты»
    assert by_key == {"main|2026-12-26T19:00": Status.AVAILABLE,
                      "main|2026-11-26T19:00": Status.SOLD_OUT}
