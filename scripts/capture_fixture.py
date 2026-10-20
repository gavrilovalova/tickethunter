"""Сохранить живую страницу спектакля в tests/fixtures/.

Запуск: python scripts/capture_fixture.py https://vakhtangov.ru/show/maskarade/ live.html
"""
import sys
from pathlib import Path

import httpx

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

url, name = sys.argv[1], sys.argv[2]
html = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True).text
out = Path("tests/fixtures") / name
out.write_text(html, encoding="utf-8")
print(f"saved {out} ({len(html)} bytes)")
