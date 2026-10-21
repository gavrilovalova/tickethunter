import json

import httpx

from .models import ParseError, ShowSnapshot
from .parser_vakhtangov import parse_show_page

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
DATA_URL = "https://vakhtangov.ru/ticketland_afisha/data.json"


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, timeout=20,
                        follow_redirects=True)


def fetch_availability(client: httpx.Client | None = None) -> dict:
    """Скачать /ticketland_afisha/data.json — источник правды о билетах.

    Возвращает {stage_uid: {raw_datetime: entry}}. Поле data в ответе —
    JSON-строка; распроданные сеансы в ней отсутствуют.
    """
    c = client or _client()
    r = c.get(DATA_URL)
    r.raise_for_status()
    try:
        data = json.loads(r.json()["data"])
    except (ValueError, KeyError, TypeError) as e:
        raise ParseError(f"data.json изменил структуру: {e}") from None
    if not isinstance(data, dict):
        raise ParseError("data.json изменил структуру: ожидался объект")
    return data


def fetch_show(url: str, client: httpx.Client | None = None,
               availability: dict | None = None) -> ShowSnapshot:
    c = client or _client()
    if availability is None:
        availability = fetch_availability(c)
    r = c.get(url)
    r.raise_for_status()
    return parse_show_page(r.text, url, availability)
