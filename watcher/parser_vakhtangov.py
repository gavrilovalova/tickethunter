import re
from datetime import date
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .models import ParseError, Session, ShowSnapshot, Status

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
          "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b.*?(\d{1,2}):(\d{2})", re.S)
SOLD_OUT_TEXT = "Билеты закончились"
BUY_PATH = "/tickets/buy/"
STAGE_WORDS = ("сцена", "зал", "арт-кафе", "амфитеатр")


def _slug(s: str) -> str:
    return re.sub(r"[^\wа-яё]+", "-", s.lower()).strip("-") or "stage"


def _infer_year(month: int, day: int, today: date) -> int:
    return today.year + 1 if (month, day) < (today.month, today.day) else today.year


def _preceding_heading(el) -> str:
    h = el.find_previous(["h1", "h2", "h3", "h4", "h5"])
    while h is not None:
        t = h.get_text(strip=True)
        if t and any(w in t.lower() for w in STAGE_WORDS):
            return t
        h = h.find_previous(["h1", "h2", "h3", "h4", "h5"])
    return ""


def parse_show_page(html: str, url: str, today: date) -> ShowSnapshot:
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        raise ParseError(f"не найден заголовок спектакля: {url}")

    sessions: dict[str, Session] = {}

    # доступные сеансы — по ссылкам на покупку
    for a in soup.find_all("a", href=True):
        if BUY_PATH not in a["href"]:
            continue
        buy_url = urljoin(url, a["href"])
        qs = parse_qs(urlparse(buy_url).query)
        try:
            stage = qs["stageuid"][0]
            p = qs["datetime"][0].split("-")          # 2026-12-26-19-00-00
            dt = f"{int(p[0]):04d}-{int(p[1]):02d}-{int(p[2]):02d}T{int(p[3]):02d}:{int(p[4]):02d}"
        except (KeyError, IndexError, ValueError):
            continue                                   # битая/чужая ссылка — пропускаем
        s = Session(stage=stage, stage_title=_preceding_heading(a), dt=dt,
                    status=Status.AVAILABLE, buy_url=buy_url)
        sessions[s.key] = s

    # распроданные сеансы — по тексту «Билеты закончились»
    for text_node in soup.find_all(string=lambda t: t and SOLD_OUT_TEXT in t):
        node = text_node.find_parent()
        m = None
        for _ in range(6):                             # поднимаемся до контейнера с датой
            if node is None:
                break
            m = DATE_RE.search(node.get_text(" ", strip=True))
            if m:
                break
            node = node.find_parent()
        if not m:
            raise ParseError(f"есть «{SOLD_OUT_TEXT}», но не найдена дата рядом: {url}")
        day, month = int(m.group(1)), MONTHS[m.group(2)]
        dt = (f"{_infer_year(month, day, today):04d}-{month:02d}-{day:02d}"
              f"T{int(m.group(3)):02d}:{int(m.group(4)):02d}")
        stage_title = _preceding_heading(text_node.parent)
        dup = any(s.dt == dt and s.stage_title == stage_title
                  and s.status is Status.AVAILABLE for s in sessions.values())
        if not dup:
            s = Session(stage=_slug(stage_title), stage_title=stage_title,
                        dt=dt, status=Status.SOLD_OUT)
            sessions.setdefault(s.key, s)

    if not sessions:
        raise ParseError(f"не найдено ни одного сеанса: {url}")
    return ShowSnapshot(title=title, url=url, sessions=list(sessions.values()))
