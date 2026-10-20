from datetime import date

import httpx

from .models import ShowSnapshot
from .parser_vakhtangov import parse_show_page

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def fetch_show(url: str, client: httpx.Client | None = None) -> ShowSnapshot:
    c = client or httpx.Client(headers={"User-Agent": UA}, timeout=20,
                               follow_redirects=True)
    r = c.get(url)
    r.raise_for_status()
    return parse_show_page(r.text, url, today=date.today())
